"""
Safety Monitor and pure Safety Evaluator for Power Supply Control.

WHY THIS EXISTS
---------------
ADR 0003 and ADR 0004 establish that safety evaluation must be a pure function
of a Snapshot (`evaluate(snapshot, state) -> list[Trip]`) with no thread, no
clock, and no power-supply reference. All trip thresholds and staleness limits
come from settings.safety_limits.

This module provides the pure SafetyEvaluator alongside the legacy SafetyMonitor
(whose pure SafetyEvaluator evaluates Snapshots deterministically).
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, Optional, Callable, List, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from t8_daq_system.rig.commands import RunSettings
from t8_daq_system.rig.snapshot import Snapshot
from t8_daq_system.settings.safety_limits import (
    PRESSURE_INTERLOCK_TORR,
    STALE_ALLOWANCE_S,
    TEMP_OVERRIDE_C,
)

logger = logging.getLogger(__name__)



@dataclass(frozen=True)
class Trip:
    """
    An immutable record of a safety trip condition.

    Carries the machine-readable kind and human-readable reason naming
    the sensor, value, and threshold (ADR 0003).
    """

    kind: str
    reason: str
    sensor: Optional[str] = None
    value: Optional[float] = None
    limit: Optional[float] = None


@dataclass(frozen=True)
class SafetyWarning:
    """
    An immutable record of an impending limit warning.

    Warnings appear when a reading is in the warning band (threshold <= value < limit).
    They are reported for operator visibility and never cause a trip (ADR 0003).
    """

    sensor: str
    value: float
    threshold: float
    message: str


@dataclass
class SafetyState:
    """State preserved between ticks for debounced evaluations."""

    violation_counts: Dict[str, int] = field(default_factory=dict)

    def copy(self) -> SafetyState:
        return SafetyState(violation_counts=self.violation_counts.copy())


class EvaluationResult(list):
    """
    Result of a safety evaluation.

    Subclasses list[Trip] so callers expecting a list of trips can use it directly,
    while also exposing warnings, permissive_ok, and permissive_reason.
    """

    def __init__(
        self,
        trips: List[Trip],
        warnings: List[SafetyWarning],
        permissive_ok: bool,
        permissive_reason: Optional[str] = None,
        state: Optional[SafetyState] = None,
    ):
        super().__init__(trips)
        self.trips: List[Trip] = list(trips)
        self.warnings: List[SafetyWarning] = list(warnings)
        self.permissive_ok: bool = permissive_ok
        self.permissive_reason: Optional[str] = permissive_reason
        self.state: Optional[SafetyState] = state


def evaluate_safety(
    snapshot: Snapshot,
    state: Optional[SafetyState] = None,
    limits: Optional[Mapping[str, float]] = None,
    warning_threshold: float = 0.9,
    debounce_count: int = 1,
    control_tc: str = "TC_1",
    run_settings: Optional[RunSettings] = None,
) -> EvaluationResult:
    """
    Pure safety evaluation function of a Snapshot (ADR 0003, ADR 0004).

    Evaluates:
    - temp_limit: a TC >= configured limit for debounce_count consecutive ticks
    - temp_override: any TC >= TEMP_OVERRIDE_C
    - soft_start_overcurrent: while the program is in Soft start, measured current above
      run_settings.soft_start_cap_a (when soft_start_cap_enabled), ADR 0006
    - run_overcurrent: after handoff, measured current above run_settings.run_cap_a
      (when run_cap_enabled), ADR 0006
    - pressure_high: any enabled gauge > PRESSURE_INTERLOCK_TORR
    - pressure_stale: any enabled gauge with no valid reading for > STALE_ALLOWANCE_S
    - control_tc_stale: while a closed-loop block runs, control TC invalid for > STALE_ALLOWANCE_S
    - permissive: true only when every enabled gauge has a valid reading <= STALE_ALLOWANCE_S old and <= threshold
    - warnings: readings in warning band (limit * warning_threshold <= value < limit), never trips
    """
    if state is None:
        state = SafetyState()
    if limits is None:
        limits = {}

    trips: List[Trip] = []
    warnings: List[SafetyWarning] = []

    # 1. Temperature override: any TC >= TEMP_OVERRIDE_C (instant, not debounced)
    for tc_name, t_val in snapshot.tc_c.items():
        if t_val is not None and t_val >= TEMP_OVERRIDE_C:
            trips.append(
                Trip(
                    kind="temp_override",
                    reason=(
                        f"Temperature override limit exceeded on {tc_name}: "
                        f"{t_val:.1f} °C >= {TEMP_OVERRIDE_C:.1f} °C"
                    ),
                    sensor=tc_name,
                    value=t_val,
                )
            )

    # 2. Configured per-sensor limits & warnings (with debouncing)
    for sensor_name, limit in limits.items():
        val = snapshot.tc_c.get(sensor_name)
        if val is None:
            state.violation_counts[sensor_name] = 0
            continue

        if val >= limit:
            count = state.violation_counts.get(sensor_name, 0) + 1
            state.violation_counts[sensor_name] = count
            if count >= debounce_count:
                trips.append(
                    Trip(
                        kind="temp_limit",
                        reason=(
                            f"Temperature limit exceeded on {sensor_name}: "
                            f"{val:.1f} °C >= {limit:.1f} °C"
                        ),
                        sensor=sensor_name,
                        value=val,
                    )
                )
        else:
            state.violation_counts[sensor_name] = 0
            if val >= limit * warning_threshold:
                warn_thresh = limit * warning_threshold
                warnings.append(
                    SafetyWarning(
                        sensor=sensor_name,
                        value=val,
                        threshold=warn_thresh,
                        message=(
                            f"Temperature warning on {sensor_name}: "
                            f"{val:.1f} °C >= {warn_thresh:.1f} °C (limit {limit:.1f} °C)"
                        ),
                    )
                )

    # 2b. Current caps (ADR 0006): Soft-start cap before handoff, Run cap after
    prog = snapshot.program
    if run_settings is not None and prog.running:
        in_soft_start = prog.phase == "soft_start"
        if in_soft_start:
            cap_enabled = run_settings.soft_start_cap_enabled
            cap_a = run_settings.soft_start_cap_a
            kind = "soft_start_overcurrent"
            label = "Soft-start overcurrent"
            cause = "check for a shorted lead or a voltage step on a cold filament"
        else:
            cap_enabled = run_settings.run_cap_enabled
            cap_a = run_settings.run_cap_a
            kind = "run_overcurrent"
            label = "Run overcurrent"
            cause = "check filament and leads"
        if cap_enabled and snapshot.ps_amps > cap_a:
            ctrl_tc = prog.control_tc or control_tc
            ctrl_c = snapshot.tc_c.get(ctrl_tc)
            ctrl_text = f"{ctrl_c:.1f} °C" if ctrl_c is not None else "no reading"
            trips.append(
                Trip(
                    kind=kind,
                    reason=(
                        f"{label}: measured {snapshot.ps_amps:.1f} A > cap {cap_a:.1f} A "
                        f"(phase {prog.phase}, commanded {snapshot.commanded_volts:.3f} V, "
                        f"control TC {ctrl_tc} {ctrl_text}); {cause}"
                    ),
                    sensor="PS_Current",
                    value=snapshot.ps_amps,
                    limit=cap_a,
                )
            )

    # 3. Pressure trips & Permissive calculation (ADR 0004)
    permissive_ok = True
    permissive_reason: Optional[str] = None

    if not snapshot.pressure_torr:
        permissive_ok = False
        permissive_reason = "No pressure gauges configured or reported"
    else:
        for gauge, p_val in snapshot.pressure_torr.items():
            age = snapshot.source_age_s.get(
                gauge, float("inf") if p_val is None else 0.0
            )

            # High pressure trip (> 1e-4 Torr)
            if p_val is not None and p_val > PRESSURE_INTERLOCK_TORR:
                trips.append(
                    Trip(
                        kind="pressure_high",
                        reason=(
                            f"Pressure high on {gauge}: "
                            f"{p_val:.2e} Torr > {PRESSURE_INTERLOCK_TORR:.2e} Torr"
                        ),
                        sensor=gauge,
                        value=p_val,
                    )
                )
                if permissive_ok:
                    permissive_ok = False
                    permissive_reason = (
                        f"Pressure high on {gauge}: "
                        f"{p_val:.2e} Torr > {PRESSURE_INTERLOCK_TORR:.2e} Torr"
                    )

            # Stale pressure trip (> 5.0 s)
            if age > STALE_ALLOWANCE_S:
                trips.append(
                    Trip(
                        kind="pressure_stale",
                        reason=(
                            f"Pressure reading stale on {gauge}: "
                            f"{age:.1f} s > {STALE_ALLOWANCE_S:.1f} s"
                        ),
                        sensor=gauge,
                        value=age,
                    )
                )
                if permissive_ok:
                    permissive_ok = False
                    permissive_reason = (
                        f"Pressure reading stale on {gauge}: "
                        f"{age:.1f} s > {STALE_ALLOWANCE_S:.1f} s"
                    )

            # Permissive also requires valid reading right now (even if age <= 5 s)
            if p_val is None and permissive_ok:
                permissive_ok = False
                permissive_reason = f"Pressure reading invalid on {gauge}"

    # 4. Control TC stale: only while a closed-loop block runs (ADR 0003)
    active_prog = snapshot.program
    is_closed_loop = (
        active_prog.running
        and active_prog.block_type in ("temp_ramp", "stable_hold")
    )
    if is_closed_loop:
        c_tc = getattr(active_prog, "control_tc", None) or control_tc or "TC_1"
        tc_val = snapshot.tc_c.get(c_tc)
        tc_age = snapshot.source_age_s.get(
            c_tc, float("inf") if tc_val is None else 0.0
        )
        if tc_age > STALE_ALLOWANCE_S:
            trips.append(
                Trip(
                    kind="control_tc_stale",
                    reason=(
                        f"Control thermocouple stale on {c_tc}: "
                        f"{tc_age:.1f} s > {STALE_ALLOWANCE_S:.1f} s"
                    ),
                    sensor=c_tc,
                    value=tc_age,
                )
            )

    return EvaluationResult(
        trips=trips,
        warnings=warnings,
        permissive_ok=permissive_ok,
        permissive_reason=permissive_reason,
        state=state,
    )


evaluate = evaluate_safety


class SafetyEvaluator:
    """
    Pure safety evaluator with per-sensor limits, warning threshold, and debounce semantics.

    WHY THIS EXISTS
    ---------------
    Previously, safety evaluation was entangled with an ad-hoc safety thread and
    direct power-supply manipulation. Safety decisions are now a pure function of a
    Snapshot without threads, clocks, or callbacks, testable with 100% deterministic
    boundaries (ADR 0002, 0003, 0004).
    """

    def __init__(
        self,
        limits: Optional[Mapping[str, float]] = None,
        warning_threshold: float = 0.9,
        debounce_count: int = 1,
        control_tc: str = "TC_1",
    ):
        self._limits: Dict[str, float] = dict(limits) if limits is not None else {}
        self._warning_threshold: float = warning_threshold
        self._debounce_count: int = debounce_count
        self._control_tc: str = control_tc
        self._state = SafetyState()

    @property
    def warning_threshold(self) -> float:
        return self._warning_threshold

    @property
    def debounce_count(self) -> int:
        return self._debounce_count

    @property
    def control_tc(self) -> str:
        return self._control_tc

    def set_temperature_limit(self, sensor_name: str, max_temp: float) -> None:
        if max_temp <= 0:
            raise ValueError(f"Temperature limit must be positive: {max_temp}")
        self._limits[sensor_name] = max_temp
        self._state.violation_counts[sensor_name] = 0

    def remove_temperature_limit(self, sensor_name: str) -> None:
        self._limits.pop(sensor_name, None)
        self._state.violation_counts.pop(sensor_name, None)

    def clear_all_limits(self) -> None:
        self._limits.clear()
        self._state.violation_counts.clear()

    def get_temperature_limit(self, sensor_name: str) -> Optional[float]:
        return self._limits.get(sensor_name)

    def get_all_limits(self) -> Dict[str, float]:
        return self._limits.copy()

    def set_warning_threshold(self, threshold: float) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError("Warning threshold must be between 0 and 1")
        self._warning_threshold = threshold

    def set_debounce_count(self, count: int) -> None:
        if count < 1:
            raise ValueError("Debounce count must be at least 1")
        self._debounce_count = count

    def set_control_tc(self, tc_name: str) -> None:
        self._control_tc = tc_name

    def evaluate(
        self,
        snapshot: Snapshot,
        state: Optional[SafetyState] = None,
        run_settings: Optional[RunSettings] = None,
    ) -> EvaluationResult:
        target_state = state if state is not None else self._state
        return evaluate_safety(
            snapshot=snapshot,
            state=target_state,
            limits=self._limits,
            warning_threshold=self._warning_threshold,
            debounce_count=self._debounce_count,
            control_tc=self._control_tc,
            run_settings=run_settings,
        )


class SafetyStatus(Enum):
    """Safety monitor status."""
    OK = "ok"
    WARNING = "warning"
    LIMIT_EXCEEDED = "limit_exceeded"
    SHUTDOWN_TRIGGERED = "shutdown_triggered"
    ERROR = "error"


@dataclass
class SafetyEvent:
    """Record of a safety event."""
    timestamp: datetime
    event_type: str
    sensor_name: str
    value: float
    limit: float
    message: str


class SafetyMonitor:
    """
    Monitors sensor readings and enforces safety limits.

    Features:
    - Temperature monitoring against configurable limits
    - 2200C emergency override with instant cutoff
    - Restart lockout until temperature drops below 2150C
    - Callbacks for warning, limit exceeded, shutdown events
    """

    # Temperature override settings
    TEMP_OVERRIDE_LIMIT = 2200.0      # Emergency override temperature (C)
    TEMP_RESTART_THRESHOLD = 2150.0   # Must be below this to restart (C)

    def __init__(self, power_supply_controller=None, auto_shutoff: bool = True):
        self.power_supply = power_supply_controller
        self.auto_shutoff = auto_shutoff

        # Temperature limits: {sensor_name: max_temperature}
        self._temperature_limits: Dict[str, float] = {}

        # Warning thresholds (percentage of limit)
        self._warning_threshold: float = 0.9

        # Current status
        self._status = SafetyStatus.OK
        self._last_event: Optional[SafetyEvent] = None
        self._event_history: List[SafetyEvent] = []
        self._max_history: int = 100

        # Watchdog sensor
        self._watchdog_sensor: Optional[str] = None

        # Callbacks
        self._on_warning: Optional[Callable[[str, float, float], None]] = None
        self._on_limit_exceeded: Optional[Callable[[str, float, float], None]] = None
        self._on_shutdown: Optional[Callable[[SafetyEvent], None]] = None

        # Thread safety
        self._lock = threading.Lock()

        # Enabled state
        self._enabled = True

        # Consecutive violation tracking (for debouncing)
        self._violation_counts: Dict[str, int] = {}
        self._required_violations: int = 1

        # Temperature override restart lockout
        self._restart_locked = False
        self._max_tc_reading = 0.0  # Track max TC reading for restart logic

    @property
    def status(self) -> SafetyStatus:
        with self._lock:
            return self._status

    @property
    def is_safe(self) -> bool:
        return self.status in [SafetyStatus.OK, SafetyStatus.WARNING]

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value

    @property
    def is_restart_locked(self) -> bool:
        with self._lock:
            return self._restart_locked

    def set_power_supply(self, power_supply_controller) -> None:
        self.power_supply = power_supply_controller

    def set_temperature_limit(self, sensor_name: str, max_temp: float) -> None:
        if max_temp <= 0:
            raise ValueError(f"Temperature limit must be positive: {max_temp}")
        with self._lock:
            self._temperature_limits[sensor_name] = max_temp
            self._violation_counts[sensor_name] = 0

    def remove_temperature_limit(self, sensor_name: str) -> None:
        with self._lock:
            self._temperature_limits.pop(sensor_name, None)
            self._violation_counts.pop(sensor_name, None)

    def clear_all_limits(self) -> None:
        with self._lock:
            self._temperature_limits.clear()
            self._violation_counts.clear()

    def get_temperature_limit(self, sensor_name: str) -> Optional[float]:
        with self._lock:
            return self._temperature_limits.get(sensor_name)

    def get_all_limits(self) -> Dict[str, float]:
        with self._lock:
            return self._temperature_limits.copy()

    def set_watchdog_sensor(self, sensor_name: str) -> None:
        with self._lock:
            self._watchdog_sensor = sensor_name

    def set_warning_threshold(self, threshold: float) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError("Warning threshold must be between 0 and 1")
        with self._lock:
            self._warning_threshold = threshold

    def set_debounce_count(self, count: int) -> None:
        if count < 1:
            raise ValueError("Debounce count must be at least 1")
        with self._lock:
            self._required_violations = count

    def check_limits(self, sensor_readings: Dict[str, float]) -> bool:
        """
        Check all sensor readings against limits. Also checks for
        2200C temperature override across ALL thermocouple readings.

        Returns:
            True if all readings are within limits (safe)
            False if any limit was exceeded (shutdown triggered)
        """
        if not self.enabled:
            return True

        # First: check 2200C override on ALL thermocouple readings
        # Note: sensor_readings here contains only TC readings, so no name filter needed
        max_tc = 0.0
        for sensor_name, value in sensor_readings.items():
            if value is None or value == -9999:
                continue
            if value > max_tc:
                max_tc = value

        with self._lock:
            self._max_tc_reading = max_tc

        # Check if temperature override should trigger (instant cutoff)
        if max_tc >= self.TEMP_OVERRIDE_LIMIT:
            # Find the offending sensor
            offending_sensor = None
            for sensor_name, value in sensor_readings.items():
                if value is not None and value >= self.TEMP_OVERRIDE_LIMIT:
                    offending_sensor = sensor_name
                    break

            self._trigger_shutdown(
                offending_sensor or "TC_unknown",
                max_tc,
                self.TEMP_OVERRIDE_LIMIT
            )
            return False

        # Check restart lockout: if temp drops below threshold, unlock
        if self._restart_locked and max_tc < self.TEMP_RESTART_THRESHOLD:
            with self._lock:
                self._restart_locked = False
            # Don't automatically reset status - user must still acknowledge

        # Standard limit checks
        with self._lock:
            limits = self._temperature_limits.copy()
            warning_threshold = self._warning_threshold
            watchdog = self._watchdog_sensor
            # NOTE: unused — possible bug, see workflow-setup ticket 02
            del watchdog

        warnings_found = []
        violations_found = []

        for sensor_name, limit in limits.items():
            if sensor_name not in sensor_readings:
                continue

            value = sensor_readings[sensor_name]
            if value is None or value == -9999:
                continue

            if value >= limit:
                violations_found.append((sensor_name, value, limit))
                continue

            if value >= limit * warning_threshold:
                warnings_found.append((sensor_name, value, limit))

            with self._lock:
                self._violation_counts[sensor_name] = 0

        # Process warnings
        for sensor_name, value, limit in warnings_found:
            self._handle_warning(sensor_name, value, limit)

        # Process violations
        for sensor_name, value, limit in violations_found:
            should_shutdown = self._handle_violation(sensor_name, value, limit)
            if should_shutdown:
                self._trigger_shutdown(sensor_name, value, limit)
                return False

        # Update status if no violations
        with self._lock:
            if warnings_found:
                self._status = SafetyStatus.WARNING
            elif self._status != SafetyStatus.SHUTDOWN_TRIGGERED:
                self._status = SafetyStatus.OK

        return True

    def _handle_warning(self, sensor_name: str, value: float, limit: float) -> None:
        with self._lock:
            self._status = SafetyStatus.WARNING

        if self._on_warning:
            try:
                self._on_warning(sensor_name, value, limit)
            except Exception as e:
                logger.error("Safety warning callback failed: %s", e)
                raise

    def _handle_violation(self, sensor_name: str, value: float, limit: float) -> bool:
        with self._lock:
            if sensor_name == self._watchdog_sensor:
                self._violation_counts[sensor_name] = self._required_violations
            else:
                self._violation_counts[sensor_name] = \
                    self._violation_counts.get(sensor_name, 0) + 1

            violation_count = self._violation_counts[sensor_name]
            required = self._required_violations

        if violation_count >= required:
            if self._on_limit_exceeded:
                try:
                    self._on_limit_exceeded(sensor_name, value, limit)
                except Exception as e:
                    logger.error("Safety limit exceeded callback failed: %s", e)
                    raise
            return True

        return False

    def _trigger_shutdown(self, sensor_name: str, value: float, limit: float) -> None:
        """Trigger emergency shutdown (immediate)."""
        event = SafetyEvent(
            timestamp=datetime.now(),
            event_type="limit_exceeded",
            sensor_name=sensor_name,
            value=value,
            limit=limit,
            message=f"Temperature limit exceeded on {sensor_name}: "
                   f"{value:.1f}\u00b0C >= {limit:.1f}\u00b0C"
        )

        with self._lock:
            self._last_event = event
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)
            self._status = SafetyStatus.LIMIT_EXCEEDED

        if self.auto_shutoff:
            with self._lock:
                self._status = SafetyStatus.SHUTDOWN_TRIGGERED
            if hasattr(self, '_on_shutdown') and self._on_shutdown:
                try:
                    self._on_shutdown(event)
                except Exception as e:
                    logger.error("Safety shutdown callback failed: %s", e)
                    raise

        with self._lock:
            self._status = SafetyStatus.SHUTDOWN_TRIGGERED

        if self._on_shutdown and not self.auto_shutoff:
            try:
                self._on_shutdown(event)
            except Exception as e:
                logger.error("Safety shutdown callback failed: %s", e)
                raise


    def emergency_shutdown(self) -> bool:
        """Immediately transition to shutdown triggered state."""
        if self.power_supply is None:
            return False

        event = SafetyEvent(
            timestamp=datetime.now(),
            event_type="emergency_shutdown",
            sensor_name="",
            value=0.0,
            limit=0.0,
            message="Emergency shutdown initiated"
        )

        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)
            self._status = SafetyStatus.SHUTDOWN_TRIGGERED
        return True

    def can_restart(self) -> bool:
        """Check if the power supply can be restarted after emergency shutdown.

        Returns True if:
        - No restart lockout is active, OR
        - Temperature has dropped below TEMP_RESTART_THRESHOLD (2150C)
        """
        with self._lock:
            if not self._restart_locked:
                return True
            # Check if max TC reading has dropped enough
            return self._max_tc_reading < self.TEMP_RESTART_THRESHOLD

    def reset(self) -> None:
        """Reset the safety monitor after a shutdown."""
        with self._lock:
            self._status = SafetyStatus.OK
            self._violation_counts = {k: 0 for k in self._violation_counts}
            # Only unlock restart if temperature is below threshold
            if self._max_tc_reading < self.TEMP_RESTART_THRESHOLD:
                self._restart_locked = False

    def get_last_event(self) -> Optional[SafetyEvent]:
        with self._lock:
            return self._last_event

    def get_event_history(self) -> List[SafetyEvent]:
        with self._lock:
            return self._event_history.copy()

    def clear_event_history(self) -> None:
        with self._lock:
            self._event_history.clear()
            self._last_event = None

    # Callback registration methods
    def on_warning(self, callback: Callable[[str, float, float], None]) -> None:
        self._on_warning = callback

    def on_limit_exceeded(self, callback: Callable[[str, float, float], None]) -> None:
        self._on_limit_exceeded = callback

    def on_shutdown(self, callback: Callable[[SafetyEvent], None]) -> None:
        self._on_shutdown = callback

    def get_status_report(self) -> Dict:
        with self._lock:
            return {
                'status': self._status.value,
                'enabled': self._enabled,
                'auto_shutoff': self.auto_shutoff,
                'power_supply_connected': self.power_supply is not None,
                'temperature_limits': self._temperature_limits.copy(),
                'watchdog_sensor': self._watchdog_sensor,
                'warning_threshold': self._warning_threshold,
                'violation_counts': self._violation_counts.copy(),
                'last_event': self._last_event,
                'event_count': len(self._event_history),
                'restart_locked': self._restart_locked,
                'max_tc_reading': self._max_tc_reading
            }

    def configure_from_dict(self, config: Dict) -> None:
        self.enabled = config.get('enabled', True)
        self.auto_shutoff = config.get('auto_shutoff', True)

        if 'warning_threshold' in config:
            self.set_warning_threshold(config['warning_threshold'])

        if 'watchdog_sensor' in config:
            self.set_watchdog_sensor(config['watchdog_sensor'])

        if 'debounce_count' in config:
            self.set_debounce_count(config['debounce_count'])

        sensor_limits = config.get('sensor_limits', {})
        default_limit = config.get('max_temperature')

        for sensor_name, limit in sensor_limits.items():
            self.set_temperature_limit(sensor_name, limit)

        if default_limit and self._watchdog_sensor:
            if self._watchdog_sensor not in self._temperature_limits:
                self.set_temperature_limit(self._watchdog_sensor, default_limit)

    def evaluate(
        self, snapshot: Snapshot, state: Optional[SafetyState] = None
    ) -> EvaluationResult:
        """
        Pure safety evaluation of a Snapshot using this monitor's configured limits.

        WHY THIS EXISTS
        ---------------
        Transitional bridge (Ticket 06) allowing consumers holding a SafetyMonitor
        instance to evaluate Snapshots purely without touching the legacy monitor
        thread or power-supply handle.
        """
        with self._lock:
            limits = self._temperature_limits.copy()
            warning_threshold = self._warning_threshold
            debounce_count = self._required_violations
            watchdog = self._watchdog_sensor

        control_tc = watchdog or "TC_1"
        target_state = state if state is not None else SafetyState(self._violation_counts)
        res = evaluate_safety(
            snapshot=snapshot,
            state=target_state,
            limits=limits,
            warning_threshold=warning_threshold,
            debounce_count=debounce_count,
            control_tc=control_tc,
        )
        if state is None:
            with self._lock:
                self._violation_counts = target_state.violation_counts
        return res

    def __repr__(self) -> str:
        return (f"SafetyMonitor(status={self.status.value}, "
                f"limits={len(self._temperature_limits)}, "
                f"enabled={self.enabled})")

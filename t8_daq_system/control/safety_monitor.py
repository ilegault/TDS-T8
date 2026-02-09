"""
Safety Monitor for Power Supply Control.

Monitors temperature readings and enforces safety limits.
Triggers emergency controlled ramp-down when limits are exceeded.
Includes 2200C temperature override with gradual power-down.
"""

import threading
import time
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SafetyStatus(Enum):
    """Safety monitor status."""
    OK = "ok"
    WARNING = "warning"
    LIMIT_EXCEEDED = "limit_exceeded"
    SHUTDOWN_TRIGGERED = "shutdown_triggered"
    RAMPDOWN_ACTIVE = "rampdown_active"
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
    - 2200C emergency override with controlled ramp-down (not instant shutoff)
    - Ramp-down over configurable duration (default 5 minutes)
    - Restart lockout until temperature drops below 2150C
    - Callbacks for warning, limit exceeded, shutdown events
    """

    # Temperature override settings
    TEMP_OVERRIDE_LIMIT = 2200.0      # Emergency override temperature (C)
    TEMP_RESTART_THRESHOLD = 2150.0   # Must be below this to restart (C)
    RAMPDOWN_DURATION_SEC = 300.0     # 5 minutes controlled ramp-down

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
        self._on_rampdown_start: Optional[Callable[[str], None]] = None

        # Thread safety
        self._lock = threading.Lock()

        # Enabled state
        self._enabled = True

        # Consecutive violation tracking (for debouncing)
        self._violation_counts: Dict[str, int] = {}
        self._required_violations: int = 1

        # Controlled ramp-down state
        self._rampdown_active = False
        self._rampdown_thread: Optional[threading.Thread] = None
        self._rampdown_stop_event = threading.Event()
        self._rampdown_start_voltage = 0.0
        self._rampdown_start_time: Optional[float] = None

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
    def is_rampdown_active(self) -> bool:
        with self._lock:
            return self._rampdown_active

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
        max_tc = 0.0
        for sensor_name, value in sensor_readings.items():
            if not sensor_name.startswith('TC_'):
                continue
            if value is None or value == -9999:
                continue
            if value > max_tc:
                max_tc = value

        with self._lock:
            self._max_tc_reading = max_tc

        # Check if temperature override should trigger
        if max_tc >= self.TEMP_OVERRIDE_LIMIT and not self._rampdown_active:
            # Find the offending sensor
            offending_sensor = None
            for sensor_name, value in sensor_readings.items():
                if sensor_name.startswith('TC_') and value is not None and value >= self.TEMP_OVERRIDE_LIMIT:
                    offending_sensor = sensor_name
                    break

            self._trigger_controlled_rampdown(
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
            if self._rampdown_active:
                self._status = SafetyStatus.RAMPDOWN_ACTIVE
            elif warnings_found:
                self._status = SafetyStatus.WARNING
            elif self._status not in [SafetyStatus.SHUTDOWN_TRIGGERED, SafetyStatus.RAMPDOWN_ACTIVE]:
                self._status = SafetyStatus.OK

        return True

    def _handle_warning(self, sensor_name: str, value: float, limit: float) -> None:
        with self._lock:
            self._status = SafetyStatus.WARNING

        if self._on_warning:
            try:
                self._on_warning(sensor_name, value, limit)
            except Exception:
                pass

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
                except Exception:
                    pass
            return True

        return False

    def _trigger_controlled_rampdown(self, sensor_name: str, value: float, limit: float) -> None:
        """Trigger a controlled ramp-down of power supply output over RAMPDOWN_DURATION_SEC."""
        event = SafetyEvent(
            timestamp=datetime.now(),
            event_type="temperature_override_rampdown",
            sensor_name=sensor_name,
            value=value,
            limit=limit,
            message=f"TEMPERATURE LIMIT EXCEEDED - EMERGENCY SHUTDOWN INITIATED. "
                   f"{sensor_name}: {value:.1f}\u00b0C >= {limit:.1f}\u00b0C. "
                   f"Controlled ramp-down over {self.RAMPDOWN_DURATION_SEC/60:.0f} minutes."
        )

        with self._lock:
            self._last_event = event
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)
            self._status = SafetyStatus.RAMPDOWN_ACTIVE
            self._rampdown_active = True
            self._restart_locked = True

        # Get current voltage for ramp-down starting point
        start_voltage = 0.0
        if self.power_supply:
            try:
                start_voltage = self.power_supply.get_voltage()
            except Exception:
                try:
                    start_voltage = self.power_supply.get_voltage_setpoint()
                except Exception:
                    start_voltage = 0.0

        self._rampdown_start_voltage = start_voltage
        self._rampdown_start_time = time.time()
        self._rampdown_stop_event.clear()

        # Start ramp-down thread
        self._rampdown_thread = threading.Thread(
            target=self._rampdown_loop, daemon=True
        )
        self._rampdown_thread.start()

        # Notify callbacks
        if self._on_rampdown_start:
            try:
                self._on_rampdown_start(event.message)
            except Exception:
                pass

        if self._on_shutdown:
            try:
                self._on_shutdown(event)
            except Exception:
                pass

    def _rampdown_loop(self) -> None:
        """Gradually reduce voltage to 0 over RAMPDOWN_DURATION_SEC."""
        if not self.power_supply:
            print("WARNING: No power supply connected for controlled ramp-down")
            return

        start_v = self._rampdown_start_voltage
        duration = self.RAMPDOWN_DURATION_SEC
        interval = 1.0  # Update every 1 second

        print(f"SAFETY: Starting controlled ramp-down from {start_v:.2f}V over {duration:.0f}s")

        while not self._rampdown_stop_event.is_set():
            elapsed = time.time() - self._rampdown_start_time
            if elapsed >= duration:
                break

            # Linear ramp-down
            fraction_remaining = max(0.0, 1.0 - (elapsed / duration))
            target_voltage = start_v * fraction_remaining

            try:
                self.power_supply.set_voltage(target_voltage)
            except Exception as e:
                print(f"SAFETY: Error during ramp-down: {e}")

            time.sleep(interval)

        # Final: set voltage to 0 and turn off output
        try:
            self.power_supply.set_voltage(0.0)
            self.power_supply.set_current(0.0)
            self.power_supply.output_off()
        except Exception as e:
            print(f"SAFETY: Error during final shutdown: {e}")

        with self._lock:
            self._rampdown_active = False
            self._status = SafetyStatus.SHUTDOWN_TRIGGERED

        print("SAFETY: Controlled ramp-down complete. Output off.")

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
            self.emergency_shutdown()

        with self._lock:
            self._status = SafetyStatus.SHUTDOWN_TRIGGERED

        if self._on_shutdown:
            try:
                self._on_shutdown(event)
            except Exception:
                pass

    def emergency_shutdown(self) -> bool:
        """Immediately shut off the power supply output."""
        # Stop any active ramp-down first
        if self._rampdown_active:
            self._rampdown_stop_event.set()

        if self.power_supply is None:
            print("WARNING: No power supply connected for emergency shutdown")
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

        try:
            success = self.power_supply.emergency_shutdown()
            if success:
                print("SAFETY: Emergency shutdown successful")
                return True
            else:
                print("SAFETY: Emergency shutdown may have failed - verify manually!")
                return False
        except Exception as e:
            print(f"SAFETY: Emergency shutdown error: {e}")
            try:
                self.power_supply.output_off()
                return True
            except Exception:
                pass
            return False

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
        # Stop any active ramp-down
        if self._rampdown_active:
            self._rampdown_stop_event.set()
            if self._rampdown_thread and self._rampdown_thread.is_alive():
                self._rampdown_thread.join(timeout=2.0)

        with self._lock:
            self._status = SafetyStatus.OK
            self._violation_counts = {k: 0 for k in self._violation_counts}
            self._rampdown_active = False
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

    def get_rampdown_progress(self) -> float:
        """Get the ramp-down progress as a percentage (0-100)."""
        if not self._rampdown_active or self._rampdown_start_time is None:
            return 0.0
        elapsed = time.time() - self._rampdown_start_time
        return min(100.0, (elapsed / self.RAMPDOWN_DURATION_SEC) * 100.0)

    # Callback registration methods
    def on_warning(self, callback: Callable[[str, float, float], None]) -> None:
        self._on_warning = callback

    def on_limit_exceeded(self, callback: Callable[[str, float, float], None]) -> None:
        self._on_limit_exceeded = callback

    def on_shutdown(self, callback: Callable[[SafetyEvent], None]) -> None:
        self._on_shutdown = callback

    def on_rampdown_start(self, callback: Callable[[str], None]) -> None:
        """Register callback for when controlled ramp-down begins.

        Args:
            callback: Function called with warning message string
        """
        self._on_rampdown_start = callback

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
                'rampdown_active': self._rampdown_active,
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

    def __repr__(self) -> str:
        return (f"SafetyMonitor(status={self.status.value}, "
                f"limits={len(self._temperature_limits)}, "
                f"enabled={self.enabled})")

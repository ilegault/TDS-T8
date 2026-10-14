"""
Heater output arbitration and latching module (Ticket 07 / ADR 0003).

WHY THIS EXISTS
---------------
Previously, five independent code paths called set_voltage with no priority:
ProgramExecutor, the safety thread, MainWindow._handle_safety_shutdown,
MainWindow._on_pressure_interlock, and manual nudge. Over-temperature shutdowns
competed with the executor, pressure interlocks turned the supply off while the
executor was still writing voltages, and a lost thermocouple left DAC0 at its last
value with nothing regulating it.

ADR 0003 establishes that HeaterOutput is the single arbiter of heater commands:
1. Priority order: Safety > Operator > Program.
2. Every trip is an instant cutoff (0 V, output disabled) that latches.
3. DAC1 is never touched (CV-only invariant).
4. Trips latch until an explicit ResetTrip is accepted, which is refused while the
   tripping condition persists.
5. An Operator request during a running Program stops the Program first.
6. A nudge never enables output (FIX-3).
7. Current caps (ADR 0006) arrive as trips from the Safety Evaluator; reset is
   refused while measured current is still above the tripped cap.
8. Output voltage is clamped to [0.0, DAC0_MAX_V].
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from t8_daq_system.control.safety_monitor import Trip
from t8_daq_system.rig.commands import (
    Nudge,
    ResetTrip,
    SetOutput,
    SetVoltage,
    StartProgram,
    StopProgram,
)
from t8_daq_system.rig.snapshot import Snapshot
from t8_daq_system.settings.safety_limits import (
    DAC0_MAX_V,
    PRESSURE_INTERLOCK_TORR,
    STALE_ALLOWANCE_S,
    TEMP_OVERRIDE_RESET_C,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeaterCommand:
    """
    Arbitrated heater command emitted by HeaterOutput.

    Supports 2-tuple unpacking (output_enabled, volts) while also carrying
    metadata (stop_program, refusal_reason, trip_kind, trip_reason).
    Enforces CV-only by exposing no fields that could command DAC1.
    """

    output_enabled: bool
    volts: float
    stop_program: bool = False
    refusal_reason: Optional[str] = None
    trip_kind: Optional[str] = None
    trip_reason: Optional[str] = None

    def __iter__(self):
        """Allow unpacking: output_enabled, volts = command."""
        return iter((self.output_enabled, self.volts))

    def __getitem__(self, index: int):
        return (self.output_enabled, self.volts)[index]

    def __len__(self) -> int:
        return 2


@dataclass(frozen=True)
class ProgramHeaterRequest:
    """Voltage setpoint request produced by a running Program."""

    volts: float


ProgramRequest = ProgramHeaterRequest


class HeaterOutput:
    """
    Single arbiter of what the heater does (ADR 0003).

    Pure logic module with no threads, no I/O, and no clock.
    Arbitrates Safety > Operator > Program, holds the safety trip latch,
    and enforces CV-only invariants.
    """

    def __init__(self) -> None:
        self._latched: bool = False
        self._active_trip_kind: Optional[str] = None
        self._active_trip_reason: Optional[str] = None
        self._active_trip_sensor: Optional[str] = None
        self._active_trip_value: Optional[float] = None
        self._active_trip_limit: Optional[float] = None
        self._last_commanded_volts: Optional[float] = None
        self._last_output_enabled: Optional[bool] = None

    @property
    def is_latched(self) -> bool:
        """True if the heater output is currently locked out by a safety trip latch."""
        return self._latched

    @property
    def active_trip_kind(self) -> Optional[str]:
        """Machine-readable kind of the active latching trip, if latched."""
        return self._active_trip_kind

    @property
    def active_trip_reason(self) -> Optional[str]:
        """Human-readable reason of the active latching trip, if latched."""
        return self._active_trip_reason

    @property
    def last_commanded_volts(self) -> float:
        """The last commanded voltage setpoint."""
        return 0.0 if self._last_commanded_volts is None else self._last_commanded_volts

    @property
    def last_output_enabled(self) -> bool:
        """The last commanded output enable state."""
        return False if self._last_output_enabled is None else self._last_output_enabled

    def reset(self, snapshot: Snapshot) -> tuple[bool, Optional[str]]:
        """
        Attempt to clear the safety trip latch against the given Snapshot.

        Returns (success: bool, refusal_reason: Optional[str]).
        Refused if the tripping condition is still present.
        """
        if not self._latched:
            return True, None

        refusal = self._check_trip_persisting(snapshot)
        if refusal is not None:
            logger.warning("Trip reset refused: %s", refusal)
            return False, refusal

        logger.info("Trip reset accepted (previous trip: %s)", self._active_trip_kind)
        self._latched = False
        self._active_trip_kind = None
        self._active_trip_reason = None
        self._active_trip_sensor = None
        self._active_trip_value = None
        self._active_trip_limit = None
        return True, None

    def resolve(self, requests: Any, snapshot: Snapshot) -> HeaterCommand:
        """
        Arbitrate incoming requests and trips against the current Snapshot.

        Priority order: Safety > Operator > Program.
        Returns HeaterCommand (unpacks as (output_enabled, volts)).
        """
        req_list = self._flatten_requests(requests)

        # Categorize requests
        trips = [r for r in req_list if isinstance(r, Trip)]
        operator_cmds = [
            r
            for r in req_list
            if isinstance(r, (ResetTrip, SetOutput, SetVoltage, Nudge))
        ]
        program_requests = [
            r
            for r in req_list
            if isinstance(r, (StartProgram, StopProgram, ProgramHeaterRequest))
        ]

        # ---------------------------------------------------------------------
        # 1. Safety Priority: Any trip this tick -> instant cutoff and latch
        # ---------------------------------------------------------------------
        if trips:
            first_trip = trips[0]
            self._latched = True
            self._active_trip_kind = first_trip.kind
            self._active_trip_reason = first_trip.reason
            self._active_trip_sensor = first_trip.sensor
            self._active_trip_value = first_trip.value
            self._active_trip_limit = (
                first_trip.limit
                if first_trip.limit is not None
                else self._extract_limit_from_reason(first_trip.reason)
            )
            self._last_commanded_volts = 0.0
            self._last_output_enabled = False

            refusal_reason = None
            if any(isinstance(r, ResetTrip) for r in req_list):
                refusal_reason = (
                    f"Reset refused: active trip condition persisting "
                    f"({first_trip.kind}: {first_trip.reason})"
                )

            stop_prog = snapshot.program.running if snapshot.program else False
            return HeaterCommand(
                output_enabled=False,
                volts=0.0,
                stop_program=stop_prog,
                refusal_reason=refusal_reason,
                trip_kind=self._active_trip_kind,
                trip_reason=self._active_trip_reason,
            )

        # ---------------------------------------------------------------------
        # 2. Latched state: handle ResetTrip or ignore all requests
        # ---------------------------------------------------------------------
        if self._latched:
            reset_reqs = [r for r in operator_cmds if isinstance(r, ResetTrip)]
            if reset_reqs:
                success, refusal = self.reset(snapshot)
                if not success:
                    # Still latched
                    return HeaterCommand(
                        output_enabled=False,
                        volts=0.0,
                        refusal_reason=refusal,
                        trip_kind=self._active_trip_kind,
                        trip_reason=self._active_trip_reason,
                    )
                # Reset succeeded: output remains off until explicitly commanded on
            else:
                # Still latched, requests ignored
                return HeaterCommand(
                    output_enabled=False,
                    volts=0.0,
                    trip_kind=self._active_trip_kind,
                    trip_reason=self._active_trip_reason,
                )

        # ---------------------------------------------------------------------
        # 3. Not latched: Arbitrate Operator vs Program
        # ---------------------------------------------------------------------
        current_enabled = (
            snapshot.output_enabled
            if self._last_output_enabled is None
            else self._last_output_enabled
        )
        current_volts = (
            snapshot.commanded_volts
            if self._last_commanded_volts is None
            else self._last_commanded_volts
        )
        stop_program = False
        refusal_reason = None

        # Filter out ResetTrip as it was already handled
        operator_action_cmds = [r for r in operator_cmds if not isinstance(r, ResetTrip)]

        if operator_action_cmds:
            # Rule 4: Operator request while Program runs stops Program first
            if snapshot.program and snapshot.program.running:
                stop_program = True

            for cmd in operator_action_cmds:
                if isinstance(cmd, SetOutput):
                    if cmd.enabled:
                        # Rule 3: Output enabled only when permissive_ok
                        if not snapshot.permissive_ok:
                            current_enabled = False
                            refusal_reason = (
                                f"SetOutput(True) refused: "
                                f"{snapshot.permissive_reason or 'permissive not OK'}"
                            )
                        else:
                            current_enabled = True
                    else:
                        current_enabled = False
                        current_volts = 0.0

                elif isinstance(cmd, SetVoltage):
                    current_volts = cmd.volts

                elif isinstance(cmd, Nudge):
                    # Rule 3 (FIX-3): A nudge never enables output
                    if not current_enabled:
                        # Output is off: nudge has no effect on enable state or voltage
                        pass
                    else:
                        step = getattr(cmd, "step", 0.05)
                        if cmd.direction in ("up", "+", "+1", 1):
                            current_volts += step
                        else:
                            current_volts -= step

        elif program_requests:
            for req in program_requests:
                if isinstance(req, StartProgram):
                    # Rule 3: StartProgram enables output only when permissive_ok
                    if not snapshot.permissive_ok:
                        current_enabled = False
                        refusal_reason = (
                            f"StartProgram refused: "
                            f"{snapshot.permissive_reason or 'permissive not OK'}"
                        )
                    else:
                        current_enabled = True

                elif isinstance(req, StopProgram):
                    current_enabled = False
                    current_volts = 0.0

                elif isinstance(req, ProgramHeaterRequest):
                    if current_enabled:
                        current_volts = req.volts

        # Permissive check: if output was on but permissive is False, cut output
        if current_enabled and not snapshot.permissive_ok:
            current_enabled = False
            current_volts = 0.0
            if snapshot.program and snapshot.program.running:
                stop_program = True
            if refusal_reason is None:
                refusal_reason = f"Output disabled: {snapshot.permissive_reason or 'permissive lost'}"

        # ---------------------------------------------------------------------
        # 5. DAC0 Voltage Clamp & CV-Only (Rule 6)
        # ---------------------------------------------------------------------
        current_volts = max(0.0, min(current_volts, DAC0_MAX_V))
        if not current_enabled:
            current_volts = 0.0

        self._last_output_enabled = current_enabled
        self._last_commanded_volts = current_volts

        return HeaterCommand(
            output_enabled=current_enabled,
            volts=current_volts,
            stop_program=stop_program,
            refusal_reason=refusal_reason,
            trip_kind=None,
            trip_reason=None,
        )

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _flatten_requests(requests: Any) -> Sequence[Any]:
        if requests is None:
            return []
        if isinstance(requests, (list, tuple, set)):
            flat = []
            for item in requests:
                if isinstance(item, (list, tuple, set)):
                    flat.extend(item)
                elif item is not None:
                    flat.append(item)
            return flat
        return [requests]

    def _check_trip_persisting(self, snapshot: Snapshot) -> Optional[str]:
        """
        Check if the condition that caused the active trip is still present.
        Returns a human-readable refusal reason if persisting, or None if cleared.
        """
        kind = self._active_trip_kind

        # 1. temp_override: needs every TC < TEMP_OVERRIDE_RESET_C
        if kind == "temp_override":
            for tc_name, val in snapshot.tc_c.items():
                if val is not None and val >= TEMP_OVERRIDE_RESET_C:
                    return (
                        f"Reset refused: thermocouple {tc_name} is "
                        f"{val:.1f} °C >= {TEMP_OVERRIDE_RESET_C:.1f} °C"
                    )
            return None

        # 2. temp_limit: check if the tripped sensor is still >= configured limit
        if kind == "temp_limit":
            if self._active_trip_sensor and self._active_trip_limit is not None:
                current_val = snapshot.tc_c.get(self._active_trip_sensor)
                if current_val is not None and current_val >= self._active_trip_limit:
                    return (
                        f"Reset refused: thermocouple {self._active_trip_sensor} is "
                        f"{current_val:.1f} °C >= {self._active_trip_limit:.1f} °C"
                    )
            return None

        # 2b. current caps: measured current must be back at or below the tripped cap
        if kind in ("soft_start_overcurrent", "run_overcurrent"):
            if self._active_trip_limit is not None and snapshot.ps_amps > self._active_trip_limit:
                return (
                    f"Reset refused: supply current is {snapshot.ps_amps:.1f} A "
                    f"> cap {self._active_trip_limit:.1f} A"
                )
            return None

        # 3. pressure_high: needs pressure <= PRESSURE_INTERLOCK_TORR
        if kind == "pressure_high":
            for g_name, p_val in snapshot.pressure_torr.items():
                if p_val is not None and p_val > PRESSURE_INTERLOCK_TORR:
                    return (
                        f"Reset refused: pressure on {g_name} is "
                        f"{p_val:.2e} Torr > {PRESSURE_INTERLOCK_TORR:.2e} Torr"
                    )
            if not snapshot.permissive_ok:
                return (
                    f"Reset refused: {snapshot.permissive_reason or 'pressure permissive not OK'}"
                )
            return None

        # 4. pressure_stale: needs fresh valid reading (<= STALE_ALLOWANCE_S)
        if kind == "pressure_stale":
            if self._active_trip_sensor:
                p_val = snapshot.pressure_torr.get(self._active_trip_sensor)
                age = snapshot.source_age_s.get(self._active_trip_sensor, float("inf"))
                if p_val is None or age > STALE_ALLOWANCE_S:
                    return (
                        f"Reset refused: pressure gauge {self._active_trip_sensor} is stale "
                        f"({age:.1f} s > {STALE_ALLOWANCE_S:.1f} s)"
                    )
            else:
                for g_name, p_val in snapshot.pressure_torr.items():
                    age = snapshot.source_age_s.get(g_name, float("inf"))
                    if p_val is None or age > STALE_ALLOWANCE_S:
                        return (
                            f"Reset refused: pressure gauge {g_name} is stale "
                            f"({age:.1f} s > {STALE_ALLOWANCE_S:.1f} s)"
                        )
            return None

        # 5. control_tc_stale: control TC must be valid and fresh
        if kind == "control_tc_stale":
            ctrl_tc = self._active_trip_sensor
            if not ctrl_tc and snapshot.program:
                ctrl_tc = snapshot.program.control_tc
            if not ctrl_tc:
                ctrl_tc = "TC_1"

            tc_val = snapshot.tc_c.get(ctrl_tc)
            age = snapshot.source_age_s.get(ctrl_tc, float("inf"))
            if tc_val is None or age > STALE_ALLOWANCE_S:
                return (
                    f"Reset refused: control thermocouple {ctrl_tc} is stale "
                    f"({age:.1f} s > {STALE_ALLOWANCE_S:.1f} s)"
                )
            return None

        # 6. labjack_lost: adapter must be connected
        if kind == "labjack_lost":
            if snapshot.labjack.state != "connected":
                return (
                    f"Reset refused: LabJack adapter state is "
                    f"'{snapshot.labjack.state}' (not connected)"
                )
            return None

        # Other trips (e.g. program_error): cleared on reset
        return None

    @staticmethod
    def _extract_limit_from_reason(reason: str) -> Optional[float]:
        """Attempt to extract threshold value from reason string (e.g. '>= 1200.0 °C')."""
        if ">=" in reason:
            try:
                parts = reason.split(">=")[1].strip().split()
                return float(parts[0])
            except (IndexError, ValueError) as err:
                logger.error("Failed to parse threshold limit from trip reason %r: %s", reason, err)
                raise ValueError(
                    f"Malformed trip reason cannot be parsed for reset verification: {reason!r}"
                ) from err
        return None


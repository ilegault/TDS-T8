"""
Frozen command dataclasses for the Rig module.

WHY THIS EXISTS
---------------
Previously, multiple threads (GUI thread, DAQ thread, executor thread, safety
thread) directly invoked methods on hardware controllers and safety monitors without
synchronization or arbitration. This led to race conditions, conflicting heater
setpoints, and UI lockups.

Commands represent operator or automation intentions as immutable values submitted
to the Rig module's thread-safe queue. The Rig loop drains and processes commands
in a single thread at known points in each tick (ADR 0002).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class LoadProgram:
    """Load a program (block sequence) into the Rig."""

    program: Any = None


@dataclass(frozen=True)
class RunSettings:
    """Frozen control and safety parameters applied at run start."""

    kp: float
    ki: float
    kd: float
    windup_limit: float
    soft_start_threshold_c: float
    soft_start_ramp_v_per_s: float
    soft_start_handoff_current_a: float
    soft_start_cap_enabled: bool
    soft_start_cap_a: float
    run_cap_enabled: bool
    run_cap_a: float


@dataclass(frozen=True)
class StartProgram:
    """Start execution of the loaded program."""

    settings: RunSettings


@dataclass(frozen=True)
class StopProgram:
    """Stop execution of the currently running program."""

    pass


@dataclass(frozen=True)
class ConfirmContinue:
    """Operator confirmation to release QMS pause or proceed to next block."""

    pass


@dataclass(frozen=True)
class Nudge:
    """Manual nudge of voltage up or down by the operator."""

    direction: str  # "up" | "down"


@dataclass(frozen=True)
class SetVoltage:
    """Manual voltage setpoint request from the operator."""

    volts: float


@dataclass(frozen=True)
class SetOutput:
    """Manual heater output enable or disable request."""

    enabled: bool


@dataclass(frozen=True)
class ResetTrip:
    """Operator request to clear a latched safety trip."""

    pass


@dataclass(frozen=True)
class SelectAdapter:
    """
    Switch between hardware (T8) and practice (Simulated) rig adapters.

    Rejected if submitted while a program is running or logging is active.
    """

    practice: bool


@dataclass(frozen=True)
class UpdateConfig:
    """
    Update runtime configuration parameters (sample rate, sensor names, etc.).
    """

    sample_rate_ms: float | None = None
    tc_names: Sequence[str] | None = None
    gauge_names: Sequence[str] | None = None
    extra: Mapping[str, Any] | None = None

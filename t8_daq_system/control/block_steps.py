"""
t8_daq_system/control/block_steps.py

Pure block-step calculation functions and context for Program execution.

WHY THIS EXISTS
---------------
Previously, _execute_block in program_executor.py combined PID computation,
feedforward mapping, linear ramping, time.sleep(0.5), hardware writes, practice-mode
simulation, and error handling in a single 220-line loop. This made it impossible
to test the control math faster than real-time or isolate calculation bugs from
threading and hardware I/O.

These step functions (step_voltage_ramp, step_temp_ramp, step_stable_hold) extract
the pure calculation of setpoint, PID correction, feedforward, and completion logic.
They perform no I/O, read no system clocks, do not sleep or print, and never catch
exceptions. They return a StepResult containing the commanded volts, completion flag,
scheduler values, and target setpoint.

This is the pure computation layer required by ADRs 0002 and 0003, preparing the
transition of program execution onto the Rig loop (ticket rig-architecture-09).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def c_to_k(temp_c: float | None) -> float | None:
    """
    Convert Celsius to Kelvin.

    This function serves as the single canonical Celsius -> Kelvin conversion point
    for the control layer.
    """
    if temp_c is None:
        return None
    return temp_c + 273.15


def k_to_c(temp_k: float | None) -> float | None:
    """Convert Kelvin to Celsius."""
    if temp_k is None:
        return None
    return temp_k - 273.15


@dataclass(frozen=True)
class SchedValues:
    """Scheduler, feedforward, and PID correction diagnostics."""

    kp: float = 0.0
    ki: float = 0.0
    kd: float = 0.0
    zone: int | str = 0
    ff_voltage: float = 0.0
    pid_correction: float = 0.0

    @property
    def sched_kp(self) -> float:
        return self.kp

    @property
    def sched_ki(self) -> float:
        return self.ki

    @property
    def sched_kd(self) -> float:
        return self.kd

    @property
    def sched_zone(self) -> int | str:
        return self.zone


@dataclass(frozen=True)
class StepResult:
    """Result of evaluating a single block step."""

    volts: float
    finished: bool
    sched: SchedValues = field(default_factory=SchedValues)
    setpoint_k: float = 0.0


@dataclass
class StepContext:
    """
    Execution context for block steps.

    Carries the controller instance, feedforward map, block start temperature,
    nominal rate, and state tracking (e.g. stability window start time).
    """

    pid: Any
    ff_map: Any = None
    start_temp_k: float = 293.15
    rate_k_per_min: float = 0.0
    stability_start: float | None = None


def step_voltage_ramp(
    block: Any,
    temp_k: float,
    elapsed_s: float,
    now_s: float,
    ctx: StepContext,
) -> StepResult:
    """
    Pure step function for VoltageRampBlock.

    Calculates open-loop linear voltage interpolation and checks completion.
    """
    if block.duration_sec > 0:
        progress = min(1.0, elapsed_s / block.duration_sec)
    else:
        progress = 1.0

    v_out = block.start_voltage + (block.end_voltage - block.start_voltage) * progress

    # PID monitoring if requested on block (diagnostic tracking only)
    if getattr(block, "pid_active", False) and ctx.pid is not None:
        ctx.pid.compute(temp_k, temp_k, now_s)

    finished = progress >= 1.0
    return StepResult(volts=v_out, finished=finished, sched=SchedValues(), setpoint_k=0.0)


def step_soft_start(
    settings: Any,
    temp_c: float,
    amps: float,
    elapsed_s: float,
    start_voltage: float,
) -> tuple[StepResult, str | None]:
    """
    Pure step function for the Soft start phase (ADR 0006 points 1-2).

    Ramps the voltage open-loop from start_voltage at settings.soft_start_ramp_v_per_s,
    with no Feedforward and no PID. Returns the StepResult (finished=True on handoff)
    and the handoff reason, or None while still ramping. The first of the control-TC
    threshold and the handoff current ends it; the threshold is reported first when
    both are met on the same step.
    """
    v_out = start_voltage + settings.soft_start_ramp_v_per_s * elapsed_s
    v_out = max(0.0, min(v_out, 6.0))

    reason: str | None = None
    if temp_c >= settings.soft_start_threshold_c:
        reason = f"threshold {settings.soft_start_threshold_c:.1f} °C reached"
    elif amps >= settings.soft_start_handoff_current_a:
        reason = (
            f"handoff current {settings.soft_start_handoff_current_a:.1f} A "
            f"reached at {temp_c:.1f} °C"
        )

    return StepResult(volts=v_out, finished=reason is not None), reason


def step_stable_hold(
    block: Any,
    temp_k: float,
    elapsed_s: float,
    now_s: float,
    ctx: StepContext,
) -> StepResult:
    """
    Pure step function for StableHoldBlock.

    Calculates PID correction around target_temp_k and tracks continuous stability
    within tolerance_k for hold_duration_sec.
    """
    setpoint_k = block.target_temp_k
    ff_v = 0.0
    pid_correction = ctx.pid.compute(setpoint_k, temp_k, now_s)
    v_out = max(0.0, min(ff_v + pid_correction, 6.0))

    sched = SchedValues(
        kp=ctx.pid._kp,
        ki=ctx.pid._ki,
        kd=ctx.pid._kd,
        zone=0,
        ff_voltage=ff_v,
        pid_correction=pid_correction,
    )

    finished = False
    if abs(temp_k - setpoint_k) <= block.tolerance_k:
        if ctx.stability_start is None:
            ctx.stability_start = now_s
        elif now_s - ctx.stability_start >= block.hold_duration_sec:
            finished = True
    else:
        ctx.stability_start = None

    return StepResult(volts=v_out, finished=finished, sched=sched, setpoint_k=setpoint_k)


def step_temp_ramp(
    block: Any,
    temp_k: float,
    elapsed_s: float,
    now_s: float,
    ctx: StepContext,
) -> StepResult:
    """
    Pure step function for TempRampBlock.

    Calculates dynamic setpoint_k along rate_k_per_min, queries feedforward map,
    computes PID correction, and checks completion (honoring FIX-2 warmup guard).
    """
    current_temp_c = temp_k - 273.15
    rate_k_per_sec = block.rate_k_per_min / 60.0
    setpoint_k = ctx.start_temp_k + rate_k_per_sec * elapsed_s

    # Cap at end_temp_k and detect completion
    is_finished = False
    if rate_k_per_sec > 0:
        setpoint_k = min(setpoint_k, block.end_temp_k)
        if setpoint_k >= block.end_temp_k:
            is_finished = True
    else:
        setpoint_k = max(setpoint_k, block.end_temp_k)
        if setpoint_k <= block.end_temp_k:
            is_finished = True

    # FIX-2: Suppress is_finished during the warmup window
    MIN_RAMP_ELAPSED_SEC = 2.0
    if elapsed_s < MIN_RAMP_ELAPSED_SEC:
        is_finished = False

    ff_v = 0.0
    if ctx.ff_map is not None:
        rate = ctx.rate_k_per_min if ctx.rate_k_per_min != 0.0 else getattr(block, "rate_k_per_min", 0.0)
        ff_v = ctx.ff_map.voltage_for(rate, current_temp_c)

    pid_correction = ctx.pid.compute(setpoint_k, temp_k, now_s)
    v_out = max(0.0, min(ff_v + pid_correction, 6.0))

    sched = SchedValues(
        kp=ctx.pid._kp,
        ki=ctx.pid._ki,
        kd=ctx.pid._kd,
        zone=0,
        ff_voltage=ff_v,
        pid_correction=pid_correction,
    )

    return StepResult(volts=v_out, finished=is_finished, sched=sched, setpoint_k=setpoint_k)

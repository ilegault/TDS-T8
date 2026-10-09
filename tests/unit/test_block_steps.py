"""
tests/unit/test_block_steps.py

Unit tests for pure block-step functions (Ticket 09 / spec: Block steps and the Program run).

WHY THIS EXISTS
---------------
Spec requires control math inside _execute_block to be extracted into pure block-step
functions (step_voltage_ramp, step_temp_ramp, step_stable_hold). Each step is a pure
function of (block, temp_k, elapsed_s, now_s, ctx) returning
StepResult(volts, finished, sched, setpoint_k).
A step performs no I/O, reads no clock, does not print, does not sleep, and never catches
its own exceptions. This enables faster-than-real-time simulation without time.sleep,
and decouples control calculations from threading/hardware.
"""
from __future__ import annotations

import math
import pytest

from t8_daq_system.control.block_steps import (
    SchedValues,
    StepContext,
    StepResult,
    c_to_k,
    step_stable_hold,
    step_temp_ramp,
    step_voltage_ramp,
)
from t8_daq_system.control.feedforward_map import FeedforwardMap
from t8_daq_system.control.program_block import (
    StableHoldBlock,
    TempRampBlock,
    VoltageRampBlock,
)
from t8_daq_system.control.temp_ramp_pid import PIDController

pytestmark = pytest.mark.unit


def test_c_to_k_conversion():
    """Verify c_to_k provides the single canonical Celsius to Kelvin conversion."""
    assert math.isclose(c_to_k(0.0), 273.15, abs_tol=1e-9)
    assert math.isclose(c_to_k(20.0), 293.15, abs_tol=1e-9)
    assert math.isclose(c_to_k(100.0), 373.15, abs_tol=1e-9)
    assert math.isclose(c_to_k(-273.15), 0.0, abs_tol=1e-9)
    assert c_to_k(None) is None


def test_step_voltage_ramp_series():
    """
    Test step_voltage_ramp with explicit series, no clock.
    Ramp 0.0 V to 3.0 V over 3.0 s.
    """
    block = VoltageRampBlock(start_voltage=0.0, end_voltage=3.0, duration_sec=3.0)
    pid = PIDController(kp=0.014, ki=0.00078, kd=0.00845)
    ctx = StepContext(pid=pid, start_temp_k=300.0)

    # At elapsed = 0.0s -> 0.0V, not finished
    r0 = step_voltage_ramp(block, temp_k=300.0, elapsed_s=0.0, now_s=10.0, ctx=ctx)
    assert isinstance(r0, StepResult)
    assert isinstance(r0.sched, SchedValues)
    assert math.isclose(r0.volts, 0.0, abs_tol=1e-9)
    assert not r0.finished
    assert r0.sched.kp == 0.0
    assert r0.sched.ff_voltage == 0.0

    # At elapsed = 1.5s -> 1.5V, not finished
    r1 = step_voltage_ramp(block, temp_k=300.0, elapsed_s=1.5, now_s=11.5, ctx=ctx)
    assert math.isclose(r1.volts, 1.5, abs_tol=1e-9)
    assert not r1.finished

    # At elapsed = 3.0s -> 3.0V, finished
    r2 = step_voltage_ramp(block, temp_k=300.0, elapsed_s=3.0, now_s=13.0, ctx=ctx)
    assert math.isclose(r2.volts, 3.0, abs_tol=1e-9)
    assert r2.finished

    # Beyond duration -> capped at 3.0V, finished
    r3 = step_voltage_ramp(block, temp_k=300.0, elapsed_s=4.0, now_s=14.0, ctx=ctx)
    assert math.isclose(r3.volts, 3.0, abs_tol=1e-9)
    assert r3.finished


def test_step_voltage_ramp_zero_duration_and_pid_active():
    """Test step_voltage_ramp with duration_sec <= 0 and with pid_active=True."""
    block = VoltageRampBlock(start_voltage=1.0, end_voltage=2.0, duration_sec=0.0, pid_active=True)
    pid = PIDController(kp=0.014, ki=0.00078, kd=0.00845)
    ctx = StepContext(pid=pid, start_temp_k=300.0)

    res = step_voltage_ramp(block, temp_k=300.0, elapsed_s=0.0, now_s=10.0, ctx=ctx)
    assert math.isclose(res.volts, 2.0, abs_tol=1e-9)
    assert res.finished


def test_step_temp_ramp_heating_and_fix2_guard():
    """
    Test step_temp_ramp heating: 60 K/min (1 K/s) from 300 K to 303 K.
    Exercises setpoint progression, FIX-2 2-second completion suppression, and completion.
    """
    block = TempRampBlock(rate_k_per_min=60.0, end_temp_k=303.0, tc_name="TC_1")
    pid = PIDController(kp=0.02, ki=0.0013, kd=0.005)
    ctx = StepContext(pid=pid, start_temp_k=300.0, rate_k_per_min=60.0)

    # Tick 1: elapsed 0.5s -> setpoint 300.5K, finished is False (elapsed < 2.0s)
    r1 = step_temp_ramp(block, temp_k=300.0, elapsed_s=0.5, now_s=10.5, ctx=ctx)
    assert math.isclose(r1.setpoint_k, 300.5, abs_tol=1e-9)
    assert not r1.finished
    assert r1.sched.kp == 0.02
    assert r1.sched.ki == 0.0013
    assert r1.sched.kd == 0.005

    # Tick 2: elapsed 1.5s -> setpoint 301.5K, finished is False
    r2 = step_temp_ramp(block, temp_k=300.0, elapsed_s=1.5, now_s=11.5, ctx=ctx)
    assert math.isclose(r2.setpoint_k, 301.5, abs_tol=1e-9)
    assert not r2.finished

    # Tick 3: elapsed 3.0s -> setpoint 303.0K (end_temp_k reached), elapsed >= 2.0s -> finished is True
    r3 = step_temp_ramp(block, temp_k=300.0, elapsed_s=3.0, now_s=13.0, ctx=ctx)
    assert math.isclose(r3.setpoint_k, 303.0, abs_tol=1e-9)
    assert r3.finished

    # Sched values
    assert r3.sched.pid_correction == r3.volts - r3.sched.ff_voltage


def test_step_temp_ramp_cooldown_and_fix2_suppression():
    """
    Test cooldown ramp: -60 K/min (-1 K/s) from 300 K to 300 K (or 301 K to 300 K).
    FIX-2 ensures that if setpoint <= end_temp_k on tick 1, finished is suppressed for 2.0s.
    """
    block = TempRampBlock(rate_k_per_min=-60.0, end_temp_k=300.0, tc_name="TC_1")
    pid = PIDController(kp=0.014, ki=0.00078, kd=0.00845)
    # Starting right at 300.0 K
    ctx = StepContext(pid=pid, start_temp_k=300.0, rate_k_per_min=-60.0)

    # At elapsed = 0.5s: setpoint_k = 300.0 (capped at end_temp_k=300.0), but elapsed < 2.0s
    r1 = step_temp_ramp(block, temp_k=300.0, elapsed_s=0.5, now_s=10.5, ctx=ctx)
    assert math.isclose(r1.setpoint_k, 300.0, abs_tol=1e-9)
    assert not r1.finished, "FIX-2 must suppress completion during first 2.0 seconds"

    # At elapsed = 1.5s: still suppressed
    r2 = step_temp_ramp(block, temp_k=300.0, elapsed_s=1.5, now_s=11.5, ctx=ctx)
    assert not r2.finished, "FIX-2 must suppress completion during first 2.0 seconds"

    # At elapsed = 2.0s: guard passed, finishes
    r3 = step_temp_ramp(block, temp_k=300.0, elapsed_s=2.0, now_s=12.0, ctx=ctx)
    assert r3.finished


def test_step_temp_ramp_feedforward_integration():
    """Verify FeedforwardMap voltage is included in StepResult.sched and volts."""
    block = TempRampBlock(rate_k_per_min=60.0, end_temp_k=350.0, tc_name="TC_1")
    pid = PIDController(kp=0.014, ki=0.00078, kd=0.00845)
    ff_map = FeedforwardMap()
    # Ingest a simple steady-state curve into ff_map
    ff_map._ss_curve = [[20.0, 1.0], [50.0, 2.0], [100.0, 3.0]]  # 1.0V at 20C (293.15K)

    ctx = StepContext(pid=pid, ff_map=ff_map, start_temp_k=293.15, rate_k_per_min=60.0)

    res = step_temp_ramp(block, temp_k=293.15, elapsed_s=0.5, now_s=10.5, ctx=ctx)
    assert math.isclose(res.sched.ff_voltage, 1.0, abs_tol=1e-6)
    assert math.isclose(res.volts, 1.0 + res.sched.pid_correction, abs_tol=1e-6)


def test_step_stable_hold_series():
    """
    Test step_stable_hold with explicit series:
    target_temp_k = 320.0, tolerance = 1.0 K, hold_duration_sec = 2.0 s.
    """
    block = StableHoldBlock(target_temp_k=320.0, tolerance_k=1.0, hold_duration_sec=2.0)
    pid = PIDController(kp=0.02, ki=0.0013, kd=0.005)
    ctx = StepContext(pid=pid, start_temp_k=315.0)

    # 1. At t=10.0, temp=315.0 (outside tolerance) -> finished False, stability_start is None
    r1 = step_stable_hold(block, temp_k=315.0, elapsed_s=0.0, now_s=10.0, ctx=ctx)
    assert not r1.finished
    assert ctx.stability_start is None
    assert math.isclose(r1.setpoint_k, 320.0, abs_tol=1e-9)

    # 2. At t=11.0, temp=319.5 (within tolerance) -> stability_start set to 11.0, finished False
    r2 = step_stable_hold(block, temp_k=319.5, elapsed_s=1.0, now_s=11.0, ctx=ctx)
    assert not r2.finished
    assert ctx.stability_start == 11.0

    # 3. At t=12.0, temp=320.5 (within tolerance) -> elapsed in stability 1.0s < 2.0s -> finished False
    r3 = step_stable_hold(block, temp_k=320.5, elapsed_s=2.0, now_s=12.0, ctx=ctx)
    assert not r3.finished
    assert ctx.stability_start == 11.0

    # 4. At t=12.5, temp=318.0 (outside tolerance) -> stability_start reset to None
    r4 = step_stable_hold(block, temp_k=318.0, elapsed_s=2.5, now_s=12.5, ctx=ctx)
    assert not r4.finished
    assert ctx.stability_start is None

    # 5. At t=13.0, temp=320.0 (within tolerance) -> stability_start set to 13.0
    r5 = step_stable_hold(block, temp_k=320.0, elapsed_s=3.0, now_s=13.0, ctx=ctx)
    assert not r5.finished
    assert ctx.stability_start == 13.0

    # 6. At t=15.0, temp=320.2 (within tolerance) -> elapsed in stability 2.0s >= 2.0s -> finished True
    r6 = step_stable_hold(block, temp_k=320.2, elapsed_s=5.0, now_s=15.0, ctx=ctx)
    assert r6.finished
    assert ctx.stability_start == 13.0


def test_step_exceptions_propagate():
    """
    Verify that steps perform no exception catching:
    Any error (e.g. None temperature, faulty controller, or bad block) propagates immediately.
    """
    block_v = VoltageRampBlock(start_voltage=0.0, end_voltage=3.0, duration_sec=3.0, pid_active=True)
    block_t = TempRampBlock(rate_k_per_min=60.0, end_temp_k=303.0, tc_name="TC_1")
    block_h = StableHoldBlock(target_temp_k=320.0, tolerance_k=1.0, hold_duration_sec=1.0)

    class FaultyPID:
        def compute(self, *args, **kwargs):
            raise RuntimeError("PID compute hardware exception")

    faulty_ctx = StepContext(pid=FaultyPID(), start_temp_k=300.0)

    # Faulty PID raises across all steps
    with pytest.raises(RuntimeError, match="PID compute hardware exception"):
        step_voltage_ramp(block_v, temp_k=300.0, elapsed_s=0.5, now_s=10.5, ctx=faulty_ctx)

    with pytest.raises(RuntimeError, match="PID compute hardware exception"):
        step_temp_ramp(block_t, temp_k=300.0, elapsed_s=0.5, now_s=10.5, ctx=faulty_ctx)

    with pytest.raises(RuntimeError, match="PID compute hardware exception"):
        step_stable_hold(block_h, temp_k=320.0, elapsed_s=0.5, now_s=10.5, ctx=faulty_ctx)

    # Passing None for temp_k without mock raises TypeError
    ctx = StepContext(pid=PIDController(kp=0.014, ki=0.00078, kd=0.00845), start_temp_k=300.0)
    with pytest.raises(TypeError):
        step_temp_ramp(block_t, temp_k=None, elapsed_s=0.5, now_s=10.5, ctx=ctx)


def test_step_raising_propagates_through_program_run(monkeypatch):
    """Verify that an exception raised by a block step turns into a program_error trip in ProgramRun."""
    from t8_daq_system.control.program_run import ProgramRun
    from t8_daq_system.rig.snapshot import Snapshot, SourceStatus, HeaterStatus, ProgramStatus

    pr = ProgramRun()
    block = TempRampBlock(rate_k_per_min=60.0, end_temp_k=303.0, tc_name="TC_1")
    pr.load([block])

    snap = Snapshot(
        t=100.0,
        wall_time=1700000000.0,
        tc_c={"TC_1": 25.0},
        tc_raw_v={"TC_1": 0.001},
        pressure_torr={"FRG702_Chamber": 1e-6},
        source_age_s={"TC_1": 0.0, "FRG702_Chamber": 0.0},
        ps_volts=0.0,
        ps_amps=0.0,
        commanded_volts=0.0,
        output_enabled=True,
        labjack=SourceStatus(state="connected"),
        xgs=SourceStatus(state="connected"),
        heater=HeaterStatus(state="on"),
        program=ProgramStatus(),
        permissive_ok=True,
        permissive_reason=None,
        adapter="simulated",
    )
    pr.start(snap, now_s=100.0)

    def _faulty_step(*args, **kwargs):
        raise ValueError("simulated step mathematical fault")

    monkeypatch.setattr(
        "t8_daq_system.control.program_run._block_steps.step_temp_ramp",
        _faulty_step,
    )

    pr.step(snap, now_s=100.0)  # Phase 2 -> 1
    pr.step(snap, now_s=100.5)  # Phase 1 -> 0
    trip = pr.step(snap, now_s=101.0)  # Phase 0: calls step_temp_ramp
    assert trip is not None
    assert trip.kind == "program_error"
    assert "simulated step mathematical fault" in trip.reason



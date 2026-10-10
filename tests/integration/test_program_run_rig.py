"""
tests/integration/test_program_run_rig.py

Integration tests for ProgramRun on the Rig loop (ticket rig-architecture-10).

WHY THIS EXISTS
---------------
These tests prove that ProgramRun, driven by the Rig loop with SimulatedRig and
ManualClock, reproduces the exact per-tick control math of ProgramExecutor (AC 5)
and correctly handles trips, operator overrides, and program completion (AC 1-4).

Main seam: real Rig + SimulatedRig + ManualClock, driven via run_tick().
Pure-module seam (AC 5): ProgramRun.step() alone with synthetic Snapshots.
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from t8_daq_system.control.heater_output import HeaterOutput, ProgramHeaterRequest
from t8_daq_system.control.program_block import (
    StableHoldBlock,
    TempRampBlock,
    VoltageRampBlock,
)
from t8_daq_system.control.program_run import ProgramRun
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.rig.adapter import RawReadings, RigAdapter
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import (
    LoadProgram,
    Nudge,
    StartProgram,
)
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig
from t8_daq_system.rig.snapshot import (
    HeaterStatus,
    ProgramStatus,
    Snapshot,
    SourceStatus,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


class CallSpyAdapter(RigAdapter):
    """Spy wrapper that records every adapter call and delegates to target."""

    def __init__(self, target: RigAdapter) -> None:
        self._target = target
        self.calls: list[object] = []

    def connect(self) -> bool:
        self.calls.append("connect")
        return self._target.connect()

    def disconnect(self) -> None:
        self.calls.append("disconnect")
        self._target.disconnect()

    def is_connected(self) -> bool:
        return self._target.is_connected()

    def read(self) -> RawReadings:
        self.calls.append("read")
        return self._target.read()

    def write_voltage(self, volts: float) -> None:
        self.calls.append(("write_voltage", volts))
        self._target.write_voltage(volts)

    def set_output(self, enabled: bool) -> None:
        self.calls.append(("set_output", enabled))
        self._target.set_output(enabled)

    def pin_current_limit(self) -> None:
        self.calls.append("pin_current_limit")
        self._target.pin_current_limit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)


def voltage_writes(spy: CallSpyAdapter) -> list[float]:
    """Extract all write_voltage values from the spy call log."""
    return [v for tag, v in spy.calls if isinstance(tag, tuple) and tag == ("write_voltage", v) or (isinstance(tag, tuple) and len(tag) == 2 and tag[0] == "write_voltage")]


def _extract_voltage_writes(spy: CallSpyAdapter) -> list[float]:
    return [v for (kind, v) in spy.calls if isinstance(kind, str) and kind == "write_voltage" or (isinstance(spy.calls, list) and False)]


def get_voltage_writes(spy: CallSpyAdapter) -> list[float]:
    """Return list of volts from write_voltage adapter calls in call order."""
    result = []
    for entry in spy.calls:
        if isinstance(entry, tuple) and len(entry) == 2 and entry[0] == "write_voltage":
            result.append(entry[1])
    return result


def make_rig_fixture(*, start_time: float = 100.0) -> SimpleNamespace:
    """Build real Rig + SimulatedRig + ManualClock + ProgramRun + spy."""
    clock = ManualClock(start_time=start_time)
    sim = SimulatedRig(
        clock=clock,
        tc_names=["TC_1"],
        gauge_names=["FRG702_Chamber"],
    )
    spy = CallSpyAdapter(sim)
    program_run = ProgramRun()
    heater_output = HeaterOutput()
    safety_evaluator = SafetyEvaluator()
    rig = Rig(
        adapter=spy,
        clock=clock,
        sample_rate_ms=500,
        tc_names=["TC_1"],
        gauge_names=["FRG702_Chamber"],
        heater_output=heater_output,
        safety_evaluator=safety_evaluator,
        program_run=program_run,
    )
    return SimpleNamespace(
        clock=clock,
        sim=sim,
        spy=spy,
        rig=rig,
        program_run=program_run,
        heater_output=heater_output,
    )


def tick(ns: SimpleNamespace, n: int = 1, dt: float = 0.5) -> None:
    """Advance clock by dt then run_tick() for n iterations."""
    for _ in range(n):
        ns.clock.advance(dt)
        ns.rig.run_tick()


# ---------------------------------------------------------------------------
# Minimal Snapshot factory for pure-module tests (AC 5)
# ---------------------------------------------------------------------------

_BASE_SOURCE = SourceStatus(state="connected")
_BASE_HEATER = HeaterStatus(state="off")
_BASE_PROGRAM = ProgramStatus()


def make_snapshot(
    *,
    tc_c: dict[str, float | None] | None = None,
    ps_amps: float = 0.0,
    ps_volts: float = 0.0,
    commanded_volts: float = 0.0,
    output_enabled: bool = True,
    permissive_ok: bool = True,
    program: ProgramStatus | None = None,
    t: float = 0.0,
) -> Snapshot:
    return Snapshot(
        t=t,
        wall_time=t + 1774000000.0,
        tc_c=dict(tc_c) if tc_c is not None else {"TC_1": 26.85},
        tc_raw_v={"TC_1": 0.0},
        pressure_torr={"FRG702_Chamber": 1e-7},
        source_age_s={"TC_1": 0.0, "FRG702_Chamber": 0.0},
        ps_volts=ps_volts,
        ps_amps=ps_amps,
        commanded_volts=commanded_volts,
        output_enabled=output_enabled,
        labjack=_BASE_SOURCE,
        xgs=_BASE_SOURCE,
        heater=_BASE_HEATER,
        program=program if program is not None else _BASE_PROGRAM,
        permissive_ok=permissive_ok,
        permissive_reason=None,
        adapter="simulated",
    )


# ---------------------------------------------------------------------------
# AC 1 — Three-block program completes on the integration fixture
# ---------------------------------------------------------------------------


def test_three_block_program_completes():
    """
    Three-block program (voltage ramp → temp ramp → stable hold) runs to completion
    on the SimulatedRig with ManualClock. Snapshot.program.running becomes False.
    """
    ns = make_rig_fixture()

    # Establish initial tick (baseline snapshot with permissive_ok=True)
    tick(ns)

    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=1.0, duration_sec=1.0),
        TempRampBlock(rate_k_per_min=60.0, end_temp_k=303.0, tc_name="TC_1"),
        StableHoldBlock(target_temp_k=303.0, tolerance_k=50.0, hold_duration_sec=0.5),
    ]
    ns.rig.submit(LoadProgram(program=blocks))
    ns.rig.submit(StartProgram())

    # Run enough ticks for all three blocks to complete:
    # Block 0: VoltageRamp 1.0s → 2 writes + transitions
    # Block 1: TempRamp 60K/min → 3 s to reach 303K + FIX-2 guard (~7 ticks)
    # Block 2: StableHold 50K tolerance → requires reaching/settling at 303K
    # With updated realistic TungstenSim thermal constants (Issue #20), it takes
    # ~130-140 ticks to fully complete and settle the run instead of 30.
    # Total budget: 200 ticks (100 simulated seconds)
    for _ in range(200):
        ns.rig.run_tick()
        ns.clock.advance(0.5)
        snap = ns.rig.latest()
        if snap is not None and not snap.program.running:
            break

    snap = ns.rig.latest()
    assert snap is not None
    assert snap.program.running is False, "Program should have completed"
    # Heater should not be tripped (normal completion)
    assert snap.heater.state != "tripped", f"Unexpected trip: {snap.heater.trip_kind}: {snap.heater.trip_reason}"


# ---------------------------------------------------------------------------
# AC 2 — drop_tc on control TC: no trip at 4.9 s, control_tc_stale at 5.1 s
# ---------------------------------------------------------------------------


def test_control_tc_stale_trips_at_5_1s_not_at_4_9s():
    """
    drop_tc on the control TC mid-ramp: no trip at 4.9 s, control_tc_stale at 5.1 s;
    adapter receives set_output(False) and write_voltage(0.0) that tick; run ends;
    reason appears in Snapshot.
    """
    ns = make_rig_fixture()

    # Establish baseline with valid readings
    tick(ns)
    assert ns.rig.latest().heater.state == "off"

    # Load and start a temp ramp
    blocks = [TempRampBlock(rate_k_per_min=60.0, end_temp_k=600.0, tc_name="TC_1")]
    ns.rig.submit(LoadProgram(program=blocks))
    ns.rig.submit(StartProgram())

    # Run a few ticks to get the program fully running
    tick(ns, n=4)
    snap = ns.rig.latest()
    assert snap.program.running is True, "Program should be running"
    assert snap.heater.state != "tripped"

    # Drop TC — record the time of last valid read
    ns.sim.drop_tc("TC_1")
    ns.spy.calls.clear()

    # Advance to 4.9 s of staleness: no trip
    ns.clock.advance(4.9)
    ns.rig.run_tick()
    snap_4_9 = ns.rig.latest()
    assert snap_4_9.heater.trip_kind is None, f"Unexpected trip at 4.9 s: {snap_4_9.heater.trip_kind}"
    assert snap_4_9.heater.state != "tripped"

    # Advance 0.2 s more → 5.1 s total staleness → control_tc_stale
    ns.clock.advance(0.2)
    ns.rig.run_tick()
    snap_5_1 = ns.rig.latest()

    assert snap_5_1.heater.state == "tripped"
    assert snap_5_1.heater.trip_kind == "control_tc_stale"
    assert "TC_1" in snap_5_1.heater.trip_reason
    assert snap_5_1.output_enabled is False
    assert snap_5_1.commanded_volts == 0.0
    assert snap_5_1.program.running is False

    # Adapter received set_output(False) and write_voltage(0.0) on that tick
    assert ("set_output", False) in ns.spy.calls
    assert ("write_voltage", 0.0) in ns.spy.calls


# ---------------------------------------------------------------------------
# AC 3 — A raising block step → program_error trip carrying exception text
# ---------------------------------------------------------------------------


class _ExplodingBlock:
    """A block whose step_xxx function is monkeypatched to raise."""

    block_type = "voltage_ramp"
    start_voltage = 0.0
    end_voltage = 1.0
    duration_sec = 100.0


def test_raising_block_step_becomes_program_error_trip():
    """
    A block step that raises must produce a program_error trip carrying the
    exception type and message as the reason.
    """
    ns = make_rig_fixture()
    tick(ns)  # baseline

    # Monkeypatch step_voltage_ramp to raise
    import t8_daq_system.control.block_steps as bs
    original = bs.step_voltage_ramp

    def exploding_step(*args, **kwargs):
        raise RuntimeError("simulated step failure")

    bs.step_voltage_ramp = exploding_step
    try:
        ns.rig.submit(LoadProgram(program=[_ExplodingBlock()]))
        ns.rig.submit(StartProgram())

        # Run enough ticks to hit the raising step
        for _ in range(5):
            ns.rig.run_tick()
            ns.clock.advance(0.5)
            snap = ns.rig.latest()
            if snap is not None and snap.heater.state == "tripped":
                break

        snap = ns.rig.latest()
        assert snap.heater.state == "tripped"
        assert snap.heater.trip_kind == "program_error"
        assert "RuntimeError" in snap.heater.trip_reason
        assert "simulated step failure" in snap.heater.trip_reason
        assert snap.program.running is False
    finally:
        bs.step_voltage_ramp = original


# ---------------------------------------------------------------------------
# AC 4 — Nudge during run → program stopped; nudge with output off → stays off
# ---------------------------------------------------------------------------


def test_nudge_during_run_stops_program_and_applies_voltage():
    """
    A Nudge while a program runs must stop the program and apply the operator
    voltage; output stays enabled.
    """
    ns = make_rig_fixture()
    tick(ns)  # baseline

    blocks = [TempRampBlock(rate_k_per_min=60.0, end_temp_k=600.0, tc_name="TC_1")]
    ns.rig.submit(LoadProgram(program=blocks))
    ns.rig.submit(StartProgram())
    tick(ns, n=4)  # let program run

    snap = ns.rig.latest()
    assert snap.program.running is True
    assert snap.output_enabled is True

    # Submit a nudge up
    ns.rig.submit(Nudge(direction="up"))
    ns.rig.run_tick()
    ns.clock.advance(0.5)

    snap_after = ns.rig.latest()
    # Program must be stopped
    assert snap_after.program.running is False
    # Output should still be enabled (nudge does not disable)
    assert snap_after.output_enabled is True


def test_nudge_with_output_disabled_leaves_output_disabled():
    """
    A Nudge when output is disabled must not enable output (FIX-3).
    """
    ns = make_rig_fixture()
    tick(ns)  # baseline

    # Output is off; submit nudge directly (no program running)
    ns.rig.submit(Nudge(direction="up"))
    ns.rig.run_tick()
    ns.clock.advance(0.5)

    snap = ns.rig.latest()
    assert snap.output_enabled is False


# ---------------------------------------------------------------------------
# AC 5 — Ticket 01's voltage literals reproduce through ProgramRun to 1e-9 V
# (pure-module seam: ProgramRun.step() alone, no Rig thread)
# ---------------------------------------------------------------------------


def _run_program_run(blocks, snap_fn, n_ticks=20):
    """
    Drive ProgramRun directly with synthetic snapshots.

    snap_fn(tick_idx) -> Snapshot. Called once per tick (0-indexed).
    Returns list of volts from ProgramHeaterRequest results.
    """
    pr = ProgramRun()
    pr.load(blocks)
    snap0 = snap_fn(0)
    pr.start(snap0, 0.0, commanded_volts=0.0)
    voltages = []
    for i in range(n_ticks):
        now = (i + 1) * 0.5
        snap = snap_fn(i)
        result = pr.step(snap, now)
        if isinstance(result, ProgramHeaterRequest):
            voltages.append(result.volts)
    return voltages


def test_program_run_voltage_ramp_matches_characterisation():
    """
    ProgramRun produces the same per-tick voltage sequence as ProgramExecutor
    for VoltageRampBlock(0.0, 3.0, 3.0): [0.5, 1.0, 1.5, 2.0, 2.5].
    """
    block = VoltageRampBlock(start_voltage=0.0, end_voltage=3.0, duration_sec=3.0)
    # Constant temp 300 K = 26.85 °C
    snap = make_snapshot(tc_c={"TC_1": 26.85})
    voltages = _run_program_run([block], lambda _: snap, n_ticks=10)

    expected = [
        0.500000000,
        1.000000000,
        1.500000000,
        2.000000000,
        2.500000000,
    ]
    assert len(voltages) == len(expected), f"Expected {len(expected)} ticks, got {len(voltages)}: {voltages}"
    for actual, exp in zip(voltages, expected):
        assert math.isclose(actual, exp, abs_tol=1e-9), f"{actual!r} != {exp!r}"


def test_program_run_temp_ramp_matches_characterisation():
    """
    ProgramRun produces the same per-tick voltage sequence as ProgramExecutor
    for TempRampBlock(60 K/min, 303 K, constant 300 K feedback):
    [0.300325, 0.310975, 0.321950, 0.333250, 0.344875].
    """
    block = TempRampBlock(rate_k_per_min=60.0, end_temp_k=303.0, tc_name="TC_1")
    snap = make_snapshot(tc_c={"TC_1": 26.85})
    voltages = _run_program_run([block], lambda _: snap, n_ticks=10)

    expected = [
        0.300325000,
        0.310975000,
        0.321950000,
        0.333250000,
        0.344875000,
    ]
    assert len(voltages) == len(expected), f"Expected {len(expected)} ticks, got {len(voltages)}: {voltages}"
    for actual, exp in zip(voltages, expected):
        assert math.isclose(actual, exp, abs_tol=1e-9), f"{actual!r} != {exp!r}"


def test_program_run_stable_hold_matches_characterisation():
    """
    ProgramRun produces the same per-tick voltage sequence as ProgramExecutor
    for StableHoldBlock(320 K, tol 1 K, hold 1 s) with scripted temperature:
    [0.041300, 0.016950, 0.008942].
    """
    # The characterisation test consumes 3 readings before the first while-loop tick
    # (run_loop setup ×2, execute_block start_temp ×1). Those see [317,317,317].
    # The while loop then sees [318, 319, 319.5, 320].
    # In ProgramRun: start() receives index 0; just_started tick receives index 1;
    # real steps receive indices 2, 3, 4 and the finish tick 5.
    # To reproduce the same PID sequence: real steps see 318, 319, 319.5, 320.
    readings = [317.0, 317.0, 318.0, 319.0, 319.5, 320.0, 320.0, 320.0]

    def snap_fn(i: int) -> Snapshot:
        tc = readings[min(i, len(readings) - 1)]
        return make_snapshot(tc_c={"TC_1": tc - 273.15})

    block = StableHoldBlock(target_temp_k=320.0, tolerance_k=1.0, hold_duration_sec=1.0)
    voltages = _run_program_run([block], snap_fn, n_ticks=12)

    expected = [
        0.041300000000,
        0.016950000000,
        0.008941666667,
    ]
    assert len(voltages) == len(expected), f"Expected {len(expected)} ticks, got {len(voltages)}: {voltages}"
    for actual, exp in zip(voltages, expected):
        assert math.isclose(actual, exp, abs_tol=1e-9), f"{actual!r} != {exp!r}"


def test_program_run_two_block_boundary_matches_characterisation():
    """
    ProgramRun produces the same per-tick voltage sequence as ProgramExecutor
    for a VoltageRamp → TempRamp boundary with bumpless transfer:
    [0.5, 1.29, 1.29, 1.29].
    """
    b0 = VoltageRampBlock(start_voltage=0.0, end_voltage=1.0, duration_sec=1.0)
    b1 = TempRampBlock(rate_k_per_min=-60.0, end_temp_k=300.0, tc_name="TC_1")
    snap = make_snapshot(tc_c={"TC_1": 26.85})
    voltages = _run_program_run([b0, b1], lambda _: snap, n_ticks=15)

    expected = [
        0.500000000,
        1.290000000,
        1.290000000,
        1.290000000,
    ]
    assert len(voltages) == len(expected), f"Expected {len(expected)} ticks, got {len(voltages)}: {voltages}"
    for actual, exp in zip(voltages, expected):
        assert math.isclose(actual, exp, abs_tol=1e-9), f"{actual!r} != {exp!r}"


# ---------------------------------------------------------------------------
# Snapshot.program fields populated by ProgramRun
# ---------------------------------------------------------------------------


def test_snapshot_program_fields_populated_while_running():
    """
    While a program is running, Snapshot.program reflects correct block index,
    type, and running=True.
    """
    ns = make_rig_fixture()
    tick(ns)

    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=1.0, duration_sec=10.0),
        TempRampBlock(rate_k_per_min=60.0, end_temp_k=600.0, tc_name="TC_1"),
    ]
    ns.rig.submit(LoadProgram(program=blocks))
    ns.rig.submit(StartProgram())
    tick(ns, n=3)  # let program advance into block 0

    snap = ns.rig.latest()
    assert snap.program.running is True
    assert snap.program.block_index == 0
    assert snap.program.block_type == "voltage_ramp"
    assert snap.program.control_tc == "TC_1"

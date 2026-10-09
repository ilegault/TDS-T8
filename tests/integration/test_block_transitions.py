"""
Layer 1: Block transition smoke tests.
Tests every 2-block and critical 3-block combination on Rig + SimulatedRig.

WHY THIS EXISTS
---------------
ADR 0002 / Ticket 10 moved Program execution from ProgramExecutor (threading + time.sleep)
onto the single Rig loop (ProgramRun + ManualClock + SimulatedRig). These tests verify
all 2-block combinations, 3-block sequences, the 27 permutations, and bumpless
power transfer across block boundaries on the target Rig architecture.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
import pytest

from t8_daq_system.control.heater_output import HeaterOutput
from t8_daq_system.control.program_block import (
    StableHoldBlock,
    TempRampBlock,
    VoltageRampBlock,
)
from t8_daq_system.control.program_run import ProgramRun
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.rig.adapter import RawReadings, RigAdapter
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import RunSettings, LoadProgram, StartProgram
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig

pytestmark = pytest.mark.integration


class CallSpyAdapter(RigAdapter):
    """Spy wrapper around RigAdapter to record call sequence and arguments."""

    def __init__(self, target: RigAdapter) -> None:
        self._target = target
        self.calls: list[object] = []
        self.override_tc_c: dict[str, float | None] | None = None

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
        r = self._target.read()
        if self.override_tc_c is not None:
            new_tc = dict(r.tc_c)
            new_tc.update(self.override_tc_c)
            return RawReadings(
                tc_c=new_tc,
                tc_raw_v=r.tc_raw_v,
                pressure_torr=r.pressure_torr,
                pressure_valid=r.pressure_valid,
                ps_volts=r.ps_volts,
                ps_amps=r.ps_amps,
                shutoff_readback=r.shutoff_readback,
            )
        return r

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


def make_rig_fixture(*, start_time: float = 100.0, initial_temp_k: float = 300.0) -> SimpleNamespace:
    """Build real Rig + SimulatedRig + ManualClock + ProgramRun + spy."""
    clock = ManualClock(start_time=start_time)
    sim = SimulatedRig(
        clock=clock,
        tc_names=["TC_1"],
        gauge_names=["FRG702_Chamber"],
    )
    sim._sim.reset(initial_temp_k)
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


def run_program_on_rig(fixture: SimpleNamespace, blocks: list, max_ticks: int = 200, dt: float = 0.5, fixed_temp_k: float | None = None):
    """
    Load and start program on rig, advance clock and tick until complete or max_ticks reached.
    Returns (completed, block_indices_seen).
    """
    rig = fixture.rig
    clock = fixture.clock

    if fixed_temp_k is not None:
        fixture.spy.override_tc_c = {"TC_1": fixed_temp_k - 273.15}

    # Establish baseline Snapshot
    clock.advance(dt)
    rig.run_tick()

    rig.submit(LoadProgram(blocks))
    rig.submit(StartProgram(settings=RunSettings(kp=0.014, ki=0.00078, kd=0.00845, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))

    block_indices = []
    completed = False

    for _ in range(max_ticks):
        clock.advance(dt)
        rig.run_tick()
        snap = rig.latest()
        if snap.program.running:
            if snap.program.block_index not in block_indices:
                block_indices.append(snap.program.block_index)
        else:
            if block_indices:  # ran and stopped
                completed = True
                break

    return completed, block_indices


# ── 2-block smoke tests ────────────────────────────────────────────────────────

@pytest.mark.parametrize("block_a,block_b", [
    (
        VoltageRampBlock(start_voltage=0.0, end_voltage=2.0, duration_sec=1),
        VoltageRampBlock(start_voltage=2.0, end_voltage=3.0, duration_sec=1),
    ),
    (
        VoltageRampBlock(start_voltage=0.0, end_voltage=2.0, duration_sec=1),
        StableHoldBlock(target_temp_k=300.0, tolerance_k=50.0, hold_duration_sec=0.1),
    ),
    (
        StableHoldBlock(target_temp_k=300.0, tolerance_k=50.0, hold_duration_sec=0.1),
        VoltageRampBlock(start_voltage=2.0, end_voltage=0.0, duration_sec=1),
    ),
    (
        StableHoldBlock(target_temp_k=300.0, tolerance_k=50.0, hold_duration_sec=0.1),
        StableHoldBlock(target_temp_k=300.0, tolerance_k=50.0, hold_duration_sec=0.1),
    ),
    (
        VoltageRampBlock(start_voltage=0.0, end_voltage=2.0, duration_sec=1),
        TempRampBlock(rate_k_per_min=600.0, end_temp_k=600.0, tc_name="TC_1"),
    ),
    (
        TempRampBlock(rate_k_per_min=600.0, end_temp_k=600.0, tc_name="TC_1"),
        VoltageRampBlock(start_voltage=2.0, end_voltage=0.0, duration_sec=1),
    ),
    (
        TempRampBlock(rate_k_per_min=600.0, end_temp_k=600.0, tc_name="TC_1"),
        # StableHold target at 300K
        StableHoldBlock(target_temp_k=300.0, tolerance_k=50.0, hold_duration_sec=0.1),
    ),
    (
        StableHoldBlock(target_temp_k=300.0, tolerance_k=50.0, hold_duration_sec=0.1),
        TempRampBlock(rate_k_per_min=600.0, end_temp_k=600.0, tc_name="TC_1"),
    ),
    (
        TempRampBlock(rate_k_per_min=600.0, end_temp_k=600.0, tc_name="TC_1"),
        TempRampBlock(rate_k_per_min=-600.0, end_temp_k=300.0, tc_name="TC_1"),
    ),
])
def test_two_block_transition(block_a, block_b):
    """Every 2-block combo: both blocks execute and program completes."""
    fix = make_rig_fixture(initial_temp_k=300.0)
    completed, block_indices = run_program_on_rig(fix, [block_a, block_b], max_ticks=100, fixed_temp_k=300.0)

    assert completed, "Program never completed"
    assert 0 in block_indices, "Block 0 never ran"
    assert 1 in block_indices, "Block 1 never ran"
    # Output shut-off was never commanded abnormally during normal run
    assert not fix.heater_output.is_latched, "HeaterOutput was tripped during normal run"


# ── 3-block regression tests ──────────────────────────────────────────────────

def test_voltage_ramp_tempramp_hold_rampdown():
    """
    BUG REGRESSION: [VoltageRamp(0->3V), TempRamp(ramp to 600K), VoltageRamp(3V->0V)]
    The ramp-down-after-hold case -- executor must run all 3 blocks.
    """
    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=3.0, duration_sec=1),
        TempRampBlock(rate_k_per_min=600.0, end_temp_k=600.0, tc_name="TC_1"),
        VoltageRampBlock(start_voltage=3.0, end_voltage=0.0, duration_sec=1),
    ]
    fix = make_rig_fixture(initial_temp_k=300.0)
    completed, block_indices = run_program_on_rig(fix, blocks, max_ticks=100, fixed_temp_k=300.0)

    assert completed, "Program never completed"
    assert block_indices == [0, 1, 2], f"Not all blocks ran: {block_indices}"
    assert not fix.heater_output.is_latched


def test_voltage_ramp_stablehold_rampdown():
    """[VoltageRamp, StableHold, VoltageRamp] -- hold then ramp-down without PID."""
    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=2.0, duration_sec=1),
        StableHoldBlock(target_temp_k=300.0, tolerance_k=50.0, hold_duration_sec=0.1),
        VoltageRampBlock(start_voltage=2.0, end_voltage=0.0, duration_sec=1),
    ]
    fix = make_rig_fixture(initial_temp_k=300.0)
    completed, block_indices = run_program_on_rig(fix, blocks, max_ticks=100, fixed_temp_k=300.0)

    assert completed
    assert block_indices == [0, 1, 2]
    assert not fix.heater_output.is_latched


def test_tempramp_stablehold_rampdown():
    """[TempRamp, StableHold, VoltageRamp] -- hold after PID."""
    blocks = [
        TempRampBlock(rate_k_per_min=600.0, end_temp_k=600.0, tc_name="TC_1"),
        StableHoldBlock(target_temp_k=600.0, tolerance_k=50.0, hold_duration_sec=0.1),
        VoltageRampBlock(start_voltage=2.0, end_voltage=0.0, duration_sec=1),
    ]
    fix = make_rig_fixture(initial_temp_k=600.0)
    completed, block_indices = run_program_on_rig(fix, blocks, max_ticks=100, fixed_temp_k=600.0)

    assert completed
    assert block_indices == [0, 1, 2]
    assert not fix.heater_output.is_latched


# ── Parametrized 3-block permutations ─────────────────────────────────────────

BLOCK_TYPES = ['V', 'H', 'T']  # Voltage ramp, Hold, TempRamp


def make_block(code, temp_k=300.0):
    if code == 'V':
        return VoltageRampBlock(start_voltage=0.0, end_voltage=2.0, duration_sec=1)
    elif code == 'H':
        return StableHoldBlock(target_temp_k=temp_k, tolerance_k=50.0, hold_duration_sec=0.1)
    else:  # 'T'
        return TempRampBlock(rate_k_per_min=600.0, end_temp_k=600.0, tc_name="TC_1")


@pytest.mark.parametrize("a,b,c", [
    (a, b, c)
    for a in BLOCK_TYPES
    for b in BLOCK_TYPES
    for c in BLOCK_TYPES
])
def test_three_block_all_permutations(a, b, c):
    """All 27 3-block permutations: program completes and all 3 blocks run."""
    temp_k = 600.0 if 'T' in [a, b, c] else 300.0
    blocks = [make_block(a, temp_k), make_block(b, temp_k), make_block(c, temp_k)]

    fix = make_rig_fixture(initial_temp_k=temp_k)
    completed, block_indices = run_program_on_rig(fix, blocks, max_ticks=150, fixed_temp_k=temp_k)

    assert completed, f"[{a},{b},{c}] program never completed"
    assert block_indices == [0, 1, 2], f"[{a},{b},{c}] not all blocks ran: {block_indices}"
    assert not fix.heater_output.is_latched, f"[{a},{b},{c}] HeaterOutput tripped"


# ── Between-block power-continuity regression ─────────────────────────────────

def test_no_power_dropout_between_blocks():
    """
    BUG REGRESSION: the power supply must NOT switch off between blocks.

    Two back-to-back closed-loop blocks with the measured temperature held far
    below setpoint, so the PID commands a substantial positive voltage the whole
    time. Previously each block boundary hard-reset the PID, and because
    compute() returns 0.0 on its first call the DAC dropped to ~0 V for a tick or
    more — the supply visibly turned off and back on. The bumpless transfer must
    keep the commanded voltage continuous across the boundary.
    """
    blocks = [
        TempRampBlock(rate_k_per_min=6000.0, end_temp_k=500.0, tc_name="TC_1"),
        TempRampBlock(rate_k_per_min=6000.0, end_temp_k=900.0, tc_name="TC_1"),
    ]
    fix = make_rig_fixture(initial_temp_k=300.0)
    rig = fix.rig
    clock = fix.clock

    clock.advance(0.5)
    rig.run_tick()

    rig.submit(LoadProgram(blocks))
    rig.submit(StartProgram(settings=RunSettings(kp=0.014, ki=0.00078, kd=0.00845, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))

    ticks = []  # (block_index, commanded_volts)

    for _ in range(80):
        clock.advance(0.5)
        # Keep simulated temp held cold (300K) so error is large and PID commands high voltage
        fix.sim._sim.reset(300.0)
        rig.run_tick()
        snap = rig.latest()
        if snap.program.running:
            ticks.append((snap.program.block_index, snap.commanded_volts))
        elif ticks:
            break

    b0 = [v for (bi, v) in ticks if bi == 0 and v > 0.0]
    b1 = [v for (bi, v) in ticks if bi == 1 and v > 0.0]
    assert b0, "block 0 produced no positive voltage ticks"
    assert b1, "block 1 produced no positive voltage ticks"

    end_b0 = b0[-1]
    assert end_b0 > 0.5, f"precondition: block 0 should command >0.5 V, got {end_b0:.3f}"

    # The first positive tick of block 1 must not collapse toward 0 V.
    first_b1_min = min(b1[:3])
    assert first_b1_min > end_b0 * 0.5, (
        f"power dropped at block boundary: block 0 ended at {end_b0:.3f} V but "
        f"block 1 started at {b1[:3]} V (min {first_b1_min:.3f} V)"
    )

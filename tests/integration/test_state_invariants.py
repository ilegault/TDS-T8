"""
Layer 4: State-sync invariant checker on Rig + SimulatedRig.

WHY THIS EXISTS
---------------
ADR 0002 / ADR 0003: All state originates from immutable Snapshots published
by the Rig loop each tick. These tests assert safety invariants across
VoltageRamp, StableHold, and TempRamp:
  1. block_index is monotonically non-decreasing
  2. block_index < len(blocks) while running
  3. When output is disabled, commanded voltage is 0.0 V (instant cutoff)
"""
from __future__ import annotations

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
    """Spy wrapper around RigAdapter to record calls and optionally override tc_c."""

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


class InvariantChecker:
    """
    Checks Snapshot invariants every tick.
    Violations are recorded; any violation fails the test.
    """

    def __init__(self, num_blocks: int):
        self.num_blocks = num_blocks
        self.violations: list[str] = []
        self._tick = 0
        self._last_block_index = -1

    def check(self, snap):
        tick = self._tick
        self._tick += 1

        prog = snap.program

        # Invariant 1: block_index is monotonically non-decreasing while running
        if prog.running:
            bi = prog.block_index
            if bi < self._last_block_index:
                self.violations.append(
                    f"tick={tick}: block_index went backwards {self._last_block_index} -> {bi}"
                )
            self._last_block_index = bi

            # Invariant 2: block_index < len(blocks) while running
            if bi >= self.num_blocks:
                self.violations.append(
                    f"tick={tick}: block_index={bi} >= len(blocks)={self.num_blocks} while running"
                )

        # Invariant 3: if heater output is disabled, commanded voltage must be 0.0 V
        if not snap.output_enabled and snap.commanded_volts > 0.0:
            self.violations.append(
                f"tick={tick}: commanded_volts={snap.commanded_volts:.2f}V but output is disabled"
            )

    def assert_no_violations(self):
        if self.violations:
            msg = "Invariant violations:\n" + "\n".join(f"  {v}" for v in self.violations)
            pytest.fail(msg)


def _run_with_invariants(blocks: list, temp_k: float = 300.0, max_ticks: int = 150):
    clock = ManualClock(start_time=100.0)
    sim = SimulatedRig(
        clock=clock,
        tc_names=["TC_1"],
        gauge_names=["FRG702_Chamber"],
    )
    spy = CallSpyAdapter(sim)
    spy.override_tc_c = {"TC_1": temp_k - 273.15}
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

    checker = InvariantChecker(num_blocks=len(blocks))

    # Baseline tick
    clock.advance(0.5)
    rig.run_tick()

    rig.submit(LoadProgram(blocks))
    rig.submit(StartProgram(settings=RunSettings(kp=0.014, ki=0.00078, kd=0.00845, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))

    ran = False
    for _ in range(max_ticks):
        clock.advance(0.5)
        rig.run_tick()
        snap = rig.latest()
        checker.check(snap)
        if snap.program.running:
            ran = True
        elif ran:
            break

    return checker


def test_invariants_voltage_ramp():
    blocks = [VoltageRampBlock(0.0, 3.0, 2), VoltageRampBlock(3.0, 0.0, 2)]
    checker = _run_with_invariants(blocks)
    checker.assert_no_violations()


def test_invariants_stable_hold():
    blocks = [
        VoltageRampBlock(0.0, 2.0, 1),
        StableHoldBlock(300.0, 50.0, 0.1),
        VoltageRampBlock(2.0, 0.0, 1),
    ]
    checker = _run_with_invariants(blocks)
    checker.assert_no_violations()


def test_invariants_temp_ramp():
    blocks = [
        TempRampBlock(rate_k_per_min=600.0, end_temp_k=600.0, tc_name="TC_1"),
        VoltageRampBlock(3.0, 0.0, 1),
    ]
    checker = _run_with_invariants(blocks, temp_k=300.0)
    checker.assert_no_violations()


def test_block_index_never_decreases():
    """block_index must only go forward."""
    blocks = [
        VoltageRampBlock(0.0, 1.0, 1),
        VoltageRampBlock(1.0, 2.0, 1),
        VoltageRampBlock(2.0, 3.0, 1),
        VoltageRampBlock(3.0, 0.0, 1),
    ]
    checker = _run_with_invariants(blocks)
    checker.assert_no_violations()

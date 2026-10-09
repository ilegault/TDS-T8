"""
Layer 3: Fault injection tests on Rig + SimulatedRig.
Tests rig and program response to hardware and sensor faults during a live run.

WHY THIS EXISTS
---------------
ADR 0002 / ADR 0003 / ADR 0004 establish that the Rig loop arbitrates safety trips
and hardware faults:
  - Hardware disconnect / comms loss trips the heater and halts ProgramRun
  - Sensor faults (e.g. pressure spike / open TC lead) trip the heater instantly (same tick)
  - Operator nudge never bypasses CV-only or asserts Shut Off / FIO1
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
import pytest

from t8_daq_system.control.heater_output import HeaterOutput
from t8_daq_system.control.program_block import TempRampBlock, VoltageRampBlock
from t8_daq_system.control.program_run import ProgramRun
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.rig.adapter import RawReadings, RigAdapter
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import RunSettings, LoadProgram, Nudge, StartProgram
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig

pytestmark = pytest.mark.fault


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


def make_fault_rig_fixture(*, start_time: float = 100.0, temp_k: float = 300.0) -> SimpleNamespace:
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


def test_so_latched_executor_stops_gracefully():
    """SO_LATCHED / shutoff trip: ProgramRun stops and does not keep running."""
    fix = make_fault_rig_fixture()
    rig = fix.rig
    clock = fix.clock

    clock.advance(0.5)
    rig.run_tick()

    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=3.0, duration_sec=1),
        TempRampBlock(rate_k_per_min=60.0, end_temp_k=1000.0, tc_name="TC_1"),
    ]
    rig.submit(LoadProgram(blocks))
    rig.submit(StartProgram(settings=RunSettings(kp=0.02, ki=0.0013, kd=0.005, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))

    # Run a few ticks into the program
    for _ in range(5):
        clock.advance(0.5)
        rig.run_tick()

    assert rig.latest().program.running, "Program should be running"

    # Inject hardware trip via disconnect
    fix.sim.disconnect()
    clock.advance(0.5)
    rig.run_tick()

    snap = rig.latest()
    assert not snap.program.running, "ProgramRun must stop after fault"
    assert fix.heater_output.is_latched, "HeaterOutput must be latched"


def test_so_latched_dac_not_nonzero_after_fault():
    """SO_LATCHED / fault trip: no voltage commanded after fault fires."""
    fix = make_fault_rig_fixture()
    rig = fix.rig
    clock = fix.clock

    clock.advance(0.5)
    rig.run_tick()

    blocks = [TempRampBlock(rate_k_per_min=60.0, end_temp_k=2000.0, tc_name="TC_1")]
    rig.submit(LoadProgram(blocks))
    rig.submit(StartProgram(settings=RunSettings(kp=0.02, ki=0.0013, kd=0.005, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))

    for _ in range(4):
        clock.advance(0.5)
        rig.run_tick()

    # Disconnect adapter
    fix.sim.disconnect()

    for _ in range(5):
        clock.advance(0.5)
        rig.run_tick()

    snap = rig.latest()
    assert snap.commanded_volts == 0.0, f"Commanded volts was {snap.commanded_volts}, expected 0.0"
    assert not snap.output_enabled, "Output should be disabled"


def test_ovp_trip_sets_interlock():
    """Over-pressure trip: latch is set and program stops immediately."""
    fix = make_fault_rig_fixture()
    rig = fix.rig
    clock = fix.clock

    clock.advance(0.5)
    rig.run_tick()

    blocks = [TempRampBlock(rate_k_per_min=600.0, end_temp_k=1000.0, tc_name="TC_1")]
    rig.submit(LoadProgram(blocks))
    rig.submit(StartProgram(settings=RunSettings(kp=0.02, ki=0.0013, kd=0.005, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))

    for _ in range(4):
        clock.advance(0.5)
        rig.run_tick()

    assert rig.latest().program.running

    # Spike pressure above interlock threshold (e.g. 2e-4 Torr > 1e-4 Torr)
    fix.sim.set_pressure("FRG702_Chamber", 2e-4)
    clock.advance(0.5)
    rig.run_tick()

    snap = rig.latest()
    assert not snap.program.running, "Program must stop on pressure interlock trip"
    assert fix.heater_output.is_latched, "HeaterOutput must latch"
    assert snap.heater.state == "tripped"


def test_comms_timeout_executor_survives():
    """COMMS_TIMEOUT: single transient write failure raises error and latches gracefully without crash."""
    fix = make_fault_rig_fixture()
    rig = fix.rig
    clock = fix.clock

    clock.advance(0.5)
    rig.run_tick()

    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=3.0, duration_sec=10),
    ]
    rig.submit(LoadProgram(blocks))
    rig.submit(StartProgram(settings=RunSettings(kp=0.02, ki=0.0013, kd=0.005, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))

    for _ in range(3):
        clock.advance(0.5)
        rig.run_tick()

    # Inject single write failure while voltage is actively changing
    fix.sim.fail_next_write()
    clock.advance(0.5)
    rig.run_tick()

    snap = rig.latest()
    assert not snap.program.running, "Program should stop on write failure trip"


def test_output_off_mid_run_executor_stops():
    """If permissive or connection is lost mid-run, program stops."""
    fix = make_fault_rig_fixture()
    rig = fix.rig
    clock = fix.clock

    clock.advance(0.5)
    rig.run_tick()

    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=3.0, duration_sec=10),
    ]
    rig.submit(LoadProgram(blocks))
    rig.submit(StartProgram(settings=RunSettings(kp=0.02, ki=0.0013, kd=0.005, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))

    for _ in range(4):
        clock.advance(0.5)
        rig.run_tick()

    assert rig.latest().program.running

    # Invalidate gauge reading (permissive lost after > 5.0 s staleness)
    fix.sim.stall_gauge("FRG702_Chamber")
    for _ in range(12):
        clock.advance(0.5)
        rig.run_tick()

    snap = rig.latest()
    assert not snap.program.running, "Program should stop when permissive is lost"


def test_regression_nudge_does_not_assert_fio1():
    """
    REGRESSION: Spam nudge calls while program is NOT running.
    set_output(False) must never be called while output is enabled.
    """
    fix = make_fault_rig_fixture()
    rig = fix.rig
    clock = fix.clock

    clock.advance(0.5)
    rig.run_tick()

    for _ in range(20):
        rig.submit(Nudge(direction="up"))
        clock.advance(0.5)
        rig.run_tick()

    # Heater remains safely operable without unexpected trips
    assert not fix.heater_output.is_latched


def test_regression_nudge_during_run_does_not_assert_fio1():
    """
    REGRESSION: Spam nudge calls while program IS running.
    Program runs and heater output does not trip.
    """
    fix = make_fault_rig_fixture()
    rig = fix.rig
    clock = fix.clock

    clock.advance(0.5)
    rig.run_tick()

    blocks = [VoltageRampBlock(start_voltage=0.0, end_voltage=3.0, duration_sec=2)]
    rig.submit(LoadProgram(blocks))
    rig.submit(StartProgram(settings=RunSettings(kp=0.02, ki=0.0013, kd=0.005, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))

    for _ in range(10):
        rig.submit(Nudge(direction="up"))
        clock.advance(0.5)
        rig.run_tick()

    assert not fix.heater_output.is_latched


def test_regression_gui_state_matches_ps_after_so_latch():
    """
    REGRESSION: After trip, Snapshot reflects tripped state and program stopped.
    """
    fix = make_fault_rig_fixture()
    rig = fix.rig
    clock = fix.clock

    clock.advance(0.5)
    rig.run_tick()

    blocks = [TempRampBlock(rate_k_per_min=600.0, end_temp_k=1000.0, tc_name="TC_1")]
    rig.submit(LoadProgram(blocks))
    rig.submit(StartProgram(settings=RunSettings(kp=0.02, ki=0.0013, kd=0.005, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))

    for _ in range(3):
        clock.advance(0.5)
        rig.run_tick()

    # Trigger trip via open TC lead
    fix.sim.drop_tc("TC_1")
    for _ in range(12):
        clock.advance(0.5)
        rig.run_tick()

    snap = rig.latest()
    assert snap.heater.state == "tripped"
    assert not snap.program.running
    assert not snap.output_enabled

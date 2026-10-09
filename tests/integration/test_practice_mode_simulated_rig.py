"""
tests/integration/test_practice_mode_simulated_rig.py

Integration tests for practice mode operating on the Simulated rig adapter (ticket rig-architecture-13).

WHY THIS EXISTS
---------------
ADR 0005 mandates that practice mode is nothing but the Rig running the Simulated
rig adapter. The real PID, feedforward, safety, Heater output and Run record run in
practice exactly as on hardware, with no synthetic demo voltage, no in-executor
thermal lag, and no practice_mode branches in control or safety code.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from t8_daq_system.control.heater_output import HeaterOutput
from t8_daq_system.control.program_block import TempRampBlock
from t8_daq_system.control.program_run import ProgramRun
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.data.data_logger import DataLogger
from t8_daq_system.data.run_record import RunRecord, build_header
from t8_daq_system.rig.adapter import RawReadings, RigAdapter
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import RunSettings, LoadProgram, SelectAdapter, StartProgram
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig

pytestmark = pytest.mark.integration

TC_NAMES = ["TC_1", "TC_2"]
GAUGE_NAMES = ["FRG702_Chamber"]
SAMPLE_RATE_MS = 500.0


def _read_event_names(csv_file: Path) -> list[str]:
    """Return list of event names from CSV."""
    events = []
    with open(csv_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = next(csv.reader([line]))
            if len(row) >= 2 and row[1].startswith("EVENT:"):
                events.append(row[1][len("EVENT:"):])
    return events


def _advance(rig: Rig, clock: ManualClock, n: int) -> None:
    """Advance clock by 0.5 s and run one tick, n times."""
    for _ in range(n):
        clock.advance(0.5)
        rig.run_tick()


def test_practice_run_uses_same_pipeline_as_hardware_path():
    """
    Practice run on SimulatedRig uses the same ProgramRun, HeaterOutput, and
    SafetyEvaluator as the T8 path. Asserted by behaviour: a trip cuts output
    instantly in the same tick and latches the heater off.
    """
    clock = ManualClock(start_time=0.0)
    sim = SimulatedRig(clock=clock, tc_names=TC_NAMES, gauge_names=GAUGE_NAMES)
    sim.connect()

    program_run = ProgramRun()
    heater_output = HeaterOutput()
    safety_eval = SafetyEvaluator()

    rig = Rig(
        adapter=sim,
        clock=clock,
        sample_rate_ms=SAMPLE_RATE_MS,
        heater_output=heater_output,
        safety_evaluator=safety_eval,
        program_run=program_run,
        tc_names=TC_NAMES,
        gauge_names=GAUGE_NAMES,
    )

    blocks = [TempRampBlock(rate_k_per_min=60.0, end_temp_k=600.0, tc_name="TC_1")]
    rig.submit_command(LoadProgram(program=blocks))
    _advance(rig, clock, 1)

    rig.submit_command(StartProgram(settings=RunSettings(kp=0.014, ki=0.00078, kd=0.00845, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))
    _advance(rig, clock, 4)

    snap = rig.latest()
    assert snap is not None
    assert snap.heater.state == "on"
    assert snap.output_enabled is True
    assert snap.commanded_volts > 0.0
    assert program_run.running is True

    # Inject trip: drop control thermocouple TC_1
    sim.drop_tc("TC_1")
    # Advance beyond stale allowance (5.0s)
    _advance(rig, clock, 11)

    snap_after = rig.latest()
    assert snap_after is not None
    assert snap_after.heater.state == "tripped"
    assert snap_after.heater.trip_kind == "control_tc_stale"
    assert snap_after.output_enabled is False
    assert snap_after.commanded_volts == 0.0
    assert heater_output.is_latched is True
    assert program_run.running is False


def test_simulated_tc_primary_only_and_others_room_temperature():
    """
    In SimulatedRig, only the primary control TC reflects the simulated specimen
    temperature; monitor TCs read room temperature (26.85 deg C).
    """
    clock = ManualClock(start_time=0.0)
    sim = SimulatedRig(clock=clock, tc_names=["TC_1", "TC_2"], gauge_names=GAUGE_NAMES, room_temp_c=26.85)
    sim.connect()
    sim.set_output(True)
    sim.write_voltage(4.0)

    # Advance clock and read multiple times so physics heats the sample
    for _ in range(20):
        clock.advance(0.5)
        readings = sim.read()

    assert readings.tc_c["TC_1"] is not None
    assert readings.tc_c["TC_1"] > 200.0, f"Primary TC should be heated, got {readings.tc_c['TC_1']}"
    assert readings.tc_c["TC_2"] == pytest.approx(26.85), (
        f"Non-primary TC should remain at room temperature, got {readings.tc_c['TC_2']}"
    )


class _DummyHardwareAdapter(RigAdapter):
    """Minimal dummy adapter representing hardware for adapter switching tests."""

    def __init__(self):
        self._connected = True

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def read(self) -> RawReadings:
        return RawReadings(
            tc_c={"TC_1": 25.0},
            tc_raw_v={"TC_1": 0.001},
            pressure_torr={"FRG702_Chamber": 1e-7},
            pressure_valid={"FRG702_Chamber": True},
            ps_volts=0.0,
            ps_amps=0.0,
            shutoff_readback=False,
        )

    def write_voltage(self, volts: float) -> None:
        pass

    def set_output(self, enabled: bool) -> None:
        pass

    def pin_current_limit(self) -> None:
        pass


def test_adapter_change_writes_event_rows(tmp_path: Path):
    """
    Switching adapters between hardware and simulated emits ADAPTER event rows
    in the CSV log via RunRecord.
    """
    clock = ManualClock(start_time=0.0)
    hw_adapter = _DummyHardwareAdapter()
    sim_adapter = SimulatedRig(clock=clock, tc_names=["TC_1"], gauge_names=["FRG702_Chamber"])

    rig = Rig(
        adapter=hw_adapter,
        clock=clock,
        sample_rate_ms=SAMPLE_RATE_MS,
        hardware_adapter=hw_adapter,
        practice_adapter=sim_adapter,
        tc_names=["TC_1"],
        gauge_names=["FRG702_Chamber"],
    )

    sensor_names = build_header(["TC_1"], ["FRG702_Chamber"], has_ps=True)
    logger_ = DataLogger(log_folder=str(tmp_path))
    logger_.start_logging(sensor_names)

    rr = RunRecord(
        logger_=logger_,
        tc_names=["TC_1"],
        gauge_names=["FRG702_Chamber"],
        t_unit="C",
        p_unit="mbar",
        sample_rate_ms=SAMPLE_RATE_MS,
        has_ps=True,
    )
    rr.start()
    rig.set_run_record(rr)

    # Initial tick on t8 hardware adapter
    _advance(rig, clock, 1)

    # Switch to simulated adapter
    rig.submit_command(SelectAdapter(practice=True))
    _advance(rig, clock, 1)

    # Switch back to t8 adapter
    rig.submit_command(SelectAdapter(practice=False))
    _advance(rig, clock, 1)

    rr.stop()
    logger_.stop_logging()

    csv_file = list(tmp_path.glob("*.csv"))[0]
    events = _read_event_names(csv_file)

    assert "ADAPTER t8" in events, f"Expected 'ADAPTER t8' in events: {events}"
    assert "ADAPTER simulated" in events, f"Expected 'ADAPTER simulated' in events: {events}"

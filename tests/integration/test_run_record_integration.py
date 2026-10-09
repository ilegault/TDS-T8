"""
tests/integration/test_run_record_integration.py

Integration tests: RunRecord driven by the Rig loop (ticket rig-architecture-11).

WHY THIS EXISTS
---------------
AC 4 of ticket 11 requires that a three-block run produces one data row per
sample_rate_ms and the expected event rows, and that a trip writes a TRIP event
and subsequent rows carry Trip_Reason.  These assertions exercise the full path:
Rig loop → ProgramRun → HeaterOutput → SimulatedRig → Snapshot → RunRecord.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest

from t8_daq_system.control.heater_output import HeaterOutput
from t8_daq_system.control.program_block import VoltageRampBlock
from t8_daq_system.control.program_run import ProgramRun
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.data.data_logger import DataLogger
from t8_daq_system.data.run_record import RunRecord, build_header
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import RunSettings, LoadProgram, StartProgram
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig

pytestmark = pytest.mark.integration

TC_NAMES = ["TC_1"]
GAUGE_NAMES = ["FRG702_Chamber"]
SAMPLE_RATE_MS = 500.0  # tick period = min(0.5, 0.5) = 0.5 s → one row per tick


def _make_fixture(tmp_path: Path) -> tuple[Rig, RunRecord, DataLogger, ManualClock, SimulatedRig, ProgramRun]:
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

    sensor_names = build_header(TC_NAMES, GAUGE_NAMES, has_ps=True)
    logger_ = DataLogger(log_folder=str(tmp_path))
    logger_.start_logging(sensor_names)

    rr = RunRecord(
        logger_=logger_,
        tc_names=TC_NAMES,
        gauge_names=GAUGE_NAMES,
        t_unit="C",
        p_unit="mbar",
        sample_rate_ms=SAMPLE_RATE_MS,
        has_ps=True,
    )
    rig.set_run_record(rr)
    rr.start()

    return rig, rr, logger_, clock, sim, program_run


def _advance(rig: Rig, clock: ManualClock, n: int) -> None:
    """Advance clock by 0.5 s and run one tick, n times."""
    for _ in range(n):
        clock.advance(0.5)
        rig.run_tick()


def _count_data_rows(csv_file: Path) -> int:
    count = 0
    with open(csv_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("Timestamp"):
                continue
            row = next(csv.reader([line]))
            if not row:
                continue
            if len(row) >= 2 and row[1].startswith("EVENT:"):
                continue
            try:
                datetime.fromisoformat(row[0])
                count += 1
            except ValueError:
                pass
    return count


def _read_event_names(csv_file: Path) -> list[str]:
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


def _read_data_rows(csv_file: Path) -> list[dict]:
    """Return all data rows as dicts keyed by column name."""
    rows = []
    headers = []
    with open(csv_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = next(csv.reader([line]))
            if not row:
                continue
            if row[0] == "Timestamp":
                headers = row
                continue
            if len(row) >= 2 and row[1].startswith("EVENT:"):
                continue
            try:
                datetime.fromisoformat(row[0])
            except ValueError:
                continue
            rows.append(dict(zip(headers, row)))
    return rows


# ── Test 1: three-block run, one row per sample_rate_ms ───────────────────────

def test_three_block_run_one_row_per_tick(tmp_path):
    """
    A three-block program (three voltage ramps) produces exactly N data rows
    for N ticks driven through the Rig, and BLOCK_START events for each block.
    """
    rig, rr, logger_, clock, sim, program_run = _make_fixture(tmp_path)

    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=1.0, duration_sec=1.0),
        VoltageRampBlock(start_voltage=1.0, end_voltage=2.0, duration_sec=1.0),
        VoltageRampBlock(start_voltage=2.0, end_voltage=0.0, duration_sec=1.0),
    ]

    rig.submit_command(LoadProgram(program=blocks))
    # Run one tick to establish first readings before starting
    _advance(rig, clock, 1)
    rig.submit_command(StartProgram(settings=RunSettings(kp=0.014, ki=0.00078, kd=0.00845, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))
    # Run enough ticks to complete all three blocks (each block ~4 control steps) + extra
    N_TICKS = 30
    _advance(rig, clock, N_TICKS)

    rr.stop()
    logger_.stop_logging()

    csv_file = list(tmp_path.glob("*.csv"))[0]

    # One row per tick: N_TICKS + 1 (the pre-start tick)
    data_rows = _count_data_rows(csv_file)
    assert data_rows == N_TICKS + 1, (
        f"Expected {N_TICKS + 1} data rows (one per tick), got {data_rows}"
    )

    # At least three BLOCK_START events
    event_names = _read_event_names(csv_file)
    block_starts = [e for e in event_names if e.startswith("BLOCK_START")]
    assert len(block_starts) >= 3, (
        f"Expected at least 3 BLOCK_START events, got {block_starts}"
    )

    # PROGRAM_COMPLETE event
    assert "PROGRAM_COMPLETE" in event_names, (
        f"Expected PROGRAM_COMPLETE in events, got {event_names}"
    )


# ── Test 2: trip writes TRIP event and updates Trip_Reason on subsequent rows ──

def test_trip_writes_event_and_trip_reason_on_rows(tmp_path):
    """
    A pressure_high trip causes a TRIP event row and Trip_Reason populated
    on all subsequent data rows while the heater is latched.
    """
    rig, rr, logger_, clock, sim, program_run = _make_fixture(tmp_path)

    blocks = [VoltageRampBlock(start_voltage=0.0, end_voltage=2.0, duration_sec=10.0)]
    rig.submit_command(LoadProgram(program=blocks))
    _advance(rig, clock, 1)
    rig.submit_command(StartProgram(settings=RunSettings(kp=0.014, ki=0.00078, kd=0.00845, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)))
    # Run a few ticks with normal pressure
    _advance(rig, clock, 4)

    # Inject pressure_high trip
    sim.set_pressure(GAUGE_NAMES[0], 1e-3)  # 1e-3 Torr > 1e-4 Torr threshold
    _advance(rig, clock, 2)

    rr.stop()
    logger_.stop_logging()

    csv_file = list(tmp_path.glob("*.csv"))[0]

    # There must be a TRIP pressure_high event
    event_names = _read_event_names(csv_file)
    trip_events = [e for e in event_names if e.startswith("TRIP")]
    assert trip_events, f"Expected TRIP event in {event_names}"
    assert any("pressure_high" in e for e in trip_events), (
        f"Expected TRIP pressure_high, got {trip_events}"
    )

    # Data rows after the trip must have Trip_Reason populated (non-empty)
    data_rows = _read_data_rows(csv_file)
    tripped_rows = [r for r in data_rows if r.get("Heater_State") == "tripped"]
    assert tripped_rows, "Expected at least one row with Heater_State=tripped"
    for row in tripped_rows:
        assert row.get("Trip_Reason", ""), (
            f"Tripped row has empty Trip_Reason: {row}"
        )

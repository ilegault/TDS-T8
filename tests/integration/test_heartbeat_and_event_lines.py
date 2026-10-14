"""
Ticket 29: heartbeat and event lines in the Diagnostic log, sized for 8-hour runs.

WHY THIS EXISTS
---------------
ADR 0008 makes the Diagnostic log the record of a deployed run. An 8-hour run must
produce about a thousand INFO lines: one heartbeat per interval plus one line per
transition, trip, start and stop. These tests drive a real Rig + SimulatedRig +
ManualClock + RunRecord and read the session log file written under tmp_path.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from t8_daq_system.control.heater_output import HeaterOutput
from t8_daq_system.control.program_block import StableHoldBlock, TempRampBlock
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.data.data_logger import DataLogger
from t8_daq_system.data.run_record import RunRecord, build_header
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import LoadProgram, StartProgram
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig
from tests.run_settings_helper import make_program_run, make_run_settings

pytestmark = pytest.mark.integration

TC_NAMES = ["TC_1"]
GAUGE_NAMES = ["FRG702_Chamber"]
HEARTBEAT_S = 30
EIGHT_HOURS_S = 8 * 3600


class _SessionLog:
    """A root-logger file handler writing the session log under tmp_path."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handler = logging.FileHandler(path, encoding="utf-8")
        self._handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        self._root = logging.getLogger()
        self._old_level = self._root.level

    def __enter__(self) -> "_SessionLog":
        self._root.addHandler(self._handler)
        self._root.setLevel(logging.INFO)
        return self

    def __exit__(self, *exc) -> None:
        self._root.removeHandler(self._handler)
        self._root.setLevel(self._old_level)
        self._handler.close()

    def lines(self) -> list[str]:
        return self.path.read_text(encoding="utf-8").splitlines()


def _make_fixture(tmp_path: Path):
    clock = ManualClock(start_time=0.0)
    sim = SimulatedRig(clock=clock, tc_names=TC_NAMES, gauge_names=GAUGE_NAMES)
    sim.connect()
    rig = Rig(
        adapter=sim,
        clock=clock,
        sample_rate_ms=500.0,
        heater_output=HeaterOutput(),
        safety_evaluator=SafetyEvaluator(),
        program_run=make_program_run(),
        tc_names=TC_NAMES,
        gauge_names=GAUGE_NAMES,
    )
    data_logger = DataLogger(log_folder=str(tmp_path))
    data_logger.start_logging(build_header(TC_NAMES, GAUGE_NAMES, has_ps=True))
    rr = RunRecord(
        logger_=data_logger,
        tc_names=TC_NAMES,
        gauge_names=GAUGE_NAMES,
        t_unit="C",
        p_unit="mbar",
        sample_rate_ms=60_000.0,
        has_ps=True,
        heartbeat_interval_s=HEARTBEAT_S,
    )
    rig.set_run_record(rr)
    rr.start()
    return rig, rr, data_logger, clock, sim


def _tick(rig: Rig, clock: ManualClock, n: int) -> None:
    for _ in range(n):
        clock.advance(0.5)
        rig.run_tick()


def _start(rig, clock, blocks, **settings) -> None:
    rig.submit_command(LoadProgram(program=blocks))
    _tick(rig, clock, 1)
    rig.submit_command(StartProgram(settings=make_run_settings(**settings)))
    _tick(rig, clock, 3)


def _finish(rr, data_logger) -> None:
    rr.stop()
    data_logger.stop_logging()


def test_eight_hour_run_writes_a_readable_number_of_lines(tmp_path):
    rig, rr, data_logger, clock, _ = _make_fixture(tmp_path)
    blocks = [
        TempRampBlock(rate_k_per_min=60.0, end_temp_k=700.0, tc_name="TC_1"),
        StableHoldBlock(target_temp_k=700.0, tolerance_k=5.0, hold_duration_sec=EIGHT_HOURS_S),
    ]
    with _SessionLog(tmp_path / "session.log") as log:
        _start(rig, clock, blocks)
        _tick(rig, clock, EIGHT_HOURS_S * 2)
        _finish(rr, data_logger)
        lines = log.lines()

    assert len(lines) < 2000, len(lines)
    heartbeats = [ln for ln in lines if " HB " in ln]
    assert abs(len(heartbeats) - EIGHT_HOURS_S // HEARTBEAT_S) <= 2, len(heartbeats)


def test_heartbeat_line_carries_the_run_state(tmp_path):
    rig, rr, data_logger, clock, _ = _make_fixture(tmp_path)
    blocks = [TempRampBlock(rate_k_per_min=60.0, end_temp_k=700.0, tc_name="TC_1")]
    with _SessionLog(tmp_path / "session.log") as log:
        _start(rig, clock, blocks)
        _tick(rig, clock, 2 * 60 * 2)
        _finish(rr, data_logger)
        heartbeats = [ln for ln in log.lines() if " HB " in ln]

    assert heartbeats
    line = heartbeats[-1]
    for field in ("HB t=", "phase=block", "tc=", "sp=", "V=", "I=", "FF=", "P=", "D="):
        assert field in line, line


def test_soft_start_overcurrent_trip_is_one_error_line_with_its_reason(tmp_path):
    rig, rr, data_logger, clock, sim = _make_fixture(tmp_path)
    blocks = [TempRampBlock(rate_k_per_min=60.0, end_temp_k=1500.0, tc_name="TC_1")]
    with _SessionLog(tmp_path / "session.log") as log:
        _start(rig, clock, blocks, soft_start_threshold_c=200.0, soft_start_cap_a=40.0)
        sim.force_current(45.0)
        _tick(rig, clock, 1)
        reason = rig.latest().heater.trip_reason
        _finish(rr, data_logger)
        lines = log.lines()

    assert rig.latest().heater.trip_kind == "soft_start_overcurrent"
    errors = [ln for ln in lines if ln.startswith("ERROR") and "soft_start_overcurrent" in ln]
    assert len(errors) == 1, lines
    assert reason in errors[0]


def test_disabled_run_cap_warns_at_run_start(tmp_path):
    rig, rr, data_logger, clock, _ = _make_fixture(tmp_path)
    blocks = [TempRampBlock(rate_k_per_min=60.0, end_temp_k=900.0, tc_name="TC_1")]
    with _SessionLog(tmp_path / "session.log") as log:
        _start(rig, clock, blocks, run_cap_enabled=False)
        _finish(rr, data_logger)
        lines = log.lines()

    warnings = [ln for ln in lines if ln.startswith("WARNING") and "Run current cap is OFF" in ln]
    assert len(warnings) == 1, lines


def test_disabled_soft_start_cap_warns_at_run_start(tmp_path):
    rig, rr, data_logger, clock, _ = _make_fixture(tmp_path)
    blocks = [TempRampBlock(rate_k_per_min=60.0, end_temp_k=900.0, tc_name="TC_1")]
    with _SessionLog(tmp_path / "session.log") as log:
        _start(rig, clock, blocks, soft_start_cap_enabled=False)
        _finish(rr, data_logger)
        lines = log.lines()

    warnings = [
        ln for ln in lines if ln.startswith("WARNING") and "Soft-start current cap is OFF" in ln
    ]
    assert len(warnings) == 1, lines


def test_transitions_start_and_stop_are_info_lines(tmp_path):
    rig, rr, data_logger, clock, _ = _make_fixture(tmp_path)
    blocks = [TempRampBlock(rate_k_per_min=600.0, end_temp_k=400.0, tc_name="TC_1")]
    with _SessionLog(tmp_path / "session.log") as log:
        _start(rig, clock, blocks)
        _tick(rig, clock, 400)
        _finish(rr, data_logger)
        lines = log.lines()

    info = [ln for ln in lines if ln.startswith("INFO")]
    assert any("PROGRAM_START" in ln for ln in info), lines
    assert any("BLOCK_START 0" in ln for ln in info), lines
    assert any("SOFT_START_HANDOFF" in ln for ln in info), lines

"""
tests/integration/test_logging_volume.py

Log volume of a 60 s Rig run on the Simulated rig (ticket cold-start-and-traceability-27).

WHY THIS EXISTS
---------------
ADR 0008 makes the Diagnostic log the record of a deployed run. At INFO it must
hold state changes only, not one line per control tick, or the file buries the
events that matter. At DEBUG the per-tick detail must be there for diagnosis.
"""
from __future__ import annotations

import logging

import pytest

from t8_daq_system.control.heater_output import HeaterOutput
from t8_daq_system.control.program_block import TempRampBlock
from t8_daq_system.control.program_run import ProgramRun
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import LoadProgram, StartProgram
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig
from tests.run_settings_helper import make_run_settings

pytestmark = pytest.mark.integration

TC_NAMES = ["TC_1"]
GAUGE_NAMES = ["FRG702_Chamber"]
CONTROL_STEPS = 120  # 60 s at one control step per 0.5 s


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _run_60s(level: int) -> list[logging.LogRecord]:
    root = logging.getLogger()
    collector = _Collector()
    old_level = root.level
    root.addHandler(collector)
    root.setLevel(level)
    try:
        clock = ManualClock(start_time=0.0)
        sim = SimulatedRig(clock=clock, tc_names=TC_NAMES, gauge_names=GAUGE_NAMES)
        sim.connect()
        rig = Rig(
            adapter=sim,
            clock=clock,
            sample_rate_ms=500.0,
            heater_output=HeaterOutput(),
            safety_evaluator=SafetyEvaluator(),
            program_run=ProgramRun(),
            tc_names=TC_NAMES,
            gauge_names=GAUGE_NAMES,
        )
        rig.submit_command(
            LoadProgram(program=[TempRampBlock(rate_k_per_min=60.0, end_temp_k=900.0, tc_name="TC_1")])
        )
        clock.advance(0.5)
        rig.run_tick()
        rig.submit_command(StartProgram(settings=make_run_settings()))
        for _ in range(CONTROL_STEPS):
            clock.advance(0.5)
            rig.run_tick()
    finally:
        root.removeHandler(collector)
        root.setLevel(old_level)
    return collector.records


def _under(records: list[logging.LogRecord], *prefixes: str) -> list[logging.LogRecord]:
    return [r for r in records if r.name.startswith(prefixes)]


def test_info_run_is_quiet_in_control_and_rig():
    records = _run_60s(logging.INFO)
    noisy = _under(records, "t8_daq_system.control", "t8_daq_system.rig")
    assert len(noisy) < 20, [r.getMessage() for r in noisy]


def test_debug_run_has_a_control_record_per_step():
    records = _run_60s(logging.DEBUG)
    control = _under(records, "t8_daq_system.control")
    assert len(control) >= CONTROL_STEPS

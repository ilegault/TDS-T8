"""
tests/integration/test_run_history.py

Run history is written only for live runs, and every record is traceable
(ticket cold-start-and-traceability-31, ADR 0007 point 7).

WHY THIS EXISTS
---------------
``logs/pid_runs.json`` in the dev tree held only pytest records because ProgramRun
built its logger on a default path and saved Simulated-rig runs.  Here the history
path is injected under ``tmp_path``; a TempRamp on the Simulated rig must leave it
untouched, and the same program through a live (non-Simulated) adapter must write
one record carrying run_id, build_id and adapter.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.integration.test_block_transitions import CallSpyAdapter
from tests.run_settings_helper import make_run_settings
from t8_daq_system.control.heater_output import HeaterOutput
from t8_daq_system.control.program_block import TempRampBlock
from t8_daq_system.control.program_run import ProgramRun
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import LoadProgram, StartProgram
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig

pytestmark = pytest.mark.integration


def _complete_temp_ramp(tmp_path, *, live: bool) -> SimpleNamespace:
    history = tmp_path / "pid_runs.json"
    clock = ManualClock(start_time=100.0)
    sim = SimulatedRig(clock=clock, tc_names=["TC_1"], gauge_names=["FRG702_Chamber"])
    sim._sim.reset(300.0)
    adapter = CallSpyAdapter(sim) if live else sim
    program_run = ProgramRun(
        pid_log_file=str(history), run_id="20261013_101500", build_id="test-build"
    )
    rig = Rig(
        adapter=adapter,
        clock=clock,
        sample_rate_ms=500,
        tc_names=["TC_1"],
        gauge_names=["FRG702_Chamber"],
        heater_output=HeaterOutput(),
        safety_evaluator=SafetyEvaluator(),
        program_run=program_run,
    )
    clock.advance(0.5)
    rig.run_tick()
    rig.submit(LoadProgram([TempRampBlock(rate_k_per_min=600.0, end_temp_k=330.0, tc_name="TC_1")]))
    rig.submit(StartProgram(settings=make_run_settings()))
    started = False
    completed = False
    for _ in range(600):
        clock.advance(0.5)
        rig.run_tick()
        running = rig.latest().program.running
        started = started or running
        if started and not running:
            completed = True
            break
    return SimpleNamespace(history=history, program_run=program_run, completed=completed)


def test_simulated_rig_run_is_not_saved_to_history(tmp_path):
    out = _complete_temp_ramp(tmp_path, live=False)
    assert out.completed
    assert (not out.history.exists()) or json.loads(out.history.read_text()) == []


def test_live_adapter_run_writes_one_traceable_record(tmp_path):
    out = _complete_temp_ramp(tmp_path, live=True)
    assert out.completed
    records = json.loads(out.history.read_text())
    assert len(records) == 1
    record = records[0]
    assert record["run_id"] == "20261013_101500"
    assert record["build_id"] == "test-build"
    assert record["adapter"] == "t8"
    assert record["suggestions"]

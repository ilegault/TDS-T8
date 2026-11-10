"""
tests/scenarios/harness.py

Scenario test execution harness for end-to-end program runs (ticket 42).

WHY THIS EXISTS
---------------
Previously, tests asserted unit or integration properties by poking values
or asserting isolated transitions, but no test ran complete programs from cold
start to completion with production settings. As a result, trips that occur during
realistic ramp-up went undetected.

This module provides run_scenario() to execute whole programs against the
calibrated SimulatedRig (ADR 0005) with ManualClock, HeaterOutput (ADR 0003),
SafetyEvaluator, and ProgramRun, observing trips, peaks, and completion metrics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from t8_daq_system.control.heater_output import HeaterOutput
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import LoadProgram, RunSettings, StartProgram
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig
from t8_daq_system.settings.run_settings import production_run_settings
from tests import run_settings_helper


@dataclass(frozen=True)
class ScenarioResult:
    """Frozen summary of a scenario run."""

    completed: bool
    trip_kind: str | None
    trip_reason: str | None
    t_end_s: float
    peak_amps: float
    peak_commanded_volts: float
    tc_c_at_end: float
    tc_c_at_trip: float | None


def run_scenario(
    blocks: Sequence[Any],
    settings: RunSettings | None = None,
    max_s: float = 3600.0,
    control_tc: str = "TC_1",
) -> ScenarioResult:
    """
    Run an end-to-end scenario with the given blocks.

    Builds the Rig exactly as test_run_record_integration._make_fixture does
    (real Rig, SimulatedRig, ManualClock, HeaterOutput, SafetyEvaluator,
    ProgramRun via tests.run_settings_helper.make_program_run), without the
    RunRecord/DataLogger.

    Submits LoadProgram, runs one tick, submits StartProgram, then ticks at
    0.5 s intervals until the program stops, the heater trips, or max_s is reached.
    """
    clock = ManualClock(start_time=0.0)
    tc_names = [control_tc]
    gauge_names = ["FRG702_Chamber"]

    sim = SimulatedRig(clock=clock, tc_names=tc_names, gauge_names=gauge_names)
    sim.connect()

    if run_settings_helper._pid_log_file is None:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        run_settings_helper.set_pid_log_file(tmp.name)

    program_run = run_settings_helper.make_program_run()
    heater_output = HeaterOutput()
    safety_eval = SafetyEvaluator()

    rig = Rig(
        adapter=sim,
        clock=clock,
        sample_rate_ms=500.0,
        heater_output=heater_output,
        safety_evaluator=safety_eval,
        program_run=program_run,
        tc_names=tc_names,
        gauge_names=gauge_names,
    )

    active_settings = settings if settings is not None else production_run_settings()

    rig.submit(LoadProgram(program=blocks))
    clock.advance(0.5)
    rig.run_tick()

    rig.submit(StartProgram(settings=active_settings))

    init_snap = rig.latest()
    peak_amps = init_snap.ps_amps if init_snap is not None else 0.0
    peak_commanded_volts = init_snap.commanded_volts if init_snap is not None else 0.0

    is_tripped = False
    is_stopped = False
    snap = init_snap

    while clock.now() < max_s:
        clock.advance(0.5)
        rig.run_tick()
        snap = rig.latest()
        assert snap is not None

        if snap.ps_amps > peak_amps:
            peak_amps = snap.ps_amps
        if snap.commanded_volts > peak_commanded_volts:
            peak_commanded_volts = snap.commanded_volts

        if snap.heater.state == "tripped":
            is_tripped = True
            break
        if not snap.program.running:
            is_stopped = True
            break

    assert snap is not None
    tc_end_val = snap.tc_c.get(control_tc)
    tc_c_at_end = float(tc_end_val) if tc_end_val is not None else float("nan")

    if is_tripped:
        completed = False
        trip_kind = snap.heater.trip_kind
        trip_reason = snap.heater.trip_reason
        tc_trip_val = snap.tc_c.get(control_tc)
        tc_c_at_trip: float | None = float(tc_trip_val) if tc_trip_val is not None else None
    elif is_stopped:
        completed = True
        trip_kind = None
        trip_reason = None
        tc_c_at_trip = None
    else:
        # Timed out at max_s without completing or tripping
        completed = False
        trip_kind = None
        trip_reason = None
        tc_c_at_trip = None

    return ScenarioResult(
        completed=completed,
        trip_kind=trip_kind,
        trip_reason=trip_reason,
        t_end_s=clock.now(),
        peak_amps=peak_amps,
        peak_commanded_volts=peak_commanded_volts,
        tc_c_at_end=tc_c_at_end,
        tc_c_at_trip=tc_c_at_trip,
    )

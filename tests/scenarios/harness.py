"""
Scenario test harness (ticket 42).

WHY THIS EXISTS
---------------
Previously, no test executed complete programs from cold to completion with the
settings the operator runs. Unit tests poked values or ran isolated blocks with
caps disabled.

The Scenario test harness provides `run_scenario()` to execute arbitrary block
sequences on the calibrated `SimulatedRig` using `production_run_settings()`
(ADR 0005, ADR 0006, ADR 0007). It captures metrics across the full run
(`peak_amps`, `peak_commanded_volts`, trip status) and returns a `ScenarioResult`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from tests.run_settings_helper import make_program_run
from t8_daq_system.control.heater_output import HeaterOutput
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import LoadProgram, RunSettings, StartProgram
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig
from t8_daq_system.settings.run_settings import production_run_settings


@dataclass(frozen=True)
class ScenarioResult:
    """Outcome and peak metrics of a scenario execution."""

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
    """Execute a block sequence in a simulated Rig from cold start.

    Parameters
    ----------
    blocks:
        Sequence of program blocks to execute.
    settings:
        RunSettings to freeze at StartProgram. Defaults to production_run_settings().
    max_s:
        Maximum simulated seconds to advance before timing out. Default 3600.0 s (1 hr).
    control_tc:
        Name of the primary control thermocouple. Default "TC_1".
    """
    if settings is None:
        settings = production_run_settings()

    tc_names = [control_tc]
    gauge_names = ["FRG702_Chamber"]
    sample_rate_ms = 500.0

    clock = ManualClock(start_time=0.0)
    sim = SimulatedRig(clock=clock, tc_names=tc_names, gauge_names=gauge_names)
    sim.connect()

    program_run = make_program_run()
    heater_output = HeaterOutput()
    safety_eval = SafetyEvaluator()

    rig = Rig(
        adapter=sim,
        clock=clock,
        sample_rate_ms=sample_rate_ms,
        heater_output=heater_output,
        safety_evaluator=safety_eval,
        program_run=program_run,
        tc_names=tc_names,
        gauge_names=gauge_names,
    )

    # 1. Submit LoadProgram and advance one tick
    rig.submit(LoadProgram(program=list(blocks)))
    clock.advance(0.5)
    rig.run_tick()

    # 2. Submit StartProgram
    rig.submit(StartProgram(settings=settings))

    peak_amps = 0.0
    peak_commanded_volts = 0.0
    tc_c_at_trip: float | None = None
    trip_kind: str | None = None
    trip_reason: str | None = None
    completed = False
    started = False

    # 3. Advance at 0.5 s per tick until stopped, tripped, or max_s
    while clock.now() < max_s:
        clock.advance(0.5)
        rig.run_tick()
        snap = rig.latest()
        if snap is None:
            continue

        if snap.ps_amps is not None and snap.ps_amps > peak_amps:
            peak_amps = snap.ps_amps
        if snap.commanded_volts is not None and snap.commanded_volts > peak_commanded_volts:
            peak_commanded_volts = snap.commanded_volts

        tc_val = snap.tc_c.get(control_tc)
        tc_c_current = float(tc_val) if tc_val is not None else 0.0

        if snap.program.running:
            started = True

        # Check trip condition
        if snap.heater.state == "tripped" or heater_output.is_latched:
            trip_kind = snap.heater.trip_kind or heater_output.active_trip_kind
            trip_reason = snap.heater.trip_reason or heater_output.active_trip_reason
            tc_c_at_trip = tc_c_current
            break

        # Check normal completion
        if started and not snap.program.running:
            completed = True
            break

    t_end_s = clock.now()
    final_snap = rig.latest()
    final_tc_val = final_snap.tc_c.get(control_tc) if final_snap is not None else None
    tc_c_at_end = float(final_tc_val) if final_tc_val is not None else 0.0

    return ScenarioResult(
        completed=completed,
        trip_kind=trip_kind,
        trip_reason=trip_reason,
        t_end_s=t_end_s,
        peak_amps=peak_amps,
        peak_commanded_volts=peak_commanded_volts,
        tc_c_at_end=tc_c_at_end,
        tc_c_at_trip=tc_c_at_trip,
    )

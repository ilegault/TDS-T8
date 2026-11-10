"""
tests/unit/test_limits_vs_field_runs.py
Contract tests verifying safety limits and current caps against real field runs (ticket 43).

WHY THIS EXISTS
---------------
ADR 0001 requires tests first.
In field runs, normal tungsten heating reaches peak currents between 143 A and 151 A.
Setting the Run current cap to 175 A ensures normal TDS experiments run to completion
without nuisance trips, while still catching runaways such as a thermocouple detachment.
The developer confirmed on 2026-11-10 that the final sample of 2026-03-28_tds_5k_per_min
(where TC fell 1454 -> 1378 °C while current surged to 179.9 A) was a TC detachment event.
This test guards against setting a cap that prematurely stops normal runs hours into operation.
"""
from __future__ import annotations

import pytest

from t8_daq_system.control.safety_monitor import evaluate_safety
from t8_daq_system.rig.snapshot import (
    HeaterStatus,
    ProgramStatus,
    Snapshot,
    SourceStatus,
)
from t8_daq_system.settings.run_settings import production_run_settings
from tests.field_runs import all_field_runs

pytestmark = pytest.mark.unit


def _make_snapshot(filament_c: float, ps_volts: float, ps_amps: float) -> Snapshot:
    tc_c = {"TC_1": filament_c}
    pressure_torr = {"FRG702_Chamber": 1e-6}
    source_age_s = {"TC_1": 0.0, "FRG702_Chamber": 0.0}
    program = ProgramStatus(
        running=True,
        phase="block",
        block_type="temp_ramp",
        control_tc="TC_1",
    )
    heater = HeaterStatus(state="on")
    labjack = SourceStatus(state="connected", message="OK")
    xgs = SourceStatus(state="connected", message="OK")
    return Snapshot(
        t=100.0,
        wall_time=1700000000.0,
        tc_c=tc_c,
        tc_raw_v={"TC_1": 0.001},
        pressure_torr=pressure_torr,
        source_age_s=source_age_s,
        ps_volts=ps_volts,
        ps_amps=ps_amps,
        commanded_volts=ps_volts,
        output_enabled=True,
        program=program,
        heater=heater,
        permissive_ok=True,
        permissive_reason=None,
        labjack=labjack,
        xgs=xgs,
        adapter="simulated",
    )


def test_only_the_tc_loss_sample_trips_a_current_cap():
    """Verify that across all historical field runs, only the TC-loss runaway trips a current cap.

    The developer confirmed (2026-11-10) that at the final sample of 2026-03-28_tds_5k_per_min,
    the control TC detached, causing PID runaway to 179.9 A. A Run current cap of 175 A must trip
    on that runaway sample and nowhere else across all field runs. This test is the guard against
    a cap that stops a normal run hours in.
    """
    settings = production_run_settings()
    tripped_samples: list[tuple[str, float]] = []
    tripping_details: list[str] = []

    last_t_2026_03_28 = None

    for run in all_field_runs():
        if run.name == "2026-03-28_tds_5k_per_min":
            last_t_2026_03_28 = run.t_s[-1]
        for t, temp, v, a in zip(run.t_s, run.filament_c, run.ps_volts, run.ps_amps):
            snap = _make_snapshot(filament_c=temp, ps_volts=v, ps_amps=a)
            trips = evaluate_safety(snap, run_settings=settings, control_tc="TC_1")
            cap_trips = [trip for trip in trips if trip.kind in ("run_overcurrent", "soft_start_overcurrent")]
            if cap_trips:
                tripped_samples.append((run.name, t))
                tripping_details.append(f"{run.name} at t={t}s with {a:.1f} A: {[tr.kind for tr in cap_trips]}")

    expected = [("2026-03-28_tds_5k_per_min", last_t_2026_03_28)]
    msg = f"Expected only TC-loss sample to trip, but got {len(tripped_samples)} trips: " + "; ".join(tripping_details)
    assert tripped_samples == expected, msg

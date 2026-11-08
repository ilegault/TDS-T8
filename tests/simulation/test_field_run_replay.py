"""
tests/simulation/test_field_run_replay.py
Tests verifying TungstenSim two-node model replay against real Field runs (ticket 41).

WHY THIS EXISTS
---------------
Practice mode and simulation previously used a single lumped node that responded
instantly and never passed ~80 A. The two-node model separates the filament
(carrying resistance and Ohmic heating) from the specimen thermocouple node.
These tests verify that replaying recorded field run voltages produces current
and TC traces matching field data within calibrated tolerances (RMS current <= 15%
of peak, RMS TC <= 50 K), and reproduces the filament-TC thermal lag.
"""
from __future__ import annotations

import math
import pytest

from t8_daq_system.rig.tungsten_model import TungstenSim
from tests.field_runs import all_field_runs, load_field_run

pytestmark = pytest.mark.simulation


@pytest.mark.parametrize("run", all_field_runs(), ids=lambda r: r.name)
def test_replay_current_tracks_field_run(run):
    """The RMS of (sim amps - recorded amps) over the run is <= 15% of peak current."""
    tc_c, amps = TungstenSim.replay(run.t_s, run.ps_volts, run.filament_c[0])
    assert len(amps) == len(run.ps_amps)
    rms_amps = math.sqrt(
        sum((s - r) ** 2 for s, r in zip(amps, run.ps_amps)) / len(run.ps_amps)
    )
    peak_current = max(run.ps_amps)
    assert rms_amps <= 0.15 * peak_current, (
        f"Run {run.name}: RMS current error {rms_amps:.2f} A exceeds 15% of peak "
        f"({0.15 * peak_current:.2f} A, peak={peak_current:.2f} A)"
    )


@pytest.mark.parametrize("run", all_field_runs(), ids=lambda r: r.name)
def test_replay_tc_tracks_field_run(run):
    """The RMS of (sim TC - recorded Filament_C) is <= 50 K."""
    tc_c, amps = TungstenSim.replay(run.t_s, run.ps_volts, run.filament_c[0])
    assert len(tc_c) == len(run.filament_c)
    rms_tc = math.sqrt(
        sum((s - r) ** 2 for s, r in zip(tc_c, run.filament_c)) / len(run.filament_c)
    )
    assert rms_tc <= 50.0, (
        f"Run {run.name}: RMS TC error {rms_tc:.2f} K exceeds 50 K"
    )


def test_filament_runs_hotter_than_tc_at_peak_current():
    """
    On 2026-04-15_ramp_hold_down, at the sample of peak recorded current,
    the simulated filament node is at least 500 K hotter than the simulated TC node.
    """
    run = load_field_run("2026-04-15_ramp_hold_down")
    peak_idx = run.ps_amps.index(max(run.ps_amps))
    sim = TungstenSim()
    sim.replay(run.t_s[: peak_idx + 1], run.ps_volts[: peak_idx + 1], run.filament_c[0])
    state = sim.get_state()
    fil_k = state["filament_temperature_k"]
    tc_k = state["temperature_k"]
    diff_k = fil_k - tc_k
    assert diff_k >= 500.0, (
        f"Simulated filament ({fil_k:.1f} K) is not >= 500 K hotter than TC ({tc_k:.1f} K) "
        f"at peak current sample (diff={diff_k:.1f} K)"
    )

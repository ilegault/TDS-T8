"""
tests/unit/test_field_runs.py
Contract tests for Field run fixtures (ticket 40).

WHY THIS EXISTS
---------------
ADR 0001 requires tests first. Field runs provide downsampled excerpts of real lab
runs so that the two-node simulator and safety limits are calibrated and checked
against real hardware traces rather than arbitrary mock data.

These tests assert:
1. All five required field runs exist, load cleanly, start at t_s = 0, and have strictly increasing timestamps.
2. Recorded peak currents match their manifest entries within 0.1 A, with 2026-03-28 reaching the 175 A ceiling.
3. Every checked-in fixture CSV is under 200 kB.
4. Cold-start transient (first 300 s) is kept at full recorded resolution (median gap <= 0.6 s),
   and subsequent downsampled data has median gap between 4.5 and 5.5 s.
"""
from __future__ import annotations

import pathlib
import statistics

from tests.field_runs import FIELD_RUN_NAMES, all_field_runs, load_field_run

EXPECTED_NAMES = [
    "2026-03-26_temp_ramp_1550",
    "2026-03-28_tds_5k_per_min",
    "2026-03-29_tds_unirradiated_33h",
    "2026-03-30_tds_irradiated_33h",
    "2026-04-15_ramp_hold_down",
]


def test_all_field_runs_are_the_five_listed():
    assert FIELD_RUN_NAMES == tuple(EXPECTED_NAMES)
    runs = all_field_runs()
    names = [r.name for r in runs]
    assert names == EXPECTED_NAMES
    for run in runs:
        assert len(run.t_s) > 0
        assert run.t_s[0] == 0.0
        assert all(t2 > t1 for t1, t2 in zip(run.t_s[:-1], run.t_s[1:]))


def test_peak_current_matches_manifest():
    runs = all_field_runs()
    for run in runs:
        peak_current = max(run.ps_amps)
        manifest_peak = run.manifest["peak_current_a"]
        assert abs(peak_current - manifest_peak) <= 0.1
        if run.name == "2026-03-28_tds_5k_per_min":
            assert peak_current >= 175.0


def test_fixture_files_are_small():
    fixtures_dir = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "field_runs"
    for name in EXPECTED_NAMES:
        csv_file = fixtures_dir / f"{name}.csv"
        assert csv_file.exists(), f"Missing fixture file: {csv_file}"
        assert csv_file.stat().st_size < 200_000, (
            f"{name}.csv exceeds 200 kB: {csv_file.stat().st_size} bytes"
        )


def test_cold_start_kept_at_full_resolution():
    runs = all_field_runs()
    for run in runs:
        gaps_early = [t2 - t1 for t1, t2 in zip(run.t_s[:-1], run.t_s[1:]) if t2 <= 300.0]
        gaps_late = [t2 - t1 for t1, t2 in zip(run.t_s[:-1], run.t_s[1:]) if t1 >= 300.0]
        assert len(gaps_early) > 0, f"{run.name}: no early points"
        assert len(gaps_late) > 0, f"{run.name}: no late points"
        median_early = statistics.median(gaps_early)
        median_late = statistics.median(gaps_late)
        assert median_early <= 0.6, f"{run.name}: early median gap is {median_early} s > 0.6 s"
        assert 4.5 <= median_late <= 5.5, (
            f"{run.name}: late median gap is {median_late} s not in [4.5, 5.5] s"
        )


def test_load_field_run_individual():
    for name in EXPECTED_NAMES:
        run = load_field_run(name)
        assert run.name == name
        assert isinstance(run.t_s, tuple)
        assert isinstance(run.filament_c, tuple)
        assert isinstance(run.ps_volts, tuple)
        assert isinstance(run.ps_amps, tuple)
        assert len(run.t_s) == len(run.filament_c) == len(run.ps_volts) == len(run.ps_amps)
        assert run.manifest["name"] == name
        assert run.manifest["control_tc"] == "Filament"

# 43: Run current cap fits real operation

**Status:** ready-for-developer

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 42

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0003, ADR 0006 (its amendment lands in ticket 46), AGENTS.md §2 (CV-only). `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## Decision needed before this ticket is claimed

The Run current cap defaults to 120 A (`t8_daq_system/settings/app_settings.py`
`_DEFAULTS["run_cap_a"]`), but normal runs on the current filament reach 139–144 A,
and the 2026-03-28 5 K/min TDS reached 180 A, the supply's ceiling. A fixed cap below
180 A trips healthy runs; one at 180 A adds nothing, because DAC1 is pinned at 180 A
(AGENTS.md §2). The developer picks one, writes it under `## Comments` with the date,
edits the criteria marked **(decision)** if the choice is not option A, and sets
`Status: ready-for-agent`.

- **A. Replace the Run cap with a low-resistance trip (planner's recommendation).**
  After Handoff, trip when measured current is above a floor (default 20 A) and
  measured resistance `ps_volts / ps_amps` is below a threshold (default 2.5 mΩ, half
  the 300 K resistance; the lowest resistance above 20 A in the five Field runs is
  5.77 mΩ, on 2026-04-15). That catches the shorted lead the cap was meant for and never
  trips a healthy filament, whose resistance only rises as it heats. New trip kind
  `low_resistance`; the Run cap toggle becomes this trip's toggle.
- **B. Raise the Run cap default** to a value the developer names.
- **C. Keep the Run cap, disabled by default.**

## What to build

The 2026-11-06 cold start (Field case from ticket 42) and every Field run finish
without a trip under **Production settings**, while a shorted lead still trips.

Requirements:
- Implement the decision in `t8_daq_system/control/safety_monitor.py`
  `evaluate_safety` (the "2b. Current caps" section) and `_DEFAULTS`. Any new setting
  follows AGENTS.md §5.6 steps 1–4 and travels in `RunSettings` (ADR 0007).
- The Soft-start current cap is unchanged.
- The trip reason names measured volts, amps, resistance (option A) and the control
  TC reading, as the current Run cap reason does.
- Update the module docstring's `WHY THIS EXISTS`.

Tests may fake: time (`ManualClock`); `SimulatedRig.force_current` for a shorted lead.
Must be real: `SafetyEvaluator`/`evaluate_safety`, `production_run_settings()`, the
Field run fixtures, the scenario harness.

## Acceptance criteria

- [ ] `test_field_case_2026_11_06_cold_start` (ticket 42) is rewritten in place under
      the same name: the same program with production settings now ends with
      `trip_kind is None`, and the docstring keeps the quoted lab `TRIP` line and
      states what was fixed.
- [ ] `test_field_runs_never_trip_current_limits` in `tests/unit/test_limits_vs_field_runs.py` (the limits-vs-reality guard),
      parametrised over `all_field_runs()`: every recorded sample is turned into a
      Snapshot with `program.running=True`, `program.phase="block"`,
      `ps_volts`/`ps_amps`/`tc_c` from the sample (build it as
      `tests/unit/test_safety_monitor.py` `_make_snapshot` does) and passed to
      `evaluate_safety` with `production_run_settings()`; no sample yields a trip of
      a current or resistance kind. The assertion message names the run, `t_s` and
      the trip reason.
- [ ] **(decision)** `test_shorted_lead_trips_low_resistance` and
      `test_low_resistance_trip_off_logs_warning` in `tests/unit/test_safety_monitor.py`: a shorted lead still trips —
      a Snapshot after Handoff with `ps_volts=0.05`, `ps_amps=50.0` (1 mΩ) yields one
      trip `kind="low_resistance"` whose reason contains `"1.0 mΩ"`; the same Snapshot
      with the toggle off yields none and the start of the run logs a WARNING that the
      trip is OFF.
- [ ] `test_tds_ramp_and_hold_completes` in `tests/scenarios/test_tds_programs.py`: `TempRampBlock(rate_k_per_min=5.0, end_temp_k=1273.15, tc_name="TC_1")`
      then `StableHoldBlock(target_temp_k=1273.15, tolerance_k=10.0, hold_duration_sec=120.0)`
      from cold, production settings: `completed is True`, `trip_kind is None`.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

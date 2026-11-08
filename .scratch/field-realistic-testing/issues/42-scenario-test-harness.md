# 42: Scenario test harness

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 39, 41

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0002, ADR 0003, ADR 0005, ADR 0006. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

No test today runs a whole program from cold to the end with the settings the
operator gets. Add **Scenario tests**: a harness that does exactly that on the
calibrated Simulated rig (ticket 41), and the first two scenarios, one of which
reproduces the 2026-11-06 lab trip as a **Field case**.

Requirements:
- `tests/scenarios/harness.py`: `run_scenario(blocks, settings=None, max_s=3600.0,
  control_tc="TC_1") -> ScenarioResult`. `settings=None` means
  `production_run_settings()` (ticket 38). Build the Rig exactly as
  `tests/integration/test_run_record_integration.py` `_make_fixture` does (real
  `Rig`, `SimulatedRig`, `ManualClock`, `HeaterOutput`, `SafetyEvaluator`,
  `ProgramRun` via `tests/run_settings_helper.make_program_run`), without the
  RunRecord/DataLogger. Submit `LoadProgram`, one tick, `StartProgram`, then tick at
  0.5 s (as `_advance` does) until the program stops, the heater trips, or `max_s`.
- `ScenarioResult` (frozen dataclass): `completed: bool`, `trip_kind: str | None`,
  `trip_reason: str | None`, `t_end_s`, `peak_amps`, `peak_commanded_volts`,
  `tc_c_at_end`, `tc_c_at_trip: float | None`.
- `tests/scenarios/` gets a pytest marker `scenario` registered in the pytest config
  (`pytest.ini`, beside the existing `integration` marker), applied with `pytestmark`. The scenarios still run in the default
  `pytest --tb=short -q`.
- Field case directory `tests/scenarios/field_cases/` with a `README.md` stating the
  rule: every lab failure gets its Diagnostic log `TRIP` line quoted in the test's
  docstring and a scenario that reproduces it.

Tests may fake: time (`ManualClock`). Must be real: `Rig`, `SimulatedRig` with the
calibrated `TungstenSim`, `ProgramRun`, `HeaterOutput`, `SafetyEvaluator`, and
`production_run_settings()` unless a scenario says otherwise.

## Acceptance criteria

- [ ] `test_field_case_2026_11_06_cold_start` in `tests/scenarios/field_cases/test_2026_11_06_cold_start.py`:
      `run_scenario([TempRampBlock(rate_k_per_min=30.0, end_temp_k=1500.0, tc_name="TC_1")])`
      with production settings. In this ticket it asserts the trip the lab saw:
      `trip_kind == "run_overcurrent"` and `tc_c_at_trip < 100.0`. Ticket 43 rewrites
      it in place to assert the fix. If the calibrated simulator does not reproduce the
      trip, escalate: that means ticket 41's model or the diagnosis is wrong.
- [ ] `test_low_power_ramp_and_hold_completes` in `tests/scenarios/test_low_power_programs.py`: a
      `TempRampBlock(rate_k_per_min=10.0, end_temp_k=373.15, tc_name="TC_1")` followed
      by `StableHoldBlock(target_temp_k=373.15, tolerance_k=5.0, hold_duration_sec=60.0)`
      (`t8_daq_system/control/program_block.py`) ends with `completed is True`, `trip_kind is None`, and `peak_amps` below the
      production `run_cap_a`.
- [ ] `test_harness_reports_a_trip` in `tests/unit/test_scenario_harness.py`: with `settings=make_run_settings(run_cap_enabled=True, run_cap_a=1.0)  # not production: proves a trip is reported`
      the harness returns `completed is False`, `trip_kind == "run_overcurrent"` and
      a `trip_reason` containing `"Run overcurrent"`.
- [ ] `test_scenario_marker_selects_the_scenarios_folder` (same file) runs
      `pytest -m scenario --collect-only -q` in a subprocess and asserts every collected
      node id starts with `tests/scenarios/` and at least two were collected.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

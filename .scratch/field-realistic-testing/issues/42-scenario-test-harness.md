# 42: Scenario test harness

**Status:** blocked

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

## Escalation — 2026-11-09
Repo: TDS-T8   Ticket: 42 Scenario test harness   Branch: ticket/field-realistic-testing-42-scenario-test-harness
Goal: Add Scenario tests to run whole programs on the calibrated Simulated rig with production settings, reproducing the 2026-11-06 lab trip as a Field case.

Attempt 1: Implemented `run_scenario()` in `tests/scenarios/harness.py`, `ScenarioResult`, `pytest.ini` marker, `test_harness_reports_a_trip`, `test_scenario_marker_selects_the_scenarios_folder`, `test_low_power_ramp_and_hold_completes`, and `test_field_case_2026_11_06_cold_start`.
Result: Unit tests and low power scenario passed. `test_field_case_2026_11_06_cold_start` did not trip at cold start (peak current in the first 120 s was only 72.5 A at commanded voltage 0.644 V). The run only tripped at `t = 2374.0 s` (~40 min into the ramp) when the specimen reached `tc_c_at_trip = 1254.3 °C`.

Attempt 2: Investigated thermal dynamics of ticket 41's calibrated `TungstenSim` (`C_FIL = 0.5 J/K`, `C_TC = 22.0 J/K`, `G_COUPLE = 0.13 W/K`).
Result: Because `C_FIL = 0.5 J/K` is very small, Ohmic heating heats the filament node almost instantly (~1 s), rapidly raising filament resistance from 5 mΩ to 14–30 mΩ. At 30 K/min ramp, the setpoint rises at 0.5 K/s and the TC node heats from 27 °C to 50 °C in 60 s, keeping PID error small and commanded voltage low, so current never exceeds ~73 A during cold start.

Attempt 3: Tested `C_FIL` sensitivity across candidates (e.g. `C_FIL = 20.0-30.0 J/K`, consistent with the ~30x thermal mass noted in `spec.md` line 48).
Result: With `C_FIL = 20.0 J/K`, `test_field_case_2026_11_06_cold_start` reproduces the exact lab trip at `t = 84.5 s`, `TC = 50.7 °C`, `peak_amps = 131.6 A` (< 100.0 °C), AND all 11 field run replay tests in `tests/simulation/test_field_run_replay.py` plus all tests in `tests/simulation/test_tungsten_model.py` and `tests/unit/test_simulated_rig.py` continue to pass with 0 failures.

Failing output:
```
tests/scenarios/field_cases/test_2026_11_06_cold_start.py:35: in test_field_case_2026_11_06_cold_start
    assert res.tc_c_at_trip < 100.0, f"Expected cold start trip with TC < 100 C, got {res.tc_c_at_trip:.1f} C"
E   AssertionError: Expected cold start trip with TC < 100 C, got 1254.3 C
E   assert 1254.2654889725832 < 100.0
E    +  where 1254.2654889725832 = ScenarioResult(completed=False, trip_kind='run_overcurrent', trip_reason='Run overcurrent: measured 120.0 A > cap 120.0 A (phase block, commanded 3.180 V, control TC TC_1 1254.3 °C); check filament and leads', t_end_s=2374.0, peak_amps=120.00579357644996, peak_commanded_volts=3.179671284199376, tc_c_at_end=1254.2654889725832, tc_c_at_trip=1254.2654889725832).tc_c_at_trip
```

Decision needed:
Per ticket 42 and AGENTS.md ("If the calibrated simulator does not reproduce the trip, escalate: that means ticket 41's model or the diagnosis is wrong"):
Should `TungstenSim.C_FIL` in `t8_daq_system/rig/tungsten_model.py` be updated (e.g. to 20.0 J/K) so the two-node simulator reproduces the cold-start transient under PID ramp while preserving replay tracking, or should the cold-start trip expectation / diagnosis be amended based on ticket 47 lab evidence?

# 41: Simulated rig is a calibrated two-node model

**Status:** blocked

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 40

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0005, ADR 0006. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

`TungstenSim` (`t8_daq_system/rig/tungsten_model.py`) is one lumped node, and
`SimulatedRig.read()` (`t8_daq_system/rig/simulated.py`) reports that node's
temperature as the primary TC. So simulated temperature follows current almost at
once, and current never passes about 80 A. On the real rig the TC lags far behind the
filament: on 2026-04-15 the supply passed 144 A at 4.17 V while the `Filament` TC read
about 127 °C. Make the simulator a two-node model and calibrate it against the Field
runs from ticket 40.

Requirements:
- `TungstenSim` gets two thermal nodes: a **filament** node that carries the
  resistance `R(T_filament)` and the Ohmic heating, and a **TC** node, coupled to the
  filament by a thermal conductance and with its own heat capacity and losses. Keep
  `step(voltage_v) -> (temperature_k, current_a)` where `temperature_k` is now the TC
  node, and keep `reset(T0)` setting both nodes. Add `filament_temperature_k` to
  `get_state()`.
- `SimulatedRig.read()` reports the TC node as the primary TC and computes `ps_amps`
  from the filament node's resistance.
- Add `TungstenSim.replay(t_s, volts, t0_c) -> (tc_c, amps)`: starting with both nodes
  at `t0_c`, step through the recorded voltage trace using each gap in `t_s` as `dt`
  (split into sub-steps of at most 0.5 s), returning the simulated TC (°C) and current
  at each recorded time. Pure: no clock, no Rig.
- Fit the constants by any offline method you like (a script under `scripts/` is fine;
  the fitted values are literals in the class, each with a comment naming its source).
  Update the class docstring's calibration targets and the module's `WHY THIS EXISTS`.
- If no physically sensible constants meet the tolerances below, do not widen them:
  escalate with the best errors you reached per Field run.
- Existing tests whose numbers change because of the new model are rewritten in place
  under the same name. No test is deleted.

Tests may fake: `ManualClock` for time. Must be real: `TungstenSim`, `SimulatedRig`,
the Field run fixtures via `tests/field_runs.py`.

## Acceptance criteria

- [ ] `test_replay_current_tracks_field_run` in `tests/simulation/test_field_run_replay.py`, parametrised over `all_field_runs()`:
      `replay(run.t_s, run.ps_volts, run.filament_c[0])`, then the RMS of
      `(sim amps − recorded amps)` over the run is at most 15 % of the run's recorded
      peak current.
- [ ] Same file, `test_replay_tc_tracks_field_run`, same parametrisation: the RMS of `(sim TC − recorded Filament_C)`
      is at most 50 K.
- [ ] Same file, `test_filament_runs_hotter_than_tc_at_peak_current`: on `2026-04-15_ramp_hold_down`, at the sample of peak recorded current,
      the simulated filament node is at least 500 K hotter than the simulated TC node
      (the lag the field data shows).
- [ ] Ticket 20's tests in `tests/unit/test_simulated_rig.py` still pass:
      `test_cold_specimen_at_small_voltage_draws_large_current` (cold
      `SimulatedRig` at 0.29 V reads `ps_amps > 40.0`) and `test_cold_resistance_matches_march_2026_logs`
      (`_resistance(300.0)` in [0.004, 0.006]), both unchanged.
      `test_current_at_6v_steady_state_is_within_rated_range` may be rewritten
      in place to compute current from the filament node; its [120, 180] A bound stays.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

## Escalation — 2026-11-08
Repo: TDS-T8   Ticket: 41 Simulated rig is a calibrated two-node model   Branch: ticket/field-realistic-testing-41-calibrated-two-node-simulator
Goal: Make the simulator a two-node model and calibrate it against the Field runs from ticket 40.
Attempt 1: Baseline two-node model (C_FIL=0.5 J/K, C_TC=8.0 J/K, G_COUPLE=0.08 W/K). Current RMS passed across all 5 runs (<= 15% peak), but TC RMS was 153 to 408 K due to uncalibrated thermal lag.
Attempt 2: High thermal coupling and slow TC node (C_TC=40.0 J/K, G_COUPLE=0.10 W/K, ALPHA=0.0026 /K). All 5 runs passed current RMS. Runs 0..3 passed TC RMS (<= 50 K: 44.6 K, 47.9 K, 39.7 K, 44.7 K) and 2026-04-15 peak thermal lag reached 533 K (>= 500 K). However, C_TC=40 was thermally too sluggish to cool in 100 s in `test_output_false_gives_zero_current_and_cools` (cooled TC was higher than hot TC due to residual heating).
Attempt 3: Balanced constants (C_TC=15.0 J/K, C_FIL=0.5 J/K, G_COUPLE=0.12 W/K, K_COND_TC=0.02 W/K, AREA_FIL=0.0012 m^2, AREA_TC=0.0003 m^2, ALPHA=0.0026 /K, R_COLD=0.0050 Ohm).
  - All existing unit and Rig tests pass (15/15 green).
  - 6.0 V steady state is 176.3 A (within [120, 180] A).
  - Cold 0.29 V current is 58 A (> 40 A).
  - Peak thermal lag on 2026-04-15 passes (515.5 K >= 500 K).
  - All 5 field runs pass current RMS (6.05 A, 5.19 A, 4.10 A, 3.92 A, 14.39 A, all <= 15% peak).
  - However, TC RMS on `2026-04-15_ramp_hold_down` is 472.6 K. Root cause: the test ended at t = 7875 s (at t=7879 s the Keysight shut off), but the fixture downsampled post-run data where the disconnected Keysight monitor pins floated to ~2.62 V and 78.7 A for 3046 s (t=7900..10946 s) while the TC cooled in the dark chamber to 62 °C. During the active experiment (t <= 7875 s), RMS TC error is 47.48 K (passing <= 50 K). In vacuum, 200 W (2.6 V) applied for 50 minutes cannot physically coexist with a 62 °C specimen. Runs 0, 1, 3 are also marginally over (55.4 K, 50.1 K, 59.3 K).

Failing output (exact, trimmed to the relevant lines):
```
AssertionError: Run 2026-04-15_ramp_hold_down: RMS TC error 472.64 K exceeds 50 K
assert 472.63582538906945 <= 50.0
AssertionError: Run 2026-03-26_temp_ramp_1550: RMS TC error 55.37 K exceeds 50 K
assert 55.37073986352773 <= 50.0
AssertionError: Run 2026-03-28_tds_5k_per_min: RMS TC error 50.14 K exceeds 50 K
assert 50.141886756020256 <= 50.0
AssertionError: Run 2026-03-30_tds_irradiated_33h: RMS TC error 59.33 K exceeds 50 K
assert 59.33092924290546 <= 50.0
```

Decision needed:
1. Should `tests/fixtures/field_runs/2026-04-15_ramp_hold_down.csv` be truncated at the run end (t = 7875 s when the Keysight shut off), or should `make_field_runs.py` stop downsampling when output is disabled?
2. Alternatively, should the TC RMS tolerance for `2026-04-15_ramp_hold_down` be assessed only over the active run (t <= 7875 s, where it achieves 47.48 K <= 50 K), and should the general tolerance be adjusted to ~60 K to accommodate runs 0, 1, 3?

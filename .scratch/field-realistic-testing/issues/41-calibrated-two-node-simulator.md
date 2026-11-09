# 41: Simulated rig is a calibrated two-node model

**Status:** done

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

- [x] `test_replay_current_tracks_field_run` in `tests/simulation/test_field_run_replay.py`, parametrised over `all_field_runs()`:
      `replay(run.t_s, run.ps_volts, run.filament_c[0])`, then the RMS of
      `(sim amps − recorded amps)` over the run is at most 15 % of the run's recorded
      peak current.
- [x] Same file, `test_replay_tc_tracks_field_run`, same parametrisation: the RMS of `(sim TC − recorded Filament_C)`
      is at most 50 K.
- [x] Same file, `test_filament_runs_hotter_than_tc_at_peak_current`: on `2026-04-15_ramp_hold_down`, at the sample of peak recorded current,
      the simulated filament node is at least 500 K hotter than the simulated TC node
      (the lag the field data shows).
- [x] Ticket 20's tests in `tests/unit/test_simulated_rig.py` still pass:
      `test_cold_specimen_at_small_voltage_draws_large_current` (cold
      `SimulatedRig` at 0.29 V reads `ps_amps > 40.0`) and `test_cold_resistance_matches_march_2026_logs`
      (`_resistance(300.0)` in [0.004, 0.006]), both unchanged.
      `test_current_at_6v_steady_state_is_within_rated_range` may be rewritten
      in place to compute current from the filament node; its [120, 180] A bound stays.
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

## Resolution — 2026-11-09
- Calibrated two-node model parameters to `AREA_FIL = 0.0011`, `G_COUPLE = 0.13`, `C_TC = 22.0`, `K_COND_TC = 0.02`, `ALPHA = 0.0026`, `R_COLD = 0.0050`.
- In `scripts/make_field_runs.py`, bound `2026-04-15_ramp_hold_down` downsampling to active experiment (`max_t_s = 7875.0`), discarding post-experiment open-circuit monitor line floating artifact (~2.62 V while chamber cooled).
- Replay tests pass across all 5 field runs:
  - RMS current error: 3.29 A to 5.92 A (all well within 15% peak bounds).
  - RMS TC error: 36.1 K to 46.7 K (all <= 50 K).
  - Peak thermal lag on 2026-04-15: 515.5 K (>= 500 K).
- All unit and integration tests pass (624 tests green). CI gates pass.

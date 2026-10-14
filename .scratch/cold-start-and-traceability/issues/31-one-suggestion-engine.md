# 31: One Suggestion engine

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 19, 26

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0007 (point 7). `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

Replace the two disagreeing suggestion sources with one correct, pure engine, and keep Run history clean.

Requirements:
- New pure module `t8_daq_system/control/suggestion_engine.py` with `run_metrics(run_log, rate_k_per_min, noise_band_k=2.0) -> dict` (overshoot K, settling s, oscillation count, rate-tracking error %) and `suggest(metrics, gains_in_use) -> Suggestion` holding suggested `kp`, `ki`, `kd` and one reason per changed gain. Rules, each a ±15 % step: rate-tracking error > 10 % → raise Ki; overshoot > 5 K → lower Kp; oscillations > 4 → raise Kd and lower Ki; settling > 120 s with overshoot ≤ 1 K → raise Kp. No rule fires → unchanged gains with reason `stable — no change`.
- Oscillations count only sign changes of error where |error| > `noise_band_k` on both sides of the change.
- `PIDRunLogger` (`t8_daq_system/control/temp_ramp_pid.py`) requires its `log_file` path (no default); `ProgramRun` receives it from the GUI. Delete `PIDRunLogger._generate_suggestions`; `ProgramRun._save_run_to_history` uses `run_metrics` and `suggest`. Records gain `run_id`, `build_id`, `adapter`. Runs on the Simulated rig are not saved.
- Every test that constructs `ProgramRun` or `PIDRunLogger` passes a file under `tmp_path`.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [x] Unit test: a run log oscillating ±1 K around setpoint gives an oscillation count of 0; ±5 K gives more than 0.
- [x] Unit test: metrics with 20 % rate-tracking error and no overshoot → suggested `ki` greater than the gains-in-use `ki`, with a reason containing `rate`.
- [x] Unit test: metrics with 8 K overshoot → suggested `kp` less than the gains-in-use `kp`.
- [x] Integration test: a completed TempRamp on SimulatedRig leaves the `tmp_path` history file absent or empty; the same program through a fake live adapter writes one record containing `run_id` and `adapter`.
- [x] A rule in `test_architecture_rules.py`: no call `PIDRunLogger()` without arguments exists under `t8_daq_system/` or `tests/`.
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

Summary (2026-10-14): new pure `control/suggestion_engine.py` (`run_metrics`, `suggest`, `Suggestion`) is the only suggestion source. `PIDRunLogger` requires `log_file`; `_generate_suggestions` and the popup's own maths are gone. `ProgramRun(pid_log_file, run_id=, build_id=)` saves only non-Simulated runs, with `run_id`, `build_id`, `adapter`, suggested gains and reasons. Oscillations 1 K vs 5 K, rate-error→Ki, overshoot→Kp: `tests/unit/test_suggestion_engine.py`. Simulated vs live history: `tests/integration/test_run_history.py`. No-arg `PIDRunLogger()` rule: `tests/unit/test_architecture_rules.py`. Tests build ProgramRun via `make_program_run()` (autouse conftest fixture points it at `tmp_path`).
Note: MainWindow did not construct a ProgramRun for its Rig at all; it now does, with the history file in the log folder and the real Build ID from `build_info.get_build_id()` (ticket 33). Re-based onto main after tickets 19-30, 33-35 landed; the heartbeat test builds its ProgramRun through `make_program_run()`. Bench: none.

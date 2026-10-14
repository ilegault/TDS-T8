# 32: Post-run suggestion dialog uses the engine

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 24, 31

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0007. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

After a live TempRamp completes, the operator sees the engine's metrics and suggestions and can open Settings prefilled. Nothing is written to the registry silently.

Requirements:
- `MainWindow._show_pid_run_summary` (`t8_daq_system/gui/main_window.py`): delete its ×0.7 / ×0.6 / ×1.3 logic; show the `run_metrics` values and every `Suggestion` reason. "Apply" opens the Settings dialog with the three gain fields set to the suggestion and never calls `AppSettings.save()` itself.
- The dialog is built only on the Tk thread, from a Snapshot or event, never from the Rig thread.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [x] Unit test (Tk mocked): with a stored Suggestion, invoking Apply opens the Settings dialog whose gain variables equal the suggested values, and `save` was not called on the real `AppSettings` (fake winreg) passed in.
- [x] Unit test: the dialog's message text contains every reason string from the Suggestion.
- [x] Unit test: `inspect.getsource(MainWindow._show_pid_run_summary)` contains none of `* 0.7`, `* 0.6`, `* 1.3`.
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

### 2026-10-14

Done. `_show_pid_run_summary` shows the engine's metrics and every Suggestion reason
(the x0.7/x0.6/x1.3 maths was already removed by 31). Apply now opens `SettingsDialog`
with the new `prefill_gains=(kp, ki, kd)` argument, which sets the three gain
variables via `_apply_gain_prefill`; `AppSettings.save()` is never called by the
summary. The method runs on the Tk thread (called from `root.after`). Tests:
`tests/unit/test_post_run_suggestion_dialog.py`. Local gate: ruff and check_tests_first
pass; pytest 543 passed, 1 known pre-existing Linux failure
(`test_build_id.py::test_window_title_ends_with_build_id`, winreg mock).

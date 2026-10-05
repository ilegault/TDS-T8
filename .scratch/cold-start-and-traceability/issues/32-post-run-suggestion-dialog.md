# 32: Post-run suggestion dialog uses the engine

**Status:** ready-for-agent

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

- [ ] Unit test (Tk mocked): with a stored Suggestion, invoking Apply opens the Settings dialog whose gain variables equal the suggested values, and `save` was not called on the real `AppSettings` (fake winreg) passed in.
- [ ] Unit test: the dialog's message text contains every reason string from the Suggestion.
- [ ] Unit test: `inspect.getsource(MainWindow._show_pid_run_summary)` contains none of `* 0.7`, `* 0.6`, `* 1.3`.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

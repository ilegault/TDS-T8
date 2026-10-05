# 28: Replace print with logging in the GUI; forbid print

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 27

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0008. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

The same conversion for `t8_daq_system/gui/` and `t8_daq_system/main.py`, after which the no-print rule covers the whole package.

Requirements: the same level rule as ticket 27. Operator commands handled in `gui/main_window.py` — Run, Stop, Nudge, Reset trip, Practice toggle, Settings saved — each log one INFO line naming the command and its parameters.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] The no-print rule from ticket 27 is widened to all of `t8_daq_system/` and passes.
- [ ] Unit test (Tk mocked): invoking the Run handler logs an INFO record containing `Run` and the number of blocks; invoking Reset trip logs a record containing `Reset trip`.
- [ ] Unit test: saving Settings logs one INFO record per changed key containing the old and new value.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

# 27: Replace print with logging outside the GUI

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 26

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0008. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

Every `print(` under `t8_daq_system/control`, `rig`, `data`, `hardware`, `core`, `utils` and `settings` becomes a call on a module logger (`logger = logging.getLogger(__name__)`).

Requirements:
- Level rule: per-tick or per-sample diagnostics → DEBUG; state changes, commands, transitions → INFO; recoverable faults → WARNING; failures → ERROR (`logger.exception` inside `except`).
- These packages print nothing to stdout afterward.
- A message text that a test asserts is not changed unless that test is rewritten in place under the same name.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] A rule in `test_architecture_rules.py` walks the AST of every file in those packages and finds zero `print` calls.
- [ ] Integration test: a 60 s `ManualClock` Rig run (120 control steps) at INFO produces fewer than 20 records from loggers under `t8_daq_system.control` and `t8_daq_system.rig`.
- [ ] The same run at DEBUG produces at least 120 records from loggers under `t8_daq_system.control`.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

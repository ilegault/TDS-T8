# 35: AGENTS.md catches up with this effort

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** no

**Blocked by:** 23, 24, 26, 33

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0006, ADR 0007, ADR 0008. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

`AGENTS.md` describes the code as it is after this effort. Held for the developer's review.

Requirements: update §4 (codebase map: `control/suggestion_engine.py`, `utils/diagnostic_log.py`, `build_info.py`, `scripts/build.py`); §5.6 (AppSettings: the registry wins, `_DEFAULTS` only seeds missing keys, `sources`); §6.3 (replace "Default gains: Kp=1.0, Ki=0.05, Kd=0.05" with the ADR 0007 defaults); §11 (build through `build.bat` / `scripts/build.py`, Build ID naming); §12.1 (add Soft start and the two current caps as invariants). Do not touch the `ACTIVE-PLAN` block.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] AGENTS.md contains `Soft start`, `Run current cap`, `scripts/build.py` and `0.014` in the sections named above.
- [ ] `git diff` shows no changed line between `<!-- ACTIVE-PLAN:START -->` and `<!-- ACTIVE-PLAN:END -->`.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

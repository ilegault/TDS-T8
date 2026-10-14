# 30: Console window setting

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 24, 26

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0008. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

A Settings checkbox, "Show console window (takes effect on restart)", lets the operator watch the Diagnostic log live without a special build.

Requirements:
- `attach_console(enabled: bool, platform: str = sys.platform, kernel32=None) -> bool` in `t8_daq_system/utils/diagnostic_log.py`: when enabled on `win32` and `GetConsoleWindow()` returns 0, call `AllocConsole()`, reopen `sys.stdout`/`sys.stderr` on `CONOUT$`, and add a `StreamHandler` with the session format. Returns whether a console was attached. `kernel32` is injectable so tests never touch Windows.
- `t8_daq_system/main.py` calls it right after `start_session` with `settings.show_console`.
- The checkbox lives on the Paths & Resources tab (`_build_paths_tab` in `gui/settings_dialog.py`).

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [x] Unit test with a fake `kernel32` whose `GetConsoleWindow` returns 0: `attach_console(True, 'win32', fake)` returns True and `AllocConsole` was called once.
- [x] Unit test: `attach_console(True, 'linux', fake)` returns False and calls nothing on `fake`.
- [x] Unit test: `attach_console(False, 'win32', fake)` returns False.
- [x] Unit test: after a successful attach, one log record reaches both the session file and the added stream handler.
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

Done (2026-10-13): `attach_console` + `_open_conout` seam in `utils/diagnostic_log.py`; called from `main.py` after `start_session`; checkbox on Paths & Resources tab (load/save wired). Tests in `tests/unit/test_diagnostic_log.py` cover each criterion (fake kernel32, in-memory CONOUT$). Bench check still wanted: real console appears on the lab PC with the setting on.

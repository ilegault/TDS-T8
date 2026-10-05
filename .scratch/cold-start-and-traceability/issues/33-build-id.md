# 33: Build ID on every artifact

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 26

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0008. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

The developer can tell from the exe name, window title, Diagnostic log or CSV exactly which commit is running on the rig PC.

Requirements:
- New `scripts/build.py` with pure functions `build_id(short_hash: str, today: date, dirty: bool) -> str` (`YYYY-MM-DD_<hash>`, plus `-dirty`) and `build_info_text(build_id, branch, built_at, files: list[str]) -> str`, and `main(argv)` that reads git (`rev-parse --short HEAD`, `rev-parse --abbrev-ref HEAD`, `status --porcelain`), refuses a dirty tree unless `--allow-dirty`, writes `t8_daq_system/_build_info.py` containing `BUILD_ID = "<id>"`, runs `pyinstaller tds.spec --clean`, renames `dist/T8_DAQ_System` to `dist/T8_DAQ_System_<id>` and the exe inside to `T8_DAQ_System_<id>.exe`, and writes `BUILD_INFO.txt` there listing every file in that folder. Git and PyInstaller are called through one injectable `run` function so tests can fake them.
- `t8_daq_system/build_info.py`: `get_build_id()` returns `_build_info.BUILD_ID` when that module exists, else `dev`.
- The window title set in `MainWindow.__init__` and in the practice-mode title changes (`gui/main_window.py`) ends with ` — <build id>`. `main.py` passes `get_build_id()` to `start_session` (ticket 26). The CSV metadata header gains `build_id`.
- Add `build.bat` at the repo root that runs `python scripts\build.py %*`, and add `t8_daq_system/_build_info.py` to `.gitignore`.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] Unit test: `build_id('7656f09', date(2026, 10, 5), False) == '2026-10-05_7656f09'`, and with `dirty=True` the result ends with `-dirty`.
- [ ] Unit test: `main([])` with a faked `run` reporting a dirty tree exits non-zero with a message containing `uncommitted`; `main(['--allow-dirty'])` reaches the faked PyInstaller call.
- [ ] Unit test: `build_info_text` output contains the id, the branch and every file name passed.
- [ ] Unit test: with no `_build_info` module importable, `get_build_id() == 'dev'`, and the main window title (Tk mocked) ends with `dev`.
- [ ] Unit test: a CSV written by the Run record to `tmp_path` has a metadata line containing `build_id`.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

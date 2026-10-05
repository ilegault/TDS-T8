# 26: Diagnostic log foundation

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 24

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0008. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

Every session writes one Diagnostic log file the developer can read cold after the operator sends it.

Requirements:
- New module `t8_daq_system/utils/diagnostic_log.py`, with no GUI or tkinter imports (`utils/` purity is enforced by `test_architecture_rules.py`), providing `start_session(log_dir, keep, build_id, run_id, adapter) -> Path`. It configures the root logger once: a file handler at `<log_dir>/console/<YYYY-MM-DD>_<run_id>.log`, format `%(asctime)s %(levelname)s %(name)s: %(message)s`, level INFO; then deletes the oldest files so at most `keep` remain.
- `new_run_id()` returns `YYYYMMDD_HHMMSS`. `t8_daq_system/main.py` calls it once at startup; the same id names this session's log and is passed to the Run record so the CSV metadata header carries `run_id`.
- First line: `Build <build_id> · adapter <adapter> · run <run_id>`. Until ticket 33 the build id is `dev`.
- Then one INFO line per setting: `setting <key>=<value> (<source>)`, from `AppSettings.sources` (ticket 24).
- `sys.excepthook` and `threading.excepthook` log uncaught exceptions at ERROR with traceback.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] Unit test with `tmp_path`: `start_session` creates `console/<date>_<run_id>.log` whose first line contains `Build dev` and the run id.
- [ ] Unit test: with `keep=3` and 5 older log files present, after `start_session` exactly 3 files remain and the new session's file is one of them.
- [ ] Unit test: after `start_session` with an AppSettings whose `pid_kp` came from the registry, the file has a line containing `setting pid_kp=` and `(registry)`.
- [ ] Unit test: an exception raised in a `threading.Thread` target writes an ERROR line containing the exception message and `Traceback`.
- [ ] Unit test: a CSV written by the Run record to `tmp_path` has a metadata line whose `run_id` equals the session's run id.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

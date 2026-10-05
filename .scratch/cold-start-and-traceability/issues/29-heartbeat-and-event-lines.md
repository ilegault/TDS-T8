# 29: Heartbeat and event lines sized for 8-hour runs

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 22, 23, 26

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0008, ADR 0006. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

The Diagnostic log tells the story of a run in about a thousand lines over eight hours.

Requirements:
- A heartbeat emitter consumes Snapshots on the Run record's writer thread (`RunRecord._process_item`, `t8_daq_system/data/run_record.py`), never on the Rig loop. Every `heartbeat_interval_s` it writes one INFO line: `HB t=<elapsed s> phase=<soft_start|block N> tc=<°C> sp=<°C> V=<v> I=<a> FF=<v> P=<p> I=<i> D=<d>`.
- Every phase or block transition and handoff, and every run start and stop, is one INFO line; every trip is one ERROR line carrying its kind and full reason.
- At run start, each disabled cap logs WARNING `Soft-start current cap is OFF` or `Run current cap is OFF`.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] Integration test: an 8-hour TempRamp + Hold program on SimulatedRig with `ManualClock` writes fewer than 2 000 lines at INFO or above to the session log in `tmp_path`.
- [ ] Same test: the number of lines containing ` HB ` is within ±2 of `8*3600/30`.
- [ ] Integration test: a forced `soft_start_overcurrent` trip writes an ERROR line containing the trip's reason sentence.
- [ ] Integration test: `run_cap_enabled=False` writes a WARNING line containing `Run current cap is OFF` at run start.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

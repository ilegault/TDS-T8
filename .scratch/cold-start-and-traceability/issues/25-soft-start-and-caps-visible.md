# 25: Soft start and caps are visible to the operator

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 22, 23, 24

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0006, ADR 0007. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

The operator can see that Soft start will happen and what it is doing, which gains the run will use, and whether each cap is on.

Requirements:
- Power Programmer, `_refresh_table` in `t8_daq_system/gui/power_programmer_panel.py`: a first, locked row `Soft start → PID at <threshold> °C or <handoff> A`. `_delete_block`, `_move_up` and `_move_down` do nothing when that row is selected.
- Preview: the pure `compute_preview` in `t8_daq_system/control/program_run.py` prepends a Soft-start segment (ramp at the configured rate until its temperature estimate reaches the threshold) and returns that segment's end time; the preview plot shades the span. `compute_preview` stays pure — the preview tests call it without Tk.
- The main window status line shows `SOFT START <V> V · <T> °C → PID at <threshold> °C` while `snapshot.program.phase == 'soft_start'`, then the handoff reason for 30 s after handoff.
- The Power Programmer shows `Gains in use: <Kp> / <Ki> / <Kd>` and `Soft-start cap: <A> A` or `Soft-start cap: OFF`, `Run cap: <A> A` or `Run cap: OFF` — from AppSettings when idle, from `snapshot.program.gains_in_use` while running.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] `test_preview_includes_the_soft_start_ramp`: Unit test: `compute_preview(...)` with settings returns a soft-start end time greater than 0, and its voltages before that time rise no faster than the ramp rate.
- [ ] `test_block_table_soft_start_row_is_protected`: Unit test (Tk mocked, as in `tests/unit/test_gui_reads_rig.py`): the block table's first row text starts with `Soft start`; calling `_delete_block` with that row selected leaves the block list unchanged.
- [ ] `test_snapshot_in_soft_start_shows_soft_start_status`: Unit test: feeding a Snapshot with `phase='soft_start'` to the GUI's snapshot handler sets status text starting with `SOFT START`.
- [ ] `test_power_programmer_shows_run_cap_off`: Unit test: with `run_cap_enabled=False` the Power Programmer cap label text contains `Run cap: OFF`.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (by hand)

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

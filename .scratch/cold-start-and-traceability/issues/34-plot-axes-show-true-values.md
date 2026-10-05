# 34: Plot axes show true values

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0001. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

Every tick label on a linear plot axis is the real value: no `+1.499` offset and no scientific notation. The PS plot never zooms tighter than 0.05 V or 1 A, so meter noise cannot fill the screen.

Requirements:
- One helper `use_true_value_ticks(ax)` in `t8_daq_system/gui/live_plot.py` sets a `ScalarFormatter(useOffset=False)` with scientific notation off on the y-axis. Apply it to every linear axis created in `LivePlot.__init__` (including `ax2` from `twinx`) and in the Power Programmer preview plot. Log-scale pressure axes are left alone.
- In `LivePlot._autoscale_visible_only` / `_render`, for `plot_type == 'ps'`, widen the voltage axis to a span of at least 0.05 V and the current axis to at least 1 A, centred on the data.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] Unit test (Agg backend, as in `tests/unit/test_live_plot.py`): after plotting a constant 1.4998 V with ±0.0001 V noise and drawing, the y-axis formatter's offset text is empty and every tick label parses to a float within [1.47, 1.53].
- [ ] Same plot: the voltage axis `get_ylim()` span is at least 0.05 and the current axis span at least 1.0.
- [ ] Unit test: a pressure plot's y-axis scale is still `log`.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

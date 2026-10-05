# 22: Soft start phase

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 19, 20, 21

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0006 (points 1–3), ADR 0002. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

Every Program run begins in Soft start whenever the control TC is below `soft_start_threshold_c`. DAC0 ramps open-loop from the currently commanded voltage at `soft_start_ramp_v_per_s`, with no Feedforward, until the control TC reaches the threshold or measured current reaches `soft_start_handoff_current_a`, whichever comes first. Then the first block starts with a bumpless transfer (ticket 21). Soft start is not a block and is not saved in profiles.

Requirements:
- The Soft-start step is a pure function in `t8_daq_system/control/block_steps.py` beside `step_voltage_ramp`, of (settings, control-TC °C, measured A, elapsed s, start voltage) → `StepResult` plus a handoff reason. No clock or hardware, so the integration tests can drive it through `ManualClock`.
- `ProgramRun.start` enters Soft start unless the control TC is already at or above the threshold, in which case it starts block 0 directly.
- `ProgramStatus` gains `phase: str` (`"soft_start"` or `"block"`) and `handoff_reason: str`, worded exactly as `"threshold 200.0 °C reached"`, `"handoff current 35.0 A reached at 143.2 °C"`, or `"skipped: control TC 250.0 °C ≥ threshold"` with the run's numbers.
- Handoff emits an event through `ProgramRun.take_events` carrying the reason, so the Run record writes an event row the same way block transitions already do.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] Integration test (Rig + SimulatedRig + ManualClock), TempRamp program on a cold specimen: while `snapshot.program.phase == 'soft_start'`, each commanded voltage exceeds the previous by at most `ramp × 0.5 + 1e-9` V.
- [ ] Same run: it hands off with `handoff_reason` starting `"handoff current"` or `"threshold"`.
- [ ] A run started with the specimen above threshold has `phase == 'block'` on its first Snapshot and `handoff_reason` starting `"skipped"`.
- [ ] The Run record CSV written to `tmp_path` in that test contains exactly one event row whose detail contains the handoff reason.
- [ ] The first block's first commanded voltage equals the last Soft-start voltage within 0.0001 V.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

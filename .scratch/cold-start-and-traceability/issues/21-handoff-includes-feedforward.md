# 21: Bumpless handoff includes Feedforward

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 19

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0006 (points 5–6). `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

At every closed-loop block boundary the first commanded voltage equals the last one, Feedforward included. Today `PIDController.reset_bumpless` (`t8_daq_system/control/temp_ramp_pid.py`) seeds the PID alone with the previous voltage, and `step_temp_ramp` (`t8_daq_system/control/block_steps.py`) then adds Feedforward on top, so voltage jumps up by FF on entry to a TempRamp; the PID's `output_min=0.0` stops it pulling back down. Separately, `FeedforwardMap.voltage_for` (`t8_daq_system/control/feedforward_map.py`) returns the lowest backbone point's voltage (0.29 V at 50 °C) for any colder temperature.

Requirements:
- `reset_bumpless(seed_output, current_time, ff_volts)` seeds the integrator so that `ff_volts + PID output == seed_output`. The caller in `ProgramRun` (where `reset_bumpless` is called today) passes `FF(rate, T_now)` for TempRamp blocks and 0.0 for StableHold.
- PID correction bounds become symmetric (−6.0 V to +6.0 V); the 0–6 V clamp applies only to the total inside `step_temp_ramp` and `step_stable_hold`. Both stay pure functions with no clock or hardware, because the block-step tests depend on that.
- `FeedforwardMap.voltage_for` returns 0.0 for any temperature below the backbone's first point and for an empty map. Behaviour above the last point is unchanged.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [x] Integration test (Rig + SimulatedRig + ManualClock, as in `tests/integration/test_block_transitions.py`): program VoltageRamp to 1.0 V then TempRamp; the first TempRamp commanded voltage equals the last VoltageRamp voltage within 0.0001 V — run once with a Feedforward map whose value at the handoff temperature is above 1.0 V and once with it below.
- [x] The same assertion holds for StableHold → TempRamp and TempRamp → StableHold boundaries.
- [x] Unit test: a Feedforward map whose first point is (50 °C, 0.29 V) returns 0.0 at 20 °C and 0.29 at 50 °C.
- [x] Unit test: with measured temperature above setpoint after seeding, `step_temp_ramp` returns a total voltage below the Feedforward value (the correction went negative).
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

2026-10-13: `PIDController.reset_bumpless(seed, t, ff_volts)` seeds `seed - ff_volts`; PID bounds are now -6..+6 V
(total still clamped 0..6 V in the block steps); `ProgramRun._setup_block` passes `FF(rate, T_now)` for TempRamp, 0.0 for
StableHold; `FeedforwardMap.voltage_for` returns 0.0 below the backbone's first point.
Tests: `tests/integration/test_handoff_includes_feedforward.py` (V->T, H->T, T->H, FF above/below),
`tests/unit/test_feedforward_map.py`, and two new tests in `tests/unit/test_block_steps.py`.
Two characterisation tests in `tests/integration/test_program_run_rig.py` were rewritten in place (same names): their
expected values encoded the 0.29 V cold FF and the FF jump at the boundary, which this ticket removes.
No bench verification needed.

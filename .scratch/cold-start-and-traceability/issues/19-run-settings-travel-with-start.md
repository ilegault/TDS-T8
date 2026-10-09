# 19: Run settings travel with Start

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0007, ADR 0002. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

When the operator presses Run, every value that shapes the run — PID gains, windup limit, soft-start threshold / ramp rate / handoff current, both current caps and their enable flags — is captured once into one frozen `RunSettings` object and sent to the Rig with the program. The run uses exactly those values until it ends. Today `MainWindow._start_programmer_ramp` (`t8_daq_system/gui/main_window.py`) reaches into `rig._program_run._pid.update_gains(...)` directly; that private reach is removed.

This ticket only moves values. It adds no soft start or cap behaviour; later tickets read the new fields.

Requirements:
- `RunSettings` is a frozen dataclass in `t8_daq_system/rig/commands.py` beside `StartProgram`, with fields `kp`, `ki`, `kd`, `windup_limit`, `soft_start_threshold_c`, `soft_start_ramp_v_per_s`, `soft_start_handoff_current_a`, `soft_start_cap_enabled`, `soft_start_cap_a`, `run_cap_enabled`, `run_cap_a`. `StartProgram` gains a required `settings: RunSettings` field.
- `ProgramRun.start` (`t8_daq_system/control/program_run.py`) takes the `RunSettings` and constructs its `PIDController` from it. `PIDController.__init__` (`t8_daq_system/control/temp_ramp_pid.py`) has no default for `kp`, `ki`, `kd` — they are required — because a silent default gain is the layering bug this effort removes.
- `ProgramStatus` (`t8_daq_system/rig/snapshot.py`) gains `gains_in_use: tuple[float, float, float]`, populated from the run's settings.
- `MainWindow._start_programmer_ramp` builds `RunSettings` with a new function `run_settings_from_app_settings(settings) -> RunSettings` in `gui/main_window.py` and submits `StartProgram(settings=...)`. Fields AppSettings does not have yet use the spec's defaults as literals inside that one function; ticket 24 replaces them.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [x] A Rig integration test (copy the setup of `tests/integration/test_program_run_rig.py`: `Rig` + `SimulatedRig` + `ManualClock`) submits `StartProgram(settings=RunSettings(kp=0.5, ...))` and asserts the published `snapshot.program.gains_in_use[0] == 0.5`.
- [x] A test changes the AppSettings gains after Run was submitted and asserts `gains_in_use` in later Snapshots is unchanged.
- [x] A test asserts `PIDController()` with no arguments raises `TypeError`.
- [x] `tests/unit/test_architecture_rules.py` gains a rule, passing, that no file under `t8_daq_system/gui/` contains the text `_program_run`.
- [x] Every existing call of `PIDController(...)` and `StartProgram()` is updated; no test is deleted (a test whose call signature changed is rewritten in place under the same name).
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

Progress (2026-10-09): Built `RunSettings` dataclass to travel with `StartProgram` command. Updated `Rig` loop and `ProgramRun` to utilize and populate `gains_in_use`. Verified GUI no longer accesses `_program_run` directly by creating explicit proxy methods on `Rig`. Added tests asserting `gains_in_use` populates correctly and remains frozen on `StartProgram`. All acceptance criteria checked and verified by `tests/integration/test_program_run_rig.py` and `tests/unit/test_temp_ramp_pid.py`.

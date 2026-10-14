# 20: Simulated filament is cold-realistic

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0005, ADR 0006. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

The Simulated rig must reproduce the cold-start event: a small voltage on a cold specimen draws a large current. Today `TungstenSim.R_COLD = 0.033` Ω (`t8_daq_system/rig/tungsten_model.py`), so 0.29 V on a cold specimen draws about 9 A. The real filament measured about 4–5 mΩ cold in March 2026 logs (0.0093 V → 2.17 A at 27 °C). Without this, every current-cap test would pass against a model that can never exceed the cap.

Requirements:
- Recalibrate `TungstenSim` constants (`R_COLD`, `ALPHA`, and thermal constants only if needed) to meet these targets from March 2026 run logs: resistance at 300 K between 0.004 and 0.006 Ω; steady-state current at 6.0 V between 120 and 180 A.
- Record both targets and their source in the class docstring.
- Existing tests that hard-code the old 0.033 Ω behaviour are rewritten in place under the same test names to assert the new targets. No test is deleted.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [x] A test in `tests/unit/test_simulated_rig.py`: `SimulatedRig` with the specimen at about 20 °C, `write_voltage(0.29)`, one `read()` → `ps_amps > 40.0`.
- [x] A test asserts `TungstenSim()._resistance(300.0)` is within [0.004, 0.006].
- [x] A test asserts that at `TungstenSim().steady_state_temp(6.0)` the current `6.0 / R` is within [120, 180] A.
- [x] The full existing suite passes with the new constants, practice-mode and Rig tests included.
- [x] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

2026-10-13: `TungstenSim` recalibrated: `R_COLD` 0.033 -> 0.005 Ω, `AREA` 2e-4 -> 3e-3 m² (so the lower cold R still balances at a realistic T_ss: 3 V ≈ 1574 K, 6 V ≈ 2077 K / 133 A). Targets and source recorded in module and class docs.
Tests (tests/unit/test_simulated_rig.py): cold 0.29 V > 40 A; R(300 K) in [0.004, 0.006]; 6 V steady-state current in [120, 180] A.
Rewritten in place: `test_three_block_program_completes` ramp end voltage 1.0 -> 0.1 V (1 V on the cold specimen now overheats past the 303 K hold). No test deleted. No bench verification needed.

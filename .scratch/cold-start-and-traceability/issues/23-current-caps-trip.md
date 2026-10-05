# 23: Current caps trip the heater

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 20, 22

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0006 (point 4), ADR 0003. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

Two current caps protect the filament. While `phase == 'soft_start'`, measured current above `soft_start_cap_a` (when `soft_start_cap_enabled`) is a `soft_start_overcurrent` trip. After handoff, current above `run_cap_a` (when `run_cap_enabled`) is a `run_overcurrent` trip. Both are ordinary ADR 0003 trips: instant cutoff in the same tick, latched, banner until reset.

Requirements:
- Add both checks to the pure `evaluate_safety` in `t8_daq_system/control/safety_monitor.py`, following the shape of its existing `temp_limit` check. Cap values and enables come from the run's `RunSettings` (ticket 19), passed in by the Rig the way `limits` is passed today.
- The reason sentence names measured A, cap A, phase, commanded V, control-TC °C, and the likely cause: for Soft start `"check for a shorted lead or a voltage step on a cold filament"`, for the run cap `"check filament and leads"`.
- Add both kinds to the trip-kind matching in `HeaterOutput` (`t8_daq_system/control/heater_output.py`, beside `pressure_high`) so reset is refused while current is still above the cap.
- Add fault injection to `SimulatedRig` (`t8_daq_system/rig/simulated.py`) beside `set_pressure` / `stall_gauge`: `force_current(amps)` makes `read()` report that `ps_amps` until `release_current()`. This is how the tests drive overcurrent.
- Delete the "Cold-Tungsten Current Guard" section of `HeaterOutput` and `COLD_CURRENT_LIMIT_A` from `t8_daq_system/settings/safety_limits.py`. Tests that asserted the old guard are rewritten in place under the same names to assert the new trip.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] Integration test: `soft_start_cap_a=40`, a SimulatedRig forced to report 45 A during Soft start → in that same Snapshot the heater output is off, commanded voltage is 0, trip kind is `soft_start_overcurrent`, and the reason contains `45` and `40`.
- [ ] Integration test: after handoff with `run_cap_a=120`, forced 125 A → trip kind `run_overcurrent`.
- [ ] With `soft_start_cap_enabled=False`, forced 45 A during Soft start → no trip.
- [ ] `ResetTrip` while the forced current is still 45 A is refused; after the current drops below the cap it is accepted.
- [ ] A rule in `test_architecture_rules.py` asserts no file under `t8_daq_system/` contains `COLD_CURRENT_LIMIT_A`.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

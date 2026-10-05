# 24: Registry is the single source of settings

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 19

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0007, ADR 0006 (point 3). `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

Settings shown in the Settings dialog are exactly what the app uses. `AppSettings._DEFAULTS` (`t8_daq_system/settings/app_settings.py`) seeds only keys missing from the registry, and every loaded key records whether it came from the registry or a default.

Requirements:
- `_DEFAULTS` and the matching `AppSettings` attributes: add `soft_start_ramp_v_per_s` 0.02, `soft_start_handoff_current_a` 35.0, `soft_start_cap_enabled` True, `soft_start_cap_a` 40.0, `run_cap_enabled` True, `run_cap_a` 120.0, `heartbeat_interval_s` 30, `show_console` False, `diagnostic_log_keep` 30; keep `soft_start_threshold_c` 200.0; set `pid_kp` 0.014, `pid_ki` 0.00078, `pid_kd` 0.00845; delete `ps_current_limit`, `soft_start_current_limit_a`, `pid_output_max`. A deleted key still in the registry is ignored on load and never written back.
- `AppSettings.load()` fills `sources: dict[str, str]` with `"registry"` or `"default"` per key.
- Settings dialog, `_build_power_programmer_tab` in `t8_daq_system/gui/settings_dialog.py`: remove the "Max Output" row and the "History may override…" label; add a "Soft start & current caps" frame with every soft-start and cap field (each cap with a checkbox); add a "Reset PID to defaults" button that sets the three gain fields to the `_DEFAULTS` values (the operator still presses Save). Remove the "Current Limit (A)" row from `_build_hardware_tab`.
- `run_settings_from_app_settings` (ticket 19) reads the real fields; its literals are deleted.

Tests may fake: Tk widgets (via `tests/conftest.py`), `winreg` (the fake registry in conftest), the LabJack/serial layer, wall-clock time (`ManualClock`), git and PyInstaller subprocess calls. Must be real: the module under change, `SimulatedRig`, `TungstenSim`, and files written under `tmp_path`.

## Acceptance criteria

- [ ] Unit test with the fake `winreg` from `tests/conftest.py`: empty registry → after `load()`, `pid_kp == 0.014` and `sources['pid_kp'] == 'default'`; registry holding `pid_kp=0.02` → `0.02` and `'registry'`.
- [ ] Unit test: a registry containing `pid_output_max` and `ps_current_limit` loads without error, the `AppSettings` object has neither attribute, and `save()` writes neither key.
- [ ] Unit test: after setting `settings.run_cap_a = 150`, `run_settings_from_app_settings(settings).run_cap_a == 150`.
- [ ] Unit test (Tk mocked): building the Settings dialog creates no widget whose text contains `History may override` or `Max Output`.
- [ ] Unit test: invoking the Reset PID handler sets the three gain variables to the `_DEFAULTS` values.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Gate

Run in this order, as CI does (`.github/workflows/`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

# 38: Run settings come from one pure function

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0007. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

Prefactor for ticket 39. Tests cannot build **Production settings** today without
importing `t8_daq_system/gui/main_window.py`, which pulls in Tk. Move the one function
that turns `AppSettings` into a frozen `RunSettings` into a pure module, and add a
second function that builds the `RunSettings` the app ships with.

Requirements:
- New module `t8_daq_system/settings/run_settings.py` with no import of `tkinter`,
  `t8_daq_system.gui` or `labjack`. It holds:
  - `run_settings_from_app_settings(settings) -> RunSettings`, moved unchanged from
    `t8_daq_system/gui/main_window.py` (currently line 125). It still holds no literals.
  - `production_run_settings() -> RunSettings`: the same mapping applied to the values
    in `t8_daq_system/settings/app_settings.py` `_DEFAULTS` (each entry is
    `(type, default)`; use the default). It must not construct an `AppSettings` that
    reads the registry, and holds no literals (ADR 0007: `_DEFAULTS` is the only place
    a default lives).
- `main_window.py` imports `run_settings_from_app_settings` from the new module; its
  two call sites (`get_soft_start_settings_fn=` and `self._run_settings = ...`) are
  otherwise unchanged.
- The two test files that import it from `main_window`
  (`tests/integration/test_run_settings_travel.py`,
  `tests/unit/test_registry_single_source.py`) import it from the new module instead.
  No test is renamed or deleted.
- Module docstring with a `WHY THIS EXISTS` section (AGENTS.md §12.4 point 10).

Tests may fake: the registry (the fake `winreg` in `tests/conftest.py`). Must be real:
`_DEFAULTS`, `RunSettings`, the new module.

## Acceptance criteria

- [ ] `test_module_imports_without_tk_or_gui` in `tests/unit/test_run_settings_module.py` runs
      `subprocess.run([sys.executable, "-c", "import t8_daq_system.settings.run_settings, sys; print('tkinter' in sys.modules, any(m.startswith('t8_daq_system.gui') for m in sys.modules))"], cwd=<repo root>)`
      and asserts stdout is `False False`.
- [ ] `test_production_run_settings_match_defaults` asserts each field of `production_run_settings()` equals its `_DEFAULTS`
      value: `kp == _DEFAULTS["pid_kp"][1]`, `ki`/`pid_ki`, `kd`/`pid_kd`,
      `windup_limit`/`pid_windup_limit`, and the seven `soft_start_*` / `run_cap_*`
      fields against the keys of the same name.
- [ ] `test_production_run_settings_read_defaults_live` changes one `_DEFAULTS` entry with `monkeypatch.setitem` (e.g.
      `run_cap_a` to `(..., 99.0)`) and asserts `production_run_settings().run_cap_a == 99.0`,
      proving no second copy of the default exists.
- [ ] `test_run_settings_from_app_settings_copies_gains_and_windup` and the other existing
      tests in the two files above pass unchanged apart from their import line, and
      `grep -n "def run_settings_from_app_settings" t8_daq_system/gui/main_window.py`
      finds nothing.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

# 43: Run current cap fits real operation

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0003, ADR 0006, ADR 0007 (bent by requirement 2; its amendment lands in
ticket 51), AGENTS.md §2 (CV-only) and §5.6. `docs/adr/0001-tests-first-and-no-muted-failures.md`
is binding on all test work.

## Decision (developer, 2026-11-10)

- **Option B: raise the Run current cap default to 175 A**, editable in Settings, valid
  range above 0 A and at most 180 A (the supply ceiling; a higher cap can never trip).
- Why 175 A: every normal sample in the five Field runs, including the two 33 h TDS runs,
  peaks at 143–151 A. The only sample above 175 A is the **last** sample of
  `2026-03-28_tds_5k_per_min` (t = 17237.6 s): the control TC fell 1454 → 1378 °C in 5 s
  while the supply jumped 4.6 → 5.97 V and 179.9 A. The developer confirmed that was the
  TC losing contact and the PID running to full power, which is exactly what the cap is
  for. 175 A must trip there and nowhere else.
- **A stored 120 A migrates to 175 A.** `AppSettings.save()` writes every key, so a lab
  PC that ever pressed Save holds `run_cap_a = 120.0` and would never see the new
  default. A stored value of exactly 120.0 (the retired default) loads as 175.0. Any
  other stored value is kept.
- **Both current caps move to their own Settings tab, "Safety limits"**, the first tab,
  which also lists every fixed limit that can stop a run, so no limit is hidden.
- Decoupled from ticket 42 on 2026-11-10. The simulator-based checks this ticket used
  to carry (rewriting `test_field_case_2026_11_06_cold_start`, a 5 K/min TDS scenario)
  wait for the three-stage-model design and are not part of this ticket.

## What to build

Requirements, in order:

1. `t8_daq_system/settings/app_settings.py`: `_DEFAULTS["run_cap_a"]` becomes
   `("float", 175.0)` and `AppSettings.__init__` sets `self.run_cap_a: float = 175.0`.
   No other module holds this number (ADR 0007): code that needs the default reads
   `_DEFAULTS["run_cap_a"][1]`.
2. Same file, `AppSettings.load()`: directly after the existing `tc_unit` `F` → `C`
   migration, add the run-cap migration. Add a module constant
   `_RETIRED_RUN_CAP_A = 120.0  # Run current cap default until 2026-11-10 (ticket 43)`.
   If `self.sources["run_cap_a"] == "registry"` and `self.run_cap_a == _RETIRED_RUN_CAP_A`,
   set `self.run_cap_a = _DEFAULTS["run_cap_a"][1]`, set
   `self.sources["run_cap_a"] = "migrated"`, and log at INFO exactly
   `"Setting run_cap_a migrated: stored %.1f A is the retired default; using %.1f A"`.
   This must happen before the `self._persisted = ...` line, so the next `save()`
   writes 175.0. The source value `migrated` is required, not cosmetic: `load()` runs
   before the Diagnostic log has a handler, so the startup dump line
   `setting run_cap_a=175.0 (migrated)` is the only record the operator gets.
   Update the module docstring's `WHY THE REGISTRY WINS` section with one paragraph on
   this migration and why.
3. Same file: add a pure function `check_run_cap_a(value: float) -> float` that returns
   `value` when `0.0 < value <= PS_CURRENT_CEILING_A` and otherwise raises
   `ValueError(f"Run current cap must be above 0 A and at most {PS_CURRENT_CEILING_A:.0f} A (the supply ceiling).")`.
   Import `PS_CURRENT_CEILING_A` from `t8_daq_system.settings.safety_limits`. It is a
   module-level pure function, not a dialog method, so it is testable without Tk.
4. `t8_daq_system/settings/safety_limits.py`: add a pure function
   `fixed_limit_lines() -> list[str]` returning exactly these six strings, built from
   the module's constants (never typed-in numbers):
   - `f"Temperature override: any thermocouple at or above {TEMP_OVERRIDE_C:.0f} °C trips"`
   - `f"Pressure interlock: any gauge above {PRESSURE_INTERLOCK_TORR:.1e} Torr trips"`
   - `f"Pressure gauge silent for more than {STALE_ALLOWANCE_S:.0f} s trips"`
   - `f"Control thermocouple silent for more than {STALE_ALLOWANCE_S:.0f} s during a closed-loop block trips"`
   - `f"Supply current ceiling: {PS_CURRENT_CEILING_A:.0f} A (hardware limit, not a trip)"`
   - `f"Output voltage ceiling: {DAC0_MAX_V:.0f} V (clamp, not a trip)"`
5. `t8_daq_system/gui/settings_dialog.py`: add `_build_safety_tab(self, notebook)` and
   call it **first** in `_build_widgets`, before `_build_sensor_tab`. It creates
   `tab = ttk.Frame(notebook, padding=10)` and `notebook.add(tab, text="Safety limits")`,
   then three `ttk.LabelFrame`s packed `fill=tk.X, pady=5`:
   - `"Run current cap — trips and cuts the heater"`: `_create_entry_row(frame, "Run current cap (A):", "run_cap_a", width=12, row=0)`;
     `_create_bool_row(frame, "Enforce run current cap", "run_cap_enabled", row=1)`;
     a `ttk.Button(frame, text="Reset cap to default", command=self._reset_run_cap_to_default)`
     on row 2; and a `ttk.Label` on row 3 (`wraplength=420`) with text
     `f"Default {_DEFAULTS['run_cap_a'][1]:.0f} A. Normal runs peak at 143–151 A; the supply cannot exceed {PS_CURRENT_CEILING_A:.0f} A. Active from the first tick of a program, or from Handoff after a Soft start block, to program end."`
   - `"Soft-start current cap — only during a Soft start block"`:
     `_create_entry_row(frame, "Soft-start current cap (A):", "soft_start_cap_a", width=12, row=0)` and
     `_create_bool_row(frame, "Enforce soft-start current cap", "soft_start_cap_enabled", row=1)`.
   - `"Fixed limits (set in code, not editable)"`: one `ttk.Label(frame, text=line)` per
     line of `fixed_limit_lines()`, packed `anchor="w"`.
6. Same file, `_build_power_programmer_tab`: delete the four cap rows (rows 3–6 of
   `cap_frame`: `soft_start_cap_a`, `soft_start_cap_enabled`, `run_cap_a`,
   `run_cap_enabled`) and rename that LabelFrame's text from
   `"Soft start & current caps"` to `"Soft start"`. Each cap has exactly one editor.
   `_load_values` and `_save_settings_from_gui` keep using the same
   `_run_cap_a_var`, `_run_cap_enabled_var`, `_soft_start_cap_a_var` and
   `_soft_start_cap_enabled_var` attributes, now created by the new tab.
7. Same file: add `_reset_run_cap_to_default(self)` that sets
   `self._run_cap_a_var` to `str(_DEFAULTS["run_cap_a"][1])` and `self._run_cap_enabled_var`
   to `_DEFAULTS["run_cap_enabled"][1]`. Like the PID reset, it does not save.
8. Same file, `_save_settings_from_gui`: replace
   `s.run_cap_a = float(self._run_cap_a_var.get())` with
   `s.run_cap_a = check_run_cap_a(float(self._run_cap_a_var.get()))`, so an out-of-range
   cap shows the existing "Invalid Value" error and nothing is saved. Update the module
   docstring to say the Safety limits tab holds every limit that can stop a run.
9. `README.md`, the Soft-Start Phase list: replace the line
   `- Pauses voltage increases if current exceeds 120 A` with
   `- Trips if current exceeds the Soft-start current cap (Settings → Safety limits)`.
   Do not edit `AGENTS.md`, `CONTEXT.md` or `docs/adr/` (ticket 51 does).

Existing tests whose numbers change because of the new default are rewritten in place
under the same name. No test is deleted. Tests that pass an explicit `run_cap_a=120.0`
are about cap behaviour, not the default, and stay as they are.

Tests may fake: `winreg` (the `FakeWinreg`/`registry` fixture in
`tests/unit/test_registry_single_source.py`), Tk widgets (that file's `dialog`
fixture). Must be real: `AppSettings.load()`/`save()`, `evaluate_safety`,
`production_run_settings()`, the Field run fixtures via `all_field_runs()`.

## Acceptance criteria

- [ ] `test_new_soft_start_and_cap_defaults` in `tests/unit/test_registry_single_source.py`
      is rewritten in place: its run-cap line asserts `s.run_cap_a == 175.0`.
- [ ] `test_retired_run_cap_in_registry_loads_as_175` (same file): `registry({"run_cap_a": "120.0"})`,
      then `AppSettings().load()` gives `run_cap_a == 175.0` and
      `sources["run_cap_a"] == "migrated"`.
- [ ] `test_custom_run_cap_in_registry_is_kept` (same file): `registry({"run_cap_a": "150.0"})`
      loads `run_cap_a == 150.0` with source `"registry"`.
- [ ] `test_migrated_run_cap_is_written_on_next_save` (same file): after loading a stored
      `"120.0"` and calling `save()`, the fake registry holds `run_cap_a == "175.0"`.
- [ ] `test_check_run_cap_a_bounds` (same file): `check_run_cap_a(175.0) == 175.0`,
      `check_run_cap_a(180.0) == 180.0`, and `0.0`, `-5.0` and `180.5` each raise
      `ValueError` whose message contains `"180 A"`.
- [ ] `test_safety_tab_holds_both_caps_and_fixed_limits` (same file, `dialog` fixture):
      `_build_safety_tab(notebook)` with a `MagicMock` notebook calls `notebook.add` with
      `text="Safety limits"`, and the recorded ttk texts include `"Run current cap (A):"`,
      `"Enforce run current cap"`, `"Soft-start current cap (A):"`,
      `"Enforce soft-start current cap"` and every string from `fixed_limit_lines()`.
- [ ] `test_power_programmer_tab_has_no_cap_editors` (same file): after
      `_build_power_programmer_tab`, neither `"Run current cap (A):"` nor
      `"Soft-start current cap (A):"` is among the recorded texts, and `"Soft start"` is.
- [ ] `test_reset_run_cap_handler_restores_default` (same file): after building the
      Safety tab and setting the cap variable to `"99"`, `_reset_run_cap_to_default()`
      leaves `float(dialog._run_cap_a_var.get()) == _DEFAULTS["run_cap_a"][1]`.
- [ ] `test_fixed_limit_lines_quote_the_constants` in `tests/unit/test_safety_limits_text.py` (new):
      the six lines contain `"2200 °C"`, `"1.0e-04 Torr"`, `"5 s"`, `"180 A"` and `"6 V"`.
- [ ] `test_only_the_tc_loss_sample_trips_a_current_cap` in `tests/unit/test_limits_vs_field_runs.py` (new):
      every sample of every run in `all_field_runs()` becomes a Snapshot with
      `program=ProgramStatus(running=True, phase="block", block_type="temp_ramp", control_tc="TC_1")`,
      `tc_c={"TC_1": filament_c}`, `ps_volts`/`ps_amps` from the sample,
      `pressure_torr={"FRG702_Chamber": 1e-6}` and all source ages 0.0 (build it as
      `tests/unit/test_safety_monitor.py` `_make_snapshot` does), and is passed to
      `evaluate_safety(snapshot, run_settings=production_run_settings(), control_tc="TC_1")`.
      The list of `(run.name, t_s)` whose trips include `run_overcurrent` or
      `soft_start_overcurrent` equals exactly
      `[("2026-03-28_tds_5k_per_min", <that run's last t_s>)]`. The assertion message
      lists every tripping run, `t_s` and amps. The docstring states why that one
      sample must trip (the TC-loss runaway, developer-confirmed 2026-11-10) and that
      this test is the guard against a cap that stops a normal run hours in.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Out of scope

The simulator and the three-stage model; tickets 42, 44, 45; PID gains; the stale
allowances and other fixed limits (shown, not changed); CV-only and DAC1; the
hard-coded `max_temperature: 2300` in `gui/main_window.py`; `AGENTS.md`, `CONTEXT.md`,
`docs/adr/` (ticket 51).

## Comments

2026-11-10 (planner): re-planned in place. Decision recorded above. Decoupled from 42;
the cap is checked against the real recorded Field runs instead of the simulator.

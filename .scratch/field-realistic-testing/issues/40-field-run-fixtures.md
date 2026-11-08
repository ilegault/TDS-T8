# 40: Field run fixtures

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

Check in **Field runs**: downsampled excerpts of real lab CSVs, so tests can compare
the Simulated rig and the safety limits with what the rig really did. The lab CSVs
live in `logs/`, which is gitignored (`.gitignore` line 268), so they exist only in
the developer's main clone on the lab-office PC, not in a worktree or a cloud runner.

**Where the source files are:** the `logs/` folder of the main clone of this repo
(the folder that holds `AGENTS.md` and `.git/` as a directory, not a worktree's `.git`
file). Find it with `git worktree list` — the first line is the main clone. If that
folder has no `logs/*.csv` files (a cloud runner), set `Status: blocked` and escalate:
this ticket cannot be done there.

Source CSVs (current filament configuration, all with a `Filament` TC column):

| Fixture name | Source file in `logs/` |
|---|---|
| `2026-03-26_temp_ramp_1550` | `data_log_Fuller_Temp_Ramp_with_1550_Target_20260326_122133.csv` |
| `2026-03-28_tds_5k_per_min` | `data_log_Unirradiated_Bulk_W_Sample_TDS___5k.min_20260328_085521.csv` |
| `2026-03-29_tds_unirradiated_33h` | `data_log_Unirradiated_Bulk_W_Sample_-_33_hr_D2_Exposure_-_TDS_20260329_151315.csv` |
| `2026-03-30_tds_irradiated_33h` | `data_log_Ion_Irradiated_DiMES_Bulk_W_-_33_hr_D2_Exposed_-_TDS_20260330_073924.csv` |
| `2026-04-15_ramp_hold_down` | `data_log_H_and_D_Chamber_Background_Check_-_Temp_Ramp_Up_and_Hold_and_Down_20260415_094625.csv` |

Requirements:
- `scripts/make_field_runs.py <logs folder>`: reads each source with
  `DataLogger.load_csv_with_metadata()` (`t8_daq_system/data/data_logger.py`) or the
  same `#`-header skipping it does, and writes `tests/fixtures/field_runs/<name>.csv`
  with columns `t_s,Filament_C,PS_Voltage,PS_Current`: `t_s` is seconds since the
  first row; the first 300 s keep every recorded row, after that one row per 5 s.
  Rows with an unparsable number are dropped and counted.
- `tests/fixtures/field_runs/manifest.json`: one entry per fixture with `name`,
  `source_file`, `rows_in`, `rows_out`, `rows_dropped`, `peak_current_a`,
  `peak_filament_c`, `control_tc: "Filament"`.
- `tests/field_runs.py`: `load_field_run(name) -> FieldRun` (a frozen dataclass with
  `name`, `t_s`, `filament_c`, `ps_volts`, `ps_amps` as tuples, plus the manifest
  entry) and `all_field_runs() -> list[FieldRun]`. Pure: no Rig, no Tk.
- Each fixture file is under 200 kB.

Tests may fake: nothing. Must be real: the checked-in fixture files.

## Acceptance criteria

- [ ] `test_all_field_runs_are_the_five_listed` in `tests/unit/test_field_runs.py`: `all_field_runs()` returns the five names in the
      table above, and each run's `t_s` is strictly increasing and starts at 0.
- [ ] Same file, `test_peak_current_matches_manifest`: for each run, `max(ps_amps)` equals the manifest's `peak_current_a`
      within 0.1 A, and the 2026-03-28 run's peak is at least 175 A (the supply's
      ceiling was reached).
- [ ] Same file, `test_fixture_files_are_small`: every fixture file's size is below 200 000 bytes.
- [ ] Same file, `test_cold_start_kept_at_full_resolution`: within the first 300 s of each run, the median gap between
      consecutive `t_s` values is at most 0.6 s (the cold-start transient kept at
      full resolution), and after 300 s it is between 4.5 and 5.5 s.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

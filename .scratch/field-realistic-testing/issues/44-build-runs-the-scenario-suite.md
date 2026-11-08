# 44: Build runs the scenario suite

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 42

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0008. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

`scripts/build.py` builds any clean tree, so a build whose whole-run behaviour is
broken can reach the lab. Make the build run the Scenario tests first and record the
result next to the Build ID.

Requirements:
- In `scripts/build.py` `main`, after the dirty-tree check and before writing
  `_build_info.py`, call
  `run([sys.executable, "-m", "pytest", "-m", "scenario", "-q", "--tb=short"], cwd=root)`.
  `default_run` raises `subprocess.CalledProcessError` on failure (it already prints
  the command's output); catch that one exception type in `main`, print
  `Refusing to build: scenario tests failed.` to stderr, and return 1 without running
  PyInstaller. Do not catch any other exception (AGENTS.md §12.1 point 6).
- Parse the pytest summary line from the returned stdout (`N passed`) and pass it to
  `build_info_text`, which gains a `scenarios: str` parameter written as the line
  `Scenarios: <N> passed` in `BUILD_INFO.txt`.
- `--skip-scenarios` flag: skips the run, writes `Scenarios: SKIPPED` in
  `BUILD_INFO.txt`, and appends `-noscen` to the Build ID (extend `build_id` with a
  keyword parameter `scenarios_skipped: bool = False`, so the existing positional
  calls in `tests/unit/test_build_id.py` keep working), so a skipped build is visible
  in the window title, Diagnostic log and CSV header.
- `build.bat` already passes `%*` through; leave it.

Tests may fake: the `run` callable (as `tests/unit/test_build_id.py` already does), git
and PyInstaller. Must be real: `main`, `build_id`, `build_info_text`, files under
`tmp_path`.

## Acceptance criteria

- [ ] `test_failed_scenarios_refuse_the_build` in `tests/unit/test_build_id.py`: with a fake `run` that raises
      `subprocess.CalledProcessError(1, cmd)` for the pytest command, `main([], run=fake, root=tmp_path)`
      returns 1, stderr contains `Refusing to build: scenario tests failed.`, and the
      fake recorded no PyInstaller command.
- [ ] Same file, `test_build_info_records_scenarios_passed`: with a fake `run` returning `"12 passed in 3.4s\n"` for pytest,
      `BUILD_INFO.txt` contains the line `Scenarios: 12 passed`.
- [ ] Same file, `test_skip_scenarios_is_recorded`: `main(["--skip-scenarios"], ...)` records no pytest command, writes
      `Scenarios: SKIPPED`, and the dist folder name ends with `-noscen`.
- [ ] Same file, `test_build_id_marks_skipped_scenarios`: `build_id("abc1234", date(2026, 11, 6), dirty=False, scenarios_skipped=True) == "2026-11-06_abc1234-noscen"`.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

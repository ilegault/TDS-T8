# 39: Tests run with production settings

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 38

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0006, ADR 0007. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

The 2026-11-06 lab trip went unseen because `tests/run_settings_helper.py` `_BASE`
does not match what the operator runs: it disables the Run current cap ("Block/
transition tests ramp the cold sim through >120 A"), uses gains 0.02 / 0.0013 / 0.005
instead of the shipped 0.014 / 0.00078 / 0.00845, a windup limit of 30 instead of 0.4,
and a soft-start threshold of −273 °C. After this ticket every test starts from
**Production settings**, and any test that needs a different value says so where it
calls `make_run_settings`.

Requirements:
- `tests/run_settings_helper.py`: `_BASE` becomes `production_run_settings()` from
  `t8_daq_system/settings/run_settings.py` (ticket 38). `make_run_settings(**overrides)`
  keeps its signature. Update the module docstring and drop the stale comments.
- Run the suite. For each test that now fails, decide by this rule, and record each
  decision in the PR description as a table (test, field, old value, decision):
  - The failing field is **not what the test is about** (for example a block-transition
    test that trips the Run cap): pass the old value at that call site with a trailing
    comment `# not production: <why this test needs it>`.
  - The failing field **is what the test is about** (a cap, Soft start, gains, windup
    or PID behaviour test): that is a finding. Do not override it. Escalate per
    AGENTS.md §12.4 point 8, quoting the failure.
- A test whose subject is the disabled state of a toggle (for example a test of what
  happens when the Run current cap is off) sets that field with
  `# not production: tests the disabled <field>` on the same line. That is the one case
  where a test overrides the field it is about.
- No test is deleted, skipped, xfailed or loosened (ADR 0001). A test whose behaviour
  changed is rewritten in place under the same name.

Tests may fake: everything they faked before. Must be real: `production_run_settings()`.

## Acceptance criteria

- [ ] test_make_run_settings_is_production in `tests/unit/test_run_settings_helper.py`: `make_run_settings() == production_run_settings()`. (no test: it checks test-helper code under `tests/`, which the integrity gate does not swap back to the base version, so check 9 cannot see it fail; the developer reviews the held PR)
- [ ] Same file, test_non_production_overrides_are_marked: scans every `tests/**/*.py` file except itself for the text
      `run_cap_enabled=False`, `soft_start_cap_enabled=False` and
      `soft_start_threshold_c=-273` and asserts each matching line also contains
      `# not production:`. The test lists the offending `file:line` values in its
      assertion message. (no test: it checks test-helper code under `tests/`, which the integrity gate does not swap back to the base version, so check 9 cannot see it fail; the developer reviews the held PR)
- [ ] Same file, test_helper_holds_no_gain_literals: asserts `tests/run_settings_helper.py` contains no float
      literal for a gain (no `kp=`, `ki=`, `kd=`, `windup_limit=` text), so the gains
      cannot drift from `_DEFAULTS` again. (no test: it checks test-helper code under `tests/`, which the integrity gate does not swap back to the base version, so check 9 cannot see it fail; the developer reviews the held PR)
- [ ] The PR description carries the decision table above, one row per test touched. (by hand)
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

- 2026-11-09 (planning): Criteria 1–3 no longer backtick their test names and carry a
  `(no test: ...)` tag. As first written, the ticket could not land: the three tests
  check `tests/run_settings_helper.py`, which check 7 does not swap to base, so they
  pass on base and check 9 failed the PR (PR #117, closed). The tests are still
  required, under exactly those names. Expect the gate to hold the PR (check 7 hold:
  new tests passed on base) for the developer's merge.
  PR #117 found that the production windup limit 0.4 breaks the bumpless-transfer
  tests in `tests/integration/test_handoff_includes_feedforward.py` (their flat Feedforward sits
  0.5 V from the held voltage). Windup is not what those tests are about, so passing
  the old `windup_limit` there with `# not production:` is allowed; list it in the PR
  table so the developer can judge it.

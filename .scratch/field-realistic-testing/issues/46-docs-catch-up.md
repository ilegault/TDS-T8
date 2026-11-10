# 46: Docs catch up with field-realistic testing

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** no

**Blocked by:** 44, 45, 51

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0006, ADR 0001.

## What to build

Record what this effort changed, so the next agent and the developer find it. This
ticket changes `docs/adr/`, `AGENTS.md` and `CONTEXT.md`, so it is `Auto-merge: no`
and a leaf: the developer reviews and merges it.

Requirements:
- `CONTEXT.md`: add **Field run**, **Field case**, **Scenario test** and **Production
  settings**, worded as in the spec's Glossary section. (The Run current cap entry,
  ADR 0006 and AGENTS.md §12.1 point 8 are done in ticket 51.)
- `AGENTS.md` §9 (Running tests): add that tests start from Production settings, that
  overriding a field needs `# not production: <why>` on that line, that
  `pytest -m scenario` runs the Scenario tests, and the Field case rule (every lab
  failure gets its `TRIP` line and a reproducing scenario under
  `tests/scenarios/field_cases/`).
- `AGENTS.md` §11 (PyInstaller Build): the build runs the Scenario tests first;
  `--skip-scenarios` marks the Build ID `-noscen`.
- Do not touch the `ACTIVE-PLAN` block.

Tests may fake: nothing. Must be real: the files above.

## Acceptance criteria

- [ ] `CONTEXT.md` contains the four headings/terms `Field run`, `Field case`,
      `Scenario test`, `Production settings`. (no test: documentation)
- [ ] `AGENTS.md` contains `# not production:`, `pytest -m scenario`,
      `tests/scenarios/field_cases/` and `--skip-scenarios`. (no test: documentation)
- [ ] The text between `<!-- ACTIVE-PLAN:START -->` and `<!-- ACTIVE-PLAN:END -->` is
      unchanged. (no test: documentation)
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

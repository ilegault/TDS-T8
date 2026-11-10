# 51: Docs record the 175 A Run cap and the retired-default migration

**Status:** in-progress

**Runner:** any

**Auto-merge:** no

**Blocked by:** 43

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0006, ADR 0007, ADR 0001.

## What to build

Ticket 43 raised the Run current cap default to 175 A, moved both caps to a
"Safety limits" Settings tab, and made a stored 120 A load as 175 A. Record that where
the next agent and the developer look. This ticket changes `docs/adr/`, `AGENTS.md` and
`CONTEXT.md`, so it is `Auto-merge: no` and a leaf: the developer reviews and merges it.

Requirements:
- `docs/adr/0006-soft-start-and-current-caps.md`: append a section
  `## Amendment — <date ticket 43 merged>: Run current cap default is 175 A` stating:
  the default is 175 A, editable on the Settings → Safety limits tab, valid above 0 A
  and at most 180 A; why: across the five Field runs, including two 33 h TDS runs,
  normal operation peaks at 143–151 A, and 175 A still trips the TC-loss runaway at the
  end of the 2026-03-28 run (179.9 A at 5.97 V); `tests/unit/test_limits_vs_field_runs.py`
  guards it. Do not rewrite earlier text.
- `docs/adr/0007-registry-is-the-single-source-of-settings.md`: append
  `## Amendment — <date ticket 43 merged>: retired defaults migrate` stating: a stored
  value exactly equal to a retired default loads as the current default, with source
  `migrated` in `AppSettings.sources` and the startup dump, and is written on the next
  Save; the only case so far is `run_cap_a` 120 → 175 (`_RETIRED_RUN_CAP_A`); any other
  stored value still wins (Decision 1). Do not rewrite earlier text.
- `CONTEXT.md`, the **Run current cap** entry: `Default 120 A, editable,` becomes
  `Default 175 A, editable on the Settings → Safety limits tab (above 0 A, at most 180 A),`.
- `AGENTS.md` §12.1 point 8: `(default 120 A)` becomes `(default 175 A)`.
- `AGENTS.md` §5.6: after the sentence ending `the startup dump logs that at INFO.`,
  add: `A stored value equal to a retired default loads as the new default with source
  \`migrated\` (ADR 0007 amendment).`
- Do not touch the `ACTIVE-PLAN` block or anything between its markers.

Tests may fake: nothing. Must be real: the files above.

## Acceptance criteria

- [ ] ADR 0006 and ADR 0007 each end with the new amendment section; `git diff` on both
      shows only added lines. (no test: documentation)
- [ ] `CONTEXT.md` and `AGENTS.md` contain `175 A` for the Run current cap and no longer
      contain `Run current cap (default 120 A)` or `Default 120 A, editable`. (no test: documentation)
- [ ] `AGENTS.md` §5.6 contains `` `migrated` ``. (no test: documentation)
- [ ] The text between `<!-- ACTIVE-PLAN:START -->` and `<!-- ACTIVE-PLAN:END -->` is
      unchanged. (no test: documentation)
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

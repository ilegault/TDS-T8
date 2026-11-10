# ADR 0001 — Tests are written first, and failures are never muted

- **Status:** Accepted
- **Date:** 2026-09-21
- **Origin:** adopted from the Right Beamline (RBL) repository's ADR 0001, where the
  rule was written after a planning document instructed an implementing model to
  mark eleven failing tests `xfail`. It complied, inventing plausible reasons for
  each — three citing a calibration step that does not exist anywhere in that
  codebase. A number needed explaining, so an explanation was invented.

## Context

TDS-T8 heats a tungsten specimen to ~1450 °C through a 6 V / 180 A supply,
unattended, for runs that last hours. The costliest bugs in this repository's
history — integral reset between blocks, PSU dropout at block transitions, false
`is_finished` on tick 1 of a cooldown — were each found only during a hardware run.
A test suite that can be made green by editing the test is worse than no suite,
because it is trusted.

## Decision

1. **Tests are written before the code.** Write the test, observe it fail, then
   write the code. The observed failure is what proves the test can detect the
   absence of the behaviour. CI enforces this with `scripts/check_tests_first.py`.
   A change under `t8_daq_system/` must also touch `tests/`. A `.py` file whose code is
   unchanged once docstrings and comments are removed does not count as a change.
   Otherwise the escape is explicit and visible, and its reach depends on where it is
   written: a tag (`[no-test-needed: <reason>]`, `[tests-exempt: <reason>]` or
   `[skip-test-gate]`) in a commit message covers only the files that commit changed,
   and a file is exempt only when every commit that changed it is tagged; the same tag
   in the PR title or body, or the `tests-exempt` / `skip-test-gate` label, covers the
   whole PR, and CI re-runs when the PR text or labels change. The check fails, never
   passes, when it cannot work out what changed.
2. **A failing test is fixed or escalated, never muted.** Never `xfail`, never
   `skip`, never delete or weaken an assertion, never loosen a tolerance without a
   physical justification written next to it, never narrow inputs until it passes,
   never wrap the code under test in `try/except` so the error disappears. These are
   all the same move.
3. **Escalation is the permitted alternative.** Commit the finished work, set the
   ticket's `Status:` to `blocked`, write what was tried and what decision is needed
   under the ticket's `## Comments`, open the PR as a draft. See `AGENTS.md` §12.
4. **Tests assert behaviour, not implementation.** Assert on what a Snapshot
   contains, what the CSV contains, what voltage reached the Rig adapter, what the
   operator is shown — not on private attributes or on whether a method was called.
5. **Tests do not sleep.** Anything time-dependent takes an injectable clock.

## Consequences

- Some changes take longer. That is the point.
- An implementing agent that cannot make a test pass stops and reports, which costs
  a human five minutes rather than an eight-hour hardware run.

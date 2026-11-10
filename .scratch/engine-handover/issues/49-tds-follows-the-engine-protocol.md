# 49: TDS-T8 follows the ticket-engine protocol only

**Status:** in-progress

**Runner:** any

**Auto-merge:** no

**Blocked by:** None

**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`. The engine's protocol is
`src/ticket_engine/resources/ticket_skill.md` in `ilegault/ticket-engine` (pinned tag `v1`).

## What to build

This repo is driven by ticket-engine: the hourly dispatch workflow and the box claim
tickets with `claim/<effort>/<NN>` branches, judge PRs with the Integrity Gate, make up to
three fix attempts on red CI, then escalate. The repo still describes an older,
repo-local protocol (two fix cycles, draft PRs, a `tds-ticket` skill that is not in the
repo, and `scripts/ticket_conductor.py`). A second orchestrator ignores the engine's
claims, so two workers can take the same ticket. After this ticket the repo describes
only the engine's protocol and has no orchestrator of its own.

This ticket changes `AGENTS.md` and `docs/`, so it is `Auto-merge: no` and a leaf: the
developer reviews and merges it.

Requirements:
- Delete `scripts/ticket_conductor.py`. No test imports it; do not add one.
- `AGENTS.md`, "Agent skills" section: replace the bullet that begins
  `**Implementing a ticket:** the \`tds-ticket\` skill` with:
  `**Implementing a ticket:** ticket-engine's runner-agnostic skill,
  \`src/ticket_engine/resources/ticket_skill.md\` in \`ilegault/ticket-engine\`
  (summarised in §12.4). The engine's dispatcher and the box assign tickets; never
  run a second orchestrator on this repo.`
- `AGENTS.md` §12.4 "Implementing a ticket — the protocol": replace points 1–10 with
  these points, in this order, keeping the heading:
  1. Read the `ACTIVE-PLAN` block, the ticket, its effort's `spec.md` if there is one,
     every ADR it names, and the engine's `ticket_skill.md`.
  2. Work the frontier. Never start a ticket whose `Blocked by:` names one that is not
     `done`. Never claim a `ready-for-developer` ticket.
  3. Claims belong to the engine: a ticket is claimed by a `claim/<effort>/<NN>` branch.
     Never create, move or delete a claim branch by hand; the dispatcher releases stale
     ones.
  4. One ticket, one branch, one PR, based on `main`. Never commit to `main`.
  5. Tests first, from the acceptance criteria. Every backticked `test_...` name in a
     criterion must exist and must fail on the base code (Integrity Gate check 9).
  6. Run the three gates in §12.3 locally with 0 failures before pushing.
  7. Red CI gets at most three fix attempts (the engine counts them), then escalate.
  8. Done: `Status: done`, every criterion ticked `- [x]`, a dated summary under
     `## Comments`, all in the same PR.
  9. Cannot finish honestly: `Status: blocked` and the escalation brief from
     `ticket_skill.md` under the ticket's `## Comments`, committed on the branch. Never
     only under `.claude/` or in chat.
  10. Update the module docstring's reasoning (`WHY THIS EXISTS`) when behaviour changes.
- `AGENTS.md` §7: replace each occurrence of `Isaac` with `the developer` (roles, not
  people — engine ADR 0002). Change nothing else in §7.
- Do not touch any other section of `AGENTS.md`, and do not touch the text between
  `<!-- ACTIVE-PLAN:START -->` and `<!-- ACTIVE-PLAN:END -->`.
- `docs/agents/multi-tool-setup.md`: remove the bullet about the `tds-ticket` skill
  existing twice; replace the "Implementation (any tool)" bullet with
  `**Implementation:** the ticket-engine box (local agents) or any tool following
  \`AGENTS.md\` §12.4. Tickets are assigned only by the engine's dispatcher and the box.
  Never run a second orchestrator on this repo: the engine's claim branches are the
  only lock.`; in the first
  paragraph, replace `Zencoder` with `the ticket-engine box`.
- `docs/agents/issue-tracker.md`:
  - Replace `numbered from \`01\`` with `numbered from the highest ticket number
    anywhere under \`.scratch/\` plus one (numbers are unique across the whole repo;
    the engine keys claims and blockers by number alone)`.
  - Replace `needs Isaac at the rig` with `needs the developer at the rig`.
  - In "Ticket file shape", add the lines `**Runner:** any` and `**Auto-merge:** yes`
    after the `**Status:**` line, and add a `## Acceptance criteria` heading above the
    criteria, matching `.github/ISSUE_TEMPLATE/ticket.md`.
- `docs/agents/cowork-project-instructions.md`: replace every `Zencoder` with
  `the ticket-engine box`, and replace the roster entry that begins `- \`tds-ticket\``
  (and its two continuation lines) with `- ticket-engine's \`ticket_skill.md\` —
  every box worker receives it in its prompt. There is no repo-local ticket skill.`

Tests may fake: nothing. Must be real: the files above.

## Acceptance criteria

- [ ] `scripts/ticket_conductor.py` no longer exists. (no test: file removal)
- [ ] `git grep -n "tds-ticket\|ticket_conductor\|Zencoder"` prints nothing outside `.scratch/` and `.claude/plans/`. (by hand)
- [ ] `AGENTS.md` §12.4 has the ten points above and contains `claim/<effort>/<NN>`, `ticket_skill.md` and `three fix attempts`. (no test: documentation)
- [ ] `git grep -n "Isaac" -- AGENTS.md docs/agents/issue-tracker.md` prints nothing. (by hand)
- [ ] The text between `<!-- ACTIVE-PLAN:START -->` and `<!-- ACTIVE-PLAN:END -->` is unchanged (`git diff main -- AGENTS.md` shows no line inside the markers). (by hand)
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

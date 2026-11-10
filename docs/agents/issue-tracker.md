# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from the highest ticket number anywhere under `.scratch/` plus one (numbers are unique across the whole repo; the engine keys claims and blockers by number alone), never a single combined tickets file
- Triage state is recorded as a `Status:` line near the top of each issue file
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Ticket file shape

```
# NN: <title>

**What to build:** <one paragraph>

**Blocked by:** NN, NN   (or: None (can start immediately))

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Read** <ADRs> **first.** `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding.

<structural requirements, stated as requirements>

## Acceptance criteria

- [ ] acceptance criterion
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass

## Comments
```

## Status vocabulary — exactly these words

- `ready-for-agent` — available to be claimed
- `ready-for-developer` — needs the developer at the rig or making a judgement call; an agent must not claim it
- `in-progress`
- `blocked` — escalated, reason under `## Comments`
- `done`

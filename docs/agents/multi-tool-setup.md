# One procedure for every agentic tool

TDS-T8 is worked by Claude Code (local and cloud), Cowork (planning), and the ticket-engine box.
Not every tool reads the same files, so:

- **`AGENTS.md` is the only conventions file.** `CLAUDE.md` contains exactly one
  line, `@AGENTS.md`, which Claude Code follows as an import. Never add a second
  line to `CLAUDE.md` — any content there is invisible to the other tools.
- **Anything an implementer must obey lives in `AGENTS.md`**, not only in a skill or
  command. Skills are conveniences; `AGENTS.md` is the contract.
- **Cloud sessions clone from GitHub.** Anything they need must be committed:
  `AGENTS.md`, `CLAUDE.md`, `CONTEXT.md`, `docs/`, `.scratch/`, `.claude/skills/`,
  `.claude/scripts/`, `.claude/plans/`. The rest of `.claude/` stays local
  (`.gitignore` uses `.claude/*` with negations for exactly those three folders).
- **Do not create `GEMINI.md`** or any other per-tool conventions file; it silently
  forks the rules.

## Pipeline

- **Planning (Cowork / Claude Code):** `/grill-with-docs` → `/to-spec` → `/to-tickets`.
  Produces ADRs, `CONTEXT.md` entries, `.scratch/<effort>/spec.md`, and ticket files.
- **Pointer:** the `ACTIVE-PLAN` block at the bottom of `AGENTS.md` is written only by
  `.claude/scripts/set_plan.py` and holds a pointer (effort paths, next ticket), never
  a copy of a spec.
- **Implementation:** the ticket-engine box (local agents) or any tool following
  `AGENTS.md` §12.4. Tickets are assigned only by the engine's dispatcher and the box.
  Never run a second orchestrator on this repo: the engine's claim branches are the
  only lock.

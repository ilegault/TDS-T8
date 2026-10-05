# ADR 0008 — A Diagnostic log per session and a Build ID on every artifact

- **Status:** Accepted
- **Date:** 2026-10-05
- **Related:** ADR 0003, `.scratch/cold-start-and-traceability/spec.md`

## Context

The application is deployed on a lab PC Isaac does not use. A run on 2026-10-01 could
not be diagnosed: the CSV was never started, the console was hidden (`console=False`),
and nobody could tell which build was installed — the behaviour matched a March 2026
build. Diagnostics today are ~230 `print()` calls, three of which fire every 0.5 s
(~170 000 lines in an 8-hour run).

## Decision

1. **Diagnostic log.** All diagnostics go through Python `logging` to one file per
   session, `logs/console/<YYYY-MM-DD>_<run id>.log`, keeping the last 30 sessions. The
   run id matches the CSV's.
2. **Levels.** INFO (always on): startup header, settings dump, every command, every
   phase/block transition with reason, every trip, and a *heartbeat* (default every
   30 s, editable): time, phase, control TC, setpoint, V, I, FF, P, I, D. WARNING/ERROR:
   every caught exception with traceback; disabled safety caps. DEBUG (off by
   default): per-tick detail. No `print()` remains in application code.
3. **Console window** is a runtime setting, not a build choice: "Show console window
   (takes effect on restart)" attaches a console via `AllocConsole` and mirrors the
   log. The file is written regardless.
4. **Build ID** = `YYYY-MM-DD_<git short hash>`, suffixed `-dirty` when built from an
   uncommitted tree (refused unless `--allow-dirty`). It appears in the dist folder and
   exe name, a `BUILD_INFO.txt` beside the exe (ID, branch, build time, shipped files),
   the window title, the first Diagnostic-log line, and the CSV header. Builds go
   through a committed `scripts/build.py`.

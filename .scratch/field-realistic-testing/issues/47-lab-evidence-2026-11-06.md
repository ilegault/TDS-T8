# 47: Lab evidence from the 2026-11-06 trip

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0008.

## What to build

Confirm the diagnosis from the lab PC's own records, and bring the operators'
programs back for ticket 45. Only the developer can reach the lab PC.

Steps:
1. On the lab PC, note the Build ID in the app's window title.
2. Copy from the app's log folder (Settings → log folder):
   - `console/2026-11-06_*.log` (the Diagnostic log of that session), and
   - the CSV started for that run, if one was started.
   Put them in `.scratch/field-realistic-testing/evidence/2026-11-06/`.
3. Find the line containing `TRIP` in the Diagnostic log and paste it verbatim under
   `## Comments` below, with the Build ID.
4. For each program the operators run routinely, write its blocks as a JSON list in
   `tests/fixtures/programs/<short-name>.json`, one dict per block in `to_dict()` form
   (see ticket 45). Example of one block:
   `{"block_type": "temp_ramp", "rate_k_per_min": 5.0, "end_temp_k": 1273.15, "tc_name": "Filament", "entry_mode": "Rate", "duration_min": 0.0}`.

## Acceptance criteria

- [ ] The Diagnostic log is in `.scratch/field-realistic-testing/evidence/2026-11-06/`.
- [ ] The `TRIP` line and Build ID are under `## Comments`.
- [ ] If the trip kind is **not** `run_overcurrent`, a comment says so, and tickets 42
      and 43 get `Status: blocked` until the planner revises them; the diagnosis in the
      spec was wrong.
- [ ] At least one JSON is in `tests/fixtures/programs/`.

## Comments

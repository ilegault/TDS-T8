# 48: Bench — cold start with the fixed build

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** yes

**Blocked by:** 43, 44

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0006, ADR 0008, AGENTS.md §3 (hardware safety).

## What to build

Prove on the real rig what the Scenario tests claim, before the fixed build goes into
routine use.

Steps:
1. Build with `python scripts/build.py` (no `--skip-scenarios`) from `main` after
   tickets 43 and 44 merged. Record the Build ID and the `Scenarios:` line from
   `BUILD_INFO.txt`.
2. On the lab PC, with Settings at their shipped values for caps and gains, start the
   operators' usual program from a cold filament (control TC below 40 °C), **without**
   a Soft-start block. Stay at the supply; be ready to press Stop.
3. Repeat with a Soft-start block as block 1.
4. After each run, copy that session's Diagnostic log and CSV to
   `.scratch/field-realistic-testing/evidence/bench/`.

## Acceptance criteria

- [ ] Both runs reach their end without the Keysight showing `SO` and with no `TRIP`
      line in the Diagnostic log; or, if either trips, its `TRIP` line is pasted below
      and the run becomes a new Field case (ticket for the planner).
- [ ] Under `## Comments`: Build ID, `Scenarios:` line, and each run's peak current
      and the control TC reading at that moment (from the CSV).
- [ ] The peak currents are compared with the Scenario test's `peak_amps` for the same
      program; a difference above 25 % is noted as a calibration finding for ticket 41's
      model.

## Comments

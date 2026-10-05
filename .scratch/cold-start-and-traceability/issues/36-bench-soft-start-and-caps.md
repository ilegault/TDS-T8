# 36: Bench: Soft start and caps on the real rig

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** no

**Blocked by:** 25, 29, 33

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0006, ADR 0003. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

The developer validates this effort on the real rig with a build that carries a Build ID.

Steps: build with `build.bat` and deploy to the rig PC; confirm the window title shows the Build ID. With a cold filament, run a short TempRamp program and watch Soft start ramp, the status banner and the handoff reason. Trip drill: set the Soft-start cap to 10 A, run, and confirm a `soft_start_overcurrent` trip with a full reason, and that reset is refused until the current falls. Repeat for the Run cap with a low value after handoff. Return the CSV and Diagnostic log to the planning project.

## Acceptance criteria

- [ ] The window title, `BUILD_INFO.txt` and the Diagnostic log's first line show the same Build ID.
- [ ] During Soft start the CSV shows no consecutive-sample current jump above 2 A.
- [ ] Both trip drills produced the expected trip kind, banner text and ERROR log line.
- [ ] The Diagnostic log holds under 2 000 lines per 8 hours of run time.


## Comments

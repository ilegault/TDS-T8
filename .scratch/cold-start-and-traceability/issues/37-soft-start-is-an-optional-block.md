# 37: Soft start is an optional block

**Status:** done

**Runner:** any

**Auto-merge:** no

**Blocked by:** 22, 25

**Spec:** `.scratch/cold-start-and-traceability/spec.md`
**Binding:** ADR 0006 (amended 2026-11-05), ADR 0007. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

The developer runs short PID tests that step the voltage on purpose to see transients.
A Soft start forced on every cold run made those tests impossible. Soft start becomes
a block the operator adds. A new program has none.

## Acceptance criteria

- [x] `SoftStartBlock` (`block_type "soft_start"`, no fields) in `control/program_block.py`.
- [x] ProgramPanel: "Soft Start" in Add Block inserts it as block 1, at most one per
      program. Its row has Del but no Edit and shows the threshold and handoff current from Settings.
- [x] A new program has no Soft start, and `get_soft_start_row_text()` is `""`.
- [x] ProgramRun: no Soft-start block means the first block runs from the first tick, phase
      `"block"`, even with a cold TC.
- [x] With no Soft-start block the Run current cap trips from the first tick.
- [x] A Soft-start block is block index 0. Handoff advances to index 1 through the normal
      bumpless warm-up. A program of only a Soft-start block completes at handoff.
- [x] `compute_preview` draws the Soft-start span only for a Soft-start block.
- [x] "Soft-start current cap is OFF" is logged only when the program has a Soft-start block.
- [x] ADR 0006 amended, CONTEXT.md and AGENTS.md §12.1 point 7 updated, bench ticket 36 told to add the block.

## Comments

Tests that relied on the old automatic Soft start were rewritten in place under their
own names: they now put a `SoftStartBlock` first. No test was deleted or skipped.

The audit for hard-coded voltage, current and temperature limits found no limit below
6 V, 180 A or 2200 °C on the control path. Two items were reported to the developer and
left unchanged by their decision: the Run current cap default is 120 A, and the
Feedforward map gives 3.9 V at 1000 °C where the developer measured 1.7 V, while the
integral term is clamped to ±0.4 V by `pid_windup_limit`.

`PowerProgrammerPanel` is not built by the app. It still shows the old locked
Soft-start row and was left alone.

# ADR 0006 — Every run begins with a Soft start; two toggleable current caps trip the heater

- **Status:** Accepted (amended 2026-11-05: Soft start is an optional block)
- **Date:** 2026-10-05
- **Supersedes:** `COLD_CURRENT_LIMIT_A` (180 A "hold, don't increase" guard), the dead
  `soft_start_threshold_c` / `soft_start_current_limit_a` settings, `pid_output_max`.
- **Related:** ADR 0003 (trips), `.scratch/cold-start-and-traceability/spec.md`

## Context

On 2026-10-01 a deployed build drove ~40 A into a cold filament the moment a program
started. Two independent mechanisms produce a cold-start current step:

1. Builds before 2026-03-27 hardcoded `PIDController(output_max=1.5)` and ignored the
   Settings value; a saturated PID pinned DAC0 at exactly 1.5 V. With DAC1 at the
   "Current Limit" setting the supply sat in CC at that limit (40 A) until the
   filament's resistance rose. Logs of 2026-03-25 and 2026-03-26 show the same 1.500 V
   ceiling.
2. Builds since 2026-07-13 add the Feedforward map to the PID output on the first
   tick. Below its lowest point (50 °C → 0.29 V) the map returned that point's value,
   so a cold filament (≈4–5 mΩ measured in March logs) received ≈0.29 V → 60–70 A in
   one step. The rig-architecture refactor preserved this and pins DAC1 at 180 A, so
   nothing caps it.

The 180 A "cold current guard" can never fire before the supply's own limit, and the
soft-start settings in AppSettings were never read by any code.

## Decision

1. **Soft start.** Every Program run begins in a *Soft start* phase whenever the
   control TC is below the *soft-start threshold*. It is not a block the operator adds
   or can delete. It ramps DAC0 open-loop from the currently commanded voltage at the
   *soft-start ramp rate*. No Feedforward is added during Soft start.
2. **Handoff.** Soft start ends at the first of: control TC ≥ soft-start threshold, or
   measured current ≥ *soft-start handoff current*. The reason that ended it is
   recorded and displayed. Handoff into the first block is a *bumpless transfer*
   (point 5).
3. **Defaults, all editable in Settings:** threshold 200 °C, ramp rate 0.02 V/s,
   handoff current 35 A.
4. **Two current caps, each with its own enable toggle:**
   - *Soft-start current cap* — default **40 A**, active only during Soft start.
   - *Run current cap* — default **120 A**, active from handoff to program end.
   Exceeding an enabled cap is a trip (ADR 0003 semantics: instant, latched cutoff).
   New trip kinds `soft_start_overcurrent` and `run_overcurrent`. The reason names
   measured current, cap, phase, voltage and control-TC temperature, and one line of
   likely cause. A disabled cap is logged at WARNING at run start and shown as
   "OFF" in the Power Programmer.
5. **Bumpless transfer includes Feedforward.** At every handoff and block boundary the
   PID is seeded with `V_now − FF(T_now)`. The PID correction may be negative; only
   the total `FF + PID` is clamped to 0–6 V. The first closed-loop output equals the
   last commanded voltage within one DAC step. Voltage never drops to "restart".
6. **Feedforward below data is 0 V.** Below the map's lowest point `voltage_for`
   returns 0.0, never the lowest point's value.
7. **CV-only is unchanged.** DAC1 stays pinned at 180 A. The caps are trips, not a
   current setpoint.

## Consequences

- `ps_current_limit`, `soft_start_current_limit_a`, `pid_output_max` and
  `COLD_CURRENT_LIMIT_A` are deleted.
- A run that genuinely needs > 120 A at high temperature must raise or disable the
  run cap; the March 2026 runs peaked at 129–180 A.
- The Simulated rig must model cold resistance closely enough that a 0.29 V step on a
  cold specimen exceeds 40 A, so the caps are testable without hardware.

## Amendment — 2026-11-05: Soft start is an optional block

**Supersedes** Decision points 1 and 2 where they say "every Program run" and "not a
block the operator adds or can delete".

**Context.** The developer runs short PID tests that step the voltage on purpose to
see the controller's transient response. A Soft start forced on every cold run makes
those tests impossible: it always ramps the voltage gently up to the threshold first.

**Decision.**

1. Soft start is a `SoftStartBlock` the operator adds from Add Block ("Soft Start").
   It always goes in as block 1, and a program holds at most one. It is deleted like
   any other block. **A new program has none.**
2. The block has no fields of its own. Its threshold, ramp rate and handoff current
   stay Settings, frozen in RunSettings at Run (ADR 0007).
3. While the block runs, points 1–2 above apply unchanged: an open-loop ramp with no
   Feedforward, skipped at once if the control TC is already at or above the
   threshold, ending at Handoff with a recorded reason, and a bumpless transfer into
   the next block. The Soft-start block is block 1 in the Run record's Block_Index.
4. **Without a Soft-start block** the first block runs from the first tick, and the
   **Run current cap is active from that tick**. A voltage step on a cold filament is
   then the operator's deliberate choice, and the Run cap is the backstop.
5. The "Soft-start current cap is OFF" warning is logged only for a program that has
   a Soft-start block.

**Consequences.** A cold run with no Soft-start block can draw a large inrush current
(the Simulated rig draws > 40 A at 0.29 V cold). That is intended for transient tests.
For a normal TDS run the operator adds the block. Bench ticket 36 must add the block.

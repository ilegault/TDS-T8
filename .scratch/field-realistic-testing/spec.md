# Spec: Field-realistic testing

Status: ready-for-agent
Date: 2026-11-06
Blocked by: nothing. Builds on `.scratch/cold-start-and-traceability/` (tickets 19–37).
Related: `docs/adr/0001-tests-first-and-no-muted-failures.md` (binding on all test work),
`docs/adr/0005-practice-mode-is-a-rig-adapter.md`,
`docs/adr/0006-soft-start-and-current-caps.md`,
`docs/adr/0007-registry-is-the-single-source-of-settings.md`,
`docs/adr/0008-diagnostic-log-and-build-id.md`,
`CONTEXT.md` (Control; Heater output and safety; Records and modes)

> ADR 0001 is binding on every ticket here. A test that goes red because the
> simulator or the settings became realistic is a finding, not noise: fix the code
> or escalate. Never loosen it to green.

## Problem Statement

On 2026-11-06 the operator started a program on the lab rig with the build that
contains tickets 19–37. Within about a minute of start, with the filament
thermocouple still below 30 °C, the voltage was rising "faster than normal" and the
Keysight front panel showed **SO**: the software asserted Shut Off (FIO1 = 1), which
it does only on a trip. The suite of 604 tests was green.

Diagnosis (to be confirmed from the lab PC's Diagnostic log, ticket 47):

- The most likely trip is `run_overcurrent`. The Run current cap (ADR 0006, ticket 23)
  defaults to 120 A. Since ticket 37 a program has no Soft start unless the operator
  adds the block, so the PID drives the cold filament from the first tick.
- The real thermocouple sits on the specimen and lags the filament badly. The PID
  sees a cold TC, keeps raising the voltage, and the cold filament (≈5–7 mΩ) passes
  more than 120 A. With a Soft-start block it trips a few seconds later anyway: Soft
  start hands off at 35 A and the PID then pushes on.
- **120 A is below normal operation.** The real lab CSVs (`logs/`, gitignored) show
  ordinary TDS runs on the current filament peaking at 139–144 A (2026-03-29, 03-30,
  04-13, 04-15) and the 5 K/min TDS of 2026-03-28 at 180 A, the supply's ceiling.
  The cap would trip normal runs near their peak even if start-up survived.
- The real TC lags far behind the filament's electrical temperature: on 2026-04-15
  the supply passed 144 A at 4.17 V (≈ 29 mΩ, a hot filament by its TCR) while the
  `Filament` TC read about 127 °C.

Reproduction on the Simulated rig with the shipped defaults
(`settings/app_settings.py` `_DEFAULTS`):

| Simulated specimen | 30 K/min TempRamp from cold |
|---|---|
| `TungstenSim` as shipped | no trip, peak ≈ 78 A |
| `TungstenSim.MASS` × 30 (slow thermal response) | `run_overcurrent` at t = 60 s, TC 51 °C, 130 A |

Why the tests did not catch it:

1. **Tests do not run with production settings.** `tests/run_settings_helper.py`
   `_BASE` disables the Run cap with the comment "Block/transition tests ramp the cold
   sim through >120 A", uses gains 0.02 / 0.0013 / 0.005 (production 0.014 / 0.00078 /
   0.00845), windup limit 30 (production 0.4) and a soft-start threshold of −273 °C.
   The tests met this very problem and switched the cap off.
2. **The simulator was never checked against a whole real run.** `TungstenSim` is one
   lumped node: the TC reads the heater itself, so temperature follows current almost
   instantly and current never exceeds ≈ 80 A. Its calibration (ticket 20) checks two
   points, not a trace.
3. **Tests poke values instead of running programs.** The cap tests force 125 A with
   `SimulatedRig.force_current` and assert a trip. No test asks "does a normal program
   finish from cold without a trip?"
4. **Nothing stands between a green suite and the lab.** `scripts/build.py` builds any
   clean tree; bench tickets (16–18, 36) are optional in practice.

## Solution

Tests run the code the operator runs, against a simulator that behaves like the rig:

- One pure function builds `RunSettings` from `AppSettings`; the tests build theirs
  from the same function and the shipped defaults. A test that needs something else
  overrides that field at its call site, visibly.
- Downsampled excerpts of real lab runs are checked in as **Field runs**
  (`tests/fixtures/field_runs/`).
- The Simulated rig becomes a two-node model — a filament node that carries the
  resistance and a specimen node that the control TC reads — calibrated so that
  replaying a Field run's voltage trace reproduces its recorded current and
  temperature within stated tolerances.
- **Scenario tests** run whole programs from cold to completion on the calibrated
  simulator with production settings and assert no trip. Every lab failure becomes a
  **Field case**: its Diagnostic log line and a scenario that reproduces it.
- A **limits-vs-reality guard** fails if any default trip limit sits below what Field
  runs reached in normal operation.
- `scripts/build.py` runs the scenario suite before building and records the result
  in `BUILD_INFO.txt`.

## Decisions taken

- Field runs come from the current filament configuration only (runs since
  2026-03-26, whose CSVs have a `Filament` TC column); earlier filament designs differ
  electrically and would pull the calibration apart. The control TC is `Filament`.
- A Field run keeps the first 300 s at the recorded 0.5 s spacing (the cold-start
  transient) and every 5 s after that, with only elapsed seconds, the `Filament` TC,
  `PS_Voltage` and `PS_Current`, so each fixture stays under 200 kB.
- Calibration tolerances (ticket 41): over each replayed Field run, current RMS error
  ≤ 15 % of the run's peak current and control-TC RMS error ≤ 50 K. Ticket 20's cold
  criterion (> 40 A at 0.29 V cold) still holds.
- The Run current cap decision (ticket 43) is the developer's, recorded as an ADR 0006
  amendment, before ticket 43 is claimed.

## Out of scope

- Any change to CV-only or DAC1 (AGENTS.md §2).
- PID gain changes; the scenario suite reports peak current and overshoot, it does not
  tune.
- Hardware-in-the-loop tests on the lab PC beyond the bench ticket.
- Running the frozen exe headless; the build gate runs the suite from source.

## Glossary (new terms for `CONTEXT.md`, ticket 46)

- **Field run** — a downsampled excerpt of a real lab CSV, checked in as a test fixture.
- **Field case** — a lab failure captured as its Diagnostic log line plus a scenario
  test that reproduces it and then guards the fix.
- **Scenario test** — a test that runs a whole program from cold to completion on the
  Simulated rig with production settings.
- **Production settings** — the `RunSettings` built from `AppSettings` defaults by the
  same function the app calls at Start.

# CONTEXT.md — TDS-T8 domain glossary

The vocabulary of the TDS-T8 thermal desorption rig and its control application.
Use these words in code, tickets, specs and commit messages. If a term you need is
missing, or the code contradicts a definition here, say so — do not silently pick a
side. Decisions behind these terms are in `docs/adr/`.

Terms marked **(target)** name modules the `rig-architecture` effort creates
(`.scratch/rig-architecture/spec.md`). Until that effort lands they describe the
intended shape, not the current code.

## The physical system

- **Rig** — the physical apparatus as a whole: tungsten specimen, LabJack T8,
  Keysight N5700 supply, XGS-600 controller with FRG-702 gauges, thermocouples,
  camera, and the Hiden QMS. In code, also the module that owns all of it — see
  *Rig module*.
- **Specimen** — the tungsten sample being resistively heated. Its resistance rises
  ~17× from cold to hot, which is why the supply only ever runs in constant voltage.
- **CV-only** — the hard invariant: the Keysight is always in constant-voltage mode.
  DAC1 (current limit) is pinned at full scale (180 A). Only DAC0 (voltage) is
  commanded, clamped to 0–6 V. Never violated, never configurable.
- **Control TC** — the thermocouple a closed-loop block regulates against. Named per
  block (`tc_name`, default `TC_1`). Distinct from *monitor TCs*, which are logged
  and safety-checked but not controlled against.
- **QMS** — the Hiden quadrupole mass spectrometer, driven through MASsoft by
  simulated keypresses/clicks (pyautogui). The application cannot read its state; it
  can only start or abort a scan.

## Acquisition

- **Rig module** **(target)** — the one module that owns the LabJack handle and the
  XGS-600 serial port. It runs the only thread that performs hardware I/O. Nothing
  else reads or writes hardware. ADR 0002.
- **Rig adapter** **(target)** — what the Rig module talks through to reach hardware.
  Two exist: the *T8 adapter* (real LabJack/Keysight/XGS) and the *Simulated rig*.
- **Simulated rig** **(target)** — the Rig adapter used in *practice mode* and in
  tests: a tungsten thermal model in which commanded voltage produces current and
  temperature, driven by an injectable clock. ADR 0005.
- **Rig tick** **(target)** — one pass of the Rig loop: read every input, publish a
  Snapshot, evaluate safety, and — on control ticks — step the Program and apply the
  Heater output. Runs at the sample rate (`sample_rate_ms`).
- **Control step** **(target)** — the subset of Rig ticks on which the Program is
  stepped and a new voltage is written. Fixed at **0.5 s** regardless of sample rate,
  because the PID gains were tuned at that period. ADR 0002.
- **Snapshot** **(target)** — an immutable record of everything read in one Rig tick:
  timestamp, TC temperatures (°C), pressures (**Torr**, internally), PS measured V/I,
  commanded voltage, heater state, trip reason, and per-source staleness. The only
  way any other module learns what the hardware is doing.
- **Stale** — a reading source (a TC, a gauge, the LabJack) that has produced no
  valid value for longer than its allowance. For the control TC and for pressure the
  allowance is **5 s**, after which the condition is a *trip*.
- **Display unit** — the unit the operator chose to see (°C/K/°F; mbar/Torr/Pa).
  Conversion to a display unit happens only at the GUI and in the Run record's
  written values. Safety logic never sees a display unit.

## Control

- **Program** — an ordered list of *blocks* the operator builds in the Power
  Programmer.
- **Block** — one segment of a Program. Three types: `voltage_ramp` (open-loop
  linear voltage), `temp_ramp` (closed-loop PID + feedforward along a linear
  temperature setpoint), `stable_hold` (closed-loop PID to a fixed temperature until
  within tolerance for a hold duration).
- **Block step** **(target)** — a pure function of (block, Snapshot, elapsed time,
  controller state) returning a voltage request and whether the block is finished. No
  clock, no sleep, no hardware.
- **Program run** **(target)** — the module that advances through blocks on control
  steps: block transitions, bumpless PID handover, per-block gain resolution, the QMS
  confirmation pause.
- **Feedforward map** — the rate-indexed, self-building table of steady-state
  voltage versus temperature, ingested from historical CSV logs. Returns the baseline
  voltage the PID corrects around.
- **Bumpless transfer** — re-seeding the PID at a block boundary or Soft-start
  handoff so the first output of `FF + PID` equals the voltage already being
  commanded: the PID is seeded with `V_now − FF(T_now)` and may go negative. ADR 0006.
- **Soft start** — the locked first phase of every Program run while the control TC
  is below the *soft-start threshold*: open-loop DAC0 ramp at the *soft-start ramp
  rate*, no Feedforward. Not a block; cannot be deleted. ADR 0006.
- **Handoff** — the end of Soft start, at the first of: control TC ≥ soft-start
  threshold, or measured current ≥ *soft-start handoff current*. Always a bumpless
  transfer; the reason is recorded.
- **Gains in use** — the Kp/Ki/Kd read from Settings when Run is pressed and frozen
  for that run.
- **Suggestion engine** — the single pure function that turns a completed live
  TempRamp's metrics into suggested gains with reasons. Advisory only. ADR 0007.
- **Run history** — the per-run metric records the Suggestion engine reads
  (`pid_runs.json`); live runs only, each tagged with build ID and run ID.

## Heater output and safety

- **Heater output** **(target)** — the single arbiter of the commanded voltage.
  Receives *heater requests*, applies priority and the latch, enforces CV-only, and
  hands one voltage to the Rig module. ADR 0003.
- **Heater request** — a request for a voltage from one of three sources, highest
  priority first: **Safety**, **Operator** (manual nudge, manual set), **Program**.
- **Trip** — a condition that forces the heater off. Every trip does the same thing:
  instant cutoff — 0 V, output off (Shut Off pin asserted) — and latches. Trip kinds:
  temperature limit, temperature override, pressure interlock, control TC stale,
  pressure stale, LabJack lost, program step error (ADR 0003), soft-start
  overcurrent, run overcurrent (ADR 0006).
- **Soft-start current cap** — measured current above which a trip fires during Soft
  start. Default 40 A, editable, toggleable. ADR 0006.
- **Run current cap** — measured current above which a trip fires after handoff.
  Default 120 A, editable, toggleable. ADR 0006.
- **Latch** — after a trip, Operator and Program requests are ignored until the
  operator explicitly *resets*. A reset is refused while the tripping condition is
  still present.
- **Trip reason** — the machine-readable kind plus a human sentence (sensor, value,
  limit, time). Written to the Run record and shown to the operator. Every trip has
  exactly one.
- **Pressure interlock** — a *permissive*: pressure must be valid and below
  **1e-4 Torr** before the heater may be energised or a QMS scan started, and going
  above it (or going stale for 5 s) trips both. ADR 0004.

## Records and modes

- **Run record** **(target)** — the module that turns each Snapshot plus Program
  state into one CSV row, and each trip or lifecycle event into an event row. Owns
  the column schema. Column names consumed by the Feedforward map's CSV ingest must
  not change.
- **Practice mode** — operating against the Simulated rig instead of the T8 adapter.
  Selected by a toggle that is disabled while running or logging. Every line of
  control, safety and logging code runs identically in both modes. ADR 0005.

- **Run ID** — the identifier shared by one run's CSV, Diagnostic log and Run
  history record.
- **Diagnostic log** — the per-session `logging` file under `logs/console/`; what the
  operator sends when something goes wrong. Never per-tick at INFO. ADR 0008.
- **Heartbeat** — the periodic (default 30 s) INFO line summarising phase, control TC,
  setpoint, V, I, FF and P/I/D.
- **Build ID** — `YYYY-MM-DD_<git short hash>[-dirty]`, stamped on the dist folder,
  exe, `BUILD_INFO.txt`, window title, Diagnostic log and CSV header. ADR 0008.

## Avoid

- "Mock PS", "demo voltage", `practice_mode` flags inside control code — replaced by
  the Simulated rig.
- "Current limit" for DAC1 or for the caps — DAC1 is pinned (CV-only); the caps are
  the *Soft-start current cap* and *Run current cap*.
- "Rampdown" — there is no controlled ramp-down any more; every trip is an instant
  cutoff (ADR 0003).
- "Service", "manager", "handler" for the modules above — use the names here.

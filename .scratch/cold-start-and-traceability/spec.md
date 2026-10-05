# Spec: Cold-start safety and deployed-run traceability

Status: ready-for-agent
Date: 2026-10-05
Blocked by: `.scratch/rig-architecture/` ticket 15 (`15-no-silent-exceptions.md`) landing
on `main`. Tickets 16–18 of that effort (bench) are not prerequisites.
Related: `docs/adr/0006-soft-start-and-current-caps.md`,
`docs/adr/0007-registry-is-the-single-source-of-settings.md`,
`docs/adr/0008-diagnostic-log-and-build-id.md`,
`docs/adr/0003-heater-output-arbitration-and-trips.md`,
`docs/adr/0001-tests-first-and-no-muted-failures.md`,
`CONTEXT.md` (Control; Heater output and safety; Records and modes)

> Read ADRs 0006–0008 before any ticket in this effort. They record decisions made in
> grilling on 2026-10-01…05 and are not open for re-litigation inside a ticket.
> ADR 0001 is binding on all test work.

## Problem Statement

On 2026-10-01 the operator started a program on the deployed rig PC and the Keysight
immediately pushed ~40 A into a cold tungsten filament. Isaac could not tell why:
no CSV had been started, the console window is hidden in deployed builds, nothing
identifies which build is installed, and the behaviour matched a March 2026 build.
The live plot made it worse — the PS axis showed "+1.499" at the top and tick labels
like 0.000825, so 0.1 mV of meter noise looked like violent oscillation.

Investigation found the cause and several layered defects behind it:

- Builds before 2026-03-27 hardcoded the PID's maximum output at 1.5 V and ignored
  the Settings value; a saturated PID pinned DAC0 at 1.5 V and the supply sat in CC
  at its "Current Limit" (40 A) on a cold filament.
- The current architecture has its own cold-start step: the Feedforward map returns
  0.29 V for any temperature below 50 °C, added on the first tick, into a ≈4–5 mΩ
  cold filament (60–70 A), with DAC1 pinned at 180 A and the only current guard set
  at 180 A — so nothing limits it.
- Bumpless transfer seeds only the PID, then adds Feedforward on top, so voltage
  jumps up at every handoff into a TempRamp; the PID output cannot go negative to pull
  it back.
- PID values come from four overlapping layers (constructor defaults, `_DEFAULTS`,
  registry, run-start overrides). Once saved, registry values freeze forever. The
  Settings dialog claims run history may override gains; nothing does.
- Two suggestion engines disagree; the popup can only lower Kp/Ki and raise Kd, and
  writes the registry directly. The oscillation count is dominated by TC noise. The
  dev tree's `pid_runs.json` contains only pytest records.
- Soft-start settings exist in AppSettings and are never read.

## Solution

Every program run now begins with a clearly displayed **Soft start**: an open-loop,
slow voltage ramp (default 0.02 V/s) with no Feedforward, which hands off to the
programmed blocks at 200 °C or 35 A, whichever comes first, without any voltage step.
Two current caps — a 40 A **Soft-start current cap** and a 120 A **Run current
cap**, each editable and each with an on/off toggle — trip the heater and tell the
operator exactly what happened. Settings have one source of truth (the registry),
one editor (the Settings dialog), and are shown and logged when a run starts. One
correct Suggestion engine replaces the two. Every session writes a compact
**Diagnostic log** sized for 8-hour runs that Isaac can read cold; the console window
can be turned on from Settings; and every build carries a **Build ID** on its exe,
folder, window title, log and CSV. Plot axes show true values.

## User Stories

### Soft start
1. As the operator, I want every program to begin with an automatic Soft start, so that a cold filament is never hit with a voltage step.
2. As the operator, I want Soft start to appear as a locked first row in the Power Programmer block list, so that I can see it will happen and cannot delete it by accident.
3. As the operator, I want Soft start drawn as its own shaded band in the program preview plot, so that I can see where it ends and the PID begins.
4. As the operator, I want a status banner during Soft start showing voltage, control-TC temperature and the handoff threshold, so that I know what phase the rig is in at a glance.
5. As the operator, I want Soft start skipped when the control TC is already at or above the threshold, so that a restarted run on a hot specimen does not ramp down first.
6. As Isaac, I want the soft-start threshold, ramp rate and handoff current editable in Settings, so that I can tune them per specimen without a rebuild.
7. As the operator, I want the handoff reason shown and logged ("threshold 200 °C reached" or "handoff current 35 A reached at 143 °C"), so that I know which condition ended Soft start.
8. As Isaac, I want no Feedforward applied during Soft start, so that a map built for hot steady state cannot push a cold filament.
9. As Isaac, I want the Feedforward map to return 0 V below its lowest data point, so that a guess below the data never adds voltage.

### Handoff without a voltage step
10. As the operator, I want the first PID output after handoff to equal the last Soft-start voltage, so that the heater never drops or jumps at the transition.
11. As the operator, I want the same no-step behaviour at every block boundary, so that moving from a hold to a ramp is seamless.
12. As Isaac, I want the PID correction allowed to go negative with only the total voltage clamped to 0–6 V, so that the PID can pull voltage down when Feedforward is above what the filament needs.

### Current caps
13. As the operator, I want a Soft-start current cap (default 40 A) that trips the heater if exceeded during Soft start, so that a cold-start fault cannot damage the filament.
14. As the operator, I want a Run current cap (default 120 A) that trips the heater if exceeded after handoff, so that a fault at temperature is caught.
15. As Isaac, I want each cap independently editable and independently toggleable in Settings, so that a hot run that needs more than 120 A can still be done deliberately.
16. As the operator, I want an overcurrent trip to say the measured current, the cap, the phase, the voltage, the control-TC temperature and a likely cause, so that I can tell Isaac exactly what happened.
17. As Isaac, I want a disabled cap logged at WARNING at run start and shown as "OFF" in the Power Programmer, so that a disabled safety limit is never silent.
18. As the operator, I want an overcurrent trip to behave like every other trip (instant cutoff, latched, banner until reset), so that there is one trip behaviour to learn.

### Settings as one source of truth
19. As Isaac, I want the registry to be the only source of a setting's value, with code defaults used only for a missing key, so that there is no hidden layer overriding what Settings shows.
20. As Isaac, I want `ps_current_limit`, `soft_start_current_limit_a`, `pid_output_max` and the PID constructor's default gains removed, so that no overlapping or dead setting can mislead anyone.
21. As Isaac, I want the Settings dialog to be the only editor of settings, so that nothing changes gains behind the operator's back.
22. As the operator, I want a "Reset PID to defaults" button, so that I can recover from bad gains without editing the registry.
23. As the operator, I want the Power Programmer to show "Gains in use: Kp / Ki / Kd" and both cap states, so that I can confirm what the next run will use.
24. As Isaac, I want gains read once when Run is pressed and frozen for the run, so that a mid-run Settings edit cannot change control behaviour.
25. As Isaac, I want new defaults Kp 0.014, Ki 0.00078, Kd 0.00845, so that a fresh install starts from the operator's tuned values.
26. As Isaac, I want the false "History may override these if 3+ matching runs exist" note removed, so that the UI does not describe behaviour that does not exist.

### Suggestion engine
27. As the operator, I want one post-run suggestion that can raise or lower any gain with a reason for each change, so that suggestions do not contradict each other or drift one way.
28. As the operator, I want "Apply" to open the Settings dialog prefilled with the suggested gains, so that I review and save them deliberately.
29. As Isaac, I want oscillation counting to ignore error crossings inside a ±2 K band, so that TC noise does not always trigger "increase Kd".
30. As Isaac, I want only live runs (not Simulated rig runs) to enter Run history and feed suggestions, so that practice runs cannot tune the real rig.
31. As Isaac, I want each Run history record to carry Build ID, Run ID and adapter, so that I can match it to the CSV and Diagnostic log.
32. As Isaac, I want tests never to write the real Run history file, so that history reflects only real runs.

### Diagnostic log and console
33. As Isaac, I want every session to write a Diagnostic log file named with the date and Run ID, so that the operator can send me one file with the CSV.
34. As Isaac, I want the log to begin with the Build ID, adapter, and every control/safety setting with its source (registry or default), so that I know exactly what the app was configured to do.
35. As Isaac, I want every operator command, phase/block transition (with reason) and trip logged at INFO, so that I can reconstruct the run's story.
36. As Isaac, I want a heartbeat line every 30 s (editable) with phase, control TC, setpoint, V, I, FF, P, I, D, so that an 8-hour run produces about a thousand readable lines, not hundreds of thousands.
37. As Isaac, I want every caught exception logged with its traceback at WARNING or ERROR, so that nothing fails silently on the deployed PC.
38. As Isaac, I want per-tick detail available at DEBUG but off by default, so that I can turn it on for a bench session without flooding normal runs.
39. As Isaac, I want only the last 30 Diagnostic logs kept, so that the deployed PC's disk does not fill.
40. As the operator, I want a "Show console window (takes effect on restart)" setting, so that I can watch the log live without a special build.
41. As Isaac, I want the log file written whether or not the console is shown, so that closing the console never loses information.
42. As Isaac, I want no `print()` left in application code, so that every diagnostic goes through one channel.

### Build ID
43. As Isaac, I want every build to carry a Build ID of the form `YYYY-MM-DD_<hash>`, so that I can tell which code is installed on the rig PC.
44. As Isaac, I want the dist folder and exe named with the Build ID, so that two builds can never be confused on disk.
45. As Isaac, I want a `BUILD_INFO.txt` next to the exe listing Build ID, branch, build time and every shipped file, so that I can audit a deployment.
46. As the operator, I want the Build ID in the window title, so that I can read it to Isaac over the phone.
47. As Isaac, I want the Build ID as the first Diagnostic-log line and in the CSV header, so that every artifact names its build.
48. As Isaac, I want the build refused from an uncommitted tree unless `--allow-dirty`, which appends `-dirty`, so that an untraceable build cannot ship by accident.
49. As Isaac, I want the build run by a committed `scripts/build.py` that `build.bat` calls, so that the build process is versioned and tested.

### Plots
50. As the operator, I want every linear plot axis to show true values with no offset and no scientific notation, so that a tick label is the real reading.
51. As the operator, I want the PS plot to keep a minimum visible span of 0.05 V and 1 A, so that meter noise does not fill the screen.

## Implementation Decisions

- **Soft start lives in Program run.** It is a phase of Program run that precedes the
  first block, not a block type in the Power Programmer's saved profiles. Program run
  receives the soft-start parameters (threshold °C, ramp V/s, handoff A) with the
  program at Run. It is stepped on control steps like blocks; its step is a pure
  function of (parameters, Snapshot, elapsed, last commanded voltage) returning a
  voltage request and whether handoff occurred plus the handoff reason. It is skipped
  when the control TC is at or above the threshold at Run.
- **Program status** gains the phase (`soft_start` or block index), handoff reason,
  gains in use and cap states, so the GUI banner, Power Programmer and Run record
  read them from Snapshots rather than querying Program run.
- **Preview.** `compute_preview` prepends a Soft-start segment (voltage ramp at the
  configured rate until the preview's temperature estimate reaches the threshold) and
  marks its span so the preview plot can shade it.
- **Bumpless transfer.** `PIDController.reset_bumpless` takes the Feedforward value at
  handoff and seeds the integrator so `FF + PID == V_now`. `PIDController` output
  limits become symmetric bounds on the correction (±6 V); the 0–6 V clamp applies to
  the total in the block step. Applied at Soft-start handoff and every closed-loop
  block boundary.
- **Feedforward map.** `voltage_for` returns 0.0 below the lowest backbone point;
  behaviour above the highest point is unchanged.
- **Current caps are safety evaluation.** The pure safety evaluator gains two checks
  reading measured current and Program phase from the Snapshot, each gated by its
  enable flag. Trip kinds `soft_start_overcurrent` and `run_overcurrent`, with reason
  sentence: measured A, cap A, phase, V, control-TC °C, likely cause. They take
  effect through the existing Heater output trip path (instant, latched). The
  "hold, don't increase" cold-current guard in Heater output and
  `COLD_CURRENT_LIMIT_A` are removed. Cap values and enables reach the Rig via the
  config sent with the program.
- **Settings schema changes** (`AppSettings._DEFAULTS` and registry):
  - Add `soft_start_ramp_v_per_s` (0.02), `soft_start_handoff_current_a` (35.0),
    `soft_start_cap_enabled` (True), `soft_start_cap_a` (40.0), `run_cap_enabled`
    (True), `run_cap_a` (120.0), `heartbeat_interval_s` (30), `show_console` (False),
    `diagnostic_log_keep` (30).
  - Keep `soft_start_threshold_c` (200.0), now read.
  - Change `pid_kp` 0.014, `pid_ki` 0.00078, `pid_kd` 0.00845.
  - Delete `ps_current_limit`, `soft_start_current_limit_a`, `pid_output_max`. Stale
    registry values for deleted keys are ignored on load.
  - `AppSettings.load()` records each key's source (`registry`/`default`) for the
    startup dump.
- **PIDController** has no default gains; Program run constructs it from the gains in
  use passed at Run.
- **One Suggestion engine** in `control/`: a pure function from a run's metric record
  plus gains in use to suggested gains with per-gain reasons, able to move any gain
  either way. Metrics computation (overshoot, settling, noise-banded oscillation
  count with ±2 K band, rate-tracking error) is pure and shared. `PIDRunLogger`
  takes its file path as a constructor argument (no default resolved inside
  Program run); records include `build_id`, `run_id`, `adapter`; Simulated-rig runs
  are not recorded. `MainWindow._show_pid_run_summary`'s multiplier logic is deleted;
  the post-run dialog displays the engine's result and "Apply" opens Settings
  prefilled.
- **Diagnostic log module** in `utils/` (no GUI imports): configures root logging
  once at startup with a file handler at
  `logs/console/<YYYY-MM-DD>_<run id>.log` and rotation by count. Run ID is generated
  once per session start and shared with Run record's CSV filename/header. A
  heartbeat emitter runs on Snapshots (in the GUI's snapshot consumer or Run record
  thread — never adding work to the Rig loop beyond a timestamp check) at the
  configured interval. All `print()` in `t8_daq_system/` are replaced with logger
  calls at the level above; an architecture test forbids `print(` in application
  code.
- **Console window.** At startup, if `show_console` is set and the process has no
  console, call `kernel32.AllocConsole` and attach a stream handler to the logger.
  No-op on non-Windows (tests).
- **Build ID.** `scripts/build.py` computes the ID from `git rev-parse --short HEAD`
  and the date, checks `git status --porcelain`, writes a generated
  `t8_daq_system/_build_info.py` (gitignored) with `BUILD_ID`, runs PyInstaller with
  the spec parameterised on the ID, renames output to
  `dist/T8_DAQ_System_<ID>/T8_DAQ_System_<ID>.exe`, and writes `BUILD_INFO.txt`
  listing every shipped file. When `_build_info.py` is absent (dev runs) the Build ID
  is `dev-<hash or unknown>`. The window title, first log line and CSV metadata
  header include it.
- **Plots.** One helper applied to every linear axis in live and preview plots sets
  `useOffset=False` and disables scientific notation. The PS plot enforces minimum
  y-spans of 0.05 V and 1 A around the data's centre when autoscaling.

### Proposed test seams (highest available; one new pure seam per concern)

1. **The Rig, driven by commands, with the Simulated rig and a manual clock** — the
   main seam. Load a program, send Run with settings, advance the clock, read
   Snapshots and trip reasons. Covers Soft start, handoff, bumpless transfer, current
   caps, frozen gains, heartbeat/transition log lines (via captured log records).
   Prior art: `tests/integration/test_program_run_rig.py`, `test_rig_trips.py`,
   `test_block_transitions.py`.
2. **AppSettings with a fake registry** — source-of-truth rules, deleted keys
   ignored, defaults only for missing keys, source tracking. Prior art:
   existing AppSettings tests patching `winreg` in `tests/conftest.py`.
3. **Suggestion engine** — pure function: metric record in, suggestions out.
4. **Build ID** — pure function from (git hash, date, dirty flag) to ID and
   BUILD_INFO text; the PyInstaller call itself is not tested.
5. **Plot axis helper** — formatter state on a real matplotlib axis. Prior art:
   `tests/unit/test_live_plot.py`.

The Simulated rig's cold resistance must make a 0.29 V step on a ~20 °C specimen draw
more than 40 A; if it does not, calibrate it from the March logs (≈4–5 mΩ cold)
as part of the first ticket that needs it.

## Testing Decisions

- Tests assert external behaviour at the seams above: voltages commanded, trips and
  reasons published in Snapshots, log records emitted, settings values loaded,
  suggestions returned. They do not assert private attributes or call counts.
- Tests are written first and must be seen failing (ADR 0001; `check_tests_first.py`).
- Bumpless handoff is asserted numerically: the first closed-loop commanded voltage
  after any handoff equals the last voltage before it within one DAC step
  (6 V / 65535 ≈ 0.1 mV), for Soft start → TempRamp, Soft start → StableHold, and
  block → block, with Feedforward both above and below the handoff voltage.
- Cold-start regression: a TempRamp program on a cold Simulated rig never exceeds the
  Soft-start current cap and never commands a step larger than one control step's
  ramp increment before handoff.
- Overcurrent: forcing Simulated-rig current above each cap trips with the right kind
  and a reason containing measured A and cap A; with the cap disabled, no trip and a
  WARNING record at run start.
- Diagnostic log: a simulated 8-hour run (manual clock) produces fewer than 2 000
  INFO lines; every trip and transition appears; no record at INFO per tick.
- Run history: tests pass a `tmp_path` history file; an architecture test asserts no
  test module writes `logs/pid_runs.json`.
- Architecture tests (prior art `tests/unit/test_architecture_rules.py`): no `print(`
  in `t8_daq_system/`; `control/` and `utils/` still import nothing from `gui/` or
  `tkinter`.

## Out of Scope

- Remote trip alerts (email/Slack) and any remote control — captured in
  `docs/future/remote-trip-alerts.md`.
- Hotfixing the September or March deployed builds; this ships in the new
  architecture only.
- Gain scheduling by zone, rate-indexed Feedforward learning, `AUTO_INGEST_ENABLED`.
- Changing the CV-only invariant or DAC1 handling.
- Camera/IR panel, QMS synchronisation.
- Tuning PID gains on hardware (bench work for Isaac).

## Further Notes

- Interim operating advice until this ships: start programs with a Voltage Ramp block
  to ≈0.3 V before any TempRamp, and confirm the deployed exe's date — if it predates
  2026-03-27 it carries the hardcoded 1.5 V PID ceiling.
- Q24 of the grilling (which cap is 40 A vs 120 A) was taken as: Soft-start cap 40 A,
  Run cap 120 A. If that reading is wrong, only the defaults in this spec and
  ADR 0006 change.
- March 2026 full-heat runs peaked at 129–180 A; a 120 A Run cap will trip such runs
  unless raised or disabled.
- A bench ticket (`ready-for-developer`) should validate Soft start and both caps on
  the real rig once the code tickets land.

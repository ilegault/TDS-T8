# ADR 0007 — The registry is the single source of settings; code defaults only seed it

- **Status:** Accepted
- **Date:** 2026-10-05
- **Related:** ADR 0006, `.scratch/cold-start-and-traceability/spec.md`

## Context

PID gains were resolved through four layers: `PIDController.__init__` defaults,
`AppSettings._DEFAULTS`, the Windows registry (`HKCU\Software\T8_DAQ_System`), and
`update_gains()` at run start. `AppSettings.save()` writes every field, so a value saved
once (for example the 2026-03-24 defaults) is frozen and later default changes never
reach that machine. The post-run popup wrote multiplied gains straight to the registry.
The Settings dialog states "History may override these if 3+ matching runs exist", which
no code does. Two suggestion engines (`PIDRunLogger._generate_suggestions` and
`MainWindow._show_pid_run_summary`) can disagree, and the popup can only lower Kp/Ki
and raise Kd. `logs/pid_runs.json` in the dev tree holds only pytest records because
`ProgramRun` constructs `PIDRunLogger()` on the real path.

## Decision

1. **The registry wins.** `_DEFAULTS` is used only for a key the registry lacks. No
   other module holds a default for a setting. `PIDController` has no default gains;
   gains are required arguments.
2. **One editor.** The Settings dialog is the only place a setting is changed. Nothing
   writes the registry silently. The post-run suggestion's "Apply" opens Settings
   prefilled; the operator saves.
3. **Gains are frozen per run.** On Run, the GUI sends the gains and soft-start/cap
   settings to the Rig with the program; they do not change mid-run. The Power
   Programmer shows "Gains in use" and the cap states.
4. **Startup dump.** At startup every setting that affects control or safety is logged
   at INFO with its source (`registry` or `default`).
5. **Reset PID to defaults** button in Settings restores the `_DEFAULTS` gains.
6. **New default gains:** Kp 0.014, Ki 0.00078, Kd 0.00845 (the operator's values).
7. **One Suggestion engine.** A single pure function maps a run's metrics to suggested
   gains, each with a reason, and may move any gain up or down. Oscillation counting
   ignores error crossings inside a ±2 K noise band. Only live runs (not Simulated rig)
   feed it. Each Run history record carries build ID, run ID and adapter. Tests inject
   the history path; nothing under test writes the real file.

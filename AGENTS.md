# AGENTS.md — Coding Agent Instructions for TDS-T8

This file tells coding agents (Claude Code, Copilot, Cursor, etc.) everything they need to know about this codebase before making any change.

**Read this fully before touching any file.**

## Agent skills

- **Issue tracker:** local markdown under `.scratch/<effort>/` — spec in `spec.md`,
  one ticket per file in `issues/NN-<slug>.md`. See `docs/agents/issue-tracker.md`.
- **Domain docs:** `CONTEXT.md` (glossary) at the repo root, decisions in
  `docs/adr/`. See `docs/agents/domain.md`. ADRs are binding in the areas they cover.
- **Implementing a ticket:** the `tds-ticket` skill (`.claude/skills/` and
  `.agents/skills/`), or §12 below for tools without skills.
- `CLAUDE.md` is a one-line `@AGENTS.md` import. This file is the only conventions
  file. See `docs/agents/multi-tool-setup.md`.

---

## 1. What This Project Is

A Python desktop application for **Thermal Desorption Spectroscopy (TDS)** experiments. It controls a **Keysight N5700 DC power supply** (6 V / 180 A) through a **LabJack T8 DAQ**, reads thermocouples and vacuum pressure gauges, and executes programmed temperature/voltage ramps. All hardware runs on a single Windows lab PC.

**Repository:** `hirstlab` GitHub org, project root `C:\Users\IGLeg\PycharmProjects\TDS-T8`  
**Language:** Python 3.9+  
**GUI:** Tkinter + matplotlib  
**IDE in use:** PyCharm  

---

## 2. The Most Important Rule — CV-Only for Tungsten

> **Never independently ramp current for a tungsten specimen.**

Tungsten has a ~17× cold-to-hot resistance ratio (positive TCR). The correct and only safe strategy is **Constant Voltage (CV) mode**:

- `DAC0` ramps the voltage setpoint.
- `DAC1` is always pinned at full scale (5 V → 180 A ceiling) and never ramped.

Any code that ramps `DAC1` or treats current as the primary control variable for tungsten is **wrong**. Do not introduce it.

---

## 3. Hardware Safety Rules — Never Violate These

These are derived from real hardware damage incidents in this lab. Violating them can destroy equipment.

### 3.1 Ground loop prevention
- Keysight J1 Pins 22 & 23 → T8 GND (DAC reference returns) — OK.
- **Pin 12 must go to `AIN4−`/`AIN5−` as the differential reference.** Never wire Pin 12 to T8 GND directly.

### 3.2 Differential AIN inputs
- Thermocouple channels use T8 differential AIN inputs with the EF (extended feature) temperature conversion.
- **Do not override these registers to single-ended mode in software** — it conflicts with the EF mode and produces negative/garbage temperature readings.

### 3.3 Shut-Off pin polarity
- The Keysight Shut-Off pin is on `FIO1` (physical wiring) — **not** `EIO1`.
- `output_on()` writes `FIO1 = 0` (de-assert). `output_off()` writes `FIO1 = 1`.
- This polarity matches **SW1 switch 5 = UP**. If SW1-5 is DOWN (factory default) the polarity is inverted and every `output_on()` call will immediately shut the supply off.

### 3.4 Keysight SW1 switches (rear panel)
These must be set correctly before connecting analog control:

| Switch | Required | Reason |
|--------|----------|--------|
| 1 | **UP** | Enable analog voltage programming |
| 2 | **UP** | Enable analog current programming |
| 3 | DOWN | 0–5 V programming range |
| 4 | DOWN | 0–5 V monitor range |
| 5 | **UP** | Shutdown polarity matches `output_on()` code |

### 3.5 XGS-600 cable
- Must be a **straight-wired male DB9** cable (PC = DTE, XGS-600 = DCE).
- A null-modem cable or gender changer breaks communication.
- The incorrect DB9 cable has already been plugged into the wrong port (analog) once in this lab — causing hardware damage. Always verify the cable type before connecting.

### 3.6 Hardware limits — never exceed in code
- Max voltage setpoint: **6.0 V** (`KeysightAnalogController.rated_max_volts`)
- Max current ceiling: **180.0 A** (`KeysightAnalogController.rated_max_amps`)
- DAC output range: **0–5 V** (T8 hardware limit)

---

## 4. Codebase Map — File Roles

Before editing any file, understand what it owns:

### `hardware/`
| File | Owns |
|------|------|
| `keysight_analog_controller.py` | All Keysight control: DAC0/DAC1 writes, FIO1 output enable, AIN4/AIN5 readback, voltage/current scaling. Contains SW1 documentation and `test_keysight_scaling()` for offline verification. |
| `thermocouple_reader.py` | T8 EF register reads for each TC channel. Returns Celsius. |
| `xgs600_controller.py` | RS-232 serial driver for XGS-600. Enforces 200 ms minimum poll interval. |
| `frg702_reader.py` | Pressure reading via XGS-600. Handles unit conversions (mbar/Torr/Pa) and gauge status codes. |
| `labjack_connection.py` | T8 USB connection open/close via LJM. |
| `keysight_connection.py` | Legacy VISA path (not used for analog control). |

### `control/`
| File | Owns |
|------|------|
| `temp_ramp_pid.py` | `PIDController` (anti-windup, derivative-on-measurement, slew-rate limiter) + `PIDRunLogger` (saves JSON run history to `logs/pid_runs.json`). **No GUI imports.** |
| `heater_output.py` | `HeaterOutput` — pure arbiter of Safety > Operator > Program, holds trip latch, enforces CV-only. |
| `program_run.py` | `ProgramRun` — stepped by the Rig loop every control tick (0.5 s). Manages block lists (Voltage Ramp, Hold, TempRamp) and soft-start phase before PID handoff. |
| `block_steps.py` | `StepState`, block step protocols and transition logic for `ProgramRun`. |
| `ramp_profile.py` | `RampProfile`, `RampStep`, `StepType`, `ControlMode` data classes. |
| `ramp_executor.py` | Executes `RampProfile` instances (voltage mode). |
| `safety_monitor.py` | `SafetyEvaluator` (pure function evaluating Snapshot against safety limits) and `SafetyMonitor`. |

### `rig/`
| File | Owns |
|------|------|
| `rig.py` | `Rig` — single owner of hardware communication, single-threaded timing loop, Snapshot publication, HeaterOutput resolution. (ADR 0002) |
| `simulated.py` | `SimulatedRig` — in-memory rig adapter with physical tungsten simulation for practice mode and testing. (ADR 0005) |
| `t8_adapter.py` | `T8Adapter` — live hardware adapter interfacing with LabJack T8 and XGS-600. |
| `snapshot.py` | `Snapshot`, `HeaterStatus`, `ProgramStatus`, `SourceStatus` immutable dataclasses. |
| `commands.py` | Immutable command dataclasses sent to Rig (`SetVoltage`, `SetOutput`, `Nudge`, `ResetTrip`, `LoadProgram`, `StartProgram`, `StopProgram`, `ConfirmContinue`, `SelectAdapter`, `UpdateConfig`). |
| `clock.py` | `Clock`, `RealClock`, `ManualClock` for testable deterministic time. |

### `data/`
| File | Owns |
|------|------|
| `data_buffer.py` | In-memory rolling circular buffer keyed by sensor name. |
| `data_logger.py` | CSV writer with metadata header. `load_csv_with_metadata()` for post-run replay. |
| `run_record.py` | `RunRecord` — background CSV writer consuming immutable Snapshots from the Rig loop. |

### `gui/`
| File | Owns |
|------|------|
| `main_window.py` | Central orchestrator (~2 000 lines). Builds hardware objects, wires callbacks, manages run/stop/log state. All GUI callbacks happen here or delegate here. |
| `power_programmer_panel.py` | Block-based programmer UI. Voltage mode (Ramp/Hold blocks with V and A fields) and TempRamp mode (rate K/min blocks). Saves/loads JSON profiles. |
| `live_plot.py` | Matplotlib embedded plots with timeline slider. Plot types: `'tc'`, `'pressure'`, `'ps'`. |
| `pinout_display.py` | Floating window for hardware bring-up verification — live T8 pin assignments, raw voltages, wiring diagram canvas. |
| `settings_dialog.py` | App settings dialog — TC count/type/pins, FRG count/pins/interface, units, serial port. |
| `sensor_panel.py` | Numeric readout tiles for current sensor values. |
| `preflight_dialog.py` | Pre-run checklist dialog. |
| `dialogs.py` | CSV file-load and logging dialogs. |

### `settings/`
| File | Owns |
|------|------|
| `app_settings.py` | Persists to Windows Registry (`HKCU\Software\T8_DAQ_System`). All user-configurable values. `get_tc_pin_list()`, `get_tc_name_list()`, `get_frg_name_list()` helpers generate correct per-sensor lists. |
| `safety_limits.py` | System-wide safety constants (interlock thresholds, stale allowance, rate limits). |

### `utils/`
| File | Owns |
|------|------|
| `helpers.py` | `convert_temperature()`, `convert_pressure()` — unit conversion utilities only. No hardware or GUI imports. |

---

## 5. Design Patterns — Follow These Exactly

### 5.1 Thread safety
- The `Rig` module runs the single hardware I/O and control loop in a **background thread**.
- **All GUI updates must be marshalled to the main thread** via `root.after(0, callback)`. Never call `tk` widget methods from a background thread.
- Snapshots published by `Rig` are immutable dataclasses, safe to read across threads without locks.

### 5.2 Sensor naming
Always use the naming convention:
- Thermocouples: `TC_<name>` (e.g. `TC_1`, `TC_AIN0_K`)
- Pressure gauges: `FRG702_<name>` (e.g. `FRG702_Chamber`)
- Power supply: `PS_Voltage`, `PS_Current`, `PS_Voltage_Setpoint`, `PS_CC_Limit`

Names are user-configurable in `AppSettings`. Never hardcode `"TC_1"` unless you are reading from `sensor_config.json` defaults.

### 5.3 Temperature units inside control code
- All PID and `ProgramRun` internals use **Kelvin**.
- Snapshot `tc_c` contains readings in Celsius (from the hardware EF registers); conversion to Kelvin (`+ 273.15`) is performed when evaluating setpoints and control steps inside `ProgramRun`.
- The GUI and CSV display in the user's selected unit (C/F/K). Use `helpers.convert_temperature()` for all display conversions.

### 5.4 Control layer purity
Files in `control/` and `utils/` must **never import from `gui/`** or `tkinter`. They are pure logic/data modules. This is required for testability — the full test suite mocks all hardware but runs `control/` code directly.

### 5.5 Practice mode
Practice mode is the `Rig` module running the `SimulatedRig` adapter (ADR 0005). No `practice_mode` branch exists in control, safety, or record code. Commanded voltage drives a physical tungsten thermal simulation (`TungstenSim`), producing realistic temperature and current. The real PID, feedforward, safety evaluator, Heater output and Run record run identically in practice as on live hardware.

### 5.6 AppSettings
User settings persist across launches. When adding a new user-configurable field:
1. Add the key and default to `_DEFAULTS` dict in `app_settings.py`.
2. Add it as a property on `AppSettings`.
3. Add registry read/write in `load()` / `save()`.
4. Add UI for it in `settings_dialog.py` if the user needs to change it.

---

## 6. Known Active Issues

Work on these carefully — they involve the live hardware path:

### 6.1 FIO vs EIO pin naming mismatch
- Physical wiring: `FIO0` = analog enable, `FIO1` = Shut-Off.
- Some older code paths reference `EIO0`/`EIO1` (different screw terminals on the T8).
- **The correct names are `FIO0` and `FIO1`.** Any reference to `EIO0`/`EIO1` for these control signals is wrong and must be updated.

### 6.2 Keysight "SO" shutdown on run start
- Caused by SW1 dip switches not set correctly (see Section 3.4) and/or the FIO/EIO naming issue above.
- Do not change the `output_on()` logic in `keysight_analog_controller.py` without verifying SW1-5 state first.

### 6.3 PID gains untested on real hardware
- Default gains: Kp=1.0, Ki=0.05, Kd=0.05.
- `PIDRunLogger` accumulates run history in `logs/pid_runs.json` with auto-generated tuning suggestions — use this data after real-hardware runs to inform gain adjustments.
- Do not change default gains without a justification from real run data.

---

## 7. How to Implement Changes

Isaac (the project owner) uses a **two-phase workflow**:

1. **Analysis first**: Claude / the agent presents its diagnosis and proposed approach. Isaac confirms or corrects it.
2. **Implementation second**: Only after confirmation, provide explicit, numbered, step-by-step instructions — including exact file names, method signatures, and find/replace code blocks.

**Instructions must be:**
- Explicit and unambiguous
- Numbered steps
- Include the exact file name
- Include the exact method or class to modify
- Include the exact old code block and the replacement code block
- Not require the user to make judgment calls

Isaac delegates all coding to an agent and does not write code directly.

---

## 8. Before You Make Any Change

Ask yourself:
1. Does this change affect the voltage/current control path? If yes, re-read Section 2 and 3.
2. Does this change affect any background thread? If yes, check thread-safety (Section 5.1).
3. Does this change add a temperature value to control code? If yes, confirm you are working in Kelvin (Section 5.3).
4. Does this change import `tkinter` or `gui/` from inside `control/` or `utils/`? If yes, **stop** — that violates Section 5.4.
5. Does this change hardcode a sensor name? If yes, read Section 5.2.

---

## 9. Running Tests

```bash
pytest
```

All hardware is mocked. Tests must pass before any PR. The mock setup lives in `tests/conftest.py` — it patches `labjack.ljm`, `pyvisa`, `serial.Serial`, `tkinter`, and `matplotlib.backends`.

If you add new hardware calls, add corresponding mocks in `conftest.py`.

---

## 10. CSV / Log Format

CSV files are written to the `logs/` folder (configurable in Settings). Format:

```
# T8_DAQ_System Log
# Start: 2026-03-25 14:00:00
# TC_Count: 1
# TC_Type: K
# TC_Unit: C
# ...
Timestamp,TC_1,FRG702_Chamber,PS_Voltage,PS_Current,TC_1_rawV,...
2026-03-25 14:00:01.234,23.4,1.5e-6,0.00,0.00,0.000123,...
```

- `TC_1_rawV` columns contain the raw differential voltage from the AIN register before EF conversion — kept for hardware verification.
- `PS_Voltage_Setpoint` and `PS_CC_Limit` are written from `DataBuffer` (injected by the temp-ramp status callback), not directly from the DAQ callback.

`DataLogger.load_csv_with_metadata()` parses the header back into a `metadata_dict` for historical data replay.

---

## 11. PyInstaller Build

```bash
pyinstaller tds.spec --clean
```

Output: `dist/T8_DAQ_System/` — ship the whole folder.

Common issues on target machines:
- **Slow startup**: matplotlib font cache scan. Mitigated in spec file.
- **PyVISA errors at startup**: `pyvisa` resource enumeration. Mitigated in spec file; handled gracefully in code.
- Enable debug by setting `console=True` and `debug=True` in the spec's `EXE()` section, then rebuild.

---

## 12. Invariants and the implementation protocol

### 12.1 Target architecture (ADRs 0002–0005)

The `rig-architecture` effort (`.scratch/rig-architecture/spec.md`) moves the code to
the shape below. Sections 5.1, 5.3 (`get_tc_kelvin_by_name`) and 5.5 describe the
code *before* that effort. Where they conflict with an accepted ADR, the ADR wins,
and the ticket that changes the code updates the section.

1. **One owner of hardware.** Only the Rig module touches `labjack.ljm` or `serial`.
   One thread, one loop: read → Snapshot → safety → (control step every 0.5 s)
   Program → Heater output → write. The GUI never blocks on hardware. (ADR 0002)
2. **One writer of the heater.** Only the Heater output writes DAC0 or Shut Off.
   Requests are prioritised Safety > Operator > Program. Every trip is an instant,
   latched cutoff with a recorded, displayed reason. (ADR 0003)
3. **Pressure is a permissive** for heater and QMS: valid, fresh (≤ 5 s) and below
   1e-4 Torr, compared in Torr, never in a display unit. (ADR 0004)
4. **No `practice_mode` branches** outside the Rig module's adapter choice. Practice
   mode is the Simulated rig. (ADR 0005)
5. **CV-only** (§2) holds on every path, including shutdown.
6. **Never swallow an exception.** `except Exception: pass` is a defect.

### 12.2 Fix or escalate — never mute a failing test

Binding, from `docs/adr/0001-tests-first-and-no-muted-failures.md`: a failing test is
fixed or escalated, never muted. No `xfail`, no `skip`, no deleted or weakened
assertion, no loosened tolerance, no narrowed input, no `try/except` hiding the
error the test exists to surface.

### 12.3 Tests-first CI gate

CI runs, in order, on a Windows runner: `ruff check .`,
`python scripts/check_tests_first.py`, `pytest --tb=short -q`. A change under
`t8_daq_system/` must also touch `tests/`, unless it carries a visible escape tag
(`[no-test-needed: <reason>]`, `[tests-exempt: <reason>]`, `[skip-test-gate]`) or
the `tests-exempt` PR label.

### 12.4 Implementing a ticket — the protocol

1. Read the `ACTIVE-PLAN` block below, the ticket file, its effort's `spec.md`, and
   every ADR the ticket references.
2. **Work the frontier.** Never start a ticket whose `Blocked by:` names one that is
   not `done`. Never claim a `ready-for-developer` ticket.
3. Set `Status: in-progress` when you start and `Status: done` when it lands —
   exactly those words (vocabulary in `docs/agents/issue-tracker.md`).
4. One ticket per branch (`ticket/<effort>-NN-<slug>`), one PR per ticket, based on
   `main`. Never commit to `main`.
5. Test first: write the test, watch it fail, then write the code.
6. Run all three gates locally with 0 failures before pushing.
7. After pushing, watch CI (`gh pr checks --watch --fail-fast`) and fix what it
   finds — at most two fix-and-push cycles, then escalate.
8. **Escalate in four steps:** commit the finished work; set `Status: blocked`;
   append under the ticket's `## Comments` what was tried, what failed (quoted), and
   what decision is needed; open or convert the PR to a **draft**.
9. The escalation report goes in the ticket file under `.scratch/` (committed) —
   never only under `.claude/` or in chat.
10. Update the module docstring's reasoning (`WHY THIS EXISTS`) when behaviour
    changes. A stale *why* is worse than none.

<!-- ACTIVE-PLAN:START -->
## Active implementation plan

_Written by the planning model on 2026-10-05 22:42. Implement this. If something in it is wrong, say so before changing course._

## Active implementation plan — Cold-start safety and deployed-run traceability

This is a pointer, not the work.

- **Spec:** `.scratch/cold-start-and-traceability/spec.md`
- **Tickets:** `.scratch/cold-start-and-traceability/issues/19`–`36`
- **Binding ADRs:** `docs/adr/0006-soft-start-and-current-caps.md`, `0007-registry-is-the-single-source-of-settings.md`, `0008-diagnostic-log-and-build-id.md`, plus 0001 (tests first, never mute) and 0003 (trips).
- **New glossary terms (`CONTEXT.md`):** Soft start, Handoff, Soft-start current cap, Run current cap, Gains in use, Suggestion engine, Run history, Run ID, Diagnostic log, Heartbeat, Build ID; Bumpless transfer redefined to include Feedforward.
- **Tracker conventions:** `docs/agents/issue-tracker.md`. Previous effort `.scratch/rig-architecture/` is done through 15; its bench tickets 16–18 are the developer's.

**Next:** 19, 20 and 34 have no blockers. Start with **19** (Run settings travel with Start) — it is the prefactor every control ticket builds on. 20 and 34 can run in parallel with it.

Dependency graph:

    19 ─┬─ 21 ─┐
        │      ├─ 22 ─┬─ 23 ─┐
    20 ─┼──────┘      │      ├─ 25 ─┐
        │             │      │      │
        ├─ 24 ─┬──────┼──────┘      │
        │      └─ 26 ─┼─ 27 ─ 28    │
        │             ├─ 29 (also 22, 23)
        │             ├─ 30 (also 24)
        └─ 31 (also 26) ─ 32 (also 24)
                      └─ 33 ──────────┴─ 36 [ready-for-developer: bench]
    34 (independent)
    35 [held: Auto-merge no, changes AGENTS.md] ← 23, 24, 26, 33

Requirements an implementer would treat as preferences — they are not:
- Block steps, the Soft-start step, `compute_preview`, `run_metrics`/`suggest` and `build_id` are **pure functions** (no clock, hardware or Tk), because the tests drive them directly.
- `PIDController` has **no default gains**; `PIDRunLogger` has **no default path**. Silent defaults are the bug this effort removes.
- The heartbeat runs on the Run record's thread, **never on the Rig loop**.
- No test is deleted. A test whose behaviour changed is rewritten in place under the same name.
- `SimulatedRig` must draw > 40 A at 0.29 V cold (ticket 20) before any cap test means anything.

Deliberately not done here: remote trip alerts (`docs/future/remote-trip-alerts.md`), hotfixes to old deployed builds, zone gain scheduling, feedforward auto-ingest, any change to CV-only / DAC1.
<!-- ACTIVE-PLAN:END -->

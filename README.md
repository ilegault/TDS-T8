# TDS-T8 — Thermal Desorption Spectroscopy DAQ & Control System

A Python-based data acquisition and power-supply control application for **Thermal Desorption Spectroscopy (TDS)** experiments. The system resistively heats tungsten specimens via a **Keysight N5700 power supply** (6 V / 180 A), reads thermocouple temperatures and vacuum pressures, and executes programmed power ramps or closed-loop PID temperature ramps.

---

## Table of Contents

1. [Hardware Overview](#hardware-overview)
2. [Critical Physics — Why CV-Only for Tungsten](#critical-physics--why-cv-only-for-tungsten)
3. [Software Architecture](#software-architecture)
4. [Project Structure](#project-structure)
5. [Key Files Quick Reference](#key-files-quick-reference)
6. [Sensor Naming Convention](#sensor-naming-convention)
7. [Control Modes](#control-modes)
8. [Practice Mode](#practice-mode)
9. [Safety System](#safety-system)
10. [Hardware Wiring Reference](#hardware-wiring-reference)
11. [Known Hardware Issues & Status](#known-hardware-issues--status)
12. [Installation & Running](#installation--running)
13. [Building a Standalone Executable](#building-a-standalone-executable)
14. [Running Tests](#running-tests)
15. [Resources](#resources)
16. [License](#license)

---

## Hardware Overview

| Device | Role | Interface |
|--------|------|-----------|
| **LabJack T8** | DAQ — reads thermocouples (AIN EF), monitors power supply (AIN), drives analog control signals (DAC) | USB (LJM library) |
| **Keysight N5700** | DC power supply — 6 V / 180 A max — resistively heats specimen | Analog DB25 J1 connector via Phoenix Contact SUBCON-25 breakout board |
| **Agilent XGS-600** | Vacuum gauge controller — reads FRG-702 pressure gauges | RS-232, COM4, OIKWAN FTDI USB-to-serial (straight-wired male DB9) |
| **Leybold FRG-702** | Full-range (Pirani + cold cathode) vacuum gauges | Connected to XGS-600 |
| **Thermocouples** | Temperature measurement — types K, J, T, E, R, S, B, N, C supported | T8 differential AIN channels via EF (extended feature) registers |

---

## Critical Physics — Why CV-Only for Tungsten

Tungsten has a **~17× cold-to-hot resistance ratio** (strong positive Temperature Coefficient of Resistance). This means:

- If you ramp **current** at constant voltage you will immediately overcurrent a cold specimen.
- The correct strategy is always **Constant Voltage (CV) mode**: ramp `DAC0` (voltage setpoint) slowly while keeping `DAC1` (current ceiling) pinned at full scale (5 V → 180 A).
- As tungsten heats, resistance rises naturally, causing current to self-limit — this is the "docile" positive-TCR control characteristic.

**This is the most important design constraint in the entire system. Never independently ramp current for a tungsten specimen.**

---

## Software Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     main_window.py                       │
│    (Tkinter GUI — orchestrates all subsystems)           │
└────────┬─────────────┬──────────────┬────────────────────┘
         │             │              │
    ┌────▼────┐  ┌─────▼─────┐  ┌────▼──────────────────┐
    │ hardware│  │  control  │  │      data / core       │
    │ layer   │  │  layer    │  │      layer             │
    └────┬────┘  └─────┬─────┘  └────┬───────────────────┘
         │             │              │
  LabJack T8      ProgramExecutor  DataAcquisition
  Keysight N5700  PIDController    DataBuffer
  XGS-600         SafetyMonitor    DataLogger
  FRG-702 gauges
  Thermocouples
```

**Data flow during a live run:**

1. `DataAcquisition` runs in a background thread, calling `read_all_sensors()` on every tick.
2. Readings are handed back to `main_window` via an `on_new_data` callback (always marshalled to the GUI thread via `root.after()`).
3. `DataBuffer` holds the rolling in-memory time series; `DataLogger` writes CSV.
4. `LivePlot` pulls from `DataBuffer` and redraws the matplotlib canvas.
5. `ProgramExecutor` / `PIDController` sit in their own thread, writing DAC setpoints to the Keysight via `KeysightAnalogController`.
6. `SafetyMonitor` checks every reading for over-temperature and triggers an emergency shutdown callback if limits are exceeded.

---

## Project Structure

```
TDS-T8/
├── README.md                       # This file
├── AGENTS.md                       # Coding-agent instructions
├── repo.md                         # Machine-readable project reference
├── pytest.ini                      # Pytest configuration
├── requirements.txt                # Python dependencies
├── t8_daq_system.spec              # PyInstaller build spec
├── LICENSE
├── tests/                          # Unit test suite
│   ├── conftest.py                 # Shared mocks (LJM, PyVISA, serial, tkinter, matplotlib)
│   ├── test_data_buffer.py
│   ├── test_data_logger.py
│   ├── test_data_logger_extended.py
│   ├── test_dialogs.py
│   ├── test_frg702_reader.py
│   ├── test_hardware.py
│   ├── test_helpers.py
│   ├── test_integration.py
│   ├── test_live_plot.py
│   ├── test_power_supply.py
│   ├── test_ramp_executor.py
│   ├── test_ramp_profile.py
│   └── test_safety_monitor.py
└── t8_daq_system/
    ├── main.py                     # Application entry point
    ├── config/
    │   └── sensor_config.json      # Default sensor definitions
    ├── hardware/                   # Device communication layer
    │   ├── labjack_connection.py   # LabJack T8 USB connection manager
    │   ├── thermocouple_reader.py  # TC reading via T8 AIN extended-feature registers
    │   ├── xgs600_controller.py    # XGS-600 RS-232 protocol driver
    │   ├── frg702_reader.py        # FRG-702 pressure reading via XGS-600
    │   ├── keysight_connection.py  # Keysight connection (legacy VISA path)
    │   └── keysight_analog_controller.py  # Analog V/I control via T8 DAC/AIN
    ├── data/                       # Data handling
    │   ├── data_buffer.py          # In-memory rolling circular buffer
    │   └── data_logger.py          # CSV file writer with metadata header
    ├── control/                    # Control logic (no GUI imports)
    │   ├── ramp_profile.py         # RampProfile / RampStep data classes
    │   ├── ramp_executor.py        # Voltage ramp profile execution engine
    │   ├── safety_monitor.py       # Over-temperature watchdog & emergency shutdown
    │   ├── temp_ramp_pid.py        # PIDController + PIDRunLogger (JSON history)
    │   └── program_executor.py     # Unified block-based execution (V-ramp + TempRamp)
    ├── core/
    │   └── data_acquisition.py     # Multi-threaded sensor polling loop
    ├── gui/                        # Tkinter user interface
    │   ├── main_window.py          # Main window — layout, callbacks, orchestration
    │   ├── live_plot.py            # Real-time matplotlib graphs with timeline slider
    │   ├── sensor_panel.py         # Numeric sensor readout tiles
    │   ├── power_supply_panel.py   # Power supply status display
    │   ├── ramp_panel.py           # Basic ramp profile panel
    │   ├── power_programmer_panel.py  # Block-based power/temp programmer UI
    │   ├── preflight_dialog.py     # Pre-run hardware checklist dialog
    │   ├── settings_dialog.py      # App settings dialog (sensors, ports, units)
    │   ├── pinout_display.py       # Live T8 pin-assignment & wiring diagram viewer
    │   └── dialogs.py              # CSV file-load and logging dialogs
    ├── settings/
    │   └── app_settings.py         # Persistent settings (Windows Registry / JSON)
    └── utils/
        └── helpers.py              # Temperature & pressure unit conversion utilities
```

---

## Key Files Quick Reference

| File | What it does |
|------|-------------|
| `keysight_analog_controller.py` | All Keysight control: set voltage (`DAC0`), current ceiling (`DAC1`), enable/disable output (`FIO1`), read back V and I via `AIN4`/`AIN5`. Contains SW1 dip-switch documentation. |
| `temp_ramp_pid.py` | `PIDController` class (anti-windup, derivative-on-measurement) + `PIDRunLogger` (saves run metrics to `logs/pid_runs.json` with auto-generated tuning suggestions). |
| `program_executor.py` | `ProgramExecutor` — runs lists of blocks (Voltage Ramp, Stable Hold, Temperature Ramp) in a background thread. Provides soft-start (Phase 1) before handing off to PID. |
| `data_acquisition.py` | `DataAcquisition` — the main polling loop. Reads TCs, pressure gauges, and power supply in one pass; feeds `SafetyMonitor`; fires `on_new_data` callback. |
| `safety_monitor.py` | `SafetyMonitor` — registers per-sensor temperature limits; triggers warning → limit-exceeded → emergency-shutdown callback chain; supports controlled ramp-down before hard cut. |
| `app_settings.py` | Persists all user settings to the Windows Registry under `HKCU\Software\T8_DAQ_System`. Survives restarts. |
| `data_logger.py` | Writes timestamped CSV with a metadata header block; supports `load_csv_with_metadata()` for post-run replay. |
| `main_window.py` | Central orchestrator — builds all hardware objects, wires callbacks, manages run/stop/log state, and routes GUI events. ~2 000 lines. |
| `pinout_display.py` | Floating window showing live T8 pin assignments, raw voltages, and a wiring diagram canvas. Useful for hardware bring-up verification. |

---

## Sensor Naming Convention

| Prefix | Meaning | Example |
|--------|---------|---------|
| `TC_` | Thermocouple temperature | `TC_1`, `TC_AIN0_K` |
| `FRG702_` | FRG-702 vacuum pressure gauge | `FRG702_Chamber` |
| `PS_` | Power supply reading or setpoint | `PS_Voltage`, `PS_Current`, `PS_Voltage_Setpoint`, `PS_CC_Limit` |

Custom names for TCs and FRG gauges can be set in **Settings → Sensors**; they are stored in `AppSettings` and used consistently across the GUI, CSV header, and live plots.

---

## Control Modes

### Block-Based Power Programmer

The **Power Programmer Panel** lets you build a sequence of blocks that `ProgramExecutor` runs in order. There are three block types:

| Block type | What happens |
|-----------|-------------|
| `Voltage Ramp` | Linearly interpolates `DAC0` voltage from `Start V` to `End V` over `Duration` seconds. Current ceiling stays fixed. Use for controlled resistive heating of cold tungsten. |
| `Stable Hold` | Drives to a `Target Temp` and holds it using closed-loop PID control. Optional **QMS Trigger** flag: when enabled, execution pauses at the end of this block and shows a confirmation banner so you can start the QMS before the next block runs. |
| `Temp Ramp` | Ramps from current temperature to `End Temp` at a specified `Rate (K/min)` using PID control. |

Blocks are validated against the 6 V / 180 A hardware limits before execution. Profile JSON files (`.json`) can be saved and loaded from the programmer panel.

**Safe Test Mode** (checkbox in the panel): clamps all voltages to ≤ 1 V and currents to ≤ 10 A — use when bench-testing wiring without a specimen.

#### Soft-Start Phase

Before any PID-controlled block runs, `ProgramExecutor` executes a **soft-start phase** to protect cold tungsten from overcurrent:

- Ramps `DAC0` at 0.010 V/tick until the specimen reaches ~150 °C
- Pauses voltage increases if current exceeds 120 A
- Aborts soft-start if heating rate exceeds 3 K/min
- Then hands control to `PIDController` (max 0.050 V slew per tick)

#### QMS Autoclicker

When a `Stable Hold` block has the **QMS Trigger** flag enabled, the system pauses at block completion and shows a **"Start QMS + Continue Ramp"** banner in the GUI.

Clicking the banner button:
1. Optionally auto-clicks a preconfigured screen coordinate (to start the QMS acquisition software)
2. Logs a `QMS_TRIGGER` event to the CSV
3. Resumes execution of the next block

Configure the auto-click in **Settings → QMS Trigger**:
- Enable the auto-click checkbox
- Use **"Capture Location (3s)"** to record the mouse position over the QMS software's start button (3-second countdown, then captures cursor position)
- Use **"Test Click"** to verify the coordinate before a real run

---

## Practice Mode

Practice mode generates **simulated sensor data** without any hardware connected. Use it to:
- Validate GUI layout and controls
- Verify CSV column headers and data formats before a real run
- Test PID logic by watching the simulated temperature track a ramp profile

**Always validate practice-mode CSV output before connecting real hardware.** Blank columns, locked TC channels, or wrong current readings in practice mode indicate a bug that will also show up live.

Enable practice mode from the startup dialog or command line.

---

## Safety System

`SafetyMonitor` provides a layered shutdown response:

1. **Warning** — temperature approaches limit (configurable threshold, default 90 %). GUI status bar turns yellow.
2. **Limit exceeded** — temperature hits the set limit. GUI turns red.
3. **Emergency shutdown** — power supply output is disabled via `FIO1` and `program_executor` is stopped. A "Reset Safety" button appears in the GUI — only click it after resolving the root cause.

Additional interlock: `DataAcquisition` monitors chamber pressure and can fire an interlock callback if vacuum drops below a safe level during a run.

**Restart lock**: After an emergency shutdown, `SafetyMonitor.is_restart_locked` is `True`. The system will refuse to start a new ramp until the user explicitly resets.

---

## Hardware Wiring Reference

### Keysight N5700 — DB25 J1 Analog Connector

| J1 Pin | Signal | T8 Connection | Direction |
|--------|--------|---------------|-----------|
| 3 | DAC0 — voltage setpoint (0–5 V = 0–6 V out) | `DAC0` | T8 → Keysight |
| 4 | DAC1 — current ceiling (0–5 V = 0–180 A) | `DAC1` | T8 → Keysight |
| 15 | Shut-Off (FIO1) — active logic depends on SW1-5 | `FIO1` | T8 → Keysight |
| 11 | Voltage monitor (0–5 V = 0–6 V) | `AIN4` | Keysight → T8 |
| 24 | Current monitor (0–5 V = 0–180 A) | `AIN5` | Keysight → T8 |
| 22, 23 | Analog GND | T8 GND | — |
| 12 | Monitor reference | `AIN4−` / `AIN5−` (differential negative) | — |

> ⚠️ **Ground loop warning**: Pin 12 goes to `AIN4−`/`AIN5−` as the differential reference. **Never wire Pin 12 directly to T8 GND** — this creates a ground loop and gives wrong current readings.

### Keysight SW1 Dip Switch (rear panel)

| Switch | Required position | Effect |
|--------|------------------|--------|
| 1 | **UP** | Enables analog voltage programming |
| 2 | **UP** | Enables analog current programming |
| 3 | DOWN | Sets 0–5 V programming range |
| 4 | DOWN | Sets 0–5 V monitor range |
| 5 | **UP** | Shutdown polarity: FIO1 = 0 → OFF (matches code's `output_on()`) |

### XGS-600 — RS-232

- Port: `COM4` (OIKWAN FTDI USB-to-serial)
- Cable: **Straight-wired male DB9** (PC = DTE, XGS-600 = DCE)
- Baud: 9600, 8N1, no flow control
- Poll rate: max once per 200 ms (`_MIN_COMMAND_INTERVAL = 0.20`)
- Address byte: `00` (RS-232 default)

> ⚠️ Do **not** use a null-modem cable or DB9 gender changer — they cancel each other and break communication.

---

## Known Hardware Issues & Status

| Issue | Status | Notes |
|-------|--------|-------|
| Keysight shows "SO" (Shut-Off) immediately on run | **Active** | Root causes: SW1 switches 1 & 2 not UP (analog interface disabled), and/or SW1-5 polarity mismatch. See SW1 table above. |
| FIO vs EIO pin mismatch | **Active** | Code uses `EIO0`/`EIO1` in some places; physical wiring is on `FIO0`/`FIO1`. Must be reconciled consistently. |
| PID tuning | **Untested on hardware** | `PIDController` defaults: Kp=1.0, Ki=0.05, Kd=0.05. PID run history (JSON) system is implemented. Gains need real-hardware tuning. |

---

## Installation & Running

### Prerequisites

- Python 3.9+
- [LabJack LJM library](https://labjack.com/support/software/installers/ljm) installed on the system
- Windows (Registry-backed settings; Linux/Mac possible but untested)

### Install dependencies

```bash
pip install -r requirements.txt
```

Key dependencies: `labjack-ljm`, `pyserial`, `matplotlib`, `tkinter` (stdlib on Windows).

### Run

```bash
python -m t8_daq_system.main
```

Or in practice mode:

```bash
python -m t8_daq_system.main --practice
```

---

## Building a Standalone Executable

```bash
pyinstaller t8_daq_system.spec --clean
```

Output: `dist/T8_DAQ_System/` folder. Ship the whole folder (zip it). The `.exe` inside is what users run.

> **PyInstaller performance note**: On non-development machines, matplotlib font scanning and PyVISA resource enumeration are the two most common causes of slow startup. The spec file includes mitigations for both.

---

## Running Tests

```bash
pytest
```

All hardware calls (LJM, PyVISA, PySerial, tkinter, matplotlib canvas) are mocked in `tests/conftest.py` so the test suite runs without any hardware connected.

---

## Resources

- [LabJack LJM Library](https://labjack.com/support/software/installers/ljm)
- [LabJack LJM Python](https://github.com/labjack/labjack-ljm-python)
- [T8 Datasheet](https://support.labjack.com/docs/t-series-datasheet)
- [T8 Thermocouple Application Note](https://support.labjack.com/docs/using-a-thermocouple-with-the-t8)
- Keysight N5700 User Guide — `keysightpowersupplyuserguide.pdf` (project docs)
- XGS-600 Instruction Manual — `xgs600.pdf` (project docs)
- FRG-700/702 User Manual — `Inverted_Magnetron_Pirani_Gauge_FRG700_FRG702.pdf` (project docs)

---

## License

MIT — see `LICENSE` file.

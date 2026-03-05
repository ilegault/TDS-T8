# LabJack T8 Data Acquisition System

A Python-based data acquisition system for the LabJack T8, designed for real-time thermocouple and pressure gauge monitoring with live visualization and CSV data logging.

## Features

- **Always-On Acquisition** - Data collection starts automatically on hardware connection; no manual Start/Stop required
- **Real-time Thermocouple Readings** - Support for Type B, E, J, K, N, R, S, T, and C thermocouples
- **FRG-702 Vacuum Gauge Support** - Digital pressure readings via XGS-600 RS-232 controller
- **Live Plotting** - Real-time matplotlib graphs with dual-mode timeline history slider
- **Logging Resets Graphs** - Clicking "Start Logging" clears all graphs so each recording starts fresh
- **CSV Data Logging** - Timestamped data export with session metadata
- **JSON Configuration** - Easy sensor setup without code changes
- **Practice Mode** - Simulate all sensors without hardware for testing and training
- **Power Programmer** - Automated voltage/current ramp profiles for the Keysight N5761A

---

## Hardware Requirements

| Component | Description                                |
|-----------|--------------------------------------------|
| **LabJack T8** | USB or Ethernet connected DAQ device       |
| **Thermocouples** | Type K, J, T, B, E, N, R, S, and C sensors |
| **XGS-600 Controller** | Agilent/Varian RS-232 vacuum gauge controller |
| **FRG-702 Gauge** | Leybold FRG-702 full-range Pirani/Cold Cathode gauge |
| **Keysight N5761A** | Optional: 6V/180A power supply (analog control via T8) |

---

## Quick Start

### 1. Install LabJack LJM Driver

Download and install from: https://labjack.com/support/software/installers/ljm

### 2. Clone and Install

```bash
git clone <repository-url>
cd TDS-T8
.venv\Scripts\activate        # Windows Command Prompt
# OR
.\.venv\Scripts\Activate.ps1  # Windows PowerShell

pip install -r requirements.txt
```

### 3. Configure Sensors

Edit `t8_daq_system/config/sensor_config.json` to match your hardware setup.

### 4. Run the Application

```bash
python t8_daq_system/main.py
```

**Acquisition starts automatically** once the LabJack T8 connects. There is no Start button.

---

## User Interface

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  T8 DAQ System with Power Supply Control                        [—] [□] [×]  │
├──────────────────────────────────────────────────────────────────────────────┤
│  [ Start Logging ]  [ Load CSV ]  [ Practice Mode: OFF ]  [ Settings ]  ...  │
│                                                      Status: Running          │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │
│  │  TC_1    │  │  TC_2    │  │FRG702_1  │  │ PS Volts │                     │
│  │ 25.3 °C  │  │ 28.1 °C  │  │ 1.5e-6   │  │  4.2 V   │                     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘                     │
├──────────────────────────────────────────────────────────────────────────────┤
│  [TC Plot]            [Pressure Plot]         [Power Supply Plot]            │
├──────────────────────────────────────────────────────────────────────────────┤
│  Safety: ● OK  | Max Temp: 2200°C  | [ History % ] [════════════════▶] LIVE │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Control Buttons

| Button | Function |
|--------|----------|
| **Start Logging** | Begin CSV recording. **Clears all graphs** and the data buffer first so each recording starts from zero. |
| **Stop Logging** | End CSV recording and close the log file. |
| **Load CSV** | View a previously saved log file in the plots. |
| **Practice Mode** | Toggle simulated data mode. Acquisition starts automatically. |
| **Settings** | Configure sensor count, units, sample rate, and display options. |
| **Power Programmer** | Open automated voltage/current ramp profile editor. |

### Timeline History Slider

Located in the bottom safety bar, the slider lets you browse historical data:

| Slider Position | Behaviour |
|-----------------|-----------|
| Far right (≥ 98%) | **LIVE** — plots auto-advance to show the most recent data |
| Pulled left | **FROZEN** — plots show a historical position you choose |

**Mode toggle button** (left of the slider):

| Mode | Description |
|------|-------------|
| **History %** | Shows ALL data from the session start up to the slider position. Pull left to see the full recording zoomed out. |
| **2-min Window** | Always shows exactly a 2-minute viewport. Slider scrubs through the timeline keeping the 2-min window. |

---

## Wiring Diagrams

### Thermocouple Wiring (Differential Input)

```
                    ┌────────────────────────────────┐
                    │         LabJack T8             │
                    │                                │
    ┌──────┐        │   AIN0+ ●──────────┐          │
    │ Type │        │                    │          │
    │  K   │ (+)────┼───────────────────►│          │
    │  TC  │        │                    │          │
    │      │ (-)────┼───────────────────►│          │
    └──────┘        │   AIN0- ●──────────┘          │
                    │                                │
                    │   (Built-in Cold Junction      │
                    │    Compensation)               │
                    └────────────────────────────────┘

    Channel Mapping:
    ┌─────────┬─────────┬─────────┐
    │ Channel │ AIN+    │ AIN-    │
    ├─────────┼─────────┼─────────┤
    │    0    │ AIN0+   │ AIN0-   │
    │    1    │ AIN1+   │ AIN1-   │
    │    2    │ AIN2+   │ AIN2-   │
    │    3    │ AIN3+   │ AIN3-   │
    └─────────┴─────────┴─────────┘
```

### FRG-702 via XGS-600 (RS-232 Digital)

```
    ┌─────────────────┐   RS-232    ┌──────────────────┐
    │   Leybold       │◄───────────►│   Agilent        │
    │   FRG-702       │             │   XGS-600        │
    │   Gauge         │             │   Controller     │
    └─────────────────┘             └─────────┬────────┘
                                              │ USB-to-Serial
                                              ▼
                                        Windows COM port
                                        (e.g. COM4)
```

---

## Usage Workflow

1. **Connect hardware** — LabJack T8 via USB and XGS-600 via RS-232
2. **Launch the app** — `python t8_daq_system/main.py`
3. **Acquisition starts automatically** — status bar shows "Running"
4. **Click "Start Logging"** — enter a filename, graphs reset and CSV recording begins
5. **Click "Stop Logging"** — recording ends, file is saved to `t8_daq_system/logs/`
6. **Close the window** — acquisition stops cleanly

### Practice Mode Workflow

1. Click **Practice Mode: OFF** → it becomes **Practice Mode: ON**
2. Simulated sensor data streams immediately — no hardware needed
3. All features (logging, ramps, graphs) work identically to live mode
4. Click again to exit practice mode

---

## Sensor Configuration

### Configuration File Location

```
t8_daq_system/config/sensor_config.json
```

Settings are also stored in the app via **Settings dialog** (backed by Windows Registry / JSON file).

### Thermocouple Configuration

```json
{
    "name": "TC_1",
    "channel": 0,
    "type": "K",
    "units": "C",
    "enabled": true
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `name` | string | Unique sensor identifier (must start with `TC_`) |
| `channel` | 0–3 | T8 differential input channel pair |
| `type` | B, E, J, K, N, R, S, T, C | Thermocouple type |
| `units` | K, C, F | Temperature unit |
| `enabled` | true/false | Enable/disable sensor |

### FRG-702 Gauge Configuration

```json
{
    "name": "FRG702_Chamber",
    "sensor_code": "T1",
    "units": "mbar",
    "enabled": true
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `name` | string | Unique sensor identifier (must start with `FRG702_`) |
| `sensor_code` | T1–T4 | XGS-600 convection gauge slot code |
| `units` | mbar, Torr, Pa | Display unit |
| `enabled` | true/false | Enable/disable sensor |

### Complete Configuration Example

```json
{
    "device": {
        "type": "T8",
        "connection": "USB",
        "identifier": "ANY"
    },
    "thermocouples": [
        {"name": "TC_1", "channel": 0, "type": "C", "units": "C", "enabled": true},
        {"name": "TC_2", "channel": 1, "type": "C", "units": "C", "enabled": true}
    ],
    "frg702_gauges": [
        {"name": "FRG702_Chamber", "sensor_code": "T1", "units": "mbar", "enabled": true}
    ],
    "xgs600": {
        "enabled": true,
        "port": "COM4",
        "baudrate": 9600
    },
    "logging": {
        "interval_ms": 1000,
        "file_prefix": "data_log",
        "auto_start": false
    }
}
```

---

## Troubleshooting

| Problem | Possible Cause | Solution |
|---------|----------------|----------|
| "Device not found" | LJM driver not installed | Install LJM from labjack.com |
| "Device not found" | T8 not connected | Check USB cable connection |
| Temperature shows `-9999` | Thermocouple disconnected | Check wiring at AIN+/AIN- terminals |
| Pressure reads `None` | XGS-600 not connected | Check RS-232 cable and COM port setting |
| Pressure reads `None` | Wrong COM port | Update `xgs600.port` in sensor_config.json |
| No data logging | Permission denied | Check write permissions on `logs/` folder |
| GUI not updating | Thread crashed | Check console for error messages |
| Import error | Missing packages | Run `pip install -r requirements.txt` |
| App won't start | Wrong Python environment | Activate `.venv` first |

---

## Running Unit Tests

The project has a comprehensive test suite that runs **without any hardware connected** and **without a display**. All hardware dependencies are automatically mocked by `tests/conftest.py`.

### Environment Setup

```bash
# Activate the virtual environment first
.venv\Scripts\activate              # Command Prompt
.\.venv\Scripts\Activate.ps1        # PowerShell
```

### Run Tests

```bash
# Run all tests (from project root TDS-T8/)
.venv\Scripts\pytest

# With verbose output
.venv\Scripts\pytest -v

# Run a specific test file
.venv\Scripts\pytest tests/test_data_buffer.py

# Run tests matching a keyword
.venv\Scripts\pytest -k "ramp"

# Stop on first failure
.venv\Scripts\pytest -x
```

### Test Structure

| Test File | What It Tests |
|-----------|---------------|
| `test_data_buffer.py` | Circular data buffer operations |
| `test_data_logger.py` | CSV file logging |
| `test_data_logger_extended.py` | Extended CSV logging (metadata, multi-sensor) |
| `test_dialogs.py` | GUI dialog logic (filename sanitization, file discovery) |
| `test_frg702_reader.py` | FRG-702 pressure conversion and XGS-600 integration |
| `test_hardware.py` | LabJack connection and thermocouple batch reads |
| `test_helpers.py` | Utility functions (temperature conversion, formatting) |
| `test_integration.py` | MainWindow instantiation and auto-acquisition |
| `test_live_plot.py` | Real-time plot axes, slider modes, and data loading |
| `test_power_supply.py` | Keysight N5761A connection and SCPI commands |
| `test_ramp_executor.py` | Ramp profile execution engine |
| `test_ramp_profile.py` | Ramp step/profile definitions and validation |
| `test_safety_monitor.py` | Temperature limits, emergency shutdown, interlocks |

### How Mocking Works

`tests/conftest.py` automatically mocks before any tests run:

- **`labjack.ljm`** — LabJack hardware driver
- **`pyvisa`** — VISA instrument communication
- **`serial`** — RS-232 communication (XGS-600)
- **`tkinter`** — GUI framework (no display needed)
- **`matplotlib`** — Plotting library (no rendering needed)

---

## Sensor Naming Convention

| Prefix | Meaning | Example |
|--------|---------|---------|
| `TC_` | Thermocouple temperature | `TC_1`, `TC_2` |
| `FRG702_` | FRG-702 vacuum pressure gauge | `FRG702_Chamber` |
| `PS_` | Power supply reading | `PS_Voltage`, `PS_Current` |

---

## Project Structure

```
TDS-T8/
├── README.md                      # This file
├── repo.md                        # Machine-readable project reference
├── pytest.ini                     # Pytest configuration
├── requirements.txt               # Python dependencies
├── tests/                         # Unit test suite
│   ├── conftest.py                # Shared mocks (labjack, pyvisa, serial, tkinter, matplotlib)
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
    ├── main.py                    # Application entry point
    ├── config/
    │   └── sensor_config.json     # Sensor definitions
    ├── hardware/                  # Device communication
    │   ├── labjack_connection.py  # LabJack T8 connection manager
    │   ├── thermocouple_reader.py # Thermocouple reading via T8 EF registers
    │   ├── xgs600_controller.py   # XGS-600 RS-232 vacuum gauge controller
    │   ├── frg702_reader.py       # FRG-702 pressure reading (digital via XGS-600)
    │   ├── keysight_connection.py # Keysight N5761A connection
    │   └── keysight_analog_controller.py  # Analog V/I control via T8 DAC
    ├── data/                      # Data handling
    │   ├── data_buffer.py         # In-memory circular buffer
    │   └── data_logger.py         # CSV file logging
    ├── control/                   # Control logic
    │   ├── ramp_profile.py        # Ramp step/profile definitions
    │   ├── ramp_executor.py       # Ramp profile execution engine
    │   └── safety_monitor.py      # Temperature limits & emergency shutdown
    ├── core/
    │   └── data_acquisition.py    # Multi-threaded acquisition loop
    ├── gui/                       # User interface
    │   ├── main_window.py         # Main window & orchestration
    │   ├── live_plot.py           # Real-time matplotlib graphs + slider
    │   ├── sensor_panel.py        # Numeric sensor display tiles
    │   ├── power_supply_panel.py  # Power supply status display
    │   ├── ramp_panel.py          # Ramp profile execution panel
    │   ├── power_programmer_panel.py  # Power programmer UI
    │   ├── preflight_dialog.py    # Pre-run checklist dialog
    │   ├── settings_dialog.py     # App settings dialog
    │   ├── pinout_display.py      # T8 pinout visualization
    │   └── dialogs.py             # File load / logging dialogs
    ├── settings/
    │   └── app_settings.py        # Persistent app settings (Registry/JSON)
    ├── utils/
    │   └── helpers.py             # Temperature/pressure unit conversion
    └── logs/                      # CSV output files (auto-created)
```

---

## Resources

- [LabJack LJM Library Download](https://labjack.com/support/software/installers/ljm)
- [LabJack LJM Python Library](https://github.com/labjack/labjack-ljm-python)
- [T8 Datasheet](https://support.labjack.com/docs/t-series-datasheet)
- [Thermocouple Application Note](https://support.labjack.com/docs/using-a-thermocouple-with-the-t8)

---

## License

See LICENSE file for details.

# TDS-T8 Repository Reference

> Machine-readable project reference for coding agents. For human documentation see README.md.

---

## Project Identity

| Field | Value |
|-------|-------|
| **Name** | TDS-T8 LabJack Data Acquisition System |
| **Language** | Python 3.11.7 |
| **GUI Framework** | tkinter (bundled with Python) |
| **Plotting** | matplotlib embedded via FigureCanvasTkAgg |
| **Hardware Interface** | LabJack LJM library + pyserial |
| **Platform** | Windows (primary); registry-backed settings |
| **Entry Point** | `t8_daq_system/main.py` |

---

## Python Virtual Environment

| Field | Value |
|-------|-------|
| **Location** | `C:\Users\IGLeg\PycharmProjects\TDS-T8\.venv` |
| **Python Version** | 3.11.7 |
| **Purpose** | Isolates project dependencies from the global Python installation |

### Activation Commands

```bat
# Command Prompt
.venv\Scripts\activate

# PowerShell
.\.venv\Scripts\Activate.ps1
```

### Running the Application

```bat
.venv\Scripts\python t8_daq_system\main.py
```

---

## Dependencies (`requirements.txt`)

| Package | Version Constraint | Role |
|---------|--------------------|------|
| `labjack-ljm` | >=1.23.0 | Hardware communication with LabJack T8 DAQ device |
| `matplotlib` | >=3.5.0 | Real-time graph rendering embedded in tkinter |
| `numpy` | >=1.21.0 | Numerical arrays for data processing |
| `pyserial` | >=3.5 | RS-232 serial communication with XGS-600 controller |
| `psutil` | >=5.9.0 | System/process utilities (startup profiling) |
| `zeroconf` | >=0.131.0 | Network device discovery |

Install all dependencies:
```bat
.venv\Scripts\pip install -r requirements.txt
```

---

## Test Suite

| Field | Value |
|-------|-------|
| **Test Count** | ~235+ tests |
| **Runner** | pytest |
| **Config File** | `pytest.ini` |
| **Test Directory** | `tests/` |
| **Hardware Required** | No — all hardware mocked by `tests/conftest.py` |
| **Display Required** | No — tkinter and matplotlib mocked |

### Running Tests

```bat
# Run all tests
.venv\Scripts\pytest

# Verbose output
.venv\Scripts\pytest -v

# Specific test file
.venv\Scripts\pytest tests\test_data_buffer.py

# Tests matching keyword pattern
.venv\Scripts\pytest -k "ramp"

# Stop on first failure
.venv\Scripts\pytest -x
```

### pytest.ini Settings

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

### Mock Strategy (`tests/conftest.py`)

Before any test runs, conftest.py inserts mock objects into `sys.modules`:

| Mocked Module | What It Replaces |
|---------------|-----------------|
| `labjack.ljm` | LabJack T8 hardware driver (`eWriteName`, `eReadName`, `openS`, etc.) |
| `pyvisa` | VISA instrument communication (Keysight power supply) |
| `serial` | RS-232 serial port (XGS-600 controller) |
| `tkinter` | GUI framework (no display required) |
| `matplotlib` | Plotting library (no rendering) |

---

## Directory Structure

```
TDS-T8/
├── README.md                          # Human-readable documentation
├── repo.md                            # This file (machine-readable reference)
├── pytest.ini                         # Pytest configuration
├── requirements.txt                   # pip dependencies
├── .venv/                             # Python 3.11.7 virtual environment (Windows)
│
├── tests/                             # Unit test suite
│   ├── __init__.py
│   ├── conftest.py                    # Auto-mocking of all hardware/GUI dependencies
│   ├── test_data_buffer.py            # DataBuffer circular buffer tests
│   ├── test_data_logger.py            # DataLogger CSV output tests
│   ├── test_data_logger_extended.py   # Extended logging with metadata
│   ├── test_dialogs.py                # GUI dialog logic (filename, file discovery)
│   ├── test_frg702_reader.py          # FRG-702 pressure conversion + XGS-600
│   ├── test_hardware.py               # LabJack connection and TC reads
│   ├── test_helpers.py                # Temperature/pressure unit conversion
│   ├── test_integration.py            # MainWindow instantiation + auto-acquisition
│   ├── test_live_plot.py              # LivePlot axes, slider modes, data loading
│   ├── test_power_supply.py           # Keysight N5761A SCPI command tests
│   ├── test_ramp_executor.py          # Ramp profile execution engine
│   ├── test_ramp_profile.py           # Ramp step/profile validation
│   └── test_safety_monitor.py         # Safety limits and emergency shutdown
│
└── t8_daq_system/
    ├── __init__.py
    ├── main.py                        # Entry point: creates tkinter root + MainWindow
    ├── startup_profiler.py            # Startup timing diagnostics
    │
    ├── config/
    │   └── sensor_config.json         # Sensor definitions (thermocouples, gauges)
    │
    ├── hardware/                      # Physical device communication layer
    │   ├── __init__.py
    │   ├── labjack_connection.py      # LabJackConnection: opens T8 via LJM
    │   ├── thermocouple_reader.py     # ThermocoupleReader: reads TC EF registers
    │   ├── xgs600_controller.py       # XGS600Controller: RS-232 protocol driver
    │   ├── frg702_reader.py           # FRG702Reader: reads pressures via XGS-600
    │   ├── keysight_connection.py     # KeysightConnection: VISA connection
    │   └── keysight_analog_controller.py  # KeysightAnalogController: T8 DAC/AIN
    │
    ├── data/                          # Data storage layer
    │   ├── __init__.py
    │   ├── data_buffer.py             # DataBuffer: circular in-memory ring buffer
    │   └── data_logger.py             # DataLogger: timestamped CSV writer
    │
    ├── control/                       # Automation and safety layer
    │   ├── __init__.py
    │   ├── ramp_profile.py            # RampStep, RampProfile: voltage ramp definitions
    │   ├── ramp_executor.py           # RampExecutor: threaded ramp execution engine
    │   └── safety_monitor.py          # SafetyMonitor: temperature limits + shutdown
    │
    ├── core/
    │   ├── __init__.py
    │   └── data_acquisition.py        # DataAcquisition: high-speed threaded sensor loop
    │
    ├── settings/
    │   ├── __init__.py
    │   └── app_settings.py            # AppSettings: persistent settings via Windows Registry
    │
    ├── utils/
    │   ├── __init__.py
    │   └── helpers.py                 # convert_temperature(), convert_pressure(), etc.
    │
    ├── gui/                           # Tkinter user interface layer
    │   ├── __init__.py
    │   ├── main_window.py             # MainWindow: top-level GUI orchestration (~2000 lines)
    │   ├── live_plot.py               # LivePlot: embedded matplotlib graph + slider
    │   ├── sensor_panel.py            # SensorPanel: numeric reading tiles
    │   ├── power_supply_panel.py      # PowerSupplyPanel: PS voltage/current display
    │   ├── ramp_panel.py              # RampPanel: ramp profile editor and executor
    │   ├── power_programmer_panel.py  # PowerProgrammerPanel: V/I ramp programmer
    │   ├── preflight_dialog.py        # PreflightDialog: pre-run safety checklist
    │   ├── settings_dialog.py         # SettingsDialog: sensor/unit/rate configuration
    │   ├── pinout_display.py          # PinoutDisplay: T8 pin assignment visualization
    │   ├── programmer_preview_plot.py # ProgrammerPreviewPlot: ramp profile preview
    │   └── dialogs.py                 # LoggingDialog, LoadCSVDialog
    │
    └── logs/                          # CSV output directory (auto-created at runtime)
```

---

## Key Classes and Responsibilities

### `DataAcquisition` (`core/data_acquisition.py`)
- Runs in a **dedicated background thread** via `start_fast_acquisition(callback)`
- Reads all sensors each cycle: thermocouples (LJM), pressure (XGS-600), power supply (T8 AIN)
- Calls `callback(timestamp, all_readings, tc_readings, frg702_details, safety_shutdown, raw_voltages)` on each cycle
- `stop_fast_acquisition()` sets stop flag; thread exits within one cycle (≤ sampling interval + serial timeout)
- Supports `practice_mode=True` for simulated data without hardware

### `MainWindow` (`gui/main_window.py`)
- Top-level tkinter `Tk` root wrapper
- **Auto-starts acquisition** on hardware connection or practice mode toggle (no Start button)
- `_on_start()`: creates `DataAcquisition`, wires callback, starts thread
- `_on_stop()`: stops thread; used internally by safety shutdown and window close
- `_on_toggle_logging()`: **clears data buffer and all graphs** before starting a new recording
- `_toggle_slider_mode()`: switches all plots between `'history_pct'` and `'window_2min'` slider modes
- `_deferred_hardware_init()`: runs 100ms after launch to avoid startup blocking

### `LivePlot` (`gui/live_plot.py`)
- Embeds a `matplotlib.figure.Figure` in a `ttk.Frame`
- Plot types: `'tc'` (thermocouple), `'pressure'` (log-scale FRG-702), `'ps'` (dual-axis V/I)
- Fixed 2-minute rolling window in live mode (`WINDOW_SECONDS = 120`)
- **Slider modes** (`_slider_mode` attribute):
  - `'history_pct'` (default): frozen mode shows ALL data from session start to slider position (no 2-min clip)
  - `'window_2min'`: frozen mode shows exactly 2-min viewport at slider position
- `set_slider_mode(mode)`: switches mode and redraws if currently frozen
- `clear()`: resets axes, clears line objects — called when logging starts
- `sync_scroll(value)`: called by master scrollbar; sets live/frozen state and redraws

### `DataBuffer` (`data/data_buffer.py`)
- Circular ring buffer keyed by sensor name
- `add_reading(readings_dict)`: adds timestamped readings for all sensors
- `get_sensor_data(name)`: returns `(timestamps_list, values_list)`
- `clear()`: wipes all data — called when logging starts to reset graphs

### `XGS600Controller` (`hardware/xgs600_controller.py`)
- RS-232 serial protocol driver for Agilent/Varian XGS-600
- `read_all_pressures()`: single command returns all slot readings (preferred polling method)
- `send_command(cmd)`: enforces 200ms inter-command delay; 1.0s read timeout
- `disconnect()`: closes serial port cleanly

### `SafetyMonitor` (`control/safety_monitor.py`)
- Monitors thermocouple readings against configurable limits
- `TEMP_OVERRIDE_LIMIT = 2200°C`: hard override that triggers controlled ramp-down
- On limit breach: calls registered callbacks and sets `_safety_triggered` flag
- `MainWindow` stops acquisition and shows reset UI on safety breach

### `AppSettings` (`settings/app_settings.py`)
- Persists all user-configurable settings in `HKEY_CURRENT_USER\Software\T8_DAQ_System`
- Settings: TC count/types/pins, temperature unit, pressure unit, sample rate, display rate, axis scales, serial port, appearance colors

---

## Data Flow Architecture

```
Hardware Layer                 Core Layer              GUI Layer
─────────────────────────────────────────────────────────────────
ThermocoupleReader ──┐
XGS600Controller  ───┼──► DataAcquisition ──► on_new_data() ──► DataBuffer ──► LivePlot
KeysightAnalogCtrl──┘      (background        (callback in        (circular      (reads
                           thread)            main thread)        ring buf)      buffer)
                                                    │
                                                    ├──► DataLogger (CSV file)
                                                    ├──► SensorPanel (numeric display)
                                                    └──► SafetyMonitor.check_limits()
```

---

## Acquisition Lifecycle

1. **App launch** → `MainWindow.__init__()` → `root.after(100, _deferred_hardware_init)`
2. **Hardware init** → connects LabJack T8 → `_update_connection_state(True)` → `_auto_start_acquisition()`
3. **Or practice mode ON** → `_toggle_practice_mode()` → `_auto_start_acquisition()`
4. **`_auto_start_acquisition()`** → calls `_on_start()` if `not self.is_running`
5. **`_on_start()`** → creates `DataAcquisition`, calls `start_fast_acquisition(callback)`
6. **Each cycle** → sensor reads → `callback()` → `DataBuffer.add_reading()` → `_update_gui()` redraws plots
7. **Logging start** → `_on_toggle_logging()` → `data_buffer.clear()`, all plots `clear()`, slider reset to live, then `DataLogger.start_logging()`
8. **Safety breach** → `SafetyMonitor` → `_handle_safety_shutdown()` → `_on_stop()`
9. **Window close** → `on_closing()` → `daq.stop_fast_acquisition()`, `logger.stop_logging()`

---

## Configuration: `sensor_config.json`

Located at `t8_daq_system/config/sensor_config.json`. **Not the primary config source** — the `AppSettings` class (Windows Registry) is authoritative for most settings. The JSON file provides defaults and hardware-specific parameters.

```json
{
    "device": {
        "type": "T8",
        "connection": "USB",
        "identifier": "ANY"
    },
    "thermocouples": [
        {
            "name": "TC_1",
            "channel": 0,
            "type": "C",
            "units": "C",
            "enabled": true
        }
    ],
    "frg702_gauges": [
        {
            "name": "FRG702_Chamber",
            "sensor_code": "T1",
            "units": "mbar",
            "enabled": true
        }
    ],
    "xgs600": {
        "enabled": true,
        "port": "COM4",
        "baudrate": 9600,
        "timeout": 1.0,
        "address": "00"
    },
    "power_supply": {
        "enabled": true,
        "interface": "Analog",
        "voltage_dac_pin": "DAC0",
        "current_dac_pin": "DAC1",
        "voltage_monitor_pin": "AIN4",
        "current_monitor_pin": "AIN5"
    },
    "logging": {
        "interval_ms": 1000,
        "file_prefix": "data_log",
        "auto_start": false
    }
}
```

---

## Sensor Naming Convention

Sensor names are used as dictionary keys throughout the codebase and as CSV column headers.

| Prefix | Type | Example |
|--------|------|---------|
| `TC_` | Thermocouple temperature (°C, K, or °F) | `TC_1`, `TC_2` |
| `TC_*_rawV` | Raw differential voltage at TC input | `TC_1_rawV` |
| `FRG702_` | FRG-702 vacuum pressure | `FRG702_Chamber` |
| `PS_Voltage` | Power supply output voltage (V) | `PS_Voltage` |
| `PS_Current` | Power supply output current (A) | `PS_Current` |
| `PS_Output_On` | Power supply output enable state (bool) | `PS_Output_On` |

---

## Key Constants

| Location | Constant | Value | Meaning |
|----------|----------|-------|---------|
| `live_plot.py` | `WINDOW_SECONDS` | `120` | Live-mode rolling window width (seconds) |
| `xgs600_controller.py` | `_MIN_COMMAND_INTERVAL` | `0.20` | Min delay between XGS-600 serial commands |
| `xgs600_controller.py` | `DEFAULT_TIMEOUT` | `1.0` | Serial read timeout (seconds) |
| `safety_monitor.py` | `TEMP_OVERRIDE_LIMIT` | `2200` | Hard temperature override limit (°C) |
| `data_acquisition.py` | `_PP_MAX_VOLTS` | `6.0` | Keysight rated max voltage |
| `data_acquisition.py` | `_PP_MAX_AMPS` | `180.0` | Keysight rated max current |
| `data_acquisition.py` | `_PP_DAC_MAX` | `5.0` | T8 DAC full-scale voltage |

---

## Registry Settings (`AppSettings`)

All stored under `HKEY_CURRENT_USER\Software\T8_DAQ_System`:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `tc_count` | int | 1 | Number of active thermocouples |
| `tc_type` | str | "C" | Default TC type (B/E/J/K/N/R/S/T/C) |
| `tc_types` | str | "" | Comma-separated per-TC types |
| `tc_pins` | str | "" | Comma-separated AIN pin assignments |
| `tc_unit` | str | "C" | Temperature display unit (C/K/F) |
| `frg_count` | int | 1 | Number of FRG-702 gauges |
| `p_unit` | str | "mbar" | Pressure display unit (mbar/Torr/Pa) |
| `sample_rate_ms` | int | 1000 | Acquisition interval (ms) |
| `display_rate_ms` | int | 1000 | GUI update interval (ms) |
| `use_absolute_scales` | bool | True | Fixed vs autoscale Y-axes |
| `frg_interface` | str | "XGS600" | FRG interface type ("XGS600" or "Analog") |
| `xgs600_port` | str | "COM4" | XGS-600 serial COM port |
| `ps_interface` | str | "Analog" | Power supply interface |
| `ps_voltage_monitor_pin` | str | "AIN4" | T8 AIN pin for voltage monitor |
| `ps_current_monitor_pin` | str | "AIN5" | T8 AIN pin for current monitor |

---

## Adding a New Sensor Type (Agent Instructions)

1. Add hardware reader class to `t8_daq_system/hardware/`
2. Instantiate in `MainWindow._initialize_hardware_readers()`
3. Pass to `DataAcquisition.__init__()` and add reads in `read_all_sensors()`
4. Add practice-mode simulation in `read_all_sensors()` under `if self.practice_mode:`
5. Add sensor to `DataBuffer` automatically (it is key-agnostic)
6. Create a `LivePlot` instance in `MainWindow._build_gui()` with appropriate `plot_type`
7. Add unit tests in `tests/test_<sensor>.py`

---

## Adding a New GUI Feature (Agent Instructions)

1. All GUI mutations must happen on the **main tkinter thread**
2. Data from the acquisition thread arrives via `on_new_data()` callback — store in `self._latest_*` attributes
3. `_update_gui()` is called periodically via `root.after(display_rate_ms, _update_gui)` — read `self._latest_*` there to update widgets
4. Never call `tkinter` methods from the acquisition background thread

---

## Common Code Patterns

### Reading sensor data from buffer in LivePlot
```python
ts, vals = self.data_buffer.get_sensor_data('TC_1')  # returns (list[datetime], list[float])
```

### Checking if acquisition is running
```python
if self.daq and self.daq.is_running():
    ...
# Or at the MainWindow level:
if self.is_running:
    ...
```

### Thread-safe GUI update from background
```python
# In acquisition callback (background thread) — just store data:
self._latest_readings = (timestamp, all_readings)

# In _update_gui() (main thread) — read and update widgets:
if self._latest_readings:
    ts, readings = self._latest_readings
    self.sensor_panel.update(readings)
```

### Clearing all plots and buffer
```python
self.data_buffer.clear()
for attr in ('plot_tc', 'plot_pressure', 'plot_ps'):
    if hasattr(self, attr):
        getattr(self, attr).clear()
```

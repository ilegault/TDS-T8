# LabJack T8 Data Acquisition System

A Python-based data acquisition system for the LabJack T8, designed for real-time thermocouple and pressure gauge monitoring with live visualization and CSV data logging.

## Features

- **Real-time Thermocouple Readings** - Support for Type B, E, J, K, N, R, S, T, and C thermocouples
- **FRG-702 Vacuum Gauge Support** - Logarithmic voltage-to-pressure conversion for Inficon FRG-702
- **Live Plotting** - Real-time matplotlib graphs with scrolling history
- **CSV Data Logging** - Timestamped data export for analysis
- **JSON Configuration** - Easy sensor setup without code changes
- **Expandable Architecture** - Add sensors by editing config file

---

## Hardware Requirements

| Component | Description                                |
|-----------|--------------------------------------------|
| **LabJack T8** | USB or Ethernet connected DAQ device       |
| **Thermocouples** | Type K, J, T, B, E, N, R, S, and C sensors |
| **FRG-702 Gauge** | Inficon FRG-702 Pirani/Cold Cathode Gauge  |
| **USB Cable** | For T8 connection (or Ethernet)            |

---

## Quick Start

### 1. Install LabJack LJM Driver

Download and install from: https://labjack.com/support/software/installers/ljm

### 2. Clone and Install

```bash
git clone <repository-url>
cd TDS-T8/t8_daq_system
pip install -r requirements.txt
```

### 3. Configure Sensors

Edit `config/sensor_config.json` to match your hardware setup.

### 4. Run the Application

```bash
python main.py
```

---

## User Interface

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LabJack T8 DAQ System                                           [—] [□] [×]│
├─────────────────────────────────────────────────────────────────────────────┤
│  [ Connect ]  [ Start ]  [ Stop ]  [ Start Logging ]     Status: Connected  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  TC1_Inlet  │  │ TC2_Outlet  │  │ P1_Chamber  │  │   P2_Tank   │        │
│  │             │  │             │  │             │  │             │        │
│  │   25.3 °C   │  │   28.1 °C   │  │  45.2 PSI   │  │  12.8 PSI   │        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Temperature / Pressure vs Time                                             │
│   ^                                                                         │
│   │      ╭──╮    ╭──╮                                                       │
│   │   ╭──╯  ╰────╯  ╰──╮      TC1_Inlet                                     │
│   │ ──╯                 ╰──── TC2_Outlet                                    │
│   │                           P1_Chamber                                    │
│   │ ────────────────────────  P2_Tank                                       │
│   └─────────────────────────────────────────────────────────────────────>   │
│     14:30:00   14:30:15   14:30:30   14:30:45   14:31:00                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

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
                    │    Compensation - No external  │
                    │    reference needed)           │
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

### FRG-702 Gauge Wiring (Single-Ended Input)

```
    ┌──────────────────┐           ┌────────────────────────────┐
    │    Inficon       │           │        LabJack T8          │
    │    FRG-702       │           │                            │
    │    Vacuum Gauge  │           │                            │
    │                  │           │                            │
    │  Signal ●────────┼───────────┼──────────► AIN4            │
    │                  │           │                            │
    │  Ground ●────────┼───────────┼──────────► GND             │
    │                  │           │                            │
    │  Status ●────────┼───────────┼──────────► AIN5 (Optional) │
    └──────────────────┘           └────────────────────────────┘

    Pressure Calculation (Logarithmic):
    P [mbar] = 10^(U - 5.5)
```

---

## Usage

1. Click **Connect** to establish connection with the T8
2. Click **Start** to begin reading sensors
3. Click **Start Logging** to save data to CSV files
4. Click **Stop** to pause data acquisition
5. Close the window to disconnect and exit

---

## Sensor Configuration

### Configuration File Location

```
t8_daq_system/config/sensor_config.json
```

### Adding New Sensors

#### Add a Thermocouple

Add to the `thermocouples` array in `sensor_config.json`:
```json
{
    "name": "TC3_NewLocation",
    "channel": 3,
    "type": "K",
    "units": "C",
    "enabled": true
}
```

#### Add an FRG-702 Gauge

Add to the `frg702_gauges` array in `sensor_config.json`:
```json
{
    "name": "FRG702_New",
    "channel": 6,
    "status_channel": 7,
    "units": "mbar",
    "enabled": true
}
```

### Thermocouple Configuration Details

```json
{
    "name": "TC1_Inlet",
    "channel": 0,
    "type": "K",
    "units": "C",
    "enabled": true
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `name` | string | Unique sensor identifier |
| `channel` | 0-3 | T8 analog input channel |
| `type` | B, E, J, K, N, R, S, T | Thermocouple type |
| `units` | K, C, F | Kelvin, Celsius, Fahrenheit |
| `enabled` | true/false | Enable/disable sensor |

### FRG-702 Gauge Configuration

```json
{
    "name": "FRG702_Chamber",
    "channel": 4,
    "status_channel": 5,
    "units": "mbar",
    "enabled": true
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `name` | string | Unique sensor identifier |
| `channel` | 0-7 | T8 analog input channel |
| `status_channel` | 0-7, null | Optional status voltage channel |
| `units` | mbar, torr, Pa | Pressure units (informational) |
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
        {"name": "TC1_Inlet", "channel": 0, "type": "K", "units": "C", "enabled": true},
        {"name": "TC2_Outlet", "channel": 1, "type": "K", "units": "C", "enabled": true}
    ],
    "frg702_gauges": [
        {"name": "FRG702_Chamber", "channel": 4, "status_channel": 5, "units": "mbar", "enabled": true}
    ],
    "logging": {
        "interval_ms": 1000,
        "file_prefix": "data_log",
        "auto_start": false
    },
    "display": {
        "update_rate_ms": 500,
        "history_seconds": 60
    }
}
```

---

## Troubleshooting

| Problem | Possible Cause | Solution |
|---------|----------------|----------|
| "Device not found" | LJM driver not installed | Install LJM from labjack.com |
| "Device not found" | T8 not connected | Check USB cable connection |
| "Device not found" | Wrong identifier | Set `"identifier": "ANY"` in config |
| Temperature shows `-9999` | Thermocouple disconnected | Check wiring at AIN+/AIN- terminals |
| Temperature shows `-9999` | Open circuit | Verify thermocouple continuity |
| Pressure reads 1000 mbar | Gauge not connected | Check signal cable at AIN channel |
| Pressure reads wrong | Gauge not on or warming | Check LED on FRG-702 gauge |
| No data logging | Permission denied | Check write permissions on logs/ folder |
| GUI not updating | Thread crashed | Check console for error messages |
| Import error | Missing packages | Run `pip install -r requirements.txt` |
| Plot not showing | Matplotlib backend | Try `pip install PyQt5` or `tkinter` |

---

## Running Unit Tests

The project has a comprehensive test suite (248 tests) that runs **without any hardware connected** and **without a display**. All hardware dependencies (LabJack LJM, PyVISA, PySerial, tkinter, matplotlib) are automatically mocked by `tests/conftest.py`.

### Quick Start

```bash
# From the project root (TDS-T8/):
pip install pytest
python -m pytest
```

That's it. Pytest will discover and run all tests in the `tests/` directory.

### Useful Commands

```bash
# Run all tests with verbose output
python -m pytest -v

# Run a specific test file
python -m pytest tests/test_safety_monitor.py

# Run a specific test class or method
python -m pytest tests/test_ramp_profile.py::TestRampStep::test_ramp_step_creation

# Run tests matching a keyword
python -m pytest -k "safety"

# Show print output from tests
python -m pytest -s

# Stop on first failure
python -m pytest -x
```

### Test Structure

| Test File | What It Tests |
|-----------|---------------|
| `test_data_buffer.py` | Circular data buffer operations |
| `test_data_logger.py` | CSV file logging |
| `test_data_logger_extended.py` | Extended CSV logging (metadata, multi-sensor) |
| `test_dialogs.py` | GUI dialog logic (filename sanitization, file discovery) |
| `test_frg702_reader.py` | FRG-702 vacuum gauge voltage-to-pressure conversion |
| `test_hardware.py` | LabJack connection and thermocouple batch reads |
| `test_helpers.py` | Utility functions (temperature conversion, formatting) |
| `test_integration.py` | MainWindow instantiation with all components mocked |
| `test_live_plot.py` | Real-time plot axes, colors, and data loading |
| `test_power_supply.py` | Keysight N5761A connection and SCPI commands |
| `test_ramp_executor.py` | Ramp profile execution engine |
| `test_ramp_profile.py` | Ramp step/profile definitions and validation |
| `test_safety_monitor.py` | Temperature limits, emergency shutdown, interlocks |

### How Mocking Works

The test suite can run on any machine (no hardware, no display) because `tests/conftest.py` automatically mocks:

- **`labjack.ljm`** -- LabJack hardware driver calls (`eWriteName`, `eReadName`, etc.)
- **`pyvisa`** -- VISA instrument communication (Keysight power supply)
- **`serial`** -- RS-232 communication (XGS-600 controller)
- **`tkinter`** -- GUI framework (no display needed)
- **`matplotlib`** -- Plotting library (no rendering needed)

Individual test files then configure the mock return values for their specific scenarios. For example, `test_turbo_pump_controller.py` sets `mock_ljm.eReadName.return_value = 0.0` to simulate a "pump at normal speed" DIO reading.

---

## Sensor Naming Convention

Sensors in this system follow a prefix convention:

| Prefix | Meaning | Example |
|--------|---------|---------|
| **TC** | Thermocouple (temperature) | `TC_1`, `TC2_Inlet` |
| **FRG702** | FRG-702 vacuum pressure gauge | `FRG702_Chamber` |
| **PS_** | Power Supply reading | `PS_Voltage`, `PS_Current` |

The **PS_** prefix (sometimes referred to as "P$" informally) denotes **Power Supply** readings. In the live plot and data logger, `PS_Voltage` and `PS_Current` track the Keysight N5761A power supply's measured output. They appear on a dedicated right-hand Y-axis in the plot with distinct colors (red for voltage, orange for current).

The **P-Unit** dropdown in the GUI config bar refers to **Pressure Units** (Torr, mbar, Pa) for the FRG-702 gauge -- it is unrelated to the PS_ power supply readings.

---

## Project Structure

```
TDS-T8/
├── README.md                      # Main documentation
├── pytest.ini                     # Pytest configuration
├── requirements.txt               # Python dependencies
├── tests/                         # Unit tests (248 tests)
│   ├── conftest.py                # Shared mocks (labjack, pyvisa, tkinter, etc.)
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
    │   ├── labjack_connection.py  # Connection manager
    │   ├── thermocouple_reader.py # TC reading logic
    │   ├── xgs600_controller.py   # XGS-600 vacuum controller
    │   ├── frg702_reader.py       # FRG-702 vacuum gauge logic
    │   ├── keysight_connection.py # Keysight power supply connection
    │   └── power_supply_controller.py # Power supply SCPI control
    ├── data/                      # Data handling
    │   ├── data_buffer.py         # In-memory circular buffer
    │   └── data_logger.py         # CSV file logging
    ├── control/                   # Control logic
    │   ├── ramp_profile.py        # Ramp step/profile definitions
    │   ├── ramp_executor.py       # Ramp profile execution
    │   └── safety_monitor.py      # Safety limits & emergency shutdown
    ├── gui/                       # User interface
    │   ├── main_window.py         # Main window & orchestration
    │   ├── live_plot.py           # Real-time matplotlib graphs
    │   ├── sensor_panel.py        # Numeric sensor displays
    │   ├── power_supply_panel.py  # Power supply status display
    │   ├── ramp_panel.py          # Ramp execution panel
    │   └── dialogs.py             # Modal dialogs
    ├── core/
    │   └── data_acquisition.py    # Main acquisition loop
    ├── utils/
    │   └── helpers.py             # Utility functions
    └── logs/                      # CSV output files
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

# LabJack T8 Data Acquisition System

A Python-based data acquisition system for the LabJack T8, designed for real-time thermocouple and pressure gauge monitoring with live visualization and CSV data logging.

## Features

- **Real-time Thermocouple Readings** - Support for Type B, E, J, K, N, R, S, T thermocouples
- **Pressure Transducer Support** - Configurable voltage-to-pressure scaling
- **Live Plotting** - Real-time matplotlib graphs with scrolling history
- **CSV Data Logging** - Timestamped data export for analysis
- **JSON Configuration** - Easy sensor setup without code changes
- **Expandable Architecture** - Add sensors by editing config file

---

## Hardware Requirements

| Component | Description |
|-----------|-------------|
| **LabJack T8** | USB or Ethernet connected DAQ device |
| **Thermocouples** | Type K, J, T, B, E, N, R, or S sensors |
| **Pressure Transducers** | 0-5V or 0-10V output sensors |
| **USB Cable** | For T8 connection (or Ethernet) |

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

### Pressure Transducer Wiring (Single-Ended Input)

```
    ┌──────────────────┐           ┌────────────────────────────┐
    │    Pressure      │           │        LabJack T8          │
    │   Transducer     │           │                            │
    │  (0.5-4.5V out)  │           │                            │
    │                  │           │                            │
    │  Signal ●────────┼───────────┼──────────► AIN2            │
    │                  │           │                            │
    │  Ground ●────────┼───────────┼──────────► GND             │
    │                  │           │                            │
    │  Power  ●────────┼───(+V Supply as required by sensor)    │
    └──────────────────┘           └────────────────────────────┘

    Voltage-to-Pressure Mapping:
    ┌───────────────┬───────────────┬───────────────┐
    │   Voltage     │   Pressure    │    Notes      │
    ├───────────────┼───────────────┼───────────────┤
    │   0.5V        │   0 PSI       │   min_voltage │
    │   2.5V        │   50 PSI      │   midpoint    │
    │   4.5V        │   100 PSI     │   max_voltage │
    └───────────────┴───────────────┴───────────────┘
```

---

## Sensor Configuration

### Configuration File Location

```
t8_daq_system/config/sensor_config.json
```

### Thermocouple Configuration

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

### Pressure Sensor Configuration

```json
{
    "name": "P1_Chamber",
    "channel": 2,
    "min_voltage": 0.5,
    "max_voltage": 4.5,
    "min_pressure": 0,
    "max_pressure": 100,
    "units": "PSI",
    "enabled": true
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `name` | string | Unique sensor identifier |
| `channel` | 0-7 | T8 analog input channel |
| `min_voltage` | float | Voltage at minimum pressure |
| `max_voltage` | float | Voltage at maximum pressure |
| `min_pressure` | float | Minimum pressure value |
| `max_pressure` | float | Maximum pressure value |
| `units` | PSI, BAR, KPA, ATM | Pressure units |
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
    "pressure_sensors": [
        {"name": "P1_Chamber", "channel": 2, "min_voltage": 0.5, "max_voltage": 4.5,
         "min_pressure": 0, "max_pressure": 100, "units": "PSI", "enabled": true}
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
| Pressure reads 0 | Transducer not powered | Verify power supply to sensor |
| Pressure reads wrong | Wrong scaling | Adjust min/max voltage and pressure |
| No data logging | Permission denied | Check write permissions on logs/ folder |
| GUI not updating | Thread crashed | Check console for error messages |
| Import error | Missing packages | Run `pip install -r requirements.txt` |
| Plot not showing | Matplotlib backend | Try `pip install PyQt5` or `tkinter` |

---

## Project Structure

```
TDS-T8/
├── README.md                      # This file
├── repo.md                        # AI/Developer reference
└── t8_daq_system/
    ├── main.py                    # Application entry point
    ├── requirements.txt           # Python dependencies
    ├── config/
    │   └── sensor_config.json     # Sensor definitions
    ├── hardware/                  # Device communication
    │   ├── labjack_connection.py  # Connection manager
    │   ├── thermocouple_reader.py # TC reading logic
    │   └── pressure_reader.py     # Pressure reading logic
    ├── data/                      # Data handling
    │   ├── data_buffer.py         # In-memory circular buffer
    │   └── data_logger.py         # CSV file logging
    ├── gui/                       # User interface
    │   ├── main_window.py         # Main window & orchestration
    │   ├── live_plot.py           # Real-time matplotlib graphs
    │   └── sensor_panel.py        # Numeric sensor displays
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

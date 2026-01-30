# LabJack T8 Data Acquisition System

A Python-based data acquisition system for the LabJack T8, designed for real-time thermocouple and pressure gauge monitoring with live visualization and CSV data logging. Now includes integrated control of Keysight N5761A DC Power Supply for specimen heating applications.

## Features

- **Real-time Thermocouple Readings** - Support for Type B, E, J, K, N, R, S, T thermocouples
- **Pressure Transducer Support** - Configurable voltage-to-pressure scaling
- **Live Plotting** - Real-time matplotlib graphs with scrolling history (dual Y-axis for voltage/current)
- **CSV Data Logging** - Timestamped data export for analysis
- **JSON Configuration** - Easy sensor setup without code changes
- **Expandable Architecture** - Add sensors by editing config file
- **Keysight N5761A Power Supply Control** - Integrated voltage/current control
- **Programmable Heating Ramps** - Define voltage profiles over time
- **Safety Interlocks** - Automatic shutoff based on temperature limits

---

## Hardware Requirements

| Component | Description |
|-----------|-------------|
| **LabJack T8** | USB or Ethernet connected DAQ device |
| **Thermocouples** | Type K, J, T, B, E, N, R, or S sensors |
| **Pressure Transducers** | 0-5V or 0-10V output sensors |
| **USB Cable** | For T8 connection (or Ethernet) |
| **Keysight N5761A** | DC Power Supply (USB, GPIB, or Ethernet) - Optional |
| **NI-VISA or pyvisa-py** | VISA backend for power supply communication |

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
┌─────────────────────────────────────────────────────────────────────────────────┐
│  T8 DAQ System with Power Supply Control                           [—] [□] [×] │
├─────────────────────────────────────────────────────────────────────────────────┤
│  [Quick Config: TCs: 2  Type: K  Press: 1  PSI: 100]                            │
│  [ Start ]  [ Stop ]  [ Start Logging ]   Status: Connected   [LJ] [PS] [TC1]...│
├───────────────────────────────────────────┬─────────────────────────────────────┤
│  Current Readings                         │  Power Supply Control               │
│  ┌─────────────┐  ┌─────────────┐        │  ┌─────────────────────────────────┐│
│  │    TC_1     │  │    TC_2     │        │  │ Status: ● Connected             ││
│  │   25.3 °C   │  │   28.1 °C   │        │  │ Voltage: 5.00 V  Current: 2.5 A ││
│  └─────────────┘  └─────────────┘        │  │ Setpoint: [___] V  [Set]        ││
│  ┌─────────────┐                         │  │ [OUTPUT ON]  [OUTPUT OFF]       ││
│  │     P_1     │                         │  └─────────────────────────────────┘│
│  │  45.2 PSI   │                         │                                     │
│  └─────────────┘                         │  Ramp Profile Control               │
│                                          │  ┌─────────────────────────────────┐│
│  Live Plot (Dual Y-Axis)                 │  │ Profile: [Slow Ramp ▼] [Load]   ││
│  ┌────────────────────────────────┐      │  │ Steps: 7  Duration: 26m 0s      ││
│  │ °C                           V │      │  │ Progress: ████████░░░░ 65%      ││
│  │ ^                           ^ │      │  │ Status: ● RUNNING  Step: 4/7    ││
│  │ │ ╭──╮                  ╱   │ │      │  │ [Start] [Pause] [Stop]          ││
│  │ │ │  ╰──╮            ╱──    │ │      │  └─────────────────────────────────┘│
│  │ └─┴─────────────────────────┴─┘      │                                     │
│  └────────────────────────────────┘      │                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│  Safety: [●] OK   Max Temp: 200C  │  PS Output: [●] ON  │  Ramp: [●] RUNNING   │
└─────────────────────────────────────────────────────────────────────────────────┘
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

### Power Supply Configuration

```json
{
    "enabled": true,
    "visa_resource": null,
    "default_voltage_limit": 20.0,
    "default_current_limit": 50.0,
    "safety": {
        "max_temperature": 200,
        "watchdog_sensor": "TC_1",
        "auto_shutoff": true,
        "warning_threshold": 0.9
    }
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `enabled` | true/false | Enable power supply integration |
| `visa_resource` | string/null | VISA resource string (null for auto-detect) |
| `default_voltage_limit` | float | Maximum voltage setpoint allowed |
| `default_current_limit` | float | Maximum current setpoint allowed |
| `safety.max_temperature` | float | Temperature limit for auto-shutoff |
| `safety.watchdog_sensor` | string | Primary sensor for safety monitoring |
| `safety.auto_shutoff` | true/false | Enable automatic emergency shutoff |
| `safety.warning_threshold` | 0.0-1.0 | Fraction of max temp for warning |

### Complete Configuration Example

```json
{
    "device": {
        "type": "T8",
        "connection": "USB",
        "identifier": "ANY"
    },
    "thermocouples": [
        {"name": "TC_1", "channel": 0, "type": "K", "units": "C", "enabled": true},
        {"name": "TC_2", "channel": 1, "type": "K", "units": "C", "enabled": true}
    ],
    "pressure_sensors": [
        {"name": "P_1", "channel": 8, "min_voltage": 0.5, "max_voltage": 4.5,
         "min_pressure": 0, "max_pressure": 100, "units": "PSI", "enabled": true}
    ],
    "power_supply": {
        "enabled": true,
        "visa_resource": null,
        "default_voltage_limit": 20.0,
        "default_current_limit": 50.0,
        "safety": {
            "max_temperature": 200,
            "watchdog_sensor": "TC_1",
            "auto_shutoff": true,
            "warning_threshold": 0.9
        }
    },
    "logging": {
        "interval_ms": 100,
        "file_prefix": "data_log",
        "auto_start": false
    },
    "display": {
        "update_rate_ms": 100,
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
| PS indicator stays gray | NI-VISA not installed | Install NI-VISA or use pyvisa-py backend |
| PS not detected | Wrong VISA resource | Set explicit resource string in config |
| PS not detected | Device powered off | Verify power supply is on and connected |
| Safety shutdown triggered | Temperature exceeded limit | Resolve cause, then click Reset Safety |
| Ramp not starting | PS output not enabled | Click OUTPUT ON before starting ramp |
| Ramp stopped unexpectedly | PS disconnected | Check USB/GPIB cable connection |

---

---

## Ramp Profiles

Ramp profiles define heating sequences as a series of voltage steps over time. Profiles are stored as JSON files in `config/profiles/`.

### Example Ramp Profile

```json
{
    "name": "Slow Ramp",
    "description": "Gentle heating profile for sensitive specimens",
    "start_voltage": 0.0,
    "current_limit": 10.0,
    "steps": [
        {"type": "ramp", "target_voltage": 5.0, "duration_sec": 120},
        {"type": "hold", "duration_sec": 180},
        {"type": "ramp", "target_voltage": 10.0, "duration_sec": 180},
        {"type": "hold", "duration_sec": 600},
        {"type": "ramp", "target_voltage": 0.0, "duration_sec": 180}
    ]
}
```

### Step Types

| Type | Description |
|------|-------------|
| `ramp` | Linear voltage transition to `target_voltage` over `duration_sec` |
| `hold` | Maintain current voltage for `duration_sec` |

### Included Example Profiles

| Profile | Description |
|---------|-------------|
| `slow_ramp.json` | Gentle heating for sensitive specimens (26 min) |
| `quick_cycle.json` | Fast thermal cycling for stress testing (7 min) |
| `hold_test.json` | Simple ramp and extended hold (33 min) |

---

## Safety System

The safety monitor provides automatic protection against overheating:

1. **Temperature Limits** - Each thermocouple can have a maximum temperature
2. **Warning Threshold** - Visual warning at 90% of limit (configurable)
3. **Auto Shutoff** - Immediately disables power supply output when limit exceeded
4. **Watchdog Sensor** - Primary sensor for safety monitoring
5. **Debouncing** - Configurable consecutive violations before shutdown

When a safety shutdown is triggered:
- Power supply output is immediately disabled
- Ramp execution is stopped
- Alert dialog is displayed
- Manual reset required to re-enable

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
    │   ├── sensor_config.json     # Sensor and PS configuration
    │   └── profiles/              # Ramp profile definitions
    │       ├── slow_ramp.json
    │       ├── quick_cycle.json
    │       └── hold_test.json
    ├── hardware/                  # Device communication
    │   ├── labjack_connection.py  # LabJack connection manager
    │   ├── thermocouple_reader.py # TC reading logic
    │   ├── pressure_reader.py     # Pressure reading logic
    │   ├── keysight_connection.py # Power supply VISA connection
    │   └── power_supply_controller.py # Power supply SCPI commands
    ├── control/                   # Control logic
    │   ├── ramp_profile.py        # Ramp profile data structure
    │   ├── ramp_executor.py       # Background ramp execution
    │   └── safety_monitor.py      # Temperature safety system
    ├── data/                      # Data handling
    │   ├── data_buffer.py         # In-memory circular buffer
    │   └── data_logger.py         # CSV file logging
    ├── gui/                       # User interface
    │   ├── main_window.py         # Main window & orchestration
    │   ├── live_plot.py           # Real-time dual-axis graphs
    │   ├── sensor_panel.py        # Numeric sensor displays
    │   ├── power_supply_panel.py  # Manual PS control panel
    │   └── ramp_panel.py          # Ramp profile control panel
    ├── utils/
    │   └── helpers.py             # Utility functions
    └── logs/                      # CSV output files
```

---

## Resources

### LabJack T8
- [LabJack LJM Library Download](https://labjack.com/support/software/installers/ljm)
- [LabJack LJM Python Library](https://github.com/labjack/labjack-ljm-python)
- [T8 Datasheet](https://support.labjack.com/docs/t-series-datasheet)
- [Thermocouple Application Note](https://support.labjack.com/docs/using-a-thermocouple-with-the-t8)

### Keysight N5761A Power Supply
- [N5761A Product Page](https://www.keysight.com/us/en/product/N5761A/dc-power-supply-6v-180a-1080w.html)
- [N5761A Programming Guide](https://www.keysight.com/us/en/assets/9018-01445/programming-guides/9018-01445.pdf)
- [PyVISA Documentation](https://pyvisa.readthedocs.io/)
- [NI-VISA Download](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html)

---

## License

See LICENSE file for details.

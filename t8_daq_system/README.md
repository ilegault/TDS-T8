# T8 DAQ System

A Python-based data acquisition system for the LabJack T8, designed for reading thermocouples and pressure gauges with live display and data logging.

## Features

- Real-time thermocouple temperature readings (Type K, J, T, etc.)
- Pressure transducer readings with configurable voltage-to-pressure scaling
- Live plotting with matplotlib
- CSV data logging with timestamps
- Easy sensor configuration via JSON file
- Expandable architecture for adding more sensors

## Requirements

### Software

1. Python 3.8 or higher
2. LabJack LJM Library - Download from: https://labjack.com/support/software/installers/ljm

### Python Packages

Install dependencies:
```bash
pip install -r requirements.txt
```

## Hardware Setup

### Thermocouples

Connect thermocouples to the T8's differential analog inputs:
- Positive lead to AIN+ (e.g., AIN0+)
- Negative lead to AIN- (e.g., AIN0-)

The T8's built-in cold junction compensation handles the reference temperature.

### Pressure Transducers

Connect pressure transducers (0.5-4.5V or similar output):
- Signal wire to AIN (e.g., AIN2)
- Ground to GND
- Power supply as required by transducer

## Configuration

Edit `config/sensor_config.json` to define your sensors:

### Thermocouple Example
```json
{
    "name": "TC1_Inlet",
    "channel": 0,
    "type": "K",
    "units": "C",
    "enabled": true
}
```

### Pressure Sensor Example
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

## Running the Application

```bash
cd t8_daq_system
python main.py
```

## Usage

1. Click **Connect** to establish connection with the T8
2. Click **Start** to begin reading sensors
3. Click **Start Logging** to save data to CSV files
4. Click **Stop** to pause data acquisition
5. Close the window to disconnect and exit

## File Structure

```
t8_daq_system/
├── main.py                    # Application entry point
├── requirements.txt           # Python dependencies
├── config/
│   └── sensor_config.json     # Sensor definitions
├── hardware/
│   ├── labjack_connection.py  # Device connection manager
│   ├── thermocouple_reader.py # Thermocouple reading
│   └── pressure_reader.py     # Pressure sensor reading
├── data/
│   ├── data_buffer.py         # In-memory data storage
│   └── data_logger.py         # CSV file logging
├── gui/
│   ├── main_window.py         # Main application window
│   ├── live_plot.py           # Real-time graphs
│   └── sensor_panel.py        # Numeric displays
├── utils/
│   └── helpers.py             # Utility functions
└── logs/                      # CSV log files (auto-created)
```

## Adding New Sensors

### Add a Thermocouple

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

### Add a Pressure Sensor

Add to the `pressure_sensors` array in `sensor_config.json`:
```json
{
    "name": "P2_Tank",
    "channel": 4,
    "min_voltage": 0.5,
    "max_voltage": 4.5,
    "min_pressure": 0,
    "max_pressure": 500,
    "units": "PSI",
    "enabled": true
}
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Device not found" | Check LJM driver is installed, T8 is connected |
| "-9999" temperature | Thermocouple open circuit or not connected |
| No data logging | Check logs/ folder exists and has write permissions |
| GUI not responding | Ensure background thread is running properly |

## Resources

- [LabJack LJM Python Library](https://github.com/labjack/labjack-ljm-python)
- [T8 Datasheet](https://support.labjack.com/docs/t-series-datasheet)
- [Thermocouple App Note](https://support.labjack.com/docs/using-a-thermocouple-with-the-t8)

# Repository Reference Guide

This document provides comprehensive technical documentation for AI assistants and developers working with the LabJack T8 DAQ system codebase.

---

## Directory Structure

```
TDS-T8/
├── README.md                           # Human-readable project documentation
├── repo.md                             # This file - AI/developer reference
│
└── t8_daq_system/                      # Main application package
    ├── main.py                         # Entry point - instantiates MainWindow and runs
    ├── requirements.txt                # Python package dependencies
    │
    ├── config/
    │   └── sensor_config.json          # Sensor definitions, logging, display settings
    │
    ├── hardware/                       # Device communication layer
    │   ├── __init__.py                 # Exports: LabJackConnection, ThermocoupleReader, PressureReader
    │   ├── labjack_connection.py       # USB/Ethernet connection management
    │   ├── thermocouple_reader.py      # TC reading via Extended Features (EF)
    │   └── pressure_reader.py          # Voltage reading and linear scaling
    │
    ├── data/                           # Data handling layer
    │   ├── __init__.py                 # Exports: DataBuffer, DataLogger
    │   ├── data_buffer.py              # Circular buffer using collections.deque
    │   └── data_logger.py              # CSV file writer with timestamps
    │
    ├── gui/                            # User interface layer
    │   ├── __init__.py                 # Exports: MainWindow, LivePlot, SensorPanel
    │   ├── main_window.py              # Tkinter main window, threading orchestration
    │   ├── live_plot.py                # Matplotlib FigureCanvasTkAgg integration
    │   └── sensor_panel.py             # Grid of sensor value displays
    │
    ├── utils/                          # Utility functions
    │   ├── __init__.py                 # Exports all helper functions
    │   └── helpers.py                  # Formatting, conversion, scaling utilities
    │
    └── logs/                           # Auto-created CSV output directory
        └── .gitkeep                    # Placeholder to preserve empty directory
```

---

## Module Descriptions & API Signatures

### hardware/labjack_connection.py

Manages connection lifecycle to the LabJack T8 device.

```python
class LabJackConnection:
    """
    Handles opening, closing, and monitoring T8 device connection.

    Attributes:
        handle: LJM device handle (int or None)
        device_info: Tuple from ljm.getHandleInfo()
        config: Dict loaded from sensor_config.json
    """

    def __init__(self, config_path: str | None = None) -> None
        """Load config and prepare for connection. Does not connect yet."""

    def connect(self) -> bool
        """Open connection to T8. Returns True on success."""

    def disconnect(self) -> None
        """Close connection and release handle."""

    def get_handle(self) -> int | None
        """Return LJM handle for use by reader classes."""

    def is_connected(self) -> bool
        """Check if device handle is valid."""

    def get_device_info(self) -> dict
        """Return device metadata: type, connection, serial, IP, port."""
```

### hardware/thermocouple_reader.py

Reads thermocouple temperatures using T8 Extended Features.

```python
class ThermocoupleReader:
    """
    Configures and reads thermocouples via T8 built-in EF registers.

    Class Attributes:
        TC_TYPES: Dict mapping type letters to AIN_EF_INDEX values
            {'B': 20, 'E': 21, 'J': 22, 'K': 23, 'N': 24, 'R': 25, 'S': 26, 'T': 27}

    Instance Attributes:
        handle: LJM device handle
        thermocouples: List of TC config dicts from JSON
    """

    def __init__(self, handle: int, tc_config_list: list[dict]) -> None
        """Initialize and configure all thermocouple channels."""

    def _configure_channels(self) -> None
        """Set voltage range (±75mV), EF index, and units for each TC."""

    def read_all(self) -> dict[str, float | None]
        """Read all enabled TCs. Returns {name: temp} or None for errors."""

    def read_single(self, channel_name: str) -> float | None
        """Read one TC by name. Returns temp or None."""

    def get_enabled_channels(self) -> list[str]
        """Return list of enabled TC names."""
```

### hardware/pressure_reader.py

Reads pressure transducers with voltage-to-pressure scaling.

```python
class PressureReader:
    """
    Reads analog voltage and converts to pressure using linear scaling.

    Attributes:
        handle: LJM device handle
        sensors: List of pressure sensor config dicts
    """

    def __init__(self, handle: int, pressure_config_list: list[dict]) -> None
        """Initialize and configure all pressure channels."""

    def _configure_channels(self) -> None
        """Set voltage range (±10V) for each pressure channel."""

    def _voltage_to_pressure(self, voltage: float, sensor_config: dict) -> float
        """Convert voltage to pressure using linear interpolation."""

    def read_all(self) -> dict[str, float | None]
        """Read all enabled pressure sensors. Returns {name: pressure}."""

    def read_single(self, channel_name: str) -> float | None
        """Read one pressure sensor by name."""

    def read_raw_voltage(self, channel_name: str) -> float | None
        """Read raw voltage for debugging."""

    def get_enabled_channels(self) -> list[str]
        """Return list of enabled pressure sensor names."""
```

### data/data_buffer.py

Circular buffer for live data visualization.

```python
class DataBuffer:
    """
    Stores recent sensor readings for plotting.
    Uses collections.deque with maxlen for automatic circular behavior.

    Attributes:
        max_samples: Calculated buffer size
        timestamps: deque of datetime objects
        data: dict of sensor_name -> deque of values
    """

    def __init__(self, max_seconds: int = 60, sample_rate_ms: int = 500) -> None
        """Initialize buffer with calculated capacity."""

    def add_reading(self, sensor_readings: dict[str, float]) -> None
        """Add timestamped readings. Auto-drops oldest when full."""

    def get_sensor_data(self, sensor_name: str) -> tuple[list, list]
        """Get (timestamps, values) lists for one sensor."""

    def get_all_current(self) -> dict[str, float]
        """Get most recent reading for each sensor."""

    def get_all_data(self) -> dict[str, tuple[list, list]]
        """Get all buffered data for all sensors."""

    def clear(self) -> None
        """Clear all buffered data."""

    def get_sensor_names(self) -> list[str]
        """Get list of sensor names in buffer."""

    def get_sample_count(self) -> int
        """Get current number of samples stored."""
```

### data/data_logger.py

CSV file logging with timestamps.

```python
class DataLogger:
    """
    Writes sensor readings to timestamped CSV files.

    Attributes:
        log_folder: Path to logs directory
        file_prefix: Prefix for log filenames
        file: Open file handle or None
        writer: csv.writer object
        sensor_names: Column order for CSV
        current_filepath: Path to active log file
    """

    def __init__(self, log_folder: str = "logs", file_prefix: str = "data_log") -> None
        """Initialize logger. Creates log_folder if missing."""

    def start_logging(self, sensor_names: list[str]) -> str
        """Create new CSV file with headers. Returns filepath."""

    def log_reading(self, sensor_readings: dict[str, float]) -> None
        """Write one row of data with timestamp."""

    def stop_logging(self) -> None
        """Close the current log file."""

    def is_logging(self) -> bool
        """Check if currently logging."""

    def get_current_filepath(self) -> str
        """Get path to current log file."""

    def get_log_files(self) -> list[str]
        """Get all log files sorted by modification time."""
```

### gui/main_window.py

Main application window and threading orchestration.

```python
class MainWindow:
    """
    Tkinter main window that coordinates all components.

    Attributes:
        root: tkinter.Tk root window
        config: Loaded sensor configuration dict
        connection: LabJackConnection instance
        tc_reader: ThermocoupleReader instance (after connect)
        pressure_reader: PressureReader instance (after connect)
        data_buffer: DataBuffer instance
        logger: DataLogger instance
        is_running: bool flag for acquisition loop
        is_logging: bool flag for CSV logging
        read_thread: Background Thread for sensor reading
        sensor_panel: SensorPanel widget
        live_plot: LivePlot widget
    """

    def __init__(self, config_path: str | None = None) -> None
        """Initialize window, load config, build GUI."""

    def _build_gui(self) -> None
        """Create buttons, labels, plots, panels."""

    def _on_connect(self) -> None
        """Handle Connect button - establish device connection."""

    def _on_start(self) -> None
        """Handle Start button - spawn read thread, start GUI updates."""

    def _on_stop(self) -> None
        """Handle Stop button - signal thread to stop."""

    def _on_toggle_logging(self) -> None
        """Handle logging button - start or stop CSV logging."""

    def _read_loop(self) -> None
        """Background thread: read sensors, buffer, log in loop."""

    def _update_gui(self) -> None
        """Periodic GUI update via tkinter.after()."""

    def _on_close(self) -> None
        """Handle window close - cleanup all resources."""

    def run(self) -> None
        """Start tkinter mainloop (blocking)."""
```

### gui/live_plot.py

Real-time matplotlib plotting embedded in tkinter.

```python
class LivePlot:
    """
    Matplotlib figure embedded in tkinter for live data visualization.

    Attributes:
        data_buffer: Reference to DataBuffer
        parent: tkinter Frame
        fig: matplotlib Figure
        ax: matplotlib Axes
        canvas: FigureCanvasTkAgg
        colors: List of line colors
    """

    def __init__(self, parent_frame: tk.Frame, data_buffer: DataBuffer) -> None
        """Create figure, canvas, embed in parent frame."""

    def update(self, sensor_names: list[str]) -> None
        """Refresh plot with current buffer data."""

    def clear(self) -> None
        """Clear the plot."""

    def set_y_label(self, label: str) -> None
        """Set Y-axis label."""

    def set_title(self, title: str) -> None
        """Set plot title."""
```

### gui/sensor_panel.py

Grid display of current sensor values.

```python
class SensorPanel:
    """
    Grid of LabelFrames showing current sensor readings.

    Attributes:
        parent: tkinter Frame
        displays: dict of sensor_name -> Label widget
        frames: dict of sensor_name -> LabelFrame widget
    """

    def __init__(self, parent_frame: tk.Frame, sensor_configs: list[dict]) -> None
        """Create grid of sensor displays from config list."""

    def update(self, readings: dict[str, float | None]) -> None
        """Update displayed values. Shows 'ERR' for None values."""

    def set_error(self, sensor_name: str, message: str = "ERR") -> None
        """Set a sensor to error state (red text)."""

    def clear_all(self) -> None
        """Reset all displays to default '--.-'."""

    def highlight(self, sensor_name: str, color: str = "green") -> None
        """Highlight a sensor display."""

    def get_sensor_names(self) -> list[str]
        """Get list of sensor names in panel."""
```

### utils/helpers.py

Utility functions for formatting and conversion.

```python
def format_timestamp(dt: datetime | None = None,
                    format_str: str = "%Y-%m-%d %H:%M:%S") -> str
    """Format datetime as string. Uses now() if dt is None."""

def format_timestamp_filename(dt: datetime | None = None) -> str
    """Format datetime for filenames: 'YYYYMMDD_HHMMSS'."""

def convert_temperature(value: float, from_unit: str, to_unit: str) -> float
    """Convert between 'C', 'F', 'K' temperature units."""

def convert_pressure(value: float, from_unit: str, to_unit: str) -> float
    """Convert between 'PSI', 'BAR', 'KPA', 'ATM' pressure units."""

def linear_scale(value: float, in_min: float, in_max: float,
                out_min: float, out_max: float) -> float
    """Scale value from input range to output range."""

def clamp(value: float, min_val: float, max_val: float) -> float
    """Clamp value to [min_val, max_val] range."""
```

---

## Configuration Schema

### sensor_config.json Structure

```json
{
    "device": {
        "type": "T8",                    // Device model (always "T8")
        "connection": "USB",              // "USB" or "ETHERNET"
        "identifier": "ANY"               // "ANY" or specific serial number
    },
    "thermocouples": [
        {
            "name": "string",            // Unique identifier
            "channel": 0,                 // 0-3 (T8 differential inputs)
            "type": "K",                  // B, E, J, K, N, R, S, T
            "units": "C",                 // K, C, F
            "enabled": true               // true/false
        }
    ],
    "pressure_sensors": [
        {
            "name": "string",            // Unique identifier
            "channel": 2,                 // 0-7 (T8 analog inputs)
            "min_voltage": 0.5,           // Voltage at min pressure
            "max_voltage": 4.5,           // Voltage at max pressure
            "min_pressure": 0,            // Min pressure value
            "max_pressure": 100,          // Max pressure value
            "units": "PSI",               // PSI, BAR, KPA, ATM
            "enabled": true               // true/false
        }
    ],
    "logging": {
        "interval_ms": 1000,             // Sample interval (ms)
        "file_prefix": "data_log",       // CSV filename prefix
        "auto_start": false              // Auto-start logging on launch
    },
    "display": {
        "update_rate_ms": 500,           // GUI refresh rate (ms)
        "history_seconds": 60            // Plot history duration
    }
}
```

---

## External Dependencies

### Python Packages (requirements.txt)

| Package | Version | Purpose |
|---------|---------|---------|
| `labjack-ljm` | >=1.23.0 | LabJack LJM Python wrapper |
| `matplotlib` | >=3.5.0 | Plotting and visualization |
| `numpy` | >=1.21.0 | Numerical operations |

### System Requirements

| Requirement | Notes |
|-------------|-------|
| Python | 3.8+ |
| tkinter | Usually bundled with Python |
| LabJack LJM Driver | Download from labjack.com |

---

## Architecture Notes

### Layer Separation

```
┌─────────────────────────────────────────────────────────────┐
│                        GUI Layer                             │
│   MainWindow  │  LivePlot  │  SensorPanel                   │
│   (tkinter)   │ (matplotlib)│  (tkinter)                    │
├─────────────────────────────────────────────────────────────┤
│                       Data Layer                             │
│           DataBuffer (deque)  │  DataLogger (CSV)           │
├─────────────────────────────────────────────────────────────┤
│                     Hardware Layer                           │
│  LabJackConnection │ ThermocoupleReader │ PressureReader    │
├─────────────────────────────────────────────────────────────┤
│                     LabJack LJM Library                      │
│                    (ljm.openS, ljm.eReadName, etc.)         │
└─────────────────────────────────────────────────────────────┘
```

### Threading Model

```
MAIN THREAD (GUI)
├── tkinter.mainloop() [BLOCKING]
│   └── _update_gui() scheduled via after() every 500ms
│       ├── Reads from DataBuffer (thread-safe via GIL)
│       ├── Updates SensorPanel widgets
│       └── Updates LivePlot
│
└── User events
    ├── _on_connect() → LabJackConnection.connect()
    ├── _on_start() → spawns BACKGROUND THREAD
    └── _on_stop() → sets is_running = False

BACKGROUND THREAD (Acquisition)
└── _read_loop()
    ├── while is_running:
    │   ├── ThermocoupleReader.read_all()
    │   ├── PressureReader.read_all()
    │   ├── DataBuffer.add_reading()
    │   ├── DataLogger.log_reading() if is_logging
    │   └── time.sleep(interval_ms / 1000)
    └── exits when is_running becomes False
```

### Data Flow

```
T8 Device
    │
    ▼ ljm.eReadName()
ThermocoupleReader / PressureReader
    │
    ▼ dict {name: value}
DataBuffer.add_reading()
    │
    ├──────────────────────────────┐
    ▼                              ▼
DataLogger.log_reading()     GUI Update Loop
    │                              │
    ▼                              ├─► SensorPanel.update()
CSV File                           └─► LivePlot.update()
```

---

## Testing Guide

### Recommended Test Directory Structure

```
t8_daq_system/
└── tests/
    ├── __init__.py
    ├── conftest.py                 # Shared fixtures
    ├── test_labjack_connection.py
    ├── test_thermocouple_reader.py
    ├── test_pressure_reader.py
    ├── test_data_buffer.py
    ├── test_data_logger.py
    ├── test_helpers.py
    ├── test_main_window.py         # Integration tests
    └── fixtures/
        └── test_sensor_config.json # Test configuration
```

### Example Pytest Fixtures (conftest.py)

```python
import pytest
from unittest.mock import Mock, MagicMock, patch
import tkinter as tk
import tempfile
import json
import os

# -----------------------------------------------------------------------------
# Mock LJM Library
# -----------------------------------------------------------------------------
@pytest.fixture
def mock_ljm():
    """Mock the labjack ljm library to avoid hardware dependency."""
    with patch('hardware.labjack_connection.ljm') as mock:
        # Mock successful connection
        mock.openS.return_value = 12345  # fake handle
        mock.getHandleInfo.return_value = (8, 1, 470000001, 0, 0, 1040)
        mock.close.return_value = None

        # Mock register reads
        mock.eReadName.return_value = 25.0  # default temperature/voltage
        mock.eWriteName.return_value = None

        yield mock


@pytest.fixture
def mock_ljm_thermocouple(mock_ljm):
    """Mock LJM with thermocouple-specific responses."""
    def read_side_effect(handle, name):
        if 'EF_READ_A' in name:
            return 25.5  # temperature in configured units
        return 0.0

    mock_ljm.eReadName.side_effect = read_side_effect
    return mock_ljm


@pytest.fixture
def mock_ljm_pressure(mock_ljm):
    """Mock LJM with pressure transducer responses."""
    def read_side_effect(handle, name):
        if name.startswith('AIN') and 'EF' not in name:
            return 2.5  # midpoint voltage
        return 0.0

    mock_ljm.eReadName.side_effect = read_side_effect
    return mock_ljm


@pytest.fixture
def mock_ljm_disconnected():
    """Mock LJM that simulates device not found."""
    with patch('hardware.labjack_connection.ljm') as mock:
        mock.openS.side_effect = Exception("Device not found")
        yield mock


@pytest.fixture
def mock_ljm_open_tc():
    """Mock LJM that returns open thermocouple value."""
    with patch('hardware.labjack_connection.ljm') as mock:
        mock.openS.return_value = 12345
        mock.eReadName.return_value = -9999.0  # open circuit
        yield mock


# -----------------------------------------------------------------------------
# Sample Configuration Fixtures
# -----------------------------------------------------------------------------
@pytest.fixture
def sample_tc_config():
    """Sample thermocouple configuration."""
    return [
        {"name": "TC1_Test", "channel": 0, "type": "K", "units": "C", "enabled": True},
        {"name": "TC2_Test", "channel": 1, "type": "J", "units": "F", "enabled": True},
        {"name": "TC3_Disabled", "channel": 2, "type": "T", "units": "C", "enabled": False},
    ]


@pytest.fixture
def sample_pressure_config():
    """Sample pressure sensor configuration."""
    return [
        {
            "name": "P1_Test",
            "channel": 2,
            "min_voltage": 0.5,
            "max_voltage": 4.5,
            "min_pressure": 0,
            "max_pressure": 100,
            "units": "PSI",
            "enabled": True
        },
        {
            "name": "P2_Test",
            "channel": 3,
            "min_voltage": 0.0,
            "max_voltage": 5.0,
            "min_pressure": 0,
            "max_pressure": 500,
            "units": "KPA",
            "enabled": True
        },
    ]


@pytest.fixture
def sample_full_config(sample_tc_config, sample_pressure_config):
    """Complete sensor configuration."""
    return {
        "device": {"type": "T8", "connection": "USB", "identifier": "ANY"},
        "thermocouples": sample_tc_config,
        "pressure_sensors": sample_pressure_config,
        "logging": {"interval_ms": 1000, "file_prefix": "test_log", "auto_start": False},
        "display": {"update_rate_ms": 500, "history_seconds": 60}
    }


@pytest.fixture
def config_file(sample_full_config, tmp_path):
    """Create a temporary config file."""
    config_path = tmp_path / "sensor_config.json"
    with open(config_path, 'w') as f:
        json.dump(sample_full_config, f)
    return str(config_path)


# -----------------------------------------------------------------------------
# Tkinter Root Fixture
# -----------------------------------------------------------------------------
@pytest.fixture
def tk_root():
    """Create a tkinter root window for GUI testing."""
    root = tk.Tk()
    root.withdraw()  # Hide the window
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass  # Window already destroyed


@pytest.fixture
def tk_frame(tk_root):
    """Create a tkinter frame for widget testing."""
    frame = tk.Frame(tk_root)
    frame.pack()
    return frame


# -----------------------------------------------------------------------------
# Data Fixtures
# -----------------------------------------------------------------------------
@pytest.fixture
def sample_readings():
    """Sample sensor readings dictionary."""
    return {
        "TC1_Test": 25.5,
        "TC2_Test": 78.3,
        "P1_Test": 45.2,
        "P2_Test": 250.0
    }


@pytest.fixture
def sample_readings_with_errors():
    """Sample readings with some None values (errors)."""
    return {
        "TC1_Test": 25.5,
        "TC2_Test": None,  # error/disconnected
        "P1_Test": 45.2,
        "P2_Test": None
    }


@pytest.fixture
def temp_log_dir(tmp_path):
    """Create a temporary logs directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return str(log_dir)
```

### Key Test Cases by Module

#### test_labjack_connection.py

```python
class TestLabJackConnection:
    """Tests for LabJackConnection class."""

    def test_connect_success(self, mock_ljm, config_file):
        """Test successful device connection."""
        # Verify connect() returns True
        # Verify ljm.openS called with correct params
        # Verify handle is stored

    def test_connect_failure(self, mock_ljm_disconnected, config_file):
        """Test connection when device not found."""
        # Verify connect() returns False
        # Verify is_connected() returns False

    def test_disconnect(self, mock_ljm, config_file):
        """Test disconnection cleans up handle."""
        # Connect first
        # Call disconnect()
        # Verify ljm.close called
        # Verify handle is None

    def test_get_device_info(self, mock_ljm, config_file):
        """Test device info retrieval."""
        # Verify returns dict with expected keys
```

#### test_thermocouple_reader.py

```python
class TestThermocoupleReader:
    """Tests for ThermocoupleReader class."""

    def test_configure_channels(self, mock_ljm, sample_tc_config):
        """Test channel configuration on init."""
        # Verify eWriteName called for each enabled TC
        # Verify correct EF_INDEX for each TC type
        # Verify disabled channels not configured

    def test_read_all_success(self, mock_ljm_thermocouple, sample_tc_config):
        """Test reading all thermocouples."""
        # Verify returns dict with correct sensor names
        # Verify values are floats

    def test_read_all_open_circuit(self, mock_ljm_open_tc, sample_tc_config):
        """Test handling of open circuit (-9999)."""
        # Verify returns None for open TCs

    def test_read_single(self, mock_ljm_thermocouple, sample_tc_config):
        """Test reading individual thermocouple."""
        # Verify correct value returned
        # Verify None for nonexistent name

    def test_get_enabled_channels(self, mock_ljm, sample_tc_config):
        """Test listing enabled channels."""
        # Verify only enabled TCs in list
        # Verify disabled TCs excluded

    def test_tc_type_mapping(self, mock_ljm, sample_tc_config):
        """Test TC type to EF_INDEX mapping."""
        # Verify K->23, J->22, T->27, etc.
```

#### test_pressure_reader.py

```python
class TestPressureReader:
    """Tests for PressureReader class."""

    def test_voltage_to_pressure_linear(self, mock_ljm, sample_pressure_config):
        """Test linear voltage-to-pressure conversion."""
        # Test min_voltage -> min_pressure
        # Test max_voltage -> max_pressure
        # Test midpoint voltage -> midpoint pressure

    def test_voltage_to_pressure_edge_cases(self, mock_ljm, sample_pressure_config):
        """Test edge cases in conversion."""
        # Test voltage below min_voltage
        # Test voltage above max_voltage

    def test_read_all(self, mock_ljm_pressure, sample_pressure_config):
        """Test reading all pressure sensors."""
        # Verify returns dict with correct names
        # Verify values are properly scaled

    def test_read_raw_voltage(self, mock_ljm_pressure, sample_pressure_config):
        """Test raw voltage reading."""
        # Verify returns unscaled voltage
```

#### test_data_buffer.py

```python
class TestDataBuffer:
    """Tests for DataBuffer class."""

    def test_add_reading(self, sample_readings):
        """Test adding readings to buffer."""
        # Verify readings stored
        # Verify timestamp added

    def test_circular_buffer_overflow(self, sample_readings):
        """Test buffer drops oldest when full."""
        # Fill buffer past capacity
        # Verify oldest samples dropped
        # Verify newest samples kept

    def test_get_sensor_data(self, sample_readings):
        """Test retrieving data for one sensor."""
        # Verify returns (timestamps, values) tuple
        # Verify lists are same length

    def test_get_all_current(self, sample_readings):
        """Test getting latest readings."""
        # Verify returns most recent value for each sensor

    def test_clear(self, sample_readings):
        """Test clearing buffer."""
        # Add readings
        # Clear
        # Verify buffer empty

    def test_max_samples_calculation(self):
        """Test buffer size calculation."""
        # 60 seconds at 500ms = 120 samples
        # Verify maxlen set correctly
```

#### test_data_logger.py

```python
class TestDataLogger:
    """Tests for DataLogger class."""

    def test_start_logging(self, temp_log_dir, sample_readings):
        """Test starting a new log file."""
        # Verify file created with correct name pattern
        # Verify header row written
        # Verify returns filepath

    def test_log_reading(self, temp_log_dir, sample_readings):
        """Test writing data rows."""
        # Start logging
        # Log multiple readings
        # Verify rows written with timestamps

    def test_stop_logging(self, temp_log_dir, sample_readings):
        """Test stopping logging."""
        # Start, log, stop
        # Verify file closed
        # Verify is_logging() returns False

    def test_creates_log_folder(self, tmp_path):
        """Test auto-creation of log folder."""
        # Use nonexistent folder path
        # Verify folder created

    def test_csv_format(self, temp_log_dir, sample_readings):
        """Test CSV file format."""
        # Log readings
        # Read file back
        # Verify header matches sensor names
        # Verify data parseable as CSV
```

#### test_helpers.py

```python
class TestHelpers:
    """Tests for utility functions."""

    def test_format_timestamp(self):
        """Test datetime formatting."""
        # Test with specific datetime
        # Test with None (uses now)
        # Test custom format string

    def test_format_timestamp_filename(self):
        """Test filename-safe timestamp."""
        # Verify no special characters
        # Verify format YYYYMMDD_HHMMSS

    def test_convert_temperature(self):
        """Test temperature unit conversion."""
        # C to F: 0°C = 32°F
        # C to K: 0°C = 273.15K
        # F to C: 32°F = 0°C
        # Round-trip conversions

    def test_convert_pressure(self):
        """Test pressure unit conversion."""
        # PSI to BAR
        # PSI to KPA
        # PSI to ATM
        # Round-trip conversions

    def test_linear_scale(self):
        """Test linear scaling."""
        # Test identity (0-100 -> 0-100)
        # Test inversion (0-100 -> 100-0)
        # Test offset ranges

    def test_clamp(self):
        """Test value clamping."""
        # Value below min -> min
        # Value above max -> max
        # Value in range -> unchanged
```

#### test_main_window.py (Integration)

```python
class TestMainWindowIntegration:
    """Integration tests for MainWindow."""

    def test_gui_builds(self, mock_ljm, config_file, tk_root):
        """Test GUI creates without errors."""
        # Verify no exceptions on init
        # Verify required widgets exist

    def test_connect_flow(self, mock_ljm, config_file, tk_root):
        """Test connection button flow."""
        # Simulate connect button
        # Verify readers initialized
        # Verify status updated

    def test_start_stop_flow(self, mock_ljm, config_file, tk_root):
        """Test start/stop acquisition flow."""
        # Connect, start, verify thread running
        # Stop, verify thread stopped

    def test_close_cleanup(self, mock_ljm, config_file, tk_root):
        """Test window close cleanup."""
        # Start acquisition
        # Trigger close
        # Verify all resources cleaned up
```

### What to Mock by Module

| Module | Mock Target | Reason |
|--------|-------------|--------|
| labjack_connection | `ljm` module | No hardware in CI |
| thermocouple_reader | `ljm.eReadName`, `ljm.eWriteName` | No hardware |
| pressure_reader | `ljm.eReadName`, `ljm.eWriteName` | No hardware |
| data_buffer | Nothing | Pure Python |
| data_logger | File system (use tmp_path) | Avoid file pollution |
| main_window | `ljm`, tkinter root | No hardware, headless CI |
| live_plot | `matplotlib.pyplot.show` | Headless CI |
| sensor_panel | tkinter root | Headless CI |
| helpers | Nothing | Pure Python |

### Edge Cases to Test

| Scenario | Expected Behavior |
|----------|-------------------|
| Device not connected | `connect()` returns False, methods return None |
| Thermocouple open circuit | `read_all()` returns None for that sensor |
| Voltage out of range | Linear scaling still works (extrapolates) |
| Empty config arrays | No crash, no sensors to read |
| Invalid TC type | Should raise or log error |
| Buffer overflow | Oldest samples dropped automatically |
| Log folder missing | Auto-created |
| CSV write error | Exception logged, doesn't crash |
| GUI update with None values | Shows "ERR" in red |
| Rapid start/stop | Thread properly synchronized |

---

## Development Notes

### Adding a New Sensor Type

1. Create reader class in `hardware/` following pattern of existing readers
2. Add configuration schema to `sensor_config.json`
3. Update `MainWindow._on_connect()` to initialize new reader
4. Update `MainWindow._read_loop()` to read new sensor
5. Add fixtures and tests in `tests/`

### Thread Safety

- Use simple boolean flags (`is_running`, `is_logging`) for control
- `deque` operations are atomic under GIL
- GUI updates only from main thread via `tkinter.after()`
- No explicit locks needed for current architecture

### Performance Considerations

- Default sample rate: 1000ms (adjustable in config)
- GUI update rate: 500ms (adjustable in config)
- Buffer holds 60 seconds of history by default
- CSV flush on every write for data integrity

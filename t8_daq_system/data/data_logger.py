"""
data_logger.py
PURPOSE: Save sensor data to CSV files for later analysis
Includes metadata header for settings, units, and notes.
"""

import csv
import os
import json
from datetime import datetime


class DataLogger:
    # Metadata prefix for comment lines in CSV
    METADATA_PREFIX = "#META:"

    def __init__(self, log_folder="logs", file_prefix="data_log"):
        """
        Initialize the data logger.

        Args:
            log_folder: Folder to save log files
            file_prefix: Prefix for log file names
        """
        self.log_folder = log_folder
        self.file_prefix = file_prefix
        self.file = None
        self.writer = None
        self.sensor_names = []
        self.current_filepath = None
        self.metadata = {}

        # Create logs folder if it doesn't exist
        os.makedirs(log_folder, exist_ok=True)

    def start_logging(self, sensor_names, custom_name=None, metadata=None):
        """
        Start a new log file.

        Args:
            sensor_names: list of sensor names for the header
            custom_name: Optional custom name for the file (instead of timestamp)
            metadata: Optional dict of metadata to store in file header

        Returns:
            Path to the created log file
        """
        # Close any existing file
        if self.file:
            self.stop_logging()

        # Create filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if custom_name:
            # Sanitize custom name (remove invalid characters)
            safe_name = "".join(c for c in custom_name if c.isalnum() or c in "._- ")
            safe_name = safe_name.strip().replace(" ", "_")
            filename = f"{self.file_prefix}_{safe_name}_{timestamp}.csv"
        else:
            filename = f"{self.file_prefix}_{timestamp}.csv"

        filepath = os.path.join(self.log_folder, filename)

        self.file = open(filepath, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.sensor_names = list(sensor_names)
        self.current_filepath = filepath
        self.metadata = metadata or {}

        # Add timestamp to metadata
        self.metadata['start_time'] = datetime.now().isoformat()
        self.metadata['sensors'] = self.sensor_names

        # Write metadata as comment lines
        self._write_metadata()

        # Write header row
        header = ['Timestamp'] + self.sensor_names
        self.writer.writerow(header)
        self.file.flush()

        print(f"Started logging to: {filepath}")
        return filepath

    def _write_metadata(self):
        """Write metadata as comment lines at the start of the file."""
        if not self.file or not self.metadata:
            return

        # Serialize any list/tuple values to comma-joined strings so the resulting JSON
        # never contains nested `[...]` arrays that can confuse downstream CSV parsers
        # when the metadata comment line is misread as a quoted CSV field.
        safe_meta = {}
        for k, v in self.metadata.items():
            if isinstance(v, (list, tuple)):
                safe_meta[k] = ', '.join(str(x) for x in v)
            else:
                safe_meta[k] = v
        metadata_json = json.dumps(safe_meta, separators=(',', ':'))
        self.file.write(f"{self.METADATA_PREFIX}{metadata_json}\n")
        self.file.flush()

    def log_reading(self, sensor_readings):
        """
        Write one row of data.

        Args:
            sensor_readings: dict like {'TC1': 25.3, 'P1': 45.2}
        """
        if self.writer is None:
            return

        timestamp = datetime.now().isoformat()
        row = [timestamp]
        for name in self.sensor_names:
            value = sensor_readings.get(name, '')
            # Use scientific notation for FRG-702 gauge values (very small floats)
            if name.startswith('FRG702_') and isinstance(value, float):
                row.append(f"{value:.2e}")
            elif name in ('PS_Voltage', 'PS_Voltage_Setpoint') and isinstance(value, float):
                row.append(f"{value:.4f}")
            elif name in ('PS_Current', 'PS_CC_Limit') and isinstance(value, float):
                row.append(f"{value:.3f}")
            else:
                row.append(value)
        self.writer.writerow(row)
        self.file.flush()  # Ensure data is written immediately

    def log_event(self, event_name, detail=""):
        """Write a named event row (e.g. RAMP_START, EMERGENCY_SHUTDOWN) with timestamp."""
        if self.writer is None:
            return
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        # Write as a special row: timestamp, EVENT:name, detail
        self.writer.writerow([timestamp, f"EVENT:{event_name}", detail])
        self.file.flush()

    def stop_logging(self):
        """Close the log file and update end time metadata."""
        if self.file:
            # We can't easily update the metadata at the start of the file,
            # so we'll add the end time as a comment at the end
            end_time = datetime.now().isoformat()
            self.file.write(f"#END_TIME:{end_time}\n")
            self.file.close()
            self.file = None
            self.writer = None
            print("Logging stopped")

    def is_logging(self):
        """Check if currently logging."""
        return self.file is not None

    def get_current_filepath(self):
        """Get the path of the current log file."""
        return self.current_filepath

    def get_log_files(self):
        """
        Get list of all log files in the log folder.

        Returns:
            List of log file paths sorted by modification time (newest first)
        """
        files = []
        if os.path.exists(self.log_folder):
            for f in os.listdir(self.log_folder):
                if f.endswith('.csv'):
                    filepath = os.path.join(self.log_folder, f)
                    files.append(filepath)

        # Sort by modification time, newest first
        files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return files

    @classmethod
    def load_csv_with_metadata(cls, filepath):
        """
        Load a CSV file and extract metadata and data.

        Args:
            filepath: Path to the CSV file

        Returns:
            Tuple of (metadata_dict, data_dict) where:
            - metadata_dict contains settings, units, etc.
            - data_dict contains 'timestamps' list and sensor data lists
        """
        metadata = {}
        data = {'timestamps': []}
        sensor_names = []
        end_time = None

        with open(filepath, 'r', newline='') as f:
            # First pass: read lines to find metadata (not using csv reader for comments)
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for metadata line (raw line, not CSV parsed)
            if line.startswith(cls.METADATA_PREFIX):
                try:
                    json_str = line[len(cls.METADATA_PREFIX):]
                    metadata = json.loads(json_str)
                    
                    # Restore list from comma-joined string if needed
                    if 'sensors' in metadata and isinstance(metadata['sensors'], str):
                        metadata['sensors'] = [s.strip() for s in metadata['sensors'].split(',')] if metadata['sensors'] else []
                    if 'tc_types' in metadata and isinstance(metadata['tc_types'], str):
                        metadata['tc_types'] = [s.strip() for s in metadata['tc_types'].split(',')] if metadata['tc_types'] else []
                        
                except json.JSONDecodeError:
                    pass
                continue

            # Check for end time comment
            if line.startswith('#END_TIME:'):
                end_time = line[len('#END_TIME:'):]
                continue

            # Skip other comments
            if line.startswith('#'):
                continue

            # Parse as CSV row
            row = next(csv.reader([line]))

            # Header row
            if row[0] == 'Timestamp':
                sensor_names = row[1:]
                for name in sensor_names:
                    data[name] = []
                continue

            # Data row
            try:
                timestamp = datetime.fromisoformat(row[0])
                data['timestamps'].append(timestamp)

                for i, name in enumerate(sensor_names):
                    if i + 1 < len(row) and row[i + 1]:
                        try:
                            value = float(row[i + 1])
                        except ValueError:
                            value = None
                    else:
                        value = None
                    data[name].append(value)
            except ValueError:
                continue

        if end_time:
            metadata['end_time'] = end_time

        return metadata, data

    @classmethod
    def get_csv_info(cls, filepath):
        """
        Get quick info about a CSV file without loading all data.

        Args:
            filepath: Path to the CSV file

        Returns:
            Dict with file info (name, start_time, sensor_count, row_count, etc.)
        """
        info = {
            'filepath': filepath,
            'filename': os.path.basename(filepath),
            'size_kb': os.path.getsize(filepath) / 1024,
            'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
        }

        row_count = 0
        with open(filepath, 'r', newline='') as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for metadata line (parse raw line, not CSV)
            if line.startswith(cls.METADATA_PREFIX):
                try:
                    json_str = line[len(cls.METADATA_PREFIX):]
                    metadata = json.loads(json_str)
                    info['metadata'] = metadata
                    info['start_time'] = metadata.get('start_time')
                    
                    # Restore list from comma-joined string if needed
                    sensors_meta = metadata.get('sensors', [])
                    if isinstance(sensors_meta, str):
                        info['sensors'] = [s.strip() for s in sensors_meta.split(',')] if sensors_meta else []
                    else:
                        info['sensors'] = sensors_meta

                    info['settings'] = {
                        'tc_count': metadata.get('tc_count'),
                        'tc_type': metadata.get('tc_type'),
                        'tc_unit': metadata.get('tc_unit'),
                        'frg702_count': metadata.get('frg702_count'),
                        'frg702_unit': metadata.get('frg702_unit'),
                        'sample_rate_ms': metadata.get('sample_rate_ms'),
                        'notes': metadata.get('notes')
                    }
                except json.JSONDecodeError:
                    pass
                continue

            # Check for end time comment
            if line.startswith('#END_TIME:'):
                info['end_time'] = line[len('#END_TIME:'):]
                continue

            # Skip other comments
            if line.startswith('#'):
                continue

            # Parse as CSV row
            row = next(csv.reader([line]))

            # Header row
            if row[0] == 'Timestamp':
                if 'sensors' not in info:
                    info['sensors'] = row[1:]
                continue

            # Count data rows
            row_count += 1

        info['row_count'] = row_count
        return info


def create_metadata_dict(tc_count=0, tc_type="K", tc_unit="C",
                         tc_types=None,
                         frg702_count=0, frg702_unit="mbar",
                         sample_rate_ms=100, notes=""):
    """
    Helper function to create a metadata dictionary for logging.

    Args:
        tc_count: Number of thermocouples
        tc_type: Thermocouple type for backward compatibility (first TC type or default)
        tc_unit: Temperature unit (C, F, K)
        tc_types: List of per-thermocouple types, e.g. ["C", "C", "K", "K"]
        frg702_count: Number of FRG-702 gauges
        frg702_unit: Pressure unit (mbar, torr, Pa)
        sample_rate_ms: Sampling rate in milliseconds
        notes: User notes about the run

    Returns:
        Dict with all metadata
    """
    result = {
        'tc_count': tc_count,
        'tc_type': tc_type,
        'tc_unit': tc_unit,
        'frg702_count': frg702_count,
        'frg702_unit': frg702_unit,
        'sample_rate_ms': sample_rate_ms,
        'notes': notes,
    }
    if tc_types is not None:
        result['tc_types'] = tc_types
    return result

"""
data_logger.py
PURPOSE: Save sensor data to CSV files for later analysis
"""

import csv
import os
from datetime import datetime


class DataLogger:
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

        # Create logs folder if it doesn't exist
        os.makedirs(log_folder, exist_ok=True)

    def start_logging(self, sensor_names):
        """
        Start a new log file.

        Args:
            sensor_names: list of sensor names for the header

        Returns:
            Path to the created log file
        """
        # Close any existing file
        if self.file:
            self.stop_logging()

        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.file_prefix}_{timestamp}.csv"
        filepath = os.path.join(self.log_folder, filename)

        self.file = open(filepath, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.sensor_names = list(sensor_names)
        self.current_filepath = filepath

        # Write header row
        header = ['Timestamp'] + self.sensor_names
        self.writer.writerow(header)
        self.file.flush()

        print(f"Started logging to: {filepath}")
        return filepath

    def log_reading(self, sensor_readings):
        """
        Write one row of data.

        Args:
            sensor_readings: dict like {'TC1': 25.3, 'P1': 45.2}
        """
        if self.writer is None:
            return

        timestamp = datetime.now().isoformat()
        row = [timestamp] + [sensor_readings.get(name, '') for name in self.sensor_names]
        self.writer.writerow(row)
        self.file.flush()  # Ensure data is written immediately

    def stop_logging(self):
        """Close the log file."""
        if self.file:
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

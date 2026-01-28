"""
data_buffer.py
PURPOSE: Store recent readings for live graphing
CONCEPT: Like a sliding window that only keeps the last N seconds of data
"""

from collections import deque
from datetime import datetime


class DataBuffer:
    def __init__(self, max_seconds=60, sample_rate_ms=500):
        """
        Initialize the data buffer.

        Args:
            max_seconds: How much history to keep
            sample_rate_ms: Expected time between samples
        """
        # Calculate how many samples to store
        max_samples = int((max_seconds * 1000) / sample_rate_ms)

        self.max_samples = max_samples
        self.timestamps = deque(maxlen=max_samples)
        self.data = {}  # sensor_name: deque of values

    def add_reading(self, sensor_readings):
        """
        Add a new set of readings to the buffer.

        Args:
            sensor_readings: dict like {'TC1': 25.3, 'P1': 45.2}
        """
        timestamp = datetime.now()
        self.timestamps.append(timestamp)

        for name, value in sensor_readings.items():
            if name not in self.data:
                # Create new deque for this sensor
                self.data[name] = deque(maxlen=self.max_samples)
            self.data[name].append(value)

    def get_sensor_data(self, sensor_name):
        """
        Get timestamps and values for one sensor.

        Args:
            sensor_name: Name of the sensor

        Returns:
            Tuple of (timestamps list, values list)
        """
        if sensor_name in self.data:
            return list(self.timestamps), list(self.data[sensor_name])
        return [], []

    def get_all_current(self):
        """
        Get the most recent reading for each sensor.

        Returns:
            dict like {'TC1': 25.3, 'P1': 45.2}
        """
        current = {}
        for name, values in self.data.items():
            if values:
                current[name] = values[-1]
        return current

    def get_all_data(self):
        """
        Get all buffered data for all sensors.

        Returns:
            dict with sensor names as keys and (timestamps, values) tuples as values
        """
        all_data = {}
        timestamps = list(self.timestamps)
        for name, values in self.data.items():
            all_data[name] = (timestamps, list(values))
        return all_data

    def clear(self):
        """Clear all buffered data."""
        self.timestamps.clear()
        self.data.clear()

    def get_sensor_names(self):
        """Get list of all sensor names in the buffer."""
        return list(self.data.keys())

    def get_sample_count(self):
        """Get current number of samples in the buffer."""
        return len(self.timestamps)

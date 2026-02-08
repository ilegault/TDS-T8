"""
data_buffer.py
PURPOSE: Store recent readings for live graphing
CONCEPT: Thread-safe ring buffer using deques with automatic old-data removal.
The acquisition thread writes data while the GUI thread reads it.
"""

import threading
from collections import deque
from datetime import datetime


class DataBuffer:
    def __init__(self, max_seconds=60, sample_rate_ms=100):
        """
        Initialize the data buffer.

        Args:
            max_seconds: How much history to keep (None for unlimited)
            sample_rate_ms: Expected time between samples
        """
        # Calculate how many samples to store
        if max_seconds is not None:
            max_samples = int((max_seconds * 1000) / sample_rate_ms)
        else:
            max_samples = None

        self.max_samples = max_samples
        self.sample_rate_ms = sample_rate_ms
        self.timestamps = deque(maxlen=max_samples)
        self.data = {}  # sensor_name: deque of values

        # Lock for thread-safe access from acquisition and GUI threads
        self._lock = threading.Lock()

    def add_reading(self, sensor_readings):
        """
        Add a new set of readings to the buffer. Thread-safe.

        Args:
            sensor_readings: dict like {'TC1': 25.3, 'P1': 45.2}
        """
        timestamp = datetime.now()

        with self._lock:
            self.timestamps.append(timestamp)

            for name, value in sensor_readings.items():
                if name not in self.data:
                    # Create new deque for this sensor
                    self.data[name] = deque(maxlen=self.max_samples)
                self.data[name].append(value)

    def get_sensor_data(self, sensor_name):
        """
        Get timestamps and values for one sensor. Thread-safe.

        Args:
            sensor_name: Name of the sensor

        Returns:
            Tuple of (timestamps list, values list)
        """
        with self._lock:
            if sensor_name in self.data:
                return list(self.timestamps), list(self.data[sensor_name])
            return [], []

    def get_all_current(self):
        """
        Get the most recent reading for each sensor. Thread-safe.

        Returns:
            dict like {'TC1': 25.3, 'P1': 45.2}
        """
        with self._lock:
            current = {}
            for name, values in self.data.items():
                if values:
                    current[name] = values[-1]
            return current

    def get_all_data(self):
        """
        Get all buffered data for all sensors. Thread-safe.

        Returns:
            dict with sensor names as keys and (timestamps, values) tuples as values
        """
        with self._lock:
            all_data = {}
            timestamps = list(self.timestamps)
            for name, values in self.data.items():
                all_data[name] = (timestamps, list(values))
            return all_data

    def clear(self):
        """Clear all buffered data. Thread-safe."""
        with self._lock:
            self.timestamps.clear()
            self.data.clear()

    def get_sensor_names(self):
        """Get list of all sensor names in the buffer. Thread-safe."""
        with self._lock:
            return list(self.data.keys())

    def get_sample_count(self):
        """Get current number of samples in the buffer. Thread-safe."""
        with self._lock:
            return len(self.timestamps)

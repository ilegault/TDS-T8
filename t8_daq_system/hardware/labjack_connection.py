"""
labjack_connection.py
PURPOSE: Connect to LabJack T8 and manage the connection
FLOW: Open device -> Return handle -> Close when done
"""

from labjack import ljm
import json
import os


class LabJackConnection:
    def __init__(self):
        """
        Initialize the LabJack connection manager.
        """
        self.handle = None
        self.device_info = None

    def connect(self):
        """
        Opens connection to T8.

        Returns:
            True if successful, False if failed
        """
        try:
            # Default to T8, USB, ANY identifier
            self.handle = ljm.openS("T8", "USB", "ANY")

            # Verify connection with a read
            ljm.eReadName(self.handle, "SERIAL_NUMBER")

            # Get device info to confirm connection
            self.device_info = ljm.getHandleInfo(self.handle)
            print(f"Connected to T8, Serial: {self.device_info[2]}")
            return True

        except ljm.LJMError:
            # Silently fail for background auto-connect
            if self.handle is not None:
                try:
                    ljm.close(self.handle)
                except:
                    pass
                self.handle = None
            return False

    def disconnect(self):
        """Always call this when done!"""
        if self.handle:
            ljm.close(self.handle)
            self.handle = None
            print("Disconnected from T8")

    def get_handle(self):
        """Other parts of code use this to talk to the device."""
        return self.handle

    def is_connected(self):
        """Check if device is currently connected and responsive by performing a small read."""
        if self.handle is None:
            return False
        
        try:
            # A real read is more reliable than getHandleInfo for detecting physical USB pull
            ljm.eReadName(self.handle, "SERIAL_NUMBER")
            return True
        except ljm.LJMError:
            # Connection lost or handle invalid
            self.handle = None
            return False

    def read_names_batch(self, names):
        """
        Read multiple named registers in a single LJM call.

        Args:
            names: List of register name strings, e.g. ["AIN0_EF_READ_A", "AIN1_EF_READ_A"]

        Returns:
            List of values in same order as names, or list of None on failure
        """
        if not self.handle or not names:
            return [None] * len(names)

        try:
            results = ljm.eReadNames(self.handle, len(names), names)
            return list(results)
        except ljm.LJMError as e:
            print(f"Batch read error: {e}")
            return [None] * len(names)

    def get_device_info(self):
        """
        Get information about the connected device.

        Returns:
            dict with device info or None if not connected
        """
        if self.device_info:
            return {
                'device_type': self.device_info[0],
                'connection_type': self.device_info[1],
                'serial_number': self.device_info[2],
                'ip_address': self.device_info[3],
                'port': self.device_info[4],
                'max_bytes_per_mb': self.device_info[5]
            }
        return None

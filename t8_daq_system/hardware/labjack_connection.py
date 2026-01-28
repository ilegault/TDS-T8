"""
labjack_connection.py
PURPOSE: Connect to LabJack T8 and manage the connection
FLOW: Open device -> Return handle -> Close when done
"""

from labjack import ljm
import json
import os


class LabJackConnection:
    def __init__(self, config_path=None):
        """
        Initialize the LabJack connection manager.

        Args:
            config_path: Path to sensor_config.json. If None, uses default location.
        """
        self.handle = None
        self.device_info = None

        # Find config file
        if config_path is None:
            # Look relative to this file's location
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, 'config', 'sensor_config.json')

        # Load config to know how to connect
        with open(config_path, 'r') as f:
            self.config = json.load(f)

    def connect(self):
        """
        Opens connection to T8.

        Returns:
            True if successful, False if failed
        """
        try:
            device_cfg = self.config['device']

            # ljm.openS() - the 'S' means we use Strings for parameters
            # Parameters: device type, connection type, identifier
            self.handle = ljm.openS(
                device_cfg['type'],       # "T8"
                device_cfg['connection'], # "USB" or "ETHERNET"
                device_cfg['identifier']  # "ANY" or specific serial
            )

            # Get device info to confirm connection
            self.device_info = ljm.getHandleInfo(self.handle)
            print(f"Connected to T8, Serial: {self.device_info[2]}")
            return True

        except ljm.LJMError as e:
            print(f"Failed to connect: {e}")
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
        """Check if device is currently connected."""
        return self.handle is not None

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

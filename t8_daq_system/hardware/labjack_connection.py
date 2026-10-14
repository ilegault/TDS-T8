"""
labjack_connection.py
PURPOSE: Connect to LabJack T8 and manage the connection
FLOW: Open device -> Return handle -> Close when done
"""

import logging

from labjack import ljm

logger = logging.getLogger(__name__)


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
            logger.info(f"Connected to T8, Serial: {self.device_info[2]}")
            return True

        except ljm.LJMError:
            # Silently fail for background auto-connect
            if self.handle is not None:
                try:
                    ljm.close(self.handle)
                except ljm.LJMError as e:
                    logger.exception(f"Error closing LabJack handle: {e}")
                self.handle = None
            return False

    def disconnect(self):
        """Always call this when done!"""
        if self.handle:
            ljm.close(self.handle)
            self.handle = None
            logger.info("Disconnected from T8")

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
            logger.exception(f"Batch read error: {e}")
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

    def configure_ain_single_ended(self, channels):
        """
        Forces specified AIN channels to single-ended mode.
        On T8, this means NEGATIVE_CH = channel number itself.
        Verifies the write succeeded.

        Args:
            channels: List of channel numbers, e.g. [4, 5]

        Returns:
            True if all writes succeeded, False otherwise
        """
        if not self.handle:
            logger.warning("Cannot configure AIN: Device not connected")
            return False

        success = True
        for ch in channels:
            reg = f"AIN{ch}_NEGATIVE_CH"
            # T8 specific: single-ended is channel number itself.
            # (On T7 it would be 199).
            val_to_write = ch 
            try:
                ljm.eWriteName(self.handle, reg, val_to_write)
                # Verify write
                val = ljm.eReadName(self.handle, reg)
                if int(val) != val_to_write:
                    logger.error(f"Verification failed for {reg}: wrote {val_to_write}, read {val}")
                    success = False
                else:
                    logger.info(f"Successfully configured {reg} to single-ended ({val_to_write})")
            except ljm.LJMError as e:
                logger.exception(f"Error configuring {reg}: {e}")
                success = False
        return success

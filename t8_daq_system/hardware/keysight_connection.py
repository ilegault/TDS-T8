"""
keysight_connection.py
PURPOSE: Connect to Keysight N5761A DC Power Supply via VISA and manage the connection
FLOW: Open VISA session -> Verify with *IDN? -> Return resource -> Close when done
"""

import socket
import threading

import pyvisa


class KeysightConnection:
    """
    Manages connection to Keysight N5761A DC Power Supply.

    Supports USB, GPIB, and Ethernet connections via VISA.
    Pattern mirrors LabJackConnection for consistency.
    """

    def __init__(self, resource_string=None):
        """
        Initialize the Keysight connection manager.

        Args:
            resource_string: VISA resource string (e.g., "USB0::0x0957::0x0F07::MY12345678::INSTR")
                           If None, will attempt auto-detection.
        """
        self.resource_string = resource_string
        self.resource_manager = None
        self.instrument = None
        self.device_info = None
        self._lock = threading.Lock()
        self._connected = False

    def connect(self):
        """
        Opens connection to Keysight N5761A.

        Returns:
            True if successful, False if failed
        """
        try:
            # Create resource manager with pyvisa-py backend to avoid NI-VISA scanning
            try:
                self.resource_manager = pyvisa.ResourceManager('@py')
            except Exception:
                self.resource_manager = pyvisa.ResourceManager()

            if self.resource_string:
                # Use specified resource string
                self.instrument = self.resource_manager.open_resource(
                    self.resource_string, open_timeout=2000
                )
            else:
                # Auto-detect: look for Keysight/Agilent power supplies
                self.instrument = self._auto_detect()
                if self.instrument is None:
                    return False

            # Configure communication settings
            self.instrument.timeout = 5000  # 5 second timeout for commands
            self.instrument.read_termination = '\n'
            self.instrument.write_termination = '\n'

            # Verify connection with identity query
            idn = self.instrument.query("*IDN?").strip()
            self._parse_idn(idn)

            print(f"Connected to {self.device_info['model']}, Serial: {self.device_info['serial_number']}")
            self._connected = True
            return True

        except (pyvisa.Error, Exception) as e:
            # Silently fail for background auto-connect
            self._cleanup()
            return False

    def _auto_detect(self):
        """
        Attempt to auto-detect a Keysight/Agilent power supply.

        A 1-second socket timeout is set for the duration of the scan to
        prevent any TCP probe from hanging the GUI thread when the network
        interface changes (e.g. ethernet cable swap).

        Returns:
            pyvisa.Resource or None if not found
        """
        # Issue 3b fix: clamp all socket probes to 1 second so a missing
        # network interface cannot stall the scan indefinitely.
        _prev_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(1.0)
        try:
            resources = self.resource_manager.list_resources()

            for resource in resources:
                try:
                    instr = self.resource_manager.open_resource(resource)
                    instr.timeout = 500  # 500ms is enough for USB/GPIB instruments
                    instr.read_termination = '\n'
                    instr.write_termination = '\n'

                    idn = instr.query("*IDN?").strip()

                    # Check if it's a Keysight/Agilent N5761A
                    if "N5761A" in idn or ("KEYSIGHT" in idn.upper() and "576" in idn):
                        self.resource_string = resource
                        return instr
                    elif "AGILENT" in idn.upper() and "576" in idn:
                        self.resource_string = resource
                        return instr

                    instr.close()
                except Exception:
                    continue

            return None
        except Exception:
            return None
        finally:
            # Always restore the previous default timeout
            socket.setdefaulttimeout(_prev_timeout)

    def _parse_idn(self, idn_string):
        """
        Parse the *IDN? response into device info.

        Expected format: Manufacturer,Model,Serial,Firmware
        Example: KEYSIGHT TECHNOLOGIES,N5761A,MY12345678,A.01.02
        """
        parts = idn_string.split(',')
        self.device_info = {
            'manufacturer': parts[0].strip() if len(parts) > 0 else 'Unknown',
            'model': parts[1].strip() if len(parts) > 1 else 'Unknown',
            'serial_number': parts[2].strip() if len(parts) > 2 else 'Unknown',
            'firmware': parts[3].strip() if len(parts) > 3 else 'Unknown',
            'idn_string': idn_string
        }

    def _cleanup(self):
        """Clean up resources on failure."""
        if self.instrument is not None:
            try:
                self.instrument.close()
            except:
                pass
            self.instrument = None
        self.device_info = None
        self._connected = False

    def disconnect(self):
        """Always call this when done!"""
        if self.instrument:
            try:
                # Ensure output is off before disconnecting (safety)
                self.instrument.write("OUTP OFF")
            except:
                pass

            try:
                self.instrument.close()
            except:
                pass

            self.instrument = None
            self._connected = False
            print("Disconnected from Keysight Power Supply")

    def get_instrument(self):
        """Other parts of code use this to talk to the device."""
        return self.instrument

    @property
    def visa_lock(self):
        """Lock that must be held for any VISA I/O on this connection's instrument."""
        return self._lock

    def is_connected(self):
        """Check if device is believed to be connected (lightweight, no VISA I/O)."""
        return self._connected and self.instrument is not None

    def mark_connected(self):
        """Called by the background monitor when it successfully communicates."""
        self._connected = True

    def mark_disconnected(self):
        """Called by the background monitor when it detects the instrument is unreachable."""
        self._connected = False

    def get_device_info(self):
        """
        Get information about the connected device.

        Returns:
            dict with device info or None if not connected
        """
        return self.device_info

    def get_resource_string(self):
        """
        Get the VISA resource string for the connected device.

        Returns:
            str or None if not connected
        """
        return self.resource_string

    def list_available_resources(self):
        """
        List all available VISA resources.

        Returns:
            tuple of resource strings
        """
        try:
            if self.resource_manager is None:
                try:
                    self.resource_manager = pyvisa.ResourceManager('@py')
                except Exception:
                    try:
                        self.resource_manager = pyvisa.ResourceManager()
                    except Exception:
                        return ()
            return self.resource_manager.list_resources()
        except Exception:
            return ()

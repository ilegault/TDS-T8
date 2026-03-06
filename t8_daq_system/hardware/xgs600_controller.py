"""
xgs600_controller.py
PURPOSE: Communicate with Agilent/Varian XGS-600 gauge controller via RS-232
KEY CONCEPT: Send text commands over serial, receive digital pressure readings directly.
Protocol: #{address}{command}{data}\r -> >{data}\r or ?FF for error
"""

import serial
import time

# XGS-600 manual: max 10 queries/second before responsiveness degrades.
# Enforce 200ms minimum between successive commands.
_MIN_COMMAND_INTERVAL = 0.20  # seconds

# Mirror the pressure debug flag from frg702_reader so both modules log together.
try:
    from t8_daq_system.hardware.frg702_reader import DEBUG_PRESSURE
except ImportError:
    DEBUG_PRESSURE = False


class XGS600Controller:
    """Serial communication interface for the XGS-600 gauge controller."""

    # Default serial settings per XGS-600 manual
    DEFAULT_BAUDRATE = 9600
    DEFAULT_TIMEOUT = 1.0
    DEFAULT_ADDRESS = "00"

    def __init__(self, port, baudrate=DEFAULT_BAUDRATE, timeout=DEFAULT_TIMEOUT,
                 address=DEFAULT_ADDRESS, debug=False):
        """
        Initialize XGS-600 controller connection parameters.

        Args:
            port: Serial port (e.g., 'COM4', '/dev/ttyUSB0')
            baudrate: Baud rate (9600)
            timeout: Read timeout in seconds
            address: Controller address ('00' for RS-232)
            debug: Enable verbose serial logging
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.address = address
        self.debug = debug
        self._serial = None
        self._connected = False
        self._last_command_time = 0.0

    def connect(self, silent=False):
        """
        Open serial port and verify connection to XGS-600.

        Args:
            silent: If True, suppress error messages on failure.

        Returns:
            True if connection successful, False otherwise
        """
        if self.debug:
            print(f"XGS-600: Attempting connection on {self.port} at {self.baudrate} baud...")

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=9600,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )

            if self.debug:
                print(f"XGS-600: Serial port {self.port} opened successfully.")

            # Flush any stale data
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()

            # Verify connection by requesting software version
            if self.debug:
                print("XGS-600: Sending software version query (#0005) for verification...")

            response = self.send_command("05")
            if response is None:
                if not silent:
                    print("XGS-600: No response to version query")
                self.disconnect()
                return False

            self._connected = True
            if not silent:
                print(f"XGS-600 connected on {self.port}, version: {response}")
            return True

        except serial.SerialException as e:
            if not silent:
                print(f"XGS-600 connection failed on {self.port}: {e}")
            if self._serial and self._serial.is_open:
                self._serial.close()
            self._serial = None
            self._connected = False
            return False

    def disconnect(self):
        """Close serial port."""
        if self._serial and self._serial.is_open:
            if self.debug:
                print(f"XGS-600: Closing serial port {self.port}.")
            try:
                self._serial.close()
            except serial.SerialException:
                pass
        self._serial = None
        self._connected = False

    def send_command(self, command):
        """
        Send a command to the XGS-600 and return the response.

        Args:
            command: Command string without address prefix or terminator
                     (e.g., '05' for version, '0F' for pressure dump)

        Returns:
            Response string (without '>' prefix and '\\r' terminator),
            None if ?FF (unsupported command — expected, not an error),
            or None on timeout/connection loss (sets _connected = False).
        """
        if not self._serial or not self._serial.is_open:
            if self.debug:
                print("XGS-600: Cannot send command - serial port not open.")
            self._connected = False
            return None

        # Enforce minimum interval between commands (max 10 queries/sec per manual)
        elapsed = time.monotonic() - self._last_command_time
        if elapsed < _MIN_COMMAND_INTERVAL:
            time.sleep(_MIN_COMMAND_INTERVAL - elapsed)

        # Build full command: #{address}{command}\r  (carriage return required)
        full_command = f"#{self.address}{command}\r"

        try:
            # Clear input buffer before sending
            self._serial.reset_input_buffer()

            if self.debug:
                print(f"XGS-600 TX: {repr(full_command)} (hex: {full_command.encode('ascii').hex()})")

            # Send command
            self._serial.write(full_command.encode('ascii'))
            self._last_command_time = time.monotonic()

            # Small delay to allow controller to process and begin responding
            time.sleep(0.05)

            # Read response until \r (waits up to self.timeout)
            response = self._serial.read_until(b'\r', size=256)

            if not response:
                print("XGS-600: serial timeout — no response received")
                # Timeout means the connection is lost — flag for reconnection
                self._connected = False
                return None

            if self.debug:
                print(f"XGS-600 RX: {repr(response)} (hex: {response.hex()})")

            if DEBUG_PRESSURE:
                print(f"[XGS600 SERIAL] Sent: {repr(full_command)}  Received: {repr(response)}")

            try:
                response_str = response.decode('ascii').strip('\r\n')
            except UnicodeDecodeError:
                if self.debug:
                    print(f"XGS-600: Failed to decode response as ASCII: {response}")
                return None

            # ?FF = command unsupported (e.g., ion gauge query with no ion boards).
            # This is expected behaviour — return None silently, do not log an error.
            if response_str.startswith('?FF'):
                return None

            # Other ? errors are unexpected; log them in debug mode.
            if response_str.startswith('?'):
                if self.debug:
                    print(f"XGS-600 error response: {response_str} for command: {command}")
                return None

            # Success — strip the leading '>' and return the data string
            if response_str.startswith('>'):
                return response_str[1:]

            return response_str

        except (serial.SerialException, serial.SerialTimeoutException) as e:
            print(f"XGS-600 serial error: {e}")
            self._connected = False
            return None

    def read_all_pressures(self):
        """
        Read all gauges using the pressure dump command (0F).

        This is the preferred polling method — one command returns every sensor,
        counting as a single query against the 10 queries/sec limit.

        Response format: >7.592E+02,NOCBL    ,7.592E+02,NOCBL
          Index 0 = T1, index 1 = T2, index 2 = T3, index 3 = T4
          NOCBL entries (no cable / sensor not installed) are returned as None.

        Returns:
            List of pressure floats or None per slot (None for NOCBL or errors),
            ordered left-to-right by board slot. Returns None if command fails.
        """
        if not self._serial or not self._serial.is_open:
            return None

        response = self.send_command("0F")
        if response is None:
            return None

        readings = response.split(',')
        readings = [r.strip() for r in readings]

        pressures = []
        for value_str in readings:
            # NOCBL means no cable / sensor not present — treat as None
            if not value_str or value_str == 'NOCBL':
                pressures.append(None)
            else:
                try:
                    pressures.append(float(value_str))
                except ValueError:
                    pressures.append(None)

        return pressures

    def read_pressure(self, sensor_code):
        """
        Read pressure from a single convection gauge by sensor code.

        Only convection gauge codes (T1–T4) are supported. Ion gauge codes
        (I1–I4) are rejected here because there are no ion gauge boards installed
        and querying them returns ?FF.

        Args:
            sensor_code: Sensor identifier — must be a convection gauge (e.g., 'T1', 'T3')

        Returns:
            Pressure as float (Torr), or None on error or unsupported sensor
        """
        if not self._serial or not self._serial.is_open:
            return None

        # Do not query ion gauge commands (codes 30–55) — no ion boards installed
        if sensor_code.upper().startswith('I'):
            if self.debug:
                print(f"XGS-600: Skipping ion gauge query for {sensor_code} — no ion boards installed")
            return None

        response = self.send_command(f"02{sensor_code}")
        if response is None:
            return None

        value_str = response.strip()
        if not value_str or value_str == 'NOCBL':
            return None

        try:
            return float(value_str)
        except ValueError:
            if self.debug:
                print(f"XGS-600: Could not parse pressure '{value_str}' for sensor {sensor_code}")
            return None

    def read_controller_info(self):
        """
        Read installed board configuration (#0001).

        Returns:
            Response string with board codes (e.g., '10' = HFIG, '40' = CNV,
            'FE' = empty), or None on error
        """
        return self.send_command("01")

    def read_software_version(self):
        """
        Read controller software version (#0005).

        Returns:
            Version string, or None on error
        """
        return self.send_command("05")

    def is_connected(self):
        """
        Return whether the controller is currently connected and responsive.

        Uses the cached connection state set by send_command() rather than
        sending a probe command, to avoid unnecessary serial traffic.

        Returns:
            True if the serial port is open and the last command succeeded.
        """
        if not self._serial or not self._serial.is_open:
            return False
        return self._connected

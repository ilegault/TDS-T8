"""
turbo_pump_controller.py
PURPOSE: Control the Leybold TURBOTRONIK NT 151/361 turbo pump via LabJack DIO.

HOW IT WORKS:
- Uses one DIO pin to drive a relay that connects/disconnects Pin 2 on the
  TURBOTRONIK terminal block (Mode 3: single external switch).
- Uses another DIO pin to read the NORMAL relay status from the TURBOTRONIK.
- DIO output HIGH = relay energized = pump START command
- DIO output LOW = relay de-energized = pump STOP command
- DIO input LOW = pump at NORMAL speed, HIGH = not normal (off/accel/fault)
"""

import time
from labjack import ljm


class TurboPumpController:
    """
    Controls the turbo pump via LabJack digital I/O.

    This class manages:
    - Sending START/STOP commands via a relay connected to a DIO output
    - Reading the NORMAL status relay via a DIO input
    - Enforcing minimum restart delay for safety
    """

    # Possible pump states
    STATE_OFF = "OFF"
    STATE_STARTING = "STARTING"
    STATE_NORMAL = "NORMAL"
    STATE_UNKNOWN = "UNKNOWN"

    def __init__(self, handle, config):
        """
        Initialize the turbo pump controller.

        Args:
            handle: LabJack LJM device handle (from LabJackConnection)
            config: Dict from sensor_config.json["turbo_pump"], containing:
                    - start_stop_channel: str like "DIO0"
                    - status_channel: str like "DIO1"
                    - start_delay_ms: int
                    - stop_delay_ms: int
                    - min_restart_delay_s: int
        """
        self.handle = handle
        self.config = config

        self.start_stop_channel = config.get('start_stop_channel', 'DIO0')
        self.status_channel = config.get('status_channel', 'DIO1')
        self.start_delay_ms = config.get('start_delay_ms', 500)
        self.stop_delay_ms = config.get('stop_delay_ms', 500)
        self.min_restart_delay_s = config.get('min_restart_delay_s', 30)

        self._is_commanded_on = False  # Tracks what WE told the relay to do
        self._last_stop_time = 0       # Timestamp of last stop command

        self._configure_channels()

    def _configure_channels(self):
        """
        Configure the LabJack DIO pins.
        - start_stop_channel as OUTPUT (initially LOW = pump off)
        - status_channel as INPUT with pull-up resistor
        """
        try:
            # Set start/stop pin as digital output, initially LOW (pump off)
            ljm.eWriteName(self.handle, self.start_stop_channel, 0)

            # Extract the DIO number from the channel name (e.g., "DIO1" -> 1)
            # Reading from a DIO pin automatically configures it as input on the T8.

        except ljm.LJMError as e:
            print(f"Error configuring turbo pump channels: {e}")
            raise

    def start(self):
        """
        Send START command to the turbo pump.

        Returns:
            tuple: (success: bool, message: str)

        Checks the minimum restart delay before allowing a start.
        Sets the DIO output HIGH to energize the relay.
        """
        # Check restart delay
        elapsed = time.time() - self._last_stop_time
        if self._last_stop_time > 0 and elapsed < self.min_restart_delay_s:
            remaining = int(self.min_restart_delay_s - elapsed)
            return (False, f"Must wait {remaining}s before restarting (safety delay)")

        try:
            # Set DIO HIGH -> relay energizes -> Pin 2 connects -> pump starts
            ljm.eWriteName(self.handle, self.start_stop_channel, 1)
            self._is_commanded_on = True

            # Brief delay for relay to settle
            time.sleep(self.start_delay_ms / 1000.0)

            return (True, "Start command sent")

        except ljm.LJMError as e:
            return (False, f"LabJack error on start: {e}")

    def stop(self):
        """
        Send STOP command to the turbo pump.

        Returns:
            tuple: (success: bool, message: str)

        Sets the DIO output LOW to de-energize the relay.
        Records the stop time for restart delay enforcement.
        """
        try:
            # Set DIO LOW -> relay de-energizes -> Pin 2 disconnects -> pump stops
            ljm.eWriteName(self.handle, self.start_stop_channel, 0)
            self._is_commanded_on = False
            self._last_stop_time = time.time()

            # Brief delay for relay to settle
            time.sleep(self.stop_delay_ms / 1000.0)

            return (True, "Stop command sent")

        except ljm.LJMError as e:
            return (False, f"LabJack error on stop: {e}")

    def read_status(self):
        """
        Read the NORMAL relay status from the TURBOTRONIK.

        Returns:
            str: One of STATE_OFF, STATE_STARTING, STATE_NORMAL, STATE_UNKNOWN

        Logic:
        - If we haven't commanded ON -> STATE_OFF
        - If DIO reads LOW (pins 5-6 closed) -> STATE_NORMAL
        - If DIO reads HIGH and we commanded ON -> STATE_STARTING (or fault)
        """
        try:
            raw_value = ljm.eReadName(self.handle, self.status_channel)
            is_normal = (raw_value < 0.5)  # LOW = NORMAL relay closed

            if not self._is_commanded_on:
                return self.STATE_OFF
            elif is_normal:
                return self.STATE_NORMAL
            else:
                return self.STATE_STARTING  # Could be accelerating or fault

        except ljm.LJMError as e:
            print(f"Error reading turbo pump status: {e}")
            return self.STATE_UNKNOWN

    def is_commanded_on(self):
        """Return True if we have sent a START command."""
        return self._is_commanded_on

    def get_status_dict(self):
        """
        Return a dict of current turbo pump state for logging/display.

        Returns:
            dict with keys: 'Turbo_Commanded', 'Turbo_Status'
        """
        status = self.read_status()
        return {
            'Turbo_Commanded': 'ON' if self._is_commanded_on else 'OFF',
            'Turbo_Status': status
        }

    def emergency_stop(self):
        """
        Immediately stop the pump. Bypasses all delays and checks.
        Called during safety shutdowns.
        """
        try:
            ljm.eWriteName(self.handle, self.start_stop_channel, 0)
        except ljm.LJMError:
            pass  # Best effort during emergency
        self._is_commanded_on = False
        self._last_stop_time = time.time()

    def cleanup(self):
        """Ensure pump relay is off when shutting down the application."""
        self.emergency_stop()

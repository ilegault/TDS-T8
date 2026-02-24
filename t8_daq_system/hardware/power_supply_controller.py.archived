"""
power_supply_controller.py
PURPOSE: Control the Keysight N5761A DC Power Supply output
FLOW: Set voltage/current -> Enable/disable output -> Read actual values
SAFETY: Always has methods to disable output on error or shutdown
"""


class PowerSupplyController:
    """
    Controls the Keysight N5761A DC Power Supply.

    Provides methods to set/get voltage and current, control output state,
    and check for errors. Designed with safety as a priority.
    """

    def __init__(self, instrument, voltage_limit=20.0, current_limit=50.0):
        """
        Initialize the power supply controller.

        Args:
            instrument: pyvisa.Resource object from KeysightConnection
            voltage_limit: Maximum allowed voltage setpoint (default 20V)
            current_limit: Maximum allowed current setpoint (default 50A)
        """
        self.instrument = instrument
        self.voltage_limit = voltage_limit
        self.current_limit = current_limit

        # Configure safety limits on initialization
        if self.instrument:
            self._configure_limits()

    def _configure_limits(self):
        """Configure the instrument's protection limits."""
        try:
            # Set voltage and current protection limits
            self.instrument.write(f"VOLT:PROT {self.voltage_limit}")
            self.instrument.write(f"CURR:PROT {self.current_limit}")
        except Exception:
            pass  # Don't fail on limit configuration

    def _validate_voltage(self, volts):
        """Validate voltage is within acceptable range."""
        if volts < 0:
            raise ValueError(f"Voltage cannot be negative: {volts}")
        if volts > self.voltage_limit:
            raise ValueError(f"Voltage {volts}V exceeds limit of {self.voltage_limit}V")
        return True

    def _validate_current(self, amps):
        """Validate current is within acceptable range."""
        if amps < 0:
            raise ValueError(f"Current cannot be negative: {amps}")
        if amps > self.current_limit:
            raise ValueError(f"Current {amps}A exceeds limit of {self.current_limit}A")
        return True

    def set_voltage(self, volts):
        """
        Set the output voltage setpoint.

        Args:
            volts: Target voltage in volts

        Returns:
            True if successful, False if failed

        Raises:
            ValueError: If voltage exceeds configured limit
        """
        self._validate_voltage(volts)

        try:
            self.instrument.write(f"VOLT {volts:.4f}")
            return True
        except Exception as e:
            print(f"Failed to set voltage: {e}")
            return False

    def set_current(self, amps):
        """
        Set the output current limit.

        Args:
            amps: Current limit in amperes

        Returns:
            True if successful, False if failed

        Raises:
            ValueError: If current exceeds configured limit
        """
        self._validate_current(amps)

        try:
            self.instrument.write(f"CURR {amps:.4f}")
            return True
        except Exception as e:
            print(f"Failed to set current: {e}")
            return False

    def get_voltage_setpoint(self):
        """
        Get the current voltage setpoint.

        Returns:
            float: Voltage setpoint in volts, or None on error
        """
        try:
            response = self.instrument.query("VOLT?")
            return float(response.strip())
        except Exception as e:
            print(f"Failed to read voltage setpoint: {e}")
            return None

    def get_current_setpoint(self):
        """
        Get the current current setpoint (limit).

        Returns:
            float: Current setpoint in amperes, or None on error
        """
        try:
            response = self.instrument.query("CURR?")
            return float(response.strip())
        except Exception as e:
            print(f"Failed to read current setpoint: {e}")
            return None

    def get_voltage(self):
        """
        Read the actual output voltage.

        Returns:
            float: Measured voltage in volts, or None on error
        """
        try:
            response = self.instrument.query("MEAS:VOLT?")
            return float(response.strip())
        except Exception as e:
            print(f"Failed to measure voltage: {e}")
            return None

    def get_current(self):
        """
        Read the actual output current.

        Returns:
            float: Measured current in amperes, or None on error
        """
        try:
            response = self.instrument.query("MEAS:CURR?")
            return float(response.strip())
        except Exception as e:
            print(f"Failed to measure current: {e}")
            return None

    def output_on(self):
        """
        Enable the power supply output.

        Returns:
            True if successful, False if failed
        """
        try:
            self.instrument.write("OUTP ON")
            return True
        except Exception as e:
            print(f"Failed to enable output: {e}")
            return False

    def output_off(self):
        """
        Disable the power supply output. CRITICAL SAFETY FUNCTION.

        This method should never fail silently - it attempts multiple times
        to ensure the output is disabled.

        Returns:
            True if successful, False if failed after retries
        """
        for attempt in range(3):
            try:
                self.instrument.write("OUTP OFF")
                # Verify output is actually off
                if not self.is_output_on():
                    return True
            except Exception as e:
                print(f"Output off attempt {attempt + 1} failed: {e}")

        print("CRITICAL: Failed to disable output after 3 attempts!")
        return False

    def is_output_on(self):
        """
        Check if the output is currently enabled.

        Returns:
            bool: True if output is on, False if off or on error
        """
        try:
            response = self.instrument.query("OUTP?").strip()
            # Response is "0" or "1" (or "ON"/"OFF" on some models)
            return response in ("1", "ON")
        except Exception as e:
            print(f"Failed to check output state: {e}")
            return False  # Assume off for safety

    def get_status(self):
        """
        Get comprehensive status of the power supply.

        Returns:
            dict: Status information including output state, readings, and errors
        """
        status = {
            'output_on': self.is_output_on(),
            'voltage_setpoint': self.get_voltage_setpoint(),
            'current_setpoint': self.get_current_setpoint(),
            'voltage_actual': self.get_voltage(),
            'current_actual': self.get_current(),
            'errors': self.get_errors(),
            'in_current_limit': self._is_in_current_limit()
        }
        return status

    def _is_in_current_limit(self):
        """
        Check if the power supply is currently in current limiting mode.

        Returns:
            bool: True if in current limit, False otherwise
        """
        try:
            # Query the status register or operation condition register
            response = self.instrument.query("STAT:OPER:COND?").strip()
            condition = int(response)
            # Bit 10 (1024) typically indicates current limiting
            return bool(condition & 1024)
        except Exception:
            return False

    def get_errors(self):
        """
        Read and clear any errors from the power supply.

        Returns:
            list: List of error strings, empty if no errors
        """
        errors = []
        try:
            # Read errors until "No error" is returned
            for _ in range(10):  # Max 10 errors to prevent infinite loop
                response = self.instrument.query("SYST:ERR?").strip()
                if response.startswith("0,") or "No error" in response:
                    break
                errors.append(response)
        except Exception as e:
            errors.append(f"Error reading error queue: {e}")

        return errors

    def reset(self):
        """
        Reset the power supply to default state.

        Returns:
            True if successful, False if failed
        """
        try:
            self.instrument.write("*RST")
            self.instrument.write("*CLS")  # Clear status registers
            return True
        except Exception as e:
            print(f"Failed to reset power supply: {e}")
            return False

    def emergency_shutdown(self):
        """
        EMERGENCY SHUTDOWN: Immediately disable output and reset.

        This is the primary safety function - called by safety monitor
        when temperature limits are exceeded.

        Returns:
            True if successful, False if failed
        """
        success = True

        # First priority: turn off output
        if not self.output_off():
            success = False

        # Second: set voltage to zero
        try:
            self.instrument.write("VOLT 0")
        except:
            success = False

        # Third: set current to minimum
        try:
            self.instrument.write("CURR 0")
        except:
            success = False

        if success:
            print("EMERGENCY SHUTDOWN: Power supply output disabled")
        else:
            print("EMERGENCY SHUTDOWN: Partial failure - verify output manually!")

        return success

    def set_voltage_limit(self, volts):
        """
        Update the software voltage limit.

        Args:
            volts: New maximum voltage limit
        """
        if volts > 0:
            self.voltage_limit = volts
            self._configure_limits()

    def set_current_limit(self, amps):
        """
        Update the software current limit.

        Args:
            amps: New maximum current limit
        """
        if amps > 0:
            self.current_limit = amps
            self._configure_limits()

    def get_readings(self):
        """
        Get current voltage and current readings in a format compatible
        with the data logging system.

        Returns:
            dict: {'PS_Voltage': float, 'PS_Current': float, 'PS_Output_On': bool}
        """
        return {
            'PS_Voltage': self.get_voltage(),
            'PS_Current': self.get_current(),
            'PS_Output_On': self.is_output_on()
        }

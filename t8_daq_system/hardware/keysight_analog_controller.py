"""
keysight_analog_controller.py
PURPOSE: Control the Keysight N5700 DC Power Supply via analog signals through the
         LabJack T8's DAC/AIN channels (J1 DB25 connector wired to T8 screw terminals).
FLOW: Scale target voltage/current to 0-10V DAC output -> Write to DAC0/DAC1
      Read AIN4/AIN5 monitor voltages -> Scale back to engineering units
WIRING:
    J1 Pin 9  -> DAC0         (Voltage Program, 0-10V = 0-rated_max_volts)
    J1 Pin 22 -> DAC GND      (Voltage Prog. Return)
    J1 Pin 10 -> DAC1         (Current Program, 0-10V = 0-rated_max_amps)
    J1 Pin 23 -> DAC GND      (Current Prog. Return)
    J1 Pin 11 -> AIN4         (Voltage Monitor, SW1 Switch 4 DOWN = 0–5V monitor range)
    J1 Pin 24 -> AIN5         (Current Monitor, SW1 Switch 4 DOWN = 0–5V monitor range)
    J1 Pin 12 -> GND          (Signal Common for monitors)
    J1 Pin 8  -> EIO0         (Local/Analog select - pull LOW for analog mode)
    J1 Pin 15 -> EIO1         (Shut Off - pull HIGH to kill output)
"""

from labjack import ljm


class KeysightAnalogController:
    """
    Controls the Keysight N5700-series DC Power Supply via analog I/O on the LabJack T8.

    Drop-in replacement for PowerSupplyController: exposes the same public API
    (set_voltage, set_current, get_voltage, get_current, output_on, output_off,
    get_readings, emergency_shutdown, etc.) but uses LJM DAC/AIN calls instead
    of SCPI strings over VISA.

    Scaling convention: the J1 connector accepts 0-10 V to represent 0-100% of the
    supply's rated output.  DAC0 and DAC1 on the T8 both output 0-10 V natively,
    so no external circuitry is needed.
    """

    # T8 register names for each signal
    _DAC_VOLTAGE = "DAC0"   # J1 Pin 9  – voltage program
    _DAC_CURRENT = "DAC1"   # J1 Pin 10 – current program
    _AIN_VOLTAGE = "AIN4"   # J1 Pin 11 – voltage monitor
    _AIN_CURRENT = "AIN5"   # J1 Pin 24 – current monitor
    _DIO_ANALOG_EN = "EIO0" # J1 Pin 8  – pull LOW to enable analog mode
    _DIO_SHUTOFF  = "EIO1"  # J1 Pin 15 – pull HIGH to kill output

    # LJM constant: 199 = single-ended (GND reference) for AIN negative channel
    _AIN_GND_REF = 199

    def __init__(self, handle, rated_max_volts=60.0, rated_max_amps=25.0,
                 voltage_limit=None, current_limit=None,
                 voltage_pin="DAC0", current_pin="DAC1",
                 voltage_monitor_pin="AIN4", current_monitor_pin="AIN5",
                 monitor_range_volts=5.0):
        """
        Initialize the analog power supply controller.

        Args:
            handle: LJM device handle from LabJackConnection.get_handle()
            rated_max_volts: Physical voltage rating of the supply (default 60 V for N5761A).
                             10 V on DAC0 programs this full-scale output.
            rated_max_amps:  Physical current rating of the supply (default 25 A for N5761A).
                             10 V on DAC1 programs this full-scale output.
            voltage_limit:   Maximum allowed voltage setpoint (software guard).
                             Defaults to rated_max_volts.
            current_limit:   Maximum allowed current setpoint (software guard).
                             Defaults to rated_max_amps.
            voltage_pin:     LJM register for voltage programming (e.g. "DAC0")
            current_pin:     LJM register for current programming (e.g. "DAC1")
            voltage_monitor_pin: LJM register for voltage monitoring (e.g. "AIN4")
            current_monitor_pin: LJM register for current monitoring (e.g. "AIN5")
            monitor_range_volts: Full-scale voltage of the analog monitor outputs.
                             SW1 Switch 4 DOWN = 0–5V monitor range (default 5.0 V).
        """
        self.handle = handle
        self.rated_max_volts = rated_max_volts
        self.rated_max_amps = rated_max_amps
        self.voltage_limit = voltage_limit if voltage_limit is not None else rated_max_volts
        self.current_limit = current_limit if current_limit is not None else rated_max_amps
        self.monitor_range_volts = monitor_range_volts
        
        # Override class defaults with instance-specific pins
        self._DAC_VOLTAGE = voltage_pin
        self._DAC_CURRENT = current_pin
        self._AIN_VOLTAGE = voltage_monitor_pin
        self._AIN_CURRENT = current_monitor_pin

        print(f"[DEBUG] KeysightAnalogController init: V_PIN={self._DAC_VOLTAGE}, I_PIN={self._DAC_CURRENT}, V_MON={self._AIN_VOLTAGE}, I_MON={self._AIN_CURRENT}")

        if self.handle is not None:
            print(f"[DEBUG] KeysightAnalogController: Handle is valid, configuring hardware...")
            self._configure_ain_channels()
            self._enable_analog_mode()
        else:
            print(f"[DEBUG] KeysightAnalogController: Handle is None, skipping hardware config")

    # ──────────────────────────────────────────────────────────────────────────
    # One-time hardware configuration
    # ──────────────────────────────────────────────────────────────────────────

    def _configure_ain_channels(self):
        """Configure AIN channels for single-ended (GND-referenced) mode."""
        try:
            print(f"[DEBUG] Keysight: Configuring {self._AIN_VOLTAGE} and {self._AIN_CURRENT} for single-ended mode")
            ljm.eWriteName(self.handle, f"{self._AIN_VOLTAGE}_NEGATIVE_CH", self._AIN_GND_REF)
            ljm.eWriteName(self.handle, f"{self._AIN_CURRENT}_NEGATIVE_CH", self._AIN_GND_REF)
        except Exception as e:
            print(f"[DEBUG] Keysight: Non-fatal error configuring AIN: {e}")
            pass  # Non-fatal; default config is usually single-ended anyway

    def _enable_analog_mode(self):
        """
        Pull the Local/Analog select pin LOW (EIO0 = 0) to put the supply in
        analog programming mode.  Must be called once at startup.
        """
        try:
            print(f"[DEBUG] Keysight: Pulling {self._DIO_ANALOG_EN} LOW to enable analog mode")
            ljm.eWriteName(self.handle, self._DIO_ANALOG_EN, 0)
        except Exception as e:
            print(f"[DEBUG] Keysight: Error enabling analog mode: {e}")
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # Validation helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _validate_voltage(self, volts):
        if volts < 0:
            raise ValueError(f"Voltage cannot be negative: {volts}")
        if volts > self.voltage_limit:
            raise ValueError(f"Voltage {volts} V exceeds limit of {self.voltage_limit} V")
        return True

    def _validate_current(self, amps):
        if amps < 0:
            raise ValueError(f"Current cannot be negative: {amps}")
        if amps > self.current_limit:
            raise ValueError(f"Current {amps} A exceeds limit of {self.current_limit} A")
        return True

    def _volts_to_dac(self, value, rated_max):
        """Scale an engineering value to the 0-10 V DAC range."""
        return (value / rated_max) * 10.0

    def _dac_to_volts(self, dac_v, rated_max):
        """Scale a DAC readback (0-10 V) back to engineering units."""
        return (dac_v / 10.0) * rated_max

    # ──────────────────────────────────────────────────────────────────────────
    # Setpoint commands (write to DAC)
    # ──────────────────────────────────────────────────────────────────────────

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
            dac_v = self._volts_to_dac(volts, self.rated_max_volts)
            ljm.eWriteName(self.handle, self._DAC_VOLTAGE, dac_v)
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
            dac_v = self._volts_to_dac(amps, self.rated_max_amps)
            ljm.eWriteName(self.handle, self._DAC_CURRENT, dac_v)
            return True
        except Exception as e:
            print(f"Failed to set current: {e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Setpoint readback (read DAC register)
    # ──────────────────────────────────────────────────────────────────────────

    def get_voltage_setpoint(self):
        """
        Read back the programmed voltage setpoint via the DAC0 register.

        Returns:
            float: Voltage setpoint in volts, or None on error
        """
        try:
            dac_v = ljm.eReadName(self.handle, self._DAC_VOLTAGE)
            return self._dac_to_volts(dac_v, self.rated_max_volts)
        except Exception as e:
            print(f"Failed to read voltage setpoint: {e}")
            return None

    def get_current_setpoint(self):
        """
        Read back the programmed current setpoint via the DAC1 register.

        Returns:
            float: Current setpoint in amperes, or None on error
        """
        try:
            dac_v = ljm.eReadName(self.handle, self._DAC_CURRENT)
            return self._dac_to_volts(dac_v, self.rated_max_amps)
        except Exception as e:
            print(f"Failed to read current setpoint: {e}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Monitor readings (read AIN)
    # ──────────────────────────────────────────────────────────────────────────

    def get_voltage(self):
        """
        Read the actual output voltage from the analog monitor (AIN4).

        The supply outputs 0–5V on Pin 11 proportional to 0–rated_max_volts.
        (SW1 Switch 4 DOWN = 0–5V monitor range.)

        Returns:
            float: Measured voltage in volts, or None on error
        """
        try:
            raw_v = ljm.eReadName(self.handle, self._AIN_VOLTAGE)
            return (raw_v / self.monitor_range_volts) * self.rated_max_volts
        except Exception as e:
            print(f"Failed to measure voltage on {self._AIN_VOLTAGE}: {e}")
            return None

    def get_current(self):
        """
        Read the actual output current from the analog monitor (AIN5).

        The supply outputs 0–5V on Pin 24 proportional to 0–rated_max_amps.
        (SW1 Switch 4 DOWN = 0–5V monitor range.)

        Returns:
            float: Measured current in amperes, or None on error
        """
        try:
            raw_v = ljm.eReadName(self.handle, self._AIN_CURRENT)
            return (raw_v / self.monitor_range_volts) * self.rated_max_amps
        except Exception as e:
            print(f"Failed to measure current on {self._AIN_CURRENT}: {e}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Output enable / disable
    # ──────────────────────────────────────────────────────────────────────────

    def output_on(self):
        """
        Enable the power supply output by de-asserting the Shut Off pin (EIO1 = 0).

        Returns:
            True if successful, False if failed
        """
        try:
            ljm.eWriteName(self.handle, self._DIO_SHUTOFF, 0)
            return True
        except Exception as e:
            print(f"Failed to enable output: {e}")
            return False

    def output_off(self):
        """
        Disable the power supply output.  CRITICAL SAFETY FUNCTION.

        Asserts the Shut Off pin (EIO1 = 1) and verifies it was accepted.
        Retries up to 3 times to ensure the output is disabled.

        Returns:
            True if successful, False if failed after retries
        """
        for attempt in range(3):
            try:
                ljm.eWriteName(self.handle, self._DIO_SHUTOFF, 1)
                if not self.is_output_on():
                    return True
            except Exception as e:
                print(f"Output off attempt {attempt + 1} failed: {e}")

        print("CRITICAL: Failed to disable output after 3 attempts!")
        return False

    def is_output_on(self):
        """
        Check whether the output is currently enabled.

        EIO1 = 0 → Shut Off de-asserted → output ON
        EIO1 = 1 → Shut Off asserted    → output OFF

        Returns:
            bool: True if output is on, False if off or on error
        """
        try:
            state = ljm.eReadName(self.handle, self._DIO_SHUTOFF)
            return int(state) == 0
        except Exception as e:
            print(f"Failed to check output state: {e}")
            return False  # Assume off for safety

    # ──────────────────────────────────────────────────────────────────────────
    # Status and diagnostics
    # ──────────────────────────────────────────────────────────────────────────

    def get_status(self):
        """
        Get a comprehensive status snapshot of the power supply.

        Returns:
            dict matching the PowerSupplyController.get_status() format
        """
        return {
            'output_on':        self.is_output_on(),
            'voltage_setpoint': self.get_voltage_setpoint(),
            'current_setpoint': self.get_current_setpoint(),
            'voltage_actual':   self.get_voltage(),
            'current_actual':   self.get_current(),
            'errors':           self.get_errors(),
            'in_current_limit': self._is_in_current_limit(),
        }

    def _is_in_current_limit(self):
        """
        Current-limit detection is not available on the analog interface.
        Returns False (no equivalent J1 signal is wired).
        """
        return False

    def get_errors(self):
        """
        No SCPI error queue on the analog interface.

        Returns:
            list: Always empty
        """
        return []

    def reset(self):
        """
        Soft-reset: zero both DAC outputs and de-assert the Shut Off pin.

        Returns:
            True if successful, False if failed
        """
        try:
            ljm.eWriteName(self.handle, self._DAC_VOLTAGE, 0.0)
            ljm.eWriteName(self.handle, self._DAC_CURRENT, 0.0)
            ljm.eWriteName(self.handle, self._DIO_SHUTOFF, 0)
            return True
        except Exception as e:
            print(f"Failed to reset power supply: {e}")
            return False

    def emergency_shutdown(self):
        """
        EMERGENCY SHUTDOWN: immediately disable output and zero all setpoints.

        Called by the safety monitor when temperature limits are exceeded.

        Returns:
            True if all steps succeeded, False if any step failed
        """
        success = True

        # 1. Assert Shut Off (highest priority)
        if not self.output_off():
            success = False

        # 2. Zero the voltage program DAC
        try:
            ljm.eWriteName(self.handle, self._DAC_VOLTAGE, 0.0)
        except Exception:
            success = False

        # 3. Zero the current program DAC
        try:
            ljm.eWriteName(self.handle, self._DAC_CURRENT, 0.0)
        except Exception:
            success = False

        if success:
            print("EMERGENCY SHUTDOWN: Power supply output disabled")
        else:
            print("EMERGENCY SHUTDOWN: Partial failure - verify output manually!")

        return success

    # ──────────────────────────────────────────────────────────────────────────
    # Limit management
    # ──────────────────────────────────────────────────────────────────────────

    def set_voltage_limit(self, volts):
        """
        Update the software voltage limit (does not affect the rated_max_volts scale).

        Args:
            volts: New maximum voltage limit
        """
        if volts > 0:
            self.voltage_limit = volts

    def set_current_limit(self, amps):
        """
        Update the software current limit (does not affect the rated_max_amps scale).

        Args:
            amps: New maximum current limit
        """
        if amps > 0:
            self.current_limit = amps

    # ──────────────────────────────────────────────────────────────────────────
    # Data acquisition interface
    # ──────────────────────────────────────────────────────────────────────────

    def get_readings(self):
        """
        Return current voltage, current, and output state in the format expected
        by the data logging and GUI systems.

        Returns:
            dict: {'PS_Voltage': float, 'PS_Current': float, 'PS_Output_On': bool}
        """
        return {
            'PS_Voltage':   self.get_voltage(),
            'PS_Current':   self.get_current(),
            'PS_Output_On': self.is_output_on(),
        }

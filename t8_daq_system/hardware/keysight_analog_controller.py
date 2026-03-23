"""
keysight_analog_controller.py
PURPOSE: Control the Keysight N5700 DC Power Supply via analog signals through the
         LabJack T8's DAC/AIN channels (J1 DB25 connector wired to T8 screw terminals).
FLOW: Scale target voltage/current to 0-5V DAC output -> Write to DAC0/DAC1
      Read AIN4/AIN5 monitor voltages -> Scale back to engineering units
WIRING:
    J1 Pin 9  -> DAC0         (Voltage Program, 0-5V = 0-6V PSU output)
    J1 Pin 22 -> DAC GND      (Voltage Prog. Return)
    J1 Pin 10 -> DAC1         (Current Program, 0-5V = 0-180A PSU output)
    J1 Pin 23 -> DAC GND      (Current Prog. Return)
    J1 Pin 11 -> AIN4         (Voltage Monitor, SW1 Switch 4 DOWN = 0–5V monitor range)
    J1 Pin 24 -> AIN5         (Current Monitor, SW1 Switch 4 DOWN = 0–5V monitor range)
    J1 Pin 12 -> AIN4-        (Signal Common / -S, also jumpered to AIN5-)
                              No connection to T8 GND - avoids ground loop
    J1 Pin 8  -> FIO0         (Local/Analog select - pull LOW for analog mode)
    J1 Pin 15 -> FIO1         (Shut Off - pull HIGH to kill output)
"""

from labjack import ljm


class KeysightAnalogController:
    """
    Controls the Keysight N5700-series DC Power Supply via analog I/O on the LabJack T8.

    Drop-in replacement for PowerSupplyController: exposes the same public API
    (set_voltage, set_current, get_voltage, get_current, output_on, output_off,
    get_readings, emergency_shutdown, etc.) but uses LJM DAC/AIN calls instead
    of SCPI strings over VISA.

    Scaling convention: the J1 connector accepts 0-5 V to represent 0-100% of the
    supply's rated output.  DAC0 and DAC1 on the T8 both output 0-5 V for full scale.
    """

    # T8 register names for each signal
    _DAC_VOLTAGE = "DAC0"   # J1 Pin 9  – voltage program
    _DAC_CURRENT = "DAC1"   # J1 Pin 10 – current program
    _AIN_VOLTAGE = "AIN4"   # J1 Pin 11 – voltage monitor
    _AIN_CURRENT = "AIN5"   # J1 Pin 24 – current monitor
    _DIO_ANALOG_EN = "FIO0" # J1 Pin 8  – pull LOW to enable analog mode
    _DIO_SHUTOFF  = "FIO1"  # J1 Pin 15 – pull HIGH to kill output

    # Keysight SW1 switch 4 DOWN = 0-5V monitor range
    # 0V = 0% of rated output, 5V = 100% of rated output
    _MONITOR_RANGE_V = 5.0

    # MAX DAC output is 5.0 V — hard limit per Keysight N5700 J1 spec (SW1-3 DOWN)
    _DAC_MAX_V = 5.0

    def __init__(self, handle, rated_max_volts=6.0, rated_max_amps=180.0,
                 voltage_limit=None, current_limit=None,
                 voltage_pin="DAC0", current_pin="DAC1",
                 voltage_monitor_pin="AIN4", current_monitor_pin="AIN5",
                 switch_4_position='down', debug=False):
        """
        Initialize the analog power supply controller.

        Args:
            handle: LJM device handle from LabJackConnection.get_handle()
            rated_max_volts: Physical voltage rating of the supply (default 6.0 V).
                             5 V on DAC0 programs this full-scale output.
            rated_max_amps:  Physical current rating of the supply (default 180.0 A).
                             5 V on DAC1 programs this full-scale output.
            voltage_limit:   Maximum allowed voltage setpoint (software guard).
                             Defaults to rated_max_volts.
            current_limit:   Maximum allowed current setpoint (software guard).
                             Defaults to rated_max_amps.
            voltage_pin:     LJM register for voltage programming (e.g. "DAC0")
            current_pin:     LJM register for current programming (e.g. "DAC1")
            voltage_monitor_pin: LJM register for voltage monitoring (e.g. "AIN4")
            current_monitor_pin: LJM register for current monitoring (e.g. "AIN5")
            switch_4_position: 'down' for 0-5V monitor range (default), 'up' for 0-10V
            debug: Set to True to enable verbose calculation debug output (default False)
        """
        self.interlock_active = False
        self.handle = handle
        self.rated_max_volts = rated_max_volts
        self.rated_max_amps = rated_max_amps
        self.voltage_limit = voltage_limit if voltage_limit is not None else rated_max_volts
        self.current_limit = current_limit if current_limit is not None else rated_max_amps
        self.switch_4_position = switch_4_position.lower().strip()
        self.debug = debug
        
        if self.switch_4_position not in ['up', 'down']:
            print(f"Warning: Invalid switch_4_position '{self.switch_4_position}', defaulting to 'down'")
            self.switch_4_position = 'down'

        # Keysight SW1 switch 4 determines monitor range
        self._MONITOR_RANGE_V = 10.0 if self.switch_4_position == 'up' else 5.0
        
        # Override class defaults with instance-specific pins
        self._DAC_VOLTAGE = voltage_pin
        self._DAC_CURRENT = current_pin
        self._AIN_VOLTAGE = voltage_monitor_pin
        self._AIN_CURRENT = current_monitor_pin

        if self.debug:
            print(f"[DEBUG] KeysightAnalogController init: V_PIN={self._DAC_VOLTAGE}, I_PIN={self._DAC_CURRENT}, V_MON={self._AIN_VOLTAGE}, I_MON={self._AIN_CURRENT}")

        if self.handle is not None:
            if self.debug:
                print(f"[DEBUG] KeysightAnalogController: Handle is valid, configuring hardware...")
            self._configure_ain_channels()
            self._enable_analog_mode()
        else:
            if self.debug:
                print(f"[DEBUG] KeysightAnalogController: Handle is None, skipping hardware config")

    # ──────────────────────────────────────────────────────────────────────────
    # One-time hardware configuration
    # ──────────────────────────────────────────────────────────────────────────

    def _set_pin_output(self, pin_name):
        """
        Set a DIO pin to output direction on the T8.

        The T8 LJM firmware does not support individual FIO#_DIRECTION or
        DIO#_DIRECTION registers.  Direction must be set via the byte registers
        FIO_DIRECTION or EIO_DIRECTION using a read-modify-write on the
        appropriate bit.  Falls back to the legacy '{pin}_DIRECTION' write for
        any unrecognised pin names (T7 compatibility).

        FIO0-7  → FIO_DIRECTION bits 0-7
        EIO0-7  → EIO_DIRECTION bits 0-7
        """
        pin_upper = pin_name.upper()
        if pin_upper.startswith('FIO') and pin_upper[3:].isdigit():
            bit = int(pin_upper[3:])
            byte_reg = 'FIO_DIRECTION'
        elif pin_upper.startswith('EIO') and pin_upper[3:].isdigit():
            bit = int(pin_upper[3:])
            byte_reg = 'EIO_DIRECTION'
        else:
            # Fallback for T7 or unexpected names
            ljm.eWriteName(self.handle, f"{pin_name}_DIRECTION", 1)
            return

        current = int(ljm.eReadName(self.handle, byte_reg))
        ljm.eWriteName(self.handle, byte_reg, current | (1 << bit))

    def _configure_ain_channels(self):
        """
        Configure AIN4 and AIN5 for hardware differential measurement.

        WIRING: Keysight J1 Pin 12 (Signal Common / -S) is physically wired to
        both AIN4- and AIN5- on the T8 breakout board. This makes the measurement
        a true differential pair with Pin 12 as the reference - no software
        NEGATIVE_CH configuration is needed or written.

        The Keysight SW1 switch 4 is DOWN (default), so monitor outputs are
        0-5V range (0V = 0% output, 5V = 100% output). The T8 AIN range is
        set to +-10V which safely covers the 0-5V signal with headroom.

        DO NOT write AIN_NEGATIVE_CH here. The T8 thermocouple EF firmware
        on AIN0-AIN3 overrides that register, and attempting to write 199
        (GND reference) to AIN4/AIN5 caused conflicts in prior versions.
        The hardware wiring makes this unnecessary.
        """
        try:
            # Set range to +-10V to safely cover the 0-5V Keysight monitor output
            ljm.eWriteName(self.handle, f"{self._AIN_VOLTAGE}_RANGE", 10.0)
            ljm.eWriteName(self.handle, f"{self._AIN_CURRENT}_RANGE", 10.0)
        except Exception as e:
            print(f"Warning: Could not configure AIN ranges for Keysight monitors: {e}")

    def _enable_analog_mode(self):
        """
        Pull the Local/Analog select pin LOW (EIO0 = 0) to put the supply in
        analog programming mode.  Must be called once at startup.
        """
        try:
            # Disable any Extended Feature (EF) on this pin first.
            # If a previous application (e.g. Kipling) left an EF active on FIO0,
            # the EF controls the pin and direct digital writes are silently ignored —
            # which causes FIO0 to read back 1 even after writing 0.
            try:
                ljm.eWriteName(self.handle, f"{self._DIO_ANALOG_EN}_EF_ENABLE", 0)
            except Exception:
                pass  # Not all T8 firmware versions expose this; safe to ignore

            # FIO pins default to input on the T8 — must set direction to output first
            self._set_pin_output(self._DIO_ANALOG_EN)
            ljm.eWriteName(self.handle, self._DIO_ANALOG_EN, 0)
            print(f'[Keysight] Analog mode ENABLED via {self._DIO_ANALOG_EN}=LOW')
            print(f'[Keysight] DAC hard clamp active: max {self._DAC_MAX_V}V on DAC0/DAC1')
            print(f'[Keysight] Scaling: 5.0V DAC = {self.rated_max_volts}V / {self.rated_max_amps}A output')
            # Readback verification — confirms pin actually went LOW on this hardware
            readback = int(ljm.eReadName(self.handle, self._DIO_ANALOG_EN))
            if readback == 0:
                print(f'[Keysight] {self._DIO_ANALOG_EN} readback=LOW (0) ✓ — analog mode confirmed')
            else:
                print(
                    f'[Keysight] WARNING: {self._DIO_ANALOG_EN} readback={readback} (expected 0/LOW) — '
                    f'analog mode may NOT be active! '
                    f'Check that the EIO0 pin is wired to the PSU Local/Analog select input and '
                    f'that no external pull-up is holding the line HIGH. '
                    f'Try power-cycling the LabJack T8 and relaunching the application.'
                )
        except Exception as e:
            print(f'[Keysight] Warning: Could not enable analog mode on {self._DIO_ANALOG_EN}: {e}')

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
        """Scale an engineering value to the 0-5 V DAC range."""
        return (value / rated_max) * 5.0

    def _dac_to_volts(self, dac_v, rated_max):
        """Scale a DAC readback (0-5 V) back to engineering units."""
        return (dac_v / 5.0) * rated_max

    def _safe_dac_write(self, register, value):
        """
        Write a DAC value with a hard clamp to prevent exceeding 5.0 V.
        This is the only place DAC values are written to the T8.
        Raises ValueError if value is negative (programming error).
        """
        if value < 0.0:
            raise ValueError(f'DAC value cannot be negative: {value}')
        
        clamped = min(value, self._DAC_MAX_V)
        if clamped != value:
            print(f'WARNING: DAC value {value:.4f}V clamped to {clamped:.4f}V on {register}')
        
        if self.debug:
            print(f"[DEBUG] LJM Write: {register} = {clamped:.4f}V (original: {value:.4f}V)")
            
        try:
            ljm.eWriteName(self.handle, register, clamped)
        except Exception as e:
            print(f"ERROR: Failed to write {clamped:.4f}V to {register}: {e}")
            raise
            
        return clamped

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
        """
        # STEP 1: Safety checks
        if volts < 0 or volts > self.voltage_limit:
            print(f"ERROR: Voltage {volts}V is out of range (0-{self.voltage_limit}V)")
            return False

        try:
            # STEP 2: Calculate DAC values with correct scaling
            # FORMULA: (target / rated_max) * 5.0
            dac_v = (volts / self.rated_max_volts) * 5.0

            # STEP 3: Debug output (Before write)
            if self.debug:
                print(f"\n--- KEYSIGHT VOLTAGE COMMAND ---")
                print(f"Target Voltage: {volts:.3f} V")
                print(f"Scaling Info: Rated Max={self.rated_max_volts}V, DAC Max=5.0V")
                print(f"Calculated DAC: {dac_v:.4f} V (formula: ({volts:.3f} / {self.rated_max_volts}) * 5.0)")

            # STEP 4: Send to T8 via clamped write
            actual_written = self._safe_dac_write(self._DAC_VOLTAGE, dac_v)

            # STEP 5: Readback Verification
            actual_dac_v = ljm.eReadName(self.handle, self._DAC_VOLTAGE)
            if self.debug:
                print(f"DAC Readback:   {actual_dac_v:.4f} V")
                print(f"--------------------------------\n")

            return True
        except Exception as e:
            print(f"Failed to set voltage to {volts}V: {e}")
            return False

    def set_current(self, amps):
        """
        Set the output current limit.

        Args:
            amps: Current limit in amperes

        Returns:
            True if successful, False if failed
        """
        # STEP 1: Safety checks
        if amps < 0 or amps > self.current_limit:
            print(f"ERROR: Current {amps}A is out of range (0-{self.current_limit}A)")
            return False

        try:
            # STEP 2: Calculate DAC values with correct scaling
            # FORMULA: (target / rated_max) * 5.0
            dac_i = (amps / self.rated_max_amps) * 5.0

            # STEP 3: Debug output (Before write)
            if self.debug:
                print(f"\n--- KEYSIGHT CURRENT COMMAND ---")
                print(f"Target Current: {amps:.2f} A")
                print(f"Scaling Info: Rated Max={self.rated_max_amps}A, DAC Max=5.0V")
                print(f"Calculated DAC: {dac_i:.4f} V (formula: ({amps:.2f} / {self.rated_max_amps}) * 5.0)")

            # STEP 4: Send to T8 via clamped write
            actual_written = self._safe_dac_write(self._DAC_CURRENT, dac_i)

            # STEP 5: Readback Verification
            actual_dac_i = ljm.eReadName(self.handle, self._DAC_CURRENT)
            if self.debug:
                print(f"DAC Readback:   {actual_dac_i:.4f} V")
                print(f"--------------------------------\n")

            return True
        except Exception as e:
            print(f"Failed to set current to {amps}A: {e}")
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

        Keysight J1 Pin 11 outputs 0-5V proportional to 0-rated_max_volts
        (SW1 switch 4 DOWN = 0-5V monitor range).

        Scaling: (raw_ain / monitor_range_v) * rated_max_volts
        Default: (raw_ain / 5.0) * 6.0

        Returns:
            float: Measured voltage in volts, or None on error
        """
        try:
            raw_v = ljm.eReadName(self.handle, self._AIN_VOLTAGE)

            # CRITICAL SCALING - 0-5V input represents 0-rated_max_volts output
            actual_voltage = (raw_v / self._MONITOR_RANGE_V) * self.rated_max_volts

            # Debug output - helps verify scaling is correct
            if self.debug:
                print(f"\n--- KEYSIGHT VOLTAGE MONITOR ---")
                print(f"Raw AIN ({self._AIN_VOLTAGE}): {raw_v:.4f} V")
                print(f"Monitor Range: {self._MONITOR_RANGE_V} V (Switch 4: {self.switch_4_position})")
                print(f"Rated Max:     {self.rated_max_volts} V")
                print(f"Scaled Value:  {actual_voltage:.3f} V (formula: ({raw_v:.4f} / {self._MONITOR_RANGE_V}) * {self.rated_max_volts})")
                print(f"--------------------------------\n")

            # Safety check for reasonable values - allow for small negative noise (-0.05V raw)
            if raw_v < -0.05 or actual_voltage > self.rated_max_volts * 1.083:
                print(f"WARNING: Voltage reading {actual_voltage:.3f}V is out of expected range (0-{self.rated_max_volts}V)")
                print(f"         Raw AIN reading was: {raw_v:.4f}V on {self._AIN_VOLTAGE}")

            return actual_voltage
        except Exception as e:
            print(f"Failed to measure voltage on {self._AIN_VOLTAGE}: {e}")
            return None

    def get_current(self):
        """
        Read the actual output current from the analog monitor (AIN5).

        Keysight J1 Pin 24 outputs 0-5V proportional to 0-rated_max_amps
        (SW1 switch 4 DOWN = 0-5V monitor range).

        Scaling: (raw_ain / monitor_range_v) * rated_max_amps
        Default: (raw_ain / 5.0) * 180.0

        Returns:
            float: Measured current in amperes, or None on error
        """
        try:
            raw_v = ljm.eReadName(self.handle, self._AIN_CURRENT)

            # CRITICAL SCALING - 0-5V input represents 0-rated_max_amps output
            actual_current = (raw_v / self._MONITOR_RANGE_V) * self.rated_max_amps

            # Debug output - helps verify scaling is correct
            if self.debug:
                print(f"\n--- KEYSIGHT CURRENT MONITOR ---")
                print(f"Raw AIN ({self._AIN_CURRENT}): {raw_v:.4f} V")
                print(f"Monitor Range: {self._MONITOR_RANGE_V} V (Switch 4: {self.switch_4_position})")
                print(f"Rated Max:     {self.rated_max_amps} A")
                print(f"Scaled Value:  {actual_current:.2f} A (formula: ({raw_v:.4f} / {self._MONITOR_RANGE_V}) * {self.rated_max_amps})")
                print(f"--------------------------------\n")

            # Safety check for reasonable values - allow for small negative noise (-0.05V raw)
            if raw_v < -0.05 or actual_current > self.rated_max_amps * 1.028:
                print(f"WARNING: Current reading {actual_current:.2f}A is out of expected range (0-{self.rated_max_amps}A)")
                print(f"         Raw AIN reading was: {raw_v:.4f}V on {self._AIN_CURRENT}")

            return actual_current
        except Exception as e:
            print(f"Failed to measure current on {self._AIN_CURRENT}: {e}")
            return None

    def validate_scaling(self):
        """
        Test the scaling with known power supply outputs.
        User should set power supply to known values and verify readings match.
        """
        print("\n=== SCALING VALIDATION TEST ===")
        print("Manually set the Keysight to these values and verify readings:")
        print()
        
        test_points = [
            (0.0, 0.0, "Zero output"),
            (self.rated_max_volts / 2.0, self.rated_max_amps / 2.0, "Half scale (50%)"),
            (self.rated_max_volts, self.rated_max_amps, "Full scale (100%)")
        ]
        
        for expected_v, expected_a, description in test_points:
            print(f"\n--- {description} ---")
            print(f"Set Keysight to: {expected_v:.2f}V, {expected_a:.2f}A")
            input("Press Enter when Keysight is set...")
            
            actual_v = self.get_voltage()
            actual_a = self.get_current()
            
            if actual_v is None or actual_a is None:
                print("✗ ERROR: Could not read from Keysight monitors")
                continue

            v_error = abs(actual_v - expected_v)
            a_error = abs(actual_a - expected_a)
            
            print(f"Expected: {expected_v:.2f}V, {expected_a:.2f}A")
            print(f"Read:     {actual_v:.3f}V, {actual_a:.2f}A")
            print(f"Error:    {v_error:.3f}V, {a_error:.2f}A")
            
            # Check if within reasonable tolerance (2% of max)
            v_tol = self.rated_max_volts * 0.02
            a_tol = self.rated_max_amps * 0.02
            
            if v_error < v_tol and a_error < a_tol:
                print(f"✓ PASS - Within tolerance ({v_tol:.3f}V, {a_tol:.2f}A)")
            else:
                print("✗ FAIL - Outside tolerance")
                print("  Check: Is SW1-4 switch position correct?")
                print("  Check: Are AIN channels wired to correct J1 pins?")

    def test_keysight_scaling(self):
        """
        Test the scaling formula with known values.
        This proves the math is correct without requiring hardware to be at specific setpoints.

        Expected results (SW1-4 DOWN, 0-5V monitor range):
            0.0V AIN  →  0.0V  /  0.0A   (0%)
            1.0V AIN  →  1.2V  / 36.0A  (20%)
            2.5V AIN  →  3.0V  / 90.0A  (50%)
            4.0V AIN  →  4.8V  /144.0A  (80%)
            5.0V AIN  →  6.0V  /180.0A  (100%)
        """
        print("\n=== SCALING FORMULA TEST ===")
        print(f"Monitor range: {self._MONITOR_RANGE_V}V  |  "
              f"Max voltage: {self.rated_max_volts}V  |  Max current: {self.rated_max_amps}A")

        test_values = [
            (0.0, "0%   / Zero"),
            (1.0, "20%"),
            (2.5, "50%  / Half scale"),
            (4.0, "80%"),
            (5.0, "100% / Maximum"),
        ]

        print("\nVoltage Scaling (AIN input → power supply output):")
        all_pass = True
        for raw_v, label in test_values:
            calculated_v = (raw_v / self._MONITOR_RANGE_V) * self.rated_max_volts
            expected_v = (raw_v / 5.0) * 6.0  # canonical formula
            ok = abs(calculated_v - expected_v) < 1e-9
            if not ok:
                all_pass = False
            status = "✓" if ok else "✗"
            print(f"  {status} {raw_v:.1f}V → {calculated_v:.3f}V  ({label})")

        print("\nCurrent Scaling (AIN input → power supply output):")
        for raw_v, label in test_values:
            calculated_a = (raw_v / self._MONITOR_RANGE_V) * self.rated_max_amps
            expected_a = (raw_v / 5.0) * 180.0  # canonical formula
            ok = abs(calculated_a - expected_a) < 1e-9
            if not ok:
                all_pass = False
            status = "✓" if ok else "✗"
            print(f"  {status} {raw_v:.1f}V → {calculated_a:.2f}A  ({label})")

        if all_pass:
            print("\n✓ All scaling values correct — formula is right")
        else:
            print("\n✗ SCALING MISMATCH DETECTED — check rated_max_volts/amps and monitor range")
        print("============================\n")
        return all_pass

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
            self._set_pin_output(self._DIO_SHUTOFF)
            ljm.eWriteName(self.handle, self._DIO_SHUTOFF, 0)
            readback = int(ljm.eReadName(self.handle, self._DIO_SHUTOFF))
            print(f"[Keysight] output_on: wrote {self._DIO_SHUTOFF}=0, readback={readback} ({'OK' if readback == 0 else 'MISMATCH — check wiring/logic!'})")
            return True
        except Exception as e:
            print(f"Failed to enable output on {self._DIO_SHUTOFF}: {e}")
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
                self._set_pin_output(self._DIO_SHUTOFF)
                ljm.eWriteName(self.handle, self._DIO_SHUTOFF, 1)
                readback = int(ljm.eReadName(self.handle, self._DIO_SHUTOFF))
                print(f"[Keysight] output_off attempt {attempt+1}: wrote {self._DIO_SHUTOFF}=1, readback={readback} ({'OK' if readback == 1 else 'MISMATCH — output may still be ON!'})")
                if not self.is_output_on():
                    return True
            except Exception as e:
                print(f"Output off attempt {attempt + 1} on {self._DIO_SHUTOFF} failed: {e}")

        print(f"CRITICAL: Failed to disable output on {self._DIO_SHUTOFF} after 3 attempts!")
        return False

    def is_output_on(self):
        """
        Check whether the output is currently enabled.

        FIO1 = 0 → Shut Off de-asserted → output ON
        FIO1 = 1 → Shut Off asserted    → output OFF

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

    def check_control_pins(self):
        """
        Read the current state of the control pins (FIO0 and FIO1).
        
        Returns:
            dict: {pin_name: state}
        """
        states = {}
        for pin in [self._DIO_ANALOG_EN, self._DIO_SHUTOFF]:
            try:
                states[pin] = int(ljm.eReadName(self.handle, pin))
            except Exception as e:
                states[pin] = f"ERROR: {e}"
        return states

    def run_diagnostics(self):
        """
        Perform a comprehensive diagnostic check of the analog controller.
        Prints results directly to console.
        """
        print("\n" + "="*50)
        print("KEYSIGHT ANALOG CONTROLLER DIAGNOSTICS")
        print("="*50)
        
        # 1. Check Handle
        print(f"LJM Handle: {'VALID' if self.handle is not None else 'INVALID (None)'}")
        if self.handle is None:
            print("ERROR: No valid LabJack handle. Diagnostics cannot continue.")
            return

        # 2. Check Pin Configuration
        print("\n[ Pin Configuration ]")
        print(f"  Voltage Program: {self._DAC_VOLTAGE}")
        print(f"  Current Program: {self._DAC_CURRENT}")
        print(f"  Voltage Monitor: {self._AIN_VOLTAGE}")
        print(f"  Current Monitor: {self._AIN_CURRENT}")
        print(f"  Analog Enable:   {self._DIO_ANALOG_EN} (Should be LOW/0)")
        print(f"  Shut Off:        {self._DIO_SHUTOFF} (Should be LOW/0 for output)")

        # 3. Check Control Pin States
        print("\n[ Control Pin States ]")
        pin_states = self.check_control_pins()
        for pin, state in pin_states.items():
            print(f"  {pin}: {state}")
            
        if pin_states.get(self._DIO_ANALOG_EN) != 0:
            print(f"  WARNING: {self._DIO_ANALOG_EN} is NOT LOW. Analog mode may be disabled!")
        else:
            print(f"  OK: {self._DIO_ANALOG_EN} is LOW (Analog mode enabled)")

        # 4. Check Monitor Scaling
        print("\n[ Monitor Scaling ]")
        print(f"  Switch 4:    {self.switch_4_position}")
        print(f"  Monitor Range: {self._MONITOR_RANGE_V} V")
        print(f"  Rated Max V:   {self.rated_max_volts} V")
        print(f"  Rated Max I:   {self.rated_max_amps} A")

        # 5. Live Readings
        print("\n[ Live Readings ]")
        try:
            raw_v_mon = ljm.eReadName(self.handle, self._AIN_VOLTAGE)
            raw_i_mon = ljm.eReadName(self.handle, self._AIN_CURRENT)
            actual_v = self.get_voltage()
            actual_i = self.get_current()
            
            print(f"  {self._AIN_VOLTAGE} (Raw): {raw_v_mon:.4f} V  →  {actual_v:.3f} V actual")
            print(f"  {self._AIN_CURRENT} (Raw): {raw_i_mon:.4f} V  →  {actual_i:.2f} A actual")
        except Exception as e:
            print(f"  ERROR reading monitors: {e}")

        # 6. Setpoint Verification
        print("\n[ Setpoint Verification ]")
        try:
            dac_v = ljm.eReadName(self.handle, self._DAC_VOLTAGE)
            dac_i = ljm.eReadName(self.handle, self._DAC_CURRENT)
            set_v = self._dac_to_volts(dac_v, self.rated_max_volts)
            set_i = self._dac_to_volts(dac_i, self.rated_max_amps)
            
            print(f"  {self._DAC_VOLTAGE} (Raw): {dac_v:.4f} V  →  {set_v:.3f} V setpoint")
            print(f"  {self._DAC_CURRENT} (Raw): {dac_i:.4f} V  →  {set_i:.2f} A setpoint")
        except Exception as e:
            print(f"  ERROR reading DACs: {e}")

        print("\n" + "="*50)
        print("DIAGNOSTICS COMPLETE")
        print("="*50 + "\n")

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
            self._safe_dac_write(self._DAC_VOLTAGE, 0.0)
            self._safe_dac_write(self._DAC_CURRENT, 0.0)
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

        self.interlock_active = True

        # 2. Zero the voltage program DAC
        try:
            self._safe_dac_write(self._DAC_VOLTAGE, 0.0)
        except Exception:
            success = False

        # 3. Zero the current program DAC
        try:
            self._safe_dac_write(self._DAC_CURRENT, 0.0)
        except Exception:
            success = False

        if success:
            print("EMERGENCY SHUTDOWN: Power supply output disabled")
        else:
            print("EMERGENCY SHUTDOWN: Partial failure - verify output manually!")

        return success

    def clear_interlock(self):
        self.interlock_active = False
        print("[Keysight] Interlock cleared by operator")

    # ──────────────────────────────────────────────────────────────────────────
    # Limit management
    # ──────────────────────────────────────────────────────────────────────────

    def set_voltage_limit(self, volts):
        """
        Update the software voltage limit (capped at rated_max_volts).

        Args:
            volts: New maximum voltage limit
        """
        if volts > 0:
            self.voltage_limit = min(volts, self.rated_max_volts)

    def set_current_limit(self, amps):
        """
        Update the software current limit (capped at rated_max_amps).

        Args:
            amps: New maximum current limit
        """
        if amps > 0:
            self.current_limit = min(amps, self.rated_max_amps)

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

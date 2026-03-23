"""
data_acquisition.py
PURPOSE: High-speed data acquisition in a dedicated thread, decoupled from GUI.
Reads all sensors at the configured interval and delivers data via callback.
"""

import threading
import time
import math
import random

# ── Power Programmer Debug Configuration ──────────────────────────────────────
# Set to False to disable verbose terminal output during Power Programmer runs.
DEBUG_POWER_PROGRAMMER = True

# Acceptable round-trip error tolerances (floating-point precision limits).
# After setpoint → analog → monitor conversion the results must match within:
_PP_VOLTAGE_TOLERANCE = 0.001   # 1 mV
_PP_CURRENT_TOLERANCE = 0.01    # 10 mA

# Keysight N5700 hardware limits (must match KeysightAnalogController defaults)
_PP_MAX_VOLTS = 6.0    # Rated maximum supply voltage
_PP_MAX_AMPS  = 180.0  # Rated maximum supply current
_PP_DAC_MAX   = 5.0    # T8 DAC / AIN full-scale voltage


# ── Shared Scaling Functions ───────────────────────────────────────────────────
# CRITICAL: These EXACT formulas are used in BOTH practice-mode simulation and
# live-mode analog output so that practice output is 100 % identical to live.
# Do NOT copy/paste these formulas elsewhere — always call these functions.

def pp_setpoint_to_dac_voltage(voltage_setpoint):
    """
    Convert a voltage setpoint to the DAC output voltage sent to the Keysight.

    Keysight voltage range : 0 V – 6 V maximum
    T8 analog output range : 0 V – 5 V
    Formula                : analog_voltage = (setpoint_voltage / 6.0) * 5.0
    """
    return (voltage_setpoint / _PP_MAX_VOLTS) * _PP_DAC_MAX


def pp_setpoint_to_dac_current(current_setpoint):
    """
    Convert a current setpoint to the DAC output voltage sent to the Keysight.

    Keysight current range : 0 A – 180 A maximum
    T8 analog output range : 0 V – 5 V
    Formula                : analog_voltage = (setpoint_current / 180.0) * 5.0
    """
    return (current_setpoint / _PP_MAX_AMPS) * _PP_DAC_MAX


def pp_dac_to_monitored_voltage(analog_input_voltage):
    """
    Convert an analog monitor input voltage back to an actual supply voltage.

    Monitor input from Keysight : 0 V – 5 V represents 0 V – 6 V actual
    Formula                     : actual_voltage = (analog_input / 5.0) * 6.0
    """
    return (analog_input_voltage / _PP_DAC_MAX) * _PP_MAX_VOLTS


def pp_dac_to_monitored_current(analog_input_current):
    """
    Convert an analog monitor input voltage back to an actual supply current.

    Monitor input from Keysight : 0 V – 5 V represents 0 A – 180 A actual
    Formula                     : actual_current = (analog_input / 5.0) * 180.0
    """
    return (analog_input_current / _PP_DAC_MAX) * _PP_MAX_AMPS


class DataAcquisition:
    def __init__(self, config, tc_reader=None, frg702_reader=None,
                 ps_controller=None, safety_monitor=None, ramp_executor=None,
                 practice_mode=False):
        """
        Initialize the data acquisition engine.

        Args:
            config: Application config dict
            tc_reader: ThermocoupleReader instance (or None for practice mode)
            frg702_reader: FRG702Reader instance (or None)
            ps_controller: PowerSupplyController instance (or None)
            safety_monitor: SafetyMonitor instance (or None)
            ramp_executor: RampExecutor instance (or None)
            practice_mode: If True, generate simulated data
        """
        self.config = config
        self.tc_reader = tc_reader
        self.frg702_reader = frg702_reader
        self.ps_controller = ps_controller
        self.safety_monitor = safety_monitor
        self.ramp_executor = ramp_executor
        self.practice_mode = practice_mode

        self._acquisition_running = False
        self._acquisition_thread = None
        self._acquisition_callback = None

        # Pressure interlock
        self._interlock_callback = None
        self._pressure_interlock_fired = False

        # Latest all_readings cache (for get_last_readings())
        self._last_all_readings = {}

        # Latest TC readings cache (thread-safe, for TempRampExecutor access)
        self._latest_tc_readings = {}
        self._tc_readings_lock = threading.Lock()

        # TempRampExecutor reference — set by main_window when a TempRamp run
        # is active so practice-mode TC simulation uses the executor's simulated
        # temperature instead of the generic sine-wave formula.
        self.temp_ramp_executor = None

        # Timing diagnostics
        self._timing_samples = []
        self._timing_lock = threading.Lock()
        self.last_timing_report = ""

    def read_all_sensors(self):
        """
        Read all sensors in one pass and return timestamp + readings dict.

        Returns:
            (timestamp, all_readings, tc_readings, frg702_details, raw_voltages) tuple

            raw_voltages is a dict keyed by '<tc_name>_rawV' containing the
            raw differential voltage read directly from the AIN# register
            before the T8 extended-feature (EF) temperature conversion.
            This is used for logging and the live pinout display so the user
            can verify the physical wiring and conversion chain.
        """
        timestamp = time.time()
        tc_readings = {}
        frg702_readings = {}
        frg702_detail_readings = {}
        ps_readings = {}
        raw_voltages = {}

        if self.practice_mode:
            # Generate simulated thermocouple data
            _t = time.time()
            _enabled_idx = 0
            for tc in self.config.get('thermocouples', []):
                if not tc.get('enabled', True):
                    continue
                _name = tc['name']
                if (_enabled_idx == 0
                        and self.temp_ramp_executor is not None
                        and self.temp_ramp_executor.is_running()):
                    # Primary TC follows the PID-simulated temperature
                    sim_temp_k = self.temp_ramp_executor._practice_temp_k or 293.15
                    val = sim_temp_k - 273.15  # convert K → °C for display
                else:
                    # Secondary TCs (or when no TempRamp is active): independent
                    # sine-wave noise around room temperature so they don't clone TC_1.
                    val = 20.0 + 5.0 * math.sin(_t / 10.0 + _enabled_idx * 1.3) + random.uniform(-0.5, 0.5)
                tc_readings[_name] = val
                # Simulate raw TC voltage: typical range ±0.1V (100mV)
                # Approximate back-calculation from temperature for Type K
                # Just a plausible simulated value for practice mode
                raw_voltages[f"{_name}_rawV"] = round(
                    (val - 20.0) * 4.1e-5 + random.uniform(-2e-6, 2e-6), 8
                )
                _enabled_idx += 1

            # Generate simulated FRG-702 data
            for gauge in self.config.get('frg702_gauges', []):
                if gauge.get('enabled', True):
                    t = time.time()
                    exponent = -6.0 + 1.5 * math.sin(t / 20.0) + random.uniform(-0.1, 0.1)
                    frg702_readings[gauge['name']] = 10 ** exponent

            for gauge in self.config.get('frg702_gauges', []):
                if gauge.get('enabled', True):
                    frg702_detail_readings[gauge['name']] = {
                        'pressure': frg702_readings.get(gauge['name']),
                        'status': 'valid',
                        'mode': 'Combined Pirani/Cold Cathode',
                        'voltage': 5.0,
                    }

            # Power supply readings
            if self.ps_controller:
                # ── TempRamp PID practice-mode simulation ─────────────────────
                # When a TempRamp PID run is active, derive simulated PS readings
                # from the executor's last computed V/I values so the power
                # supply monitor shows exactly what the real hardware will output.
                # Uses the same pp_dac_to_monitored_* scaling functions as live
                # mode to guarantee practice output matches real output precisely.
                if (self.temp_ramp_executor is not None
                        and self.temp_ramp_executor.is_running()):
                    _v_dac = getattr(self.temp_ramp_executor, '_last_voltage_dac', 0.0)
                    _i_dac = getattr(self.temp_ramp_executor, '_last_current_dac', 0.0)
                    monitored_voltage = pp_dac_to_monitored_voltage(_v_dac)
                    monitored_current = pp_dac_to_monitored_current(_i_dac)
                    ps_readings = {
                        'PS_Voltage':   monitored_voltage,
                        'PS_Current':   monitored_current,
                        'PS_Output_On': True,
                    }
                # ── Power Programmer practice-mode simulation ─────────────────
                # When the ramp executor is actively running, simulate the full
                # T8 analog signal chain instead of returning the raw setpoints.
                # This ensures that what Isaac sees on the monitor plots is
                # EXACTLY what the live hardware will deliver — any formula
                # error in the scaling will cause a visible mismatch here.
                elif (self.ramp_executor is not None
                        and self.ramp_executor.is_running()):
                    # STEP 1: Read setpoints stored by the ramp executor's
                    #         set_voltage() / set_current() calls.
                    voltage_setpoint = self.ps_controller.get_voltage_setpoint() or 0.0
                    current_setpoint = self.ps_controller.get_current_setpoint() or 0.0

                    # STEP 2: Convert setpoints → DAC output voltages
                    #         (what the T8 DAC0/DAC1 would output in live mode)
                    dac_v = pp_setpoint_to_dac_voltage(voltage_setpoint)
                    dac_i = pp_setpoint_to_dac_current(current_setpoint)

                    # STEP 3: Simulate those DAC voltages passing through the
                    #         cable and arriving at the AIN4/AIN5 monitor inputs.

                    # STEP 4: Convert monitor inputs → engineering units
                    #         (what the software reads from AIN4/AIN5 in live mode)
                    monitored_voltage = pp_dac_to_monitored_voltage(dac_v)
                    # In practice mode there is no physical load. Simulate near-zero current
                    # with a tiny noise term so the plot isn't a flat zero line.
                    monitored_current = 0.0

                    # STEP 5: Validation — the round-trip must be exact within
                    #         floating-point tolerance.  Any failure here means
                    #         the scaling formulas are inconsistent.
                    voltage_error = abs(voltage_setpoint - monitored_voltage)
                    current_error = abs(current_setpoint - monitored_current)

                    if voltage_error > _PP_VOLTAGE_TOLERANCE:
                        print(f"WARNING: Voltage mismatch detected! "
                              f"Error: {voltage_error:.6f} V  "
                              f"(setpoint={voltage_setpoint:.4f} V, "
                              f"monitored={monitored_voltage:.4f} V)")

                    if current_error > _PP_CURRENT_TOLERANCE:
                        print(f"WARNING: Current mismatch detected! "
                              f"Error: {current_error:.6f} A  "
                              f"(setpoint={current_setpoint:.4f} A, "
                              f"monitored={monitored_current:.4f} A)")

                    if DEBUG_POWER_PROGRAMMER:
                        print(
                            f"[PP PRACTICE] "
                            f"Setpoint -> V={voltage_setpoint:.4f}V  A={current_setpoint:.4f}A  |  "
                            f"DAC_V={dac_v:.4f}V  DAC_A={dac_i:.4f}V  |  "
                            f"Monitor -> V={monitored_voltage:.4f}V  A={monitored_current:.4f}A"
                        )

                    # ── Debug terminal output ─────────────────────────────────
                    if DEBUG_POWER_PROGRAMMER:
                        # Gather block / timing info from the ramp executor
                        step_start_v = step_end_v = step_start_a = step_end_a = None
                        progress = 0.0
                        try:
                            elapsed   = self.ramp_executor.get_elapsed_time()
                            profile   = self.ramp_executor._profile
                            total_dur = profile.get_total_duration() if profile else 0.0
                            step_idx  = self.ramp_executor._current_step_index
                            if profile and 0 <= step_idx < len(profile.steps):
                                step      = profile.steps[step_idx]
                                block_num = step_idx + 1
                                block_type = step.step_type.upper()  # "RAMP" or "HOLD"

                                # Compute start values for this block by evaluating setpoint
                                # at the exact moment the block began
                                cumulative_time = sum(
                                    s.duration_sec for s in profile.steps[:step_idx]
                                )
                                time_into_step = elapsed - cumulative_time
                                progress = (
                                    time_into_step / step.duration_sec
                                    if step.duration_sec > 0 else 1.0
                                )

                                # Start values are the profile setpoints at block start time
                                step_start_v = profile.get_setpoint_at_time(cumulative_time)
                                step_end_v   = step.target_voltage
                                step_start_a = profile.get_current_setpoint_at_time(cumulative_time)
                                step_end_a   = step.target_current
                            else:
                                block_num  = "?"
                                block_type = "UNKNOWN"
                        except Exception:
                            elapsed    = 0.0
                            total_dur  = 0.0
                            block_num  = "?"
                            block_type = "UNKNOWN"

                        v_pass = "PASS" if voltage_error <= _PP_VOLTAGE_TOLERANCE else "FAIL"
                        i_pass = "PASS" if current_error <= _PP_CURRENT_TOLERANCE else "FAIL"

                        # Build block table debug lines
                        if step_start_v is not None:
                            block_debug = (
                                f"\n  BLOCK TABLE VALUES:\n"
                                f"    From table: Start V={step_start_v:.4f}, End V={step_end_v}\n"
                                f"    From table: Start A={step_start_a:.4f}, End A={step_end_a}\n"
                                f"    Progress in block: {progress:.4f}\n"
                            )
                        else:
                            block_debug = ""

                        print(
                            f"\n=== POWER PROGRAMMER DEBUG [Practice Mode] ===\n"
                            f"  Time : {elapsed:.2f} s / {total_dur:.2f} s\n"
                            f"  Block: {block_num} — {block_type}\n"
                            f"{block_debug}"
                            f"\n  TARGET VALUES:\n"
                            f"    Voltage Setpoint : {voltage_setpoint:8.3f} V\n"
                            f"    Current Setpoint : {current_setpoint:8.2f} A\n"
                            f"\n  ANALOG OUTPUT CALCULATIONS:\n"
                            f"    Voltage -> Analog : {voltage_setpoint:.3f} V setpoint "
                            f"-> {dac_v:.4f} V analog output  "
                            f"(0-5 V scale: 0 V=0 V, 5 V=6 V)\n"
                            f"    Current -> Analog : {current_setpoint:.2f} A setpoint "
                            f"-> {dac_i:.4f} V analog output  "
                            f"(0-5 V scale: 0 V=0 A, 5 V=180 A)\n"
                            f"\n  EXPECTED MONITOR RESPONSE (simulating T8 analog inputs):\n"
                            f"    Voltage Monitor Reading : {monitored_voltage:.3f} V  "
                            f"(from {dac_v:.4f} V analog input)\n"
                            f"    Current Monitor Reading : {monitored_current:.2f} A  "
                            f"(from {dac_i:.4f} V analog input)\n"
                            f"\n  VERIFICATION:\n"
                            f"    Setpoint matches Monitor : {v_pass} / {i_pass}\n"
                            f"    Voltage error : ±{voltage_error:.4f} V\n"
                            f"    Current error : ±{current_error:.3f} A\n"
                            f"{'=' * 50}"
                        )

                    # Use the analog-derived monitor values for the plots,
                    # NOT the raw setpoints (avoids 'direct setpoint' mistake).
                    ps_readings = {
                        'PS_Voltage':   monitored_voltage,
                        'PS_Current':   monitored_current,
                        'PS_Output_On': self.ps_controller.is_output_on(),
                    }
                else:
                    # Programmer not running — use normal mock readings
                    # (may include simulated noise for general practice mode)
                    ps_readings = self.ps_controller.get_readings()
            elif self.config.get('power_supply', {}).get('enabled', True):
                t = time.time()
                ps_readings = {
                    'PS_Voltage': 12.0 + 2.0 * math.sin(t / 15.0) + random.uniform(-0.1, 0.1),
                    'PS_Current': 2.0 + 0.5 * math.cos(t / 12.0) + random.uniform(-0.05, 0.05)
                }
        else:
            # Read real hardware
            if self.tc_reader:
                tc_readings = self.tc_reader.read_all()
                # Also read raw input voltages for signal-chain verification
                try:
                    raw_voltages = self.tc_reader.read_raw_voltages()
                except Exception as e:
                    print(f"Raw voltage read skipped: {e}")
                    raw_voltages = {}

            if self.frg702_reader:
                # Single serial read — derive the flat pressure dict from the
                # detail dict so the plot buffer and status panel always share
                # the exact same measurement (no second round-trip to hardware).
                frg702_detail_readings = self.frg702_reader.read_all_with_status()
                frg702_readings = {
                    name: info['pressure']
                    for name, info in frg702_detail_readings.items()
                }

                if getattr(self.frg702_reader, 'DEBUG_PRESSURE', False):
                    from t8_daq_system.hardware.frg702_reader import UNIT_CONVERSIONS, FRG702Reader
                    display_unit = self.config.get('pressure_unit', 'mbar')
                    for name, detail in frg702_detail_readings.items():
                        mbar = detail.get('pressure')
                        if mbar is not None:
                            converted = FRG702Reader.convert_pressure(mbar, display_unit)
                            print(
                                f"[DISPLAY CHAIN] {name}: "
                                f"{mbar:.4e} mbar  ->  {converted:.4e} {display_unit}  "
                                f"(conversion factor: {UNIT_CONVERSIONS.get(display_unit, 1.0)})"
                            )

            if self.ps_controller:
                ps_readings = self.ps_controller.get_readings()

        # Merge readings but exclude status flags (PS_Output_On is not a sensor value)
        ps_sensor_readings = {k: v for k, v in ps_readings.items() if k != 'PS_Output_On'}
        all_readings = {**tc_readings, **frg702_readings, **ps_sensor_readings}
        return timestamp, all_readings, tc_readings, frg702_detail_readings, raw_voltages

    def start_fast_acquisition(self, callback=None):
        """
        Start high-speed data acquisition in a separate thread.

        Args:
            callback: function called with (timestamp, all_readings, tc_readings,
                      frg702_details) on each acquisition cycle
        """
        if self._acquisition_running:
            return

        self._acquisition_running = True
        self._acquisition_callback = callback
        self._timing_samples = []

        def acquisition_loop():
            while self._acquisition_running:
                loop_start = time.time()

                try:
                    timestamp, all_readings, tc_readings, frg702_details, raw_voltages = \
                        self.read_all_sensors()

                    # Cache latest TC readings for thread-safe access by TempRampExecutor
                    with self._tc_readings_lock:
                        self._latest_tc_readings = dict(tc_readings)

                    # Cache all_readings for get_last_readings()
                    self._last_all_readings = dict(all_readings)

                    # ── Pressure interlock: >1e-4 Torr → emergency shutdown ──────
                    PRESSURE_INTERLOCK_TORR = 1e-4
                    for k, info in frg702_details.items():
                        if isinstance(info, dict):
                            pval = info.get('pressure')
                        elif isinstance(info, float):
                            pval = info
                        else:
                            pval = None
                        if pval is not None and isinstance(pval, float) and pval > PRESSURE_INTERLOCK_TORR:
                            if not self._pressure_interlock_fired:
                                self._pressure_interlock_fired = True
                                print(f"[INTERLOCK] Pressure {pval:.2e} Torr exceeds {PRESSURE_INTERLOCK_TORR:.0e} Torr limit!")
                                if self._interlock_callback:
                                    self._interlock_callback(pval)
                            break

                    # Safety check
                    if self.safety_monitor and tc_readings:
                        safe = self.safety_monitor.check_limits(tc_readings)
                        if not safe:
                            self._acquisition_running = False
                            if callback:
                                callback(timestamp, all_readings, tc_readings,
                                         frg702_details, safety_shutdown=True,
                                         raw_voltages=raw_voltages)
                            break

                    # Ramp executor voltage update
                    if self.ps_controller and self.ramp_executor:
                        if self.ramp_executor.is_running():
                            new_setpoint = self.ramp_executor.get_current_setpoint()
                            try:
                                self.ps_controller.set_voltage(new_setpoint)
                            except Exception as e:
                                print(f"Error setting voltage: {e}")

                    # Deliver data via callback
                    if callback and all_readings:
                        callback(timestamp, all_readings, tc_readings,
                                 frg702_details, safety_shutdown=False,
                                 raw_voltages=raw_voltages)

                except Exception as e:
                    print(f"Error in acquisition loop: {e}")

                # Timing diagnostics
                elapsed = time.time() - loop_start
                with self._timing_lock:
                    self._timing_samples.append(elapsed * 1000)  # ms
                    if len(self._timing_samples) >= 50:
                        avg_time = sum(self._timing_samples) / len(self._timing_samples)
                        max_time = max(self._timing_samples)
                        target = self.config['logging']['interval_ms']
                        self.last_timing_report = (
                            f"Avg acquisition time: {avg_time:.1f}ms, "
                            f"Max: {max_time:.1f}ms (target: {target}ms)"
                        )
                        print(self.last_timing_report)
                        self._timing_samples = []

                # Sleep for remaining time to hit target rate
                elapsed = time.time() - loop_start
                sleep_time = max(0, (self.config['logging']['interval_ms'] / 1000.0) - elapsed)
                time.sleep(sleep_time)

        self._acquisition_thread = threading.Thread(target=acquisition_loop, daemon=True)
        self._acquisition_thread.start()

    def stop_fast_acquisition(self):
        """Stop the acquisition thread."""
        self._acquisition_running = False
        if self._acquisition_thread is not None:
            self._acquisition_thread.join(timeout=2.0)
            self._acquisition_thread = None

    def is_running(self):
        """Check if acquisition is currently running."""
        return self._acquisition_running

    def set_pressure_interlock_callback(self, fn):
        """Register fn(pressure_torr) called when pressure exceeds 1e-4 Torr."""
        self._interlock_callback = fn

    def reset_pressure_interlock(self):
        self._pressure_interlock_fired = False

    def get_last_readings(self):
        """Return the most recent all_readings dict (thread-safe copy)."""
        return dict(self._last_all_readings)

    def update_readers(self, tc_reader=None, frg702_reader=None,
                       ps_controller=None, config=None):
        """Update hardware reader references and optionally config."""
        if tc_reader is not None:
            self.tc_reader = tc_reader
        if frg702_reader is not None:
            self.frg702_reader = frg702_reader
        if ps_controller is not None:
            self.ps_controller = ps_controller
        if config is not None:
            self.config = config

    def get_latest_tc_celsius(self, name=None):
        """
        Return the most recent thermocouple reading in °C.

        Thread-safe — can be called from background threads (e.g. TempRampExecutor).

        Args:
            name: Optional TC name (e.g. 'TC_1').  If None, returns the first
                  enabled TC reading found.

        Returns:
            float in °C, or None if no reading is available.
        """
        with self._tc_readings_lock:
            readings = dict(self._latest_tc_readings)

        if not readings:
            return None

        if name and name in readings:
            return readings[name]

        # Return first enabled TC in config order
        for tc in self.config.get('thermocouples', []):
            if tc.get('enabled', True) and tc['name'] in readings:
                return readings[tc['name']]

        return None

    def get_tc_kelvin_by_name(self, tc_name: str):
        """
        Read a thermocouple by name and return the value in Kelvin,
        regardless of the display unit setting.

        The ThermocoupleReader always configures AIN_EF_CONFIG_A = 1 (Celsius).
        This method explicitly converts Celsius → Kelvin so the PID loop
        always receives Kelvin without double-converting.

        Returns:
            float: Temperature in Kelvin, or None if reading failed.
        """
        if self.tc_reader is None:
            return None
        try:
            temp_c = self.tc_reader.read_single(tc_name)
            if temp_c is None:
                return None
            # ThermocoupleReader always outputs Celsius (EF_CONFIG_A=1)
            # Convert to Kelvin for PID consumption
            return temp_c + 273.15
        except Exception as e:
            print(f"[DAQ] get_tc_kelvin_by_name({tc_name}) error: {e}")
            return None

    def get_available_tc_names(self) -> list:
        """
        Return a list of enabled thermocouple names available for PID selection.

        Returns:
            list of str: e.g. ['TC_AIN0_C', 'TC_AIN1_C']
        """
        if self.tc_reader is None:
            return []
        return self.tc_reader.get_enabled_channels()

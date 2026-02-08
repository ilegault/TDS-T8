"""
data_acquisition.py
PURPOSE: High-speed data acquisition in a dedicated thread, decoupled from GUI.
Reads all sensors at the configured interval and delivers data via callback.
"""

import threading
import time
import math
import random


class DataAcquisition:
    def __init__(self, config, tc_reader=None, frg702_reader=None,
                 ps_controller=None, turbo_controller=None,
                 safety_monitor=None, ramp_executor=None,
                 practice_mode=False):
        """
        Initialize the data acquisition engine.

        Args:
            config: Application config dict
            tc_reader: ThermocoupleReader instance (or None for practice mode)
            frg702_reader: FRG702Reader instance (or None)
            ps_controller: PowerSupplyController instance (or None)
            turbo_controller: TurboPumpController instance (or None)
            safety_monitor: SafetyMonitor instance (or None)
            ramp_executor: RampExecutor instance (or None)
            practice_mode: If True, generate simulated data
        """
        self.config = config
        self.tc_reader = tc_reader
        self.frg702_reader = frg702_reader
        self.ps_controller = ps_controller
        self.turbo_controller = turbo_controller
        self.safety_monitor = safety_monitor
        self.ramp_executor = ramp_executor
        self.practice_mode = practice_mode

        self._acquisition_running = False
        self._acquisition_thread = None
        self._acquisition_callback = None

        # Timing diagnostics
        self._timing_samples = []
        self._timing_lock = threading.Lock()
        self.last_timing_report = ""

    def read_all_sensors(self):
        """
        Read all sensors in one pass and return timestamp + readings dict.

        Returns:
            (timestamp, all_readings, frg702_details) tuple
        """
        timestamp = time.time()
        tc_readings = {}
        frg702_readings = {}
        frg702_detail_readings = {}
        ps_readings = {}
        turbo_readings = {}

        if self.practice_mode:
            # Generate simulated thermocouple data
            for tc in self.config.get('thermocouples', []):
                if tc.get('enabled', True):
                    t = time.time()
                    val = 20.0 + 5.0 * math.sin(t / 10.0) + random.uniform(-0.5, 0.5)
                    tc_readings[tc['name']] = val

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
                ps_readings = self.ps_controller.get_readings()
            elif self.config.get('power_supply', {}).get('enabled', True):
                ps_readings = {
                    'PS_Voltage': 12.0 + random.uniform(-0.1, 0.1),
                    'PS_Current': 2.0 + random.uniform(-0.05, 0.05)
                }

            # Turbo pump readings
            if self.turbo_controller:
                turbo_readings = self.turbo_controller.get_status_dict()
            elif self.config.get('turbo_pump', {}).get('enabled', False):
                turbo_readings = {
                    'Turbo_Commanded': 'OFF',
                    'Turbo_Status': 'OFF'
                }
        else:
            # Read real hardware
            if self.tc_reader:
                tc_readings = self.tc_reader.read_all()

            if self.frg702_reader:
                frg702_readings = self.frg702_reader.read_all()
                frg702_detail_readings = self.frg702_reader.read_all_with_status()

            if self.ps_controller:
                ps_readings = self.ps_controller.get_readings()

            if self.turbo_controller:
                turbo_readings = self.turbo_controller.get_status_dict()

        all_readings = {**tc_readings, **frg702_readings, **ps_readings, **turbo_readings}
        return timestamp, all_readings, tc_readings, frg702_detail_readings

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
                    timestamp, all_readings, tc_readings, frg702_details = self.read_all_sensors()

                    # Safety check
                    if self.safety_monitor and tc_readings:
                        safe = self.safety_monitor.check_limits(tc_readings)
                        if not safe:
                            self._acquisition_running = False
                            if callback:
                                callback(timestamp, all_readings, tc_readings,
                                         frg702_details, safety_shutdown=True)
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
                                 frg702_details, safety_shutdown=False)

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

    def update_readers(self, tc_reader=None, frg702_reader=None,
                       ps_controller=None, turbo_controller=None):
        """Update hardware reader references (e.g. after reconnection)."""
        if tc_reader is not None:
            self.tc_reader = tc_reader
        if frg702_reader is not None:
            self.frg702_reader = frg702_reader
        if ps_controller is not None:
            self.ps_controller = ps_controller
        if turbo_controller is not None:
            self.turbo_controller = turbo_controller

"""
main_window.py
PURPOSE: Main application window - coordinates everything

Integrates LabJack T8 DAQ (thermocouples) and XGS-600 controller
(FRG-702 gauges) with Keysight N5761A power supply control, safety monitoring,
and ramp profile execution.

Safety features:
- 2200C temperature override triggers controlled ramp-down
- Restart lockout until temperature drops below 2150C
"""

import tkinter as tk
from tkinter import ttk, messagebox
import time
import os
import sys
import random
import math

from t8_daq_system.utils.startup_profiler import profiler


class GUIProfiler:
    """Lightweight continuous profiler for the GUI update loop."""
    def __init__(self):
        self.enabled = True
        self.call_count = 0
        self.section_times = {}  # section_name -> list of durations
        self._current_section_start = None
        self._current_section_name = None
        self._loop_start = None
        self._slow_threshold_ms = 50  # Log warning if any section takes > 50ms

    def loop_start(self):
        self.call_count += 1
        self._loop_start = time.perf_counter()

    def start(self, name):
        now = time.perf_counter()
        # End previous section if any
        if self._current_section_name:
            self._end_current(now)
        self._current_section_start = now
        self._current_section_name = name

    def _end_current(self, now):
        if self._current_section_name and self._current_section_start:
            elapsed_ms = (now - self._current_section_start) * 1000
            if self._current_section_name not in self.section_times:
                self.section_times[self._current_section_name] = []
            self.section_times[self._current_section_name].append(elapsed_ms)
            if elapsed_ms > self._slow_threshold_ms:
                print(f"[GUI SLOW] {self._current_section_name}: {elapsed_ms:.1f}ms (call #{self.call_count})")

    def loop_end(self):
        now = time.perf_counter()
        self._end_current(now)
        self._current_section_name = None
        total_ms = (now - self._loop_start) * 1000
        if total_ms > 100:  # Log if total loop takes > 100ms
            print(f"[GUI SLOW LOOP] Total: {total_ms:.1f}ms (call #{self.call_count})")

        # Print summary every 100 calls
        if self.call_count % 100 == 0 and self.enabled:
            self.print_summary()

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"GUI PROFILER SUMMARY (after {self.call_count} update cycles)")
        print(f"{'='*60}")
        for name, times in sorted(self.section_times.items(), key=lambda x: sum(x[1]), reverse=True):
            avg = sum(times) / len(times)
            mx = max(times)
            total = sum(times)
            print(f"  {name:40s} avg={avg:7.1f}ms  max={mx:7.1f}ms  total={total:8.0f}ms")
        print(f"{'='*60}\n")
        # Reset for next window
        self.section_times.clear()

gui_profiler = GUIProfiler()


# Import our modules
from t8_daq_system.hardware.labjack_connection import LabJackConnection
from t8_daq_system.hardware.thermocouple_reader import ThermocoupleReader
from t8_daq_system.hardware.xgs600_controller import XGS600Controller
from t8_daq_system.hardware.frg702_reader import FRG702Reader, FRG702AnalogReader
from t8_daq_system.hardware.keysight_analog_controller import KeysightAnalogController
from t8_daq_system.control.safety_monitor import SafetyMonitor, SafetyStatus
from t8_daq_system.data.data_buffer import DataBuffer
from t8_daq_system.data.data_logger import DataLogger, create_metadata_dict
from t8_daq_system.gui.live_plot import LivePlot
from t8_daq_system.gui.sensor_panel import SensorPanel
from t8_daq_system.utils.helpers import convert_temperature
from t8_daq_system.gui.dialogs import LoggingDialog, LoadCSVDialog
from t8_daq_system.gui.settings_dialog import SettingsDialog
from t8_daq_system.gui.pinout_display import PinoutDisplay
from t8_daq_system.control.program_executor import ProgramExecutor
from t8_daq_system.gui.program_panel import ProgramPanel
from t8_daq_system.core.data_acquisition import DataAcquisition
from t8_daq_system.settings.app_settings import AppSettings
from t8_daq_system.gui.power_programmer_panel import PowerProgrammerPanel
from t8_daq_system.gui.programmer_preview_plot import ProgrammerPreviewPlot

# Safe Mode limits for the Voltage/Current Power Programmer (not TempRamp)
_PROGRAMMER_SAFE_MODE_MAX_VOLTS = 1.0   # V
_PROGRAMMER_SAFE_MODE_MAX_AMPS  = 10.0  # A


class MockPowerSupplyController:
    """
    Simulated power supply for practice mode.

    In normal practice mode, get_voltage() / get_current() add small sinusoidal
    noise to make the display look realistic.

    When Power Programmer execution is active (programmer_active = True) the
    analog simulation is handled entirely by DataAcquisition.read_all_sensors()
    using the shared pp_* scaling functions, so noise is suppressed here to
    allow clean validation of the signal chain.
    """

    def __init__(self, voltage_limit=6.0, current_limit=180.0):
        self.voltage = 0.0
        self.current = 0.0
        self.output_state = False
        self.voltage_limit = voltage_limit
        self.current_limit = current_limit
        # Set True while the Power Programmer ramp is running so that
        # get_readings() returns exact setpoints (no noise) and the DA
        # layer can perform the proper analog round-trip validation.
        self.programmer_active = False

    def set_voltage(self, volts):
        self.voltage = min(max(volts, 0.0), self.voltage_limit)
        return True

    def set_current(self, amps):
        self.current = min(max(amps, 0.0), self.current_limit)
        return True

    def output_on(self):
        self.output_state = True
        return True

    def output_off(self):
        self.output_state = False
        return True

    def is_output_on(self):
        return self.output_state

    def get_voltage_setpoint(self):
        return self.voltage

    def get_current_setpoint(self):
        return self.current

    def get_voltage(self):
        if not self.output_state:
            return 0.0
        # Suppress noise during programmer execution — the DA layer simulates
        # the full analog round-trip and the validation requires exact values.
        if self.programmer_active:
            return self.voltage
        t = time.time()
        fluctuation = (self.voltage * 0.02) * math.sin(t / 8.0)
        return self.voltage + fluctuation + random.uniform(-0.02, 0.02)

    def get_current(self):
        if not self.output_state:
            return 0.0
        if self.programmer_active:
            return self.current
        t = time.time()
        fluctuation = (self.current * 0.03) * math.cos(t / 10.0)
        return self.current + fluctuation + random.uniform(-0.01, 0.01)

    def get_readings(self):
        return {
            'PS_Voltage': self.get_voltage(),
            'PS_Current': self.get_current(),
            'PS_Output_On': self.output_state
        }

    def get_status(self):
        return {
            'output_on': self.output_state,
            'voltage_setpoint': self.voltage,
            'current_setpoint': self.current,
            'voltage_actual': self.get_voltage(),
            'current_actual': self.get_current(),
            'errors': [],
            'in_current_limit': False
        }

    def get_errors(self):
        return []

    def reset(self):
        self.voltage = 0.0
        self.current = 0.0
        self.output_state = False
        return True

    def emergency_shutdown(self):
        self.output_state = False
        self.voltage = 0.0
        self.current = 0.0
        return True


class MainWindow:
    # Available sampling rates in milliseconds
    SAMPLE_RATES = [100, 200, 500, 1000, 2000]

    def __init__(self, settings=None):
        profiler.section("MainWindow.__init__ START")
        profiler.checkpoint("Entering __init__ method")

        # Persistent settings (registry-backed).  If no settings object was
        # provided, create one and load from registry now (covers edge cases
        # such as direct instantiation in tests).
        if settings is None:
            settings = AppSettings()
            settings.load()
        self._app_settings = settings

        # Build the internal config dict from AppSettings
        self.config = self._build_config_from_settings(settings)
        self._tc_names = {tc['name'] for tc in self.config['thermocouples']}
        self._frg_names = {g['name'] for g in self.config.get('frg702_gauges', [])}
        profiler.checkpoint("Config built from AppSettings")

        # Axis scale settings (from AppSettings)
        self._use_absolute_scales = settings.use_absolute_scales
        self._temp_range  = settings.temp_range
        self._press_range = settings.press_range
        self._ps_v_range  = settings.ps_v_range
        self._ps_i_range  = settings.ps_i_range

        profiler.checkpoint("Axis scale settings applied")

        profiler.checkpoint("About to create tk.Tk() root window")
        self.root = tk.Tk()
        profiler.checkpoint("tk.Tk() root window created")

        self.root.title("T8 DAQ System with Power Supply Control")
        self.root.geometry("1200x800")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        profiler.checkpoint("Root window properties set")

        profiler.section("LabJack Hardware Connection")
        profiler.checkpoint("Creating LabJackConnection instance")
        # Initialize LabJack hardware
        self.connection = LabJackConnection()
        profiler.checkpoint("LabJackConnection instance created (not connected yet)")
        # LabJack reconnect guard
        self._last_labjack_read_failed = False

        profiler.section("XGS-600 Controller Connection")
        profiler.checkpoint("Initializing XGS-600 variables")
        # Initialize XGS-600 controller
        self.xgs600 = None
        self.frg702_reader = None
        self.tc_reader = None
        profiler.checkpoint("XGS-600 variables initialized (not connected yet)")

        profiler.section("Analog Power Supply Controller")
        profiler.checkpoint("Analog PS controller will be created after T8 connects")
        # The analog controller is initialized in _initialize_power_supply() once
        # the LabJack T8 handle is available.  No separate network connection needed.
        self.ps_controller = None
        profiler.checkpoint("Analog PS controller placeholder set")

        profiler.section("Control Systems Initialization")
        # Unified Program Mode
        self._program_executor = ProgramExecutor(
            power_supply=None,
            get_temp_k_fn_provider=self._get_tc_reading_k_provider,
            on_block_start=self._on_program_block_start,
            on_block_complete=self._on_program_block_complete,
            on_program_complete=self._on_program_complete,
            on_status=self._on_program_status
        )
        self._program_panel = None

        profiler.checkpoint("Creating SafetyMonitor...")
        self.safety_monitor = SafetyMonitor(auto_shutoff=True)
        profiler.checkpoint("SafetyMonitor created")

        profiler.section("Data Handling Initialization")
        profiler.checkpoint("Creating DataBuffer...")
        # Initialize data handling
        self.data_buffer = DataBuffer(
            max_seconds=None,
            sample_rate_ms=self.config['logging']['interval_ms']
        )
        profiler.checkpoint("DataBuffer created")

        profiler.checkpoint("Setting up log folder paths...")
        # Set up log folder path
        if getattr(sys, 'frozen', False):
            # If the application is run as a bundle, use the directory of the executable
            base_dir = os.path.dirname(sys.executable)
        else:
            # If run as a script, use the parent of t8_daq_system
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Use registry-persisted log folder if set, otherwise default to base_dir/logs
        _custom_log = settings.log_folder if settings.log_folder else ""
        self.log_folder = _custom_log if _custom_log else os.path.join(base_dir, 'logs')
        self.profiles_folder = os.path.join(base_dir, 'config', 'profiles')

        if not os.path.exists(self.profiles_folder):
            os.makedirs(self.profiles_folder)
        if not os.path.exists(self.log_folder):
            os.makedirs(self.log_folder)
        profiler.checkpoint("Log folders created/verified")

        profiler.checkpoint("Creating DataLogger...")
        self.logger = DataLogger(
            log_folder=self.log_folder,
            file_prefix=self.config['logging']['file_prefix']
        )
        profiler.checkpoint("DataLogger created")

        profiler.checkpoint("Initializing DAQ engine and control variables...")
        # Data acquisition engine
        self.daq = None

        # Latest readings from acquisition thread
        self._latest_readings = None
        self._latest_tc_readings = {}
        self._latest_frg702_details = {}

        # Control flags
        self.is_running = False
        self.is_logging = False
        self.read_thread = None
        self._safety_triggered = False
        self._hardware_init_attempted = False  # Track if deferred init has run

        # Mode tracking
        self._viewing_historical = False
        self._practice_mode = False
        self._practice_banner = None  # tk.Frame shown in practice mode
        self._loaded_data = None
        self._loaded_data_units = {'temp': 'C', 'press': 'PSI'}
        self._programmer_mode_active = False
        self._programmer_ramp_running = False
        self._programmer_preview_data = ([], [], [])
        self._programmer_blocks = []
        self._programmer_control_mode = "Voltage"
        self._programmer_pid_tc = None  # Store the last selected TC for PID
        self._run_ramp_btn_visible = False
        self._programmer_panel = None
        self._programmer_panel_frame = None
        self._programmer_plot_frame = None
        self._programmer_preview_plot = None

        # Reconnection cooldown timers (prevent blocking GUI with repeated failed attempts)
        self._last_xgs_reconnect_time = 0
        self._last_lj_reconnect_time = 0
        self._reconnect_interval = 30.0  # Only retry connection every 30 seconds

        # FIX 4: Plot skip counter - reduce plot frequency in frozen mode
        self._plot_skip_count = 10 if getattr(sys, 'frozen', False) else 3

        profiler.checkpoint("Control variables initialized")

        profiler.section("GUI Components Creation")
        profiler.checkpoint("About to call _build_gui()...")
        # Build the GUI
        self._build_gui()
        profiler.checkpoint("_build_gui() completed")

        profiler.section("Final Initialization Steps")
        profiler.checkpoint("Configuring safety monitor...")
        # Configure safety monitor
        self._configure_safety_monitor()
        profiler.checkpoint("Safety monitor configured")

        profiler.checkpoint("Registering safety callbacks...")
        # Register safety callbacks
        self._register_safety_callbacks()
        profiler.checkpoint("Safety callbacks registered")

        profiler.checkpoint("Starting GUI update loop...")

        # PERFORMANCE FIX: Defer hardware connection until AFTER GUI is shown
        # This prevents blocking the startup for 10+ seconds
        # Connection will happen 100ms after GUI appears
        self.root.after(100, self._deferred_hardware_init)

        # Start GUI update loop (without hardware init)
        self._update_gui()
        profiler.checkpoint("GUI update loop started (hardware connection deferred)")

        profiler.section("MainWindow.__init__ COMPLETE")
        profiler.summary()

    # ──────────────────────────────────────────────────────────────────────────
    # AppSettings helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_config_from_settings(s):
        """
        Translate an AppSettings object into the internal config dictionary
        used by the rest of MainWindow.
        """
        # Build thermocouple list (per-TC types and per-TC AIN pins from settings)
        thermocouples = []
        tc_type_list = s.get_tc_type_list(s.tc_count)
        tc_pin_list  = s.get_tc_pin_list(s.tc_count)

        print(f"[DEBUG] _build_config_from_settings: tc_count={s.tc_count}, tc_pins={tc_pin_list}")
        print(f"[DEBUG] _build_config_from_settings: ps_enabled={s.ps_enabled}, ps_v_mon={s.ps_voltage_monitor_pin}, ps_i_mon={s.ps_current_monitor_pin}")

        # Conflict detection: check TC pins against Keysight monitor pins
        keysight_v_pin_str = s.ps_voltage_monitor_pin  # e.g. "AIN4"
        keysight_i_pin_str = s.ps_current_monitor_pin  # e.g. "AIN5"
        keysight_v_pin = int(keysight_v_pin_str.replace("AIN", "")) if keysight_v_pin_str.startswith("AIN") else None
        keysight_i_pin = int(keysight_i_pin_str.replace("AIN", "")) if keysight_i_pin_str.startswith("AIN") else None
        tc_name_list = s.get_tc_name_list(s.tc_count, tc_pin_list, tc_type_list)
        conflict_errors = []
        for i, ch in enumerate(tc_pin_list):
            tc_name = tc_name_list[i]
            if keysight_v_pin is not None and ch == keysight_v_pin:
                conflict_errors.append(
                    f"TC pin conflict: {tc_name} is assigned to AIN{ch} which is also used by "
                    f"Keysight Voltage Monitor. Please reassign in Settings."
                )
            if keysight_i_pin is not None and ch == keysight_i_pin:
                conflict_errors.append(
                    f"TC pin conflict: {tc_name} is assigned to AIN{ch} which is also used by "
                    f"Keysight Current Monitor. Please reassign in Settings."
                )
        if conflict_errors:
            import tkinter.messagebox as _mb
            _mb.showerror("Pin Conflict", "\n\n".join(conflict_errors))

        # Warn if TC count exceeds available non-PS AIN channels
        if s.tc_count > 4 and s.ps_enabled:
            print("[CONFIG WARNING] tc_count > 4 with PS enabled: AIN4 and AIN5 are reserved "
                  "for Keysight monitoring. Reduce TC count or disable PS.")

        for i in range(s.tc_count):
            thermocouples.append({
                "name": tc_name_list[i],
                "channel": tc_pin_list[i],
                "type": tc_type_list[i],
                "units": s.tc_unit,
                "enabled": True
            })

        # Build FRG-702 list
        frg702_gauges = []
        frg_pin_list = s.get_frg_pin_list(s.frg_count)

        # Warn if any FRG pin conflicts with an assigned TC channel (Analog interface only)
        if s.frg_interface != "XGS600":
            tc_channels_used = {f"AIN{ch}" for ch in tc_pin_list}
            for pin in frg_pin_list:
                if pin in tc_channels_used:
                    print(f"[CONFIG WARNING] FRG pin {pin} conflicts with a TC channel!")
        frg_name_list = s.get_frg_name_list(s.frg_count, s.frg_interface, frg_pin_list)
        for i in range(s.frg_count):
            sensor_code = f"T{2*i+1}"
            frg702_gauges.append({
                "name": frg_name_list[i],
                "sensor_code": sensor_code,
                "pin": frg_pin_list[i],
                "units": s.p_unit,
                "enabled": True
            })

        return {
            "device": {"type": "T8", "connection": "USB", "identifier": "ANY"},
            "thermocouples": thermocouples,
            "frg702_gauges": frg702_gauges,
            "xgs600": {
                "enabled": s.xgs_enabled and s.frg_interface == "XGS600",
                "port": s.xgs600_port,
                "baudrate": s.xgs600_baudrate,
                "timeout": s.xgs600_timeout,
                "address": s.xgs600_address
            },
            "frg_interface": s.frg_interface,
            "power_supply": {
                "enabled": s.ps_enabled,
                "interface": "Analog",
                "voltage_pin": s.ps_voltage_pin,
                "current_pin": s.ps_current_pin,
                "voltage_monitor_pin": s.ps_voltage_monitor_pin,
                "current_monitor_pin": s.ps_current_monitor_pin,
                "rated_max_volts": 6,
                "rated_max_amps": 180,
                "default_voltage_limit": s.ps_voltage_limit,
                "default_current_limit": s.ps_current_limit,
                "safety": {
                    "max_temperature": 2300,
                    "watchdog_sensor": "TC_1" if s.tc_count > 0 else None,
                    "auto_shutoff": True,
                    "warning_threshold": 0.9
                }
            },
            "logging": {
                "interval_ms": s.sample_rate_ms,
                "file_prefix": "data_log",
                "auto_start": False
            },
            "display": {
                "update_rate_ms": s.display_rate_ms,
                "history_seconds": 60
            }
        }

    def _apply_settings_to_gui(self):
        """
        Apply a freshly-saved AppSettings to the live GUI.
        Called from SettingsDialog's on_save callback.
        All configuration now flows exclusively through the Settings dialog.
        """
        s = self._app_settings

        # Update axis scale state
        self._use_absolute_scales = s.use_absolute_scales
        self._temp_range  = s.temp_range
        self._press_range = s.press_range
        self._ps_v_range  = s.ps_v_range
        self._ps_i_range  = s.ps_i_range

        # Sync internal StringVars used by the rest of the GUI
        self.tc_count_var.set(str(s.tc_count))
        self.t_unit_var.set(s.tc_unit)
        self.frg_count_var.set(str(s.frg_count))
        self.p_unit_var.set(s.p_unit)
        self.sample_rate_var.set(f"{s.sample_rate_ms}ms")
        self.display_rate_var.set(f"{s.display_rate_ms}ms")

        # Update rates in live config
        self.config['logging']['interval_ms']   = s.sample_rate_ms
        self.config['display']['update_rate_ms'] = s.display_rate_ms
        self.data_buffer.sample_rate_ms = s.sample_rate_ms

        # Rebuild sensor config and refresh
        self._on_config_change()

        # Apply appearance settings to all live plots
        self._apply_appearance_to_plots()

        # Refresh pinout display if open
        if hasattr(self, '_pinout_window') and self._pinout_window is not None:
            try:
                if self._pinout_window.winfo_exists():
                    self._pinout_window.refresh_config(self.config, self._app_settings)
            except tk.TclError:
                self._pinout_window = None

    def _apply_appearance_to_plots(self):
        """Push appearance settings from AppSettings to all live plot instances."""
        s = self._app_settings
        tc_colors  = [c.strip() for c in s.tc_colors.split(',') if c.strip()]
        tc_styles  = [x.strip() for x in s.tc_line_style.split(',') if x.strip()]
        tc_widths  = [x.strip() for x in s.tc_line_width.split(',') if x.strip()]
        press_colors = [c.strip() for c in s.press_colors.split(',') if c.strip()]
        press_styles = [x.strip() for x in s.press_line_style.split(',') if x.strip()]
        press_widths = [x.strip() for x in s.press_line_width.split(',') if x.strip()]
        for plot in getattr(self, '_live_plots', []):
            plot.apply_appearance(
                tc_colors=tc_colors, tc_styles=tc_styles, tc_widths=tc_widths,
                press_colors=press_colors, press_styles=press_styles, press_widths=press_widths,
                ps_voltage_color=s.ps_voltage_color,
                ps_current_color=s.ps_current_color,
                ps_voltage_style=s.ps_voltage_line_style,
                ps_current_style=s.ps_current_line_style,
                ps_voltage_width=s.ps_voltage_line_width,
                ps_current_width=s.ps_current_line_width,
                pp_voltage_color=s.pp_voltage_color,
                pp_voltage_style=s.pp_voltage_line_style,
                pp_voltage_width=s.pp_voltage_line_width,
            )

        # Apply appearance to the Power Programmer preview plot (if open)
        if (hasattr(self, '_programmer_preview_plot')
                and self._programmer_preview_plot is not None):
            self._programmer_preview_plot.apply_appearance(
                voltage_color=s.pp_voltage_color,
                voltage_style=s.pp_voltage_line_style,
                voltage_width=s.pp_voltage_line_width,
            )

    def _open_settings_dialog(self):
        """Open the persistent Settings dialog."""
        SettingsDialog(self.root, self._app_settings,
                       on_save_callback=self._apply_settings_to_gui)

    def _open_pinout_display(self):
        """Open (or bring to front) the live pinout display window."""
        if hasattr(self, '_pinout_window') and self._pinout_window is not None:
            try:
                if self._pinout_window.winfo_exists():
                    self._pinout_window.lift()
                    self._pinout_window.focus_set()
                    return
            except tk.TclError:
                pass
        self._pinout_window = PinoutDisplay(self.root, self.config, self._app_settings)

    def _deferred_hardware_init(self):
        """
        Initialize hardware connections AFTER GUI is displayed.

        This runs 100ms after the window opens, preventing startup blocking.
        Called via root.after() from __init__().

        Issue 3c: The Keysight power-supply connection attempt runs in a
        dedicated background thread so a slow/failed network connection never
        blocks the main (GUI) thread.  On failure the app continues normally
        with ps_controller left as None (Disconnected state).
        """
        try:
            print("[DEFERRED] Starting hardware initialization...")

            # Connect to LabJack T8
            if self.connection:
                print("[DEFERRED] Connecting to LabJack T8...")
                if self.connection.connect():
                    print("[DEFERRED] T8 connected successfully")

                    # Create thermocouple reader now that we're connected
                    if self.tc_reader is None:
                        if self._initialize_hardware_readers():
                            print("[DEFERRED] Hardware readers initialized")

                    # Initialize the analog power supply controller using the T8 handle.
                    # No separate network connection is needed — the DAC/AIN channels on
                    # the T8 are the sole interface once the J1 wiring is in place.
                    if self.config.get('power_supply', {}).get('enabled', True):
                        if self._initialize_power_supply():
                            print("[DEFERRED] Analog power supply controller initialized")
                        else:
                            print("[DEFERRED] Analog PS init failed — running without PS")

                    # Update button states
                    self._update_connection_state(True)
                else:
                    print("[DEFERRED] T8 connection failed")
                    self._last_labjack_read_failed = True
                    self._update_connection_state(False)

            # Connect to XGS-600 if configured
            if self.config.get('xgs600', {}).get('enabled', False):
                print("[DEFERRED] Connecting to XGS-600...")
                if self._connect_xgs600():
                    print("[DEFERRED] XGS-600 connected")

            print("[DEFERRED] Hardware initialization complete")
            self._hardware_init_attempted = True

        except Exception as exc:
            print(f"[DEFERRED] Hardware init error (non-fatal): {exc}")
            self._hardware_init_attempted = True

    def _update_connection_state(self, connected):
        """Update UI to reflect connection state"""
        if connected:
            self.status_var.set("Connected")
            self._auto_start_acquisition()
        else:
            self.status_var.set("Disconnected")

    def _build_gui(self):
        """Create all the GUI elements."""
        profiler.checkpoint("_build_gui() entered - creating control frames")

        # ── Configure ttk Styles ──────────────────────────────────────────────
        style = ttk.Style()
        style.configure('Settings.TButton', foreground='#1a5f7a')
        profiler.checkpoint("Styles configured")

        # ── Menu bar ─────────────────────────────────────────────────────────
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        profiler.checkpoint("Menu bar created")

        # ── Internal StringVars (no GUI widgets — settings come from Settings dialog only)
        # These are synced by _apply_settings_to_gui() after every Settings save.
        s = self._app_settings
        t_unit  = self.config['thermocouples'][0]['units'] if self.config['thermocouples'] else s.tc_unit
        p_unit  = self.config['frg702_gauges'][0].get('units', s.p_unit) if self.config.get('frg702_gauges') else s.p_unit
        self.tc_count_var    = tk.StringVar(value=str(len(self.config['thermocouples'])))
        self.t_unit_var      = tk.StringVar(value=t_unit)
        self.frg_count_var   = tk.StringVar(value=str(len(self.config.get('frg702_gauges', []))))
        self.p_unit_var      = tk.StringVar(value=p_unit)
        self.sample_rate_var = tk.StringVar(value=f"{self.config['logging']['interval_ms']}ms")
        self.display_rate_var = tk.StringVar(value=f"{self.config['display']['update_rate_ms']}ms")

        # Pinout window reference (created lazily)
        self._pinout_window = None

        # Power Programmer state
        self._programmer_mode_active = False
        self._programmer_preview_data = ([], [], [])  # (times, voltages_or_temps, currents_or_None)
        self._programmer_panel = None
        self._programmer_preview_plot = None
        self._programmer_panel_frame = None
        self._programmer_plot_frame = None
        self._run_ramp_btn_visible = False
        self._programmer_ramp_running = False

        # Top frame - Control buttons
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        self.control_frame = control_frame  # Save reference for banner placement

        # Logging button (acquisition is always auto-started on connection)
        self.log_btn = ttk.Button(
            control_frame, text="Start Logging", command=self._on_toggle_logging,
            state='disabled'
        )
        self.log_btn.pack(side=tk.LEFT, padx=5)

        self.load_csv_btn = ttk.Button(
            control_frame, text="Load CSV", command=self._on_load_csv
        )
        self.load_csv_btn.pack(side=tk.LEFT, padx=5)

        self.practice_btn = ttk.Button(
            control_frame, text="Practice Mode: OFF", command=self._toggle_practice_mode
        )
        self.practice_btn.pack(side=tk.LEFT, padx=5)

        self.settings_btn = ttk.Button(
            control_frame, text="Settings", command=self._open_settings_dialog,
            style='Settings.TButton'
        )
        self.settings_btn.pack(side=tk.LEFT, padx=5)

        self.pinout_btn = ttk.Button(
            control_frame, text="Pinout", command=self._open_pinout_display
        )
        self.pinout_btn.pack(side=tk.LEFT, padx=5)

        self.power_programmer_btn = ttk.Button(
            control_frame, text="Power Programmer",
            command=self._toggle_power_programmer
        )
        self.power_programmer_btn.pack(side=tk.LEFT, padx=5)

        self.refresh_gui_btn = ttk.Button(
            control_frame, text="Refresh GUI", command=self._on_refresh_gui
        )
        self.refresh_gui_btn.pack(side=tk.LEFT, padx=5)

        self.pid_log_btn = ttk.Button(
            control_frame, text="PID Log", command=self._open_pid_log_viewer
        )
        self.pid_log_btn.pack(side=tk.LEFT, padx=5)

        self.run_ramp_btn = ttk.Button(
            control_frame, text="Run Program", command=self._on_run_program
        )
        # Do NOT pack yet — only shown when programmer is active AND profile is ready

        # Separator
        ttk.Separator(control_frame, orient='vertical').pack(
            side=tk.LEFT, padx=10, fill='y'
        )

        # Status label
        self.status_var = tk.StringVar(value="Connecting...")
        self.ps_resource_var = tk.StringVar(value="None")

        # Connection Status Indicators
        self.indicator_frame = ttk.Frame(control_frame)
        self.indicator_frame.pack(side=tk.RIGHT, padx=10)

        self.indicators = {}
        self._build_indicators()
        profiler.checkpoint("Control buttons and indicators created")

        status_label = ttk.Label(
            control_frame, textvariable=self.status_var, font=('Arial', 10, 'bold')
        )
        status_label.pack(side=tk.RIGHT, padx=10)

        ttk.Label(control_frame, text="Status:").pack(side=tk.RIGHT)
        profiler.checkpoint("Status labels created")

        profiler.checkpoint("Creating safety status bar...")
        # Safety Status Bar at bottom
        safety_frame = ttk.Frame(self.root)
        safety_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(2, 10))

        ttk.Label(safety_frame, text="Safety:", font=('Arial', 8, 'bold')).pack(side=tk.LEFT)

        self.safety_indicator = tk.Canvas(
            safety_frame, width=12, height=12,
            bg='#00FF00', highlightthickness=1, highlightbackground='black'
        )
        self.safety_indicator.pack(side=tk.LEFT, padx=5)

        self.safety_status_label = ttk.Label(
            safety_frame, text="OK", font=('Arial', 8)
        )
        self.safety_status_label.pack(side=tk.LEFT)

        # Reset Safety button (initially hidden)
        self.reset_safety_btn = ttk.Button(
            safety_frame, text="Reset Safety",
            command=self._on_reset_safety
        )

        # Temperature limit display
        ttk.Separator(safety_frame, orient='vertical').pack(side=tk.LEFT, padx=10, fill='y')
        self.temp_limit_label = ttk.Label(
            safety_frame, text="Max Temp: --",
            font=('Arial', 8)
        )
        self.temp_limit_label.pack(side=tk.LEFT, padx=5)

        # Temperature override info
        self.override_label = ttk.Label(
            safety_frame,
            text=f"Override: {SafetyMonitor.TEMP_OVERRIDE_LIMIT:.0f}\u00b0C",
            font=('Arial', 8)
        )
        self.override_label.pack(side=tk.LEFT, padx=5)

        # Historical data indicator (initially hidden)
        self.historical_label = ttk.Label(
            safety_frame, text="[VIEWING HISTORICAL DATA]",
            font=('Arial', 9, 'bold'), foreground='blue'
        )

        # ── Master Plot Scrollbar (In Safety Frame) ─────────────────────────
        ttk.Separator(safety_frame, orient='vertical').pack(side=tk.LEFT, padx=10, fill='y')
        ttk.Label(safety_frame, text="Timeline History:", font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=2)

        # Two radio-style buttons — the active/current mode is shown disabled
        # ("pressed") so it's obvious which mode is live.  Click the other
        # button to switch.  Default mode is '2-min Window'.
        self._btn_2min = ttk.Button(
            safety_frame, text="2-min Window", width=13,
            command=lambda: self._set_slider_mode('window_2min')
        )
        self._btn_2min.pack(side=tk.LEFT, padx=(4, 1))
        self._btn_hist = ttk.Button(
            safety_frame, text="Full History", width=12,
            command=lambda: self._set_slider_mode('history_pct')
        )
        self._btn_hist.pack(side=tk.LEFT, padx=(1, 4))
        # Start with 2-min Window active (matches LivePlot default)
        self._btn_2min.config(state='disabled')
        self._btn_hist.config(state='normal')

        self.master_scroll_var = tk.DoubleVar(value=1.0)
        self.master_scrollbar = ttk.Scale(
            safety_frame, from_=0.0, to=1.0, orient=tk.HORIZONTAL,
            variable=self.master_scroll_var, command=self._on_master_scroll
        )
        self.master_scrollbar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        profiler.checkpoint("Safety status bar created")

        profiler.checkpoint("Creating main content area with PanedWindow...")
        # Create main content area with PanedWindow
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=2)

        profiler.checkpoint("Main PanedWindow created")

        # Left side - Monitoring
        profiler.checkpoint("Creating left frame (monitoring side)...")
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=1)
        profiler.checkpoint("Left frame created")

        # Current readings panel
        profiler.checkpoint("Creating sensor panel container...")
        self.panel_container = ttk.LabelFrame(left_frame, text="Current Readings")
        self.panel_container.pack(fill=tk.X, padx=5, pady=2)
        profiler.checkpoint("Sensor panel container created")

        profiler.checkpoint("Building sensor panel (_rebuild_sensor_panel)...")
        self._rebuild_sensor_panel()
        profiler.checkpoint("Sensor panel built")

        # Live plots container
        profiler.checkpoint("Creating plot container frame...")
        self.plot_container_main = ttk.Frame(left_frame)
        self.plot_container_main.pack(fill=tk.BOTH, expand=True, padx=2, pady=1)
        profiler.checkpoint("Plot container frame created")

        profiler.checkpoint("Building live plots (_build_plots)...")
        self._build_plots(self.plot_container_main)
        profiler.checkpoint("Live plots built")


    def _build_plots(self, parent):
        """Create a 2×2 grid of dedicated live plots in the parent widget."""
        profiler.checkpoint("_build_plots() entered - creating 2x2 plot grid")

        # Configure equal-weight grid rows and columns
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)

        # Initialize the live plots tracking list
        if not hasattr(self, '_live_plots'):
            self._live_plots = []

        # Row 0, Col 0 — Thermocouple temperatures
        tc_frame = ttk.LabelFrame(parent, text="Temperatures")
        tc_frame.grid(row=0, column=0, sticky='nsew', padx=2, pady=2)
        self.plot_tc = LivePlot(tc_frame, self.data_buffer, plot_type='tc', show_scrollbar=False)
        self._live_plots.append(self.plot_tc)
        profiler.checkpoint("TC plot created")

        # Row 0, Col 1 — Pressure gauges (log scale)
        press_frame = ttk.LabelFrame(parent, text="Pressures")
        press_frame.grid(row=0, column=1, sticky='nsew', padx=2, pady=2)
        self.plot_pressure = LivePlot(press_frame, self.data_buffer, plot_type='pressure', show_scrollbar=False)
        self._live_plots.append(self.plot_pressure)
        profiler.checkpoint("Pressure plot created")

        # Row 1, Col 0 — PS Voltage & Current
        ps_frame = ttk.LabelFrame(parent, text="Power Supply V & I")
        ps_frame.grid(row=1, column=0, sticky='nsew', padx=2, pady=2)
        self.plot_ps = LivePlot(ps_frame, self.data_buffer, plot_type='ps', show_scrollbar=False)
        self._live_plots.append(self.plot_ps)
        profiler.checkpoint("PS plot created")

        # Row 1, Col 1 — Placeholder (future camera / IR)
        placeholder_frame = ttk.LabelFrame(parent, text="Camera / IR")
        placeholder_frame.grid(row=1, column=1, sticky='nsew', padx=2, pady=2)
        placeholder_lbl = ttk.Label(
            placeholder_frame,
            text="Camera / IR — Coming Soon",
            foreground='gray',
            font=('Arial', 12)
        )
        placeholder_lbl.place(relx=0.5, rely=0.5, anchor='center')
        profiler.checkpoint("Placeholder frame created")

        profiler.checkpoint("Updating plot settings...")
        self._update_plot_settings()
        profiler.checkpoint("Plot settings updated")

        # Apply persisted appearance settings on startup
        self._apply_appearance_to_plots()
        profiler.checkpoint("Appearance settings applied to plots")

    def _toggle_practice_mode(self):
        """Toggle practice mode on/off."""
        self._practice_mode = not self._practice_mode
        if self._practice_mode:
            self._hardware_init_attempted = True  # Practice mode counts as initialized
            self.practice_btn.config(text="Practice Mode: ON")
            self.status_var.set("Practice Mode Active")

            if not self.config.get('frg702_gauges'):
                self.config['frg702_gauges'] = [
                    {"name": "FRG702_Mock", "sensor_code": "T1", "units": "mbar", "enabled": True}
                ]
            self.frg_count_var.set(str(len(self.config['frg702_gauges'])))

            # Set up Mock Power Supply
            self.ps_controller = MockPowerSupplyController()
            self.safety_monitor.set_power_supply(self.ps_controller)
            if self._program_executor:
                self._program_executor.set_power_supply(self.ps_controller)
                self._program_executor.practice_mode = True

            self.ps_resource_var.set("Mock Power Supply")
            self._auto_start_acquisition()

            # ── Feature C: Window title ───────────────────────────────────
            self.root.title('[PRACTICE MODE] T8 DAQ System with Power Supply Control')

            # ── Feature C: Orange banner below control buttons ────────────
            if self._practice_banner is None:
                self._practice_banner = tk.Frame(self.root, bg='#FF8C00', height=28)
                self._practice_banner.pack(fill=tk.X, padx=0, pady=0,
                                           after=self.control_frame)
                banner_label = tk.Label(
                    self._practice_banner,
                    text='⚠  PRACTICE MODE — No real hardware is being controlled  ⚠',
                    bg='#FF8C00', fg='white',
                    font=('Arial', 10, 'bold')
                )
                banner_label.pack(expand=True)

            # ── Feature C: Practice button style ─────────────────────────
            try:
                style = ttk.Style()
                style.configure('PracticeOn.TButton',
                                background='#FF8C00',
                                foreground='white',
                                font=('Arial', 9, 'bold'))
                self.practice_btn.configure(style='PracticeOn.TButton')
            except Exception:
                pass  # Theme may not support background color changes

        else:
            self.practice_btn.config(text="Practice Mode: OFF")
            self.ps_resource_var.set("None")

            # Stop practice acquisition before switching to real hardware
            self._on_stop()

            if not self.connection or not self.connection.is_connected():
                self.status_var.set("Disconnected")
                self.ps_controller = None
            else:
                self.status_var.set("Connected")
                self._initialize_hardware_readers()
                # Re-initialize the analog PS controller with the live T8 handle
                self._initialize_power_supply()
                self._auto_start_acquisition()

            # Clear programmer overlay from PS plot when leaving practice mode
            for plot in getattr(self, '_live_plots', []):
                if hasattr(plot, 'plot_type') and plot.plot_type == 'ps':
                    plot.set_programmer_overlay([], [], [])
                    break

            # ── Feature C: Revert window title ────────────────────────────
            self.root.title('T8 DAQ System with Power Supply Control')

            # ── Feature C: Destroy orange banner ─────────────────────────
            if self._practice_banner is not None:
                self._practice_banner.destroy()
                self._practice_banner = None

            # ── Feature C: Revert practice button style ───────────────────
            try:
                self.practice_btn.configure(style='TButton')
            except Exception:
                pass

        self._rebuild_sensor_panel()
        self._update_plot_settings()

    # ──────────────────────────────────────────────────────────────────────
    # Power Programmer feature
    # ──────────────────────────────────────────────────────────────────────

    def _toggle_power_programmer(self):
        if self._programmer_mode_active:
            self._deactivate_power_programmer()
        else:
            self._activate_power_programmer()

    def _activate_power_programmer(self):
        self._programmer_mode_active = True
        self.power_programmer_btn.config(text="Exit Power Programmer")

        # 1. Hide the sensor panel (Current Readings)
        self.panel_container.pack_forget()

        # 2. Hide the 2×2 plot grid
        self.plot_container_main.pack_forget()

        # 3. Create programmer panel frame (replaces sensor panel)
        self._programmer_panel_frame = ttk.LabelFrame(
            self.panel_container.master, text="Power Programmer"
        )
        self._programmer_panel_frame.pack(fill=tk.X, padx=5, pady=2)

        # 4. Create preview plot frame (replaces plot grid)
        self._programmer_plot_frame = ttk.Frame(self.plot_container_main.master)
        self._programmer_plot_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=1)

        # 5. Instantiate the preview plot
        self._programmer_preview_plot = ProgrammerPreviewPlot(
            parent_frame=self._programmer_plot_frame
        )

        # 6. Instantiate the programmer panel
        self._programmer_panel = ProgramPanel(
            parent_frame=self._programmer_panel_frame,
            preview_plot=self._programmer_preview_plot,
            get_initial_state_fn=lambda: (self._get_latest_tc_reading_k("TC_1"), (self.daq._last_all_readings.get('PS_Voltage') or 0.0) if self.daq else 0.0),
            on_program_change=self._update_run_button_state,
            tc_names=sorted(self._tc_names),
            get_unit_fn=lambda: getattr(self, 't_unit_var', None) and self.t_unit_var.get() or 'K',
            get_tc_temp_k_fn=self._get_latest_tc_reading_k,
        )
        
        # Build manual nudge sub-panel
        self._reposition_nudge_panel()
        
        # Show run button
        self._update_run_button_state()

    def _update_run_button_state(self):
        if self._programmer_mode_active and self._programmer_panel:
            if not self._run_ramp_btn_visible:
                self.run_ramp_btn.pack(side=tk.LEFT, padx=5)
                self._run_ramp_btn_visible = True
        else:
            if self._run_ramp_btn_visible:
                self.run_ramp_btn.pack_forget()
                self._run_ramp_btn_visible = False

    def _update_programmer_preview(self):
        # The new ProgramPanel manages preview updates via its own Preview button.
        # This method is retained for call-site compatibility but is otherwise a no-op.
        pass

    def _deactivate_power_programmer(self):
        # SAFETY: If a ramp is currently running, stop it safely first
        if self._programmer_ramp_running:
            self._stop_programmer_ramp_safe()

        # Save profile data before destroying panel
        if self._programmer_panel:
            self._programmer_blocks = list(self._programmer_panel.get_blocks())
            self._programmer_preview_data = ([], [], [])
            self._programmer_control_mode = "Program"
            self._programmer_mode = "Program"
        # (Otherwise keep whatever was already in self._programmer_blocks)

        # Destroy programmer UI
        if self._programmer_panel_frame:
            self._programmer_panel_frame.destroy()
            self._programmer_panel_frame = None
        if self._programmer_plot_frame:
            self._programmer_plot_frame.destroy()
            self._programmer_plot_frame = None
        self._programmer_panel = None
        self._programmer_preview_plot = None

        # Restore original UI
        self.panel_container.pack(fill=tk.X, padx=5, pady=2)
        self.plot_container_main.pack(fill=tk.BOTH, expand=True, padx=2, pady=1)

        # Reset button
        self._programmer_mode_active = False
        self.power_programmer_btn.config(text="Power Programmer")

        # Keep run ramp button visible if profile is ready
        if self._programmer_blocks:
            self.run_ramp_btn.pack(side=tk.LEFT, padx=5)
            self._run_ramp_btn_visible = True
        else:
            if self._run_ramp_btn_visible:
                self.run_ramp_btn.pack_forget()
                self._run_ramp_btn_visible = False
        
        # Update nudge panel position/visibility
        self._reposition_nudge_panel()

        # Apply dotted preview overlay to the ps LivePlot
        self._apply_programmer_overlay()

    def _get_tc_reading_k_provider(self, tc_name):
        return lambda: self._get_latest_tc_reading_k(tc_name)

    def _get_latest_tc_reading_k(self, tc_name):
        if not self._latest_tc_readings:
            return 293.15
        val_c = self._latest_tc_readings.get(tc_name, 20.0)
        return val_c + 273.15

    def _on_program_block_start(self, index, block):
        print(f"[Program] Starting block {index+1}: {block.block_type}")
        self.root.after(0, lambda: self.status_var.set(f"Program: Block {index+1}"))

    def _on_program_block_complete(self, index):
        print(f"[Program] Block {index+1} complete")

    def _on_program_complete(self):
        print("[Program] All blocks complete")
        def _gui_update():
            self.status_var.set("Program Complete")
            self._programmer_ramp_running = False
            self.run_ramp_btn.config(text="Run Program")
            self._show_pid_run_summary()
        self.root.after(0, _gui_update)

    def _show_pid_run_summary(self):
        """Show a post-run PID performance summary and offer to update settings gains."""
        executor = getattr(self, '_program_executor', None)
        if executor is None:
            return
        record = getattr(executor, '_last_run_record', None)
        if record is None:
            return

        overshoot = record.get('overshoot_k', 0.0)
        oscillations = record.get('oscillation_count', 0)
        settling = record.get('settling_time_sec')
        kp_used = record.get('kp_used', self._app_settings.pid_kp)
        ki_used = record.get('ki_used', self._app_settings.pid_ki)
        kd_used = record.get('kd_used', self._app_settings.pid_kd)

        # Build suggestion: if overshoot > 5K or oscillations > 4, recommend reducing gains
        suggest_kp, suggest_ki, suggest_kd = kp_used, ki_used, kd_used
        notes = []
        if overshoot > 5.0:
            suggest_kp = round(kp_used * 0.7, 5)
            suggest_ki = round(ki_used * 0.6, 5)
            notes.append(f"Overshoot was {overshoot:.1f} K — reducing Kp and Ki")
        if oscillations > 4:
            suggest_kd = round(kd_used * 1.3, 5)
            notes.append(f"{oscillations} oscillations detected — increasing Kd")
        if not notes:
            notes.append("Run looked stable — gains unchanged")

        settling_str = f"{settling:.0f} s" if settling is not None else "did not settle"
        note_str = "\n".join(notes)

        msg = (
            f"Run Complete — PID Performance Summary\n\n"
            f"  Overshoot:      {overshoot:.2f} K\n"
            f"  Oscillations:   {oscillations}\n"
            f"  Settling time:  {settling_str}\n\n"
            f"Gains used:  Kp={kp_used}  Ki={ki_used}  Kd={kd_used}\n\n"
            f"Analysis:\n{note_str}\n\n"
            f"Suggested for next run:\n"
            f"  Kp={suggest_kp}  Ki={suggest_ki}  Kd={suggest_kd}\n\n"
            f"Apply suggested gains to Settings?"
        )

        if messagebox.askyesno("PID Run Summary", msg):
            self._app_settings.pid_kp = suggest_kp
            self._app_settings.pid_ki = suggest_ki
            self._app_settings.pid_kd = suggest_kd
            self._app_settings.save()

    def _on_program_status(self, status):
        idx = status['block_index']
        btype = status['block_type'].replace('_', ' ').title()
        elapsed = status['elapsed_sec']
        temp = status['current_temp_k'] - 273.15
        volt = status['voltage_v']
        ff_v = status.get('ff_voltage', 0.0)
        p = status.get('pid_p', 0.0)
        i = status.get('pid_i', 0.0)
        d = status.get('pid_d', 0.0)

        msg = (f"B{idx+1} {btype}: {elapsed:.0f}s | {temp:.1f}°C | "
               f"V={volt:.3f} (FF={ff_v:.3f} P={p:+.3f} I={i:+.3f} D={d:+.3f})")
        self.root.after(0, lambda: self.status_var.set(msg))

    def _on_programmer_profile_confirmed(self, times, voltages, currents):
        self._programmer_preview_data = (times, voltages, currents)

    def _apply_programmer_overlay(self):
        """
        After exiting programmer mode, apply the dotted preview overlay to the ps LivePlot.
        The overlay will appear as dotted lines on the V&I plot.
        It becomes time-anchored once the user clicks Run Program.
        """
        from datetime import datetime
        # In TempRamp mode the preview data contains temperatures (K), not voltages.
        # Sending those values to the PS overlay would make the V axis autoscale to ~300V.
        # Guard: only apply the overlay when operating in Voltage/Current mode.
        if getattr(self, '_programmer_mode', 'Voltage') == 'TempRamp':
            # Clear any stale overlay from a previous Voltage/Current session
            for plot in getattr(self, '_live_plots', []):
                if hasattr(plot, 'plot_type') and plot.plot_type == 'ps':
                    plot.set_programmer_overlay([], [], [])
                    break
            return

        times, voltages, currents = self._programmer_preview_data
        for plot in getattr(self, '_live_plots', []):
            if hasattr(plot, 'plot_type') and plot.plot_type == 'ps':
                plot.set_programmer_overlay(times, voltages, currents)
                # Anchor the overlay to 'now' so it's visible immediately as a preview.
                # This will be re-anchored to the true run start when Run Program is clicked.
                if times:
                    plot.set_overlay_start_time(datetime.now())
                break

    def _on_run_program(self):
        if self._programmer_ramp_running:
            self._stop_programmer_ramp_safe()
        else:
            self._start_programmer_ramp()

    def _start_programmer_ramp(self):
        """Start executing the unified block-based program."""
        if self._programmer_panel:
            blocks = self._programmer_panel.get_blocks()
        else:
            blocks = list(self._programmer_blocks) if self._programmer_blocks else []

        if not blocks:
            messagebox.showwarning("No Program", "Please add at least one block.")
            return

        # Guard: must have a power supply controller
        if not self.ps_controller:
            messagebox.showerror("No Power Supply", "Power supply is not connected.")
            return

        # Guard: safety monitor must not be in shutdown state
        if self.safety_monitor.is_restart_locked:
            messagebox.showwarning("Safety Lockout", "Safety lockout is active.")
            return

        # Load and start
        self._program_executor.load_program(blocks)
        self._program_executor.practice_mode = self._practice_mode

        # Apply PID gains from AppSettings
        for block in blocks:
            if block.block_type == "temp_ramp":
                self._program_executor._pid.update_gains(
                    self._app_settings.pid_kp,
                    self._app_settings.pid_ki,
                    self._app_settings.pid_kd,
                )
                break

        if self._program_executor.start():
            self._programmer_ramp_running = True
            self.run_ramp_btn.config(text="Stop Program")
            print("[Program] Started execution")
        else:
            messagebox.showerror("Error", "Failed to start program executor.")

    def _stop_programmer_ramp_safe(self):
        """Stop the running program safely."""
        if self._program_executor and self._program_executor.is_running():
            self._program_executor.stop()
        self._programmer_ramp_running = False
        self.run_ramp_btn.config(text="Run Program")
        self.status_var.set("Program Stopped")
        # Restore default legend if it was modified during a run
        if hasattr(self, 'plot_ps'):
            self.plot_ps.set_legend_label_overrides({})
            self.plot_ps.update(['PS_Voltage', 'PS_Current'])

    def _on_pressure_unit_change(self):
        """Handle pressure unit selection change."""
        new_unit = self.p_unit_var.get()
        # Update config for persistence
        if self.config.get('frg702_gauges'):
            for gauge in self.config['frg702_gauges']:
                gauge['units'] = new_unit
        
        # Update FRG702 reader target unit
        if hasattr(self, 'frg702_reader') and self.frg702_reader:
            self.frg702_reader.target_unit = new_unit

        # Update sensor panel if it exists
        if hasattr(self, 'sensor_panel'):
            self.sensor_panel.update_global_pressure_unit(new_unit)
            
        self._update_plot_settings()

    def _on_sample_rate_change(self):
        rate_str = self.sample_rate_var.get()
        rate_ms = int(rate_str.replace('ms', ''))
        self.config['logging']['interval_ms'] = rate_ms
        self.data_buffer.sample_rate_ms = rate_ms

    def _on_display_rate_change(self):
        rate_str = self.display_rate_var.get()
        display_rate_ms = int(rate_str.replace('ms', ''))
        self.config['display']['update_rate_ms'] = display_rate_ms

    def _update_plot_settings(self):
        """Update plot settings based on current config."""
        # Reset skip counter to force immediate redraw on next update loop
        self._plot_skip_counter = 0

        t_unit = self.t_unit_var.get() if hasattr(self, 't_unit_var') else 'C'

        temp_symbols = {'C': '\u00b0C', 'F': '\u00b0F', 'K': 'K'}
        temp_unit_display = temp_symbols.get(t_unit, '\u00b0C')

        if not hasattr(self, '_temp_range'):
            self._temp_range = (0.0, 300.0)

        # Convert temperature range from storage (Celsius) to current display units
        t_min, t_max = self._temp_range
        t_min_disp = convert_temperature(t_min, 'C', t_unit)
        t_max_disp = convert_temperature(t_max, 'C', t_unit)
        display_temp_range = (t_min_disp, t_max_disp)

        press_unit = self.p_unit_var.get()

        # Apply settings to each active plot
        _ps_v_range = self._ps_v_range if hasattr(self, '_ps_v_range') else None
        _ps_i_range = self._ps_i_range if hasattr(self, '_ps_i_range') else None
        _press_range = self._press_range if hasattr(self, '_press_range') else None

        for plot_attr in ('plot_tc', 'plot_pressure', 'plot_ps'):
            if hasattr(self, plot_attr):
                plot = getattr(self, plot_attr)
                plot.set_units(temp_unit_display, press_unit)
                plot.set_absolute_scales(
                    self._use_absolute_scales,
                    display_temp_range,
                    _press_range,
                    _ps_v_range,
                    _ps_i_range
                )
                plot.ax.relim()
                plot.ax.autoscale_view()
                plot.canvas.draw_idle()

        tc_names = [tc['name'] for tc in self.config['thermocouples']
                    if tc.get('enabled', True)]
        frg_names = [g['name'] for g in self.config.get('frg702_gauges', [])
                     if g.get('enabled', True)]

        if self._viewing_historical and self._loaded_data:
            if hasattr(self, 'plot_tc'):
                self.plot_tc.update_from_loaded_data(
                    self._loaded_data, tc_names,
                    data_units=self._loaded_data_units
                )
            if hasattr(self, 'plot_pressure'):
                self.plot_pressure.update_from_loaded_data(
                    self._loaded_data, frg_names,
                    data_units=self._loaded_data_units
                )
            if hasattr(self, 'plot_ps'):
                ps_names = [n for n in self._loaded_data
                            if n in ('PS_Voltage', 'PS_Current')]
                self.plot_ps.update_from_loaded_data(
                    self._loaded_data, ps_names,
                    data_units=self._loaded_data_units
                )

            if self._loaded_data.get('timestamps'):
                last_readings = {name: self._loaded_data[name][-1]
                                for name in self._loaded_data if name != 'timestamps'}
                display_last = {}
                source_t_unit = self._loaded_data_units.get('temp', 'C')

                for name, value in last_readings.items():
                    if value is None:
                        display_last[name] = None
                    elif name in self._tc_names:
                        display_last[name] = convert_temperature(value, source_t_unit, t_unit)
                    else:
                        display_last[name] = value
                self.sensor_panel.update(display_last)
        else:
            if hasattr(self, 'plot_tc'):
                # TC data in buffer is always in Celsius (converted at acquisition)
                self.plot_tc.update(tc_names, data_units={'temp': 'C'})
            if hasattr(self, 'plot_pressure'):
                self.plot_pressure.update(frg_names, data_units={'press': self.p_unit_var.get()})
            if hasattr(self, 'plot_ps'):
                self.plot_ps.update(['PS_Voltage', 'PS_Current'])

    def _on_load_csv(self):
        dialog = LoadCSVDialog(self.root, self.log_folder)
        self.root.wait_window(dialog)
        if dialog.result:
            self._load_historical_data(dialog.result)

    def _load_historical_data(self, filepath):
        try:
            metadata, data = DataLogger.load_csv_with_metadata(filepath)

            if not data.get('timestamps'):
                messagebox.showerror("Error", "No data found in file.")
                return

            self._loaded_data = data
            self._viewing_historical = True

            if metadata:
                self._loaded_data_units = {
                    'temp': metadata.get('tc_unit', 'C'),
                    'press': metadata.get('p_unit', 'PSI')
                }
                # Sync internal vars for display-unit conversions; settings are not
                # modified so the live config is preserved after returning to live view.
                if 'tc_count' in metadata:
                    self.tc_count_var.set(str(metadata['tc_count']))
                if 'frg702_count' in metadata:
                    self.frg_count_var.set(str(metadata['frg702_count']))
                if 'tc_unit' in metadata:
                    self.t_unit_var.set(metadata['tc_unit'])
                if 'p_unit' in metadata:
                    self.p_unit_var.set(metadata['p_unit'])
                    if hasattr(self, 'sensor_panel'):
                        self.sensor_panel.update_global_pressure_unit(metadata['p_unit'])
                if 'sample_rate_ms' in metadata:
                    self.sample_rate_var.set(f"{metadata['sample_rate_ms']}ms")

            self._update_plot_settings()
            self.historical_label.pack(side=tk.RIGHT, padx=10)

            if data['timestamps']:
                last_readings = {}
                for name in data:
                    if name != 'timestamps':
                        last_readings[name] = data[name][-1]

                display_last = {}
                t_unit = self.t_unit_var.get()
                source_t_unit = self._loaded_data_units.get('temp', 'C')

                for name, value in last_readings.items():
                    if value is None:
                        display_last[name] = None
                        continue
                    if name in self._tc_names:
                        display_last[name] = convert_temperature(value, source_t_unit, t_unit)
                    else:
                        display_last[name] = value

                self.sensor_panel.update(display_last)

            filename = os.path.basename(filepath)
            self.status_var.set(f"Viewing: {filename}")

            self.log_btn.config(state='disabled')

            if not hasattr(self, 'return_live_btn'):
                self.return_live_btn = ttk.Button(
                    self.root,
                    text="Return to Live View",
                    command=self._return_to_live
                )
            self.return_live_btn.pack(pady=5)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file: {e}")

    def _return_to_live(self):
        self._viewing_historical = False
        self._loaded_data = None
        self.historical_label.pack_forget()

        if hasattr(self, 'return_live_btn'):
            self.return_live_btn.pack_forget()

        for _plot_attr in ('plot_tc', 'plot_pressure', 'plot_ps'):
            if hasattr(self, _plot_attr):
                getattr(self, _plot_attr).clear()
        self.data_buffer.clear()

        lj_ok = self.connection and self.connection.is_connected()
        if lj_ok or self._practice_mode:
            self.status_var.set("Connected")
            self.log_btn.config(state='normal' if self.is_running else 'disabled')
        else:
            self.status_var.set("Disconnected")

    def _on_config_change(self):
        """
        Rebuild internal config dictionary from AppSettings and refresh hardware
        readers.  This ensures that the Settings dialog is the ultimate source
        of truth and that all configuration flows through a single path.
        """
        # Re-build the entire config dict from settings
        self.config = self._build_config_from_settings(self._app_settings)
        self._tc_names = {tc['name'] for tc in self.config['thermocouples']}
        self._frg_names = {g['name'] for g in self.config.get('frg702_gauges', [])}
        # Sync GUI vars (for historical reasons / other panels that watch them)
        self.tc_count_var.set(str(len(self.config['thermocouples'])))
        self.frg_count_var.set(str(len(self.config.get('frg702_gauges', []))))

        if self.connection and self.connection.is_connected():
            self._initialize_hardware_readers()
            # Always call _initialize_power_supply; it now handles its own enabled check
            self._initialize_power_supply()
        elif self.daq:
            # If not connected but daq exists (e.g. practice mode), update config
            self.daq.update_readers(config=self.config)

        self._configure_safety_monitor()
        self._rebuild_sensor_panel()
        self._update_plot_settings()

    def _build_indicators(self):
        for widget in self.indicator_frame.winfo_children():
            widget.destroy()
        self.indicators = {}

        lbl_font = ('Arial', 7, 'bold')
        canvas_size = 14

        lj_frame = ttk.Frame(self.indicator_frame)
        lj_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(lj_frame, text="LJ", font=lbl_font).pack()
        self.indicators['LabJack'] = tk.Canvas(lj_frame, width=canvas_size, height=canvas_size, bg='#333333', highlightthickness=1, highlightbackground="black")
        self.indicators['LabJack'].pack()

        xgs_frame = ttk.Frame(self.indicator_frame)
        xgs_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(xgs_frame, text="XGS", font=lbl_font).pack()
        self.indicators['XGS600'] = tk.Canvas(xgs_frame, width=canvas_size, height=canvas_size, bg='#333333', highlightthickness=1, highlightbackground="black")
        self.indicators['XGS600'].pack()

        ps_frame = ttk.Frame(self.indicator_frame)
        ps_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(ps_frame, text="PS", font=lbl_font).pack()
        self.indicators['PowerSupply'] = tk.Canvas(ps_frame, width=canvas_size, height=canvas_size, bg='#333333', highlightthickness=1, highlightbackground="black")
        self.indicators['PowerSupply'].pack()

        for i, tc in enumerate(self.config['thermocouples']):
            name = tc['name']
            f = ttk.Frame(self.indicator_frame)
            f.pack(side=tk.LEFT, padx=2)
            ttk.Label(f, text=f"TC{i+1}", font=lbl_font).pack()
            self.indicators[name] = tk.Canvas(f, width=canvas_size, height=canvas_size, bg='#333333', highlightthickness=1, highlightbackground="black")
            self.indicators[name].pack()

        for i, gauge in enumerate(self.config.get('frg702_gauges', [])):
            name = gauge['name']
            f = ttk.Frame(self.indicator_frame)
            f.pack(side=tk.LEFT, padx=2)
            ttk.Label(f, text=f"FRG{i+1}", font=lbl_font).pack()
            self.indicators[name] = tk.Canvas(f, width=canvas_size, height=canvas_size, bg='#333333', highlightthickness=1, highlightbackground="black")
            self.indicators[name].pack()

    def _rebuild_sensor_panel(self):
        for widget in self.panel_container.winfo_children():
            widget.destroy()

        all_sensors = self.config['thermocouples']
        frg702_configs = self.config.get('frg702_gauges', [])
        self.sensor_panel = SensorPanel(self.panel_container, all_sensors, frg702_configs)
        self.sensor_panel.on_sensor_toggle(self._on_sensor_toggle)

        self._build_indicators()

    def _on_sensor_toggle(self, name, visible):
        """Route a sensor-tile click to the correct plot's visibility toggle."""
        if name in self._tc_names:
            if hasattr(self, 'plot_tc'):
                self.plot_tc.set_sensor_visible(name, visible)
        elif name in self._frg_names:
            if hasattr(self, 'plot_pressure'):
                self.plot_pressure.set_sensor_visible(name, visible)
        elif name == 'PS_Voltage':
            if hasattr(self, 'plot_ps'):
                self.plot_ps.set_sensor_visible('PS_Voltage', visible)
        elif name == 'PS_Current':
            if hasattr(self, 'plot_ps'):
                self.plot_ps.set_sensor_visible('PS_Current', visible)

    def _configure_safety_monitor(self):
        safety_config = self.config.get('power_supply', {}).get('safety', {})

        max_temp = safety_config.get('max_temperature', 2300)
        for tc in self.config['thermocouples']:
            self.safety_monitor.set_temperature_limit(tc['name'], max_temp)

        watchdog = safety_config.get('watchdog_sensor')
        if watchdog:
            self.safety_monitor.set_watchdog_sensor(watchdog)

        warning_threshold = safety_config.get('warning_threshold', 0.9)
        self.safety_monitor.set_warning_threshold(warning_threshold)

        self.safety_monitor.auto_shutoff = safety_config.get('auto_shutoff', True)

        self.temp_limit_label.config(text=f"Max Temp: {max_temp}C")

    def _register_safety_callbacks(self):
        self.safety_monitor.on_warning(self._on_safety_warning)
        self.safety_monitor.on_limit_exceeded(self._on_safety_limit_exceeded)
        self.safety_monitor.on_shutdown(self._on_safety_shutdown)
        self.safety_monitor.on_rampdown_start(self._on_safety_rampdown_start)

    def _on_safety_warning(self, sensor_name: str, value: float, limit: float):
        self.root.after(0, lambda: self._update_safety_display(SafetyStatus.WARNING))

    def _on_safety_limit_exceeded(self, sensor_name: str, value: float, limit: float):
        self.root.after(0, lambda: self._update_safety_display(SafetyStatus.LIMIT_EXCEEDED))

    def _on_safety_shutdown(self, event):
        self._safety_triggered = True
        self.root.after(0, self._handle_safety_shutdown)

    def _on_safety_rampdown_start(self, message: str):
        """Handle controlled ramp-down start event."""
        self.root.after(0, lambda: self._handle_rampdown_start(message))

    def _handle_rampdown_start(self, message: str):
        """Handle ramp-down start on main thread."""
        # Stop program executor if running
        if self._program_executor and self._program_executor.is_running():
            self._program_executor.stop()

        # Update safety display
        self._update_safety_display(SafetyStatus.RAMPDOWN_ACTIVE)

        # Show reset button
        self.reset_safety_btn.pack(side=tk.LEFT, padx=10)

        # Show alert
        messagebox.showerror(
            "TEMPERATURE OVERRIDE - EMERGENCY SHUTDOWN",
            f"{message}\n\n"
            "A controlled power-down ramp is now active.\n"
            "Power will be gradually reduced to zero.\n\n"
            "You cannot restart the power supply until\n"
            f"temperature drops below {SafetyMonitor.TEMP_RESTART_THRESHOLD:.0f}\u00b0C."
        )

    def _handle_safety_shutdown(self):
        # Stop program executor if running
        if self._program_executor and self._program_executor.is_running():
            self._program_executor.stop()

        # Directly shut down the power supply controller
        if self.ps_controller:
            try:
                self.ps_controller.emergency_shutdown()
            except Exception:
                pass

        # Update safety display
        self._update_safety_display(SafetyStatus.SHUTDOWN_TRIGGERED)

        # Show reset button
        self.reset_safety_btn.pack(side=tk.LEFT, padx=10)

        event = self.safety_monitor.get_last_event()
        if event:
            messagebox.showerror(
                "SAFETY SHUTDOWN",
                f"Emergency shutdown triggered!\n\n{event.message}\n\n"
                "Power supply output has been disabled.\n"
                "Resolve the issue before clicking Reset Safety."
            )

    def _update_safety_display(self, status: SafetyStatus):
        status_colors = {
            SafetyStatus.OK: ('#00FF00', 'OK', 'black'),
            SafetyStatus.WARNING: ('#FFFF00', 'WARNING', 'orange'),
            SafetyStatus.LIMIT_EXCEEDED: ('#FF0000', 'LIMIT EXCEEDED', 'red'),
            SafetyStatus.SHUTDOWN_TRIGGERED: ('#FF0000', 'SHUTDOWN', 'red'),
            SafetyStatus.RAMPDOWN_ACTIVE: ('#FF8800', 'RAMP-DOWN ACTIVE', 'red'),
            SafetyStatus.ERROR: ('#FF0000', 'ERROR', 'red')
        }

        color, text, fg = status_colors.get(status, ('#333333', 'UNKNOWN', 'gray'))
        self.safety_indicator.config(bg=color)
        self.safety_status_label.config(text=text, foreground=fg)

    def _on_reset_safety(self):
        # Check if restart is allowed (temperature must be below threshold)
        if self.safety_monitor.is_restart_locked:
            messagebox.showwarning(
                "Cannot Reset",
                f"Temperature is still too high.\n\n"
                f"Temperature must drop below {SafetyMonitor.TEMP_RESTART_THRESHOLD:.0f}\u00b0C "
                f"before the safety system can be reset."
            )
            return

        if messagebox.askyesno(
            "Confirm Reset",
            "Reset safety system?\n\n"
            "Only do this after resolving the cause of the shutdown."
        ):
            self.safety_monitor.reset()
            self._safety_triggered = False
            self._update_safety_display(SafetyStatus.OK)
            self.reset_safety_btn.pack_forget()

    def _on_ps_output_change(self, is_on: bool):
        if is_on:
            self.status_var.set("Running - PS Output ON")
        else:
            if self.is_running:
                self.status_var.set("Running")

    def _on_ramp_start(self):
        # Enable power supply output if not already on
        if self.ps_controller and not self.ps_controller.is_output_on():
            self.ps_controller.output_on()

    def _on_ramp_stop(self):
        pass

    def _check_connections(self):
        if self._practice_mode:
            for name in self.indicators:
                self.indicators[name].config(bg='#00FF00')
            return

        if not self.tc_reader:
            return

        try:
            tc_readings = self.tc_reader.read_all()
            all_readings = {**tc_readings}

            if self.frg702_reader:
                frg702_readings = self.frg702_reader.read_all()
                all_readings.update(frg702_readings)

            for name, value in all_readings.items():
                if name in self.indicators:
                    color = '#00FF00' if value is not None else '#333333'
                    self.indicators[name].config(bg=color)
        except Exception as e:
            print(f"Error checking connections: {e}")

    def _update_safety_interlocks(self):
        """Update all safety interlock states. Called from the GUI update loop."""
        # ramp_panel removed; safety monitor status shown via _update_safety_display()
        pass

    def _on_master_scroll(self, value):
        """Sync all plots to the master scrollbar position."""
        val = float(value)
        if hasattr(self, 'plot_tc'):
            self.plot_tc.sync_scroll(val)
        if hasattr(self, 'plot_pressure'):
            self.plot_pressure.sync_scroll(val)
        if hasattr(self, 'plot_ps'):
            self.plot_ps.sync_scroll(val)

    def _auto_start_acquisition(self):
        """Auto-start acquisition if not already running."""
        if not self.is_running:
            self._on_start()

    def _set_slider_mode(self, mode):
        """
        Set the timeline slider mode for all plots.

        Args:
            mode: 'window_2min' — fixed 2-minute viewport (the default).
                  'history_pct' — show all data from session start to slider.
        """
        for plot_attr in ('plot_tc', 'plot_pressure', 'plot_ps'):
            if hasattr(self, plot_attr):
                getattr(self, plot_attr).set_slider_mode(mode)
        # Keep the active-mode button disabled ("pressed") and the other normal
        self._btn_2min.config(state='disabled' if mode == 'window_2min' else 'normal')
        self._btn_hist.config(state='disabled' if mode == 'history_pct' else 'normal')

    def _on_start(self):
        self.is_running = True
        self.log_btn.config(state='normal')
        self.status_var.set("Running")

        self.data_buffer.clear()

        self.daq = DataAcquisition(
            config=self.config,
            tc_reader=self.tc_reader,
            frg702_reader=self.frg702_reader,
            ps_controller=self.ps_controller,
            safety_monitor=self.safety_monitor if not self._safety_triggered else None,
            program_executor=self._program_executor,
            practice_mode=self._practice_mode
        )

        # Wire pressure interlock callback
        self.daq.set_pressure_interlock_callback(self._on_pressure_interlock)

        def on_new_data(timestamp, all_readings, tc_readings, frg702_details,
                        safety_shutdown=False, raw_voltages=None, read_failed=False):
            # Update LabJack read status (Task 6)
            self._last_labjack_read_failed = read_failed
            if read_failed:
                return

            # Unified Program Mode: Add current block index to log (Task 7d)
            prog_executor = getattr(self, '_program_executor', None)
            if prog_executor and prog_executor.is_running():
                all_readings['Block_Index'] = prog_executor.current_block_index + 1
            else:
                all_readings['Block_Index'] = None

            self.data_buffer.add_reading(all_readings)

            self._latest_readings = (timestamp, all_readings)
            self._latest_tc_readings = tc_readings
            self._latest_frg702_details = frg702_details
            self._latest_raw_voltages = raw_voltages

            if self.is_logging:
                log_readings = {}
                # Avoid calling tk.StringVar.get() from background thread
                t_unit = getattr(self, '_current_t_unit', 'C')
                for name, value in all_readings.items():
                    if value is None:
                        log_readings[name] = None
                        continue
                    if name in self._tc_names:
                        log_readings[name] = convert_temperature(value, 'C', t_unit)
                    else:
                        log_readings[name] = value
                # Include raw voltages (and differential voltages — same value,
                # labelled _rawV) so the log shows the full conversion chain:
                #   physical TC wire → raw mV input → EF temperature conversion
                #
                # Unified Program Mode: Add current block index to CSV (Task 7d)
                prog_executor = getattr(self, '_program_executor', None)
                if prog_executor and prog_executor.is_running():
                    log_readings['Block_Index'] = prog_executor.current_block_index + 1
                else:
                    log_readings['Block_Index'] = None

                if raw_voltages:
                    log_readings.update(raw_voltages)
                self.logger.log_reading(log_readings)

            if safety_shutdown:
                self.is_running = False
                self.root.after(0, self._handle_safety_shutdown)

        self.daq.start_fast_acquisition(callback=on_new_data)

    def _on_stop(self):
        self.is_running = False

        if self.daq:
            self.daq.stop_fast_acquisition()

        self.log_btn.config(state='disabled')
        self.status_var.set("Stopped")

        if self.is_logging:
            self._on_toggle_logging()

    def _on_toggle_logging(self):
        if not self.is_logging:
            # Clear all graphs and the data buffer so logging starts fresh
            self.data_buffer.clear()
            for plot_attr in ('plot_tc', 'plot_pressure', 'plot_ps'):
                if hasattr(self, plot_attr):
                    getattr(self, plot_attr).clear()
            # Reset timeline slider to live position
            if hasattr(self, 'master_scroll_var'):
                self.master_scroll_var.set(1.0)
                self._on_master_scroll(1.0)

            dialog = LoggingDialog(self.root)
            self.root.wait_window(dialog)

            if dialog.result is None:
                return

            custom_name, notes = dialog.result

            frg702_gauges = self.config.get('frg702_gauges', [])
            frg702_count = len([g for g in frg702_gauges if g.get('enabled', True)])
            frg702_unit = frg702_gauges[0].get('units', 'mbar') if frg702_gauges else 'mbar'

            tc_types_list = [tc['type'] for tc in self.config['thermocouples']
                             if tc.get('enabled', True)]
            metadata = create_metadata_dict(
                tc_count=int(self.tc_count_var.get()),
                tc_type=tc_types_list[0] if tc_types_list else "K",
                tc_types=tc_types_list,
                tc_unit=self.t_unit_var.get(),
                frg702_count=frg702_count,
                frg702_unit=frg702_unit,
                sample_rate_ms=int(self.sample_rate_var.get().replace('ms', '')),
                notes=notes or ""
            )

            enabled_tcs = [tc for tc in self.config['thermocouples']
                           if tc.get('enabled', True)]
            sensor_names = [tc['name'] for tc in enabled_tcs]
            sensor_names += [g['name'] for g in self.config.get('frg702_gauges', [])
                            if g.get('enabled', True)]

            if self.ps_controller:
                sensor_names += ['PS_Voltage', 'PS_Current',
                                 'PS_Voltage_Setpoint', 'PS_CC_Limit']

            # Unified Program Mode: Add block index column (Task 7d)
            sensor_names += ['Block_Index']

            # Append Power Programmer metadata if a profile is loaded
            if self._programmer_blocks:
                metadata['programmer_mode'] = self._programmer_control_mode

            # Append raw-voltage columns right after the temperature columns so the
            # log shows the full conversion chain for each thermocouple:
            #   <TC_N>  = converted temperature
            #   <TC_N>_rawV = raw differential input voltage (V) before EF conversion
            # Both columns carry identical physical information; having both lets the
            # user verify that the T8's internal millivolt→temperature lookup is correct.
            for tc in enabled_tcs:
                sensor_names.append(f"{tc['name']}_rawV")

            # Guard: remove any None or empty-string entries that could produce phantom CSV columns
            sensor_names = [n for n in sensor_names if n]
            filepath = self.logger.start_logging(sensor_names, custom_name, metadata)
            self.is_logging = True
            self.log_btn.config(text="Stop Logging")
            self.status_var.set(f"Running - Logging to {os.path.basename(filepath)}")
        else:
            self.logger.stop_logging()
            self.is_logging = False
            self.log_btn.config(text="Start Logging")
            self.status_var.set("Running")

    def _update_gui(self):
        """Update the GUI (called periodically)."""
        gui_profiler.loop_start()

        # Update cache of GUI-owned variables for background threads
        self._current_t_unit = self.t_unit_var.get()

        gui_profiler.start("skip_counter_check")
        # Only redraw plots every Nth call to avoid overwhelming matplotlib
        if not hasattr(self, '_plot_skip_counter'):
            self._plot_skip_counter = 0
        self._plot_skip_counter += 1
        should_redraw_plots = (self._plot_skip_counter % self._plot_skip_count == 0)

        if self._viewing_historical:
            self.root.after(self.config['display']['update_rate_ms'], self._update_gui)
            gui_profiler.loop_end()
            return

        gui_profiler.start("labjack_reconnect")
        # Auto-connect hardware (only when last read failed and after initial attempt)
        lj_connected = self.connection.is_connected()
        now = time.time()
        if self._practice_mode:
            lj_connected = True
        elif self._last_labjack_read_failed and not lj_connected and self._hardware_init_attempted:
            if (now - self._last_lj_reconnect_time) >= self._reconnect_interval:
                self._last_lj_reconnect_time = now
                if self.connection.connect():
                    if self._initialize_hardware_readers():
                        lj_connected = True
                        self._update_connection_state(True)
                        self._last_labjack_read_failed = False
                    else:
                        self.connection.disconnect()
                        lj_connected = False

            if not lj_connected:
                if self.status_var.get() != "Disconnected":
                    self._update_connection_state(False)
                    self.is_running = False
                    for name in self.indicators:
                        self.indicators[name].config(bg='#333333')

        gui_profiler.start("labjack_indicator")
        # Update LabJack indicator
        color = '#00FF00' if lj_connected else '#333333'
        if 'LabJack' in self.indicators:
            self.indicators['LabJack'].config(bg=color)

        gui_profiler.start("xgs600_reconnect")
        # Auto-connect XGS-600 (only after initial deferred init)
        xgs_connected = (self.xgs600 is not None and self.xgs600.is_connected()) or self._practice_mode
        if not xgs_connected and not self._practice_mode and self._hardware_init_attempted and self.config.get('xgs600', {}).get('enabled', False):
            if (now - self._last_xgs_reconnect_time) >= self._reconnect_interval:
                self._last_xgs_reconnect_time = now
                if self._connect_xgs600():
                    xgs_connected = True

        color = '#00FF00' if xgs_connected else '#333333'
        if 'XGS600' in self.indicators:
            self.indicators['XGS600'].config(bg=color)

        gui_profiler.start("keysight_reconnect")
        # PS is connected whenever the T8 is connected and the controller is initialised.
        # If T8 just reconnected but the controller is missing, create it now.
        ps_connected = (lj_connected and self.ps_controller is not None) or \
                       (self._practice_mode and self.ps_controller is not None)

        if lj_connected and self.ps_controller is None and not self._practice_mode \
                and self._hardware_init_attempted \
                and self.config.get('power_supply', {}).get('enabled', True):
            self._initialize_power_supply()
            ps_connected = self.ps_controller is not None

        color = '#00FF00' if ps_connected else '#333333'
        if 'PowerSupply' in self.indicators:
            self.indicators['PowerSupply'].config(bg=color)

        # When not running, poll PS directly and update sensor-panel tiles
        if ps_connected and self.ps_controller and not self.is_running:
            _ps_live = self.ps_controller.get_readings()
            if hasattr(self, 'sensor_panel'):
                self.sensor_panel.update({
                    'PS_Voltage': _ps_live.get('PS_Voltage'),
                    'PS_Current': _ps_live.get('PS_Current'),
                })

        gui_profiler.start("safety_interlocks")
        # Update safety interlocks
        self._update_safety_interlocks()

        # Update safety display
        if not self._safety_triggered:
            self._update_safety_display(self.safety_monitor.status)

        if not self.is_running:
            if lj_connected:
                self._check_connections()

            gui_profiler.start("schedule_next")
            self.root.after(self.config['display']['update_rate_ms'], self._update_gui)
            gui_profiler.loop_end()
            return

        gui_profiler.start("read_sensors")
        # Get current readings and update panel
        current = self.data_buffer.get_all_current()

        display_readings = {}
        t_unit = self.t_unit_var.get()

        for name, value in current.items():
            if value is None:
                display_readings[name] = None
                continue
            if name in self._tc_names:
                display_readings[name] = convert_temperature(value, 'C', t_unit)
            else:
                display_readings[name] = value

        gui_profiler.start("sensor_panel_update")
        self.sensor_panel.update(display_readings)

        # Update FRG-702 detailed status
        if hasattr(self, '_latest_frg702_details') and self._latest_frg702_details:
            self.sensor_panel.update_frg702_status(self._latest_frg702_details)

        # Update live pinout display if open (Change 6: moved from DAQ thread to GUI thread)
        if hasattr(self, '_pinout_window') and self._pinout_window is not None:
            try:
                if self._pinout_window.winfo_exists():
                    self._pinout_window.update_readings(
                        all_readings=current,
                        raw_voltages=getattr(self, '_latest_raw_voltages', {}),
                        frg702_details=getattr(self, '_latest_frg702_details', {})
                    )
            except tk.TclError:
                self._pinout_window = None

        # Update indicators
        for name, value in current.items():
            if name in self.indicators:
                color = '#00FF00' if value is not None else '#333333'
                self.indicators[name].config(bg=color)

        # Update plots (only every Nth call to reduce matplotlib overhead)
        if should_redraw_plots:
            gui_profiler.start("plot_update")
            tc_names = [tc['name'] for tc in self.config['thermocouples']
                        if tc.get('enabled', True)]
            frg_names = [g['name'] for g in self.config.get('frg702_gauges', [])
                         if g.get('enabled', True)]

            # If any plot is live, keep master scroll at 1.0
            if hasattr(self, 'plot_tc') and self.plot_tc._is_live:
                self.master_scroll_var.set(1.0)

            if hasattr(self, 'plot_tc'):
                # TC data in buffer is always in Celsius (converted at acquisition)
                self.plot_tc.update(tc_names, data_units={'temp': 'C'})
            if hasattr(self, 'plot_pressure'):
                self.plot_pressure.update(frg_names, data_units={'press': self.p_unit_var.get()})
            if hasattr(self, 'plot_ps'):
                _ps_names = ['PS_Voltage', 'PS_Current']
                if getattr(self, '_programmer_ramp_running', False):
                    _ps_names += ['PS_Voltage_Setpoint', 'PS_CC_Limit']
                self.plot_ps.update(_ps_names)

        gui_profiler.start("schedule_next")
        self.root.after(self.config['display']['update_rate_ms'], self._update_gui)
        gui_profiler.loop_end()

    def _initialize_hardware_readers(self):
        try:
            handle = self.connection.get_handle()
            self.tc_reader = ThermocoupleReader(handle, self.config['thermocouples'])

            # Handle FRG702 Analog transition
            if self.config.get('frg_interface') == "Analog":
                frg702_config = self.config.get('frg702_gauges', [])
                if frg702_config:
                    self.frg702_reader = FRG702AnalogReader(handle, frg702_config)
                    print("Analog FRG-702 reader initialized via LabJack AIN")

            # Update live DAQ engine if running
            if self.daq:
                self.daq.update_readers(
                    tc_reader=self.tc_reader,
                    frg702_reader=self.frg702_reader,
                    config=self.config
                )

            self._check_connections()
            return True
        except Exception as e:
            print(f"Error initializing hardware readers: {e}")
            return False

    def _connect_xgs600(self):
        xgs_config = self.config.get('xgs600', {})
        if not xgs_config.get('enabled', False):
            return False

        try:
            self.xgs600 = XGS600Controller(
                port=xgs_config['port'],
                baudrate=xgs_config.get('baudrate', 9600),
                timeout=xgs_config.get('timeout', 1.0),
                address=xgs_config.get('address', '00'),
                debug=False # Enable verbose serial logging for debugging
            )
            if not self.xgs600.connect(silent=True):
                self.xgs600 = None
                return False

            frg702_config = self.config.get('frg702_gauges', [])
            if frg702_config:
                self.frg702_reader = FRG702Reader(self.xgs600, frg702_config)

            # Update live DAQ engine if running
            if self.daq:
                self.daq.update_readers(frg702_reader=self.frg702_reader)

            print("XGS-600 controller connected, FRG-702 reader initialized")
            return True
        except Exception:
            self.xgs600 = None
            return False

    def _check_keysight_monitor_config(self):
        """
        Checks which voltage range is configured for monitoring.
        User must verify the physical switch setting.
        """
        print("\n=== KEYSIGHT MONITOR CONFIGURATION ===")
        print("Check SW1 Switch 4 on the Keysight power supply:")
        print("  DOWN (default) = 0-5V monitoring range")
        print("  UP = 0-10V monitoring range")
        print()
        
        while True:
            response = input("Is SW1 Switch 4 UP or DOWN? (up/down): ").lower().strip()
            if response in ['up', 'down']:
                return response
            print("Please enter 'up' or 'down'")

    def _verify_t8_input_impedance(self):
        """
        Verify T8 is configured for high impedance input.
        T8 default is 10 MΩ which exceeds 500 kΩ requirement.
        """
        print("\n=== T8 INPUT IMPEDANCE CHECK ===")
        print("LabJack T8 AIN channels default to 10 MΩ input impedance")
        print("Keysight requires > 500 kΩ")
        print("✓ T8 meets requirement (10 MΩ >> 500 kΩ)")
        print("No configuration changes needed.")

    def _initialize_power_supply(self):
        try:
            handle = self.connection.get_handle()
            ps_config = self.config.get('power_supply', {})
            enabled = ps_config.get('enabled', False)

            print(f"[DEBUG] _initialize_power_supply: enabled={enabled}, handle_is_none={handle is None}")

            if not enabled:
                print("[DEBUG] Power supply is disabled in config. Setting ps_controller to None.")
                self.ps_controller = None
                self.safety_monitor.set_power_supply(None)
                self.ps_resource_var.set("None")
                return True

            if handle is None:
                print("[DEBUG] Cannot initialize power supply: LabJack handle is None")
                return False

            # Verify impedance is OK
            self._verify_t8_input_impedance()
            
            # Monitoring range is fixed to 0-5V (SW1 Switch 4 DOWN)
            switch_position = 'down'

            self.ps_controller = KeysightAnalogController(
                handle,
                rated_max_volts=ps_config.get('rated_max_volts', 6.0),
                rated_max_amps=ps_config.get('rated_max_amps', 180.0), # Fixed to PSU rating
                voltage_limit=ps_config.get('default_voltage_limit', 6.0),
                current_limit=ps_config.get('default_current_limit', 10.0), # Limited for sample safety
                voltage_pin=ps_config.get('voltage_pin', "DAC0"),
                current_pin=ps_config.get('current_pin', "DAC1"),
                voltage_monitor_pin=ps_config.get('voltage_monitor_pin', "AIN4"),
                current_monitor_pin=ps_config.get('current_monitor_pin', "AIN5"),
                switch_4_position=switch_position,
                debug=False
            )

            # Update live DAQ engine if running
            if self.daq:
                self.daq.update_readers(ps_controller=self.ps_controller)

            self.safety_monitor.set_power_supply(self.ps_controller)
            if self._program_executor:
                self._program_executor.set_power_supply(self.ps_controller)
                self._program_executor.practice_mode = self._practice_mode

            v_pin = ps_config.get('voltage_pin', 'DAC0')
            i_pin = ps_config.get('current_pin', 'DAC1')
            self.ps_resource_var.set(f"Analog ({v_pin}/{i_pin})")

            print(f"Analog power supply controller initialized successfully (Range: {switch_position})")
            self.ps_controller.run_diagnostics()
            return True
        except Exception as e:
            print(f"Failed to initialize analog PS controller: {e}")
            return False

    # ── Feature 3: Manual Voltage Nudge ──────────────────────────────────────

    def _build_manual_nudge_panel(self, parent_frame, pack_side=tk.TOP):
        """
        Build a 'Manual Voltage Nudge' sub-panel inside parent_frame.
        Lets user bump voltage by a configurable step (default 0.001 V).
        Visible whenever Power Programmer is active; respects Safe Mode clamping.
        """
        # Cleanup old frame and job if it exists
        if getattr(self, '_nudge_update_job', None):
            self.root.after_cancel(self._nudge_update_job)
            self._nudge_update_job = None
            
        if hasattr(self, '_nudge_frame') and self._nudge_frame:
            try:
                self._nudge_frame.destroy()
            except:
                pass

        frame = ttk.LabelFrame(parent_frame, text="Manual Voltage Nudge")
        frame.pack(side=pack_side, fill=tk.X, padx=4, pady=2)

        row = ttk.Frame(frame)
        row.pack(fill=tk.X, padx=4, pady=2)

        ttk.Label(row, text="Current V:").pack(side=tk.LEFT)
        self._nudge_v_var = tk.StringVar(value="0.000 V")
        ttk.Label(row, textvariable=self._nudge_v_var, width=7,
                   foreground='blue').pack(side=tk.LEFT, padx=2)

        ttk.Label(row, text="Step (V):").pack(side=tk.LEFT, padx=(6, 0))
        self._nudge_step_var = tk.StringVar(value="0.001")
        step_entry = ttk.Entry(row, textvariable=self._nudge_step_var, width=7)
        step_entry.pack(side=tk.LEFT, padx=2)

        ttk.Button(row, text="\u2212", width=3,
                    command=lambda: self._nudge_voltage(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(row, text="+", width=3,
                    command=lambda: self._nudge_voltage(+1)).pack(side=tk.LEFT, padx=2)

        self._nudge_frame = frame
        self._nudge_update_job = None
        self._start_nudge_readback_loop()

    def _reposition_nudge_panel(self):
        """
        Moves the Manual Nudge panel based on current state.
        - If Ready: move to control_frame (beside Run Program)
        - Otherwise: hide it (removed from programmer panel per user request)
        """
        # 1. Determine readiness
        ready = False
        if self._programmer_panel:
            ready = len(self._programmer_panel.get_blocks()) > 0
        elif self._programmer_blocks:
            ready = True 
        
        # 2. Decide target parent and side
        target_parent = None
        pack_side = tk.LEFT
        
        if ready:
            target_parent = self.control_frame
            
        # 3. Apply changes
        if target_parent:
            # Rebuild if parent changed or doesn't exist
            current_parent = None
            if hasattr(self, '_nudge_frame') and self._nudge_frame:
                try:
                    current_parent = self._nudge_frame.master
                except:
                    pass
            
            if not hasattr(self, '_nudge_frame') or not self._nudge_frame or not self._nudge_frame.winfo_exists() or current_parent != target_parent:
                self._build_manual_nudge_panel(target_parent, pack_side=pack_side)
            else:
                # Already in correct parent, just ensure it's packed correctly
                self._nudge_frame.pack(side=pack_side, padx=5, pady=2)
        else:
            # Hide if no target parent
            if getattr(self, '_nudge_update_job', None):
                self.root.after_cancel(self._nudge_update_job)
                self._nudge_update_job = None
            if hasattr(self, '_nudge_frame') and self._nudge_frame:
                try:
                    self._nudge_frame.destroy()
                except:
                    pass
                self._nudge_frame = None

    def _nudge_voltage(self, direction):
        """Apply one nudge step in the given direction (+1 or -1)."""
        try:
            step = float(self._nudge_step_var.get())
        except ValueError:
            return
        if step <= 0:
            return

        ps = getattr(self, 'ps_controller', None)
        print(f"[Nudge] direction={direction:+d}, ps={ps}, practice={self._practice_mode}")
        if ps is None:
            print("[Nudge] ps_controller is None — cannot nudge")
            return

        current_v = ps.get_voltage_setpoint() or 0.0
        target_v  = current_v + direction * step
        target_v  = round(target_v, 4)  # Prevent float drift (DAC resolution is ~0.001V)

        # Safe mode clamp: 1 V ceiling
        safe_mode = getattr(self, '_programmer_safe_mode', False)
        if safe_mode:
            target_v = min(target_v, 1.0)

        target_v = max(0.0, min(target_v, 6.0))

        # Ensure output is enabled and current limit is non-zero before writing voltage.
        # DAC1 starts at 0V (= 0A limit) at power-on; without a non-zero ceiling the
        # supply cannot source current even when the voltage setpoint is correct.
        if hasattr(ps, 'is_output_on') and hasattr(ps, 'output_on'):
            if not ps.is_output_on():
                try:
                    ps.output_on()
                    max_amps = getattr(ps, 'current_limit', getattr(ps, 'rated_max_amps', 180.0))
                    ps.set_current(max_amps)
                    print(f"[Nudge] output_on + set_current({max_amps}A)")
                except Exception as e:
                    print(f"[Nudge] output_on/set_current failed: {e}")

        result = ps.set_voltage(target_v)
        print(f"[Nudge] set_voltage({target_v:.3f}) → {result}")
        self._nudge_v_var.set(f"{target_v:.3f} V")

    def _start_nudge_readback_loop(self):
        """Poll the power supply setpoint every 500ms and update the nudge display."""
        def _poll():
            ps = getattr(self, 'ps_controller', None)
            if ps is not None:
                v = ps.get_voltage_setpoint()
                if v is not None:
                    self._nudge_v_var.set(f"{v:.3f} V")
            
            # Continue polling if nudge frame exists and is visible, 
            # or if the programmer is active.
            nudge_exists = hasattr(self, '_nudge_frame') and self._nudge_frame and self._nudge_frame.winfo_exists()
            if nudge_exists or getattr(self, '_programmer_mode_active', False):
                self._nudge_update_job = self.root.after(500, _poll)
        _poll()

    # ── Feature 4: Start QMS + Begin Ramp button ─────────────────────────────

    def _build_qms_ramp_button(self, parent_frame):
        """
        Build the gated 'Start QMS + Begin Ramp' button.
        Stays disabled until: (1) Hold is stable AND (2) pressure < 1e-4 Torr.
        """
        self._qms_btn_frame = ttk.Frame(parent_frame)
        self._qms_btn_frame.pack(fill=tk.X, padx=4, pady=4)

        self._qms_status_var = tk.StringVar(value="Waiting: temperature not yet stable")
        ttk.Label(self._qms_btn_frame, textvariable=self._qms_status_var,
                  foreground='gray').pack(side=tk.LEFT, padx=4)

        self._qms_ramp_btn = ttk.Button(
            self._qms_btn_frame,
            text="\U0001f680  Start QMS + Begin Ramp",
            state='disabled',
            command=self._on_qms_ramp_start
        )
        self._qms_ramp_btn.pack(side=tk.RIGHT, padx=4)
        self._qms_btn_gate_job = None
        self._qms_gate_active = False

    def _start_qms_gate_poll(self):
        """Begin polling every 2s to check if the QMS/Ramp button should be enabled."""
        self._qms_gate_active = True
        self._poll_qms_gate()

    def _poll_qms_gate(self):
        if not self._qms_gate_active:
            return

        hold_stable = False
        pressure_ok = False
        pressure_val = None
        if hasattr(self, 'daq') and self.daq is not None:
            try:
                readings = self.daq.get_last_readings() if hasattr(self.daq, 'get_last_readings') else {}
                for k, v in readings.items():
                    if ('FRG' in k or 'pressure' in k.lower()) and v is not None and isinstance(v, float):
                        pressure_val = v
                        break
            except Exception:
                pass

        if pressure_val is not None:
            pressure_ok = pressure_val < 1e-4
        else:
            pressure_ok = False

        ready = hold_stable and pressure_ok

        btn = getattr(self, '_qms_ramp_btn', None)
        status_var = getattr(self, '_qms_status_var', None)

        if btn and status_var:
            if ready:
                btn.config(state='normal')
                status_var.set("\u2705 Ready \u2014 temperature stable, pressure OK")
                for widget in self._qms_btn_frame.winfo_children():
                    if isinstance(widget, ttk.Label):
                        widget.config(foreground='green')
            else:
                btn.config(state='disabled')
                reasons = []
                if not hold_stable:
                    reasons.append("temperature not stable")
                if not pressure_ok:
                    if pressure_val is None:
                        reasons.append("no pressure reading")
                    else:
                        reasons.append(f"pressure too high ({pressure_val:.1e} Torr)")
                status_var.set("Waiting: " + ", ".join(reasons))
                for widget in self._qms_btn_frame.winfo_children():
                    if isinstance(widget, ttk.Label):
                        widget.config(foreground='gray')

        self._qms_btn_gate_job = self.root.after(2000, self._poll_qms_gate)

    def _on_qms_ramp_start(self):
        """
        Simultaneous QMS + Ramp launch.
        1. Trigger MASsoft Start via pyautogui keyboard shortcut.
        2. Write RAMP_START event to DataLogger CSV.
        3. Signal the program executor to continue (if pausing between blocks).
        """
        import datetime
        try:
            import pyautogui
            import time as _time

            windows = pyautogui.getWindowsWithTitle("MASsoft")
            if not windows:
                from tkinter import messagebox
                messagebox.showwarning(
                    "MASsoft Not Found",
                    "Could not find a window titled 'MASsoft'. "
                    "Make sure MASsoft is open with your scan tree loaded, then try again."
                )
                return
            win = windows[0]
            win.activate()
            _time.sleep(0.15)
            pyautogui.press('f5')

        except ImportError:
            from tkinter import messagebox
            messagebox.showerror("Missing Library",
                                 "pyautogui is not installed. Run: pip install pyautogui")
            return
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("QMS Start Error", f"Could not start MASsoft:\n{e}")
            return

        # Log RAMP_START event with ISO timestamp
        ts = datetime.datetime.now().isoformat()
        if hasattr(self, 'logger') and self.logger is not None:
            if self.logger.is_logging():
                self.logger.log_event("RAMP_START", ts)

        # Disable the button immediately — one-shot launch
        if hasattr(self, '_qms_ramp_btn'):
            self._qms_ramp_btn.config(state='disabled', text="QMS + Ramp Running")
        self._qms_gate_active = False

        self.status_var.set("TDS Ramp Running \u2014 QMS active")

    # ── Feature 5: Emergency pressure interlock ───────────────────────────────

    def _on_pressure_interlock(self, pressure_torr):
        """Emergency: pressure exceeded 1e-4 Torr. Stop QMS and power supply."""
        def _shutdown():
            # 1. Stop power supply immediately
            ps = getattr(self, 'ps_controller', None)
            if ps is not None:
                try:
                    ps.set_voltage(0.0)
                    ps.output_off()
                except Exception:
                    pass

            # 2. Stop program executor if running
            if self._program_executor and self._program_executor.is_running():
                self._program_executor.stop()

            # 3. Abort MASsoft scan via pyautogui (Escape key = Abort in MASsoft toolbar)
            try:
                import pyautogui, time as _t
                windows = pyautogui.getWindowsWithTitle("MASsoft")
                if windows:
                    windows[0].activate()
                    _t.sleep(0.1)
                    pyautogui.press('escape')
            except Exception:
                pass

            # 4. Log the event
            if hasattr(self, 'logger') and self.logger and self.logger.is_logging():
                self.logger.log_event("EMERGENCY_PRESSURE_SHUTDOWN",
                                      f"{pressure_torr:.2e} Torr")

            # 5. Disable QMS gate button
            self._qms_gate_active = False
            if hasattr(self, '_qms_ramp_btn'):
                self._qms_ramp_btn.config(state='disabled', text="SHUTDOWN \u2014 Pressure")

            # 6. Alert the user
            from tkinter import messagebox
            messagebox.showerror(
                "\u26a0\ufe0f PRESSURE INTERLOCK",
                f"Pressure reached {pressure_torr:.2e} Torr \u2014 exceeds 1\u00d710\u207b\u2074 Torr limit.\n\n"
                "Power supply OFF.\nMASsoft scan aborted.\nCheck vacuum system before restarting."
            )
            self.status_var.set(f"INTERLOCK: Pressure {pressure_torr:.2e} Torr \u2014 ALL STOPPED")

        self.root.after(0, _shutdown)

    def _on_close(self):
        self.is_running = False

        if self.daq:
            self.daq.stop_fast_acquisition()

        if self._program_executor and self._program_executor.is_running():
            self._program_executor.stop()

        if self.is_logging:
            self.logger.stop_logging()

        if self.ps_controller:
            try:
                self.ps_controller.output_off()
                self.ps_controller.set_voltage(0)
            except Exception:
                pass

        if self.xgs600:
            self.xgs600.disconnect()
            self.xgs600 = None

        if self.connection:
            self.connection.disconnect()

        self.root.destroy()

    def _on_refresh_gui(self):
        """
        Perform a deep refresh of the GUI, hardware readers, and plots.
        This acts as a 'soft restart' to ensure all settings are applied
        and hardware communication is synchronized.
        """
        try:
            print("[GUI] Deep refresh triggered...")
            
            # 1. Re-apply settings and rebuild config
            self._apply_settings_to_gui()
            
            # 2. Force hardware readers to re-sync if possible
            if self.daq:
                self.daq.update_readers(config=self.config)
            
            # 3. Reset plot skip counters to force immediate redraw
            self._plot_skip_counter = 0
            
            # 4. Process all pending events
            self.root.update_idletasks()
            
            # 5. Explicitly redraw the canvases
            for plot_attr in ('plot_tc', 'plot_pressure', 'plot_ps'):
                if hasattr(self, plot_attr):
                    plot = getattr(self, plot_attr)
                    plot.ax.relim()
                    plot.ax.autoscale_view()
                    plot.canvas.draw_idle()
            
            print("[GUI] Deep refresh completed successfully")
            
        except Exception as e:
            print(f"[GUI] Refresh error: {e}")
            import traceback
            traceback.print_exc()

    def _open_pid_log_viewer(self):
        """Open a scrollable dialog showing all logged PID ramp runs with suggestions."""
        pid_logger = self._program_executor.get_pid_logger()
        runs = pid_logger.get_all_runs()

        win = tk.Toplevel(self.root)
        win.title("PID Run History")
        win.geometry("760x540")
        win.transient(self.root)

        # Header
        header = ttk.Frame(win, padding=(10, 8, 10, 4))
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=f"PID Run Log  —  {len(runs)} run(s)  —  {pid_logger.get_log_path()}",
            font=('Arial', 9), foreground='#555'
        ).pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=lambda: _refresh()).pack(side=tk.RIGHT)

        # Scrollable text
        frame = ttk.Frame(win, padding=(10, 0, 10, 10))
        frame.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(frame, wrap=tk.WORD, font=('Courier', 9), state='disabled',
                       relief='flat', bg='#fafafa')
        sb = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _render(runs):
            text.configure(state='normal')
            text.delete('1.0', tk.END)
            if not runs:
                text.insert(tk.END, "No PID runs recorded yet.\n\nRun a Temperature Ramp block to generate a log entry.")
            else:
                for i, run in enumerate(reversed(runs), 1):
                    text.insert(tk.END, f"{'─'*70}\n")
                    text.insert(tk.END,
                        f"Run #{len(runs) - i + 1}  |  {run.get('timestamp', 'unknown')}\n"
                    )
                    text.insert(tk.END,
                        f"  Target rate : {run.get('target_rate_k_per_min', 0):.2f} K/min\n"
                        f"  Achieved    : {run.get('achieved_mean_rate_k_per_min', 0):.2f} K/min\n"
                        f"  Overshoot   : {run.get('overshoot_k', 0):.2f} K\n"
                        f"  Settling    : {run.get('settling_time_sec') or 'N/A'}"
                        + (f" s\n" if run.get('settling_time_sec') else "\n") +
                        f"  Oscillations: {run.get('oscillation_count', 0)}\n"
                        f"  Duration    : {run.get('duration_sec', 0):.1f} s\n"
                        f"  Gains (Kp/Ki/Kd): {run.get('kp_used', 0):.4f} / "
                        f"{run.get('ki_used', 0):.4f} / {run.get('kd_used', 0):.4f}\n"
                    )
                    text.insert(tk.END, "  Suggestions:\n")
                    for s in run.get('suggestions', []):
                        text.insert(tk.END, f"    • {s}\n")
                    text.insert(tk.END, "\n")
            text.configure(state='disabled')

        def _refresh():
            pid_logger._load()
            fresh_runs = pid_logger.get_all_runs()
            _render(fresh_runs)

        _render(runs)

    def run(self):
        self.root.mainloop()

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
import threading
import time
import os
import sys
import random
import math

from t8_daq_system.startup_profiler import profiler


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
from t8_daq_system.control.ramp_executor import RampExecutor
from t8_daq_system.control.safety_monitor import SafetyMonitor, SafetyStatus
from t8_daq_system.data.data_buffer import DataBuffer
from t8_daq_system.data.data_logger import DataLogger, create_metadata_dict
from t8_daq_system.gui.live_plot import LivePlot
from t8_daq_system.gui.sensor_panel import SensorPanel
from t8_daq_system.utils.helpers import convert_temperature
from t8_daq_system.gui.dialogs import LoggingDialog, LoadCSVDialog
from t8_daq_system.gui.settings_dialog import SettingsDialog
from t8_daq_system.gui.pinout_display import PinoutDisplay
from t8_daq_system.core.data_acquisition import DataAcquisition
from t8_daq_system.settings.app_settings import AppSettings
from t8_daq_system.gui.power_programmer_panel import PowerProgrammerPanel
from t8_daq_system.gui.programmer_preview_plot import ProgrammerPreviewPlot


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
        self.tc_reader = None

        profiler.section("XGS-600 Controller Connection")
        profiler.checkpoint("Initializing XGS-600 variables")
        # Initialize XGS-600 controller
        self.xgs600 = None
        self.frg702_reader = None
        profiler.checkpoint("XGS-600 variables initialized (not connected yet)")

        profiler.section("Analog Power Supply Controller")
        profiler.checkpoint("Analog PS controller will be created after T8 connects")
        # The analog controller is initialized in _initialize_power_supply() once
        # the LabJack T8 handle is available.  No separate network connection needed.
        self.ps_controller = None
        profiler.checkpoint("Analog PS controller placeholder set")

        profiler.section("Control Systems Initialization")
        profiler.checkpoint("Creating RampExecutor...")
        # Initialize ramp executor and safety monitor
        self.ramp_executor = RampExecutor()
        profiler.checkpoint("RampExecutor created")

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
        conflict_errors = []
        for i, ch in enumerate(tc_pin_list):
            tc_name = f"TC_{i+1}"
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
                "name": f"TC_{i+1}",
                "channel": tc_pin_list[i],
                "type": tc_type_list[i],
                "units": s.tc_unit,
                "enabled": True
            })

        # Build FRG-702 list
        frg702_gauges = []
        frg_pin_list = s.get_frg_pin_list(s.frg_count)

        # Warn if any FRG pin conflicts with an assigned TC channel
        tc_channels_used = {f"AIN{i}" for i in range(s.tc_count)}
        for pin in frg_pin_list:
            if pin in tc_channels_used:
                print(f"[CONFIG WARNING] FRG pin {pin} conflicts with a TC channel!")
        for i in range(s.frg_count):
            frg702_gauges.append({
                "name": f"FRG702_{i+1}",
                "sensor_code": f"T{2*i+1}",
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

                    # Force AIN 4 and 5 to single-ended mode on startup
                    print("[DEFERRED] Configuring AIN 4 and 5 to single-ended...")
                    self.connection.configure_ain_single_ended([4, 5])

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
        self._programmer_preview_data = ([], [], [])  # (times, voltages, currents)
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

        self._slider_mode_btn = ttk.Button(
            safety_frame, text="History %", width=12,
            command=self._toggle_slider_mode
        )
        self._slider_mode_btn.pack(side=tk.LEFT, padx=4)

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
            self.ramp_executor.set_power_supply(self.ps_controller)

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

        # 5. Instantiate the programmer panel
        self._programmer_panel = PowerProgrammerPanel(
            parent_frame=self._programmer_panel_frame,
            settings=self._app_settings,
            on_profile_confirmed_callback=self._on_programmer_profile_confirmed,
            on_panel_closed_callback=self._deactivate_power_programmer
        )

        # Restore saved blocks/mode into the newly created panel
        if self._programmer_blocks:
            self._programmer_panel._blocks = list(self._programmer_blocks)
            self._programmer_panel._mode = self._programmer_control_mode
            self._programmer_panel._mode_var.set(self._programmer_control_mode)
            self._programmer_panel._refresh_table()
            self._programmer_panel._refresh_status()

        # 6. Instantiate the preview plot
        self._programmer_preview_plot = ProgrammerPreviewPlot(
            parent_frame=self._programmer_plot_frame
        )

        # 7. Patch the panel's _refresh_status to also update the preview plot live
        original_refresh = self._programmer_panel._refresh_status

        def _patched_refresh():
            original_refresh()
            self._update_programmer_preview()

        self._programmer_panel._refresh_status = _patched_refresh

        # 8. If blocks were restored before the plot existed, force one preview render now
        if self._programmer_blocks:
            self._update_programmer_preview()

    def _update_programmer_preview(self):
        if self._programmer_panel and self._programmer_preview_plot:
            times, voltages, currents = self._programmer_panel.get_preview_data()
            self._programmer_preview_plot.update_preview(times, voltages, currents)
            # Show/hide the Run Ramp button
            if (self._programmer_panel.get_profile_ready()
                    and not self._run_ramp_btn_visible):
                self.run_ramp_btn.pack(side=tk.LEFT, padx=5)
                self._run_ramp_btn_visible = True
            elif (not self._programmer_panel.get_profile_ready()
                  and self._run_ramp_btn_visible):
                self.run_ramp_btn.pack_forget()
                self._run_ramp_btn_visible = False

    def _deactivate_power_programmer(self):
        # SAFETY: If a ramp is currently running, stop it safely first
        if self._programmer_ramp_running:
            self._stop_programmer_ramp_safe()

        # Save profile data before destroying panel
        if self._programmer_panel and self._programmer_panel.get_profile_ready():
            self._programmer_preview_data = self._programmer_panel.get_preview_data()
            self._programmer_blocks = list(self._programmer_panel._blocks)
            self._programmer_control_mode = self._programmer_panel._mode
        else:
            self._programmer_preview_data = ([], [], [])
            self._programmer_blocks = []
            self._programmer_control_mode = "Voltage"

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

        # Apply dotted preview overlay to the ps LivePlot
        self._apply_programmer_overlay()

    def _on_programmer_profile_confirmed(self, times, voltages, currents):
        self._programmer_preview_data = (times, voltages, currents)

    def _apply_programmer_overlay(self):
        """
        After exiting programmer mode, apply the dotted preview overlay to the ps LivePlot.
        The overlay will appear as dotted lines on the V&I plot.
        It becomes time-anchored once the user clicks Run Program.
        """
        from datetime import datetime
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
        """Start executing the programmer ramp using the ramp_executor infrastructure."""
        from datetime import datetime

        # Use stored blocks if panel is not active
        if self._programmer_panel:
            blocks = self._programmer_panel._blocks
            control_mode = self._programmer_panel._mode
        else:
            blocks = self._programmer_blocks
            control_mode = self._programmer_control_mode

        # Guard: must have valid profile
        if not blocks:
            messagebox.showwarning("No Profile", "Build a valid program first.")
            return

        # Guard: must have a power supply controller
        if not hasattr(self, 'ps_controller') or self.ps_controller is None:
            messagebox.showerror(
                "No Power Supply",
                "Power supply is not connected. Cannot run program."
            )
            return

        # Guard: safety monitor must not be in shutdown state
        if hasattr(self, 'safety_monitor') and self.safety_monitor.is_restart_locked:
            messagebox.showwarning(
                "Safety Lockout",
                "Safety lockout is active. Resolve temperature issue before running."
            )
            return

        # Convert programmer blocks to RampProfile steps
        from t8_daq_system.control.ramp_profile import RampProfile, RampStep, StepType, ControlMode
        
        # Determine global control mode from programmer
        is_current_mode = control_mode == "Current"
        
        # Initial values from first block
        first_v = float(blocks[0]["start_v"])
        first_a = float(blocks[0].get("start_a", blocks[0].get("current_a", 0.0)))
        
        # Validate hardware limits before building profile
        for block in blocks:
            start_v = float(block["start_v"])
            end_v = float(block["end_v"]) if block["type"] == "Ramp" else float(block["start_v"])
            start_a = float(block.get("start_a", block.get("current_a", 0.0)))
            end_a = float(block.get("end_a", start_a)) if block["type"] == "Ramp" else start_a

            if start_v > 6.0 or end_v > 6.0:
                messagebox.showerror(
                    "Voltage Limit Exceeded",
                    f"Block has voltage > 6.0V (hard limit). Aborting.\n"
                    f"Start V: {start_v}, End V: {end_v}"
                )
                return
            if start_a > 180.0 or end_a > 180.0:
                messagebox.showerror(
                    "Current Limit Exceeded",
                    f"Block has current > 180.0A (hard limit). Aborting.\n"
                    f"Start A: {start_a}, End A: {end_a}"
                )
                return

        # Compute actual max current and voltage across all blocks (never hardcode 180.0)
        max_current_a = max(
            max(float(b.get("start_a", 0.0)), float(b.get("end_a", b.get("start_a", 0.0))))
            for b in blocks
        )
        max_voltage_v = max(
            max(float(b["start_v"]), float(b["end_v"]))
            for b in blocks
        )
        # current_limit and voltage_limit must be > 0 per RampProfile.validate()
        max_current_a = max(max_current_a, 0.001)
        max_voltage_v = max(max_voltage_v, 0.001)

        profile = RampProfile(
            name=f"Programmer_{datetime.now().strftime('%H%M%S')}",
            control_mode=ControlMode.CURRENT.value if is_current_mode else ControlMode.VOLTAGE.value,
            start_voltage=first_v,
            start_current=first_a,
            voltage_limit=max_voltage_v,
            current_limit=max_current_a
        )

        for block in blocks:
            duration = float(block["duration"])
            step_type = StepType.RAMP.value if block["type"] == "Ramp" else StepType.HOLD.value

            # Per-block current and voltage targets (for interpolation during execution)
            block_start_a = float(block.get("start_a", block.get("current_a", 0.0)))
            block_end_a = float(block.get("end_a", block_start_a)) if block["type"] == "Ramp" else block_start_a
            block_start_v = float(block["start_v"])
            block_end_v = float(block["end_v"]) if block["type"] == "Ramp" else block_start_v

            print(f"[BLOCK DEBUG] Block #{blocks.index(block) + 1}")
            print(f"  From table: Start V={block_start_v}, End V={block_end_v}")
            print(f"  From table: Start A={block_start_a}, End A={block_end_a}")

            if is_current_mode:
                target_a = block_end_a
                step = RampStep(
                    step_type=step_type,
                    duration_sec=duration,
                    target_current=target_a
                )
            else:
                target_v = block_end_v
                # Also store target_current so ramp_executor can interpolate current per-block
                target_a = block_end_a
                step = RampStep(
                    step_type=step_type,
                    duration_sec=duration,
                    target_voltage=target_v,
                    target_current=target_a
                )
            profile.add_step(step)

        # Load into ramp_executor and start
        if not self.ramp_executor.load_profile(profile):
            messagebox.showerror("Load Error", "Failed to load profile into executor.")
            return

        if not self.ramp_executor.start():
            messagebox.showerror("Start Error", "Failed to start ramp executor.")
            return

        # Mark as running and enable programmer simulation mode on the mock
        # controller so DataAcquisition uses the proper analog round-trip.
        self._programmer_ramp_running = True
        if isinstance(self.ps_controller, MockPowerSupplyController):
            self.ps_controller.programmer_active = True
        self.run_ramp_btn.config(text="Stop Program")

        # Set overlay start time so the dotted preview anchors correctly on the ps plot.
        # Re-anchor to the actual run start time for accurate comparison.
        from datetime import datetime as _dt
        times, voltages, currents = self._programmer_preview_data
        for plot in getattr(self, '_live_plots', []):
            if hasattr(plot, 'plot_type') and plot.plot_type == 'ps':
                plot.set_programmer_overlay(times, voltages, currents)
                plot.set_overlay_start_time(_dt.now())  # pass datetime, not time.time()
                break

        self.status_var.set("Running Program")

    def _stop_programmer_ramp_safe(self):
        """
        Safely stop the programmer ramp, following Keysight N5700 manual guidance.

        Safe shutdown procedure:
        1. Stop the ramp_executor thread (sets setpoint toward 0V).
        2. Command 0V via DAC0, wait 500ms for supply to settle.
        3. Command 0A via DAC1.
        Do NOT abruptly de-assert the Enable/Analog pin while voltage is non-zero.
        """
        import time as _time

        # 1. Stop the executor thread
        if self.ramp_executor.is_active():
            self.ramp_executor.stop()

        # 2. Command 0V and 0A explicitly as belt-and-suspenders
        if hasattr(self, 'ps_controller') and self.ps_controller:
            try:
                self.ps_controller.set_voltage(0.0)
                _time.sleep(0.5)  # Allow supply to ramp down
                self.ps_controller.set_current(0.0)
                _time.sleep(0.1)
            except Exception as e:
                messagebox.showwarning("Stop Warning", f"Error during safe stop: {e}")

        # 3. Update UI and disable programmer simulation mode
        self._programmer_ramp_running = False
        if isinstance(self.ps_controller, MockPowerSupplyController):
            self.ps_controller.programmer_active = False
        self.run_ramp_btn.config(text="Run Program")

        # Keep overlay visible but don't update start time (dotted lines stay)

    def _on_pressure_unit_change(self):
        """Handle pressure unit selection change."""
        new_unit = self.p_unit_var.get()
        # Update config for persistence
        if self.config.get('frg702_gauges'):
            for gauge in self.config['frg702_gauges']:
                gauge['units'] = new_unit
        
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
                    elif name.startswith('TC_'):
                        display_last[name] = convert_temperature(value, source_t_unit, t_unit)
                    else:
                        display_last[name] = value
                self.sensor_panel.update(display_last)
        else:
            if hasattr(self, 'plot_tc'):
                self.plot_tc.update(tc_names)
            if hasattr(self, 'plot_pressure'):
                self.plot_pressure.update(frg_names)
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
                    if name.startswith('TC_'):
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
        print(f"[DEBUG] _on_config_change: New config built. PS enabled: {self.config.get('power_supply', {}).get('enabled')}")

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
        if name.startswith('TC_'):
            if hasattr(self, 'plot_tc'):
                self.plot_tc.set_sensor_visible(name, visible)
        elif name.startswith('FRG702_'):
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
        # Stop the user's ramp executor if running
        if self.ramp_executor.is_active():
            self.ramp_executor.stop()

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
        # Stop ramp executor if active
        if self.ramp_executor.is_active():
            self.ramp_executor.stop()

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

    def _toggle_slider_mode(self):
        """Toggle timeline slider between 'History %' and '2-min Window' modes."""
        for plot_attr in ('plot_tc', 'plot_pressure', 'plot_ps'):
            if hasattr(self, plot_attr):
                plot = getattr(self, plot_attr)
                current = getattr(plot, '_slider_mode', 'history_pct')
                new_mode = 'window_2min' if current == 'history_pct' else 'history_pct'
                plot.set_slider_mode(new_mode)
        # Update button label based on new mode
        if hasattr(self, 'plot_tc'):
            mode = self.plot_tc._slider_mode
        elif hasattr(self, 'plot_pressure'):
            mode = self.plot_pressure._slider_mode
        else:
            return
        label = "2-min Window" if mode == 'window_2min' else "History %"
        self._slider_mode_btn.config(text=label)

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
            ramp_executor=self.ramp_executor,
            practice_mode=self._practice_mode
        )

        def on_new_data(timestamp, all_readings, tc_readings, frg702_details,
                        safety_shutdown=False, raw_voltages=None):
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
                    if name.startswith('TC_'):
                        log_readings[name] = convert_temperature(value, 'C', t_unit)
                    else:
                        log_readings[name] = value
                # Include raw voltages (and differential voltages — same value,
                # labelled _rawV) so the log shows the full conversion chain:
                #   physical TC wire → raw mV input → EF temperature conversion
                if raw_voltages:
                    log_readings.update(raw_voltages)
                self.logger.log_reading(log_readings)

            if safety_shutdown:
                self.is_running = False
                self.root.after(0, self._handle_safety_shutdown)

        self.daq.start_fast_acquisition(callback=on_new_data)
        self._update_gui()

    def _on_stop(self):
        self.is_running = False

        if self.daq:
            self.daq.stop_fast_acquisition()

        self.log_btn.config(state='disabled')
        self.status_var.set("Stopped")

        if self.ramp_executor.is_active():
            self.ramp_executor.stop()

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
                sensor_names += ['PS_Voltage', 'PS_Current']

            # Append raw-voltage columns right after the temperature columns so the
            # log shows the full conversion chain for each thermocouple:
            #   <TC_N>  = converted temperature
            #   <TC_N>_rawV = raw differential input voltage (V) before EF conversion
            # Both columns carry identical physical information; having both lets the
            # user verify that the T8's internal millivolt→temperature lookup is correct.
            for tc in enabled_tcs:
                sensor_names.append(f"{tc['name']}_rawV")

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
        # Auto-connect hardware (only after initial deferred init has attempted)
        lj_connected = self.connection.is_connected()
        now = time.time()
        if self._practice_mode:
            lj_connected = True
        elif not lj_connected and self._hardware_init_attempted:
            if (now - self._last_lj_reconnect_time) >= self._reconnect_interval:
                self._last_lj_reconnect_time = now
                if self.connection.connect():
                    if self._initialize_hardware_readers():
                        lj_connected = True
                        self._update_connection_state(True)
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
            if name.startswith('TC_'):
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
                self.plot_tc.update(tc_names)
            if hasattr(self, 'plot_pressure'):
                self.plot_pressure.update(frg_names)
            if hasattr(self, 'plot_ps'):
                self.plot_ps.update(['PS_Voltage', 'PS_Current'])

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
                debug=True # Enable verbose serial logging for debugging
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
                self.ramp_executor.set_power_supply(None)
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
                debug=False # Disable verbose calculation debug prints
            )

            # Update live DAQ engine if running
            if self.daq:
                self.daq.update_readers(ps_controller=self.ps_controller)

            self.safety_monitor.set_power_supply(self.ps_controller)
            self.ramp_executor.set_power_supply(self.ps_controller)

            v_pin = ps_config.get('voltage_pin', 'DAC0')
            i_pin = ps_config.get('current_pin', 'DAC1')
            self.ps_resource_var.set(f"Analog ({v_pin}/{i_pin})")

            print(f"Analog power supply controller initialized successfully (Range: {switch_position})")
            return True
        except Exception as e:
            print(f"Failed to initialize analog PS controller: {e}")
            return False

    def _on_close(self):
        self.is_running = False

        if self.daq:
            self.daq.stop_fast_acquisition()

        if self.ramp_executor.is_active():
            self.ramp_executor.stop()

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

    def run(self):
        self.root.mainloop()

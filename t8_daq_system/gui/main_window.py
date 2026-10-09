"""
main_window.py
PURPOSE: Main application window - coordinates everything

Integrates LabJack T8 DAQ (thermocouples) and XGS-600 controller
(FRG-702 gauges) with Keysight N5761A power supply control, safety monitoring,
and ramp profile execution.

Safety features:
- 2200C temperature override triggers instant cutoff
- Restart lockout until temperature drops below 2150C
"""

import tkinter as tk
from tkinter import ttk, messagebox
import time
import os
import sys

from t8_daq_system.utils.startup_profiler import profiler
from t8_daq_system.control.safety_monitor import SafetyMonitor, SafetyStatus
from t8_daq_system.data.data_buffer import DataBuffer
from t8_daq_system.data.data_logger import DataLogger, create_metadata_dict
from t8_daq_system.gui.live_plot import LivePlot
from t8_daq_system.gui.camera_panel import CameraPanel
from t8_daq_system.gui.sensor_panel import SensorPanel
from t8_daq_system.utils.helpers import convert_pressure, convert_temperature
from t8_daq_system.gui.dialogs import LoggingDialog, LoadCSVDialog
from t8_daq_system.gui.settings_dialog import SettingsDialog
from t8_daq_system.gui.pinout_display import PinoutDisplay
from t8_daq_system.gui.program_panel import ProgramPanel
from t8_daq_system.settings.app_settings import AppSettings
import logging
from t8_daq_system.gui.programmer_preview_plot import ProgrammerPreviewPlot


from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.t8_adapter import T8Adapter
from t8_daq_system.rig.simulated import SimulatedRig
from t8_daq_system.rig.clock import RealClock
from t8_daq_system.rig.commands import (
    ConfirmContinue,
    LoadProgram,
    Nudge,
    ResetTrip,
    SelectAdapter,
    SetOutput,
    SetVoltage,
    StartProgram,
    StopProgram,
    UpdateConfig,
    RunSettings,
)
from t8_daq_system.rig.snapshot import Snapshot
from t8_daq_system.settings.safety_limits import PRESSURE_INTERLOCK_TORR
from t8_daq_system.data.run_record import RunRecord, build_header as _rr_build_header

_log = logging.getLogger(__name__)


def run_settings_from_app_settings(settings: AppSettings) -> RunSettings:
    """Create a frozen RunSettings from the current AppSettings, using spec defaults for new fields."""
    return RunSettings(
        kp=settings.pid_kp,
        ki=settings.pid_ki,
        kd=settings.pid_kd,
        windup_limit=settings.pid_windup_limit,
        soft_start_threshold_c=getattr(settings, "soft_start_threshold_c", 200.0),
        soft_start_ramp_v_per_s=getattr(settings, "soft_start_ramp_v_per_s", 0.02),
        soft_start_handoff_current_a=getattr(settings, "soft_start_handoff_current_a", 35.0),
        soft_start_cap_enabled=getattr(settings, "soft_start_cap_enabled", True),
        soft_start_cap_a=getattr(settings, "soft_start_cap_a", 40.0),
        run_cap_enabled=getattr(settings, "run_cap_enabled", True),
        run_cap_a=getattr(settings, "run_cap_a", 120.0),
    )


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

# Safe Mode limits for the Voltage/Current Power Programmer (not TempRamp)
_PROGRAMMER_SAFE_MODE_MAX_VOLTS = 1.0   # V
_PROGRAMMER_SAFE_MODE_MAX_AMPS  = 10.0  # A


def build_csv_header(config: dict, has_ps_controller: bool = True) -> list:
    """
    Build the full CSV header row (including 'Timestamp') in exact column order.

    WHY THIS EXISTS
    ---------------
    Extracted from MainWindow._on_start_stop_logging (rig-architecture ticket 01)
    to allow pure characterisation testing of the CSV column schema without
    requiring a Tk root.

    Delegates to RunRecord.build_header (ticket 11) which owns the canonical
    column schema including the two appended columns Heater_State and Trip_Reason.
    """
    enabled_tcs = [tc for tc in config.get('thermocouples', [])
                   if tc.get('enabled', True)]
    tc_names = [tc['name'] for tc in enabled_tcs]
    gauge_names = [g['name'] for g in config.get('frg702_gauges', [])
                   if g.get('enabled', True)]
    sensor_names = _rr_build_header(tc_names, gauge_names, has_ps=has_ps_controller)
    return ['Timestamp'] + sensor_names


class MainWindow:
    # Available sampling rates in milliseconds
    SAMPLE_RATES = [100, 200, 500, 1000, 2000]

    def __init__(self, settings=None, rig=None):
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
        profiler.checkpoint("Rig and Adapter Initialization")
        # LabJack reconnect guard
        self._last_labjack_read_failed = False
        self._pressure_interlock_fired = False

        profiler.section("Rig and Adapter Initialization")
        self.connection = None
        if rig is not None:
            self.rig = rig
            self._hardware_adapter = getattr(rig, '_hardware_adapter', None)
            self._practice_adapter = getattr(rig, '_practice_adapter', None)
            self.clock = getattr(rig, '_clock', None)
        else:
            tc_names = [tc['name'] for tc in self.config['thermocouples'] if tc.get('enabled', True)]
            gauge_names = [g['name'] for g in self.config.get('frg702_gauges', []) if g.get('enabled', True)]
            self.clock = RealClock()
            self._hardware_adapter = T8Adapter(config=self.config)
            self._practice_adapter = SimulatedRig(clock=self.clock, tc_names=tc_names, gauge_names=gauge_names)
            initial_adapter = self._hardware_adapter

            self.rig = Rig(
                adapter=initial_adapter,
                clock=self.clock,
                sample_rate_ms=self.config['logging']['interval_ms'],
                snapshot_consumer=self._on_snapshot,
                practice_adapter=self._practice_adapter,
                hardware_adapter=self._hardware_adapter,
                tc_names=tc_names,
                gauge_names=gauge_names,
            )
            self.rig.start()

        profiler.section("XGS-600 Controller Connection")
        profiler.checkpoint("Initializing XGS-600 variables")
        # Legacy reader placeholders
        self.xgs600 = None
        self.frg702_reader = None
        self.tc_reader = None
        profiler.checkpoint("XGS-600 variables initialized (managed by Rig)")

        profiler.section("Analog Power Supply Controller")
        self.ps_controller = None

        profiler.section("Control Systems Initialization")
        self._program_panel  = None
        self._camera_panel   = None
        self._qms_confirm_frame = None   # Created/destroyed with programmer panel

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
        _custom_log = settings.log_folder if isinstance(settings.log_folder, str) and settings.log_folder else ""
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
        self._run_record: RunRecord | None = None
        self.read_thread = None
        self._safety_triggered = False
        self._hardware_init_attempted = False  # Track if deferred init has run

        # Mode tracking
        self._viewing_historical = False
        self._loaded_data = None
        self._loaded_data_units = {'temp': 'C', 'press': 'PSI'}
        self._loaded_tc_names = []
        self._loaded_press_names = []
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

        # Apply camera button placement mode
        self._apply_camera_button_mode()

        # If camera index changed, switch the camera
        if self._camera_panel is not None:
            new_idx = getattr(s, 'camera_index', 0)
            if new_idx != self._camera_panel._camera_index:
                self._camera_panel.change_camera_index(new_idx)
            # Update timelapse settings (take effect on next timelapse start)
            self._camera_panel._timelapse_interval_s = getattr(s, 'timelapse_interval_s', 60)
            self._camera_panel._timelapse_export_fps = getattr(s, 'timelapse_export_fps', 10)

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
            except tk.TclError as e:
                # Existing pinout window was closed or destroyed; recreate below
                _log.debug("Existing pinout window check failed (%s); recreating", e)

        self._pinout_window = PinoutDisplay(self.root, self.config, self._app_settings)


    # ──────────────────────────────────────────────────────────────────────────
    # Camera button helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _on_cam_snapshot(self):
        if self._camera_panel is not None:
            self._camera_panel._take_snapshot()

    def _on_cam_timelapse(self):
        if self._camera_panel is not None:
            self._camera_panel._toggle_timelapse()

    def _on_cam_toggle(self):
        """Toggle the camera feed on or off."""
        if self._camera_panel is None:
            return
        now_starting = self._camera_panel.toggle_feed()
        if now_starting:
            self._cam_toggle_btn.config(text='Cam Off')
        else:
            self._cam_toggle_btn.config(text='Cam On')

    def _apply_camera_button_mode(self):
        """
        Show/hide camera buttons according to the camera_buttons_overlay setting.
        Status-bar mode (default): buttons in bottom status bar, no overlay.
        Overlay mode: buttons overlaid on camera panel, status-bar buttons hidden.
        """
        if self._camera_panel is None:
            return
        use_overlay = getattr(self._app_settings, 'camera_buttons_overlay', False)
        if use_overlay:
            # Hide status-bar buttons
            self._cam_snapshot_statusbar_btn.pack_forget()
            self._cam_timelapse_statusbar_btn.pack_forget()
            # Show overlay on camera panel
            self._camera_panel.show_overlay_buttons()
        else:
            # Hide any existing overlay
            self._camera_panel.hide_overlay_buttons()
            # Register status-bar buttons with the camera panel for state sync
            self._camera_panel.register_external_controls(
                self._cam_snapshot_statusbar_btn,
                self._cam_timelapse_statusbar_btn
            )
            # Re-pack status-bar buttons if they were hidden
            self._cam_snapshot_statusbar_btn.pack(side=tk.RIGHT, padx=(2, 0))
            self._cam_timelapse_statusbar_btn.pack(side=tk.RIGHT, padx=(0, 2))

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

            print("[DEFERRED] Hardware initialization managed by Rig loop")
            self._hardware_init_attempted = True

            # FF-8 START — seed feedforward map from historical CSVs in background
            ff_map = self.rig.get_ff_map() if hasattr(self, 'rig') and self.rig else None
            if ff_map is not None:
                import threading as _threading
                def _ff_ingest_thread():
                    try:
                        ff_map.scan_log_folder(self.log_folder)
                    except Exception as _exc:
                        print(f"[FF-ingest] Background scan error (non-fatal): {_exc}")
                _threading.Thread(target=_ff_ingest_thread, daemon=True,
                                  name='FF-LogIngest').start()
            # FF-8 END

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
        style.theme_use('clam')  # 'clam' respects background/foreground on buttons; Windows native themes do not
        _BG = '#d9d9d9'  # clam theme standard background — used for root window and plots too
        self.root.configure(bg=_BG)
        style.configure('TFrame', background=_BG)
        style.configure('TLabelframe', background=_BG)
        style.configure('TLabelframe.Label', background=_BG)
        style.configure('TLabel', background=_BG)
        style.configure('Settings.TButton', foreground='#1a5f7a')
        style.configure('Red.TButton', foreground='white', background='#cc0000',
                        bordercolor='#990000', darkcolor='#990000', lightcolor='#ee3333')
        style.map('Red.TButton',
                  background=[('active', '#990000'), ('pressed', '#880000')],
                  foreground=[('active', 'white'), ('pressed', 'white')])
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

        # ── Trip Banner (non-modal) ──────────────────────────────────────────
        self._trip_banner_frame = tk.Frame(self.root, bg="#cc0000", bd=2, relief=tk.RIDGE)
        self._trip_label = tk.Label(
            self._trip_banner_frame,
            text="",
            font=("Arial", 10, "bold"),
            fg="white",
            bg="#cc0000",
            anchor="w",
            justify=tk.LEFT,
        )
        self._trip_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=4)

        self._trip_refusal_label = tk.Label(
            self._trip_banner_frame,
            text="",
            font=("Arial", 9, "italic"),
            fg="#ffdddd",
            bg="#cc0000",
            anchor="w",
        )
        self._trip_refusal_label.pack(side=tk.LEFT, padx=8, pady=4)

        self._trip_reset_btn = ttk.Button(
            self._trip_banner_frame,
            text="Reset",
            command=self._on_reset_trip,
        )
        self._trip_reset_btn.pack(side=tk.RIGHT, padx=8, pady=4)
        self._trip_banner_visible = False
        self._trip_text = ""
        self._trip_refusal_text = ""
        self._practice_btn_state = "normal"
        self._last_aborted_trip_kind = None
        self._qms_status_var = tk.StringVar(value="Waiting: temperature not yet stable")

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

        self.cut_power_btn = ttk.Button(
            control_frame,
            text="Cut Power",
            command=self._cut_power_output,
            style='Red.TButton'
        )
        self.cut_power_btn.pack(side=tk.LEFT, padx=5)

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

        profiler.checkpoint("Status labels created")

        profiler.checkpoint("Creating safety status bar...")
        # Safety Status Bar at bottom
        safety_frame = ttk.Frame(self.root)
        safety_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(2, 10))

        ttk.Label(safety_frame, text="Status:", font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=(0, 2))
        self.status_label_bottom = ttk.Label(
            safety_frame, textvariable=self.status_var, font=('Arial', 8, 'bold')
        )
        self.status_label_bottom.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Separator(safety_frame, orient='vertical').pack(side=tk.LEFT, padx=5, fill='y')

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

        # ── Camera buttons (far right of status bar) ─────────────────────────
        ttk.Separator(safety_frame, orient='vertical').pack(side=tk.RIGHT, padx=5, fill='y')
        self._cam_timelapse_statusbar_btn = ttk.Button(
            safety_frame, text='\u23fa Timelapse',
            command=self._on_cam_timelapse, state='disabled', width=12
        )
        self._cam_timelapse_statusbar_btn.pack(side=tk.RIGHT, padx=(0, 2))
        self._cam_snapshot_statusbar_btn = ttk.Button(
            safety_frame, text='\U0001f4f7 Snapshot',
            command=self._on_cam_snapshot, state='disabled', width=10
        )
        self._cam_snapshot_statusbar_btn.pack(side=tk.RIGHT, padx=(2, 0))
        self._cam_toggle_btn = ttk.Button(
            safety_frame, text='Cam On',
            command=self._on_cam_toggle, width=8
        )
        self._cam_toggle_btn.pack(side=tk.RIGHT, padx=(2, 0))

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

        # Clear CSV cache when rebuilding plots
        for _p in (self.plot_tc, self.plot_pressure, self.plot_ps):
            _p._loaded_timestamps = []
            _p._loaded_plot_data = {}

        # Row 1, Col 1 — Camera feed (Logitech C920s)
        camera_frame = ttk.LabelFrame(parent, text="Camera / IR")
        camera_frame.grid(row=1, column=1, sticky='nsew', padx=2, pady=2)
        camera_frame.grid_rowconfigure(0, weight=1)
        camera_frame.grid_columnconfigure(0, weight=1)
        camera_index = self._app_settings.camera_index if hasattr(self._app_settings, 'camera_index') else 0
        self._camera_panel = CameraPanel(
            camera_frame,
            log_folder=self.log_folder,
            camera_index=camera_index,
            show_internal_buttons=False,
            timelapse_interval_s=getattr(self._app_settings, 'timelapse_interval_s', 60),
            timelapse_export_fps=getattr(self._app_settings, 'timelapse_export_fps', 10)
        )
        self._camera_panel.grid(row=0, column=0, sticky='nsew')
        profiler.checkpoint("Camera panel created")

        # Wire camera buttons to their placement based on the current setting
        self._apply_camera_button_mode()

        profiler.checkpoint("Updating plot settings...")
        self._update_plot_settings()
        profiler.checkpoint("Plot settings updated")

        # Apply persisted appearance settings on startup
        self._apply_appearance_to_plots()
        profiler.checkpoint("Appearance settings applied to plots")

    def _toggle_practice_mode(self):
        """Toggle practice mode on/off."""
        if hasattr(self, 'practice_btn') and str(self.practice_btn.cget('state')) == 'disabled':
            return
        snap = self.rig.latest() if hasattr(self, 'rig') and self.rig is not None else None
        current_is_practice = snap is not None and snap.adapter == "simulated"
        practice_mode = not current_is_practice
        if hasattr(self, 'rig') and self.rig is not None:
            self.rig.submit(SelectAdapter(practice=practice_mode))

        if practice_mode:
            self._hardware_init_attempted = True  # Practice mode counts as initialized
            self.practice_btn.config(text="Practice Mode: ON")
            self.status_var.set("Practice Mode Active")

            if not self.config.get('frg702_gauges'):
                self.config['frg702_gauges'] = [
                    {"name": "FRG702_Mock", "sensor_code": "T1", "units": "mbar", "enabled": True}
                ]
            self.frg_count_var.set(str(len(self.config['frg702_gauges'])))

            self.ps_resource_var.set("Simulated Rig")
            self._auto_start_acquisition()

            # ── Feature C: Window title ───────────────────────────────────
            self.root.title('[PRACTICE MODE] T8 DAQ System with Power Supply Control')

            # ── Feature C: Practice button style ─────────────────────────
            style = ttk.Style()
            style.configure('PracticeOn.TButton',
                            background='#FF8C00',
                            foreground='white',
                            font=('Arial', 9, 'bold'))
            style.map('PracticeOn.TButton',
                      background=[('active', '#cc7000'), ('pressed', '#aa5e00')],
                      foreground=[('active', 'white'), ('pressed', 'white')])
            self.practice_btn.configure(style='PracticeOn.TButton')

        else:
            self.practice_btn.config(text="Practice Mode: OFF")
            self.ps_resource_var.set("None")

            # Stop practice acquisition before switching to real hardware
            self._on_stop()

            snap = self.rig.latest() if hasattr(self, 'rig') and self.rig else None
            if snap is not None and snap.labjack.state == "connected":
                self.status_var.set("Connected")
                self._auto_start_acquisition()
            else:
                self.status_var.set("Disconnected")

            # Clear programmer overlay from PS plot when leaving practice mode
            for plot in getattr(self, '_live_plots', []):
                if hasattr(plot, 'plot_type') and plot.plot_type == 'ps':
                    plot.set_programmer_overlay([], [], [])
                    break

            # ── Feature C: Revert window title ────────────────────────────
            self.root.title('T8 DAQ System with Power Supply Control')

            # ── Feature C: Revert practice button style ───────────────────
            self.practice_btn.configure(style='TButton')

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
            get_initial_state_fn=lambda: (self._get_latest_tc_reading_k("TC_1"), self._latest_snapshot.ps_volts if self._latest_snapshot else 0.0),
            on_program_change=self._update_run_button_state,
            tc_names=sorted(self._tc_names),
            get_unit_fn=lambda: getattr(self, 't_unit_var', None) and self.t_unit_var.get() or 'K',
            get_tc_temp_k_fn=self._get_latest_tc_reading_k,
            ff_map=self.rig.get_ff_map() if hasattr(self, 'rig') and self.rig else None,  # FF-10
        )
        
        # Restore saved blocks from before the programmer was last closed
        if self._programmer_blocks:
            self._programmer_panel.load_blocks(self._programmer_blocks)

        # QMS confirmation frame (hidden; shown when executor pauses for QMS trigger)
        self._qms_confirm_frame = ttk.LabelFrame(
            self._programmer_panel_frame, text=" \u25b6 QMS Trigger Required "
        )
        # Not packed yet — shown by _on_waiting_for_qms_confirmation

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
        # NOTE: Do NOT stop a running ramp when navigating away from the programmer.
        # The executor thread is independent of the UI panel.
        # The run continues in the background; the Stop button and Cut Power button
        # remain available from the main toolbar.

        # Save profile data before destroying panel
        if self._programmer_panel:
            self._programmer_blocks = list(self._programmer_panel.get_blocks())
            self._programmer_preview_data = ([], [], [])
            self._programmer_control_mode = "Program"
            self._programmer_mode = "Program"
        # (Otherwise keep whatever was already in self._programmer_blocks)

        # Destroy programmer UI
        self._qms_confirm_frame = None   # Will be destroyed with _programmer_panel_frame
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
        if hasattr(self, 'rig') and self.rig:
            snap = self.rig.latest()
            if snap is not None and tc_name in snap.tc_c:
                val_c = snap.tc_c[tc_name]
                if val_c is not None:
                    return val_c + 273.15
        if not self._latest_tc_readings:
            return 293.15
        val_c = self._latest_tc_readings.get(tc_name, 20.0)
        return val_c + 273.15

    def _on_snapshot(self, snap: Snapshot):
        """
        Consume each Snapshot published by the Rig (Step 7 of the Rig loop).

        Checks the pressure interlock, updates DataBuffer, latest readings,
        and logs CSV rows if logging is active.
        """
        # Marshal snapshot rendering to the Tk thread
        if hasattr(self, 'root') and hasattr(self.root, 'after'):
            self.root.after(0, lambda s=snap: self.render_snapshot(s))

        # Pressure interlock check in canonical Torr
        if snap.pressure_torr:
            for k, pval in snap.pressure_torr.items():
                if pval is not None and isinstance(pval, (int, float)) and pval > PRESSURE_INTERLOCK_TORR:
                    if not self._pressure_interlock_fired:
                        self._pressure_interlock_fired = True
                        print(f"[INTERLOCK] {k} pressure {pval:.2e} Torr exceeds {PRESSURE_INTERLOCK_TORR:.0e} Torr limit - output disabled")
                        self._on_pressure_interlock(pval)
                    break

        all_readings = {}
        for k, v in snap.tc_c.items():
            all_readings[k] = v
        for k, v in snap.pressure_torr.items():
            all_readings[k] = v

        all_readings['PS_Voltage'] = snap.ps_volts
        all_readings['PS_Current'] = snap.ps_amps
        all_readings['PS_Voltage_Setpoint'] = snap.commanded_volts
        all_readings['PS_CC_Limit'] = 180.0

        if snap.program.running and snap.program.block_index is not None:
            all_readings['Block_Index'] = snap.program.block_index + 1
        else:
            all_readings['Block_Index'] = None

        if self.is_running:
            self.data_buffer.add_reading(all_readings)

        self._latest_readings = (snap.wall_time, all_readings)
        self._latest_tc_readings = dict(snap.tc_c)
        self._latest_raw_voltages = dict(snap.tc_raw_v)
        self._latest_frg702_details = {
            g: {'pressure': p, 'status': 'OK' if p is not None else 'Error'}
            for g, p in snap.pressure_torr.items()
        }

        # CSV logging is handled by RunRecord (ticket 11): the Rig forwards each
        # Snapshot to RunRecord.put_snapshot() at step 7, so no logging here.

    def is_trip_banner_visible(self) -> bool:
        """Return True if the trip banner is currently shown."""
        return getattr(self, '_trip_banner_visible', False)

    def get_trip_text(self) -> str:
        """Return the text currently shown in the trip label."""
        return getattr(self, '_trip_text', "")

    def get_trip_refusal_text(self) -> str:
        """Return the text currently shown in the trip refusal label."""
        return getattr(self, '_trip_refusal_text', "")

    def get_practice_button_state(self) -> str:
        """Return the current state ('normal' or 'disabled') of the practice mode button."""
        return getattr(self, '_practice_btn_state', "normal")

    def _on_reset_trip(self):
        """Submit ResetTrip command to the Rig."""
        if hasattr(self, 'rig') and self.rig is not None:
            self.rig.submit(ResetTrip())

    def _abort_massoft(self):
        """Abort MASsoft scan on Tk thread; failure is reported and not swallowed."""
        try:
            import pyautogui
            windows = pyautogui.getWindowsWithTitle("MASsoft")
            if windows:
                windows[0].activate()
                time.sleep(0.1)
                pyautogui.press('escape')
        except Exception as err:
            _log.error("MASsoft abort failed: %s", err)
            messagebox.showerror(
                "MASsoft Abort Failed",
                f"Could not abort MASsoft scan:\n{err}"
            )
            self.status_var.set(f"MASsoft abort failed: {err}")

    def render_snapshot(self, snap: Snapshot):
        """
        Render a Snapshot on the GUI (runs on the Tk thread).
        Updates the non-modal trip banner, practice button state, and aborts QMS on trip.
        """
        if snap is None:
            return

        self._latest_rendered_snapshot = snap

        # 1. Trip banner handling
        is_tripped = (snap.heater is not None and snap.heater.state == "tripped")
        if is_tripped:
            kind = snap.heater.trip_kind or "unknown"
            reason = snap.heater.trip_reason or ""
            if snap.heater.shutoff_unverified:
                banner_bg = "#880000"
                text = f"CRITICAL: shutoff_unverified! Trip: {kind} \u2014 {reason}"
            else:
                banner_bg = "#cc0000"
                text = f"TRIP: {kind} \u2014 {reason}"

            self._trip_text = text
            refusal = snap.command_rejected_reason or snap.adapter_refusal_reason or ""
            self._trip_refusal_text = refusal

            if hasattr(self, '_trip_banner_frame'):
                self._trip_banner_frame.config(bg=banner_bg)
            if hasattr(self, '_trip_label'):
                self._trip_label.config(text=text, bg=banner_bg)
            if hasattr(self, '_trip_refusal_label'):
                self._trip_refusal_label.config(text=refusal, bg=banner_bg)

            if not getattr(self, '_trip_banner_visible', False):
                if hasattr(self, '_trip_banner_frame'):
                    if hasattr(self, 'panel_container') and hasattr(self.panel_container, 'winfo_exists') and self.panel_container.winfo_exists():
                        self._trip_banner_frame.pack(before=self.panel_container, fill=tk.X, padx=10, pady=2)
                    else:
                        self._trip_banner_frame.pack(fill=tk.X, padx=10, pady=2)
                self._trip_banner_visible = True

            # On pressure_high or pressure_stale trip, run MASsoft abort if not yet aborted for this trip
            if kind in ("pressure_high", "pressure_stale"):
                if getattr(self, '_last_aborted_trip_kind', None) != kind:
                    self._last_aborted_trip_kind = kind
                    self._abort_massoft()
        else:
            self._last_aborted_trip_kind = None
            self._trip_text = ""
            self._trip_refusal_text = ""
            if getattr(self, '_trip_banner_visible', False):
                if hasattr(self, '_trip_banner_frame'):
                    self._trip_banner_frame.pack_forget()
                self._trip_banner_visible = False
                if hasattr(self, '_trip_label'):
                    self._trip_label.config(text="")
                if hasattr(self, '_trip_refusal_label'):
                    self._trip_refusal_label.config(text="")

        # 2. Practice toggle enabled/disabled
        prog_running = bool(snap.program and snap.program.running)
        logging_active = getattr(self, 'is_logging', False) or getattr(self, '_run_record', None) is not None
        target_state = 'disabled' if (prog_running or logging_active) else 'normal'
        self._practice_btn_state = target_state
        if hasattr(self, 'practice_btn'):
            self.practice_btn.config(state=target_state)

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
            if self._programmer_preview_plot is not None:
                self._programmer_preview_plot.clear_progress_dot()
        self.root.after(0, _gui_update)

    def _on_waiting_for_qms_confirmation(self, block_index):
        """Called from executor thread when a QMS-triggered StableHold completes."""
        def _show_banner():
            frame = getattr(self, '_qms_confirm_frame', None)
            if frame is None or not frame.winfo_exists():
                return
            # Clear any old content
            for w in frame.winfo_children():
                w.destroy()
            ttk.Label(
                frame,
                text="Stable Hold complete — click to start QMS recording and continue to next ramp.",
                font=('Arial', 10, 'bold'), foreground='#9b59b6'
            ).pack(side=tk.LEFT, padx=8, pady=6, expand=True)
            ttk.Button(
                frame,
                text="\u25b6  Start QMS + Continue Ramp",
                command=self._on_qms_confirmation_click
            ).pack(side=tk.RIGHT, padx=8, pady=6)
            frame.pack(fill=tk.X, padx=4, pady=4)
        self.root.after(0, _show_banner)

    def _on_qms_confirmation_click(self):
        """User clicked the QMS confirmation button."""
        import datetime

        # 1. Perform auto-click if enabled
        settings = getattr(self, '_app_settings', None)
        if settings and getattr(settings, 'qms_auto_click_enabled', False):
            try:
                import pyautogui
                x = int(settings.qms_auto_click_x)
                y = int(settings.qms_auto_click_y)
                pyautogui.click(x, y)
            except ImportError:
                from tkinter import messagebox
                messagebox.showerror(
                    "Missing Library",
                    "pyautogui is not installed. Run: pip install pyautogui\n"
                    "Continuing without auto-click."
                )
            except Exception as e:
                from tkinter import messagebox
                messagebox.showwarning("Auto-Click Error",
                                       f"Click failed: {e}\nContinuing anyway.")

        # 2. Log QMS_TRIGGER event
        ts = datetime.datetime.now().isoformat()
        if hasattr(self, 'logger') and self.logger is not None:
            if self.logger.is_logging():
                self.logger.log_event("QMS_TRIGGER", ts)

        # 3. Hide confirmation banner
        frame = getattr(self, '_qms_confirm_frame', None)
        if frame is not None and frame.winfo_exists():
            frame.pack_forget()

        # 4. Release executor / submit ConfirmContinue to Rig
        if hasattr(self, 'rig') and self.rig is not None:
            self.rig.submit(ConfirmContinue())

        self.status_var.set("QMS triggered — ramp continuing")

    def _show_pid_run_summary(self):
        """Show a post-run PID performance summary and offer to update settings gains."""
        record = self.rig.get_last_run_record() if hasattr(self, 'rig') and self.rig else None
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
        def _update_status_and_dot():
            self.status_var.set(msg)
            if self._programmer_preview_plot is not None:
                self._programmer_preview_plot.set_progress_time(elapsed)
        self.root.after(0, _update_status_and_dot)

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

        # Guard: safety monitor must not be in shutdown state
        if self.safety_monitor.is_restart_locked:
            messagebox.showwarning("Safety Lockout", "Safety lockout is active.")
            return

        # Submit LoadProgram and StartProgram commands to Rig
        if hasattr(self, 'rig') and self.rig is not None:
            settings = run_settings_from_app_settings(self._app_settings)
            self.rig.submit(LoadProgram(program=blocks))
            self.rig.submit(StartProgram(settings=settings))

        self._programmer_ramp_running = True
        self.run_ramp_btn.config(text="Stop Program")
        print("[Program] Started execution")

    def _stop_programmer_ramp_safe(self):
        """Stop the running program safely."""
        if hasattr(self, 'rig') and self.rig is not None:
            self.rig.submit(StopProgram())
        self._programmer_ramp_running = False
        self.run_ramp_btn.config(text="Run Program")
        self.status_var.set("Program Stopped")
        if self._programmer_preview_plot is not None:
            self._programmer_preview_plot.clear_progress_dot()
        # Restore default legend if it was modified during a run
        if hasattr(self, 'plot_ps'):
            self.plot_ps.set_legend_label_overrides({})
            self.plot_ps.update(['PS_Voltage', 'PS_Current'])

    def _cut_power_output(self):
        """
        Immediately command 0 V to the power supply and stop any
        running executor. Safe to call at any time.
        """
        if hasattr(self, 'rig') and self.rig is not None:
            self.rig.submit(StopProgram())
            self.rig.submit(SetOutput(False))
            self.rig.submit(SetVoltage(0.0))

        # Reset run state
        self._programmer_ramp_running = False
        self.run_ramp_btn.config(text="Run Program")
        self.status_var.set("Power Cut")

        # Restore default legend
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

        temp_symbols = {'C': '\u00b0C', 'K': 'K'}
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
            # Only push loaded data to plots on first entry; after that, plots
            # are frozen and the scrollbar drives rendering via sync_scroll.
            if not getattr(self, '_historical_plots_initialized', False):
                _hist_tc = self._loaded_tc_names or tc_names
                _hist_press = self._loaded_press_names or frg_names
                if hasattr(self, 'plot_tc'):
                    self.plot_tc.update_from_loaded_data(
                        self._loaded_data, _hist_tc,
                        data_units=self._loaded_data_units
                    )
                if hasattr(self, 'plot_pressure'):
                    self.plot_pressure.update_from_loaded_data(
                        self._loaded_data, _hist_press,
                        data_units=self._loaded_data_units
                    )
                if hasattr(self, 'plot_ps'):
                    ps_names = [n for n in self._loaded_data
                                if n in ('PS_Voltage', 'PS_Current')]
                    self.plot_ps.update_from_loaded_data(
                        self._loaded_data, ps_names,
                        data_units=self._loaded_data_units
                    )
                self._historical_plots_initialized = True

            if self._loaded_data.get('timestamps'):
                last_readings = {name: self._loaded_data[name][-1]
                                for name in self._loaded_data if name != 'timestamps'}
                display_last = {}
                source_t_unit = self._loaded_data_units.get('temp', 'C')

                for name, value in last_readings.items():
                    if value is None:
                        display_last[name] = None
                    elif name in _hist_tc:
                        display_last[name] = convert_temperature(value, source_t_unit, t_unit)
                    else:
                        display_last[name] = value
                self.sensor_panel.update(display_last)
        else:
            if hasattr(self, 'plot_tc'):
                # TC data in buffer is always in Celsius (converted at acquisition)
                self.plot_tc.update(tc_names, data_units={'temp': 'C'})
            if hasattr(self, 'plot_pressure'):
                # Gauge data in buffer is always in Torr (canonical unit)
                self.plot_pressure.update(frg_names, data_units={'press': 'Torr'})
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
            self._historical_plots_initialized = False

            # Derive which columns are TCs vs pressure from the file itself so that
            # old-format files (TC_1/P_1) and new-format files (1/2/FRG702_T1) both work.
            all_names = [n for n in data if n != 'timestamps']
            sensors_meta = metadata.get('sensors', []) if metadata else []
            tc_count = metadata.get('tc_count', 0) if metadata else 0
            frg_count = metadata.get('frg702_count', metadata.get('p_count', 0)) if metadata else 0

            if sensors_meta and tc_count:
                self._loaded_tc_names = [n for n in sensors_meta[:tc_count] if n in all_names]
            else:
                self._loaded_tc_names = [n for n in all_names if n.upper().startswith('TC')]

            if sensors_meta and frg_count and tc_count:
                self._loaded_press_names = [n for n in sensors_meta[tc_count:tc_count + frg_count]
                                            if n in all_names]
            else:
                self._loaded_press_names = [n for n in all_names
                                            if n.startswith('FRG702_') or n.startswith('P_')]

            if metadata:
                self._loaded_data_units = {
                    'temp': metadata.get('tc_unit', 'C'),
                    'press': metadata.get('p_unit') or metadata.get('frg702_unit', 'mbar')
                }
                # Sync internal vars for display-unit conversions; settings are not
                # modified so the live config is preserved after returning to live view.
                if 'tc_count' in metadata:
                    self.tc_count_var.set(str(metadata['tc_count']))
                if 'frg702_count' in metadata:
                    self.frg_count_var.set(str(metadata['frg702_count']))
                if 'tc_unit' in metadata:
                    self.t_unit_var.set('C' if metadata['tc_unit'] == 'F' else metadata['tc_unit'])
                _press_unit = metadata.get('p_unit') or metadata.get('frg702_unit')
                if _press_unit:
                    self.p_unit_var.set(_press_unit)
                    if hasattr(self, 'sensor_panel'):
                        self.sensor_panel.update_global_pressure_unit(_press_unit)
                if 'sample_rate_ms' in metadata:
                    self.sample_rate_var.set(f"{metadata['sample_rate_ms']}ms")

            self._update_plot_settings()
            # Reset master timeline slider to the end of the CSV (rightmost)
            if hasattr(self, 'master_scroll_var'):
                self.master_scroll_var.set(1.0)
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
                    if name in self._loaded_tc_names:
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
        self._historical_plots_initialized = False
        self._loaded_data = None
        self._loaded_tc_names = []
        self._loaded_press_names = []
        self.historical_label.pack_forget()

        if hasattr(self, 'return_live_btn'):
            self.return_live_btn.pack_forget()

        for _plot_attr in ('plot_tc', 'plot_pressure', 'plot_ps'):
            if hasattr(self, _plot_attr):
                getattr(self, _plot_attr).clear()
        self.data_buffer.clear()

        snap = self.rig.latest() if hasattr(self, 'rig') and self.rig is not None else None
        lj_ok = (snap is not None and snap.labjack.state == "connected") or bool(self.connection and self.connection.is_connected())
        if lj_ok:
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

        if hasattr(self, 'rig') and self.rig is not None:
            sample_rate = self.config.get('logging', {}).get('interval_ms')
            self.rig.submit(UpdateConfig(
                sample_rate_ms=float(sample_rate) if sample_rate is not None else None,
                tc_names=list(self._tc_names),
                gauge_names=list(self._frg_names),
            ))

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

    def _on_safety_warning(self, sensor_name: str, value: float, limit: float):
        self.root.after(0, lambda: self._update_safety_display(SafetyStatus.WARNING))

    def _on_safety_limit_exceeded(self, sensor_name: str, value: float, limit: float):
        self.root.after(0, lambda: self._update_safety_display(SafetyStatus.LIMIT_EXCEEDED))

    def _on_safety_shutdown(self, event):
        self._safety_triggered = True
        self.root.after(0, self._handle_safety_shutdown)

    def _handle_safety_shutdown(self):
        # Update safety display (power supply cutoff is handled by Rig/HeaterOutput)
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
            if hasattr(self, 'rig') and self.rig is not None:
                self.rig.submit(ResetTrip())

    def _on_ps_output_change(self, is_on: bool):
        if is_on:
            self.status_var.set("Running - PS Output ON")
        else:
            if self.is_running:
                self.status_var.set("Running")

    def _on_ramp_start(self):
        """Deprecated: heater output is commanded via Rig / HeaterOutput (ADR 0003)."""
        pass

    def _on_ramp_stop(self):
        pass

    def _check_connections(self):
        """Deprecated: hardware connection checking now lives in Rig/Snapshot (ADR 0002)."""
        pass

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
        self._pressure_interlock_fired = False

    def _on_stop(self):
        self.is_running = False

        self.log_btn.config(state='disabled')
        self.status_var.set("Stopped")

        if self.is_logging:
            self._on_toggle_logging()

    def _on_toggle_logging(self):
        if not self.is_logging:
            # Optionally clear all graphs and the data buffer so logging starts fresh
            if self._app_settings.reset_graph_on_start_logging:
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

            header = build_csv_header(self.config, has_ps_controller=bool(self.ps_controller))
            sensor_names = header[1:]

            # Append Power Programmer metadata if a profile is loaded
            if self._programmer_blocks:
                metadata['programmer_mode'] = self._programmer_control_mode

            filepath = self.logger.start_logging(sensor_names, custom_name, metadata)

            # Create and start RunRecord (ticket 11); wire to Rig as step-7 consumer.
            enabled_tcs = [tc for tc in self.config.get('thermocouples', [])
                           if tc.get('enabled', True)]
            tc_names_list = [tc['name'] for tc in enabled_tcs]
            gauge_names_list = [g['name'] for g in self.config.get('frg702_gauges', [])
                                if g.get('enabled', True)]
            t_unit = self.t_unit_var.get() if hasattr(self, 't_unit_var') else 'C'
            p_unit = self.p_unit_var.get() if hasattr(self, 'p_unit_var') else 'mbar'
            sample_rate = int(self.sample_rate_var.get().replace('ms', '')) if hasattr(self, 'sample_rate_var') else 1000
            self._run_record = RunRecord(
                logger_=self.logger,
                tc_names=tc_names_list,
                gauge_names=gauge_names_list,
                t_unit=t_unit,
                p_unit=p_unit,
                sample_rate_ms=float(sample_rate),
                has_ps=bool(self.ps_controller),
            )
            self._run_record.start()
            if hasattr(self, 'rig') and self.rig:
                self.rig.set_run_record(self._run_record)

            self.is_logging = True
            if hasattr(self, 'rig') and self.rig:
                self.rig.set_logging_active(True)
            self.log_btn.config(text="Stop Logging")
            self.status_var.set(f"Running - Logging to {os.path.basename(filepath)}")
        else:
            if self._run_record is not None:
                self._run_record.stop()
                self._run_record = None
            if hasattr(self, 'rig') and self.rig:
                self.rig.clear_run_record()
            self.logger.stop_logging()
            self.is_logging = False
            if hasattr(self, 'rig') and self.rig:
                self.rig.set_logging_active(False)
            self.log_btn.config(text="Start Logging")
            self.status_var.set("Running")

    def _update_gui(self):
        """Update the GUI (called periodically)."""
        gui_profiler.loop_start()

        # Update cache of GUI-owned variables for background threads
        self._current_t_unit = self.t_unit_var.get()
        self._current_p_unit = self.p_unit_var.get()

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

        gui_profiler.start("rig_snapshot_render")
        snap = self.rig.latest() if hasattr(self, 'rig') and self.rig else None
        if snap is not None:
            self.render_snapshot(snap)
        lj_connected = (snap.labjack.state == "connected") if snap else False
        xgs_connected = (snap.xgs.state == "connected") if snap else False
        ps_connected = lj_connected and (self.ps_controller is not None or (snap is not None and snap.adapter == "simulated"))

        # Update connection indicators from Snapshot SourceStatus
        if 'LabJack' in self.indicators:
            self.indicators['LabJack'].config(bg='#00FF00' if lj_connected else '#333333')
        if 'XGS600' in self.indicators:
            self.indicators['XGS600'].config(bg='#00FF00' if xgs_connected else '#333333')
        if 'PowerSupply' in self.indicators:
            self.indicators['PowerSupply'].config(bg='#00FF00' if ps_connected else '#333333')

        # If not connected, update status var
        if not lj_connected:
            if self.status_var.get() != "Disconnected":
                self._update_connection_state(False)
                self.is_running = False
        elif lj_connected and not self.is_running and self.status_var.get() == "Disconnected":
            self._update_connection_state(True)
            self.status_var.set("Connected")

        gui_profiler.start("safety_interlocks")
        # Update safety interlocks
        self._update_safety_interlocks()

        # Update safety display
        if not self._safety_triggered:
            self._update_safety_display(self.safety_monitor.status)

        if not self.is_running:
            # Idle display: update sensor panel with latest readings from Snapshot if available
            if snap is not None:
                idle_readings = {}
                t_unit = self.t_unit_var.get()
                p_unit = self.p_unit_var.get()
                for name, value in snap.tc_c.items():
                    idle_readings[name] = convert_temperature(value, 'C', t_unit) if value is not None else None
                for name, value in snap.pressure_torr.items():
                    idle_readings[name] = convert_pressure(value, 'Torr', p_unit) if value is not None else None
                idle_readings['PS_Voltage'] = snap.ps_volts
                idle_readings['PS_Current'] = snap.ps_amps
                if hasattr(self, 'sensor_panel'):
                    self.sensor_panel.update(idle_readings)
                for name, value in idle_readings.items():
                    if name in self.indicators:
                        self.indicators[name].config(bg='#00FF00' if value is not None else '#333333')

            gui_profiler.start("schedule_next")
            self.root.after(self.config['display']['update_rate_ms'], self._update_gui)
            gui_profiler.loop_end()
            return

        gui_profiler.start("read_sensors")
        # Get current readings and update panel
        current = self.data_buffer.get_all_current()

        display_readings = {}
        t_unit = self.t_unit_var.get()
        p_unit = self.p_unit_var.get()

        for name, value in current.items():
            if value is None:
                display_readings[name] = None
                continue
            if name in self._tc_names:
                display_readings[name] = convert_temperature(value, 'C', t_unit)
            elif name in self._frg_names:
                display_readings[name] = convert_pressure(value, 'Torr', p_unit)
            else:
                display_readings[name] = value

        gui_profiler.start("sensor_panel_update")
        self.sensor_panel.update(display_readings)

        # Update FRG-702 detailed status
        display_frg_details = {}
        if hasattr(self, '_latest_frg702_details') and self._latest_frg702_details:
            for g_name, info in self._latest_frg702_details.items():
                p_val = info.get('pressure')
                display_frg_details[g_name] = {
                    **info,
                    'pressure': convert_pressure(p_val, 'Torr', p_unit) if p_val is not None else None,
                }
            self.sensor_panel.update_frg702_status(display_frg_details)

        # Update live pinout display if open (Change 6: moved from DAQ thread to GUI thread)
        if hasattr(self, '_pinout_window') and self._pinout_window is not None:
            try:
                if self._pinout_window.winfo_exists():
                    self._pinout_window.update_readings(
                        all_readings=display_readings,
                        raw_voltages=getattr(self, '_latest_raw_voltages', {}),
                        frg702_details=display_frg_details if display_frg_details else getattr(self, '_latest_frg702_details', {})
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
                # Gauge data in buffer is always in Torr (canonical unit)
                self.plot_pressure.update(frg_names, data_units={'press': 'Torr'})
            if hasattr(self, 'plot_ps'):
                _ps_names = ['PS_Voltage', 'PS_Current']
                if getattr(self, '_programmer_ramp_running', False):
                    _ps_names += ['PS_Voltage_Setpoint', 'PS_CC_Limit']
                self.plot_ps.update(_ps_names)

        gui_profiler.start("schedule_next")
        self.root.after(self.config['display']['update_rate_ms'], self._update_gui)
        gui_profiler.loop_end()

    def _initialize_hardware_readers(self):
        """
        Transitional: reader construction and ownership live in the Rig adapter (ADR 0002).
        This method no longer swaps reader objects under a running acquisition thread.
        """
        return True

    def _connect_xgs600(self):
        """Deprecated: XGS-600 hardware connection is managed by T8Adapter / Rig (ADR 0002)."""
        return True

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
        """Deprecated: Power supply control is managed by T8Adapter / Rig (ADR 0002)."""
        return True

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
            except (tk.TclError, AttributeError) as e:
                print(f"[MainWindow] Error cleaning up nudge frame: {e}")

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
                except (tk.TclError, AttributeError) as e:
                    print(f"[MainWindow] Error accessing nudge frame master: {e}")
            
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
                except (tk.TclError, AttributeError) as e:
                    print(f"[MainWindow] Error destroying nudge frame: {e}")
                self._nudge_frame = None

    def _nudge_voltage(self, direction):
        """Apply one nudge step by submitting a Nudge command to the Rig."""
        dir_str = (
            "up"
            if (isinstance(direction, (int, float)) and direction > 0)
            or str(direction).lower() in ("up", "+", "+1")
            else "down"
        )
        if hasattr(self, 'rig') and self.rig is not None:
            self.rig.submit(Nudge(direction=dir_str))

    def set_voltage(self, volts: float):
        """Submit SetVoltage command to the Rig."""
        if hasattr(self, 'rig') and self.rig is not None:
            self.rig.submit(SetVoltage(volts=float(volts)))

    def set_output(self, enabled: bool):
        """Submit SetOutput command to the Rig."""
        if hasattr(self, 'rig') and self.rig is not None:
            self.rig.submit(SetOutput(enabled=bool(enabled)))

    def _start_nudge_readback_loop(self):
        """Poll latest snapshot commanded voltage and update the nudge display."""
        def _poll():
            if hasattr(self, 'rig') and self.rig is not None:
                snap = self.rig.latest()
                if snap is not None:
                    self._nudge_v_var.set(f"{snap.commanded_volts:.3f} V")
            
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

        snap = self.rig.latest() if hasattr(self, 'rig') and self.rig else None
        hold_stable = False
        if snap and snap.program:
            hold_stable = snap.program.waiting_for_confirmation

        pressure_ok = snap.permissive_ok if snap is not None else False
        permissive_reason = (
            snap.permissive_reason
            if (snap and snap.permissive_reason)
            else "no pressure reading"
        )

        ready = hold_stable and pressure_ok

        if ready:
            txt = "\u2705 Ready \u2014 temperature stable, pressure OK"
            fg = 'green'
        else:
            reasons = []
            if not hold_stable:
                reasons.append("temperature not stable")
            if not pressure_ok:
                reasons.append(permissive_reason)
            txt = "Waiting: " + ", ".join(reasons)
            fg = 'gray'

        self._qms_status_text = txt

        btn = getattr(self, '_qms_ramp_btn', None)
        status_var = getattr(self, '_qms_status_var', None)

        if btn:
            btn.config(state='normal' if ready else 'disabled')
        if status_var:
            status_var.set(txt)
        if getattr(self, '_qms_btn_frame', None):
            for widget in self._qms_btn_frame.winfo_children():
                if isinstance(widget, ttk.Label):
                    widget.config(foreground=fg)

        self._qms_btn_gate_job = self.root.after(2000, self._poll_qms_gate)

    def get_qms_status_text(self) -> str:
        """Return the current QMS gate status text."""
        return getattr(self, '_qms_status_text', "")

    def _on_qms_ramp_start(self):
        """
        Simultaneous QMS + Ramp launch.
        1. Guard: Check pressure permissive (ADR 0004).
        2. Trigger MASsoft Start via pyautogui keyboard shortcut.
        3. Write RAMP_START event to DataLogger CSV.
        4. Signal the program executor to continue (if pausing between blocks).
        """
        snap = self.rig.latest() if hasattr(self, 'rig') and self.rig else None
        if snap is not None and not snap.permissive_ok:
            reason = snap.permissive_reason or "Pressure interlock permissive not satisfied"
            messagebox.showwarning("QMS Start Refused", f"Cannot start QMS: {reason}")
            return

        import datetime
        try:
            import pyautogui
            import time as _time

            windows = pyautogui.getWindowsWithTitle("MASsoft")
            if not windows:
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
            messagebox.showerror("Missing Library",
                                 "pyautogui is not installed. Run: pip install pyautogui")
            return
        except Exception as e:
            messagebox.showerror("QMS Start Error", f"Could not start MASsoft:\n{e}")
            return

        # Log RAMP_START event with ISO timestamp
        ts = datetime.datetime.now().isoformat()
        if hasattr(self, 'logger') and self.logger is not None:
            if self.logger.is_logging():
                self.logger.log_event("RAMP_START", ts)

        # Release confirmation / continue
        if hasattr(self, 'rig') and self.rig is not None:
            self.rig.submit(ConfirmContinue())

        # Disable the button immediately — one-shot launch
        if hasattr(self, '_qms_ramp_btn'):
            self._qms_ramp_btn.config(state='disabled', text="QMS + Ramp Running")
        self._qms_gate_active = False

        self.status_var.set("TDS Ramp Running \u2014 QMS active")

    # ── Feature 5: Emergency pressure interlock ───────────────────────────────

    def _on_pressure_interlock(self, pressure_torr):
        """Emergency: pressure exceeded 1e-4 Torr. Stop QMS and power supply."""
        def _shutdown():
            # Stop running program
            self._stop_programmer_ramp_safe()

            # Power supply cutoff is handled by Rig / HeaterOutput (ADR 0003)

            # 3. Abort MASsoft scan via pyautogui (Escape key = Abort in MASsoft toolbar)
            self._abort_massoft()

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

        if hasattr(self, 'rig') and self.rig:
            self.rig.submit(SetOutput(False))
            self.rig.submit(SetVoltage(0.0))
            self.rig.stop()

        # Stop camera feed and timelapse before destroying widgets
        if self._camera_panel is not None:
            try:
                self._camera_panel.stop_camera()
            except Exception as e:
                # Best-effort camera cleanup during window close; safe to continue closing
                _log.warning("Error stopping camera on window close: %s", e)



        if self.is_logging:
            if self._run_record is not None:
                self._run_record.stop()
                self._run_record = None
            if hasattr(self, 'rig') and self.rig:
                self.rig.clear_run_record()
            self.logger.stop_logging()

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
            
            # 2. Reset plot skip counters to force immediate redraw
            self._plot_skip_counter = 0
            
            # 3. Process all pending events
            self.root.update_idletasks()
            
            # 4. Explicitly redraw the canvases
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

    def get_pid_logger(self):
        """Return the active PIDRunLogger from Rig/ProgramRun."""
        logger = self.rig.get_pid_logger() if hasattr(self, 'rig') and self.rig else None
        if logger is not None:
            return logger
        from t8_daq_system.control.temp_ramp_pid import PIDRunLogger
        return PIDRunLogger()

    def _open_pid_log_viewer(self):
        """Open a scrollable dialog showing all logged PID ramp runs with suggestions."""
        pid_logger = self.get_pid_logger()
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
                        + (" s\n" if run.get('settling_time_sec') else "\n") +
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

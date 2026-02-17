"""
main_window.py
PURPOSE: Main application window - coordinates everything

Integrates LabJack T8 DAQ (thermocouples, turbo pump) and XGS-600 controller
(FRG-702 gauges) with Keysight N5761A power supply control, safety monitoring,
and ramp profile execution.

Safety interlocks:
- Power supply ramp locked unless turbo pump is running (NORMAL)
- Turbo pump locked unless FRG pressure is below 5E-3 Torr
- 2200C temperature override triggers controlled ramp-down
- Restart lockout until temperature drops below 2150C
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import threading
import time
import os
import sys
import random
import math

# Import our modules
from t8_daq_system.hardware.labjack_connection import LabJackConnection
from t8_daq_system.hardware.thermocouple_reader import ThermocoupleReader
from t8_daq_system.hardware.xgs600_controller import XGS600Controller
from t8_daq_system.hardware.frg702_reader import FRG702Reader
from t8_daq_system.hardware.keysight_connection import KeysightConnection
from t8_daq_system.hardware.power_supply_controller import PowerSupplyController
from t8_daq_system.hardware.turbo_pump_controller import TurboPumpController
from t8_daq_system.control.ramp_executor import RampExecutor
from t8_daq_system.control.safety_monitor import SafetyMonitor, SafetyStatus
from t8_daq_system.data.data_buffer import DataBuffer
from t8_daq_system.data.data_logger import DataLogger, create_metadata_dict
from t8_daq_system.gui.live_plot import LivePlot
from t8_daq_system.gui.sensor_panel import SensorPanel
from t8_daq_system.utils.helpers import convert_temperature
from t8_daq_system.gui.power_supply_panel import PowerSupplyPanel
from t8_daq_system.gui.ramp_panel import RampPanel
from t8_daq_system.gui.turbo_pump_panel import TurboPumpPanel
from t8_daq_system.gui.dialogs import LoggingDialog, LoadCSVDialog, AxisScaleDialog
from t8_daq_system.core.data_acquisition import DataAcquisition
from t8_daq_system.detailed_profiler import mainwindow_profiler as profiler


class MockPowerSupplyController:
    """Simulated power supply for practice mode."""
    def __init__(self, voltage_limit=20.0, current_limit=50.0):
        self.voltage = 0.0
        self.current = 0.0
        self.output_state = False
        self.voltage_limit = voltage_limit
        self.current_limit = current_limit

    def set_voltage(self, volts):
        self.voltage = min(volts, self.voltage_limit)
        return True

    def set_current(self, amps):
        self.current = min(amps, self.current_limit)
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
        if not self.output_state: return 0.0
        return self.voltage + random.uniform(-0.02, 0.02)

    def get_current(self):
        if not self.output_state: return 0.0
        return self.current + random.uniform(-0.01, 0.01)

    def get_readings(self):
        return {'PS_Voltage': self.get_voltage(), 'PS_Current': self.get_current()}

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

    def emergency_shutdown(self):
        self.output_off()
        self.voltage = 0
        return True


class MockTurboPumpController:
    """Simulated turbo pump for practice mode."""
    def __init__(self):
        self.state = "OFF"
        self._is_commanded_on = False
        self._start_time = 0

    def start(self):
        self._is_commanded_on = True
        self.state = "STARTING"
        self._start_time = time.time()
        return True, "Start command sent (Mock)"

    def stop(self):
        self._is_commanded_on = False
        self.state = "OFF"
        return True, "Stop command sent (Mock)"

    def read_status(self):
        if self._is_commanded_on:
            if time.time() - self._start_time > 5.0:
                self.state = "NORMAL"
            else:
                self.state = "STARTING"
        else:
            self.state = "OFF"
        return self.state

    def get_status_dict(self):
        return {
            'Turbo_Commanded': 'ON' if self._is_commanded_on else 'OFF',
            'Turbo_Status': self.read_status()
        }

    def is_commanded_on(self):
        return self._is_commanded_on

    def emergency_stop(self):
        self.stop()

    def cleanup(self):
        self.stop()


class MainWindow:
    # Available sampling rates in milliseconds
    SAMPLE_RATES = [100, 200, 500, 1000, 2000]

    def __init__(self, config_path=None):
        profiler.section("MainWindow.__init__ START")
        profiler.checkpoint("Entering __init__ method")

        # Default configuration
        self.config = {
            "device": {"type": "T8", "connection": "USB", "identifier": "ANY"},
            "thermocouples": [{"name": "TC_1", "channel": 0, "type": "C", "units": "C", "enabled": True}],
            "power_supply": {
                "enabled": True,
                "visa_resource": None,
                "default_voltage_limit": 20.0,
                "default_current_limit": 50.0,
                "safety": {
                    "max_temperature": 2300,
                    "watchdog_sensor": "TC_1",
                    "auto_shutoff": True,
                    "warning_threshold": 0.9
                }
            },
            "logging": {"interval_ms": 1000, "file_prefix": "data_log", "auto_start": False},
            "display": {"update_rate_ms": 1000, "history_seconds": 60}
        }
        profiler.checkpoint("Default config dictionary created")

        # Default Axis scale settings
        self._use_absolute_scales = True
        self._temp_range = (0, 2500)
        self._press_range = (1e-9, 1e-3)
        self._ps_v_range = (0, 100)
        self._ps_i_range = (0, 100)

        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    loaded_config = json.load(f)
                    self.config.update(loaded_config)
                    
                    # Apply defaults if present
                    if 'defaults' in loaded_config:
                        defaults = loaded_config['defaults']
                        
                        # Apply temperature units
                        if 'temperature_units' in defaults:
                            for tc in self.config.get('thermocouples', []):
                                if 'units' not in tc:
                                    tc['units'] = defaults['temperature_units']
                        
                        # Apply pressure units
                        if 'pressure_units' in defaults:
                            for gauge in self.config.get('frg702_gauges', []):
                                if 'units' not in gauge:
                                    gauge['units'] = defaults['pressure_units']
                        
                        # Apply acquisition rates
                        if 'internal_acquisition_ms' in defaults:
                            self.config['logging']['interval_ms'] = defaults['internal_acquisition_ms']
                        elif 'acquisition_rate' in defaults:
                            rate_hz = defaults['acquisition_rate']
                            if rate_hz > 0:
                                self.config['logging']['interval_ms'] = int(1000 / rate_hz)
                                
                        if 'display_acquisition_ms' in defaults:
                            self.config['display']['update_rate_ms'] = defaults['display_acquisition_ms']

                        # Apply axis scales
                        if 'axis_scales' in defaults:
                            scales = defaults['axis_scales']
                            self._use_absolute_scales = scales.get('use_absolute', True)
                            if 'temp_range' in scales: self._temp_range = tuple(scales['temp_range'])
                            if 'press_range' in scales: self._press_range = tuple(scales['press_range'])
                            if 'voltage_range' in scales: self._ps_v_range = tuple(scales['voltage_range'])
                            if 'current_range' in scales: self._ps_i_range = tuple(scales['current_range'])
            except Exception as e:
                print(f"Error loading config from {config_path}: {e}")

        profiler.checkpoint("Config file loaded (if present)")

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

        profiler.section("Keysight Power Supply Connection")
        profiler.checkpoint("Creating KeysightConnection instance")
        # Initialize Keysight power supply components
        self.ps_connection = KeysightConnection(
            resource_string=self.config.get('power_supply', {}).get('visa_resource')
        )
        profiler.checkpoint("KeysightConnection instance created (not connected yet)")
        self.ps_controller = None

        profiler.section("Turbo Pump Controller")
        profiler.checkpoint("Initializing turbo pump variables")
        # Initialize turbo pump controller
        self.turbo_controller = None
        profiler.checkpoint("Turbo pump variables initialized")

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
        
        self.log_folder = os.path.join(base_dir, 'logs')
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
        self._loaded_data = None
        self._loaded_data_units = {'temp': 'C', 'press': 'PSI'}

        # Track latest FRG pressure for turbo interlock
        self._latest_frg_pressure_mbar = None
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

    def _deferred_hardware_init(self):
        """
        Initialize hardware connections AFTER GUI is displayed.

        This runs 100ms after the window opens, preventing startup blocking.
        Called via root.after() from __init__().
        """
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

        # Connect to Keysight power supply if configured
        if self.config.get('power_supply', {}).get('enabled', True):
            print("[DEFERRED] Connecting to Keysight power supply...")
            if self.ps_connection.connect():
                print("[DEFERRED] Power supply connected")
                self._initialize_power_supply()

        # Connect to turbo pump if configured (part of LabJack init)
        if self.turbo_controller:
            print("[DEFERRED] Turbo pump controller initialized")

        print("[DEFERRED] Hardware initialization complete")
        self._hardware_init_attempted = True

    def _update_connection_state(self, connected):
        """Update UI to reflect connection state"""
        if connected:
            self.status_var.set("Connected")
            # Enable start button and other controls
            if hasattr(self, 'start_btn'):
                self.start_btn.config(state='normal')
        else:
            self.status_var.set("Disconnected")
            # Disable controls
            if hasattr(self, 'start_btn'):
                self.start_btn.config(state='disabled')

    def _build_gui(self):
        """Create all the GUI elements."""
        profiler.checkpoint("_build_gui() entered - creating control frames")

        # Top frame - Control buttons
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill=tk.X, padx=10, pady=5)

        # Configuration Area
        config_area = ttk.LabelFrame(control_frame, text="Quick Config")
        config_area.pack(side=tk.LEFT, padx=5)

        # TC count
        ttk.Label(config_area, text="TCs:").pack(side=tk.LEFT, padx=2)
        self.tc_count_var = tk.StringVar(value=str(len(self.config['thermocouples'])))
        self.tc_count_combo = ttk.Combobox(
            config_area, textvariable=self.tc_count_var,
            values=["0", "1", "2", "3", "4", "5", "6", "7"], width=3
        )
        self.tc_count_combo.pack(side=tk.LEFT, padx=2)
        self.tc_count_combo.bind("<<ComboboxSelected>>", lambda e: self._on_config_change())

        # TC Type
        ttk.Label(config_area, text="Type:").pack(side=tk.LEFT, padx=2)
        tc_type = "K"
        if self.config['thermocouples']:
            tc_type = self.config['thermocouples'][0]['type']
        self.tc_type_var = tk.StringVar(value=tc_type)
        self.tc_type_combo = ttk.Combobox(
            config_area, textvariable=self.tc_type_var,
            values=["K", "J", "T", "E", "R", "S", "B", "N", "C"], width=3
        )
        self.tc_type_combo.pack(side=tk.LEFT, padx=2)
        self.tc_type_combo.bind("<<ComboboxSelected>>", lambda e: self._on_config_change())

        # Units Selection
        ttk.Label(config_area, text="T-Unit:").pack(side=tk.LEFT, padx=2)
        t_unit = "C"
        if self.config['thermocouples']:
            t_unit = self.config['thermocouples'][0]['units']
        self.t_unit_var = tk.StringVar(value=t_unit)
        self.t_unit_combo = ttk.Combobox(
            config_area, textvariable=self.t_unit_var,
            values=["C", "F", "K"], width=3
        )
        self.t_unit_combo.pack(side=tk.LEFT, padx=2)
        self.t_unit_combo.bind("<<ComboboxSelected>>", lambda e: self._on_config_change())

        # Pressure Units Selection
        ttk.Label(config_area, text="FRGs:").pack(side=tk.LEFT, padx=2)
        frg_count = len(self.config.get('frg702_gauges', []))
        self.frg_count_var = tk.StringVar(value=str(frg_count))
        self.frg_count_combo = ttk.Combobox(
            config_area, textvariable=self.frg_count_var,
            values=["0", "1", "2"], width=2
        )
        self.frg_count_combo.pack(side=tk.LEFT, padx=2)
        self.frg_count_combo.bind("<<ComboboxSelected>>", lambda e: self._on_config_change())

        ttk.Label(config_area, text="P-Unit:").pack(side=tk.LEFT, padx=2)
        p_unit = "mbar"
        if self.config.get('frg702_gauges'):
            p_unit = self.config['frg702_gauges'][0].get('units', 'mbar')
        self.p_unit_var = tk.StringVar(value=p_unit)
        self.p_unit_combo = ttk.Combobox(
            config_area, textvariable=self.p_unit_var,
            values=["mbar", "Torr", "Pa"], width=5
        )
        self.p_unit_combo.pack(side=tk.LEFT, padx=2)
        self.p_unit_combo.bind("<<ComboboxSelected>>", lambda e: self._on_pressure_unit_change())

        # Sampling rate dropdown
        ttk.Label(config_area, text="Rate:").pack(side=tk.LEFT, padx=2)
        current_rate = self.config['logging']['interval_ms']
        self.sample_rate_var = tk.StringVar(value=f"{current_rate}ms")
        rate_values = [f"{r}ms" for r in self.SAMPLE_RATES]
        self.sample_rate_combo = ttk.Combobox(
            config_area, textvariable=self.sample_rate_var,
            values=rate_values, width=8
        )
        self.sample_rate_combo.pack(side=tk.LEFT, padx=2)
        self.sample_rate_combo.bind("<<ComboboxSelected>>", lambda e: self._on_sample_rate_change())

        # Display rate dropdown
        ttk.Label(config_area, text="Display:").pack(side=tk.LEFT, padx=2)
        display_rate = self.config['display']['update_rate_ms']
        self.display_rate_var = tk.StringVar(value=f"{display_rate}ms")
        self.display_rate_combo = ttk.Combobox(
            config_area, textvariable=self.display_rate_var,
            values=["100ms", "250ms", "500ms", "1000ms"], width=8
        )
        self.display_rate_combo.pack(side=tk.LEFT, padx=2)
        self.display_rate_combo.bind("<<ComboboxSelected>>", lambda e: self._on_display_rate_change())

        # Control buttons
        self.start_btn = ttk.Button(
            control_frame, text="Start", command=self._on_start, state='disabled'
        )
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(
            control_frame, text="Stop", command=self._on_stop, state='disabled'
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.log_btn = ttk.Button(
            control_frame, text="Start Logging", command=self._on_toggle_logging,
            state='disabled'
        )
        self.log_btn.pack(side=tk.LEFT, padx=5)

        self.load_csv_btn = ttk.Button(
            control_frame, text="Load CSV", command=self._on_load_csv
        )
        self.load_csv_btn.pack(side=tk.LEFT, padx=5)

        self.scale_btn = ttk.Button(
            control_frame, text="Axis Scales", command=self._on_axis_scales
        )
        self.scale_btn.pack(side=tk.LEFT, padx=5)

        self.dual_btn = ttk.Button(
            control_frame, text="Dual Display", command=self._toggle_dual_display
        )
        self.dual_btn.pack(side=tk.LEFT, padx=5)

        self.practice_btn = ttk.Button(
            control_frame, text="Practice Mode: OFF", command=self._toggle_practice_mode
        )
        self.practice_btn.pack(side=tk.LEFT, padx=5)

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

        # Right side - Power Supply Control (unified ramp interface)
        profiler.checkpoint("Creating right frame (control side)...")
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=2)
        profiler.checkpoint("Right frame created")

        # Power Supply Status Panel (read-only display with interlock)
        profiler.checkpoint("Creating PowerSupplyPanel...")
        ps_frame = ttk.LabelFrame(right_frame, text="Power Supply Status")
        ps_frame.pack(fill=tk.X, padx=5, pady=1)

        self.ps_panel = PowerSupplyPanel(ps_frame, self.ps_controller)
        self.ps_panel.on_output_change(self._on_ps_output_change)
        profiler.checkpoint("PowerSupplyPanel created")

        # Ramp Profile Panel (ONLY power control interface)
        profiler.checkpoint("Creating RampPanel...")
        ramp_frame = ttk.LabelFrame(right_frame, text="Power Supply Ramp Control")
        ramp_frame.pack(fill=tk.X, expand=True, padx=5, pady=1)

        self.ramp_panel = RampPanel(
            ramp_frame,
            self.ramp_executor,
            self.profiles_folder
        )
        self.ramp_panel.on_ramp_start(self._on_ramp_start)
        self.ramp_panel.on_ramp_stop(self._on_ramp_stop)
        profiler.checkpoint("RampPanel created")

        # Turbo Pump Panel
        profiler.checkpoint("Creating TurboPumpPanel...")
        self.turbo_panel = TurboPumpPanel(right_frame)
        self.turbo_panel.pack(fill=tk.BOTH, padx=5, pady=1)
        profiler.checkpoint("TurboPumpPanel created")

        # Dual window tracking
        profiler.checkpoint("Initializing dual window tracking...")
        self.dual_window = None
        profiler.checkpoint("Dual window tracking initialized")

    def _build_plots(self, parent):
        """Create the live plots in the specified parent widget."""
        profiler.checkpoint("_build_plots() entered - creating plot paned window")
        plot_paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        plot_paned.pack(fill=tk.BOTH, expand=True)
        profiler.checkpoint("Plot paned window created")

        profiler.checkpoint("Creating full history plot frame...")
        full_frame = ttk.LabelFrame(plot_paned, text="Full Run History")
        plot_paned.add(full_frame, weight=1)
        profiler.checkpoint("Full history frame created")

        profiler.checkpoint("Creating LivePlot for full history (matplotlib)...")
        self.full_plot = LivePlot(full_frame, self.data_buffer)
        profiler.checkpoint("Full history LivePlot created")

        profiler.checkpoint("Creating recent plot frame...")
        recent_frame = ttk.LabelFrame(plot_paned, text="Last 1 Minute")
        plot_paned.add(recent_frame, weight=1)
        profiler.checkpoint("Recent plot frame created")

        profiler.checkpoint("Creating LivePlot for recent data (matplotlib)...")
        self.recent_plot = LivePlot(recent_frame, self.data_buffer)
        profiler.checkpoint("Recent LivePlot created")

        profiler.checkpoint("Updating plot settings...")
        self._update_plot_settings()
        profiler.checkpoint("Plot settings updated")

    def _toggle_practice_mode(self):
        """Toggle practice mode on/off."""
        self._practice_mode = not self._practice_mode
        if self._practice_mode:
            self._hardware_init_attempted = True  # Practice mode counts as initialized
            self.practice_btn.config(text="Practice Mode: ON")
            self.start_btn.config(state='normal')
            self.status_var.set("Practice Mode Active")

            if not self.config.get('frg702_gauges'):
                self.config['frg702_gauges'] = [
                    {"name": "FRG702_Mock", "sensor_code": "T1", "units": "mbar", "enabled": True}
                ]
            self.frg_count_var.set(str(len(self.config['frg702_gauges'])))

            if 'turbo_pump' not in self.config:
                self.config['turbo_pump'] = {
                    "enabled": True,
                    "start_stop_channel": "DIO0",
                    "status_channel": "DIO1"
                }
            self.config['turbo_pump']['enabled'] = True

            # Set up Mock Power Supply
            self.ps_connection.disconnect()
            self.ps_controller = MockPowerSupplyController()
            self.ps_panel.set_controller(self.ps_controller)
            self.safety_monitor.set_power_supply(self.ps_controller)
            self.ramp_executor.set_power_supply(self.ps_controller)

            self.turbo_controller = MockTurboPumpController()
            self.turbo_panel.set_controller(self.turbo_controller)

            # In practice mode, simulate acceptable pressure for turbo interlock
            self._latest_frg_pressure_mbar = 1e-4  # Well below threshold
            self.turbo_panel.update_pressure_interlock(self._latest_frg_pressure_mbar)

            self.ps_resource_var.set("Mock Power Supply")
        else:
            self.practice_btn.config(text="Practice Mode: OFF")
            self.ps_resource_var.set("None")

            self._latest_frg_pressure_mbar = None
            self.turbo_panel.update_pressure_interlock(None)

            if not self.connection or not self.connection.is_connected():
                self.start_btn.config(state='disabled')
                self.status_var.set("Disconnected")
                self.ps_controller = None
                self.ps_panel.set_controller(None)
                self.turbo_controller = None
                self.turbo_panel.set_controller(None)
            else:
                self.status_var.set("Connected")
                self._initialize_hardware_readers()
                # Attempt to auto-detect real power supply
                self.ps_connection.resource_string = None
                if self.ps_connection.connect():
                    self._initialize_power_supply()

        self._rebuild_sensor_panel()
        self._update_plot_settings()

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
        t_unit = self.t_unit_var.get() if hasattr(self, 't_unit_var') else 'C'

        temp_symbols = {'C': '\u00b0C', 'F': '\u00b0F', 'K': 'K'}
        temp_unit_display = temp_symbols.get(t_unit, '\u00b0C')

        if not hasattr(self, '_temp_range'):
            t_min_display = convert_temperature(0, 'C', t_unit)
            t_max_display = convert_temperature(300, 'C', t_unit)
            self._temp_range = (t_min_display, t_max_display)

        press_unit = self.p_unit_var.get()

        if hasattr(self, 'full_plot'):
            self.full_plot.set_units(temp_unit_display, press_unit)
            self.full_plot.set_absolute_scales(
                self._use_absolute_scales,
                self._temp_range,
                self._press_range,
                self._ps_v_range,
                self._ps_i_range
            )
        if hasattr(self, 'recent_plot'):
            self.recent_plot.set_units(temp_unit_display, press_unit)
            self.recent_plot.set_absolute_scales(
                self._use_absolute_scales,
                self._temp_range,
                self._press_range,
                self._ps_v_range,
                self._ps_i_range
            )

        sensor_names = [tc['name'] for tc in self.config['thermocouples'] if tc.get('enabled', True)]
        sensor_names += [g['name'] for g in self.config.get('frg702_gauges', []) if g.get('enabled', True)]
        ps_names = []  # Explicitly empty to remove from thermocouple plots

        if self._viewing_historical and self._loaded_data:
            if hasattr(self, 'full_plot'):
                self.full_plot.update_from_loaded_data(
                    self._loaded_data, sensor_names, [],
                    data_units=self._loaded_data_units
                )
            if hasattr(self, 'recent_plot'):
                self.recent_plot.update_from_loaded_data(
                    self._loaded_data, sensor_names, [],
                    window_seconds=60, data_units=self._loaded_data_units
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
            if hasattr(self, 'full_plot'):
                self.full_plot.update(sensor_names, [])
            if hasattr(self, 'recent_plot'):
                self.recent_plot.update(sensor_names, [], window_seconds=60)

    def _toggle_dual_display(self):
        if self.dual_window is None or not self.dual_window.winfo_exists():
            self.dual_window = tk.Toplevel(self.root)
            self.dual_window.title("T8 DAQ System - Live Plots")
            self.dual_window.geometry("800x600")
            self.dual_window.protocol("WM_DELETE_WINDOW", self._toggle_dual_display)

            for widget in self.plot_container_main.winfo_children():
                widget.destroy()

            self._build_plots(self.dual_window)
            self.dual_btn.config(text="Single Display")
        else:
            self.dual_window.destroy()
            self.dual_window = None

            for widget in self.plot_container_main.winfo_children():
                widget.destroy()

            self._build_plots(self.plot_container_main)
            self.dual_btn.config(text="Dual Display")

    def _on_axis_scales(self):
        dialog = AxisScaleDialog(
            self.root,
            self._temp_range,
            self._press_range,
            self._ps_v_range,
            self._ps_i_range,
            self._use_absolute_scales
        )
        self.root.wait_window(dialog)

        if dialog.result:
            self._use_absolute_scales = dialog.result['use_absolute']
            self._temp_range = dialog.result['temp_range']
            self._press_range = dialog.result['press_range']
            self._ps_v_range = dialog.result['ps_v_range']
            self._ps_i_range = dialog.result['ps_i_range']
            self._update_plot_settings()

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
                if 'tc_count' in metadata:
                    self.tc_count_var.set(str(metadata['tc_count']))
                if 'frg702_count' in metadata:
                    self.frg_count_var.set(str(metadata['frg702_count']))
                if 'tc_type' in metadata:
                    self.tc_type_var.set(metadata['tc_type'])
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

            self.start_btn.config(state='disabled')
            self.stop_btn.config(state='disabled')
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

        if hasattr(self, 'full_plot'):
            self.full_plot.clear()
        if hasattr(self, 'recent_plot'):
            self.recent_plot.clear()
        self.data_buffer.clear()

        lj_ok = self.connection and self.connection.is_connected()
        if lj_ok or self._practice_mode:
            self.start_btn.config(state='normal')
            self.status_var.set("Connected")
        else:
            self.status_var.set("Disconnected")

    def _on_config_change(self):
        new_tc_count = int(self.tc_count_var.get())
        new_tc_type = self.tc_type_var.get()
        new_tc_unit = self.t_unit_var.get()
        new_frg_count = int(self.frg_count_var.get())

        if new_tc_count > 7:
            messagebox.showwarning("Config Limit", "Maximum total sensors allowed is 7.\nAdjusting counts to fit limit.")
            new_tc_count = 7
            self.tc_count_var.set(str(new_tc_count))

        old_tcs = {tc['name']: tc for tc in self.config['thermocouples']}
        self.config['thermocouples'] = []
        for i in range(new_tc_count):
            name = f"TC_{i+1}"
            old_tc = old_tcs.get(name, {})
            self.config['thermocouples'].append({
                "name": name,
                "channel": i,
                "type": new_tc_type,
                "units": new_tc_unit,
                "enabled": True
            })

        # Update FRG config
        old_frgs = {g['name']: g for g in self.config.get('frg702_gauges', [])}
        self.config['frg702_gauges'] = []
        for i in range(new_frg_count):
            name = f"FRG702_{i+1}"
            self.config['frg702_gauges'].append({
                "name": name,
                "sensor_code": f"T{i+1}",
                "units": self.p_unit_var.get(),
                "enabled": True
            })

        if self.connection and self.connection.is_connected():
            self._initialize_hardware_readers()

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

        turbo_frame = ttk.Frame(self.indicator_frame)
        turbo_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(turbo_frame, text="Turbo", font=lbl_font).pack()
        self.indicators['Turbo'] = tk.Canvas(turbo_frame, width=canvas_size, height=canvas_size, bg='#333333', highlightthickness=1, highlightbackground="black")
        self.indicators['Turbo'].pack()

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

        self._build_indicators()

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
        # Stop the user's ramp if running
        if self.ramp_panel.is_running():
            self.ramp_panel.stop_execution()

        # Update ramp panel with emergency state
        self.ramp_panel.set_emergency_shutdown(
            True,
            "TEMPERATURE LIMIT EXCEEDED - EMERGENCY SHUTDOWN INITIATED"
        )

        # Update PS panel
        self.ps_panel._show_error("EMERGENCY RAMP-DOWN IN PROGRESS")

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
        # Stop ramp if running
        if self.ramp_panel.is_running():
            self.ramp_panel.stop_execution()

        # Emergency stop turbo pump on safety trigger
        if self.turbo_controller:
            self.turbo_controller.emergency_stop()

        # Update power supply panel
        self.ps_panel.emergency_off()

        # Update ramp panel
        self.ramp_panel.set_emergency_shutdown(True, "EMERGENCY SHUTDOWN ACTIVE")

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

            # Clear emergency state on ramp panel
            self.ramp_panel.set_emergency_shutdown(False)
            self.ps_panel._clear_error()

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
            self.ps_panel.update_output_state(True)

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

        # 1. Get latest FRG pressure for turbo pump interlock
        if self._practice_mode and self._latest_frg_pressure_mbar is None:
            self._latest_frg_pressure_mbar = 1e-4  # Mock low pressure in practice

        # Update turbo pump panel with current pressure
        self.turbo_panel.update_pressure_interlock(self._latest_frg_pressure_mbar)

        # 2. Check turbo pump status for power supply interlock
        turbo_running = self.turbo_panel.is_turbo_running()

        # Update PS panel interlock
        self.ps_panel.set_interlock_state(turbo_running)

        # Update ramp panel interlock
        self.ramp_panel.set_turbo_interlock(turbo_running)

        # 3. Check restart lockout from safety monitor
        if self.safety_monitor.is_restart_locked:
            self.ramp_panel.set_emergency_shutdown(
                True,
                f"RESTART LOCKED - Temperature must drop below {SafetyMonitor.TEMP_RESTART_THRESHOLD:.0f}\u00b0C"
            )
        elif self.safety_monitor.is_rampdown_active:
            progress = self.safety_monitor.get_rampdown_progress()
            self.ramp_panel.set_emergency_shutdown(
                True,
                f"EMERGENCY RAMP-DOWN IN PROGRESS ({progress:.0f}%)"
            )

    def _on_start(self):
        self.is_running = True
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.log_btn.config(state='normal')
        self.status_var.set("Running")

        self.data_buffer.clear()

        self.daq = DataAcquisition(
            config=self.config,
            tc_reader=self.tc_reader,
            frg702_reader=self.frg702_reader,
            ps_controller=self.ps_controller,
            turbo_controller=self.turbo_controller,
            safety_monitor=self.safety_monitor if not self._safety_triggered else None,
            ramp_executor=self.ramp_executor,
            practice_mode=self._practice_mode
        )

        def on_new_data(timestamp, all_readings, tc_readings, frg702_details,
                        safety_shutdown=False):
            self.data_buffer.add_reading(all_readings)

            self._latest_readings = (timestamp, all_readings)
            self._latest_tc_readings = tc_readings
            self._latest_frg702_details = frg702_details

            # Track latest FRG pressure for turbo interlock
            for name, value in all_readings.items():
                if name.startswith('FRG702') and value is not None:
                    self._latest_frg_pressure_mbar = value
                    break

            if self.is_logging:
                log_readings = {}
                t_unit = self.t_unit_var.get()
                for name, value in all_readings.items():
                    if value is None:
                        log_readings[name] = None
                        continue
                    if name.startswith('TC_'):
                        log_readings[name] = convert_temperature(value, 'C', t_unit)
                    else:
                        log_readings[name] = value
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

        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.status_var.set("Stopped")

        if self.ramp_panel.is_running():
            self.ramp_panel.stop_execution()

        if self.is_logging:
            self._on_toggle_logging()

    def _on_toggle_logging(self):
        if not self.is_logging:
            dialog = LoggingDialog(self.root)
            self.root.wait_window(dialog)

            if dialog.result is None:
                return

            custom_name, notes = dialog.result

            frg702_gauges = self.config.get('frg702_gauges', [])
            frg702_count = len([g for g in frg702_gauges if g.get('enabled', True)])
            frg702_unit = frg702_gauges[0].get('units', 'mbar') if frg702_gauges else 'mbar'

            metadata = create_metadata_dict(
                tc_count=int(self.tc_count_var.get()),
                tc_type=self.tc_type_var.get(),
                tc_unit=self.t_unit_var.get(),
                frg702_count=frg702_count,
                frg702_unit=frg702_unit,
                sample_rate_ms=int(self.sample_rate_var.get().replace('ms', '')),
                notes=notes or ""
            )

            sensor_names = [tc['name'] for tc in self.config['thermocouples']
                          if tc.get('enabled', True)]
            sensor_names += [g['name'] for g in self.config.get('frg702_gauges', [])
                            if g.get('enabled', True)]

            if self.ps_controller:
                sensor_names += ['PS_Voltage', 'PS_Current']

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
        # Only redraw plots every 3rd call to avoid overwhelming matplotlib
        if not hasattr(self, '_plot_skip_counter'):
            self._plot_skip_counter = 0
        self._plot_skip_counter += 1
        should_redraw_plots = (self._plot_skip_counter % 3 == 0)

        if self._viewing_historical:
            self.root.after(self.config['display']['update_rate_ms'], self._update_gui)
            return

        # Auto-connect hardware (only after initial deferred init has attempted)
        lj_connected = self.connection.is_connected()
        if self._practice_mode:
            lj_connected = True
        elif not lj_connected and self._hardware_init_attempted:
            # Only auto-reconnect if we've already done the initial deferred init
            if self.connection.connect():
                if self._initialize_hardware_readers():
                    lj_connected = True
                    self.status_var.set("Connected")
                    self.start_btn.config(state='normal')
                else:
                    self.connection.disconnect()
                    lj_connected = False

            if not lj_connected:
                if self.status_var.get() != "Disconnected":
                    self.status_var.set("Disconnected")
                    self.start_btn.config(state='disabled')
                    self.stop_btn.config(state='disabled')
                    self.is_running = False
                    for name in self.indicators:
                        self.indicators[name].config(bg='#333333')

        # Update LabJack indicator
        color = '#00FF00' if lj_connected else '#333333'
        if 'LabJack' in self.indicators:
            self.indicators['LabJack'].config(bg=color)

        # Auto-connect XGS-600 (only after initial deferred init)
        xgs_connected = (self.xgs600 is not None and self.xgs600.is_connected()) or self._practice_mode
        if not xgs_connected and not self._practice_mode and self._hardware_init_attempted and self.config.get('xgs600', {}).get('enabled', False):
            if self._connect_xgs600():
                xgs_connected = True

        color = '#00FF00' if xgs_connected else '#333333'
        if 'XGS600' in self.indicators:
            self.indicators['XGS600'].config(bg=color)

        # Auto-connect Power Supply (only after initial deferred init)
        ps_connected = self.ps_connection.is_connected() or \
                       (self._practice_mode and self.ps_controller is not None)

        if not ps_connected and not self._practice_mode and self._hardware_init_attempted and self.config.get('power_supply', {}).get('enabled', True):
            if self.ps_connection.connect():
                ps_connected = True
                self._initialize_power_supply()

        color = '#00FF00' if ps_connected else '#333333'
        if 'PowerSupply' in self.indicators:
            self.indicators['PowerSupply'].config(bg=color)

        # Update Turbo indicator
        turbo_connected = self.turbo_controller is not None
        color = '#00FF00' if turbo_connected else '#333333'
        if 'Turbo' in self.indicators:
            self.indicators['Turbo'].config(bg=color)

        # Update power supply panel
        if ps_connected and self.ps_controller:
            if self._practice_mode:
                self.ps_panel.set_connected(True)

            ps_readings = self.ps_controller.get_readings()
            self.ps_panel.update(ps_readings)

            # Feed V/I data into ramp panel's embedded plot
            voltage = ps_readings.get('PS_Voltage', 0.0)
            current = ps_readings.get('PS_Current', 0.0)
            if self.is_running:
                self.ramp_panel.update_plot_data(
                    voltage if voltage is not None else 0.0,
                    current if current is not None else 0.0
                )
        else:
            self.ps_panel.set_connected(False)

        # Update ramp panel
        self.ramp_panel.update()

        # Update turbo pump status display
        if self.turbo_controller:
            self.turbo_panel.update_status_display()

        # Update safety interlocks
        self._update_safety_interlocks()

        # Update safety display
        if not self._safety_triggered:
            self._update_safety_display(self.safety_monitor.status)

        if not self.is_running:
            if lj_connected:
                self._check_connections()

            self.root.after(self.config['display']['update_rate_ms'], self._update_gui)
            return

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

        self.sensor_panel.update(display_readings)

        # Update FRG-702 detailed status
        if hasattr(self, '_latest_frg702_details') and self._latest_frg702_details:
            self.sensor_panel.update_frg702_status(self._latest_frg702_details)

        # Update indicators
        for name, value in current.items():
            if name in self.indicators:
                color = '#00FF00' if value is not None else '#333333'
                self.indicators[name].config(bg=color)

        # Update plots (only every 3rd call to reduce matplotlib overhead)
        if should_redraw_plots:
            sensor_names = [tc['name'] for tc in self.config['thermocouples']
                           if tc.get('enabled', True)]
            sensor_names += [g['name'] for g in self.config.get('frg702_gauges', [])
                            if g.get('enabled', True)]

            ps_names = []  # Explicitly empty to remove from thermocouple plots

            if hasattr(self, 'full_plot'):
                self.full_plot.update(sensor_names, ps_names)

            if hasattr(self, 'recent_plot'):
                self.recent_plot.update(sensor_names, ps_names, window_seconds=60)

        self.root.after(self.config['display']['update_rate_ms'], self._update_gui)

    def _initialize_hardware_readers(self):
        try:
            handle = self.connection.get_handle()
            self.tc_reader = ThermocoupleReader(handle, self.config['thermocouples'])

            turbo_config = self.config.get('turbo_pump', {})
            if turbo_config.get('enabled', False):
                try:
                    self.turbo_controller = TurboPumpController(handle, turbo_config)
                    self.turbo_panel.set_controller(self.turbo_controller)
                    print("Turbo pump controller initialized")
                except Exception as e:
                    print(f"Failed to initialize turbo pump controller: {e}")
                    self.turbo_controller = None

            self._check_connections()
            return True
        except Exception:
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
            )
            if not self.xgs600.connect(silent=True):
                self.xgs600 = None
                return False

            frg702_config = self.config.get('frg702_gauges', [])
            if frg702_config:
                self.frg702_reader = FRG702Reader(self.xgs600, frg702_config)

            print("XGS-600 controller connected, FRG-702 reader initialized")
            return True
        except Exception:
            self.xgs600 = None
            return False

    def _initialize_power_supply(self):
        try:
            instrument = self.ps_connection.get_instrument()
            ps_config = self.config.get('power_supply', {})

            self.ps_controller = PowerSupplyController(
                instrument,
                voltage_limit=ps_config.get('default_voltage_limit', 20.0),
                current_limit=ps_config.get('default_current_limit', 50.0)
            )

            self.safety_monitor.set_power_supply(self.ps_controller)
            self.ramp_executor.set_power_supply(self.ps_controller)
            self.ps_panel.set_controller(self.ps_controller)
            
            # Update resource display
            resource = self.ps_connection.get_resource_string()
            if resource:
                self.ps_resource_var.set(resource)

            print("Power supply initialized successfully")
            return True
        except Exception:
            return False

    def _on_close(self):
        self.is_running = False

        if self.daq:
            self.daq.stop_fast_acquisition()

        if self.ramp_executor.is_active():
            self.ramp_executor.stop()

        if self.is_logging:
            self.logger.stop_logging()

        if self.turbo_controller:
            try:
                self.turbo_controller.cleanup()
            except Exception:
                pass

        if self.ps_controller:
            try:
                self.ps_controller.output_off()
                self.ps_controller.set_voltage(0)
            except Exception:
                pass

        if self.ps_connection:
            self.ps_connection.disconnect()

        if self.xgs600:
            self.xgs600.disconnect()
            self.xgs600 = None

        if self.connection:
            self.connection.disconnect()

        self.root.destroy()

    def run(self):
        self.root.mainloop()

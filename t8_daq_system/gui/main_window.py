"""
main_window.py
PURPOSE: Main application window - coordinates everything

Integrates LabJack T8 DAQ with Keysight N5761A power supply control,
safety monitoring, and ramp profile execution.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import threading
import time
import os
import random
import math

# Import our modules
from t8_daq_system.hardware.labjack_connection import LabJackConnection
from t8_daq_system.hardware.thermocouple_reader import ThermocoupleReader
from t8_daq_system.hardware.pressure_reader import PressureReader
from t8_daq_system.hardware.frg702_reader import FRG702Reader
from t8_daq_system.hardware.keysight_connection import KeysightConnection
from t8_daq_system.hardware.power_supply_controller import PowerSupplyController
from t8_daq_system.control.ramp_executor import RampExecutor
from t8_daq_system.control.safety_monitor import SafetyMonitor, SafetyStatus
from t8_daq_system.data.data_buffer import DataBuffer
from t8_daq_system.data.data_logger import DataLogger, create_metadata_dict
from t8_daq_system.gui.live_plot import LivePlot
from t8_daq_system.gui.sensor_panel import SensorPanel
from t8_daq_system.utils.helpers import convert_temperature, convert_pressure
from t8_daq_system.gui.power_supply_panel import PowerSupplyPanel
from t8_daq_system.gui.ramp_panel import RampPanel
from t8_daq_system.gui.dialogs import LoggingDialog, LoadCSVDialog, AxisScaleDialog


class MainWindow:
    # Available sampling rates in milliseconds
    SAMPLE_RATES = [50, 100, 200, 500, 1000, 2000]

    def __init__(self, config_path=None):
        """
        Initialize the main application window.
        """
        # Default configuration
        self.config = {
            "device": {"type": "T8", "connection": "USB", "identifier": "ANY"},
            "thermocouples": [{"name": "TC_1", "channel": 0, "type": "C", "units": "C", "enabled": True}],
            "pressure_sensors": [{"name": "P_1", "channel": 8, "min_voltage": 0.5, "max_voltage": 4.5, "min_pressure": 0, "max_pressure": 100, "units": "PSI", "enabled": True}],
            "power_supply": {
                "enabled": True,
                "visa_resource": None,  # Auto-detect if None
                "default_voltage_limit": 20.0,
                "default_current_limit": 50.0,
                "safety": {
                    "max_temperature": 2300,
                    "watchdog_sensor": "TC_1",
                    "auto_shutoff": True,
                    "warning_threshold": 0.9
                }
            },
            "logging": {"interval_ms": 100, "file_prefix": "data_log", "auto_start": False},
            "display": {"update_rate_ms": 100, "history_seconds": 60}
        }

        # Load from config file if provided
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    loaded_config = json.load(f)
                    self.config.update(loaded_config)
            except Exception as e:
                print(f"Error loading config from {config_path}: {e}")

        # Create main window
        self.root = tk.Tk()
        self.root.title("T8 DAQ System with Power Supply Control")
        self.root.geometry("1200x800")

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Initialize LabJack hardware
        self.connection = LabJackConnection()
        self.tc_reader = None
        self.pressure_reader = None
        self.frg702_reader = None

        # Initialize Keysight power supply components
        self.ps_connection = KeysightConnection(
            resource_string=self.config.get('power_supply', {}).get('visa_resource')
        )
        self.ps_controller = None

        # Initialize ramp executor and safety monitor
        self.ramp_executor = RampExecutor()
        self.safety_monitor = SafetyMonitor(auto_shutoff=True)

        # Initialize data handling (None for unlimited history)
        self.data_buffer = DataBuffer(
            max_seconds=None,
            sample_rate_ms=self.config['display']['update_rate_ms']
        )

        # Set up log folder path
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.log_folder = os.path.join(base_dir, 'logs')
        self.profiles_folder = os.path.join(base_dir, 'config', 'profiles')

        # Create folders if they don't exist
        if not os.path.exists(self.profiles_folder):
            os.makedirs(self.profiles_folder)
        if not os.path.exists(self.log_folder):
            os.makedirs(self.log_folder)

        self.logger = DataLogger(
            log_folder=self.log_folder,
            file_prefix=self.config['logging']['file_prefix']
        )

        # Control flags
        self.is_running = False
        self.is_logging = False
        self.read_thread = None
        self._safety_triggered = False

        # Axis scale settings
        self._use_absolute_scales = True  # Default to absolute scales
        self._temp_range = (0, 2500)  # Default temp range
        self._pressure_range = (0, 100)  # Default pressure range

        # FRG-702 detail readings for GUI status
        self._latest_frg702_details = {}

        # Mode tracking (live vs viewing historical data)
        self._viewing_historical = False
        self._practice_mode = False
        self._loaded_data = None
        self._loaded_data_units = {'temp': 'C', 'press': 'PSI'}

        # Build the GUI
        self._build_gui()

        # Configure safety monitor from config
        self._configure_safety_monitor()

        # Register safety callbacks
        self._register_safety_callbacks()

        # Start GUI update loop (always runs to check connection)
        self._update_gui()

    def _build_gui(self):
        """Create all the GUI elements."""

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

        # Pressure count
        ttk.Label(config_area, text="Press:").pack(side=tk.LEFT, padx=2)
        self.p_count_var = tk.StringVar(value=str(len(self.config['pressure_sensors'])))
        self.p_count_combo = ttk.Combobox(
            config_area, textvariable=self.p_count_var,
            values=["0", "1", "2", "3", "4", "5", "6", "7"], width=3
        )
        self.p_count_combo.pack(side=tk.LEFT, padx=2)
        self.p_count_combo.bind("<<ComboboxSelected>>", lambda e: self._on_config_change())

        # Pressure Type (PSI Range)
        ttk.Label(config_area, text="P-Max:").pack(side=tk.LEFT, padx=2)
        p_max = "100"
        if self.config['pressure_sensors']:
            p_max = str(int(self.config['pressure_sensors'][0]['max_pressure']))
        self.p_type_var = tk.StringVar(value=p_max)
        self.p_type_combo = ttk.Combobox(
            config_area, textvariable=self.p_type_var,
            values=["50", "100", "250", "500", "1000"], width=4
        )
        self.p_type_combo.pack(side=tk.LEFT, padx=2)
        self.p_type_combo.bind("<<ComboboxSelected>>", lambda e: self._on_config_change())

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

        ttk.Label(config_area, text="P-Unit:").pack(side=tk.LEFT, padx=2)
        p_unit = "PSI"
        if self.config['pressure_sensors']:
            p_unit = self.config['pressure_sensors'][0]['units']
        self.p_unit_var = tk.StringVar(value=p_unit)
        self.p_unit_combo = ttk.Combobox(
            config_area, textvariable=self.p_unit_var,
            values=["PSI", "Bar", "kPa", "Torr"], width=5
        )
        self.p_unit_combo.pack(side=tk.LEFT, padx=2)
        self.p_unit_combo.bind("<<ComboboxSelected>>", lambda e: self._on_config_change())

        # Sampling rate dropdown
        ttk.Label(config_area, text="Rate:").pack(side=tk.LEFT, padx=2)
        current_rate = self.config['logging']['interval_ms']
        self.sample_rate_var = tk.StringVar(value=f"{current_rate}ms")
        rate_values = [f"{r}ms" for r in self.SAMPLE_RATES]
        self.sample_rate_combo = ttk.Combobox(
            config_area, textvariable=self.sample_rate_var,
            values=rate_values, width=6
        )
        self.sample_rate_combo.pack(side=tk.LEFT, padx=2)
        self.sample_rate_combo.bind("<<ComboboxSelected>>", lambda e: self._on_sample_rate_change())

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

        # Load CSV button
        self.load_csv_btn = ttk.Button(
            control_frame, text="Load CSV", command=self._on_load_csv
        )
        self.load_csv_btn.pack(side=tk.LEFT, padx=5)

        # Axis Scale button
        self.scale_btn = ttk.Button(
            control_frame, text="Axis Scales", command=self._on_axis_scales
        )
        self.scale_btn.pack(side=tk.LEFT, padx=5)

        # Dual Display button
        self.dual_btn = ttk.Button(
            control_frame, text="Dual Display", command=self._toggle_dual_display
        )
        self.dual_btn.pack(side=tk.LEFT, padx=5)

        # Practice Mode button
        self.practice_btn = ttk.Button(
            control_frame, text="Practice Mode: OFF", command=self._toggle_practice_mode
        )
        self.practice_btn.pack(side=tk.LEFT, padx=5)

        # Separator
        ttk.Separator(control_frame, orient='vertical').pack(
            side=tk.LEFT, padx=10, fill='y'
        )

        # Status label
        self.status_var = tk.StringVar(value="Disconnected")

        # Connection Status Indicators
        self.indicator_frame = ttk.Frame(control_frame)
        self.indicator_frame.pack(side=tk.RIGHT, padx=10)

        self.indicators = {}  # name: widget
        self._build_indicators()

        status_label = ttk.Label(
            control_frame, textvariable=self.status_var, font=('Arial', 10, 'bold')
        )
        status_label.pack(side=tk.RIGHT, padx=10)

        ttk.Label(control_frame, text="Status:").pack(side=tk.RIGHT)

        # Create main content area with PanedWindow for flexible layout
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Left side - Monitoring
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=1)

        # Current readings panel
        self.panel_container = ttk.LabelFrame(left_frame, text="Current Readings")
        self.panel_container.pack(fill=tk.X, padx=5, pady=5)

        # Build initial panel
        self._rebuild_sensor_panel()

        # Live plots container
        self.plot_container_main = ttk.Frame(left_frame)
        self.plot_container_main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Build initial plots
        self._build_plots(self.plot_container_main)

        # Right side - Power Supply Control
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=1)

        # Power Supply Panel
        ps_frame = ttk.LabelFrame(right_frame, text="Power Supply Control")
        ps_frame.pack(fill=tk.X, padx=5, pady=5)

        self.ps_panel = PowerSupplyPanel(ps_frame, self.ps_controller)
        self.ps_panel.on_output_change(self._on_ps_output_change)

        # Ramp Profile Panel
        ramp_frame = ttk.LabelFrame(right_frame, text="Ramp Profile Control")
        ramp_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.ramp_panel = RampPanel(
            ramp_frame,
            self.ramp_executor,
            self.profiles_folder
        )
        self.ramp_panel.on_ramp_start(self._on_ramp_start)
        self.ramp_panel.on_ramp_stop(self._on_ramp_stop)

        # Safety Status Bar at bottom
        safety_frame = ttk.Frame(self.root)
        safety_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(safety_frame, text="Safety:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT)

        self.safety_indicator = tk.Canvas(
            safety_frame, width=16, height=16,
            bg='#00FF00', highlightthickness=1, highlightbackground='black'
        )
        self.safety_indicator.pack(side=tk.LEFT, padx=5)

        self.safety_status_label = ttk.Label(
            safety_frame, text="OK", font=('Arial', 9)
        )
        self.safety_status_label.pack(side=tk.LEFT)

        # Reset Safety button (initially hidden)
        self.reset_safety_btn = ttk.Button(
            safety_frame, text="Reset Safety",
            command=self._on_reset_safety
        )
        # Don't pack yet - only show after safety trigger

        # Temperature limit display
        ttk.Separator(safety_frame, orient='vertical').pack(side=tk.LEFT, padx=10, fill='y')
        self.temp_limit_label = ttk.Label(
            safety_frame, text="Max Temp: --",
            font=('Arial', 8)
        )
        self.temp_limit_label.pack(side=tk.LEFT, padx=5)

        # Historical data indicator (initially hidden)
        self.historical_label = ttk.Label(
            safety_frame, text="[VIEWING HISTORICAL DATA]",
            font=('Arial', 9, 'bold'), foreground='blue'
        )
        # Don't pack initially

        # Dual window tracking
        self.dual_window = None

    def _build_plots(self, parent):
        """Create the live plots in the specified parent widget."""
        # Use PanedWindow for resizable dual windows
        plot_paned = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        plot_paned.pack(fill=tk.BOTH, expand=True)

        # Full run plot
        full_frame = ttk.LabelFrame(plot_paned, text="Full Run History")
        plot_paned.add(full_frame, weight=1)
        self.full_plot = LivePlot(full_frame, self.data_buffer)

        # Recent plot (1 min)
        recent_frame = ttk.LabelFrame(plot_paned, text="Last 1 Minute")
        plot_paned.add(recent_frame, weight=1)
        self.recent_plot = LivePlot(recent_frame, self.data_buffer)

        # Configure plots with units and scales
        self._update_plot_settings()

    def _toggle_practice_mode(self):
        """Toggle practice mode on/off."""
        self._practice_mode = not self._practice_mode
        if self._practice_mode:
            self.practice_btn.config(text="Practice Mode: ON")
            self.start_btn.config(state='normal')
            self.status_var.set("Practice Mode Active")
        else:
            self.practice_btn.config(text="Practice Mode: OFF")
            if not self.connection or not self.connection.is_connected():
                self.start_btn.config(state='disabled')
                self.status_var.set("Disconnected")
            else:
                self.status_var.set("Connected")
        
        self._rebuild_sensor_panel()
        self._update_plot_settings()

    def _on_sample_rate_change(self):
        """Handle change in sampling rate."""
        rate_str = self.sample_rate_var.get()
        rate_ms = int(rate_str.replace('ms', ''))

        self.config['logging']['interval_ms'] = rate_ms
        self.config['display']['update_rate_ms'] = rate_ms

        # Update data buffer sample rate
        self.data_buffer.sample_rate_ms = rate_ms

    def _update_plot_settings(self):
        """Update plot settings (units, scales) based on current config."""
        # Get current units
        t_unit = self.t_unit_var.get() if hasattr(self, 't_unit_var') else 'C'
        p_unit = self.p_unit_var.get() if hasattr(self, 'p_unit_var') else 'PSI'

        # Map unit codes to display symbols
        temp_symbols = {'C': '°C', 'F': '°F', 'K': 'K'}
        temp_unit_display = temp_symbols.get(t_unit, '°C')
        
        # Update temperature range (base range is 0-300C)
        t_min_display = convert_temperature(0, 'C', t_unit)
        t_max_display = convert_temperature(300, 'C', t_unit)
        self._temp_range = (t_min_display, t_max_display)

        # Update plot units
        if hasattr(self, 'full_plot'):
            self.full_plot.set_units(temp_unit_display, p_unit)
        if hasattr(self, 'recent_plot'):
            self.recent_plot.set_units(temp_unit_display, p_unit)

        # Update pressure range based on max pressure setting (dropdown is in PSI)
        p_max_str = self.p_type_var.get() if hasattr(self, 'p_type_var') else "100"
        try:
            p_max_psi = float(p_max_str)
        except ValueError:
            p_max_psi = 100
            
        # Convert max pressure to current display units for the plot scale
        p_max_display = convert_pressure(p_max_psi, 'PSI', p_unit)
        self._pressure_range = (0, p_max_display)

        # Update axis scales
        if hasattr(self, 'full_plot'):
            self.full_plot.set_absolute_scales(
                self._use_absolute_scales,
                self._temp_range,
                self._pressure_range
            )
        if hasattr(self, 'recent_plot'):
            self.recent_plot.set_absolute_scales(
                self._use_absolute_scales,
                self._temp_range,
                self._pressure_range
            )
            
        # Calculate names to plot based on current config
        sensor_names = [tc['name'] for tc in self.config['thermocouples'] if tc.get('enabled', True)]
        sensor_names += [p['name'] for p in self.config['pressure_sensors'] if p.get('enabled', True)]
        sensor_names += [g['name'] for g in self.config.get('frg702_gauges', []) if g.get('enabled', True)]
        
        # Power supply names to show (if enabled in config or present in loaded data)
        ps_names = []
        if self.config.get('power_supply', {}).get('enabled', True):
            ps_names = ['PS_Voltage', 'PS_Current']

        # Trigger redraw if viewing historical data or if running
        if self._viewing_historical and self._loaded_data:
            if hasattr(self, 'full_plot'):
                self.full_plot.update_from_loaded_data(
                    self._loaded_data, sensor_names, ps_names, 
                    data_units=self._loaded_data_units
                )
            if hasattr(self, 'recent_plot'):
                self.recent_plot.update_from_loaded_data(
                    self._loaded_data, sensor_names, ps_names, 
                    window_seconds=60, data_units=self._loaded_data_units
                )
            
            # Update sensor panel with converted last row of data
            if self._loaded_data.get('timestamps'):
                last_readings = {name: self._loaded_data[name][-1] 
                                for name in self._loaded_data if name != 'timestamps'}
                display_last = {}
                source_t_unit = self._loaded_data_units.get('temp', 'C')
                source_p_unit = self._loaded_data_units.get('press', 'PSI')
                
                for name, value in last_readings.items():
                    if value is None:
                        display_last[name] = None
                    elif name.startswith('TC_'):
                        display_last[name] = convert_temperature(value, source_t_unit, t_unit)
                    elif name.startswith('P_'):
                        display_last[name] = convert_pressure(value, source_p_unit, p_unit)
                    else:
                        display_last[name] = value
                self.sensor_panel.update(display_last)
                
        else:
            # Not viewing historical and not running - force a redraw with empty data to update units/axes
            if hasattr(self, 'full_plot'):
                self.full_plot.update(sensor_names, ps_names)
            if hasattr(self, 'recent_plot'):
                self.recent_plot.update(sensor_names, ps_names, window_seconds=60)

    def _toggle_dual_display(self):
        """Toggle between single window and dual window (for 2 displays)."""
        if self.dual_window is None or not self.dual_window.winfo_exists():
            # Create dual window
            self.dual_window = tk.Toplevel(self.root)
            self.dual_window.title("T8 DAQ System - Live Plots")
            self.dual_window.geometry("800x600")
            
            # Handle closure
            self.dual_window.protocol("WM_DELETE_WINDOW", self._toggle_dual_display)

            # Move plots to dual window
            for widget in self.plot_container_main.winfo_children():
                widget.destroy()
            
            self._build_plots(self.dual_window)
            self.dual_btn.config(text="Single Display")
        else:
            # Return to single window
            self.dual_window.destroy()
            self.dual_window = None
            
            # Rebuild in main window
            for widget in self.plot_container_main.winfo_children():
                widget.destroy()
                
            self._build_plots(self.plot_container_main)
            self.dual_btn.config(text="Dual Display")

    def _on_axis_scales(self):
        """Open dialog to configure axis scales."""
        dialog = AxisScaleDialog(
            self.root,
            self._temp_range,
            self._pressure_range,
            self._use_absolute_scales
        )
        self.root.wait_window(dialog)

        if dialog.result:
            self._use_absolute_scales = dialog.result['use_absolute']
            self._temp_range = dialog.result['temp_range']
            self._pressure_range = dialog.result['pressure_range']
            self._update_plot_settings()

    def _on_load_csv(self):
        """Open dialog to load historical CSV data."""
        dialog = LoadCSVDialog(self.root, self.log_folder)
        self.root.wait_window(dialog)

        if dialog.result:
            self._load_historical_data(dialog.result)

    def _load_historical_data(self, filepath):
        """Load and display historical data from a CSV file."""
        try:
            metadata, data = DataLogger.load_csv_with_metadata(filepath)

            if not data.get('timestamps'):
                messagebox.showerror("Error", "No data found in file.")
                return

            self._loaded_data = data
            self._viewing_historical = True

            # Update GUI to reflect loaded settings
            if metadata:
                # Store original units for conversion
                self._loaded_data_units = {
                    'temp': metadata.get('tc_unit', 'C'),
                    'press': metadata.get('p_unit', 'PSI')
                }
                
                # Update config displays based on metadata
                if 'tc_count' in metadata:
                    self.tc_count_var.set(str(metadata['tc_count']))
                if 'tc_type' in metadata:
                    self.tc_type_var.set(metadata['tc_type'])
                if 'tc_unit' in metadata:
                    self.t_unit_var.set(metadata['tc_unit'])
                if 'p_count' in metadata:
                    self.p_count_var.set(str(metadata['p_count']))
                if 'p_unit' in metadata:
                    self.p_unit_var.set(metadata['p_unit'])
                if 'p_max' in metadata:
                    self.p_type_var.set(str(int(metadata['p_max'])))
                if 'sample_rate_ms' in metadata:
                    self.sample_rate_var.set(f"{metadata['sample_rate_ms']}ms")

            # Update plot settings based on loaded metadata
            self._update_plot_settings()

            # Show historical data indicator
            self.historical_label.pack(side=tk.RIGHT, padx=10)

            # Update sensor panel with last row of data
            if data['timestamps']:
                last_readings = {}
                for name in data:
                    if name != 'timestamps':
                        last_readings[name] = data[name][-1]
                
                # Convert last readings for display
                display_last = {}
                t_unit = self.t_unit_var.get()
                p_unit = self.p_unit_var.get()
                source_t_unit = self._loaded_data_units.get('temp', 'C')
                source_p_unit = self._loaded_data_units.get('press', 'PSI')
                
                for name, value in last_readings.items():
                    if value is None:
                        display_last[name] = None
                        continue
                    if name.startswith('TC_'):
                        display_last[name] = convert_temperature(value, source_t_unit, t_unit)
                    elif name.startswith('P_'):
                        display_last[name] = convert_pressure(value, source_p_unit, p_unit)
                    else:
                        display_last[name] = value
                
                self.sensor_panel.update(display_last)

            # Update status
            filename = os.path.basename(filepath)
            self.status_var.set(f"Viewing: {filename}")

            # Disable live controls
            self.start_btn.config(state='disabled')
            self.stop_btn.config(state='disabled')
            self.log_btn.config(state='disabled')

            # Add "Return to Live" button if not exists
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
        """Return to live data view from historical view."""
        self._viewing_historical = False
        self._loaded_data = None

        # Hide historical indicator
        self.historical_label.pack_forget()

        # Hide return button
        if hasattr(self, 'return_live_btn'):
            self.return_live_btn.pack_forget()

        # Clear plots
        if hasattr(self, 'full_plot'):
            self.full_plot.clear()
        if hasattr(self, 'recent_plot'):
            self.recent_plot.clear()
        self.data_buffer.clear()

        # Re-enable controls if connected
        if self.connection and self.connection.is_connected():
            self.start_btn.config(state='normal')
            self.status_var.set("Connected")
        else:
            self.status_var.set("Disconnected")

    def _on_config_change(self):
        """Update configuration when user changes counts or units in UI."""
        new_tc_count = int(self.tc_count_var.get())
        new_tc_type = self.tc_type_var.get()
        new_tc_unit = self.t_unit_var.get()
        new_p_count = int(self.p_count_var.get())
        new_p_max = float(self.p_type_var.get())
        new_p_unit = self.p_unit_var.get()

        # Enforce total limit of 7 sensors
        if new_tc_count + new_p_count > 7:
            messagebox.showwarning("Config Limit", "Maximum total sensors allowed is 7.\nAdjusting counts to fit limit.")
            if new_tc_count > 7:
                new_tc_count = 7
                new_p_count = 0
            else:
                new_p_count = 7 - new_tc_count

            self.tc_count_var.set(str(new_tc_count))
            self.p_count_var.set(str(new_p_count))

        # Update thermocouples
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

        # Update pressure sensors
        old_ps = {p['name']: p for p in self.config['pressure_sensors']}
        self.config['pressure_sensors'] = []
        for i in range(new_p_count):
            name = f"P_{i+1}"
            old_p = old_ps.get(name, {})
            self.config['pressure_sensors'].append({
                "name": name,
                "channel": 8 + i,
                "min_voltage": 0.5,
                "max_voltage": 4.5,
                "min_pressure": 0,
                "max_pressure": new_p_max,
                "units": new_p_unit,
                "enabled": True
            })

        # If already connected, update the readers
        if self.connection and self.connection.is_connected():
            self._initialize_hardware_readers()

        # Update safety monitor limits
        self._configure_safety_monitor()

        self._rebuild_sensor_panel()

        # Update plot settings
        self._update_plot_settings()

    def _build_indicators(self):
        """Build the small light-up boxes for connection status."""
        for widget in self.indicator_frame.winfo_children():
            widget.destroy()
        self.indicators = {}

        lbl_font = ('Arial', 7, 'bold')

        # LabJack Indicator
        lj_frame = ttk.Frame(self.indicator_frame)
        lj_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(lj_frame, text="LJ", font=lbl_font).pack()
        self.indicators['LabJack'] = tk.Canvas(lj_frame, width=20, height=20, bg='#333333', highlightthickness=1, highlightbackground="black")
        self.indicators['LabJack'].pack()

        # Power Supply Indicator
        ps_frame = ttk.Frame(self.indicator_frame)
        ps_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(ps_frame, text="PS", font=lbl_font).pack()
        self.indicators['PowerSupply'] = tk.Canvas(ps_frame, width=20, height=20, bg='#333333', highlightthickness=1, highlightbackground="black")
        self.indicators['PowerSupply'].pack()

        # TC Indicators
        for i, tc in enumerate(self.config['thermocouples']):
            name = tc['name']
            f = ttk.Frame(self.indicator_frame)
            f.pack(side=tk.LEFT, padx=2)
            ttk.Label(f, text=f"TC{i+1}", font=lbl_font).pack()
            self.indicators[name] = tk.Canvas(f, width=20, height=20, bg='#333333', highlightthickness=1, highlightbackground="black")
            self.indicators[name].pack()

        # PG Indicators
        for i, pg in enumerate(self.config['pressure_sensors']):
            name = pg['name']
            f = ttk.Frame(self.indicator_frame)
            f.pack(side=tk.LEFT, padx=2)
            ttk.Label(f, text=f"P{i+1}", font=lbl_font).pack()
            self.indicators[name] = tk.Canvas(f, width=20, height=20, bg='#333333', highlightthickness=1, highlightbackground="black")
            self.indicators[name].pack()

        # FRG-702 Indicators
        for i, gauge in enumerate(self.config.get('frg702_gauges', [])):
            name = gauge['name']
            f = ttk.Frame(self.indicator_frame)
            f.pack(side=tk.LEFT, padx=2)
            ttk.Label(f, text=f"FRG{i+1}", font=lbl_font).pack()
            self.indicators[name] = tk.Canvas(f, width=20, height=20, bg='#333333', highlightthickness=1, highlightbackground="black")
            self.indicators[name].pack()

    def _rebuild_sensor_panel(self):
        """Re-create the sensor panel with current configuration."""
        for widget in self.panel_container.winfo_children():
            widget.destroy()

        all_sensors = self.config['thermocouples'] + self.config['pressure_sensors']
        frg702_configs = self.config.get('frg702_gauges', [])
        self.sensor_panel = SensorPanel(self.panel_container, all_sensors, frg702_configs)
        self._build_indicators()

    def _configure_safety_monitor(self):
        """Configure the safety monitor from config."""
        safety_config = self.config.get('power_supply', {}).get('safety', {})

        # Set temperature limits for all thermocouples
        max_temp = safety_config.get('max_temperature', 2300)
        for tc in self.config['thermocouples']:
            self.safety_monitor.set_temperature_limit(tc['name'], max_temp)

        # Set watchdog sensor
        watchdog = safety_config.get('watchdog_sensor')
        if watchdog:
            self.safety_monitor.set_watchdog_sensor(watchdog)

        # Set warning threshold
        warning_threshold = safety_config.get('warning_threshold', 0.9)
        self.safety_monitor.set_warning_threshold(warning_threshold)

        # Set auto shutoff
        self.safety_monitor.auto_shutoff = safety_config.get('auto_shutoff', True)

        # Update display
        self.temp_limit_label.config(text=f"Max Temp: {max_temp}C")

    def _register_safety_callbacks(self):
        """Register callbacks with the safety monitor."""
        self.safety_monitor.on_warning(self._on_safety_warning)
        self.safety_monitor.on_limit_exceeded(self._on_safety_limit_exceeded)
        self.safety_monitor.on_shutdown(self._on_safety_shutdown)

    def _on_safety_warning(self, sensor_name: str, value: float, limit: float):
        """Handle safety warning."""
        # Update GUI on main thread
        self.root.after(0, lambda: self._update_safety_display(SafetyStatus.WARNING))

    def _on_safety_limit_exceeded(self, sensor_name: str, value: float, limit: float):
        """Handle safety limit exceeded."""
        self.root.after(0, lambda: self._update_safety_display(SafetyStatus.LIMIT_EXCEEDED))

    def _on_safety_shutdown(self, event):
        """Handle safety shutdown event."""
        self._safety_triggered = True
        self.root.after(0, self._handle_safety_shutdown)

    def _handle_safety_shutdown(self):
        """Handle safety shutdown on main thread."""
        # Stop ramp if running
        if self.ramp_panel.is_running():
            self.ramp_panel.stop_execution()

        # Update power supply panel
        self.ps_panel.emergency_off()

        # Update safety display
        self._update_safety_display(SafetyStatus.SHUTDOWN_TRIGGERED)

        # Show reset button
        self.reset_safety_btn.pack(side=tk.LEFT, padx=10)

        # Show alert
        event = self.safety_monitor.get_last_event()
        if event:
            messagebox.showerror(
                "SAFETY SHUTDOWN",
                f"Emergency shutdown triggered!\n\n{event.message}\n\n"
                "Power supply output has been disabled.\n"
                "Resolve the issue before clicking Reset Safety."
            )

    def _update_safety_display(self, status: SafetyStatus):
        """Update the safety status display."""
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
        """Handle Reset Safety button click."""
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
        """Handle power supply output state change."""
        if is_on:
            self.status_var.set("Running - PS Output ON")
        else:
            if self.is_running:
                self.status_var.set("Running")

    def _on_ramp_start(self):
        """Handle ramp start event."""
        # Enable power supply output if not already on
        if self.ps_controller and not self.ps_controller.is_output_on():
            self.ps_controller.output_on()
            self.ps_panel.update_output_state(True)

    def _on_ramp_stop(self):
        """Handle ramp stop event."""
        pass  # Output handled by ramp executor

    def _check_connections(self):
        """Do a one-time read to update connection indicators."""
        if not self.tc_reader or not self.pressure_reader:
            return

        try:
            tc_readings = self.tc_reader.read_all()
            p_readings = self.pressure_reader.read_all()
            all_readings = {**tc_readings, **p_readings}

            # Include FRG-702 readings if available
            if self.frg702_reader:
                frg702_readings = self.frg702_reader.read_all()
                all_readings.update(frg702_readings)

            for name, value in all_readings.items():
                if name in self.indicators:
                    color = '#00FF00' if value is not None else '#333333'
                    self.indicators[name].config(bg=color)
        except Exception as e:
            print(f"Error checking connections: {e}")

    def _on_start(self):
        """Start reading data."""
        self.is_running = True
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.log_btn.config(state='normal')
        self.status_var.set("Running")

        # Clear old data
        self.data_buffer.clear()

        # Start reading in background thread
        self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.read_thread.start()

    def _on_stop(self):
        """Stop reading data."""
        self.is_running = False
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.status_var.set("Stopped")

        # Stop ramp if running
        if self.ramp_panel.is_running():
            self.ramp_panel.stop_execution()

        if self.is_logging:
            self._on_toggle_logging()

    def _on_toggle_logging(self):
        """Start or stop logging to file."""
        if not self.is_logging:
            # Show logging dialog
            dialog = LoggingDialog(self.root)
            self.root.wait_window(dialog)

            if dialog.result is None:
                return  # User cancelled

            custom_name, notes = dialog.result

            # Build metadata
            frg702_gauges = self.config.get('frg702_gauges', [])
            frg702_count = len([g for g in frg702_gauges if g.get('enabled', True)])
            frg702_unit = frg702_gauges[0].get('units', 'mbar') if frg702_gauges else 'mbar'

            metadata = create_metadata_dict(
                tc_count=int(self.tc_count_var.get()),
                tc_type=self.tc_type_var.get(),
                tc_unit=self.t_unit_var.get(),
                p_count=int(self.p_count_var.get()),
                p_unit=self.p_unit_var.get(),
                p_max=float(self.p_type_var.get()),
                frg702_count=frg702_count,
                frg702_unit=frg702_unit,
                sample_rate_ms=int(self.sample_rate_var.get().replace('ms', '')),
                notes=notes or ""
            )

            # Start logging
            sensor_names = [tc['name'] for tc in self.config['thermocouples']
                          if tc.get('enabled', True)]
            sensor_names += [p['name'] for p in self.config['pressure_sensors']
                            if p.get('enabled', True)]
            sensor_names += [g['name'] for g in self.config.get('frg702_gauges', [])
                            if g.get('enabled', True)]

            # Add power supply channels if connected
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

    def _read_loop(self):
        """Background thread that reads sensors."""
        interval = self.config['logging']['interval_ms'] / 1000.0

        while self.is_running:
            # Check if still connected
            if not self._practice_mode:
                if not self.connection or not self.connection.is_connected():
                    print("Connection lost in read loop")
                    self.is_running = False
                    break

            try:
                if self._practice_mode:
                    # Generate simulated data
                    tc_readings = {}
                    for tc in self.config['thermocouples']:
                        if tc.get('enabled', True):
                            # Base temp 20C + sine wave + noise
                            t = time.time()
                            val = 20.0 + 5.0 * math.sin(t / 10.0) + random.uniform(-0.5, 0.5)
                            tc_readings[tc['name']] = val

                    pressure_readings = {}
                    for p in self.config['pressure_sensors']:
                        if p.get('enabled', True):
                            # Base pressure 50PSI + sine wave + noise
                            t = time.time()
                            val = 50.0 + 10.0 * math.cos(t / 15.0) + random.uniform(-1.0, 1.0)
                            pressure_readings[p['name']] = val

                    # Simulate FRG-702 data (logarithmic sweep in mbar)
                    frg702_readings = {}
                    for gauge in self.config.get('frg702_gauges', []):
                        if gauge.get('enabled', True):
                            t = time.time()
                            # Sweep through decades: 1e-6 to 1e-3 mbar with sine wave
                            exponent = -6.0 + 1.5 * math.sin(t / 20.0) + random.uniform(-0.1, 0.1)
                            frg702_readings[gauge['name']] = 10 ** exponent

                    frg702_detail_readings = {}
                    for gauge in self.config.get('frg702_gauges', []):
                        if gauge.get('enabled', True):
                            frg702_detail_readings[gauge['name']] = {
                                'pressure': frg702_readings.get(gauge['name']),
                                'status': 'valid',
                                'mode': 'Combined Pirani/Cold Cathode',
                                'voltage': 5.0,
                            }

                    ps_readings = {}
                    if self.config.get('power_supply', {}).get('enabled', True):
                        ps_readings = {
                            'PS_Voltage': 12.0 + random.uniform(-0.1, 0.1),
                            'PS_Current': 2.0 + random.uniform(-0.05, 0.05)
                        }
                else:
                    # Read all sensors from hardware
                    tc_readings = self.tc_reader.read_all()
                    pressure_readings = self.pressure_reader.read_all()

                    # Read FRG-702 gauges if configured
                    frg702_readings = {}
                    frg702_detail_readings = {}
                    if self.frg702_reader:
                        frg702_readings = self.frg702_reader.read_all()
                        frg702_detail_readings = self.frg702_reader.read_all_with_status()

                    # Read power supply state if connected
                    ps_readings = {}
                    if self.ps_controller:
                        ps_readings = self.ps_controller.get_readings()

                # SAFETY CHECK FIRST
                if not self._safety_triggered:
                    if not self.safety_monitor.check_limits(tc_readings):
                        self.is_running = False
                        break

                # If ramp is running and not in practice mode, update setpoint
                if self.ps_controller and not self._practice_mode:
                    if self.ramp_executor.is_running():
                        new_setpoint = self.ramp_executor.get_current_setpoint()
                        try:
                            self.ps_controller.set_voltage(new_setpoint)
                        except Exception as e:
                            print(f"Error setting voltage: {e}")

                # Combine readings (FRG-702 stored in mbar internally)
                all_readings = {**tc_readings, **pressure_readings, **frg702_readings, **ps_readings}

                # Store FRG-702 detail readings for GUI status update
                self._latest_frg702_details = frg702_detail_readings

                # Add to buffer (stays in base units)
                self.data_buffer.add_reading(all_readings)

                # Log if enabled (convert to selected units)
                if self.is_logging:
                    log_readings = {}
                    t_unit = self.t_unit_var.get()
                    p_unit = self.p_unit_var.get()

                    for name, value in all_readings.items():
                        if value is None:
                            log_readings[name] = None
                            continue
                        if name.startswith('TC_'):
                            log_readings[name] = convert_temperature(value, 'C', t_unit)
                        elif name.startswith('P_'):
                            log_readings[name] = convert_pressure(value, 'PSI', p_unit)
                        else:
                            # FRG-702 and PS values stored as-is (mbar for FRG-702)
                            log_readings[name] = value

                    self.logger.log_reading(log_readings)

            except Exception as e:
                print(f"Error in read loop: {e}")
                if not self.connection or not self.connection.is_connected():
                    self.is_running = False
                    break

            time.sleep(interval)

    def _update_gui(self):
        """Update the GUI (called periodically)."""

        # Skip GUI updates if viewing historical data
        if self._viewing_historical:
            self.root.after(self.config['display']['update_rate_ms'], self._update_gui)
            return

        # Auto-connect LabJack
        lj_connected = self.connection.is_connected()

        if not lj_connected:
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

        # Auto-connect Power Supply
        ps_connected = self.ps_connection.is_connected()

        if not ps_connected and self.config.get('power_supply', {}).get('enabled', True):
            if self.ps_connection.connect():
                ps_connected = True
                self._initialize_power_supply()

        # Update Power Supply indicator
        color = '#00FF00' if ps_connected else '#333333'
        if 'PowerSupply' in self.indicators:
            self.indicators['PowerSupply'].config(bg=color)

        # Update power supply panel
        if ps_connected and self.ps_controller:
            ps_readings = self.ps_controller.get_readings()
            self.ps_panel.update(ps_readings)
        else:
            self.ps_panel.set_connected(False)

        # Update ramp panel
        self.ramp_panel.update()

        # Update safety display
        if not self._safety_triggered:
            self._update_safety_display(self.safety_monitor.status)

        if not self.is_running:
            if lj_connected:
                self._check_connections()

            self.root.after(self.config['display']['update_rate_ms'], self._update_gui)
            return

        # Get current readings and update panel (when running)
        current = self.data_buffer.get_all_current()

        # Convert readings for display and logging
        display_readings = {}
        t_unit = self.t_unit_var.get()
        p_unit = self.p_unit_var.get()

        for name, value in current.items():
            if value is None:
                display_readings[name] = None
                continue

            if name.startswith('TC_'):
                display_readings[name] = convert_temperature(value, 'C', t_unit)
            elif name.startswith('P_'):
                display_readings[name] = convert_pressure(value, 'PSI', p_unit)
            else:
                # FRG-702 and PS values passed through as-is (mbar for FRG-702)
                display_readings[name] = value

        self.sensor_panel.update(display_readings)

        # Update FRG-702 detailed status (status indicator, mode label)
        if hasattr(self, '_latest_frg702_details') and self._latest_frg702_details:
            self.sensor_panel.update_frg702_status(self._latest_frg702_details)

        # Update indicators (when running)
        for name, value in current.items():
            if name in self.indicators:
                color = '#00FF00' if value is not None else '#333333'
                self.indicators[name].config(bg=color)

        # Update plots - include power supply data and FRG-702
        sensor_names = [tc['name'] for tc in self.config['thermocouples']
                       if tc.get('enabled', True)]
        sensor_names += [p['name'] for p in self.config['pressure_sensors']
                        if p.get('enabled', True)]
        sensor_names += [g['name'] for g in self.config.get('frg702_gauges', [])
                        if g.get('enabled', True)]

        # Add PS data to plot if available
        ps_names = []
        if self.ps_controller:
            ps_names = ['PS_Voltage', 'PS_Current']

        # Update full run plot (no window)
        if hasattr(self, 'full_plot'):
            self.full_plot.update(sensor_names, ps_names)

        # Update recent plot (last 60 seconds)
        if hasattr(self, 'recent_plot'):
            self.recent_plot.update(sensor_names, ps_names, window_seconds=60)

        # Schedule next update
        self.root.after(self.config['display']['update_rate_ms'], self._update_gui)

    def _initialize_hardware_readers(self):
        """Helper to set up readers once connected."""
        try:
            handle = self.connection.get_handle()
            self.tc_reader = ThermocoupleReader(handle, self.config['thermocouples'])
            self.pressure_reader = PressureReader(handle, self.config['pressure_sensors'])

            # Initialize FRG-702 reader if configured
            frg702_config = self.config.get('frg702_gauges', [])
            if frg702_config:
                self.frg702_reader = FRG702Reader(handle, frg702_config)

            self._check_connections()
            return True
        except Exception as e:
            print(f"Failed to initialize hardware readers: {e}")
            return False

    def _initialize_power_supply(self):
        """Initialize the power supply controller once connected."""
        try:
            instrument = self.ps_connection.get_instrument()
            ps_config = self.config.get('power_supply', {})

            self.ps_controller = PowerSupplyController(
                instrument,
                voltage_limit=ps_config.get('default_voltage_limit', 20.0),
                current_limit=ps_config.get('default_current_limit', 50.0)
            )

            # Connect safety monitor to power supply
            self.safety_monitor.set_power_supply(self.ps_controller)

            # Connect ramp executor to power supply
            self.ramp_executor.set_power_supply(self.ps_controller)

            # Update GUI components
            self.ps_panel.set_controller(self.ps_controller)

            print("Power supply initialized successfully")
            return True

        except Exception as e:
            print(f"Failed to initialize power supply: {e}")
            return False

    def _on_close(self):
        """Handle window close event."""
        self.is_running = False

        # Stop ramp execution
        if self.ramp_executor.is_active():
            self.ramp_executor.stop()

        # Stop logging if active
        if self.is_logging:
            self.logger.stop_logging()

        # Safely turn off power supply
        if self.ps_controller:
            try:
                self.ps_controller.output_off()
                self.ps_controller.set_voltage(0)
            except Exception:
                pass

        # Disconnect from power supply
        if self.ps_connection:
            self.ps_connection.disconnect()

        # Disconnect from LabJack
        if self.connection:
            self.connection.disconnect()

        # Destroy the window
        self.root.destroy()

    def run(self):
        """Start the application."""
        self.root.mainloop()

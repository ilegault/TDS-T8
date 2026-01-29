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

# Import our modules
from t8_daq_system.hardware.labjack_connection import LabJackConnection
from t8_daq_system.hardware.thermocouple_reader import ThermocoupleReader
from t8_daq_system.hardware.pressure_reader import PressureReader
from t8_daq_system.hardware.keysight_connection import KeysightConnection
from t8_daq_system.hardware.power_supply_controller import PowerSupplyController
from t8_daq_system.control.ramp_executor import RampExecutor
from t8_daq_system.control.safety_monitor import SafetyMonitor, SafetyStatus
from t8_daq_system.data.data_buffer import DataBuffer
from t8_daq_system.data.data_logger import DataLogger
from t8_daq_system.gui.live_plot import LivePlot
from t8_daq_system.gui.sensor_panel import SensorPanel
from t8_daq_system.gui.power_supply_panel import PowerSupplyPanel
from t8_daq_system.gui.ramp_panel import RampPanel


class MainWindow:
    def __init__(self, config_path=None):
        """
        Initialize the main application window.
        """
        # Default configuration
        self.config = {
            "device": {"type": "T8", "connection": "USB", "identifier": "ANY"},
            "thermocouples": [{"name": "TC_1", "channel": 0, "type": "K", "units": "C", "enabled": True, "scale": 1.0, "offset": -15.0}],
            "pressure_sensors": [{"name": "P_1", "channel": 8, "min_voltage": 0.5, "max_voltage": 4.5, "min_pressure": 0, "max_pressure": 100, "units": "PSI", "enabled": True, "scale": 1.0, "offset": 0.0}],
            "power_supply": {
                "enabled": True,
                "visa_resource": None,  # Auto-detect if None
                "default_voltage_limit": 20.0,
                "default_current_limit": 50.0,
                "safety": {
                    "max_temperature": 200,
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
        self.root.geometry("1400x900")

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Initialize LabJack hardware
        self.connection = LabJackConnection()
        self.tc_reader = None
        self.pressure_reader = None

        # Initialize Keysight power supply components
        self.ps_connection = KeysightConnection(
            resource_string=self.config.get('power_supply', {}).get('visa_resource')
        )
        self.ps_controller = None

        # Initialize ramp executor and safety monitor
        self.ramp_executor = RampExecutor()
        self.safety_monitor = SafetyMonitor(auto_shutoff=True)

        # Initialize data handling
        self.data_buffer = DataBuffer(
            max_seconds=self.config['display']['history_seconds'],
            sample_rate_ms=self.config['display']['update_rate_ms']
        )

        # Set up log folder path
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_folder = os.path.join(base_dir, 'logs')
        self.profiles_folder = os.path.join(base_dir, 'config', 'profiles')

        # Create profiles folder if it doesn't exist
        if not os.path.exists(self.profiles_folder):
            os.makedirs(self.profiles_folder)

        self.logger = DataLogger(
            log_folder=log_folder,
            file_prefix=self.config['logging']['file_prefix']
        )

        # Control flags
        self.is_running = False
        self.is_logging = False
        self.read_thread = None
        self._safety_triggered = False

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
        ttk.Label(config_area, text="PSI:").pack(side=tk.LEFT, padx=2)
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
            values=["PSI", "Bar", "kPa"], width=5
        )
        self.p_unit_combo.pack(side=tk.LEFT, padx=2)
        self.p_unit_combo.bind("<<ComboboxSelected>>", lambda e: self._on_config_change())

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
        main_paned.add(left_frame, weight=3)

        # Current readings panel
        self.panel_container = ttk.LabelFrame(left_frame, text="Current Readings")
        self.panel_container.pack(fill=tk.X, padx=5, pady=5)

        # Build initial panel
        self._rebuild_sensor_panel()

        # Live plot
        plot_frame = ttk.LabelFrame(left_frame, text="Live Data")
        plot_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.live_plot = LivePlot(plot_frame, self.data_buffer)

        # Right side - Power Supply Control
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=2)

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
                "enabled": True,
                "scale": old_tc.get('scale', 1.0),
                "offset": old_tc.get('offset', 0.0)
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
                "enabled": True,
                "scale": old_p.get('scale', 1.0),
                "offset": old_p.get('offset', 0.0)
            })

        # If already connected, update the readers
        if self.connection and self.connection.is_connected():
            self._initialize_hardware_readers()

        # Update safety monitor limits
        self._configure_safety_monitor()

        self._rebuild_sensor_panel()

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

    def _rebuild_sensor_panel(self):
        """Re-create the sensor panel with current configuration."""
        for widget in self.panel_container.winfo_children():
            widget.destroy()

        all_sensors = self.config['thermocouples'] + self.config['pressure_sensors']
        self.sensor_panel = SensorPanel(self.panel_container, all_sensors)
        self._build_indicators()

    def _configure_safety_monitor(self):
        """Configure the safety monitor from config."""
        safety_config = self.config.get('power_supply', {}).get('safety', {})

        # Set temperature limits for all thermocouples
        max_temp = safety_config.get('max_temperature', 200)
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
            # Start logging - include power supply data
            sensor_names = [tc['name'] for tc in self.config['thermocouples']
                          if tc.get('enabled', True)]
            sensor_names += [p['name'] for p in self.config['pressure_sensors']
                            if p.get('enabled', True)]

            # Add power supply channels if connected
            if self.ps_controller:
                sensor_names += ['PS_Voltage', 'PS_Current']

            filepath = self.logger.start_logging(sensor_names)
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
            if not self.connection or not self.connection.is_connected():
                print("Connection lost in read loop")
                self.is_running = False
                break

            try:
                # Read all sensors
                tc_readings = self.tc_reader.read_all()
                pressure_readings = self.pressure_reader.read_all()

                # SAFETY CHECK FIRST - before any other processing
                if not self._safety_triggered:
                    if not self.safety_monitor.check_limits(tc_readings):
                        # Shutdown triggered - stop the loop
                        self.is_running = False
                        break

                # Read power supply state if connected
                ps_readings = {}
                if self.ps_controller:
                    ps_readings = self.ps_controller.get_readings()

                    # If ramp is running, update setpoint
                    if self.ramp_executor.is_running():
                        new_setpoint = self.ramp_executor.get_current_setpoint()
                        try:
                            self.ps_controller.set_voltage(new_setpoint)
                        except Exception as e:
                            print(f"Error setting voltage: {e}")

                # Combine readings
                all_readings = {**tc_readings, **pressure_readings, **ps_readings}

                # Add to buffer
                self.data_buffer.add_reading(all_readings)

                # Log if enabled
                if self.is_logging:
                    self.logger.log_reading(all_readings)

            except Exception as e:
                print(f"Error in read loop: {e}")
                if not self.connection or not self.connection.is_connected():
                    self.is_running = False
                    break

            time.sleep(interval)

    def _update_gui(self):
        """Update the GUI (called periodically)."""

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
        self.sensor_panel.update(current)

        # Update indicators (when running)
        for name, value in current.items():
            if name in self.indicators:
                color = '#00FF00' if value is not None else '#333333'
                self.indicators[name].config(bg=color)

        # Update plot - include power supply data
        sensor_names = [tc['name'] for tc in self.config['thermocouples']
                       if tc.get('enabled', True)]
        sensor_names += [p['name'] for p in self.config['pressure_sensors']
                        if p.get('enabled', True)]

        # Add PS data to plot if available
        ps_names = []
        if self.ps_controller:
            ps_names = ['PS_Voltage', 'PS_Current']

        self.live_plot.update(sensor_names, ps_names)

        # Schedule next update
        self.root.after(self.config['display']['update_rate_ms'], self._update_gui)

    def _initialize_hardware_readers(self):
        """Helper to set up readers once connected."""
        try:
            handle = self.connection.get_handle()
            self.tc_reader = ThermocoupleReader(handle, self.config['thermocouples'])
            self.pressure_reader = PressureReader(handle, self.config['pressure_sensors'])
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

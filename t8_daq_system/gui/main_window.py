"""
main_window.py
PURPOSE: Main application window - coordinates everything
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import threading
import time
import os

# Import our modules
from hardware.labjack_connection import LabJackConnection
from hardware.thermocouple_reader import ThermocoupleReader
from hardware.pressure_reader import PressureReader
from data.data_buffer import DataBuffer
from data.data_logger import DataLogger
from gui.live_plot import LivePlot
from gui.sensor_panel import SensorPanel


class MainWindow:
    def __init__(self, config_path=None):
        """
        Initialize the main application window.

        Args:
            config_path: Path to sensor_config.json. If None, uses default.
        """
        # Find config file
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, 'config', 'sensor_config.json')

        self.config_path = config_path

        # Load configuration
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        # Create main window
        self.root = tk.Tk()
        self.root.title("T8 DAQ System")
        self.root.geometry("1200x800")

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Initialize hardware (will connect later)
        self.connection = None
        self.tc_reader = None
        self.pressure_reader = None

        # Initialize data handling
        self.data_buffer = DataBuffer(
            max_seconds=self.config['display']['history_seconds'],
            sample_rate_ms=self.config['display']['update_rate_ms']
        )

        # Set up log folder path
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_folder = os.path.join(base_dir, 'logs')
        self.logger = DataLogger(
            log_folder=log_folder,
            file_prefix=self.config['logging']['file_prefix']
        )

        # Control flags
        self.is_running = False
        self.is_logging = False
        self.read_thread = None

        # Build the GUI
        self._build_gui()

    def _build_gui(self):
        """Create all the GUI elements."""

        # Top frame - Control buttons
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill=tk.X, padx=10, pady=5)

        self.connect_btn = ttk.Button(
            control_frame, text="Connect", command=self._on_connect
        )
        self.connect_btn.pack(side=tk.LEFT, padx=5)

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
        status_label = ttk.Label(
            control_frame, textvariable=self.status_var, font=('Arial', 10, 'bold')
        )
        status_label.pack(side=tk.RIGHT, padx=10)

        ttk.Label(control_frame, text="Status:").pack(side=tk.RIGHT)

        # Middle frame - Current readings panel
        panel_frame = ttk.LabelFrame(self.root, text="Current Readings")
        panel_frame.pack(fill=tk.X, padx=10, pady=5)

        # Combine all sensor configs for the panel
        all_sensors = self.config['thermocouples'] + self.config['pressure_sensors']
        self.sensor_panel = SensorPanel(panel_frame, all_sensors)

        # Bottom frame - Live plot
        plot_frame = ttk.LabelFrame(self.root, text="Live Data")
        plot_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.live_plot = LivePlot(plot_frame, self.data_buffer)

    def _on_connect(self):
        """Connect to the LabJack."""
        self.status_var.set("Connecting...")
        self.root.update()

        self.connection = LabJackConnection(self.config_path)
        if self.connection.connect():
            handle = self.connection.get_handle()

            # Initialize readers
            self.tc_reader = ThermocoupleReader(handle, self.config['thermocouples'])
            self.pressure_reader = PressureReader(handle, self.config['pressure_sensors'])

            self.status_var.set("Connected")
            self.connect_btn.config(state='disabled')
            self.start_btn.config(state='normal')
        else:
            self.status_var.set("Connection Failed")
            messagebox.showerror("Connection Error",
                "Failed to connect to LabJack T8.\n\n"
                "Check that:\n"
                "- The device is plugged in\n"
                "- LJM driver is installed\n"
                "- No other software is using the device"
            )

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

        # Start GUI update loop
        self._update_gui()

    def _on_stop(self):
        """Stop reading data."""
        self.is_running = False
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.status_var.set("Stopped")

        if self.is_logging:
            self._on_toggle_logging()

    def _on_toggle_logging(self):
        """Start or stop logging to file."""
        if not self.is_logging:
            # Start logging
            sensor_names = [tc['name'] for tc in self.config['thermocouples']
                          if tc.get('enabled', True)]
            sensor_names += [p['name'] for p in self.config['pressure_sensors']
                            if p.get('enabled', True)]
            filepath = self.logger.start_logging(sensor_names)
            self.is_logging = True
            self.log_btn.config(text="Stop Logging")
            self.status_var.set(f"Running - Logging to {os.path.basename(filepath)}")
        else:
            # Stop logging
            self.logger.stop_logging()
            self.is_logging = False
            self.log_btn.config(text="Start Logging")
            self.status_var.set("Running")

    def _read_loop(self):
        """Background thread that reads sensors."""
        interval = self.config['logging']['interval_ms'] / 1000.0

        while self.is_running:
            try:
                # Read all sensors
                tc_readings = self.tc_reader.read_all()
                pressure_readings = self.pressure_reader.read_all()

                # Combine readings
                all_readings = {**tc_readings, **pressure_readings}

                # Add to buffer
                self.data_buffer.add_reading(all_readings)

                # Log if enabled
                if self.is_logging:
                    self.logger.log_reading(all_readings)

            except Exception as e:
                print(f"Error in read loop: {e}")

            time.sleep(interval)

    def _update_gui(self):
        """Update the GUI (called periodically)."""
        if not self.is_running:
            return

        # Get current readings and update panel
        current = self.data_buffer.get_all_current()
        self.sensor_panel.update(current)

        # Update plot
        sensor_names = [tc['name'] for tc in self.config['thermocouples']
                       if tc.get('enabled', True)]
        sensor_names += [p['name'] for p in self.config['pressure_sensors']
                        if p.get('enabled', True)]
        self.live_plot.update(sensor_names)

        # Schedule next update
        self.root.after(self.config['display']['update_rate_ms'], self._update_gui)

    def _on_close(self):
        """Handle window close event."""
        self.is_running = False

        # Stop logging if active
        if self.is_logging:
            self.logger.stop_logging()

        # Disconnect from device
        if self.connection:
            self.connection.disconnect()

        # Destroy the window
        self.root.destroy()

    def run(self):
        """Start the application."""
        self.root.mainloop()

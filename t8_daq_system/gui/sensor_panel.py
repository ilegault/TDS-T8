"""
sensor_panel.py
PURPOSE: Display current sensor values as text/numbers
"""

import tkinter as tk
from tkinter import ttk
from t8_daq_system.hardware.frg702_reader import (
    FRG702Reader, STATUS_VALID, STATUS_UNDERRANGE, STATUS_OVERRANGE,
    STATUS_SENSOR_ERROR_NO_SUPPLY, STATUS_SENSOR_ERROR_PIRANI_DEFECTIVE,
    MODE_PIRANI_ONLY, MODE_COMBINED, MODE_UNKNOWN,
)


class SensorPanel:
    def __init__(self, parent_frame, sensor_configs, frg702_configs=None):
        """
        Initialize the sensor display panel.

        Args:
            parent_frame: tkinter frame to put displays in
            sensor_configs: list of thermocouple configs
            frg702_configs: optional list of FRG-702 gauge configs
        """
        self.parent = parent_frame
        self.displays = {}        # sensor_name: Label widget for value
        self.status_labels = {}   # sensor_name: Label widget for status
        self.frames = {}          # sensor_name: LabelFrame widget
        self.precisions = {}      # sensor_name: decimal places to show

        # FRG-702 specific widgets
        self.frg702_unit_vars = {}     # sensor_name: StringVar for unit dropdown
        self.frg702_mode_labels = {}   # sensor_name: Label for operating mode
        self.frg702_status_indicators = {}  # sensor_name: Canvas for status color

        i = 0  # grid index counter

        # Create a label for each standard sensor (Thermocouples)
        for sensor in sensor_configs:
            if not sensor.get('enabled', True):
                continue

            name = sensor['name']
            units = sensor.get('units', '')

            # Thermocouple precision and placeholder
            self.precisions[name] = 2
            placeholder = "--.--"

            # Create frame for this sensor with fixed size
            frame = ttk.LabelFrame(parent_frame, text=name, width=206, height=90)
            frame.grid(row=i//7, column=i%7, padx=6, pady=5)
            frame.pack_propagate(False)
            self.frames[name] = frame

            # Large number display
            value_label = ttk.Label(
                frame,
                text=placeholder,
                font=('Arial', 14, 'bold')
            )
            value_label.pack(padx=5, pady=1)

            # Units label
            units_label = ttk.Label(frame, text=units)
            units_label.pack(pady=(0, 1))

            # Status indicator
            status_label = ttk.Label(
                frame,
                text="WAITING",
                font=('Arial', 6, 'italic'),
                foreground='gray'
            )
            status_label.pack(side=tk.BOTTOM, pady=1)

            self.displays[name] = value_label
            self.status_labels[name] = status_label
            i += 1

        # Create FRG-702 gauge displays
        if frg702_configs:
            for gauge in frg702_configs:
                if not gauge.get('enabled', True):
                    continue

                name = gauge['name']
                default_unit = gauge.get('units', 'mbar')

                # Wider frame for FRG-702 to accommodate unit selector and mode
                frame = ttk.LabelFrame(parent_frame, text=name, width=240, height=120)
                frame.grid(row=i//7, column=i%7, padx=6, pady=5)
                frame.pack_propagate(False)
                self.frames[name] = frame

                # Status color indicator (green/yellow/red circle)
                status_canvas = tk.Canvas(frame, width=12, height=12,
                                          highlightthickness=0)
                status_canvas.pack(anchor='ne', padx=2, pady=1)
                status_canvas.create_oval(1, 1, 11, 11, fill='gray', outline='black',
                                          tags='indicator')
                self.frg702_status_indicators[name] = status_canvas

                # Large value display (scientific notation)
                value_label = ttk.Label(
                    frame,
                    text="-.--e--",
                    font=('Courier', 14, 'bold')
                )
                value_label.pack(padx=5, pady=1)

                # Unit selector row
                unit_frame = ttk.Frame(frame)
                unit_frame.pack(pady=(0, 1))

                unit_var = tk.StringVar(value=default_unit)
                self.frg702_unit_vars[name] = unit_var

                unit_combo = ttk.Combobox(
                    unit_frame, textvariable=unit_var,
                    values=["mbar", "Torr", "Pa"], width=5,
                    state='readonly'
                )
                unit_combo.pack(side=tk.LEFT, padx=2)

                # Operating mode label
                mode_label = ttk.Label(
                    frame,
                    text="",
                    font=('Arial', 6, 'italic'),
                    foreground='gray'
                )
                mode_label.pack(pady=(0, 1))
                self.frg702_mode_labels[name] = mode_label

                # Status text label
                status_label = ttk.Label(
                    frame,
                    text="WAITING",
                    font=('Arial', 6, 'italic'),
                    foreground='gray'
                )
                status_label.pack(side=tk.BOTTOM, pady=1)

                self.displays[name] = value_label
                self.status_labels[name] = status_label
                self.precisions[name] = -1  # Flag: use scientific notation
                i += 1

    def update(self, readings):
        """
        Update displayed values and status.

        Args:
            readings: dict like {'TC1': 25.3, 'FRG702_Chamber': 1.5e-6}
        """
        for name, value in readings.items():
            if name in self.displays:
                if name in self.frg702_unit_vars:
                    # FRG-702 display: use scientific notation
                    self._update_frg702_display(name, value)
                elif value is None:
                    self.displays[name].config(text="---", foreground='gray')
                    self.status_labels[name].config(text="DISCONNECTED", foreground='red')
                else:
                    precision = self.precisions.get(name, 1)
                    self.displays[name].config(text=f"{value:.{precision}f}", foreground='black')
                    self.status_labels[name].config(text="CONNECTED", foreground='green')

    def _update_frg702_display(self, name, value):
        """Update an FRG-702 gauge display with unit conversion and scientific notation."""
        if value is None:
            self.displays[name].config(text="-.--e--", foreground='gray')
            self.status_labels[name].config(text="DISCONNECTED", foreground='red')
            self._set_frg702_indicator(name, 'gray')
            return

        # Convert to selected display unit
        display_unit = self.frg702_unit_vars[name].get()
        display_value = FRG702Reader.convert_pressure(value, display_unit)

        # Show in scientific notation
        self.displays[name].config(
            text=f"{display_value:.2e}",
            foreground='black'
        )
        self.status_labels[name].config(text="CONNECTED", foreground='green')
        self._set_frg702_indicator(name, '#00FF00')

    def update_frg702_status(self, frg702_detail_readings):
        """
        Update FRG-702 displays with full status info (status, mode).

        Args:
            frg702_detail_readings: dict from FRG702Reader.read_all_with_status()
                e.g. {'FRG702_Chamber': {'pressure': 1.5e-6, 'status': 'valid', 'mode': 'Combined...'}}
        """
        for name, info in frg702_detail_readings.items():
            if name not in self.displays:
                continue

            pressure = info.get('pressure')
            status = info.get('status', '')
            mode = info.get('mode', MODE_UNKNOWN)

            # Update mode label if configured
            if name in self.frg702_mode_labels:
                self.frg702_mode_labels[name].config(text=mode)

            # Determine indicator color and display based on status
            if status == STATUS_VALID:
                if mode == MODE_COMBINED:
                    indicator_color = '#00FF00'  # Green for combined mode
                elif mode == MODE_PIRANI_ONLY:
                    indicator_color = '#FFFF00'  # Yellow for Pirani-only
                else:
                    indicator_color = '#00FF00'  # Green default for valid

                # Convert and display value
                display_unit = self.frg702_unit_vars.get(name, tk.StringVar(value='mbar')).get()
                display_value = FRG702Reader.convert_pressure(pressure, display_unit)
                self.displays[name].config(
                    text=f"{display_value:.2e}",
                    foreground='black'
                )
                self.status_labels[name].config(text="CONNECTED", foreground='green')

            elif status == STATUS_UNDERRANGE:
                indicator_color = '#FF0000'
                self.displays[name].config(text="UNDERRANGE", foreground='orange')
                self.status_labels[name].config(text="UNDERRANGE", foreground='orange')

            elif status == STATUS_OVERRANGE:
                indicator_color = '#FF0000'
                self.displays[name].config(text="OVERRANGE", foreground='orange')
                self.status_labels[name].config(text="OVERRANGE", foreground='orange')

            elif status == STATUS_SENSOR_ERROR_NO_SUPPLY:
                indicator_color = '#FF0000'
                self.displays[name].config(text="NO SUPPLY", foreground='red')
                self.status_labels[name].config(text="ERROR", foreground='red')

            elif status == STATUS_SENSOR_ERROR_PIRANI_DEFECTIVE:
                indicator_color = '#FF0000'
                self.displays[name].config(text="DEFECTIVE", foreground='red')
                self.status_labels[name].config(text="ERROR", foreground='red')

            else:
                indicator_color = '#FF0000'
                self.displays[name].config(text="ERR", foreground='red')
                self.status_labels[name].config(text="ERROR", foreground='red')

            self._set_frg702_indicator(name, indicator_color)

    def _set_frg702_indicator(self, name, color):
        """Set the color of an FRG-702 status indicator circle."""
        if name in self.frg702_status_indicators:
            canvas = self.frg702_status_indicators[name]
            canvas.delete('indicator')
            canvas.create_oval(1, 1, 11, 11, fill=color, outline='black',
                               tags='indicator')

    def set_error(self, sensor_name, message="ERR"):
        """
        Set a sensor display to show an error state.

        Args:
            sensor_name: Name of the sensor
            message: Error message to display
        """
        if sensor_name in self.displays:
            self.displays[sensor_name].config(text=message, foreground='red')
            self.status_labels[sensor_name].config(text="ERROR", foreground='red')
            if sensor_name in self.frg702_status_indicators:
                self._set_frg702_indicator(sensor_name, '#FF0000')

    def clear_all(self):
        """Reset all displays to default state."""
        for name in self.displays:
            if name in self.frg702_unit_vars:
                self.displays[name].config(text="-.--e--", foreground='black')
            else:
                placeholder = "--.--" if self.precisions.get(name) == 2 else "--.-"
                self.displays[name].config(text=placeholder, foreground='black')
            self.status_labels[name].config(text="WAITING", foreground='gray')
            if name in self.frg702_status_indicators:
                self._set_frg702_indicator(name, 'gray')

    def highlight(self, sensor_name, color='green'):
        """
        Highlight a sensor display (e.g., for alarms).

        Args:
            sensor_name: Name of the sensor to highlight
            color: Color to use for highlighting
        """
        if sensor_name in self.displays:
            self.displays[sensor_name].config(foreground=color)

    def get_sensor_names(self):
        """Get list of sensor names in the panel."""
        return list(self.displays.keys())

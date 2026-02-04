"""
live_plot.py
PURPOSE: Display real-time updating graphs of sensor data
KEY CONCEPT: Use matplotlib's FigureCanvasTkAgg to embed plots in tkinter

Supports dual Y-axis plotting:
- Left Y-axis: Temperature sensors (only if thermocouples selected)
- Right Y-axis: Pressure sensors (only if pressure gauges selected)
- Power supply data on whichever axis is available
"""

import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
from datetime import datetime


class LivePlot:
    # Default axis ranges (absolute scales)
    DEFAULT_TEMP_RANGE = (0, 300)  # Celsius
    DEFAULT_PRESSURE_RANGE = (0, 100)  # PSI

    def __init__(self, parent_frame, data_buffer):
        """
        Initialize the live plot.

        Args:
            parent_frame: tkinter frame to put the plot in
            data_buffer: DataBuffer object to get data from
        """
        self.data_buffer = data_buffer
        self.parent = parent_frame

        # Create matplotlib figure
        self.fig = Figure(figsize=(10, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)

        # Create secondary axis for pressure data
        self.ax2 = None  # Created on demand

        # Embed in tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Store line objects for each sensor (for efficient updating)
        self.lines = {}

        # Configure the plot appearance
        self.ax.set_xlabel('Time')
        self.ax.set_ylabel('Temperature (°C)')
        self.ax.grid(True, alpha=0.3)

        # Format x-axis to show time nicely
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))

        # Color cycle for temperature sensors (left axis) - warm colors
        self.temp_colors = ['#d62728', '#ff7f0e', '#e377c2', '#bcbd22',
                           '#8c564b', '#9467bd', '#17becf']

        # Color cycle for pressure sensors (right axis) - cool colors
        self.pressure_colors = ['#1f77b4', '#2ca02c', '#17becf', '#7f7f7f',
                               '#9467bd', '#8c564b', '#e377c2']

        # Power supply colors
        self.ps_colors = {
            'PS_Voltage': '#d62728',   # Red for voltage
            'PS_Current': '#ff7f0e'    # Orange for current
        }

        # Track what's currently shown
        self._showing_ps = False

        # Axis scale settings (for absolute scaling)
        self._temp_range = None  # None = auto, tuple = (min, max)
        self._pressure_range = None
        self._use_absolute_scales = False

        # Unit labels
        self._temp_unit = "°C"
        self._pressure_unit = "PSI"

    def set_absolute_scales(self, enabled=True, temp_range=None, pressure_range=None):
        """
        Enable or disable absolute (fixed) axis scales.

        Args:
            enabled: Whether to use absolute scales
            temp_range: Tuple (min, max) for temperature axis, or None for default
            pressure_range: Tuple (min, max) for pressure axis, or None for default
        """
        self._use_absolute_scales = enabled
        self._temp_range = temp_range if temp_range else self.DEFAULT_TEMP_RANGE
        self._pressure_range = pressure_range if pressure_range else self.DEFAULT_PRESSURE_RANGE

    def set_units(self, temp_unit="°C", pressure_unit="PSI"):
        """Set the unit labels for the axes."""
        self._temp_unit = temp_unit
        self._pressure_unit = pressure_unit

    def update(self, sensor_names, ps_names=None, window_seconds=None):
        """
        Refresh the plot with current data.
        Call this periodically (e.g., every 500ms).

        Args:
            sensor_names: List of sensor names to plot (TC and pressure)
            ps_names: Optional list of power supply sensor names
            window_seconds: If provided, only show data from the last X seconds
        """
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('Time')

        # Check what types of data we have
        tc_names = [name for name in sensor_names if name.startswith('TC_')]
        p_names = [name for name in sensor_names if name.startswith('P_')]
        has_tc = len(tc_names) > 0
        has_p = len(p_names) > 0
        has_ps = bool(ps_names)

        # Determine axis configuration:
        # - If TC selected: show left axis for temperature
        # - If P selected: show right axis for pressure
        # - If only one type: show only that axis
        # - PS data goes on whichever axis is available (prefer right if both)

        show_left_axis = has_tc
        show_right_axis = has_p or (has_ps and not has_tc)

        # Configure Left Axis (Temperature) - only if TC sensors selected
        if show_left_axis:
            self.ax.set_ylabel(f'Temperature ({self._temp_unit})', color='#d62728')
            self.ax.tick_params(axis='y', labelcolor='#d62728', labelleft=True)
            self.ax.yaxis.set_visible(True)
            if self._use_absolute_scales and self._temp_range:
                self.ax.set_ylim(self._temp_range)
        else:
            # Hide left axis completely
            self.ax.set_ylabel('')
            self.ax.tick_params(axis='y', labelleft=False)
            self.ax.yaxis.set_visible(False)

        # Configure Right Axis (Pressure) - only if P sensors or PS data selected
        if show_right_axis:
            if self.ax2 is None:
                self.ax2 = self.ax.twinx()
            self.ax2.clear()
            self.ax2.yaxis.set_visible(True)

            label_parts = []
            if has_p:
                label_parts.append(f'Pressure ({self._pressure_unit})')
            if has_ps and not has_p:
                label_parts.append('Power Supply')

            self.ax2.set_ylabel(' / '.join(label_parts), color='#1f77b4')
            self.ax2.tick_params(axis='y', labelcolor='#1f77b4')

            if self._use_absolute_scales and self._pressure_range and has_p:
                self.ax2.set_ylim(self._pressure_range)
        elif self.ax2 is not None:
            self.ax2.yaxis.set_visible(False)

        self._showing_ps = has_ps

        # Plot sensors
        legend_handles = []
        legend_labels = []

        now = datetime.now() if window_seconds else None

        # Plot temperature sensors on LEFT axis
        for i, name in enumerate(tc_names):
            timestamps, values = self.data_buffer.get_sensor_data(name)
            if not timestamps or not values:
                continue

            # Filter data
            valid_data = []
            for t, v in zip(timestamps, values):
                if v is None:
                    continue
                if window_seconds and (now - t).total_seconds() > window_seconds:
                    continue
                valid_data.append((t, v))

            if valid_data:
                times, vals = zip(*valid_data)
                color = self.temp_colors[i % len(self.temp_colors)]
                line, = self.ax.plot(times, vals, label=name, linewidth=2, color=color)
                legend_handles.append(line)
                legend_labels.append(name)

        # Plot pressure sensors on RIGHT axis
        for i, name in enumerate(p_names):
            timestamps, values = self.data_buffer.get_sensor_data(name)
            if not timestamps or not values:
                continue

            valid_data = []
            for t, v in zip(timestamps, values):
                if v is None:
                    continue
                if window_seconds and (now - t).total_seconds() > window_seconds:
                    continue
                valid_data.append((t, v))

            if valid_data:
                times, vals = zip(*valid_data)
                color = self.pressure_colors[i % len(self.pressure_colors)]

                if self.ax2:
                    line, = self.ax2.plot(times, vals, label=name, linewidth=2,
                                         color=color, linestyle='--')
                else:
                    # Fallback: use left axis if right not available
                    line, = self.ax.plot(times, vals, label=name, linewidth=2,
                                        color=color, linestyle='--')
                legend_handles.append(line)
                legend_labels.append(name)

        # Plot power supply data
        if ps_names:
            # Determine which axis to use for PS data
            ps_axis = self.ax2 if self.ax2 and self.ax2.yaxis.get_visible() else self.ax

            for name in ps_names:
                timestamps, values = self.data_buffer.get_sensor_data(name)
                if not timestamps or not values:
                    continue

                valid_data = []
                for t, v in zip(timestamps, values):
                    if v is None:
                        continue
                    if window_seconds and (now - t).total_seconds() > window_seconds:
                        continue
                    valid_data.append((t, v))

                if valid_data:
                    times, vals = zip(*valid_data)
                    color = self.ps_colors.get(name, '#d62728')

                    if name == 'PS_Voltage':
                        label = 'Voltage (V)'
                        linestyle = ':'
                    elif name == 'PS_Current':
                        label = 'Current (A)'
                        linestyle = '-.'
                    else:
                        label = name
                        linestyle = '-'

                    line, = ps_axis.plot(times, vals, label=label,
                                        linewidth=2, color=color,
                                        linestyle=linestyle)
                    legend_handles.append(line)
                    legend_labels.append(label)

        # Combined legend
        if legend_handles:
            self.ax.legend(legend_handles, legend_labels, loc='upper left', fontsize=8)

        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.fig.autofmt_xdate()  # Angle the time labels

        # Ensure proper layout
        self.fig.tight_layout()

        self.canvas.draw()

    def update_from_loaded_data(self, loaded_data, window_seconds=None):
        """
        Update plot with pre-loaded data (from CSV file).

        Args:
            loaded_data: Dict with 'timestamps' list and sensor data dicts
            window_seconds: If provided, only show data from the last X seconds
        """
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('Time')

        timestamps = loaded_data.get('timestamps', [])
        if not timestamps:
            self.canvas.draw()
            return

        # Separate TC and P sensors
        tc_names = [k for k in loaded_data.keys() if k.startswith('TC_')]
        p_names = [k for k in loaded_data.keys() if k.startswith('P_')]
        ps_names = [k for k in loaded_data.keys() if k.startswith('PS_')]

        has_tc = len(tc_names) > 0
        has_p = len(p_names) > 0
        has_ps = len(ps_names) > 0

        show_left_axis = has_tc
        show_right_axis = has_p or (has_ps and not has_tc)

        # Configure axes
        if show_left_axis:
            self.ax.set_ylabel(f'Temperature ({self._temp_unit})', color='#d62728')
            self.ax.tick_params(axis='y', labelcolor='#d62728', labelleft=True)
            self.ax.yaxis.set_visible(True)
            if self._use_absolute_scales and self._temp_range:
                self.ax.set_ylim(self._temp_range)
        else:
            self.ax.set_ylabel('')
            self.ax.tick_params(axis='y', labelleft=False)
            self.ax.yaxis.set_visible(False)

        if show_right_axis:
            if self.ax2 is None:
                self.ax2 = self.ax.twinx()
            self.ax2.clear()
            self.ax2.yaxis.set_visible(True)
            label_parts = []
            if has_p:
                label_parts.append(f'Pressure ({self._pressure_unit})')
            if has_ps and not has_p:
                label_parts.append('Power Supply')
            self.ax2.set_ylabel(' / '.join(label_parts), color='#1f77b4')
            self.ax2.tick_params(axis='y', labelcolor='#1f77b4')
            if self._use_absolute_scales and self._pressure_range and has_p:
                self.ax2.set_ylim(self._pressure_range)
        elif self.ax2 is not None:
            self.ax2.yaxis.set_visible(False)

        legend_handles = []
        legend_labels = []

        now = timestamps[-1] if timestamps and window_seconds else None

        # Plot TC data
        for i, name in enumerate(tc_names):
            values = loaded_data.get(name, [])
            if not values:
                continue

            valid_data = []
            for t, v in zip(timestamps, values):
                if v is None:
                    continue
                if window_seconds and now and (now - t).total_seconds() > window_seconds:
                    continue
                valid_data.append((t, v))

            if valid_data:
                times, vals = zip(*valid_data)
                color = self.temp_colors[i % len(self.temp_colors)]
                line, = self.ax.plot(times, vals, label=name, linewidth=2, color=color)
                legend_handles.append(line)
                legend_labels.append(name)

        # Plot P data
        for i, name in enumerate(p_names):
            values = loaded_data.get(name, [])
            if not values:
                continue

            valid_data = []
            for t, v in zip(timestamps, values):
                if v is None:
                    continue
                if window_seconds and now and (now - t).total_seconds() > window_seconds:
                    continue
                valid_data.append((t, v))

            if valid_data:
                times, vals = zip(*valid_data)
                color = self.pressure_colors[i % len(self.pressure_colors)]
                target_ax = self.ax2 if self.ax2 and self.ax2.yaxis.get_visible() else self.ax
                line, = target_ax.plot(times, vals, label=name, linewidth=2,
                                       color=color, linestyle='--')
                legend_handles.append(line)
                legend_labels.append(name)

        # Plot PS data
        for name in ps_names:
            values = loaded_data.get(name, [])
            if not values:
                continue

            valid_data = []
            for t, v in zip(timestamps, values):
                if v is None:
                    continue
                if window_seconds and now and (now - t).total_seconds() > window_seconds:
                    continue
                valid_data.append((t, v))

            if valid_data:
                times, vals = zip(*valid_data)
                color = self.ps_colors.get(name, '#d62728')

                if name == 'PS_Voltage':
                    label = 'Voltage (V)'
                    linestyle = ':'
                elif name == 'PS_Current':
                    label = 'Current (A)'
                    linestyle = '-.'
                else:
                    label = name
                    linestyle = '-'

                ps_axis = self.ax2 if self.ax2 and self.ax2.yaxis.get_visible() else self.ax
                line, = ps_axis.plot(times, vals, label=label,
                                    linewidth=2, color=color, linestyle=linestyle)
                legend_handles.append(line)
                legend_labels.append(label)

        if legend_handles:
            self.ax.legend(legend_handles, legend_labels, loc='upper left', fontsize=8)

        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.fig.autofmt_xdate()
        self.fig.tight_layout()
        self.canvas.draw()

    def clear(self):
        """Clear the plot."""
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('Time')
        self.ax.set_ylabel(f'Temperature ({self._temp_unit})')

        if self.ax2 is not None:
            self.ax2.clear()

        self.canvas.draw()

    def set_y_label(self, label):
        """Set the y-axis label."""
        self.ax.set_ylabel(label)
        self.canvas.draw()

    def set_title(self, title):
        """Set the plot title."""
        self.ax.set_title(title)
        self.canvas.draw()

    def set_y_limits(self, ymin=None, ymax=None, axis='primary'):
        """
        Set Y-axis limits.

        Args:
            ymin: Minimum Y value (None for auto)
            ymax: Maximum Y value (None for auto)
            axis: 'primary' for left axis, 'secondary' for right axis
        """
        target_ax = self.ax if axis == 'primary' else self.ax2
        if target_ax is None:
            return

        if ymin is not None and ymax is not None:
            target_ax.set_ylim(ymin, ymax)
        elif ymin is not None:
            target_ax.set_ylim(bottom=ymin)
        elif ymax is not None:
            target_ax.set_ylim(top=ymax)
        else:
            target_ax.set_ylim(auto=True)

        self.canvas.draw()

    def enable_secondary_axis(self, enable=True):
        """
        Enable or disable the secondary Y-axis.

        Args:
            enable: Whether to enable the secondary axis
        """
        if enable:
            if self.ax2 is None:
                self.ax2 = self.ax.twinx()
                self.ax2.set_ylabel('Voltage (V) / Current (A)', color='#d62728')
                self.ax2.tick_params(axis='y', labelcolor='#d62728')
        else:
            if self.ax2 is not None:
                self.ax2.set_visible(False)
                self.ax2 = None

        self.canvas.draw()

    def get_figure(self):
        """Get the matplotlib Figure object for advanced customization."""
        return self.fig

    def get_axes(self):
        """Get the matplotlib Axes objects."""
        return self.ax, self.ax2

    def save_figure(self, filepath, dpi=150):
        """
        Save the current plot to a file.

        Args:
            filepath: Path to save the figure to
            dpi: Resolution in dots per inch
        """
        self.fig.savefig(filepath, dpi=dpi, bbox_inches='tight')

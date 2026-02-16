"""
live_plot.py
PURPOSE: Display real-time updating graphs of sensor data
KEY CONCEPT: Use matplotlib's FigureCanvasTkAgg to embed plots in tkinter

Supports dual Y-axis plotting:
- Top plot: Temperature sensors (only if thermocouples selected)
- Bottom plot: Pressure sensors (only if pressure gauges selected)
- Power supply data on whichever axis is available
"""

import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
from datetime import datetime
from t8_daq_system.utils.helpers import convert_temperature
from t8_daq_system.hardware.frg702_reader import FRG702Reader


class LivePlot:
    # Default axis ranges (absolute scales)
    DEFAULT_TEMP_RANGE = (0, 300)  # Celsius
    DEFAULT_PRESS_RANGE = (1e-9, 1e-3) # mbar
    DEFAULT_PS_V_RANGE = (0, 60) # V
    DEFAULT_PS_I_RANGE = (0, 60) # A

    def __init__(self, parent_frame, data_buffer):
        """
        Initialize the live plot.

        Args:
            parent_frame: tkinter frame to put the plot in
            data_buffer: DataBuffer object to get data from
        """
        self.data_buffer = data_buffer
        self.parent = parent_frame

        # Create matplotlib figure with space for FRG-702 subplot
        self.fig = Figure(figsize=(7, 3), dpi=100)
        self.fig.patch.set_facecolor('#f0f0f0')  # Match tkinter background if needed
        self.ax = self.fig.add_subplot(111)

        # Maximize space
        self.fig.subplots_adjust(left=0.25, right=0.7, top=0.98, bottom=0.12)

        # Create secondary axes for power supply data
        self.ax2 = None  # Voltage
        self.ax3 = None  # Current

        # FRG-702 logarithmic subplot (created on demand)
        self.ax_frg702 = None
        self._has_frg702 = False

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

        # Standard color cycle
        self.colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                      '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

        # Power supply colors
        self.ps_colors = {
            'PS_Voltage': '#d62728',   # Red for voltage
            'PS_Current': '#ff7f0e'    # Orange for current
        }

        # Track what's currently shown
        self._showing_ps = False

        # Axis scale settings (for absolute scaling)
        self._temp_range = None
        self._press_range = None
        self._ps_v_range = None
        self._ps_i_range = None
        self._use_absolute_scales = False

        # Unit labels
        self._temp_unit = "°C"
        self._press_unit = "mbar"

    def set_absolute_scales(self, enabled=True, temp_range=None, press_range=None, 
                            ps_v_range=None, ps_i_range=None):
        """
        Enable or disable absolute (fixed) axis scales.

        Args:
            enabled: Whether to use absolute scales
            temp_range: Tuple (min, max) for temperature axis
            press_range: Tuple (min, max) for pressure axis
            ps_v_range: Tuple (min, max) for power supply voltage axis
            ps_i_range: Tuple (min, max) for power supply current axis
        """
        self._use_absolute_scales = enabled
        self._temp_range = temp_range if temp_range else self.DEFAULT_TEMP_RANGE
        self._press_range = press_range if press_range else self.DEFAULT_PRESS_RANGE
        self._ps_v_range = ps_v_range if ps_v_range else self.DEFAULT_PS_V_RANGE
        self._ps_i_range = ps_i_range if ps_i_range else self.DEFAULT_PS_I_RANGE

    def set_units(self, temp_unit="°C", press_unit="mbar"):
        """Set the unit labels for the axes."""
        self._temp_unit = temp_unit
        self._press_unit = press_unit
        
    def _prepare_data(self, timestamps, values, window_seconds=None, now=None):
        """Filter data by window and remove Nones."""
        if not timestamps or not values:
            return [], []
            
        valid_times = []
        valid_vals = []
        
        for t, v in zip(timestamps, values):
            if v is None:
                continue
            if window_seconds and now and (now - t).total_seconds() > window_seconds:
                continue
            valid_times.append(t)
            valid_vals.append(v)
            
        return valid_times, valid_vals

    def update(self, sensor_names, ps_names=None, window_seconds=None):
        """
        Refresh the plot with current data from the buffer.
        """
        # Get data from buffer and format it for the core update method
        plot_data = {}
        all_timestamps = []
        
        for name in sensor_names:
            ts, vals = self.data_buffer.get_sensor_data(name)
            plot_data[name] = vals
            if ts and not all_timestamps: # Use first available timestamps as reference
                all_timestamps = ts
                
        if ps_names:
            for name in ps_names:
                ts, vals = self.data_buffer.get_sensor_data(name)
                plot_data[name] = vals
                if ts and not all_timestamps:
                    all_timestamps = ts
                    
        # Live data from buffer is always in base units (C)
        # Force conversion by passing 'C' as data_units
        self._core_update(all_timestamps, plot_data, window_seconds, data_units={'temp': 'C'})

    def update_from_loaded_data(self, loaded_data, sensor_names=None, ps_names=None, window_seconds=None, data_units=None):
        """
        Update plot with pre-loaded data (from CSV file).
        
        Args:
            loaded_data: Dict with 'timestamps' list and sensor data dicts
            sensor_names: Optional list of sensor names to filter by
            ps_names: Optional list of power supply names to filter by
            window_seconds: If provided, only show data from the last X seconds
            data_units: Dict like {'temp': 'C', 'press': 'PSI'} indicating units in loaded_data
        """
        timestamps = loaded_data.get('timestamps', [])
        
        if sensor_names is not None or ps_names is not None:
            # Filter data by provided names
            plot_data = {}
            names_to_plot = (sensor_names or []) + (ps_names or [])
            for name in names_to_plot:
                if name in loaded_data:
                    plot_data[name] = loaded_data[name]
        else:
            # Pass everything except timestamps as data
            plot_data = {k: v for k, v in loaded_data.items() if k != 'timestamps'}
        
        self._core_update(timestamps, plot_data, window_seconds, data_units=data_units)

    def _ensure_frg702_subplot(self, has_frg702_data):
        """Create or remove the FRG-702 logarithmic subplot as needed."""
        if has_frg702_data and not self._has_frg702:
            # Need to add FRG-702 subplot — reconfigure figure layout
            self.fig.clear()
            self.ax = self.fig.add_subplot(211)
            self.ax_frg702 = self.fig.add_subplot(212)
            self.ax_frg702.set_yscale('log')
            self.ax2 = None  # Will be recreated on demand
            self.ax3 = None
            self._has_frg702 = True
            self.fig.subplots_adjust(left=0.15, right=0.92, top=0.98, bottom=0.08, hspace=0.25)
        elif not has_frg702_data and self._has_frg702:
            # Remove FRG-702 subplot
            self.fig.clear()
            self.ax = self.fig.add_subplot(111)
            self.ax_frg702 = None
            self.ax2 = None
            self.ax3 = None
            self._has_frg702 = False
            self.fig.subplots_adjust(left=0.15, right=0.92, top=0.98, bottom=0.12)

    def _core_update(self, timestamps, plot_data, window_seconds=None, data_units=None):
        """Core plotting logic used by both live and historical updates."""
        # Separate sensor types
        tc_names = [name for name in plot_data.keys() if name.startswith('TC_')]
        frg702_names = [name for name in plot_data.keys() if name.startswith('FRG702_')]
        ps_names = [name for name in plot_data.keys() if name.startswith('PS_')]

        # Create/remove FRG-702 subplot as needed
        self._ensure_frg702_subplot(len(frg702_names) > 0)

        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('Time (HH:MM:SS)')
        
        has_tc = len(tc_names) > 0
        has_ps = len(ps_names) > 0

        show_left_axis = has_tc
        show_right_axis = has_ps

        # Configure Left Axis (Temperature)
        if show_left_axis:
            self.ax.set_ylabel(f'Temperature ({self._temp_unit})', color='black')
            self.ax.tick_params(axis='y', labelcolor='black', labelleft=True)
            self.ax.yaxis.set_visible(True)
            if self._use_absolute_scales and self._temp_range:
                self.ax.set_ylim(self._temp_range)
        else:
            self.ax.set_ylabel('')
            self.ax.tick_params(axis='y', labelleft=False)
            self.ax.yaxis.set_visible(False)

        # Configure Right Axis (PS Voltage)
        if has_ps:
            if self.ax2 is None:
                self.ax2 = self.ax.twinx()
            
            self.ax2.clear()
            self.ax2.set_visible(True)
            self.ax2.yaxis.set_visible(True)

            self.ax2.set_ylabel('PS Voltage (V)', color=self.ps_colors['PS_Voltage'], rotation=270, labelpad=15)
            self.ax2.yaxis.set_label_position('right')
            self.ax2.tick_params(axis='y', labelcolor=self.ps_colors['PS_Voltage'])
            
            if self._use_absolute_scales and self._ps_v_range:
                self.ax2.set_ylim(self._ps_v_range)
                
            # Configure Third Axis (PS Current)
            if self.ax3 is None:
                self.ax3 = self.ax.twinx()
                # Offset the right spine to make room for the second axis
                self.ax3.spines['right'].set_position(('outward', 50))
                
            self.ax3.clear()
            self.ax3.set_visible(True)
            self.ax3.yaxis.set_visible(True)

            self.ax3.set_ylabel('PS Current (A)', color=self.ps_colors['PS_Current'], rotation=270, labelpad=15)
            self.ax3.yaxis.set_label_position('right')
            self.ax3.tick_params(axis='y', labelcolor=self.ps_colors['PS_Current'])
            
            if self._use_absolute_scales and self._ps_i_range:
                self.ax3.set_ylim(self._ps_i_range)
        else:
            if self.ax2 is not None:
                self.ax2.clear()
                self.ax2.set_visible(False)
            if self.ax3 is not None:
                self.ax3.clear()
                self.ax3.set_visible(False)

        if not timestamps:
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            self.canvas.draw_idle()
            return

        # Plotting
        legend_handles = []
        legend_labels = []
        
        # Color index to keep colors consistent across axes
        color_idx = 0

        # Reference time for windowing - always use last timestamp if available
        now = timestamps[-1] if timestamps and window_seconds else None

        # Plot TC data on LEFT axis
        data_temp_unit = data_units.get('temp', 'C') if data_units else 'C'
        for i, name in enumerate(tc_names):
            values = plot_data.get(name, [])
            
            # Convert units if needed
            if data_temp_unit != self._temp_unit:
                # Use C, F, K directly for comparison
                display_unit = self._temp_unit.replace('°', '')
                source_unit = data_temp_unit.replace('°', '')
                values = [convert_temperature(v, source_unit, display_unit) if v is not None else None for v in values]
                
            times, vals = self._prepare_data(timestamps, values, window_seconds, now)
            
            if times:
                color = self.colors[color_idx % len(self.colors)]
                color_idx += 1
                line, = self.ax.plot(times, vals, label=name, linewidth=2, color=color)
                legend_handles.append(line)
                legend_labels.append(name)

        # Plot PS data on RIGHT axis
        for i, name in enumerate(ps_names):
            values = plot_data.get(name, [])
            times, vals = self._prepare_data(timestamps, values, window_seconds, now)
            
            if times:
                color = self.ps_colors.get(name, self.colors[color_idx % len(self.colors)])
                color_idx += 1
                
                # Use ax2 for voltage, ax3 for current
                target_ax = self.ax2 if name == 'PS_Voltage' else self.ax3
                line, = target_ax.plot(times, vals, label=name, linewidth=2, color=color, linestyle='--')
                legend_handles.append(line)
                legend_labels.append(name)

        if legend_handles:
            # Sort legend to keep it somewhat organized
            combined = list(zip(legend_handles, legend_labels))
            # Sort: TC first, then PS
            combined.sort(key=lambda x: (not x[1].startswith('TC_'), x[1]))
            handles, labels = zip(*combined)
            self.ax.legend(handles, labels, loc='upper left', fontsize=8)

        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        # Manual adjustment for x-axis labels to save space
        for label in self.ax.get_xticklabels():
            label.set_rotation(0)
            label.set_fontsize(8)

        # Plot FRG-702 data on separate logarithmic subplot
        if self.ax_frg702 and frg702_names:
            self.ax_frg702.clear()
            self.ax_frg702.grid(True, alpha=0.3, which='both')
            self.ax_frg702.set_xlabel('Time (HH:MM:SS)')
            self.ax_frg702.set_ylabel(f'Pressure ({self._press_unit})')
            self.ax_frg702.set_yscale('log')
            if self._use_absolute_scales and self._press_range:
                self.ax_frg702.set_ylim(self._press_range)

            frg702_color_idx = 0
            data_press_unit = data_units.get('press', 'mbar') if data_units else 'mbar'
            for name in frg702_names:
                values = plot_data.get(name, [])
                
                # Convert units if needed
                if data_press_unit != self._press_unit:
                    values = [FRG702Reader.convert_pressure(v, self._press_unit) if v is not None else None for v in values]
                
                times, vals = self._prepare_data(timestamps, values, window_seconds, now)

                if times:
                    color = self.colors[frg702_color_idx % len(self.colors)]
                    frg702_color_idx += 1
                    self.ax_frg702.plot(times, vals, label=name, linewidth=2, color=color)

            self.ax_frg702.legend(loc='upper left', fontsize=8)
            self.ax_frg702.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            for label in self.ax_frg702.get_xticklabels():
                label.set_rotation(0)
                label.set_fontsize(8)

        self.canvas.draw_idle()


    def clear(self):
        """Clear the plot."""
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('Time (HH:MM:SS)')
        self.ax.set_ylabel(f'Temperature ({self._temp_unit})')

        if self.ax2 is not None:
            self.ax2.clear()

        if self.ax3 is not None:
            self.ax3.clear()

        if self.ax_frg702 is not None:
            self.ax_frg702.clear()
            self.ax_frg702.grid(True, alpha=0.3, which='both')
            self.ax_frg702.set_yscale('log')
            self.ax_frg702.set_ylabel(f'Pressure ({self._press_unit})')
            self.ax_frg702.set_xlabel('Time (HH:MM:SS)')

        self.canvas.draw_idle()

    def set_y_label(self, label):
        """Set the y-axis label."""
        self.ax.set_ylabel(label)
        self.canvas.draw_idle()

    def set_title(self, title):
        """Set the plot title."""
        self.ax.set_title(title)
        self.canvas.draw_idle()

    def set_y_limits(self, ymin=None, ymax=None, axis='primary'):
        """
        Set Y-axis limits.

        Args:
            ymin: Minimum Y value (None for auto)
            ymax: Maximum Y value (None for auto)
            axis: 'primary' for left axis, 'secondary' for right axis, 'tertiary' for offset right
        """
        if axis == 'primary':
            target_ax = self.ax
        elif axis == 'secondary':
            target_ax = self.ax2
        else:
            target_ax = self.ax3

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

        self.canvas.draw_idle()

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

        self.canvas.draw_idle()

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

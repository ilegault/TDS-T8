"""
live_plot.py
PURPOSE: Display real-time updating graphs of sensor data
KEY CONCEPT: Use matplotlib's FigureCanvasTkAgg to embed plots in tkinter

Each LivePlot instance is a single-subject figure controlled by plot_type:
  'tc'       – Thermocouple temperature lines on a linear Y-axis
  'pressure' – FRG-702 gauge lines on a logarithmic Y-axis
  'ps'       – PS_Voltage (left Y-axis) and PS_Current (right Y-axis)

Every plot shows the last 2 minutes of data (WINDOW_SECONDS = 120).

A horizontal scrollbar below the canvas lets the user browse history:
  scrollbar = 1.0  → live mode  (auto-advances, always shows most-recent 2 min)
  scrollbar < 0.98 → frozen mode (shows 2-min window at chosen history position)
Dragging back to 1.0 resumes live mode automatically.
"""

import tkinter as tk
from tkinter import ttk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from t8_daq_system.utils.helpers import convert_temperature
from t8_daq_system.hardware.frg702_reader import FRG702Reader


class LivePlot:
    # Default axis ranges (absolute scales)
    DEFAULT_TEMP_RANGE = (0, 300)       # Celsius
    DEFAULT_PRESS_RANGE = (1e-9, 1e-3)  # mbar
    DEFAULT_PS_V_RANGE = (0, 60)        # V
    DEFAULT_PS_I_RANGE = (0, 60)        # A

    # Fixed 2-minute rolling window for all plots
    WINDOW_SECONDS = 120

    def __init__(self, parent_frame, data_buffer, plot_type='tc', show_scrollbar=True):
        """
        Initialize a dedicated single-subject live plot.

        Args:
            parent_frame: tkinter frame to embed the plot in
            data_buffer:  DataBuffer object to read data from
            plot_type:    'tc' | 'pressure' | 'ps'
            show_scrollbar: If False, this plot is controlled externally
        """
        self.data_buffer = data_buffer
        self.parent = parent_frame
        self.plot_type = plot_type

        # Persistent line objects  {(category, sensor_name): Line2D}
        self.lines = {}

        # Sensors whose lines should be hidden (Change 6)
        self._hidden_sensors = set()

        # Axis scale settings
        self._temp_range = self.DEFAULT_TEMP_RANGE
        self._press_range = self.DEFAULT_PRESS_RANGE
        self._ps_v_range = self.DEFAULT_PS_V_RANGE
        self._ps_i_range = self.DEFAULT_PS_I_RANGE
        self._use_absolute_scales = False

        # Unit labels
        self._temp_unit = "°C"
        self._press_unit = "mbar"

        # Color cycles (default fallbacks)
        self.colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                       '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        self.ps_colors = {
            'PS_Voltage': '#d62728',   # Red
            'PS_Current': '#ff7f0e',   # Orange
        }

        # Custom appearance (overridden by apply_appearance())
        self._custom_tc_colors = list(self.colors)
        self._custom_tc_styles = ['solid'] * 10
        self._custom_tc_widths = [2] * 10
        self._custom_press_colors = ['#17becf', '#bcbd22', '#7f7f7f', '#e377c2']
        self._custom_press_styles = ['solid'] * 4
        self._custom_press_widths = [2] * 4

        # ── Build matplotlib figure ───────────────────────────────────────
        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.fig.patch.set_facecolor('#f0f0f0')

        if plot_type == 'ps':
            # Two y-axes: voltage (left) and current (right)
            self.ax = self.fig.add_subplot(111)
            self.ax2 = self.ax.twinx()
            self.ax.set_ylabel('PS Voltage (V)', color=self.ps_colors['PS_Voltage'])
            self.ax.tick_params(axis='y', labelcolor=self.ps_colors['PS_Voltage'])
            self.ax2.set_ylabel('PS Current (A)', color=self.ps_colors['PS_Current'],
                                rotation=270, labelpad=15)
            self.ax2.yaxis.set_label_position('right')
            self.ax2.tick_params(axis='y', labelcolor=self.ps_colors['PS_Current'])
            self.fig.subplots_adjust(left=0.12, right=0.85, top=0.95, bottom=0.18)
        elif plot_type == 'pressure':
            self.ax = self.fig.add_subplot(111)
            self.ax2 = None
            self.ax.set_ylabel(f'Pressure ({self._press_unit})')
            self.ax.set_yscale('log')
            self.fig.subplots_adjust(left=0.14, right=0.95, top=0.95, bottom=0.18)
        else:  # 'tc' (default)
            self.ax = self.fig.add_subplot(111)
            self.ax2 = None
            self.ax.set_ylabel(f'Temperature ({self._temp_unit})')
            self.fig.subplots_adjust(left=0.12, right=0.95, top=0.95, bottom=0.18)

        self.ax.set_xlabel('Time')
        self.ax.grid(True, alpha=0.3)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))

        # ── Scrollbar + mode label (Change 5) ─────────────────────────────
        scroll_frame = ttk.Frame(parent_frame)
        scroll_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=2, pady=(0, 2))

        self._mode_label = ttk.Label(
            scroll_frame, text="● LIVE", foreground='green', font=('Arial', 7)
        )
        self._mode_label.pack(side=tk.LEFT, padx=3)

        self._scroll_var = tk.DoubleVar(value=1.0)
        if show_scrollbar:
            self._scrollbar = ttk.Scale(
                scroll_frame, from_=0.0, to=1.0, orient=tk.HORIZONTAL,
                variable=self._scroll_var, command=self.sync_scroll
            )
            self._scrollbar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        else:
            self._scrollbar = None

        # ── Embed canvas ──────────────────────────────────────────────────
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Live / frozen state
        self._is_live = True
        self._frozen_right_edge = None  # datetime: right edge of frozen 2-min window

        # Slider mode: 'window_2min' (default) shows a fixed 2-minute viewport
        # whose right edge tracks the slider position.  'history_pct' shows all
        # data from session start up to the slider position (zoom-out view).
        self._slider_mode = 'window_2min'

        # Programmer overlay (dotted preview lines)
        self._overlay_times = []       # list of floats (seconds relative to ramp start)
        self._overlay_voltages = []    # list of floats
        self._overlay_currents = []    # list of floats
        self._overlay_line_v = None    # matplotlib Line2D or None
        self._overlay_line_a = None    # matplotlib Line2D or None
        self._overlay_start_time = None  # datetime when ramp started, or None

    # ──────────────────────────────────────────────────────────────────────
    # Scrollbar callback  (Change 5)
    # ──────────────────────────────────────────────────────────────────────

    def sync_scroll(self, value):
        """Handle scrollbar movement (can be called externally)."""
        val = float(value)
        self._scroll_var.set(val)
        if val > 0.98:
            # Transition (back) to live mode
            if not self._is_live:
                self._is_live = True
                self._frozen_right_edge = None
                self._mode_label.config(text="● LIVE", foreground='green')
        else:
            # Frozen mode: compute frozen right edge from scrollbar position
            self._is_live = False
            ts = self._get_all_timestamps()
            if ts:
                oldest = ts[0]
                newest = ts[-1]
                span = (newest - oldest).total_seconds()
                if span > 0:
                    self._frozen_right_edge = oldest + timedelta(seconds=val * span)
                else:
                    self._frozen_right_edge = newest
                self._mode_label.config(
                    text=self._frozen_right_edge.strftime('%H:%M:%S'),
                    foreground='gray'
                )
                # Redraw immediately when scroll changes in frozen mode
                self._do_update_frozen()

    def set_slider_mode(self, mode):
        """
        Switch between slider display modes.

        Args:
            mode: 'history_pct' — show all data from session start up to the
                  slider position (zoom-out view of the full session).
                  'window_2min' — always show a fixed 2-minute viewport whose
                  position is determined by the slider (current/default behavior).
        """
        self._slider_mode = mode
        if not self._is_live:
            self._do_update_frozen()

    def _get_all_timestamps(self):
        """Return all timestamps from the data buffer (from any available sensor)."""
        # Try common sensor names first for efficiency
        for prefix in ('TC_1', 'TC_2', 'FRG702_1', 'PS_Voltage', 'PS_Current'):
            ts, _ = self.data_buffer.get_sensor_data(prefix)
            if ts:
                return ts
        # Fallback: try any sensor in the buffer
        names = self.data_buffer.get_sensor_names()
        for name in names:
            ts, _ = self.data_buffer.get_sensor_data(name)
            if ts:
                return ts
        return []

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def set_sensor_visible(self, sensor_name, visible):
        """
        Show or hide a sensor's line in this plot.  (Change 6)

        Args:
            sensor_name: Sensor identifier (e.g. 'TC_1', 'PS_Voltage')
            visible:     True to show, False to hide
        """
        if not visible:
            self._hidden_sensors.add(sensor_name)
        else:
            self._hidden_sensors.discard(sensor_name)
        # Update any already-created line object immediately
        for key, line in self.lines.items():
            if key[1] == sensor_name:
                line.set_visible(visible)
        self.canvas.draw_idle()

    def update(self, sensor_names):
        """
        Refresh the plot with current live data.

        In live mode: advances the 2-min window to now and redraws.
        In frozen mode: no-op (only sync_scroll triggers redraws).

        Args:
            sensor_names: List of sensor names this plot should render.
        """
        if not self._is_live:
            return  # Frozen — only sync_scroll triggers redraws
        # Keep scrollbar pinned to right edge while live
        if self._scrollbar is not None:
            self._scroll_var.set(1.0)
        self._do_update_live(sensor_names)

    def update_from_loaded_data(self, loaded_data, sensor_names=None,
                                window_seconds=None, data_units=None):
        """
        Update plot with pre-loaded CSV data.

        Args:
            loaded_data:   dict with 'timestamps' key and per-sensor value lists
            sensor_names:  names to display (None = auto-select by plot_type)
            window_seconds: optional time-window override (default: WINDOW_SECONDS)
            data_units:    dict like {'temp': 'C', 'press': 'mbar'}
        """
        timestamps = loaded_data.get('timestamps', [])
        if not timestamps:
            return

        if sensor_names is not None:
            plot_data = {n: loaded_data[n] for n in sensor_names if n in loaded_data}
        else:
            # Auto-select based on plot_type
            if self.plot_type == 'tc':
                plot_data = {k: v for k, v in loaded_data.items()
                             if k.startswith('TC_') and not k.endswith('_rawV')
                             and k != 'timestamps'}
            elif self.plot_type == 'pressure':
                plot_data = {k: v for k, v in loaded_data.items()
                             if k.startswith('FRG702_') and k != 'timestamps'}
            elif self.plot_type == 'ps':
                plot_data = {k: v for k, v in loaded_data.items()
                             if k in ('PS_Voltage', 'PS_Current')}
            else:
                plot_data = {}

        ws = window_seconds if window_seconds is not None else self.WINDOW_SECONDS
        self._render(timestamps, plot_data, ws, data_units)

    def set_absolute_scales(self, enabled=True, temp_range=None, press_range=None,
                            ps_v_range=None, ps_i_range=None):
        """Enable or disable absolute (fixed) axis scales."""
        self._use_absolute_scales = enabled
        if temp_range:
            self._temp_range = temp_range
        if press_range:
            self._press_range = press_range
        if ps_v_range:
            self._ps_v_range = ps_v_range
        if ps_i_range:
            self._ps_i_range = ps_i_range

        if not enabled:
            self.ax.set_autoscaley_on(True)
            self.ax.relim()
            self.ax.autoscale_view()
            if self.ax2 is not None:
                self.ax2.set_autoscaley_on(True)
                self.ax2.relim()
                self.ax2.autoscale_view()

    def set_units(self, temp_unit="°C", press_unit="mbar"):
        """Set the unit labels for the axes."""
        self._temp_unit = temp_unit
        self._press_unit = press_unit
        if self.plot_type == 'tc':
            self.ax.set_ylabel(f'Temperature ({temp_unit})')
        elif self.plot_type == 'pressure':
            self.ax.set_ylabel(f'Pressure ({press_unit})')

    def clear(self):
        """Clear the plot and reset persistent line objects."""
        self.lines.clear()
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('Time')
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))

        # Reset overlay lines (they were removed by ax.clear())
        self._overlay_line_v = None
        self._overlay_line_a = None

        if self.plot_type == 'tc':
            self.ax.set_ylabel(f'Temperature ({self._temp_unit})')
        elif self.plot_type == 'pressure':
            self.ax.set_ylabel(f'Pressure ({self._press_unit})')
            self.ax.set_yscale('log')
        elif self.plot_type == 'ps':
            self.ax.set_ylabel('PS Voltage (V)', color=self.ps_colors['PS_Voltage'])
            if self.ax2 is not None:
                self.ax2.clear()
                self.ax2.set_ylabel('PS Current (A)',
                                    color=self.ps_colors['PS_Current'],
                                    rotation=270, labelpad=15)

        self.canvas.draw_idle()

    def save_figure(self, filepath, dpi=150):
        """Save the current plot to a file."""
        self.fig.savefig(filepath, dpi=dpi, bbox_inches='tight')

    def get_figure(self):
        """Get the matplotlib Figure object."""
        return self.fig

    def get_axes(self):
        """Get the matplotlib Axes objects."""
        return self.ax, self.ax2

    def apply_appearance(self, tc_colors=None, tc_styles=None, tc_widths=None,
                         press_colors=None, press_styles=None, press_widths=None,
                         ps_voltage_color=None, ps_current_color=None,
                         ps_voltage_style=None, ps_current_style=None,
                         ps_voltage_width=None, ps_current_width=None):
        """
        Apply appearance settings to existing and future plot lines.
        Call this after loading settings or after the user saves in Settings dialog.
        """
        if tc_colors:
            self._custom_tc_colors = list(tc_colors)
        if tc_styles:
            self._custom_tc_styles = list(tc_styles)
        if tc_widths:
            self._custom_tc_widths = [int(w) for w in tc_widths if str(w).strip()]
        if press_colors:
            self._custom_press_colors = list(press_colors)
        if press_styles:
            self._custom_press_styles = list(press_styles)
        if press_widths:
            self._custom_press_widths = [int(w) for w in press_widths if str(w).strip()]
        if ps_voltage_color:
            self.ps_colors['PS_Voltage'] = ps_voltage_color
        if ps_current_color:
            self.ps_colors['PS_Current'] = ps_current_color
        if ps_voltage_style:
            self._ps_voltage_style = ps_voltage_style
        if ps_current_style:
            self._ps_current_style = ps_current_style
        if ps_voltage_width:
            try:
                self._ps_voltage_width = int(ps_voltage_width)
            except (ValueError, TypeError):
                pass
        if ps_current_width:
            try:
                self._ps_current_width = int(ps_current_width)
            except (ValueError, TypeError):
                pass
        # Apply immediately to any already-drawn lines
        self._reapply_line_styles()
        self.canvas.draw_idle()

    def _linestyle_str_to_mpl(self, style_str):
        """Convert a style name string to a matplotlib linestyle specifier."""
        mapping = {'solid': '-', 'dashed': '--', 'dotted': ':', 'dashdot': '-.'}
        return mapping.get(style_str, '-')

    def _reapply_line_styles(self):
        """Update color/linestyle/linewidth on all existing Line2D objects."""
        tc_idx = 0
        press_idx = 0
        for key, line in self.lines.items():
            category, name = key
            if category == 'tc':
                if self._custom_tc_colors:
                    line.set_color(self._custom_tc_colors[tc_idx % len(self._custom_tc_colors)])
                if self._custom_tc_styles:
                    line.set_linestyle(self._linestyle_str_to_mpl(
                        self._custom_tc_styles[tc_idx % len(self._custom_tc_styles)]
                    ))
                if self._custom_tc_widths:
                    line.set_linewidth(self._custom_tc_widths[tc_idx % len(self._custom_tc_widths)])
                tc_idx += 1
            elif category == 'frg':
                if self._custom_press_colors:
                    line.set_color(self._custom_press_colors[press_idx % len(self._custom_press_colors)])
                if self._custom_press_styles:
                    line.set_linestyle(self._linestyle_str_to_mpl(
                        self._custom_press_styles[press_idx % len(self._custom_press_styles)]
                    ))
                if self._custom_press_widths:
                    line.set_linewidth(self._custom_press_widths[press_idx % len(self._custom_press_widths)])
                press_idx += 1
            elif category == 'ps':
                color = self.ps_colors.get(name, '#666666')
                line.set_color(color)
                # PS voltage/current style
                if name == 'PS_Voltage' and hasattr(self, '_ps_voltage_style'):
                    line.set_linestyle(self._linestyle_str_to_mpl(self._ps_voltage_style))
                    line.set_linewidth(self._ps_voltage_width)
                elif name == 'PS_Current' and hasattr(self, '_ps_current_style'):
                    line.set_linestyle(self._linestyle_str_to_mpl(self._ps_current_style))
                    line.set_linewidth(self._ps_current_width)

    def set_programmer_overlay(self, times, voltages, currents):
        """
        Set the dotted preview overlay on the ps plot.
        Call with empty lists to clear the overlay.

        Args:
            times:    list of floats in seconds (relative offsets from ramp start)
            voltages: list of floats in volts
            currents: list of floats in amps
        """
        self._overlay_times = times
        self._overlay_voltages = voltages
        self._overlay_currents = currents
        self._overlay_start_time = None  # Reset; set when ramp starts

    def set_overlay_start_time(self, start_datetime):
        """Call this when the ramp actually begins to anchor the overlay in time."""
        self._overlay_start_time = start_datetime

    # ──────────────────────────────────────────────────────────────────────
    # Internal rendering helpers
    # ──────────────────────────────────────────────────────────────────────

    def _do_update_live(self, sensor_names):
        """Render the most recent WINDOW_SECONDS of data (live mode)."""
        plot_data = {}
        all_timestamps = []
        for name in sensor_names:
            ts, vals = self.data_buffer.get_sensor_data(name)
            plot_data[name] = vals
            if ts and not all_timestamps:
                all_timestamps = ts
        self._render(all_timestamps, plot_data, self.WINDOW_SECONDS,
                     data_units={'temp': 'C', 'press': 'mbar'})

    def _do_update_frozen(self):
        """Render frozen view ending at _frozen_right_edge.

        In 'window_2min' mode the viewport is always WINDOW_SECONDS wide.
        In 'history_pct' mode all data from the session start to
        _frozen_right_edge is shown (no time-window clipping).
        """
        if self._frozen_right_edge is None:
            return
        # Collect all data from buffer and filter to this plot's sensor types
        names = self.data_buffer.get_sensor_names()
        plot_data = {}
        all_timestamps = []
        for name in names:
            ts, vals = self.data_buffer.get_sensor_data(name)
            if self._sensor_belongs(name):
                plot_data[name] = vals
            if ts and not all_timestamps:
                all_timestamps = ts
        ws = self.WINDOW_SECONDS if self._slider_mode == 'window_2min' else None
        self._render(all_timestamps, plot_data, ws,
                     data_units={'temp': 'C', 'press': 'mbar'},
                     right_edge=self._frozen_right_edge)

    def _sensor_belongs(self, name):
        """Return True if the sensor name belongs to this plot's type."""
        if self.plot_type == 'tc':
            return name.startswith('TC_') and not name.endswith('_rawV')
        elif self.plot_type == 'pressure':
            return name.startswith('FRG702_')
        elif self.plot_type == 'ps':
            return name in ('PS_Voltage', 'PS_Current')
        return False

    def _prepare_data(self, timestamps, values, window_seconds, right_edge=None):
        """Filter (timestamp, value) pairs by time window and strip Nones."""
        if not timestamps or not values:
            return [], []

        now = right_edge if right_edge is not None else (timestamps[-1] if timestamps else None)

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

    def _render(self, timestamps, plot_data, window_seconds=None,
                data_units=None, right_edge=None):
        """
        Core rendering logic using persistent line objects for performance.

        Creates Line2D objects on first call; updates set_data() on subsequent
        calls to avoid expensive full matplotlib redraws every cycle.

        Args:
            timestamps:    List of datetime objects (shared x-axis).
            plot_data:     Dict {sensor_name: [values]}.
            window_seconds: Only show data within this many seconds of right_edge
                           (or now if right_edge is None).
            data_units:    Dict {'temp': unit, 'press': unit} for source data.
            right_edge:    datetime for the right edge of the view window
                           (None = use last timestamp = live mode).
        """
        if not timestamps:
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            self.canvas.draw_idle()
            return

        now = right_edge if right_edge is not None else (
            timestamps[-1] if timestamps and window_seconds else None
        )
        ws = window_seconds
        active_line_keys = set()
        color_idx = 0

        # ── TC plot ────────────────────────────────────────────────────────
        if self.plot_type == 'tc':
            data_temp_unit = (data_units.get('temp', 'C') if data_units else 'C')
            tc_names = sorted(
                n for n in plot_data
                if n.startswith('TC_') and not n.endswith('_rawV')
            )
            for name in tc_names:
                values = list(plot_data.get(name, []))
                # Unit conversion
                if data_temp_unit != self._temp_unit:
                    disp_u = self._temp_unit.replace('°', '')
                    src_u = data_temp_unit.replace('°', '')
                    values = [
                        convert_temperature(v, src_u, disp_u) if v is not None else None
                        for v in values
                    ]
                times, vals = self._prepare_data(timestamps, values, ws, now)
                color = self._custom_tc_colors[color_idx % len(self._custom_tc_colors)]
                style = self._linestyle_str_to_mpl(
                    self._custom_tc_styles[color_idx % len(self._custom_tc_styles)]
                )
                width = self._custom_tc_widths[color_idx % len(self._custom_tc_widths)]
                color_idx += 1

                line_key = ('tc', name)
                active_line_keys.add(line_key)
                visible = name not in self._hidden_sensors

                if line_key in self.lines:
                    self.lines[line_key].set_data(times, vals)
                    self.lines[line_key].set_visible(visible)
                else:
                    line, = self.ax.plot(times, vals, label=name, linewidth=width,
                                         color=color, linestyle=style, visible=visible)
                    self.lines[line_key] = line

            if self._use_absolute_scales and self._temp_range:
                self.ax.set_ylim(self._temp_range)

        # ── Pressure plot ──────────────────────────────────────────────────
        elif self.plot_type == 'pressure':
            data_press_unit = (data_units.get('press', 'mbar') if data_units else 'mbar')
            frg_names = sorted(n for n in plot_data if n.startswith('FRG702_'))
            for name in frg_names:
                values = list(plot_data.get(name, []))
                # Unit conversion
                if data_press_unit != self._press_unit:
                    values = [
                        FRG702Reader.convert_pressure(v, self._press_unit)
                        if v is not None else None
                        for v in values
                    ]
                times, vals = self._prepare_data(timestamps, values, ws, now)
                color = self._custom_press_colors[color_idx % len(self._custom_press_colors)]
                style = self._linestyle_str_to_mpl(
                    self._custom_press_styles[color_idx % len(self._custom_press_styles)]
                )
                width = self._custom_press_widths[color_idx % len(self._custom_press_widths)]
                color_idx += 1

                line_key = ('frg', name)
                active_line_keys.add(line_key)
                visible = name not in self._hidden_sensors

                if line_key in self.lines:
                    self.lines[line_key].set_data(times, vals)
                    self.lines[line_key].set_visible(visible)
                else:
                    line, = self.ax.plot(times, vals, label=name, linewidth=width,
                                         color=color, linestyle=style, visible=visible)
                    self.lines[line_key] = line

            if self._use_absolute_scales and self._press_range:
                self.ax.set_ylim(self._press_range)

        # ── PS V & I plot ──────────────────────────────────────────────────
        elif self.plot_type == 'ps':
            ps_axis_map = {
                'PS_Voltage': (self.ax,  self._ps_v_range),
                'PS_Current': (self.ax2, self._ps_i_range),
            }
            for name, (target_ax, abs_range) in ps_axis_map.items():
                if target_ax is None:
                    continue
                values = list(plot_data.get(name, []))
                times, vals = self._prepare_data(timestamps, values, ws, now)
                color = self.ps_colors.get(name, '#666666')

                line_key = ('ps', name)
                active_line_keys.add(line_key)
                visible = name not in self._hidden_sensors

                if line_key in self.lines:
                    self.lines[line_key].set_data(times, vals)
                    self.lines[line_key].set_visible(visible)
                else:
                    line, = target_ax.plot(times, vals, label=name, linewidth=2,
                                           color=color, linestyle='--', visible=visible)
                    self.lines[line_key] = line

                if self._use_absolute_scales and abs_range:
                    target_ax.set_ylim(abs_range)

        # ── Remove stale line objects ──────────────────────────────────────
        stale_keys = [k for k in self.lines if k not in active_line_keys]
        for key in stale_keys:
            self.lines[key].remove()
            del self.lines[key]

        # ── Autoscaling ────────────────────────────────────────────────────
        self.ax.relim()
        if self._use_absolute_scales:
            self.ax.autoscale_view(scaley=False)
        else:
            self.ax.autoscale_view()

        if self.ax2 is not None:
            self.ax2.relim()
            if not self._use_absolute_scales:
                self.ax2.autoscale_view()

        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.ax.grid(True, alpha=0.3)

        # ── Programmer overlay (dotted preview lines) for ps plot ──────────
        if self.plot_type == 'ps' and self._overlay_times and self._overlay_voltages:
            # Remove stale overlay lines
            if self._overlay_line_v is not None:
                try:
                    self._overlay_line_v.remove()
                except (ValueError, NotImplementedError):
                    pass
                self._overlay_line_v = None
            if self._overlay_line_a is not None and self.ax2 is not None:
                try:
                    self._overlay_line_a.remove()
                except (ValueError, NotImplementedError):
                    pass
                self._overlay_line_a = None

            if self._overlay_start_time is not None:
                # Convert relative seconds to absolute datetime for x-axis alignment
                from datetime import timedelta
                overlay_datetimes = [
                    self._overlay_start_time + timedelta(seconds=t)
                    for t in self._overlay_times
                ]
                self._overlay_line_v, = self.ax.plot(
                    overlay_datetimes, self._overlay_voltages,
                    color='blue', linestyle=':', linewidth=1.5, alpha=0.6,
                    label='Programmed V'
                )
                if self.ax2 is not None:
                    self._overlay_line_a, = self.ax2.plot(
                        overlay_datetimes, self._overlay_currents,
                        color='red', linestyle=':', linewidth=1.5, alpha=0.6,
                        label='Programmed I'
                    )

        # ── Legend (built after overlay so all lines are included) ─────────
        handles = list(self.lines.values())
        labels = [k[1] for k in self.lines.keys()]
        if self.plot_type == 'ps':
            if self._overlay_line_v is not None:
                handles.append(self._overlay_line_v)
                labels.append('Programmed V')
            if self._overlay_line_a is not None:
                handles.append(self._overlay_line_a)
                labels.append('Programmed I')
        if handles:
            self.ax.legend(handles, labels, loc='upper left', fontsize=7)

        self.canvas.draw_idle()

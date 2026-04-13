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
    DEFAULT_PS_V_RANGE = (0, 6)         # V (Keysight N5700 max is 6V)
    DEFAULT_PS_I_RANGE = (0, 180)       # A (Keysight N5700 max is 180A)

    # Rolling window for all plots (2 minutes = 120 seconds)
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

        # Track the units of the data stored in DataBuffer
        self._data_units = {'temp': 'C', 'press': 'mbar'}

        # Valid sensor names for this plot (Change 7: avoid startswith)
        self._valid_sensor_names = set()

        # Color cycles (default fallbacks)
        self.colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                       '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        self.ps_colors = {
            'PS_Voltage':          '#d62728',   # Red
            'PS_Current':          '#ff7f0e',   # Orange
            'PS_Voltage_Setpoint': '#4488FF',   # Light blue — setpoint
            'PS_CC_Limit':         '#FF8800',   # Orange — current ceiling
        }

        # Optional legend label overrides: {sensor_key -> display label}
        self._legend_label_overrides: dict = {}

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
        self._loaded_timestamps = []   # timestamps from CSV load (list of datetime)
        self._loaded_plot_data = {}    # {sensor_name: [values]} from CSV load

        # Programmer overlay (dotted preview lines)
        self._overlay_times = []       # list of floats (seconds relative to ramp start)
        self._overlay_voltages = []    # list of floats
        self._overlay_line_v = None    # matplotlib Line2D or None
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
                if self._slider_mode == 'window_2min':
                    window_start = self._frozen_right_edge - timedelta(seconds=self.WINDOW_SECONDS)
                    self._mode_label.config(
                        text=f"{window_start.strftime('%H:%M:%S')} → {self._frozen_right_edge.strftime('%H:%M:%S')}",
                        foreground='gray'
                    )
                else:
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
        """Return all timestamps (CSV cache first, then data buffer)."""
        if self._loaded_timestamps:
            return self._loaded_timestamps
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
        Show or hide a sensor's line in this plot.
        When auto-scale is active and a line is hidden/shown, the Y-axis
        immediately re-scales to only the visible data.
        """
        if not visible:
            self._hidden_sensors.add(sensor_name)
        else:
            self._hidden_sensors.discard(sensor_name)

        # Update any already-created line object immediately
        for key, line in self.lines.items():
            if key[1] == sensor_name:
                line.set_visible(visible)

        # If auto-scale is active, recompute limits from visible lines only
        if not self._use_absolute_scales:
            self._autoscale_visible_only()

        self.canvas.draw_idle()

    # Setpoint/limit lines excluded from autoscale on the PS plot
    _PS_AUTOSCALE_EXCLUDE = {'PS_Voltage_Setpoint', 'PS_CC_Limit'}

    def _autoscale_visible_only(self):
        """
        Recompute Y-axis limits based solely on data in currently-visible lines.
        Called after any hide/show toggle when auto-scale mode is active.
        For the PS plot, reference lines (Setpoint, CC_Limit) are excluded so
        the axes scale to the measured Voltage / Current only.
        """
        def _get_bounds(ax):
            """Return (ymin, ymax) across all visible lines on this axis, or None."""
            y_all = []
            for key, line in self.lines.items():
                if line.axes is not ax:
                    continue
                if not line.get_visible():
                    continue
                # Skip reference lines on PS plot
                if self.plot_type == 'ps' and key[1] in self._PS_AUTOSCALE_EXCLUDE:
                    continue
                ydata = line.get_ydata()
                valid = [y for y in ydata if y is not None and y == y]
                if valid:
                    y_all.extend(valid)
            if not y_all:
                return None
            return min(y_all), max(y_all)

        bounds_main = _get_bounds(self.ax)
        if bounds_main is not None:
            lo, hi = bounds_main
            if self.plot_type == 'pressure':
                if lo <= 0:
                    lo = 1e-12
                self.ax.set_ylim(lo * 0.9, hi * 1.1)
            else:
                margin = (hi - lo) * 0.05 if hi != lo else 1.0
                self.ax.set_ylim(lo - margin, hi + margin)

        if self.ax2 is not None:
            bounds_ax2 = _get_bounds(self.ax2)
            if bounds_ax2 is not None:
                lo2, hi2 = bounds_ax2
                margin2 = (hi2 - lo2) * 0.05 if hi2 != lo2 else 1.0
                self.ax2.set_ylim(lo2 - margin2, hi2 + margin2)

    def update(self, sensor_names, data_units=None):
        """
        Refresh the plot with current live data.

        In live mode: advances the 2-min window to now and redraws.
        In frozen mode: no-op (only sync_scroll triggers redraws).

        Args:
            sensor_names: List of sensor names this plot should render.
            data_units:   Optional dict like {'temp': 'C', 'press': 'mbar'}
        """
        if data_units:
            self._data_units.update(data_units)

        # Remember the current sensor list so frozen mode uses the same names
        if sensor_names:
            self._active_sensor_names = list(sensor_names)
            self._valid_sensor_names = set(sensor_names)

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
        On first call: enters frozen mode and caches the data.
        Subsequent calls: no-op if already frozen (scroll handles rendering).
        """
        timestamps = loaded_data.get('timestamps', [])
        if not timestamps:
            return

        if data_units:
            self._data_units.update(data_units)

        if sensor_names is not None:
            plot_data = {n: loaded_data[n] for n in sensor_names if n in loaded_data}
            self._valid_sensor_names = set(sensor_names)
        else:
            if self.plot_type == 'tc':
                plot_data = {k: v for k, v in loaded_data.items()
                             if self._sensor_belongs(k) and k != 'timestamps'}
            elif self.plot_type == 'pressure':
                plot_data = {k: v for k, v in loaded_data.items()
                             if self._sensor_belongs(k) and k != 'timestamps'}
            elif self.plot_type == 'ps':
                plot_data = {k: v for k, v in loaded_data.items()
                             if k in ('PS_Voltage', 'PS_Current')}
            else:
                plot_data = {}

        # Cache the loaded data so sync_scroll / _do_update_frozen can use it
        self._loaded_timestamps = timestamps
        self._loaded_plot_data = plot_data

        # Enter frozen mode pinned to the right edge (show most recent data first)
        self._is_live = False
        self._frozen_right_edge = timestamps[-1]
        if self._scrollbar is not None:
            self._scroll_var.set(1.0)
        if self._mode_label is not None:
            self._mode_label.config(text="● CSV", foreground='blue')

        # Render using current scroll position / slider mode
        self._do_update_frozen()

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

        # Reset overlay line (removed by ax.clear())
        self._overlay_line_v = None

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
                self.ax2.yaxis.set_label_position('right')
                self.ax2.tick_params(axis='y', labelcolor=self.ps_colors['PS_Current'])
                self.ax.tick_params(axis='y', labelcolor=self.ps_colors['PS_Voltage'])
                self.fig.subplots_adjust(left=0.12, right=0.85, top=0.95, bottom=0.18)

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
                         ps_voltage_width=None, ps_current_width=None,
                         pp_voltage_color=None, pp_voltage_style=None,
                         pp_voltage_width=None):
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
        # Cache pp_voltage overlay appearance settings
        if pp_voltage_color:
            self._pp_voltage_color = pp_voltage_color
        if pp_voltage_style:
            self._pp_voltage_style = pp_voltage_style
        if pp_voltage_width:
            self._pp_voltage_width = pp_voltage_width
        # ── Re-apply axis label colors and layout for ps plot ──────────────────
        if self.plot_type == 'ps':
            self.ax.set_ylabel('PS Voltage (V)', color=self.ps_colors['PS_Voltage'])
            self.ax.tick_params(axis='y', labelcolor=self.ps_colors['PS_Voltage'])
            if self.ax2 is not None:
                self.ax2.set_ylabel(
                    'PS Current (A)',
                    color=self.ps_colors['PS_Current'],
                    rotation=270, labelpad=15
                )
                self.ax2.yaxis.set_label_position('right')
                self.ax2.tick_params(axis='y', labelcolor=self.ps_colors['PS_Current'])
            # Re-enforce the fixed margins that keep both labels on-screen
            self.fig.subplots_adjust(left=0.12, right=0.85, top=0.95, bottom=0.18)
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

        # Apply appearance to voltage setpoint overlay line if it exists
        if self.plot_type == "ps" and self._overlay_line_v is not None:
            try:
                ov_color = getattr(self, "_pp_voltage_color", None)
                ov_style = getattr(self, "_pp_voltage_style", None)
                ov_width = getattr(self, "_pp_voltage_width", None)
                if ov_color:
                    self._overlay_line_v.set_color(ov_color)
                if ov_style:
                    self._overlay_line_v.set_linestyle(self._linestyle_str_to_mpl(ov_style))
                if ov_width:
                    self._overlay_line_v.set_linewidth(int(ov_width))
            except Exception:
                pass

    def set_programmer_overlay(self, times, voltages, currents=None):
        """Set dotted voltage preview overlay on the ps plot. Pass empty lists to clear.

        Args:
            times:    list of floats in seconds (relative offsets from ramp start)
            voltages: list of floats in volts
            currents: accepted for backward compatibility but ignored
        """
        self._overlay_times = times
        self._overlay_voltages = voltages
        # currents parameter accepted for backward compatibility but ignored
        self._overlay_start_time = None  # Reset; set when ramp starts

    def set_overlay_start_time(self, start_datetime):
        """Call this when the ramp actually begins to anchor the overlay in time."""
        self._overlay_start_time = start_datetime

    def set_legend_label_overrides(self, overrides: dict):
        """
        Override the legend label for specific sensor keys.

        Args:
            overrides: dict mapping internal key → display label.
                       Pass an empty dict {} to clear all overrides.
        Example:
            plot_ps.set_legend_label_overrides({'PS_Current': 'CC Limit (A)'})
        """
        self._legend_label_overrides = dict(overrides)

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
                     data_units=self._data_units)

    def _do_update_frozen(self):
        """Render frozen view ending at _frozen_right_edge.

        Uses _loaded_timestamps/_loaded_plot_data when CSV data is loaded,
        otherwise reads from data_buffer.
        In 'window_2min' mode the viewport is WINDOW_SECONDS wide.
        In 'history_pct' mode all data from session start to right_edge is shown.
        """
        if self._frozen_right_edge is None:
            return

        # Choose data source: CSV cache takes priority over live buffer
        if self._loaded_timestamps:
            all_timestamps = self._loaded_timestamps
            plot_data = self._loaded_plot_data
        else:
            active = getattr(self, '_active_sensor_names', None)
            if active:
                names = active
            else:
                names = [n for n in self.data_buffer.get_sensor_names()
                         if self._sensor_belongs(n)]
            plot_data = {}
            all_timestamps = []
            for name in names:
                ts, vals = self.data_buffer.get_sensor_data(name)
                plot_data[name] = vals
                if ts and not all_timestamps:
                    all_timestamps = ts

        ws = self.WINDOW_SECONDS if self._slider_mode == 'window_2min' else None
        self._render(all_timestamps, plot_data, ws,
                     data_units=self._data_units,
                     right_edge=self._frozen_right_edge)

    def _sensor_belongs(self, name):
        """Return True if the sensor name belongs to this plot's type."""
        if self._valid_sensor_names and name in self._valid_sensor_names:
            return True
        # Fallback for when update() hasn't been called yet
        if self.plot_type == 'tc':
            return name.startswith('TC_') and not name.endswith('_rawV')
        elif self.plot_type == 'pressure':
            return name.startswith('FRG702_')
        elif self.plot_type == 'ps':
            return name in ('PS_Voltage', 'PS_Current',
                            'PS_Voltage_Setpoint', 'PS_CC_Limit')
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

        # Plot decimation (Task 6b): keep only last 600 points
        MAX_PLOT_POINTS = 600
        if len(valid_times) > MAX_PLOT_POINTS:
            valid_times = valid_times[-MAX_PLOT_POINTS:]
            valid_vals = valid_vals[-MAX_PLOT_POINTS:]

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
                if not n.endswith('_rawV')
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

            if self._use_absolute_scales and self._temp_range and self.plot_type == 'tc':
                self.ax.set_ylim(self._temp_range)

        # ── Pressure plot ──────────────────────────────────────────────────
        elif self.plot_type == 'pressure':
            data_press_unit = (data_units.get('press', 'mbar') if data_units else 'mbar')
            frg_names = sorted(n for n in plot_data if self._sensor_belongs(n))
            for name in frg_names:
                values = list(plot_data.get(name, []))
                # Unit conversion: convert from data unit to display unit
                if data_press_unit != self._press_unit:
                    values = [
                        FRG702Reader.convert_pressure(v, data_press_unit, self._press_unit)
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

            if self._use_absolute_scales and self._press_range and self.plot_type == 'pressure':
                self.ax.set_ylim(self._press_range)

        # ── PS V & I plot ──────────────────────────────────────────────────
        elif self.plot_type == 'ps':
            ps_axis_map = {
                'PS_Voltage':          (self.ax,  self._ps_v_range),
                'PS_Voltage_Setpoint': (self.ax,  self._ps_v_range),   # Same left axis as voltage
                'PS_Current':          (self.ax2, self._ps_i_range),
                'PS_CC_Limit':         (self.ax2, self._ps_i_range),   # Same right axis as current
            }
            _linestyle_map = {
                'PS_Voltage':          '-',
                'PS_Voltage_Setpoint': '--',
                'PS_Current':          '-',
                'PS_CC_Limit':         ':',
            }
            for name, (target_ax, abs_range) in ps_axis_map.items():
                if target_ax is None:
                    continue
                values = list(plot_data.get(name, []))
                times, vals = self._prepare_data(timestamps, values, ws, now)

                # Debug: log values for PS_Voltage_Setpoint if they look suspiciously high
                if name == 'PS_Voltage_Setpoint' and vals:
                    max_val = max([v for v in vals if v is not None] or [0])
                    if max_val > 6.1: # Allow a tiny bit of overshoot/noise but not 300
                        print(f"[DEBUG] CRITICAL: PS_Voltage_Setpoint has high value {max_val:.1f} in LivePlot")

                color = self.ps_colors.get(name, '#666666')
                _ls = _linestyle_map.get(name, '--')

                line_key = ('ps', name)
                active_line_keys.add(line_key)
                visible = name not in self._hidden_sensors

                if line_key in self.lines:
                    self.lines[line_key].set_data(times, vals)
                    self.lines[line_key].set_visible(visible)
                else:
                    line, = target_ax.plot(times, vals, label=name, linewidth=2,
                                           color=color, linestyle=_ls, visible=visible)
                    self.lines[line_key] = line

                if self._use_absolute_scales and abs_range and self.plot_type == 'ps':
                    target_ax.set_ylim(abs_range)

        # ── Remove stale line objects ──────────────────────────────────────
        stale_keys = [k for k in self.lines if k not in active_line_keys]
        for key in stale_keys:
            self.lines[key].remove()
            del self.lines[key]

        # ── Autoscaling ────────────────────────────────────────────────────
        if self.plot_type == 'ps' and not self._use_absolute_scales:
            # For the PS plot, autoscale only from the measured lines (Voltage &
            # Current), not the reference/limit lines (Setpoint & CC_Limit).
            # Including those causes the axis to jump to fit e.g. 180 A CC_Limit
            # while the real current is in single digits.
            _measured_ax  = {('ps', 'PS_Voltage')}
            _measured_ax2 = {('ps', 'PS_Current')}

            def _ylim_from_keys(ax, keys):
                y_all = []
                for key in keys:
                    line = self.lines.get(key)
                    if line is None:
                        continue
                    ydata = [y for y in line.get_ydata() if y is not None and y == y]
                    y_all.extend(ydata)
                if not y_all:
                    return
                lo, hi = min(y_all), max(y_all)
                margin = (hi - lo) * 0.1 if hi != lo else max(abs(hi) * 0.1, 0.1)
                ax.set_ylim(lo - margin, hi + margin)

            _ylim_from_keys(self.ax, _measured_ax)
            if self.ax2 is not None:
                _ylim_from_keys(self.ax2, _measured_ax2)
            # Still update x-axis autoscale
            self.ax.autoscale_view(scaley=False)
        else:
            self.ax.relim()
            if self._use_absolute_scales:
                self.ax.autoscale_view(scaley=False)
                if self.ax2 is not None:
                    self.ax2.relim()
            else:
                self._autoscale_visible_only()

        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.ax.grid(True, alpha=0.3)

        # ── Set X axis limits ────────────────────────────────────────────────
        if right_edge is not None:
            # Frozen mode
            if window_seconds is not None:
                # 2-min window: show exactly [right_edge - window_seconds, right_edge]
                x_right = right_edge
                x_left  = right_edge - timedelta(seconds=window_seconds)
            else:
                # History-pct mode: show all data from oldest timestamp to right_edge
                if timestamps:
                    x_left  = timestamps[0]
                else:
                    x_left  = right_edge - timedelta(seconds=self.WINDOW_SECONDS)
                x_right = right_edge
            self.ax.set_xlim(x_left, x_right)
        else:
            # Live mode: show [now - window_seconds, now]
            now_dt = datetime.now()
            self.ax.set_xlim(
                now_dt - timedelta(seconds=window_seconds or self.WINDOW_SECONDS),
                now_dt
            )

        # ── Programmer overlay (dotted voltage preview line) for ps plot ───
        if self.plot_type == 'ps' and self._overlay_times and self._overlay_voltages:
            # Remove stale overlay line
            if self._overlay_line_v is not None:
                try:
                    self._overlay_line_v.remove()
                except (ValueError, NotImplementedError):
                    pass
                self._overlay_line_v = None

            if self._overlay_start_time is not None:
                # Convert relative seconds to absolute datetime for x-axis alignment
                overlay_datetimes = [
                    self._overlay_start_time + timedelta(seconds=t)
                    for t in self._overlay_times
                ]
                ov_color = getattr(self, '_pp_voltage_color', 'blue')
                ov_style = getattr(self, '_pp_voltage_style', 'dotted')
                ov_width = getattr(self, '_pp_voltage_width', '1')
                self._overlay_line_v, = self.ax.plot(
                    overlay_datetimes, self._overlay_voltages,
                    color=ov_color,
                    linestyle=self._linestyle_str_to_mpl(ov_style) if isinstance(ov_style, str) else ':',
                    linewidth=int(ov_width) if str(ov_width).isdigit() else 1,
                    alpha=0.6,
                    label='Voltage Setpoint'
                )

        # ── Legend (built after overlay so all lines are included) ─────────
        handles = list(self.lines.values())
        labels = [
            self._legend_label_overrides.get(k[1], k[1])
            for k in self.lines.keys()
        ]
        if self.plot_type == 'ps':
            if self._overlay_line_v is not None:
                handles.append(self._overlay_line_v)
                labels.append('Voltage Setpoint')
        if handles:
            self.ax.legend(handles, labels, loc='upper left', fontsize=7)

        self.canvas.draw_idle()

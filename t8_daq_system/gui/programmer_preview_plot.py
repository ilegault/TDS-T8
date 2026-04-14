"""
programmer_preview_plot.py
PURPOSE: Full-screen preview plot shown when Power Programmer mode is active.

Shows the computed temperature profile over time.
If voltage ramp blocks are present a second (right) y-axis shows the voltage
scale and the voltage segments are drawn there.
A small animated dot tracks the programme's current position while it runs.
"""

import tkinter as tk
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class ProgrammerPreviewPlot:
    """
    Embedded matplotlib preview plot for the Power Programmer panel.

    • Left y-axis  : Temperature (°C or K)
    • Right y-axis : Voltage (V) — only shown when voltage ramp blocks exist
    • Animated dot : moves along the curve to show current programme progress
    """

    def __init__(self, parent_frame):
        self._parent = parent_frame

        self.fig = Figure(figsize=(8, 4), dpi=100)
        self.fig.patch.set_facecolor('#d9d9d9')

        self._ax_v = self.fig.add_subplot(111)
        # Right axis created once; shown/hidden per render
        self._ax_a = self._ax_v.twinx()
        self._ax_a.set_visible(False)

        self._v_color  = '#e84118'
        self._a_color  = '#d62728'
        self._v_style  = 'solid'
        self._a_style  = 'dashed'
        self._v_width  = 2
        self._a_width  = 2

        self._ax_v.set_xlabel('Time (min)')
        self._ax_v.set_ylabel('Temperature (°C)', color=self._v_color)
        self._ax_v.tick_params(axis='y', labelcolor=self._v_color)
        self.fig.suptitle('Temperature Preview', fontsize=11, fontweight='bold')
        self._ax_v.grid(True, alpha=0.3)
        self.fig.subplots_adjust(left=0.12, right=0.95, top=0.90, bottom=0.15)

        # Persistent line objects
        self._line_v    = None
        self._line_a    = None
        self._line_temp = None
        self._temp_mode = False

        # Placeholder text
        self._placeholder = self._ax_v.text(
            0.5, 0.5,
            "Add blocks and click Preview to see temperature profile",
            transform=self._ax_v.transAxes,
            ha='center', va='center',
            fontsize=10, color='gray', style='italic'
        )

        # ── Dot-indicator state ────────────────────────────────────────────
        # Stored preview arrays for interpolation (seconds)
        self._dot_times_sec   = None   # np.array of time in seconds
        self._dot_temps_disp  = None   # np.array of display temperature values
        self._dot_volts       = None   # np.array of voltage values (may be None)
        self._dot_has_voltage = False  # True if right-axis voltage line is shown
        self._dot_unit        = 'C'    # display unit used in last render

        # The dot scatter artists (one per axis if dual)
        self._dot_temp  = None   # scatter on left axis
        self._dot_volt  = None   # scatter on right axis (voltage)
        # ──────────────────────────────────────────────────────────────────

        self.canvas = FigureCanvasTkAgg(self.fig, master=parent_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.draw()

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def update_preview(self, times, voltages, currents):
        """Legacy voltage/current preview (kept for API compatibility)."""
        if self._line_v is not None:
            self._line_v.remove()
            self._line_v = None
        if self._line_a is not None:
            self._line_a.remove()
            self._line_a = None

        for line in list(self._ax_v.lines):
            line.remove()
        for line in list(self._ax_a.lines):
            line.remove()

        if not times:
            self._placeholder.set_visible(True)
            self._ax_v.relim()
            self._ax_v.autoscale_view()
            self._ax_a.relim()
            self._ax_a.autoscale_view()
            self.canvas.draw_idle()
            return

        self._placeholder.set_visible(False)
        _style_map = {'solid': '-', 'dashed': '--', 'dotted': ':', 'dashdot': '-.'}
        self._line_v, = self._ax_v.plot(
            times, voltages,
            color=self._v_color, linewidth=self._v_width,
            linestyle=_style_map.get(self._v_style, '-'),
            label='Voltage (V)'
        )
        self._line_a, = self._ax_a.plot(
            times, currents,
            color=self._a_color, linewidth=self._a_width,
            linestyle=_style_map.get(self._a_style, '-'),
            label='Current (A)'
        )

        boundaries = self._find_block_boundaries(times, voltages, currents)
        for bt in boundaries:
            self._ax_v.axvline(bt, color='gray', linestyle=':', linewidth=1.0, alpha=0.7)

        self._ax_v.relim()
        self._ax_v.autoscale_view()
        self._ax_a.relim()
        self._ax_a.autoscale_view()
        self.canvas.draw_idle()

    def update_unified_preview(self, times, voltages, temps_k, blocks, boundaries,
                               display_unit='K'):
        """
        Render the unified temperature-over-time preview.

        If any of the blocks is a voltage_ramp the right y-axis is shown with
        the voltage profile so the user can see both temperature and voltage
        in the same view.
        """
        self._ax_v.cla()
        self._ax_a.cla()
        self._ax_a.set_visible(False)
        self._dot_temp = None
        self._dot_volt = None

        if not times:
            self._placeholder = self._ax_v.text(
                0.5, 0.5,
                "Add blocks and click Preview to see temperature profile",
                transform=self._ax_v.transAxes,
                ha='center', va='center',
                fontsize=10, color='gray', style='italic'
            )
            self.canvas.draw()
            return

        t_sec = np.array(times)
        t_min = t_sec / 60.0
        t_arr = np.array(temps_k)
        v_arr = np.array(voltages)

        if display_unit == 'C':
            disp_arr  = t_arr - 273.15
            unit_label = '\u00b0C'
        else:
            disp_arr  = t_arr
            unit_label = 'K'

        # Detect whether any voltage ramp blocks are present
        has_voltage_ramp = any(
            getattr(b, 'block_type', None) == 'voltage_ramp'
            for b in blocks
        )

        # ── Left axis: temperature ─────────────────────────────────────────
        self._ax_v.plot(t_min, disp_arr, color='#e84118', linewidth=2.0,
                        label=f'Target Temp ({unit_label})', zorder=3)
        self._ax_v.set_ylabel(f'Temperature ({unit_label})', color='#e84118')
        self._ax_v.tick_params(axis='y', labelcolor='#e84118')
        self._ax_v.set_xlabel('Time (min)')
        self._ax_v.grid(True, alpha=0.3)

        # ── Right axis: voltage (only when voltage ramp blocks exist) ──────
        if has_voltage_ramp:
            self._ax_a.set_visible(True)
            # Mask NaN-safe: only draw where voltage actually changes
            self._ax_a.plot(t_min, v_arr, color='#2980b9', linewidth=1.8,
                            linestyle='--', label='Voltage (V)', zorder=2)
            self._ax_a.set_ylabel('Voltage (V)', color='#2980b9',
                                   rotation=270, labelpad=15)
            self._ax_a.tick_params(axis='y', labelcolor='#2980b9')
            right_margin = 0.88
        else:
            right_margin = 0.95

        # ── Block boundary lines ───────────────────────────────────────────
        for b_time in boundaries[1:]:
            self._ax_v.axvline(b_time / 60.0, color='gray', linewidth=0.8,
                               linestyle='--', alpha=0.6)

        # ── QMS trigger markers (purple dash-dot line + label) ─────────────
        for i, block in enumerate(blocks):
            if (getattr(block, 'qms_trigger', False) and
                    i + 1 < len(blocks) and
                    blocks[i + 1].block_type == 'temp_ramp' and
                    i + 1 < len(boundaries)):
                qms_t_min = boundaries[i + 1] / 60.0
                self._ax_v.axvline(qms_t_min, color='#9b59b6', linewidth=1.5,
                                   linestyle='-.', alpha=0.85, zorder=4)
                self._ax_v.text(
                    qms_t_min, 0.97, ' QMS',
                    transform=self._ax_v.get_xaxis_transform(),
                    color='#9b59b6', fontsize=8, va='top', zorder=4
                )

        total_min = t_min[-1] if len(t_min) > 0 else 0
        self.fig.suptitle(f'Temperature Preview  —  {total_min:.0f} min total',
                          fontsize=10, fontweight='bold')
        self.fig.subplots_adjust(left=0.12, right=right_margin, top=0.90, bottom=0.15)

        # ── Dot indicators (start at t=0, hidden until programme runs) ────
        dot_t0 = t_min[0]
        dot_temp0 = disp_arr[0]
        self._dot_temp = self._ax_v.scatter(
            [dot_t0], [dot_temp0],
            s=70, color='white', edgecolors='#e84118', linewidths=2.0,
            zorder=5
        )
        self._dot_temp.set_visible(False)

        if has_voltage_ramp:
            dot_v0 = v_arr[0]
            self._dot_volt = self._ax_a.scatter(
                [dot_t0], [dot_v0],
                s=70, color='white', edgecolors='#2980b9', linewidths=2.0,
                zorder=5
            )
            self._dot_volt.set_visible(False)

        # ── Store arrays for dot interpolation ────────────────────────────
        self._dot_times_sec   = t_sec
        self._dot_temps_disp  = disp_arr
        self._dot_volts       = v_arr if has_voltage_ramp else None
        self._dot_has_voltage = has_voltage_ramp
        self._dot_unit        = display_unit

        self.canvas.draw()

    def set_progress_time(self, elapsed_sec):
        """
        Move the animated dot to the position corresponding to *elapsed_sec*
        of programme execution.  Safe to call from any thread via root.after().
        """
        if self._dot_times_sec is None or len(self._dot_times_sec) == 0:
            return
        if self._dot_temp is None:
            return

        t_sec = self._dot_times_sec
        t_min_elapsed = elapsed_sec / 60.0

        # Clamp to the range of the preview
        t_min_arr = t_sec / 60.0
        t_min_elapsed = max(t_min_arr[0], min(t_min_arr[-1], t_min_elapsed))

        temp_disp = float(np.interp(t_min_elapsed, t_min_arr, self._dot_temps_disp))

        self._dot_temp.set_offsets([[t_min_elapsed, temp_disp]])
        self._dot_temp.set_visible(True)

        if self._dot_has_voltage and self._dot_volt is not None and self._dot_volts is not None:
            volt_val = float(np.interp(t_min_elapsed, t_min_arr, self._dot_volts))
            self._dot_volt.set_offsets([[t_min_elapsed, volt_val]])
            self._dot_volt.set_visible(True)

        self.canvas.draw_idle()

    def clear_progress_dot(self):
        """Hide the dot (call after programme finishes or is stopped)."""
        if self._dot_temp is not None:
            self._dot_temp.set_visible(False)
        if self._dot_volt is not None:
            self._dot_volt.set_visible(False)
        self.canvas.draw_idle()

    def update_temp_preview(self, times, temps_k, blocks=None):
        """
        Render TempRamp preview with full phase annotations.
        (Used by the legacy PowerProgrammerPanel — kept for compatibility.)
        """
        self._ax_v.cla()
        self._ax_a.cla()
        self._ax_a.set_visible(False)
        self._temp_mode = True
        self._line_v    = None
        self._line_a    = None
        self._line_temp = None
        self._dot_temp  = None
        self._dot_volt  = None

        if not times or not temps_k:
            self._placeholder = self._ax_v.text(
                0.5, 0.5, "No program loaded — add blocks above",
                transform=self._ax_v.transAxes,
                ha='center', va='center', fontsize=10,
                color='gray', style='italic'
            )
            self.canvas.draw()
            return

        t_arr  = np.array(times)
        c_arr  = np.array(temps_k) - 273.15
        t_min  = t_arr / 60.0

        PREHEAT_TARGET_C = 150.0
        preheat_end_idx = next(
            (i for i, c in enumerate(c_arr) if c >= PREHEAT_TARGET_C), len(c_arr) - 1
        )
        preheat_end_min = t_min[preheat_end_idx]

        self._ax_v.axvspan(0, preheat_end_min, alpha=0.12, color='gray',
                           label='Soft-start preheat')
        self._ax_v.text(preheat_end_min / 2, max(c_arr) * 0.05,
                        'Soft-start\n(auto)', ha='center', va='bottom',
                        fontsize=7, color='gray', style='italic')

        BLOCK_COLORS = {'Hold': '#ffe066', 'Ramp': '#a8e6a3'}
        BLOCK_ALPHA  = 0.25

        if blocks:
            block_start_time_s = times[preheat_end_idx] if preheat_end_idx < len(times) else 0
            for i, block in enumerate(blocks):
                dur_s  = float(block.get('duration_sec', 0))
                btype  = block.get('type', 'Hold')
                rate   = block.get('rate_k_per_min', 0.0)
                block_end_time_s = block_start_time_s + dur_s
                bs_min = block_start_time_s / 60.0
                be_min = block_end_time_s   / 60.0
                color  = BLOCK_COLORS.get(btype, '#cccccc')
                self._ax_v.axvspan(bs_min, be_min, alpha=BLOCK_ALPHA, color=color)
                mid_min = (bs_min + be_min) / 2.0
                if btype == 'Hold':
                    label_text = f"Block {i+1}\nHold\n~150\u00b0C"
                else:
                    label_text = f"Block {i+1}\nRamp\n{rate:.1f} K/min"
                self._ax_v.text(mid_min, max(c_arr) * 0.85,
                                label_text, ha='center', va='top',
                                fontsize=7, color='#333333',
                                bbox=dict(boxstyle='round,pad=0.2', fc='white', alpha=0.6))
                self._ax_v.axvline(x=bs_min, color='#888888', linewidth=0.8,
                                   linestyle='--', alpha=0.6)
                block_start_time_s = block_end_time_s
            self._ax_v.axvline(x=block_start_time_s / 60.0, color='#888888',
                               linewidth=0.8, linestyle='--', alpha=0.6)

        self._ax_v.plot(t_min, c_arr, color='#e84118', linewidth=2.0,
                        label='Filament temp (\u00b0C)')
        self._ax_v.axhline(y=PREHEAT_TARGET_C, color='gray', linewidth=1.0,
                           linestyle=':', alpha=0.8, label='150\u00b0C preheat target')

        ax2 = self._ax_v.twinx()
        c_min_plot, c_max_plot = self._ax_v.get_ylim()
        ax2.set_ylim(c_min_plot + 273.15, c_max_plot + 273.15)
        ax2.set_ylabel('Temperature (K)', color='#888888', rotation=270, labelpad=15)
        ax2.tick_params(axis='y', labelcolor='#888888')

        # Dot for this mode
        self._dot_times_sec   = t_arr
        self._dot_temps_disp  = c_arr
        self._dot_volts       = None
        self._dot_has_voltage = False
        self._dot_unit        = 'C'
        self._dot_temp = self._ax_v.scatter(
            [t_min[0]], [c_arr[0]],
            s=70, color='white', edgecolors='#e84118', linewidths=2.0, zorder=5
        )
        self._dot_temp.set_visible(False)

        self._ax_v.set_xlabel('Time (min)')
        self._ax_v.set_ylabel('Temperature (\u00b0C)', color='#e84118')
        self._ax_v.tick_params(axis='y', labelcolor='#e84118')
        self._ax_v.grid(True, alpha=0.25)

        handles, labels = self._ax_v.get_legend_handles_labels()
        if handles:
            self._ax_v.legend(handles, labels, loc='upper left', fontsize=7)

        total_min = t_min[-1] if len(t_min) > 0 else 0
        self.fig.suptitle(f'TDS Temperature Preview  —  {total_min:.0f} min total',
                          fontsize=10, fontweight='bold')
        self.fig.subplots_adjust(left=0.1, right=0.88, top=0.90, bottom=0.15)
        self.canvas.draw()

    def reset_to_vi_mode(self):
        """Restore the dual-axis Voltage/Current layout after leaving TempRamp mode."""
        self._temp_mode = False
        self._ax_a.set_visible(True)
        self._ax_v.set_ylabel('Voltage (V)', color=self._v_color)
        self._ax_v.tick_params(axis='y', labelcolor=self._v_color)
        self._ax_a.set_ylabel('Current (A)', color=self._a_color, rotation=270, labelpad=15)
        self._ax_a.tick_params(axis='y', labelcolor=self._a_color)
        self.fig.suptitle('Power Program Preview', fontsize=11, fontweight='bold')
        if self._line_temp is not None:
            self._line_temp.remove()
            self._line_temp = None
        self._placeholder.set_visible(True)
        self._ax_v.relim()
        self._ax_v.autoscale_view()
        self._ax_a.relim()
        self._ax_a.autoscale_view()
        self.canvas.draw_idle()

    def apply_appearance(self, voltage_color=None, current_color=None,
                         voltage_style=None, current_style=None,
                         voltage_width=None, current_width=None):
        """Apply color/style settings from the Settings dialog."""
        _style_map = {'solid': '-', 'dashed': '--', 'dotted': ':', 'dashdot': '-.'}
        if voltage_color:
            self._v_color = voltage_color
        if current_color:
            self._a_color = current_color
        if voltage_style:
            self._v_style = voltage_style
        if current_style:
            self._a_style = current_style
        if voltage_width:
            try:
                self._v_width = int(voltage_width)
            except (ValueError, TypeError):
                pass
        if current_width:
            try:
                self._a_width = int(current_width)
            except (ValueError, TypeError):
                pass
        self._ax_v.set_ylabel('Voltage (V)', color=self._v_color)
        self._ax_v.tick_params(axis='y', labelcolor=self._v_color)
        self._ax_a.set_ylabel('Current (A)', color=self._a_color, rotation=270, labelpad=15)
        self._ax_a.tick_params(axis='y', labelcolor=self._a_color)
        if self._line_v is not None:
            self._line_v.set_color(self._v_color)
            self._line_v.set_linestyle(_style_map.get(self._v_style, '-'))
            self._line_v.set_linewidth(self._v_width)
        if self._line_a is not None:
            self._line_a.set_color(self._a_color)
            self._line_a.set_linestyle(_style_map.get(self._a_style, '-'))
            self._line_a.set_linewidth(self._a_width)
        self.canvas.draw_idle()

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _find_block_boundaries(times, voltages, currents):
        """Return time values where voltage or current slope changes."""
        if len(times) < 3:
            return []
        boundaries = []
        prev_dv = None
        prev_di = None
        for i in range(1, len(times) - 1):
            dt = times[i] - times[i - 1]
            if dt == 0:
                continue
            dv = (voltages[i] - voltages[i - 1]) / dt
            di = (currents[i] - currents[i - 1]) / dt
            if prev_dv is not None:
                if abs(dv - prev_dv) > 1e-9 or abs(di - prev_di) > 1e-9:
                    boundaries.append(times[i])
            prev_dv = dv
            prev_di = di
        return boundaries

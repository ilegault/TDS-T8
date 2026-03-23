"""
programmer_preview_plot.py
PURPOSE: Full-screen preview plot shown when Power Programmer mode is active.

Shows the computed voltage and current waveform on a single matplotlib figure
with two y-axes (voltage left, current right) shared on the time x-axis.
"""

import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class ProgrammerPreviewPlot:
    """
    Embedded matplotlib preview plot for the Power Programmer panel.

    Displays the voltage (blue, left y-axis) and current (red, right y-axis)
    waveforms computed from the block editor.
    """

    def __init__(self, parent_frame):
        """
        Args:
            parent_frame: tkinter frame to embed the plot in.
        """
        self._parent = parent_frame

        # Build figure with two y-axes
        self.fig = Figure(figsize=(8, 4), dpi=100)
        self.fig.patch.set_facecolor('#f0f0f0')

        self._ax_v = self.fig.add_subplot(111)
        self._ax_a = self._ax_v.twinx()

        self._v_color = '#1f77b4'
        self._a_color = '#d62728'
        self._v_style = 'solid'
        self._a_style = 'dashed'
        self._v_width = 2
        self._a_width = 2

        self._ax_v.set_xlabel('Time (s)')
        self._ax_v.set_ylabel('Voltage (V)', color=self._v_color)
        self._ax_v.tick_params(axis='y', labelcolor=self._v_color)

        self._ax_a.set_ylabel('Current (A)', color=self._a_color, rotation=270, labelpad=15)
        self._ax_a.yaxis.set_label_position('right')
        self._ax_a.tick_params(axis='y', labelcolor=self._a_color)

        self.fig.suptitle('Power Program Preview', fontsize=11, fontweight='bold')
        self._ax_v.grid(True, alpha=0.3)
        self.fig.subplots_adjust(left=0.1, right=0.88, top=0.90, bottom=0.15)

        # Persistent line objects
        self._line_v = None
        self._line_a = None
        self._line_temp = None  # green temperature line for TempRamp mode
        self._temp_mode = False  # True when displaying TempRamp preview

        # "No program" placeholder text
        self._placeholder = self._ax_v.text(
            0.5, 0.5,
            "No program loaded — add blocks in the editor above",
            transform=self._ax_v.transAxes,
            ha='center', va='center',
            fontsize=10, color='gray', style='italic'
        )

        # Embed canvas
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.draw()

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def update_preview(self, times, voltages, currents):
        """
        Refresh the preview plot with new waveform data.

        Args:
            times:    list of float (seconds)
            voltages: list of float (volts)
            currents: list of float (amps)
        """
        # Clear old lines
        if self._line_v is not None:
            self._line_v.remove()
            self._line_v = None
        if self._line_a is not None:
            self._line_a.remove()
            self._line_a = None

        # Remove existing block-boundary lines
        for line in list(self._ax_v.lines):
            line.remove()
        for line in list(self._ax_a.lines):
            line.remove()

        if not times:
            # Show placeholder
            self._placeholder.set_visible(True)
            self._ax_v.relim()
            self._ax_v.autoscale_view()
            self._ax_a.relim()
            self._ax_a.autoscale_view()
            self.canvas.draw_idle()
            return

        # Hide placeholder
        self._placeholder.set_visible(False)

        _style_map = {'solid': '-', 'dashed': '--', 'dotted': ':', 'dashdot': '-.'}
        # Draw voltage and current lines
        self._line_v, = self._ax_v.plot(
            times, voltages,
            color=self._v_color,
            linewidth=self._v_width,
            linestyle=_style_map.get(self._v_style, '-'),
            label='Voltage (V)'
        )
        self._line_a, = self._ax_a.plot(
            times, currents,
            color=self._a_color,
            linewidth=self._a_width,
            linestyle=_style_map.get(self._a_style, '-'),
            label='Current (A)'
        )

        # Draw vertical dotted gray lines at block boundaries
        # A boundary occurs where the slope changes (consecutive differences differ)
        boundaries = self._find_block_boundaries(times, voltages, currents)
        for bt in boundaries:
            self._ax_v.axvline(bt, color='gray', linestyle=':', linewidth=1.0, alpha=0.7)

        # Autoscale
        self._ax_v.relim()
        self._ax_v.autoscale_view()
        self._ax_a.relim()
        self._ax_a.autoscale_view()

        self.canvas.draw_idle()

    def update_temp_preview(self, times, temps_k, blocks=None):
        """
        Render TempRamp preview with full phase annotations:
          - Phase 1 (Soft-Start preheat): grey shaded region, 0 → ~150°C
          - Hold blocks: yellow shaded regions, labelled with setpoint
          - Ramp blocks: green shaded regions, labelled with rate
          - Block boundary vertical lines with block numbers
          - Temperature axis in °C (left) and K (right)
          - Estimated time labels on x-axis in minutes

        Args:
            times:   list of floats (seconds)
            temps_k: list of floats (Kelvin)
            blocks:  list of block dicts from PowerProgrammerPanel (TempRamp format).
                     If None, only the raw curve is drawn without annotations.
        """
        import numpy as np

        # Clear everything
        self._ax_v.cla()
        if self._ax_a:
            self._ax_a.cla()
            self._ax_a.set_visible(False)

        self._temp_mode = True
        self._line_v = None
        self._line_a = None
        self._line_temp = None

        if not times or not temps_k:
            self._placeholder = self._ax_v.text(
                0.5, 0.5, "No program loaded — add blocks above",
                transform=self._ax_v.transAxes,
                ha='center', va='center', fontsize=10,
                color='gray', style='italic'
            )
            self.canvas.draw()
            return

        # Convert to numpy; temperature axis in °C
        t_arr = np.array(times)
        c_arr = np.array(temps_k) - 273.15
        t_min = t_arr / 60.0   # x-axis in minutes

        # ── Soft-start preheat region (always present: t=0 to first block boundary)
        PREHEAT_TARGET_C = 150.0
        # Find the time index where temp first crosses 150°C
        preheat_end_idx = next((i for i, c in enumerate(c_arr) if c >= PREHEAT_TARGET_C), len(c_arr) - 1)
        preheat_end_min = t_min[preheat_end_idx]

        self._ax_v.axvspan(0, preheat_end_min, alpha=0.12, color='gray',
                           label='Soft-start preheat')
        self._ax_v.text(preheat_end_min / 2, max(c_arr) * 0.05,
                        'Soft-start\n(auto)', ha='center', va='bottom',
                        fontsize=7, color='gray', style='italic')

        # ── Block regions (user-defined Hold and Ramp blocks)
        BLOCK_COLORS = {'Hold': '#ffe066', 'Ramp': '#a8e6a3'}
        BLOCK_ALPHA   = 0.25

        if blocks:
            block_start_time_s = times[preheat_end_idx] if preheat_end_idx < len(times) else 0

            for i, block in enumerate(blocks):
                dur_s = float(block.get('duration_sec', 0))
                btype = block.get('type', 'Hold')
                rate  = block.get('rate_k_per_min', 0.0)

                block_end_time_s = block_start_time_s + dur_s
                bs_min = block_start_time_s / 60.0
                be_min = block_end_time_s   / 60.0

                color = BLOCK_COLORS.get(btype, '#cccccc')
                self._ax_v.axvspan(bs_min, be_min, alpha=BLOCK_ALPHA, color=color)

                # Block label
                mid_min = (bs_min + be_min) / 2.0
                if btype == 'Hold':
                    label_text = f"Block {i+1}\nHold\n~150°C"
                else:
                    label_text = f"Block {i+1}\nRamp\n{rate:.1f} K/min"

                self._ax_v.text(mid_min, max(c_arr) * 0.85,
                                label_text, ha='center', va='top',
                                fontsize=7, color='#333333',
                                bbox=dict(boxstyle='round,pad=0.2', fc='white', alpha=0.6))

                # Block boundary line
                self._ax_v.axvline(x=bs_min, color='#888888', linewidth=0.8,
                                   linestyle='--', alpha=0.6)

                block_start_time_s = block_end_time_s

            # Final boundary
            self._ax_v.axvline(x=block_start_time_s / 60.0, color='#888888',
                               linewidth=0.8, linestyle='--', alpha=0.6)

        # ── Main temperature curve
        self._ax_v.plot(t_min, c_arr, color='#e84118', linewidth=2.0,
                        label='Filament temp (°C)')

        # ── 150°C preheat target line
        self._ax_v.axhline(y=PREHEAT_TARGET_C, color='gray', linewidth=1.0,
                           linestyle=':', alpha=0.8, label='150°C preheat target')

        # ── Right y-axis: Kelvin scale
        ax2 = self._ax_v.twinx()
        c_min_plot, c_max_plot = self._ax_v.get_ylim()
        ax2.set_ylim(c_min_plot + 273.15, c_max_plot + 273.15)
        ax2.set_ylabel('Temperature (K)', color='#888888', rotation=270, labelpad=15)
        ax2.tick_params(axis='y', labelcolor='#888888')

        # ── Axis labels and formatting
        self._ax_v.set_xlabel('Time (min)')
        self._ax_v.set_ylabel('Temperature (°C)', color='#e84118')
        self._ax_v.tick_params(axis='y', labelcolor='#e84118')
        self._ax_v.grid(True, alpha=0.25)

        # ── Legend
        handles, labels = self._ax_v.get_legend_handles_labels()
        if handles:
            self._ax_v.legend(handles, labels, loc='upper left', fontsize=7)

        # ── Title
        total_min = t_min[-1] if len(t_min) > 0 else 0
        self.fig.suptitle(f'TDS Temperature Preview  —  {total_min:.0f} min total',
                          fontsize=10, fontweight='bold')

        self.fig.subplots_adjust(left=0.1, right=0.88, top=0.90, bottom=0.15)
        self.canvas.draw()

    def reset_to_vi_mode(self):
        """
        Restore the dual-axis Voltage/Current layout after leaving TempRamp mode.
        """
        self._temp_mode = False
        self._ax_a.set_visible(True)

        # Restore axis labels
        self._ax_v.set_ylabel('Voltage (V)', color=self._v_color)
        self._ax_v.tick_params(axis='y', labelcolor=self._v_color)
        self._ax_a.set_ylabel('Current (A)', color=self._a_color,
                               rotation=270, labelpad=15)
        self._ax_a.tick_params(axis='y', labelcolor=self._a_color)
        self.fig.suptitle('Power Program Preview', fontsize=11, fontweight='bold')

        # Remove temperature line
        if self._line_temp is not None:
            self._line_temp.remove()
            self._line_temp = None

        # Show placeholder and reset view
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

        # Re-apply to axis labels and ticks
        self._ax_v.set_ylabel('Voltage (V)', color=self._v_color)
        self._ax_v.tick_params(axis='y', labelcolor=self._v_color)
        self._ax_a.set_ylabel('Current (A)', color=self._a_color, rotation=270, labelpad=15)
        self._ax_a.tick_params(axis='y', labelcolor=self._a_color)

        # Re-apply to existing lines
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
        """
        Return a list of time values where voltage slope or current changes,
        indicating block boundaries.
        """
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
                # Detect slope change (block boundary)
                if abs(dv - prev_dv) > 1e-9 or abs(di - prev_di) > 1e-9:
                    boundaries.append(times[i])

            prev_dv = dv
            prev_di = di

        return boundaries

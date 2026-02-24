"""
pinout_display.py
PURPOSE: Live pinout display showing current hardware configuration and pin
         assignments, updated in real-time with live sensor readings.

Allows users to verify that the physical wiring matches what the software
expects, and to confirm that unit conversions are working correctly by showing
both the raw thermocouple voltage and the resulting temperature side-by-side.
"""

import tkinter as tk
from tkinter import ttk


# Human-readable thermocouple type descriptions
_TC_TYPE_DESC = {
    'B': 'Type B  Pt-Rh  (0 – 1820 °C)',
    'C': 'Type C  W-Re   (0 – 2315 °C)',
    'E': 'Type E  Chr-Con (-270 – 1000 °C)',
    'J': 'Type J  Fe-Con  (-210 – 1200 °C)',
    'K': 'Type K  Chr-Alu (-270 – 1372 °C)',
    'N': 'Type N  Nic-Nis (-270 – 1300 °C)',
    'R': 'Type R  Pt-Rh   (-50 – 1768 °C)',
    'S': 'Type S  Pt-Rh   (-50 – 1768 °C)',
    'T': 'Type T  Cu-Con  (-270 – 400 °C)',
}

_MONO = ('Courier', 9)
_BOLD = ('Arial', 9, 'bold')
_HDR  = ('Arial', 10, 'bold')


def _dot(parent, color='#333333'):
    """Return a small square Canvas widget used as a status indicator."""
    c = tk.Canvas(parent, width=14, height=14, bg=color,
                  highlightthickness=1, highlightbackground='black')
    return c


class PinoutDisplay(tk.Toplevel):
    """
    Live pinout display Toplevel window.

    Shows the current hardware assignment for every LabJack T8 analog input,
    every digital I/O line, the XGS-600 serial connection, and the Keysight
    power-supply analog connections.

    Tab 1 "Pin Table": text-based table of all pin assignments with live readings.
    Tab 2 "Wiring Diagram": visual canvas showing device boxes and wiring.

    Call ``update_readings(all_readings, raw_voltages)`` whenever new data
    arrives from the acquisition thread to refresh the live values.
    Call ``refresh_config(config, app_settings)`` after a settings change to
    rebuild the display.

    Parameters
    ----------
    parent : tk.Widget
    config : dict          current internal config dict
    app_settings : AppSettings
    """

    REFRESH_MS = 200  # How often to redraw live value cells (ms)

    def __init__(self, parent, config, app_settings):
        super().__init__(parent)
        self.title("Live Pinout Display")
        self.geometry("900x700")
        self.minsize(700, 550)
        self.resizable(True, True)
        self.transient(parent)

        self._config   = config
        self._settings = app_settings

        # Latest readings supplied by main_window
        self._all_readings   = {}   # {sensor_name: value}
        self._raw_voltages   = {}   # {tc_name + '_rawV': volts}
        self._latest_frg702_details = {} # {frg_name: detail_dict}

        # Widget references updated per rebuild (name -> dict of labels/dots)
        self._tc_rows   = {}   # tc_name -> {'dot': Canvas, 'temp': Label, 'raw': Label}
        self._frg_rows  = {}   # frg_name -> {'dot': Canvas, 'val': Label}

        # Canvas reference for wiring diagram (rebuilt on config change)
        self._wiring_canvas = None

        self._build_chrome()
        self._schedule_refresh()

        # Centre over parent
        self.update_idletasks()
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h   = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def update_readings(self, all_readings: dict, raw_voltages: dict | None = None,
                        frg702_details: dict | None = None):
        """
        Store the latest sensor readings so the periodic refresh can display them.
        """
        self._all_readings = all_readings or {}
        if raw_voltages is not None:
            self._raw_voltages = raw_voltages
        if frg702_details is not None:
            self._latest_frg702_details = frg702_details

    def refresh_config(self, config: dict, app_settings):
        """Rebuild the display after a config/settings change."""
        self._config   = config
        self._settings = app_settings
        # Rebuild pin-table tab content
        for widget in self._content_frame.winfo_children():
            widget.destroy()
        self._tc_rows  = {}
        self._frg_rows = {}
        self._build_content()
        # Rebuild wiring diagram
        self._build_wiring_diagram()

    # ──────────────────────────────────────────────────────────────────────────
    # Build helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_chrome(self):
        """Build the outer frame: header, notebook (2 tabs), close button."""
        hdr = ttk.Frame(self)
        hdr.pack(fill=tk.X, padx=10, pady=(8, 4))

        ttk.Label(hdr, text="LabJack T8  —  Live Pinout & Signal Verification",
                  font=('Arial', 12, 'bold')).pack(side=tk.LEFT)
        ttk.Label(hdr,
                  text="● = live data   ○ = no / stale data",
                  font=('Arial', 8), foreground='#555555').pack(side=tk.RIGHT)

        ttk.Separator(self, orient='horizontal').pack(fill=tk.X, padx=8, pady=2)

        # Notebook with two tabs
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # ── Tab 1: Pin Table ───────────────────────────────────────────────
        tab1 = ttk.Frame(self._notebook)
        self._notebook.add(tab1, text="Pin Table")

        outer = ttk.Frame(tab1)
        outer.pack(fill=tk.BOTH, expand=True)

        canvas    = tk.Canvas(outer, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._content_frame = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=self._content_frame, anchor='nw')

        def _on_content_resize(event):
            canvas.configure(scrollregion=canvas.bbox('all'))

        def _on_canvas_resize(event):
            canvas.itemconfig(win_id, width=event.width)

        self._content_frame.bind('<Configure>', _on_content_resize)
        canvas.bind('<Configure>', _on_canvas_resize)

        def _scroll(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', _scroll)

        self._build_content()

        # ── Tab 2: Wiring Diagram ──────────────────────────────────────────
        tab2 = ttk.Frame(self._notebook)
        self._notebook.add(tab2, text="Wiring Diagram")

        wd_outer = ttk.Frame(tab2)
        wd_outer.pack(fill=tk.BOTH, expand=True)

        wd_scroll_y = ttk.Scrollbar(wd_outer, orient='vertical')
        wd_scroll_x = ttk.Scrollbar(wd_outer, orient='horizontal')
        self._wiring_canvas = tk.Canvas(
            wd_outer, bg='#fafafa', highlightthickness=0,
            yscrollcommand=wd_scroll_y.set,
            xscrollcommand=wd_scroll_x.set
        )
        wd_scroll_y.config(command=self._wiring_canvas.yview)
        wd_scroll_x.config(command=self._wiring_canvas.xview)
        wd_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        wd_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self._wiring_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _scroll_wd(event):
            self._wiring_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        self._wiring_canvas.bind('<MouseWheel>', _scroll_wd)

        self._build_wiring_diagram()

        # Close button
        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, padx=8, pady=(2, 8))
        ttk.Button(btn_row, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _section(self, text):
        """Add a bold section header to the content frame."""
        ttk.Label(self._content_frame, text=text, font=_HDR).pack(
            anchor='w', padx=6, pady=(10, 2))

    def _separator(self):
        ttk.Separator(self._content_frame, orient='horizontal').pack(
            fill=tk.X, padx=6, pady=4)

    # ──────────────────────────────────────────────────────────────────────────
    # Content sections (Pin Table tab)
    # ──────────────────────────────────────────────────────────────────────────

    def _build_content(self):
        self._build_tc_section()
        self._separator()
        self._build_dio_section()
        self._separator()
        self._build_xgs_section()
        self._separator()
        self._build_ps_section()

    # ── Thermocouples ─────────────────────────────────────────────────────────

    def _build_tc_section(self):
        self._section("LabJack T8  —  Analog Inputs (Thermocouples)")

        f = ttk.Frame(self._content_frame)
        f.pack(fill=tk.X, padx=12, pady=2)

        # Column header row
        col_defs = [
            # (header_text, width_chars, anchor)
            ('',         2,  'w'),   # dot placeholder
            ('T8 Pin',   9,  'w'),
            ('Pair',     5,  'w'),
            ('Sensor',   12, 'w'),
            ('Type',     30, 'w'),
            ('Unit',     6,  'w'),
            ('Live Temp',     11, 'e'),
            ('Raw Voltage (V)', 17, 'e'),
            ('Diff Voltage (V)', 17, 'e'),
        ]
        hdr_row = ttk.Frame(f)
        hdr_row.pack(fill=tk.X)
        for txt, w, anchor in col_defs:
            ttk.Label(hdr_row, text=txt, font=_BOLD,
                      width=w, anchor=anchor).pack(side=tk.LEFT, padx=2)

        ttk.Separator(f, orient='horizontal').pack(fill=tk.X, pady=2)

        # Assigned channels
        thermocouples = self._config.get('thermocouples', [])
        assigned = set()

        for tc in thermocouples:
            if not tc.get('enabled', True):
                continue
            ch   = tc['channel']
            name = tc['name']
            assigned.add(ch)
            tc_type = tc.get('type', 'K')
            units   = tc.get('units', 'C')
            type_desc = _TC_TYPE_DESC.get(tc_type, f'Type {tc_type}')

            row = ttk.Frame(f)
            row.pack(fill=tk.X, pady=1)

            dot = _dot(row)
            dot.pack(side=tk.LEFT, padx=(2, 4))

            pin_str  = f"AIN{ch}"
            pair_str = f"+/GND"

            for val, w, anchor in [
                (pin_str,    9,  'w'),
                (pair_str,   5,  'w'),
                (name,       12, 'w'),
                (type_desc,  30, 'w'),
                (units,      6,  'w'),
            ]:
                ttk.Label(row, text=val, width=w, anchor=anchor,
                          font=_MONO).pack(side=tk.LEFT, padx=2)

            temp_lbl = ttk.Label(row, text="—", width=11, anchor='e',
                                 font=_MONO, foreground='#1a5f7a')
            temp_lbl.pack(side=tk.LEFT, padx=2)

            raw_lbl  = ttk.Label(row, text="—", width=17, anchor='e',
                                 font=_MONO, foreground='#5a3e7a')
            raw_lbl.pack(side=tk.LEFT, padx=2)

            diff_lbl = ttk.Label(row, text="—", width=17, anchor='e',
                                 font=_MONO, foreground='#5a3e7a')
            diff_lbl.pack(side=tk.LEFT, padx=2)

            self._tc_rows[name] = {
                'dot':  dot,
                'temp': temp_lbl,
                'raw':  raw_lbl,
                'diff': diff_lbl,
            }

        # Unassigned AIN channels
        unassigned = [i for i in range(8) if i not in assigned]
        if unassigned:
            ttk.Separator(f, orient='horizontal').pack(fill=tk.X, pady=3)
            for ch in unassigned:
                row = ttk.Frame(f)
                row.pack(fill=tk.X, pady=1)
                _dot(row).pack(side=tk.LEFT, padx=(2, 4))
                for val, w, anchor in [
                    (f"AIN{ch}",       9,  'w'),
                    ("",               5,  'w'),
                    ("(unassigned)",   12, 'w'),
                    ("",               30, 'w'),
                    ("",               6,  'w'),
                    ("",               11, 'e'),
                    ("",               17, 'e'),
                    ("",               17, 'e'),
                ]:
                    ttk.Label(row, text=val, width=w, anchor=anchor,
                              font=_MONO, foreground='#999999').pack(
                        side=tk.LEFT, padx=2)

        if not thermocouples:
            ttk.Label(f, text="  No thermocouples configured.",
                      foreground='gray').pack(anchor='w', pady=4)

    # ── Digital I/O ───────────────────────────────────────────────────────────

    def _build_dio_section(self):
        self._section("LabJack T8  —  Digital I/O (Turbo Pump)")

        s      = self._settings
        turbo  = self._config.get('turbo_pump', {})
        start_ch  = turbo.get('start_stop_channel', 'DIO0')
        status_ch = turbo.get('status_channel',     'DIO1')
        enabled   = getattr(s, 'turbo_pump_enabled', True)

        f = ttk.Frame(self._content_frame)
        f.pack(fill=tk.X, padx=12, pady=2)

        hdr_row = ttk.Frame(f)
        hdr_row.pack(fill=tk.X)
        for txt, w in [('T8 Pin', 10), ('Direction', 12), ('Function', 38), ('Enabled', 8)]:
            ttk.Label(hdr_row, text=txt, font=_BOLD,
                      width=w, anchor='w').pack(side=tk.LEFT, padx=2)
        ttk.Separator(f, orient='horizontal').pack(fill=tk.X, pady=2)

        fg = 'black' if enabled else '#888888'
        for pin, direction, func in [
            (start_ch,  'Output', 'Turbo Pump Start/Stop  (active HIGH = start)'),
            (status_ch, 'Input',  'Turbo Pump Status  (HIGH = running)'),
        ]:
            row = ttk.Frame(f)
            row.pack(fill=tk.X, pady=1)
            for val, w in [(pin, 10), (direction, 12), (func, 38),
                           ('Yes' if enabled else 'No', 8)]:
                ttk.Label(row, text=val, width=w, anchor='w',
                          font=_MONO, foreground=fg).pack(side=tk.LEFT, padx=2)

        del_row = ttk.Frame(f)
        del_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(del_row,
                  text=f"  Start delay: {getattr(s,'turbo_pump_start_delay_ms',500)} ms   "
                       f"Stop delay: {getattr(s,'turbo_pump_stop_delay_ms',500)} ms   "
                       f"Min restart: {getattr(s,'turbo_pump_min_restart_delay_s',30)} s",
                  font=('Arial', 8), foreground='#555555').pack(anchor='w')

    # ── XGS-600 / FRG-702 ────────────────────────────────────────────────────

    def _build_xgs_section(self):
        interface = self._config.get('frg_interface', 'XGS600')
        if interface == 'Analog':
            self._section("Leybold FRG-702 Gauges  —  Analog Input (LabJack T8)")
        else:
            self._section("XGS-600 Controller  —  RS-232  (FRG-702 Gauges)")

        s = self._settings
        f = ttk.Frame(self._content_frame)
        f.pack(fill=tk.X, padx=12, pady=2)

        if interface != 'Analog':
            # Serial port info box
            info = ttk.LabelFrame(f, text="Serial Port Config", padding=6)
            info.pack(fill=tk.X, pady=(0, 6))
            for label, value in [
                ("COM Port:",  s.xgs600_port),
                ("Baud Rate:", str(s.xgs600_baudrate)),
                ("Timeout:",   f"{s.xgs600_timeout} s"),
                ("Address:",   s.xgs600_address),
                ("Physical:", "SER.COMM DB9 → DB9 gender changer → FTDI USB cable → USB"),
            ]:
                r = ttk.Frame(info)
                r.pack(fill=tk.X, pady=1)
                ttk.Label(r, text=label, width=14, anchor='w',
                          font=_BOLD).pack(side=tk.LEFT, padx=2)
                ttk.Label(r, text=value,  anchor='w',
                          font=_MONO).pack(side=tk.LEFT)
        else:
            # Analog interface info
            info = ttk.LabelFrame(f, text="Analog Interface (AIN)", padding=6)
            info.pack(fill=tk.X, pady=(0, 6))
            ttk.Label(info, text="Gauges are read directly as analog voltages via LabJack T8 pins.",
                      font=('Arial', 8)).pack(anchor='w', padx=5, pady=2)

        gauges = self._config.get('frg702_gauges', [])
        if not gauges:
            ttk.Label(f, text="  No FRG-702 gauges configured.",
                      foreground='gray').pack(anchor='w', pady=4)
            return

        # Gauge assignment table
        hdr_row = ttk.Frame(f)
        hdr_row.pack(fill=tk.X)

        col1_hdr = 'T8 Pin' if interface == 'Analog' else 'XGS-600 Code'

        for txt, w in [('', 2), (col1_hdr, 14), ('Name', 18),
                       ('Units', 8), ('Live Pressure', 18)]:
            ttk.Label(hdr_row, text=txt, font=_BOLD,
                      width=w, anchor='w').pack(side=tk.LEFT, padx=2)
        ttk.Separator(f, orient='horizontal').pack(fill=tk.X, pady=2)

        for gauge in gauges:
            if not gauge.get('enabled', True):
                continue
            name = gauge['name']
            row  = ttk.Frame(f)
            row.pack(fill=tk.X, pady=1)
            dot  = _dot(row)
            dot.pack(side=tk.LEFT, padx=(2, 4))

            col1_val = gauge.get('pin', 'N/A') if interface == 'Analog' else gauge['sensor_code']

            for val, w in [(col1_val, 14), (name, 18),
                           (gauge.get('units', 'mbar'), 8)]:
                ttk.Label(row, text=val, width=w, anchor='w',
                          font=_MONO).pack(side=tk.LEFT, padx=2)
            val_lbl = ttk.Label(row, text="—", width=18, anchor='w',
                                font=_MONO, foreground='#1a5f7a')
            val_lbl.pack(side=tk.LEFT, padx=2)
            self._frg_rows[name] = {'dot': dot, 'val': val_lbl}

    # ── Power Supply ──────────────────────────────────────────────────────────

    def _build_ps_section(self):
        self._section("Keysight N5700 Series  —  Analog Control (LabJack T8)")

        s    = self._settings
        cfg  = self._config.get('power_supply', {})

        f = ttk.Frame(self._content_frame)
        f.pack(fill=tk.X, padx=12, pady=2)

        info = ttk.LabelFrame(f, text="Connection & Safety Limits", padding=6)
        info.pack(fill=tk.X, pady=2)

        status_items = [
            ("Physical:",      "J1 DB25 → Phoenix Contact breakout → T8 screw terminals"),
            ("Voltage Prog:",  s.ps_voltage_pin),
            ("Current Prog:",  s.ps_current_pin),
            ("Voltage Mon:",   s.ps_voltage_monitor_pin),
            ("Current Mon:",   s.ps_current_monitor_pin),
            ("Voltage Limit:", f"{s.ps_voltage_limit} V"),
            ("Current Limit:", f"{s.ps_current_limit} A"),
            ("V Range (plot):", f"{s.ps_v_range_min} – {s.ps_v_range_max} V"),
            ("I Range (plot):", f"{s.ps_i_range_min} – {s.ps_i_range_max} A"),
        ]

        for label, value in status_items:
            r = ttk.Frame(info)
            r.pack(fill=tk.X, pady=1)
            ttk.Label(r, text=label, width=18, anchor='w',
                      font=_BOLD).pack(side=tk.LEFT, padx=2)
            ttk.Label(r, text=str(value), anchor='w',
                      font=_MONO).pack(side=tk.LEFT)

    # ──────────────────────────────────────────────────────────────────────────
    # Wiring Diagram tab
    # ──────────────────────────────────────────────────────────────────────────

    def _build_wiring_diagram(self):
        """Draw the visual wiring diagram on self._wiring_canvas."""
        c = self._wiring_canvas
        if c is None:
            return
        c.delete('all')

        s   = self._config.get('power_supply', {})
        tcs = [tc for tc in self._config.get('thermocouples', []) if tc.get('enabled', True)]

        v_mon_pin = self._settings.ps_voltage_monitor_pin  # e.g. "AIN4"
        i_mon_pin = self._settings.ps_current_monitor_pin  # e.g. "AIN5"
        v_mon_ain = int(v_mon_pin.replace("AIN", "")) if v_mon_pin.startswith("AIN") else 4
        i_mon_ain = int(i_mon_pin.replace("AIN", "")) if i_mon_pin.startswith("AIN") else 5
        v_prog_pin = self._settings.ps_voltage_pin  # e.g. "DAC0"
        i_prog_pin = self._settings.ps_current_pin  # e.g. "DAC1"

        # Detect conflicts
        tc_pin_set = {tc['channel'] for tc in tcs}
        conflicts = set()
        for tc in tcs:
            if tc['channel'] in (v_mon_ain, i_mon_ain):
                conflicts.add(tc['channel'])

        # ── Layout constants ──────────────────────────────────────────────────
        T8_X      = 380   # left edge of T8 rectangle
        T8_Y      = 60    # top edge
        T8_W      = 160   # width
        ROW_H     = 28    # height per terminal row
        PAD       = 10    # inner text padding

        # T8 terminals (left side = AIN + others)
        t8_terminals = (
            ['AIN0', 'AIN1', 'AIN2', 'AIN3', 'AIN4', 'AIN5', 'AIN6', 'AIN7',
             'DAC0', 'DAC1', 'EIO0', 'EIO1', 'GND']
        )
        T8_H = ROW_H * len(t8_terminals) + 20

        # ── Draw T8 box ───────────────────────────────────────────────────────
        c.create_rectangle(T8_X, T8_Y, T8_X + T8_W, T8_Y + T8_H,
                           fill='#e8f0fe', outline='#3a5fd9', width=2)
        c.create_text(T8_X + T8_W // 2, T8_Y + 8,
                      text="LabJack T8", font=('Arial', 10, 'bold'), fill='#1a3399')

        # Draw terminal labels and record their y-centres
        term_y = {}
        for idx, term in enumerate(t8_terminals):
            y = T8_Y + 20 + idx * ROW_H + ROW_H // 2
            term_y[term] = y
            c.create_text(T8_X + PAD, y, text=term, anchor='w',
                          font=('Courier', 9), fill='#222222')
            # tick mark on left edge
            c.create_line(T8_X - 6, y, T8_X, y, fill='#555555', width=1)

        # ── Left side: Thermocouples ──────────────────────────────────────────
        BOX_W  = 120
        BOX_H  = 36
        LEFT_X = T8_X - 200   # right edge of TC boxes
        GAP    = 14

        tc_boxes_y = {}
        total_tc_h = len(tcs) * (BOX_H + GAP) - GAP if tcs else 0
        # Centre TC boxes vertically around AIN0..AIN(n-1) region
        first_ain_y = term_y.get('AIN0', T8_Y + 30)
        last_ain_y  = term_y.get(f'AIN{max(tc["channel"] for tc in tcs)}', first_ain_y) if tcs else first_ain_y
        tc_region_mid = (first_ain_y + last_ain_y) // 2
        tc_start_y = tc_region_mid - total_tc_h // 2

        for idx, tc in enumerate(tcs):
            bx = LEFT_X - BOX_W
            by = tc_start_y + idx * (BOX_H + GAP)
            tc_boxes_y[tc['name']] = (bx, by, BOX_W, BOX_H)
            # Conflict highlight
            fill = '#ffe0e0' if tc['channel'] in conflicts else '#e8f8e8'
            outline = '#cc0000' if tc['channel'] in conflicts else '#2a8a2a'
            c.create_rectangle(bx, by, bx + BOX_W, by + BOX_H,
                               fill=fill, outline=outline, width=2)
            c.create_text(bx + BOX_W // 2, by + BOX_H // 2 - 7,
                          text=tc['name'], font=('Arial', 9, 'bold'), fill='#1a3a1a')
            c.create_text(bx + BOX_W // 2, by + BOX_H // 2 + 7,
                          text=f"Type {tc.get('type','K')} → AIN{tc['channel']}",
                          font=('Courier', 8), fill='#444444')

            # Draw wiring line TC box → T8 AIN pin
            ain_key = f'AIN{tc["channel"]}'
            ty = term_y.get(ain_key, T8_Y + 40)
            bx_right = bx + BOX_W
            by_mid   = by + BOX_H // 2
            line_color = '#cc0000' if tc['channel'] in conflicts else '#1a5fc8'
            c.create_line(bx_right, by_mid, T8_X - 6, ty,
                          fill=line_color, width=2, smooth=True)
            mid_x = (bx_right + T8_X - 6) // 2
            mid_y = (by_mid + ty) // 2
            c.create_text(mid_x, mid_y - 6, text="TC+", font=('Arial', 7),
                          fill=line_color)
            if tc['channel'] in conflicts:
                c.create_text(mid_x, mid_y + 8,
                              text="⚠ CONFLICT", font=('Arial', 7, 'bold'),
                              fill='#cc0000')

        # ── Left side: Keysight box ───────────────────────────────────────────
        KS_BOX_W = 140
        KS_BOX_H = 110
        KS_X = LEFT_X - KS_BOX_W - 20 if tcs else T8_X - 200 - KS_BOX_W - 20
        # Place it below TC boxes
        KS_Y = (tc_start_y + total_tc_h + 30) if tcs else T8_Y + 30

        c.create_rectangle(KS_X, KS_Y, KS_X + KS_BOX_W, KS_Y + KS_BOX_H,
                           fill='#fff3e0', outline='#c77a00', width=2)
        c.create_text(KS_X + KS_BOX_W // 2, KS_Y + 12,
                      text="Keysight N5700", font=('Arial', 9, 'bold'), fill='#7a3d00')
        c.create_text(KS_X + KS_BOX_W // 2, KS_Y + 27,
                      text="J1 DB25 → Phoenix", font=('Arial', 7), fill='#555555')
        c.create_text(KS_X + KS_BOX_W // 2, KS_Y + 40,
                      text="Contact breakout", font=('Arial', 7), fill='#555555')

        ks_lines = [
            (f"V.Mon → {v_mon_pin}", v_mon_pin,  '#e07820', 55),
            (f"I.Mon → {i_mon_pin}", i_mon_pin,  '#e07820', 68),
            (f"V.Prog → {v_prog_pin}", v_prog_pin, '#1a7a1a', 81),
            (f"I.Prog → {i_prog_pin}", i_prog_pin, '#1a7a1a', 94),
        ]
        for label, pin, col, y_off in ks_lines:
            c.create_text(KS_X + 6, KS_Y + y_off, text=label, anchor='w',
                          font=('Courier', 7), fill=col)

        # Draw wiring lines from Keysight to T8
        ks_connections = [
            (v_mon_pin,  '#e07820', 'V_MON'),
            (i_mon_pin,  '#e07820', 'I_MON'),
            (v_prog_pin, '#1a7a1a', 'V_PROG'),
            (i_prog_pin, '#1a7a1a', 'I_PROG'),
        ]
        ks_mid_x = KS_X + KS_BOX_W
        for pin, col, lbl in ks_connections:
            ty = term_y.get(pin)
            if ty is None:
                continue
            ks_wire_y = KS_Y + KS_BOX_H // 2
            c.create_line(ks_mid_x, ks_wire_y, T8_X - 6, ty,
                          fill=col, width=2, smooth=True)
            mid_x = (ks_mid_x + T8_X - 6) // 2
            mid_y = (ks_wire_y + ty) // 2
            c.create_text(mid_x, mid_y - 6, text=lbl, font=('Arial', 7), fill=col)

        # GND line
        gnd_y = term_y.get('GND', T8_Y + T8_H - 10)
        c.create_line(ks_mid_x, KS_Y + KS_BOX_H - 10, T8_X - 6, gnd_y,
                      fill='#222222', width=2, dash=(4, 2))
        mid_x = (ks_mid_x + T8_X - 6) // 2
        c.create_text(mid_x, (KS_Y + KS_BOX_H - 10 + gnd_y) // 2 - 6,
                      text="GND", font=('Arial', 7), fill='#222222')

        # EIO0 line (Local/Analog enable)
        eio0_y = term_y.get('EIO0')
        if eio0_y is not None:
            c.create_line(ks_mid_x, KS_Y + KS_BOX_H - 25, T8_X - 6, eio0_y,
                          fill='#888888', width=2, dash=(3, 3))
            mid_x = (ks_mid_x + T8_X - 6) // 2
            c.create_text(mid_x, (KS_Y + KS_BOX_H - 25 + eio0_y) // 2 - 6,
                          text="LOCAL", font=('Arial', 7), fill='#888888')

        # ── Right side: XGS-600 ───────────────────────────────────────────────
        XGS_X = T8_X + T8_W + 40
        XGS_Y = T8_Y + 20
        XGS_W = 130
        XGS_H = 60
        c.create_rectangle(XGS_X, XGS_Y, XGS_X + XGS_W, XGS_Y + XGS_H,
                           fill='#f0f0ff', outline='#444499', width=2)
        c.create_text(XGS_X + XGS_W // 2, XGS_Y + 14,
                      text="XGS-600", font=('Arial', 9, 'bold'), fill='#1a1a66')
        port = getattr(self._settings, 'xgs600_port', 'COM3')
        c.create_text(XGS_X + XGS_W // 2, XGS_Y + 32,
                      text=f"SER.COMM DB9", font=('Courier', 7), fill='#333333')
        c.create_text(XGS_X + XGS_W // 2, XGS_Y + 46,
                      text=f"→ FTDI USB ({port})", font=('Courier', 7), fill='#333333')

        # Arrow going right off-screen labeled "→ COM3 USB"
        arrow_y = XGS_Y + XGS_H // 2
        c.create_line(XGS_X + XGS_W, arrow_y, XGS_X + XGS_W + 80, arrow_y,
                      fill='#444499', width=2, arrow=tk.LAST)
        c.create_text(XGS_X + XGS_W + 42, arrow_y - 10,
                      text=f"→ {port} USB", font=('Arial', 8, 'bold'), fill='#444499')

        # XGS not connected to T8 — draw "No T8 connection" note
        c.create_text(XGS_X + XGS_W // 2, XGS_Y + XGS_H + 14,
                      text="(direct to PC only)", font=('Arial', 7, 'italic'),
                      fill='#888888')

        # ── Legend ────────────────────────────────────────────────────────────
        legend_y = T8_Y + T8_H + 30
        legend_items = [
            ('#1a5fc8', "Thermocouple AIN wiring"),
            ('#e07820', "Keysight monitor (AIN)"),
            ('#1a7a1a', "Keysight program (DAC)"),
            ('#888888', "Keysight local/analog (EIO)"),
            ('#222222', "Ground connections"),
            ('#cc0000', "Pin CONFLICT — reassign in Settings"),
        ]
        lx = T8_X
        for col, text in legend_items:
            c.create_line(lx, legend_y + 6, lx + 22, legend_y + 6,
                          fill=col, width=3)
            c.create_text(lx + 26, legend_y + 6, text=text, anchor='w',
                          font=('Arial', 8), fill='#333333')
            lx += 200

        # Update scroll region to fit all content
        total_w = XGS_X + XGS_W + 120
        total_h = legend_y + 30
        c.configure(scrollregion=(0, 0, total_w, total_h))

    # ──────────────────────────────────────────────────────────────────────────
    # Live-refresh loop
    # ──────────────────────────────────────────────────────────────────────────

    def _schedule_refresh(self):
        try:
            self.after(self.REFRESH_MS, self._do_refresh)
        except tk.TclError:
            pass  # Window was destroyed

    def _do_refresh(self):
        """Update live value labels and status dots from stored readings."""
        # Thermocouple rows
        for name, widgets in self._tc_rows.items():
            temp_val = self._all_readings.get(name)
            raw_val  = self._raw_voltages.get(f"{name}_rawV")

            # Status dot
            dot_color = '#00CC00' if temp_val is not None else '#333333'
            try:
                widgets['dot'].config(bg=dot_color)
            except tk.TclError:
                continue

            # Temperature
            if temp_val is not None:
                # Find TC unit from config
                unit = 'C'
                for tc in self._config.get('thermocouples', []):
                    if tc['name'] == name:
                        unit = tc.get('units', 'C')
                        break
                widgets['temp'].config(
                    text=f"{temp_val:>9.2f} °{unit}",
                    foreground='#1a5f7a'
                )
            else:
                widgets['temp'].config(text="—", foreground='#888888')

            # Raw / differential voltage
            if raw_val is not None:
                # Display in millivolts (TC signals are millivolt-range)
                mv = raw_val * 1000.0
                volt_str = f"{raw_val:>+10.6f} V  ({mv:>+8.3f} mV)"
                widgets['raw'].config(text=volt_str,  foreground='#5a3e7a')
                widgets['diff'].config(text=volt_str, foreground='#5a3e7a')
            else:
                widgets['raw'].config(text="—  (no raw read)", foreground='#888888')
                widgets['diff'].config(text="—  (no raw read)", foreground='#888888')

        # FRG-702 rows
        for name, widgets in self._frg_rows.items():
            details = self._latest_frg702_details.get(name, {})
            val = details.get('pressure')
            mode = details.get('mode', 'Unknown')
            voltage = details.get('voltage')

            dot_color = '#00CC00' if val is not None else '#333333'
            try:
                widgets['dot'].config(bg=dot_color)
            except tk.TclError:
                continue

            if val is not None:
                text = f"{val:.3e}"
                if mode == 'Analog' and voltage is not None:
                    text += f" ({voltage:.3f} V)"

                widgets['val'].config(
                    text=text,
                    foreground='#1a5f7a'
                )
            else:
                widgets['val'].config(text="—", foreground='#888888')

        self._schedule_refresh()

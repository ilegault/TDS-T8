"""
pinout_display.py
PURPOSE: Live pinout display showing current hardware configuration and pin
         assignments, updated in real-time with live sensor readings.

Allows users to verify that the physical wiring matches what the software
expects, and to confirm that unit conversions are working correctly by showing
both the raw thermocouple voltage and the resulting temperature side-by-side.
"""

import logging
import tkinter as tk
from tkinter import ttk

logger = logging.getLogger(__name__)



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
        self._separator()
        self._build_stripe_mapping_section()

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

            pin_str  = f"AIN{ch}+"
            pair_str = "+/−"

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
        # NOTE: unused — possible bug, see workflow-setup ticket 02
        del cfg

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

    def _build_stripe_mapping_section(self):
        """Constructs the static table showing how the striped ribbon cable
        is mapped from the Keysight DB25 J1 connector to the T8 terminals."""
        self._section("Cable Stripe Mappings (Keysight J1 to LabJack T8)")

        f = ttk.Frame(self._content_frame)
        f.pack(fill=tk.X, padx=12, pady=2)

        # Header row
        hdr_row = ttk.Frame(f)
        hdr_row.pack(fill=tk.X)
        col_defs = [
            ("Stripe #", 10),
            ("Keysight Pin", 15),
            ("Function", 35),
            ("LabJack Terminal", 18),
        ]
        for txt, w in col_defs:
            ttk.Label(hdr_row, text=txt, font=_BOLD, width=w, anchor='w').pack(side=tk.LEFT, padx=2)

        ttk.Separator(f, orient='horizontal').pack(fill=tk.X, pady=2)

        # Data rows
        mappings = [
            ("1", "Pin 12", "Signal Common (GND reference)", "GND"),
            ("2", "Pin 11", "Voltage Monitor output",        "AIN4+"),
            ("3", "Pin 24", "Current Monitor output",        "AIN5+"),
            ("4", "Pin 9",  "Voltage Program",               "DAC0"),
            ("5", "Pin 22", "Voltage Program Return",        "GND"),
            ("6", "Pin 10", "Current Program",               "DAC1"),
            ("7", "Pin 23", "Current Program Return",        "GND"),
            ("8", "Pin 8",  "Local/Analog Enable",           "FIO0"),
            ("9", "Pin 15", "Shut off",                      "FIO1"),
        ]

        for stripe, pin, func, terminal in mappings:
            row = ttk.Frame(f)
            row.pack(fill=tk.X, pady=1)
            for val, w in zip([stripe, pin, func, terminal], [10, 15, 35, 18]):
                ttk.Label(row, text=val, width=w, anchor='w', font=_MONO).pack(side=tk.LEFT, padx=2)

    # ──────────────────────────────────────────────────────────────────────────
    # Wiring Diagram tab
    # ──────────────────────────────────────────────────────────────────────────

    def _build_wiring_diagram(self):
        """Draw the visual wiring diagram on self._wiring_canvas.

        T8 physical layout:
          Left screw block:  DAC1, DAC0, GND, EIO0
          Right screw block: AIN0+/− through AIN7+/− (differential pairs)

        Thermocouples (differential) connect to AIN0+/− through AINn+/−
        on the RIGHT side.  Keysight V/I program wires connect to DAC0/DAC1
        on the LEFT side.  Keysight V/I monitor wires connect to AIN4/AIN5
        on the RIGHT side, routed below the T8 box.
        """
        c = self._wiring_canvas
        if c is None:
            return
        c.delete('all')

        tcs = [tc for tc in self._config.get('thermocouples', []) if tc.get('enabled', True)]

        v_mon_pin  = self._settings.ps_voltage_monitor_pin  # e.g. "AIN4"
        i_mon_pin  = self._settings.ps_current_monitor_pin  # e.g. "AIN5"
        v_mon_ain  = int(v_mon_pin.replace("AIN", "")) if v_mon_pin.startswith("AIN") else 4
        i_mon_ain  = int(i_mon_pin.replace("AIN", "")) if i_mon_pin.startswith("AIN") else 5
        v_prog_pin = self._settings.ps_voltage_pin   # e.g. "DAC0"
        i_prog_pin = self._settings.ps_current_pin   # e.g. "DAC1"

        # Detect TC/PS monitor pin conflicts
        conflicts = {tc['channel'] for tc in tcs
                     if tc['channel'] in (v_mon_ain, i_mon_ain)}

        # ── Layout constants ──────────────────────────────────────────────────
        T8_X  = 340   # left edge of T8 rectangle
        T8_Y  = 80    # top edge
        T8_W  = 190   # width
        ROW_H = 28    # height per terminal row
        PAD   = 10    # inner text padding

        # Physical terminal groups
        left_terminals  = ['DAC1', 'DAC0', 'GND', 'EIO0']
        right_terminals = ['AIN0', 'AIN1', 'AIN2', 'AIN3',
                           'AIN4', 'AIN5', 'AIN6', 'AIN7']
        T8_H = ROW_H * max(len(left_terminals), len(right_terminals)) + 20

        # ── Draw T8 box ───────────────────────────────────────────────────────
        c.create_rectangle(T8_X, T8_Y, T8_X + T8_W, T8_Y + T8_H,
                           fill='#e8f0fe', outline='#3a5fd9', width=2)
        c.create_text(T8_X + T8_W // 2, T8_Y + 8,
                      text="LabJack T8", font=('Arial', 10, 'bold'), fill='#1a3399')
        c.create_text(T8_X + PAD, T8_Y + T8_H - 6,
                      text="LEFT side", font=('Arial', 7, 'italic'), anchor='w',
                      fill='#555555')
        c.create_text(T8_X + T8_W - PAD, T8_Y + T8_H - 6,
                      text="RIGHT side", font=('Arial', 7, 'italic'), anchor='e',
                      fill='#555555')

        # LEFT terminals (DAC/GND/EIO) — tick marks on left edge
        left_term_y = {}
        for idx, term in enumerate(left_terminals):
            y = T8_Y + 20 + idx * ROW_H + ROW_H // 2
            left_term_y[term] = y
            c.create_text(T8_X + PAD, y, text=term, anchor='w',
                          font=('Courier', 9), fill='#222222')
            c.create_line(T8_X - 6, y, T8_X, y, fill='#555555', width=1)

        # RIGHT terminals (AIN differential pairs) — tick marks on right edge
        right_term_y = {}
        for idx, term in enumerate(right_terminals):
            y = T8_Y + 20 + idx * ROW_H + ROW_H // 2
            right_term_y[term] = y
            c.create_text(T8_X + T8_W - PAD, y,
                          text=f"{term}+/−", anchor='e',
                          font=('Courier', 9), fill='#222222')
            c.create_line(T8_X + T8_W, y, T8_X + T8_W + 6, y,
                          fill='#555555', width=1)

        # ── Helper: 4-point horizontal-exit bezier curve ──────────────────────
        def _bezier(x1, y1, x2, y2, **kw):
            cx1 = x1 + (x2 - x1) * 0.4
            cx2 = x2 - (x2 - x1) * 0.4
            c.create_line(x1, y1, cx1, y1, cx2, y2, x2, y2,
                          smooth=True, **kw)

        # ── Right side: TC boxes (aligned with their AIN terminal rows) ───────
        TC_BOX_W = 140
        TC_BOX_H = 36
        TC_LEFT  = T8_X + T8_W + 60   # left edge of TC boxes

        for tc in tcs:
            ain_key = f'AIN{tc["channel"]}'
            aim_y   = right_term_y.get(ain_key, T8_Y + 40)
            bx = TC_LEFT
            by = aim_y - TC_BOX_H // 2
            fill    = '#ffe0e0' if tc['channel'] in conflicts else '#e8f8e8'
            outline = '#cc0000' if tc['channel'] in conflicts else '#2a8a2a'
            c.create_rectangle(bx, by, bx + TC_BOX_W, by + TC_BOX_H,
                               fill=fill, outline=outline, width=2)
            c.create_text(bx + TC_BOX_W // 2, by + TC_BOX_H // 2 - 7,
                          text=tc['name'], font=('Arial', 9, 'bold'), fill='#1a3a1a')
            c.create_text(bx + TC_BOX_W // 2, by + TC_BOX_H // 2 + 7,
                          text=f"Type {tc.get('type', 'K')}  →  {ain_key}+/−",
                          font=('Courier', 8), fill='#444444')

            # Wire: TC box left edge → T8 right-edge tick (bezier)
            line_color = '#cc0000' if tc['channel'] in conflicts else '#1a5fc8'
            _bezier(bx, aim_y, T8_X + T8_W + 6, aim_y, fill=line_color, width=2)
            mid_x = (bx + T8_X + T8_W + 6) // 2
            c.create_text(mid_x, aim_y - 7, text="TC+/−",
                          font=('Arial', 7), fill=line_color)
            if tc['channel'] in conflicts:
                c.create_text(mid_x, aim_y + 8,
                              text="⚠ CONFLICT", font=('Arial', 7, 'bold'),
                              fill='#cc0000')

        # ── Left side: Keysight box ───────────────────────────────────────────
        KS_BOX_W = 158
        KS_BOX_H = 132
        KS_X     = 12
        # Centre vertically on the DAC/GND left-terminal region
        left_mid_y = (left_term_y.get('DAC1', T8_Y + 34) +
                      left_term_y.get('GND',  T8_Y + 90)) // 2
        KS_Y = left_mid_y - KS_BOX_H // 2

        c.create_rectangle(KS_X, KS_Y, KS_X + KS_BOX_W, KS_Y + KS_BOX_H,
                           fill='#fff3e0', outline='#c77a00', width=2)
        c.create_text(KS_X + KS_BOX_W // 2, KS_Y + 12,
                      text="Keysight N5700", font=('Arial', 9, 'bold'), fill='#7a3d00')
        c.create_text(KS_X + KS_BOX_W // 2, KS_Y + 26,
                      text="J1 DB25 → Phoenix", font=('Arial', 7), fill='#555555')
        c.create_text(KS_X + KS_BOX_W // 2, KS_Y + 38,
                      text="Contact breakout", font=('Arial', 7), fill='#555555')

        # Signal labels inside the Keysight box
        ks_signal_rows = [
            (f"V.Mon (J1 P11) → {v_mon_pin}",   '#e07820', 52),
            (f"I.Mon (J1 P24) → {i_mon_pin}",   '#e07820', 65),
            (f"V.Prog (J1 P9) → {v_prog_pin}",  '#1a7a1a', 78),
            (f"I.Prog (J1 P10) → {i_prog_pin}", '#1a7a1a', 91),
            ("GND (J1 12/22/23) → GND",          '#222222', 104),
            ("LOCAL (J1 P14) → EIO0",             '#888888', 117),
        ]
        for label, col, y_off in ks_signal_rows:
            c.create_text(KS_X + 5, KS_Y + y_off, text=label, anchor='w',
                          font=('Courier', 6), fill=col)

        ks_right = KS_X + KS_BOX_W

        # DAC program connections: Keysight right → T8 left-edge tick (bezier)
        dac_prog = [
            (v_prog_pin, '#1a7a1a', 'V_PROG', KS_Y + 78),
            (i_prog_pin, '#1a7a1a', 'I_PROG', KS_Y + 91),
        ]
        for pin, col, lbl, ks_wy in dac_prog:
            ty = left_term_y.get(pin)
            if ty is None:
                continue
            _bezier(ks_right, ks_wy, T8_X - 6, ty, fill=col, width=2)
            mid_x = (ks_right + T8_X - 6) // 2
            c.create_text(mid_x, (ks_wy + ty) // 2 - 7,
                          text=lbl, font=('Arial', 7), fill=col)

        # GND: Keysight right → T8 left-edge GND tick (bezier, dashed)
        gnd_ty = left_term_y.get('GND')
        if gnd_ty is not None:
            ks_gnd_y = KS_Y + 104
            _bezier(ks_right, ks_gnd_y, T8_X - 6, gnd_ty,
                    fill='#222222', width=2, dash=(4, 2))
            mid_x = (ks_right + T8_X - 6) // 2
            c.create_text(mid_x, (ks_gnd_y + gnd_ty) // 2 - 7,
                          text="GND", font=('Arial', 7), fill='#222222')

        # LOCAL/ANALOG ENABLE: Keysight right → T8 left-edge EIO0 (bezier, dashed)
        eio0_ty = left_term_y.get('EIO0')
        if eio0_ty is not None:
            ks_eio_y = KS_Y + 117
            _bezier(ks_right, ks_eio_y, T8_X - 6, eio0_ty,
                    fill='#888888', width=2, dash=(3, 3))
            mid_x = (ks_right + T8_X - 6) // 2
            c.create_text(mid_x, (ks_eio_y + eio0_ty) // 2 - 7,
                          text="LOCAL", font=('Arial', 7), fill='#888888')

        # Monitor connections: Keysight left side → T8 RIGHT-edge AIN ticks.
        # Route below the T8 box to avoid visual crossing.
        mon_connections = [
            (v_mon_pin, '#e07820', 'V_MON', KS_Y + 52, 25),
            (i_mon_pin, '#e07820', 'I_MON', KS_Y + 65, 42),
        ]
        for pin, col, lbl, ks_wy, bot_off in mon_connections:
            ty = right_term_y.get(pin)
            if ty is None:
                continue
            below_y = T8_Y + T8_H + bot_off
            left_x  = T8_X - 20
            right_x = T8_X + T8_W + 20
            tick_x  = T8_X + T8_W + 6
            c.create_line(
                ks_right, ks_wy,
                left_x,   ks_wy,
                left_x,   below_y,
                right_x,  below_y,
                right_x,  ty,
                tick_x,   ty,
                smooth=True, fill=col, width=2
            )
            lbl_x = T8_X + T8_W // 2
            c.create_text(lbl_x, below_y + 7, text=lbl,
                          font=('Arial', 7), fill=col)

        # ── XGS-600 box (upper right, above TC boxes) ─────────────────────────
        XGS_X = TC_LEFT
        XGS_Y = max(10, T8_Y - 65)
        XGS_W = 140
        XGS_H = 52
        c.create_rectangle(XGS_X, XGS_Y, XGS_X + XGS_W, XGS_Y + XGS_H,
                           fill='#f0f0ff', outline='#444499', width=2)
        c.create_text(XGS_X + XGS_W // 2, XGS_Y + 13,
                      text="XGS-600", font=('Arial', 9, 'bold'), fill='#1a1a66')
        port = getattr(self._settings, 'xgs600_port', 'COM3')
        c.create_text(XGS_X + XGS_W // 2, XGS_Y + 28,
                      text="SER.COMM DB9", font=('Courier', 7), fill='#333333')
        c.create_text(XGS_X + XGS_W // 2, XGS_Y + 40,
                      text=f"→ FTDI USB ({port})", font=('Courier', 7), fill='#333333')
        arrow_y = XGS_Y + XGS_H // 2
        c.create_line(XGS_X + XGS_W, arrow_y, XGS_X + XGS_W + 70, arrow_y,
                      fill='#444499', width=2, arrow=tk.LAST)
        c.create_text(XGS_X + XGS_W + 36, arrow_y - 10,
                      text=f"→ {port}", font=('Arial', 8, 'bold'), fill='#444499')
        c.create_text(XGS_X + XGS_W // 2, XGS_Y + XGS_H + 12,
                      text="(direct to PC only)", font=('Arial', 7, 'italic'),
                      fill='#888888')

        # ── Legend ────────────────────────────────────────────────────────────
        legend_y = T8_Y + T8_H + 80
        legend_items = [
            ('#1a5fc8', "Thermocouple AIN+/− wiring"),
            ('#e07820', "Keysight monitor (right-side AIN)"),
            ('#1a7a1a', "Keysight program (left-side DAC)"),
            ('#888888', "Keysight local/analog enable (EIO)"),
            ('#222222', "Ground connections"),
            ('#cc0000', "Pin CONFLICT — reassign in Settings"),
        ]
        lx = max(20, T8_X - 160)
        ly = legend_y
        for i, (col, text) in enumerate(legend_items):
            if i > 0 and i % 3 == 0:
                ly += 18
                lx = max(20, T8_X - 160)
            c.create_line(lx, ly + 6, lx + 22, ly + 6, fill=col, width=3)
            c.create_text(lx + 26, ly + 6, text=text, anchor='w',
                          font=('Arial', 8), fill='#333333')
            lx += 240

        # Update scroll region
        total_w = XGS_X + XGS_W + 120
        total_h = ly + 40
        c.configure(scrollregion=(0, 0, total_w, total_h))

    # ──────────────────────────────────────────────────────────────────────────
    # Live-refresh loop
    # ──────────────────────────────────────────────────────────────────────────

    def _schedule_refresh(self):
        try:
            self.after(self.REFRESH_MS, self._do_refresh)
        except tk.TclError as e:
            # Pinout window was destroyed; stop refresh loop
            logger.debug("Pinout window destroyed; refresh loop stopped (%s)", e)


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

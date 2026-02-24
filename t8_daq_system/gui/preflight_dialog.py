"""
preflight_dialog.py
PURPOSE: Pre-flight wiring check dialog shown before DAQ acquisition starts.

Displays a checklist of every expected physical connection, dynamically
generated from the current configuration.  The user must tick all items and
click "Confirmed — Start DAQ" before acquisition begins.

A "Skip" button is provided for experienced users; skipping logs a warning.
The skip_preflight_check registry flag (AppSettings) permanently bypasses this
dialog when True.
"""

import tkinter as tk
from tkinter import ttk


# J1 DB25 pin assignments for the Keysight N5700 Series (fixed physical wiring)
_KEYSIGHT_J1_PINS = {
    # signal_name: (pin_numbers_str, description)
    'V_PROG':  ('J1 Pin 9',           'Voltage Program (0–10 V analog)'),
    'I_PROG':  ('J1 Pin 10',          'Current Program (0–10 V analog)'),
    'V_MON':   ('J1 Pin 11',          'Voltage Monitor (analog output)'),
    'I_MON':   ('J1 Pin 24',          'Current Monitor (analog output)'),
    'GND':     ('J1 Pins 12, 22, 23', 'Signal Ground — NOT to any voltage source'),
    'LOCAL':   ('J1 Pin 14 / EIO0',   'Local/Analog Enable (digital output from T8 EIO0)'),
}

# DAC pin → J1 description
_DAC_TO_J1 = {
    'DAC0': ('J1 Pin 9',  'Voltage Program'),
    'DAC1': ('J1 Pin 10', 'Current Program'),
}

# AIN pin → J1 description
_AIN_TO_J1 = {
    'AIN0': 'AIN0', 'AIN1': 'AIN1', 'AIN2': 'AIN2', 'AIN3': 'AIN3',
    'AIN4': 'AIN4', 'AIN5': 'AIN5', 'AIN6': 'AIN6', 'AIN7': 'AIN7',
}


class PreflightDialog(tk.Toplevel):
    """
    Modal wiring pre-flight check dialog.

    Parameters
    ----------
    parent : tk.Widget
    config : dict           Current internal config dict from MainWindow.
    app_settings : AppSettings
    """

    def __init__(self, parent, config, app_settings):
        super().__init__(parent)
        self.title("Wiring Pre-flight Check")
        self.resizable(True, True)
        self.grab_set()
        self.transient(parent)

        self._config   = config
        self._settings = app_settings
        self.confirmed = False   # Set True if user confirms

        self._check_vars = []    # list of (tk.BooleanVar, description_str)

        self._build_widgets()

        self.update_idletasks()
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h   = self.winfo_width(), self.winfo_height()
        self.geometry(f"{max(w, 580)}x{min(max(h, 300), 700)}"
                      f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    # ──────────────────────────────────────────────────────────────────────────

    def _build_widgets(self):
        # Header
        hdr = ttk.Frame(self)
        hdr.pack(fill=tk.X, padx=12, pady=(10, 4))
        ttk.Label(hdr, text="Wiring Pre-flight Check",
                  font=('Arial', 13, 'bold')).pack(anchor='w')
        ttk.Label(hdr,
                  text="Verify every physical connection before starting acquisition.\n"
                       "Check each item to confirm it is correctly wired.",
                  font=('Arial', 9), foreground='#555555').pack(anchor='w', pady=(2, 0))

        ttk.Separator(self, orient='horizontal').pack(fill=tk.X, padx=8, pady=6)

        # Scrollable checklist
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        canvas    = tk.Canvas(outer, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _resize_inner(event):
            canvas.configure(scrollregion=canvas.bbox('all'))
        def _resize_canvas(event):
            canvas.itemconfig(win_id, width=event.width)

        inner.bind('<Configure>', _resize_inner)
        canvas.bind('<Configure>', _resize_canvas)

        def _scroll(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', _scroll)

        self._populate_checklist(inner)

        ttk.Separator(self, orient='horizontal').pack(fill=tk.X, padx=8, pady=6)

        # Bottom buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=(0, 10))

        self._confirm_btn = ttk.Button(
            btn_frame, text="Confirmed — Start DAQ",
            command=self._on_confirm, state='disabled'
        )
        self._confirm_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(btn_frame, text="Skip (I know what I'm doing)",
                   command=self._on_skip).pack(side=tk.LEFT)

        ttk.Button(btn_frame, text="Cancel",
                   command=self.destroy).pack(side=tk.RIGHT)

    def _populate_checklist(self, parent):
        """Build checklist items from the current config."""
        items = self._generate_checklist_items()

        for desc in items:
            var = tk.BooleanVar(value=False)
            self._check_vars.append(var)
            row = ttk.Frame(parent)
            row.pack(fill=tk.X, pady=2, padx=6)
            cb = ttk.Checkbutton(row, variable=var,
                                 command=self._on_check_changed)
            cb.pack(side=tk.LEFT, padx=(0, 6))
            ttk.Label(row, text=desc, wraplength=480, anchor='w',
                      justify='left').pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _generate_checklist_items(self):
        """Return a list of plain-language wiring check strings."""
        items = []
        s = self._settings

        # Thermocouples
        tcs = [tc for tc in self._config.get('thermocouples', [])
               if tc.get('enabled', True)]
        for tc in tcs:
            tc_type = tc.get('type', 'K')
            ch      = tc['channel']
            name    = tc['name']
            items.append(
                f"{name} (Type {tc_type})  →  T8 AIN{ch} screw terminal  (+) and (−)"
            )

        # Keysight connections
        v_prog = s.ps_voltage_pin   # e.g. "DAC0"
        i_prog = s.ps_current_pin   # e.g. "DAC1"
        v_mon  = s.ps_voltage_monitor_pin  # e.g. "AIN4"
        i_mon  = s.ps_current_monitor_pin  # e.g. "AIN5"

        v_prog_j1 = _DAC_TO_J1.get(v_prog, (v_prog, 'Voltage Program'))
        i_prog_j1 = _DAC_TO_J1.get(i_prog, (i_prog, 'Current Program'))

        # Map AIN pin name to number for display
        v_mon_num = v_mon.replace('AIN', '') if v_mon.startswith('AIN') else v_mon
        i_mon_num = i_mon.replace('AIN', '') if i_mon.startswith('AIN') else i_mon

        items.append(
            f"Keysight {v_prog_j1[0]}  →  T8 {v_prog}  ({v_prog_j1[1]})"
        )
        items.append(
            f"Keysight {i_prog_j1[0]}  →  T8 {i_prog}  ({i_prog_j1[1]})"
        )
        items.append(
            f"Keysight J1 Pin 11  →  T8 {v_mon}  (Voltage Monitor)"
        )
        items.append(
            f"Keysight J1 Pin 24  →  T8 {i_mon}  (Current Monitor)"
        )
        items.append(
            "Keysight J1 Pins 12, 22, 23  →  T8 GND only — NOT to any voltage"
        )

        # XGS-600 connection
        port = getattr(s, 'xgs600_port', 'COM3')
        items.append(
            f"XGS-600 SER.COMM  →  DB9 male-male adapter  →  FTDI USB cable  →  USB port ({port})"
        )

        return items

    def _on_check_changed(self):
        """Enable Confirm button only when all boxes are checked."""
        all_checked = all(v.get() for v in self._check_vars)
        self._confirm_btn.config(state='normal' if all_checked else 'disabled')

    def _on_confirm(self):
        self.confirmed = True
        self.destroy()

    def _on_skip(self):
        print("[WARNING] Pre-flight wiring check skipped by user.")
        self.confirmed = True
        self.destroy()

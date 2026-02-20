"""
settings_dialog.py
PURPOSE: Settings dialog window for configuring persistent application settings.

Opened via the Settings menu in the main menu bar.  All fields map directly to
AppSettings attributes.  On Save the dialog calls AppSettings.save() and
triggers a callback so the live GUI can apply the new values immediately.
"""

import tkinter as tk
from tkinter import ttk, filedialog


class SettingsDialog(tk.Toplevel):
    """
    Modal dialog that exposes all AppSettings fields as labeled widgets.

    Parameters
    ----------
    parent : tk.Widget
        Owner window (main window root).
    settings : AppSettings
        Live AppSettings instance shared with MainWindow.
    on_save_callback : callable, optional
        Called after a successful save so the caller can refresh the GUI.
        Signature: ``on_save_callback()``
    """

    def __init__(self, parent, settings, on_save_callback=None):
        super().__init__(parent)
        self.title("Application Settings")
        self.resizable(False, False)
        self.grab_set()                        # Modal
        self.transient(parent)

        self._settings = settings
        self._on_save = on_save_callback
        self._result_saved = False

        self._build_widgets()
        self._load_values()

        # Centre over parent
        self.update_idletasks()
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    # ──────────────────────────────────────────────────────────────────────────
    # Widget construction
    # ──────────────────────────────────────────────────────────────────────────

    def _build_widgets(self):
        pad = {"padx": 8, "pady": 4}

        # ── Sensor Configuration ──────────────────────────────────────────────
        sensor_frame = ttk.LabelFrame(self, text="Sensor Configuration")
        sensor_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=6)

        ttk.Label(sensor_frame, text="TC Count:").grid(row=0, column=0, sticky="w", **pad)
        self._tc_count_var = tk.StringVar()
        ttk.Combobox(sensor_frame, textvariable=self._tc_count_var,
                     values=["0","1","2","3","4","5","6","7"], width=6,
                     state="readonly").grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(sensor_frame, text="TC Type:").grid(row=1, column=0, sticky="w", **pad)
        self._tc_type_var = tk.StringVar()
        ttk.Combobox(sensor_frame, textvariable=self._tc_type_var,
                     values=["K","J","T","E","R","S","B","N","C"], width=6,
                     state="readonly").grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(sensor_frame, text="TC Unit:").grid(row=2, column=0, sticky="w", **pad)
        self._tc_unit_var = tk.StringVar()
        ttk.Combobox(sensor_frame, textvariable=self._tc_unit_var,
                     values=["C","F","K"], width=6,
                     state="readonly").grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(sensor_frame, text="FRG Count:").grid(row=3, column=0, sticky="w", **pad)
        self._frg_count_var = tk.StringVar()
        ttk.Combobox(sensor_frame, textvariable=self._frg_count_var,
                     values=["0","1","2"], width=6,
                     state="readonly").grid(row=3, column=1, sticky="w", **pad)

        ttk.Label(sensor_frame, text="Pressure Unit:").grid(row=4, column=0, sticky="w", **pad)
        self._p_unit_var = tk.StringVar()
        ttk.Combobox(sensor_frame, textvariable=self._p_unit_var,
                     values=["mbar","Torr","Pa"], width=8,
                     state="readonly").grid(row=4, column=1, sticky="w", **pad)

        # ── Acquisition Rates ─────────────────────────────────────────────────
        rate_frame = ttk.LabelFrame(self, text="Acquisition Rates")
        rate_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=6)

        ttk.Label(rate_frame, text="Sample Rate (ms):").grid(row=0, column=0, sticky="w", **pad)
        self._sample_rate_var = tk.StringVar()
        ttk.Combobox(rate_frame, textvariable=self._sample_rate_var,
                     values=["100","200","500","1000","2000"], width=8,
                     state="readonly").grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(rate_frame, text="Display Rate (ms):").grid(row=1, column=0, sticky="w", **pad)
        self._display_rate_var = tk.StringVar()
        ttk.Combobox(rate_frame, textvariable=self._display_rate_var,
                     values=["100","250","500","1000"], width=8,
                     state="readonly").grid(row=1, column=1, sticky="w", **pad)

        # ── Axis Scale Settings ───────────────────────────────────────────────
        scale_frame = ttk.LabelFrame(self, text="Axis Scales")
        scale_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=10, pady=6)

        self._abs_scale_var = tk.BooleanVar()
        ttk.Checkbutton(scale_frame, text="Use Absolute Scales",
                        variable=self._abs_scale_var).grid(
            row=0, column=0, columnspan=2, sticky="w", **pad)

        def _row(frame, row, label, var):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", **pad)
            e = ttk.Entry(frame, textvariable=var, width=12)
            e.grid(row=row, column=1, sticky="w", **pad)

        self._temp_min_var   = tk.StringVar()
        self._temp_max_var   = tk.StringVar()
        self._press_min_var  = tk.StringVar()
        self._press_max_var  = tk.StringVar()
        self._psv_min_var    = tk.StringVar()
        self._psv_max_var    = tk.StringVar()
        self._psi_min_var    = tk.StringVar()
        self._psi_max_var    = tk.StringVar()

        _row(scale_frame, 1, "Temp Min:",      self._temp_min_var)
        _row(scale_frame, 2, "Temp Max:",      self._temp_max_var)
        _row(scale_frame, 3, "Press Min:",     self._press_min_var)
        _row(scale_frame, 4, "Press Max:",     self._press_max_var)
        _row(scale_frame, 5, "PS Volt Min:",   self._psv_min_var)
        _row(scale_frame, 6, "PS Volt Max:",   self._psv_max_var)
        _row(scale_frame, 7, "PS Curr Min:",   self._psi_min_var)
        _row(scale_frame, 8, "PS Curr Max:",   self._psi_max_var)

        # ── Hardware / Paths ──────────────────────────────────────────────────
        hw_frame = ttk.LabelFrame(self, text="Hardware & Paths")
        hw_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=6)

        ttk.Label(hw_frame, text="VISA Resource:").grid(row=0, column=0, sticky="w", **pad)
        self._visa_var = tk.StringVar()
        ttk.Entry(hw_frame, textvariable=self._visa_var, width=36).grid(
            row=0, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(hw_frame, text="Log Folder:").grid(row=1, column=0, sticky="w", **pad)
        self._log_folder_var = tk.StringVar()
        ttk.Entry(hw_frame, textvariable=self._log_folder_var, width=30).grid(
            row=1, column=1, sticky="ew", **pad)
        ttk.Button(hw_frame, text="Browse…",
                   command=self._browse_log_folder).grid(row=1, column=2, **pad)

        hw_frame.columnconfigure(1, weight=1)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10)

        ttk.Button(btn_frame, text="Save",   command=self._on_save_click,
                   width=10).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy,
                   width=10).pack(side=tk.LEFT, padx=8)

    # ──────────────────────────────────────────────────────────────────────────
    # Load / Save logic
    # ──────────────────────────────────────────────────────────────────────────

    def _load_values(self):
        """Populate widgets from the current AppSettings object."""
        s = self._settings
        self._tc_count_var.set(str(s.tc_count))
        self._tc_type_var.set(s.tc_type)
        self._tc_unit_var.set(s.tc_unit)
        self._frg_count_var.set(str(s.frg_count))
        self._p_unit_var.set(s.p_unit)
        self._sample_rate_var.set(str(s.sample_rate_ms))
        self._display_rate_var.set(str(s.display_rate_ms))
        self._abs_scale_var.set(s.use_absolute_scales)
        self._temp_min_var.set(str(s.temp_range_min))
        self._temp_max_var.set(str(s.temp_range_max))
        self._press_min_var.set(repr(s.press_range_min))
        self._press_max_var.set(repr(s.press_range_max))
        self._psv_min_var.set(str(s.ps_v_range_min))
        self._psv_max_var.set(str(s.ps_v_range_max))
        self._psi_min_var.set(str(s.ps_i_range_min))
        self._psi_max_var.set(str(s.ps_i_range_max))
        self._visa_var.set(s.visa_resource)
        self._log_folder_var.set(s.log_folder)

    def _on_save_click(self):
        """Validate fields, update AppSettings, persist, and close."""
        s = self._settings
        try:
            s.tc_count         = int(self._tc_count_var.get())
            s.tc_type          = self._tc_type_var.get()
            s.tc_unit          = self._tc_unit_var.get()
            s.frg_count        = int(self._frg_count_var.get())
            s.p_unit           = self._p_unit_var.get()
            s.sample_rate_ms   = int(self._sample_rate_var.get())
            s.display_rate_ms  = int(self._display_rate_var.get())
            s.use_absolute_scales = self._abs_scale_var.get()
            s.temp_range_min   = float(self._temp_min_var.get())
            s.temp_range_max   = float(self._temp_max_var.get())
            s.press_range_min  = float(self._press_min_var.get())
            s.press_range_max  = float(self._press_max_var.get())
            s.ps_v_range_min   = float(self._psv_min_var.get())
            s.ps_v_range_max   = float(self._psv_max_var.get())
            s.ps_i_range_min   = float(self._psi_min_var.get())
            s.ps_i_range_max   = float(self._psi_max_var.get())
            s.visa_resource    = self._visa_var.get().strip()
            s.log_folder       = self._log_folder_var.get().strip()
        except ValueError as exc:
            from tkinter import messagebox
            messagebox.showerror("Invalid Value", f"Please check your entries:\n{exc}",
                                 parent=self)
            return

        # Persist to registry
        s.save()
        self._result_saved = True

        # Notify caller so live GUI refreshes
        if callable(self._on_save):
            try:
                self._on_save()
            except Exception:
                pass

        self.destroy()

    def _browse_log_folder(self):
        folder = filedialog.askdirectory(
            parent=self,
            title="Select Log Folder",
            initialdir=self._log_folder_var.get() or "."
        )
        if folder:
            self._log_folder_var.set(folder)

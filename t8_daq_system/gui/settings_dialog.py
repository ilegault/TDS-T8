"""
settings_dialog.py
PURPOSE: Settings dialog window for configuring persistent application settings.

Opened via the Settings button in the main control panel.  Features a tabbed
interface with presets, sensor configuration, hardware settings, and axis scales.
All fields map directly to AppSettings attributes.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


PRESETS = {
    "Basic Setup": {
        "tc_count": 1,
        "tc_type": "C",
        "tc_unit": "C",
        "frg_count": 1,
        "p_unit": "mbar",
        "sample_rate_ms": 1000,
        "display_rate_ms": 1000,
    },
    "High Frequency": {
        "tc_count": 2,
        "tc_type": "K",
        "tc_unit": "C",
        "frg_count": 1,
        "p_unit": "Torr",
        "sample_rate_ms": 100,
        "display_rate_ms": 250,
    },
    "Multi-Sensor": {
        "tc_count": 4,
        "tc_type": "K",
        "tc_unit": "C",
        "frg_count": 2,
        "p_unit": "mbar",
        "sample_rate_ms": 500,
        "display_rate_ms": 500,
    },
    "Lab Default": {
        "tc_count": 1,
        "tc_type": "C",
        "tc_unit": "C",
        "frg_count": 1,
        "p_unit": "mbar",
        "sample_rate_ms": 1000,
        "display_rate_ms": 1000,
    },
}


class SettingsDialog(tk.Toplevel):
    """
    Modal settings dialog with tabbed interface.

    Parameters
    ----------
    parent : tk.Widget
        Owner window (main window root).
    settings : AppSettings
        Live AppSettings instance shared with MainWindow.
    on_save_callback : callable, optional
        Called after a successful save so the caller can refresh the GUI.
    """

    def __init__(self, parent, settings, on_save_callback=None):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("750x750")
        self.minsize(600, 600)
        self.resizable(True, True)
        self.grab_set()
        self.transient(parent)

        self._settings = settings
        self._on_save = on_save_callback
        self._result_saved = False

        self._build_widgets()
        self._load_values()

        self.update_idletasks()
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    def _build_widgets(self):
        """Create the tabbed interface."""
        
        style = ttk.Style()
        style.configure('Settings.TFrame', background='#f0f0f0')
        
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._build_presets_tab(notebook)
        self._build_sensor_tab(notebook)
        self._build_hardware_tab(notebook)
        self._build_scales_tab(notebook)
        self._build_paths_tab(notebook)

        self._build_button_frame()

    def _build_presets_tab(self, notebook):
        """Tab with preset configurations."""
        tab = ttk.Frame(notebook, padding=15)
        notebook.add(tab, text="Presets")

        ttk.Label(tab, text="Quick Configuration Presets", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(0, 10))

        preset_frame = ttk.Frame(tab)
        preset_frame.pack(fill=tk.X, pady=10)

        ttk.Label(preset_frame, text="Load Preset:").pack(side=tk.LEFT, padx=5)
        self._preset_var = tk.StringVar(value="Basic Setup")
        preset_combo = ttk.Combobox(preset_frame, textvariable=self._preset_var,
                                   values=list(PRESETS.keys()), state="readonly", width=20)
        preset_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(preset_frame, text="Apply", 
                  command=self._apply_preset).pack(side=tk.LEFT, padx=5)

        ttk.Separator(tab, orient='horizontal').pack(fill=tk.X, pady=10)

        info_frame = ttk.LabelFrame(tab, text="Preset Information", padding=10)
        info_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self._preset_info = tk.Text(info_frame, height=12, width=50, 
                                    state=tk.DISABLED, wrap=tk.WORD)
        self._preset_info.pack(fill=tk.BOTH, expand=True)

        self._update_preset_info()
        preset_combo.bind("<<ComboboxSelected>>", lambda e: self._update_preset_info())

        ttk.Separator(tab, orient='horizontal').pack(fill=tk.X, pady=10)

        ttk.Label(tab, text="Create Custom Preset", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(10, 5))

        save_frame = ttk.LabelFrame(tab, text="Save Current Settings as Preset", padding=10)
        save_frame.pack(fill=tk.X, pady=5)

        ttk.Label(save_frame, text="Preset Name:").pack(side=tk.LEFT, padx=5)
        self._custom_preset_var = tk.StringVar()
        ttk.Entry(save_frame, textvariable=self._custom_preset_var, width=25).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(save_frame, text="Save as Preset", 
                  command=self._save_custom_preset).pack(side=tk.LEFT, padx=5)

    def _update_preset_info(self):
        """Display current preset information."""
        preset_name = self._preset_var.get()
        preset = PRESETS.get(preset_name, {})
        
        info = f"Preset: {preset_name}\n\n"
        if preset:
            for key, value in preset.items():
                label = key.replace('_', ' ').title()
                info += f"  • {label}: {value}\n"
        
        self._preset_info.config(state=tk.NORMAL)
        self._preset_info.delete(1.0, tk.END)
        self._preset_info.insert(1.0, info)
        self._preset_info.config(state=tk.DISABLED)

    def _apply_preset(self):
        """Apply selected preset to current settings."""
        preset_name = self._preset_var.get()
        preset = PRESETS.get(preset_name)
        if not preset:
            return

        for key, value in preset.items():
            if hasattr(self, f'_{key}_var'):
                var = getattr(self, f'_{key}_var')
                var.set(str(value))

        messagebox.showinfo("Preset Applied", 
                           f"Preset '{preset_name}' has been applied.", parent=self)

    def _save_custom_preset(self):
        """Save current settings as a new custom preset."""
        preset_name = self._custom_preset_var.get().strip()
        if not preset_name:
            messagebox.showwarning("Empty Name", 
                                  "Please enter a preset name.", parent=self)
            return

        preset_data = {
            "tc_count": int(self._tc_count_var.get()),
            "tc_type": self._tc_type_var.get(),
            "tc_unit": self._tc_unit_var.get(),
            "frg_count": int(self._frg_count_var.get()),
            "p_unit": self._p_unit_var.get(),
            "sample_rate_ms": int(self._sample_rate_ms_var.get()),
            "display_rate_ms": int(self._display_rate_ms_var.get()),
        }

        PRESETS[preset_name] = preset_data
        self._custom_preset_var.set("")

        messagebox.showinfo("Preset Saved", 
                           f"Preset '{preset_name}' has been saved.", parent=self)

    def _build_sensor_tab(self, notebook):
        """Tab for sensor configuration."""
        tab = ttk.Frame(notebook, padding=15)
        notebook.add(tab, text="Sensors")

        ttk.Label(tab, text="Thermocouple Configuration", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(0, 10))

        tc_frame = ttk.LabelFrame(tab, text="Thermocouple", padding=10)
        tc_frame.pack(fill=tk.X, pady=5)

        self._create_option_row(tc_frame, "Count:", "tc_count", 
                               ["0", "1", "2", "3", "4", "5", "6", "7"], row=0)
        self._create_option_row(tc_frame, "Type:", "tc_type", 
                               ["K", "J", "T", "E", "R", "S", "B", "N", "C"], row=1)
        self._create_option_row(tc_frame, "Unit:", "tc_unit", 
                               ["C", "F", "K"], row=2)

        ttk.Label(tab, text="FRG702 Gauge Configuration", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 10))

        frg_frame = ttk.LabelFrame(tab, text="FRG702", padding=10)
        frg_frame.pack(fill=tk.X, pady=5)

        self._create_option_row(frg_frame, "Count:", "frg_count", 
                               ["0", "1", "2"], row=0)
        self._create_option_row(frg_frame, "Pressure Unit:", "p_unit", 
                               ["mbar", "Torr", "Pa"], row=1)

    def _build_hardware_tab(self, notebook):
        """Tab for hardware-specific settings."""
        tab = ttk.Frame(notebook, padding=15)
        notebook.add(tab, text="Hardware")

        ttk.Label(tab, text="Data Acquisition", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(0, 10))

        acq_frame = ttk.LabelFrame(tab, text="Sampling Rates", padding=10)
        acq_frame.pack(fill=tk.X, pady=5)

        self._create_option_row(acq_frame, "Sample Rate (ms):", "sample_rate_ms",
                               ["100", "200", "500", "1000", "2000"], row=0)
        self._create_option_row(acq_frame, "Display Rate (ms):", "display_rate_ms",
                               ["100", "250", "500", "1000"], row=1)

        ttk.Label(tab, text="XGS600 Controller", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 10))

        xgs_frame = ttk.LabelFrame(tab, text="XGS600 Settings", padding=10)
        xgs_frame.pack(fill=tk.X, pady=5)

        self._create_entry_row(xgs_frame, "COM Port:", "xgs600_port", width=15, row=0)
        self._create_entry_row(xgs_frame, "Baudrate:", "xgs600_baudrate", width=15, row=1)
        self._create_entry_row(xgs_frame, "Timeout (s):", "xgs600_timeout", width=15, row=2)
        self._create_entry_row(xgs_frame, "Address:", "xgs600_address", width=15, row=3)

        ttk.Label(tab, text="Turbo Pump", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 10))

        pump_frame = ttk.LabelFrame(tab, text="Turbo Pump Settings", padding=10)
        pump_frame.pack(fill=tk.X, pady=5)

        self._create_bool_row(pump_frame, "Enabled:", "turbo_pump_enabled", row=0)
        self._create_entry_row(pump_frame, "Start Delay (ms):", "turbo_pump_start_delay_ms", 
                              width=15, row=1)
        self._create_entry_row(pump_frame, "Stop Delay (ms):", "turbo_pump_stop_delay_ms", 
                              width=15, row=2)
        self._create_entry_row(pump_frame, "Min Restart Delay (s):", 
                              "turbo_pump_min_restart_delay_s", width=15, row=3)

    def _build_scales_tab(self, notebook):
        """Tab for axis scale configuration."""
        tab = ttk.Frame(notebook, padding=15)
        notebook.add(tab, text="Axis Scales")

        ttk.Label(tab, text="Plot Axis Ranges", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(0, 10))

        abs_frame = ttk.Frame(tab)
        abs_frame.pack(fill=tk.X, pady=10)

        self._abs_scale_var = tk.BooleanVar()
        ttk.Checkbutton(abs_frame, text="Use Absolute Scales",
                       variable=self._abs_scale_var).pack(anchor='w')

        ttk.Label(tab, text="Temperature", 
                 font=('Arial', 10, 'bold')).pack(anchor='w', pady=(15, 10))

        temp_frame = ttk.LabelFrame(tab, padding=10)
        temp_frame.pack(fill=tk.X, pady=5)

        self._temp_min_var = tk.StringVar()
        self._temp_max_var = tk.StringVar()
        self._create_entry_row(temp_frame, "Min (°C):", None, width=20, row=0, 
                              var=self._temp_min_var)
        self._create_entry_row(temp_frame, "Max (°C):", None, width=20, row=1, 
                              var=self._temp_max_var)

        ttk.Label(tab, text="Pressure", 
                 font=('Arial', 10, 'bold')).pack(anchor='w', pady=(15, 10))

        press_frame = ttk.LabelFrame(tab, padding=10)
        press_frame.pack(fill=tk.X, pady=5)

        self._press_min_var = tk.StringVar()
        self._press_max_var = tk.StringVar()
        self._create_entry_row(press_frame, "Min:", None, width=20, row=0, 
                              var=self._press_min_var)
        self._create_entry_row(press_frame, "Max:", None, width=20, row=1, 
                              var=self._press_max_var)

        ttk.Label(tab, text="Power Supply", 
                 font=('Arial', 10, 'bold')).pack(anchor='w', pady=(15, 10))

        ps_frame = ttk.LabelFrame(tab, padding=10)
        ps_frame.pack(fill=tk.X, pady=5)

        self._psv_min_var = tk.StringVar()
        self._psv_max_var = tk.StringVar()
        self._psi_min_var = tk.StringVar()
        self._psi_max_var = tk.StringVar()

        self._create_entry_row(ps_frame, "Voltage Min (V):", None, width=20, row=0, 
                              var=self._psv_min_var)
        self._create_entry_row(ps_frame, "Voltage Max (V):", None, width=20, row=1, 
                              var=self._psv_max_var)
        self._create_entry_row(ps_frame, "Current Min (A):", None, width=20, row=2, 
                              var=self._psi_min_var)
        self._create_entry_row(ps_frame, "Current Max (A):", None, width=20, row=3, 
                              var=self._psi_max_var)

        self._create_entry_row(ps_frame, "Voltage Limit (V):", "ps_voltage_limit", 
                              width=20, row=4)
        self._create_entry_row(ps_frame, "Current Limit (A):", "ps_current_limit", 
                              width=20, row=5)

    def _build_paths_tab(self, notebook):
        """Tab for file paths and resource configuration."""
        tab = ttk.Frame(notebook, padding=15)
        notebook.add(tab, text="Paths & Resources")

        ttk.Label(tab, text="Hardware & File Configuration", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(0, 10))

        hw_frame = ttk.LabelFrame(tab, text="VISA Resource", padding=10)
        hw_frame.pack(fill=tk.X, pady=5)

        ttk.Label(hw_frame, text="Power Supply VISA:").pack(anchor='w', pady=(5, 2))
        self._visa_var = tk.StringVar()
        ttk.Entry(hw_frame, textvariable=self._visa_var, width=45).pack(fill=tk.X, pady=5)

        ttk.Label(tab, text="Logging", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 10))

        log_frame = ttk.LabelFrame(tab, text="Log Folder", padding=10)
        log_frame.pack(fill=tk.X, pady=5)

        log_input_frame = ttk.Frame(log_frame)
        log_input_frame.pack(fill=tk.X, pady=5)

        self._log_folder_var = tk.StringVar()
        ttk.Entry(log_input_frame, textvariable=self._log_folder_var, 
                 width=35).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(log_input_frame, text="Browse…",
                  command=self._browse_log_folder).pack(side=tk.LEFT, padx=5)

    def _create_option_row(self, parent, label, var_name, values, row):
        """Helper to create a label + combobox row."""
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=5, pady=5)
        
        if var_name:
            var = tk.StringVar()
            setattr(self, f'_{var_name}_var', var)
        else:
            var = None
        
        combo = ttk.Combobox(parent, textvariable=var, values=values, 
                            state='readonly', width=20)
        combo.grid(row=row, column=1, sticky='ew', padx=5, pady=5)
        parent.columnconfigure(1, weight=1)

    def _create_entry_row(self, parent, label, var_name, width=20, row=0, var=None):
        """Helper to create a label + entry row."""
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=5, pady=5)
        
        if var is None:
            var = tk.StringVar()
            if var_name:
                setattr(self, f'_{var_name}_var', var)
        
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.grid(row=row, column=1, sticky='ew', padx=5, pady=5)
        parent.columnconfigure(1, weight=1)

    def _create_bool_row(self, parent, label, var_name, row):
        """Helper to create a label + checkbox row."""
        var = tk.BooleanVar()
        setattr(self, f'_{var_name}_var', var)
        ttk.Checkbutton(parent, text=label, variable=var).grid(
            row=row, column=0, columnspan=2, sticky='w', padx=5, pady=5)

    def _build_button_frame(self):
        """Create Save/Cancel buttons at the bottom."""
        btn_frame = ttk.Frame(self)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="Save", command=self._on_save_click,
                  width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy,
                  width=15).pack(side=tk.LEFT, padx=5)

    def _load_values(self):
        """Populate widgets from AppSettings."""
        s = self._settings
        
        self._tc_count_var.set(str(s.tc_count))
        self._tc_type_var.set(s.tc_type)
        self._tc_unit_var.set(s.tc_unit)
        self._frg_count_var.set(str(s.frg_count))
        self._p_unit_var.set(s.p_unit)
        self._sample_rate_ms_var.set(str(s.sample_rate_ms))
        self._display_rate_ms_var.set(str(s.display_rate_ms))
        self._xgs600_port_var.set(s.xgs600_port)
        self._xgs600_baudrate_var.set(str(s.xgs600_baudrate))
        self._xgs600_timeout_var.set(str(s.xgs600_timeout))
        self._xgs600_address_var.set(s.xgs600_address)
        self._turbo_pump_enabled_var.set(s.turbo_pump_enabled)
        self._turbo_pump_start_delay_ms_var.set(str(s.turbo_pump_start_delay_ms))
        self._turbo_pump_stop_delay_ms_var.set(str(s.turbo_pump_stop_delay_ms))
        self._turbo_pump_min_restart_delay_s_var.set(str(s.turbo_pump_min_restart_delay_s))
        self._abs_scale_var.set(s.use_absolute_scales)
        self._temp_min_var.set(str(s.temp_range_min))
        self._temp_max_var.set(str(s.temp_range_max))
        self._press_min_var.set(repr(s.press_range_min))
        self._press_max_var.set(repr(s.press_range_max))
        self._psv_min_var.set(str(s.ps_v_range_min))
        self._psv_max_var.set(str(s.ps_v_range_max))
        self._psi_min_var.set(str(s.ps_i_range_min))
        self._psi_max_var.set(str(s.ps_i_range_max))
        self._ps_voltage_limit_var.set(str(s.ps_voltage_limit))
        self._ps_current_limit_var.set(str(s.ps_current_limit))
        self._visa_var.set(s.visa_resource)
        self._log_folder_var.set(s.log_folder)

    def _on_save_click(self):
        """Validate and save all settings."""
        s = self._settings
        try:
            s.tc_count = int(self._tc_count_var.get())
            s.tc_type = self._tc_type_var.get()
            s.tc_unit = self._tc_unit_var.get()
            s.frg_count = int(self._frg_count_var.get())
            s.p_unit = self._p_unit_var.get()
            s.sample_rate_ms = int(self._sample_rate_ms_var.get())
            s.display_rate_ms = int(self._display_rate_ms_var.get())
            s.xgs600_port = self._xgs600_port_var.get().strip()
            s.xgs600_baudrate = int(self._xgs600_baudrate_var.get())
            s.xgs600_timeout = float(self._xgs600_timeout_var.get())
            s.xgs600_address = self._xgs600_address_var.get().strip()
            s.turbo_pump_enabled = self._turbo_pump_enabled_var.get()
            s.turbo_pump_start_delay_ms = int(self._turbo_pump_start_delay_ms_var.get())
            s.turbo_pump_stop_delay_ms = int(self._turbo_pump_stop_delay_ms_var.get())
            s.turbo_pump_min_restart_delay_s = int(self._turbo_pump_min_restart_delay_s_var.get())
            s.use_absolute_scales = self._abs_scale_var.get()
            s.temp_range_min = float(self._temp_min_var.get())
            s.temp_range_max = float(self._temp_max_var.get())
            s.press_range_min = float(self._press_min_var.get())
            s.press_range_max = float(self._press_max_var.get())
            s.ps_v_range_min = float(self._psv_min_var.get())
            s.ps_v_range_max = float(self._psv_max_var.get())
            s.ps_i_range_min = float(self._psi_min_var.get())
            s.ps_i_range_max = float(self._psi_max_var.get())
            s.ps_voltage_limit = float(self._ps_voltage_limit_var.get())
            s.ps_current_limit = float(self._ps_current_limit_var.get())
            s.visa_resource = self._visa_var.get().strip()
            s.log_folder = self._log_folder_var.get().strip()
        except ValueError as exc:
            messagebox.showerror("Invalid Value", 
                                f"Please check your entries:\n{exc}", parent=self)
            return

        s.save()
        self._result_saved = True

        if callable(self._on_save):
            try:
                self._on_save()
            except Exception:
                pass

        self.destroy()

    def _browse_log_folder(self):
        """Open folder browser dialog."""
        folder = filedialog.askdirectory(
            parent=self,
            title="Select Log Folder",
            initialdir=self._log_folder_var.get() or "."
        )
        if folder:
            self._log_folder_var.set(folder)

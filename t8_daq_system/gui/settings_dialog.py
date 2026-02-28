"""
settings_dialog.py
PURPOSE: Settings dialog window for configuring persistent application settings.

Opened via the Settings button in the main control panel.  Features a tabbed
interface with sensor configuration, hardware settings, and axis scales.
All fields map directly to AppSettings attributes.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser


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
        self.geometry("500x900")
        self.minsize(500, 900)
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

        self._build_sensor_tab(notebook)
        self._build_hardware_tab(notebook)
        self._build_scales_tab(notebook)
        self._build_paths_tab(notebook)
        self._build_power_programmer_tab(notebook)

        self._build_button_frame()

    def _build_power_programmer_tab(self, notebook):
        """Tab for Power Programmer settings."""
        tab = ttk.Frame(notebook, padding=15)
        notebook.add(tab, text="Power Programmer")

        ttk.Label(tab, text="Power Programmer Configuration",
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(0, 10))

        # Profiles Folder
        folder_frame = ttk.LabelFrame(tab, text="Profiles Storage", padding=10)
        folder_frame.pack(fill=tk.X, pady=5)

        input_frame = ttk.Frame(folder_frame)
        input_frame.pack(fill=tk.X, pady=5)

        self._pp_profiles_folder_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self._pp_profiles_folder_var,
                 width=35).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(input_frame, text="Browse…",
                  command=self._browse_pp_profiles_folder).pack(side=tk.LEFT, padx=5)

        # Default Values
        defaults_frame = ttk.LabelFrame(tab, text="Default Ramp Parameters", padding=10)
        defaults_frame.pack(fill=tk.X, pady=5)

        self._create_entry_row(defaults_frame, "Default Duration (s):", "pp_default_ramp_duration", 
                              width=15, row=0)
        self._create_entry_row(defaults_frame, "Default Start Voltage (V):", "pp_default_start_v", 
                              width=15, row=1)
        self._create_entry_row(defaults_frame, "Default Start Current (A):", "pp_default_start_a", 
                              width=15, row=2)

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
        self._create_option_row(tc_frame, "Unit:", "tc_unit",
                               ["C", "F", "K"], row=1)

        # Rebuild per-TC type/pin rows whenever the count changes
        self._tc_type_vars = []
        self._tc_pin_vars  = []
        self._tc_count_var.trace_add('write', lambda *_: self._on_tc_count_change())

        self._tc_types_frame = ttk.LabelFrame(tab, text="Thermocouple Types", padding=10)
        self._tc_types_frame.pack(fill=tk.X, pady=5)

        ttk.Label(tab, text="FRG702 Gauge Configuration", 
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 10))

        frg_frame = ttk.LabelFrame(tab, text="FRG702", padding=10)
        frg_frame.pack(fill=tk.X, pady=5)

        self._create_option_row(frg_frame, "Count:", "frg_count", 
                               ["0", "1", "2"], row=0)
        self._create_option_row(frg_frame, "Pressure Unit:", "p_unit", 
                               ["mbar", "Torr", "Pa"], row=1)
        self._create_option_row(frg_frame, "Interface:", "frg_interface",
                               ["XGS600", "Analog"], row=2)
        self._create_entry_row(frg_frame, "AIN Pins (CSV):", "frg_pins", 
                               width=15, row=3)

    _TC_TYPE_VALUES = ["K", "J", "T", "E", "R", "S", "B", "N", "C"]
    _AIN_PIN_VALUES = ["0", "1", "2", "3", "4", "5", "6", "7"]

    def _on_tc_count_change(self):
        """Called when the TC count combobox value changes."""
        try:
            count = int(self._tc_count_var.get())
        except ValueError:
            return
        self._rebuild_tc_type_rows(count)

    def _rebuild_tc_type_rows(self, count):
        """Destroy and recreate the per-TC type and pin rows for *count* thermocouples."""
        existing_types = [v.get() for v in self._tc_type_vars]
        existing_pins  = [v.get() for v in self._tc_pin_vars]
        for w in self._tc_types_frame.winfo_children():
            w.destroy()
        self._tc_type_vars = []
        self._tc_pin_vars  = []
        if count == 0:
            ttk.Label(self._tc_types_frame,
                      text="No thermocouples configured").pack(anchor='w')
            return

        # Column headers
        hdr = ttk.Frame(self._tc_types_frame)
        hdr.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(hdr, text="",        width=6).pack(side=tk.LEFT, padx=5)
        ttk.Label(hdr, text="Type",    width=7, font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=5)
        ttk.Label(hdr, text="AIN Pin", width=8, font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=5)

        for i in range(count):
            default_type = existing_types[i] if i < len(existing_types) else self._settings.tc_type
            default_pin  = existing_pins[i]  if i < len(existing_pins)  else str(i)

            type_var = tk.StringVar(value=default_type)
            pin_var  = tk.StringVar(value=default_pin)
            self._tc_type_vars.append(type_var)
            self._tc_pin_vars.append(pin_var)

            row_f = ttk.Frame(self._tc_types_frame)
            row_f.pack(fill=tk.X, pady=2)
            ttk.Label(row_f, text=f"TC {i + 1}:", width=6).pack(side=tk.LEFT, padx=5)
            ttk.Combobox(row_f, textvariable=type_var, values=self._TC_TYPE_VALUES,
                         state='readonly', width=5).pack(side=tk.LEFT, padx=5)
            ttk.Combobox(row_f, textvariable=pin_var, values=self._AIN_PIN_VALUES,
                         state='readonly', width=4).pack(side=tk.LEFT, padx=5)

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

        ttk.Label(tab, text="Hardware Enable",
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 10))

        enable_frame = ttk.LabelFrame(tab, text="Device Enable/Disable", padding=10)
        enable_frame.pack(fill=tk.X, pady=5)

        self._ps_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(enable_frame, text="Enable Keysight Power Supply",
                        variable=self._ps_enabled_var).pack(anchor='w', padx=5, pady=4)

        self._xgs_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(enable_frame, text="Enable XGS-600 Gauge Controller",
                        variable=self._xgs_enabled_var).pack(anchor='w', padx=5, pady=4)

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
        """Tab for axis scale and appearance configuration (scrollable)."""
        tab = ttk.Frame(notebook, padding=0)
        notebook.add(tab, text='Appearance')

        # Scrollable canvas
        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = ttk.Frame(canvas, padding=10)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox('all'))
        inner.bind('<Configure>', _on_frame_configure)

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind('<Configure>', _on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', _on_mousewheel)

        # ── Global axis mode ─────────────────────────────────────────────
        self._abs_scale_var = tk.BooleanVar()
        ttk.Checkbutton(inner, text='Use Absolute Y-Axis Scales (uncheck = auto-scale)',
                       variable=self._abs_scale_var).pack(anchor='w', pady=(0, 10))

        # ── Build three sections ─────────────────────────────────────────
        # Initialize appearance variable holders before building sections
        self._tc_color_vars = []
        self._tc_color_btns = []
        self._tc_style_vars = []
        self._tc_width_vars = []
        self._press_color_vars = []
        self._press_color_btns = []
        self._press_style_vars = []
        self._press_width_vars = []
        self._ps_v_color_var = '#d62728'
        self._ps_i_color_var = '#ff7f0e'
        self._ps_v_style_var = tk.StringVar(value='solid')
        self._ps_i_style_var = tk.StringVar(value='solid')
        self._ps_v_width_var = tk.StringVar(value='2')
        self._ps_i_width_var = tk.StringVar(value='2')

        self._build_tc_appearance_section(inner)
        self._build_pressure_appearance_section(inner)
        self._build_ps_appearance_section(inner)

    _STYLE_CHOICES = ['solid', 'dashed', 'dotted', 'dashdot']

    def _make_color_picker_btn(self, parent, initial_color, on_color_chosen):
        """Create a color picker button that shows the selected color as its background."""
        btn = tk.Button(parent, text='  ', bg=initial_color, width=4, relief='raised',
                        cursor='hand2')

        def _pick():
            result = colorchooser.askcolor(color=btn['bg'], parent=self)
            if result and result[1]:
                new_color = result[1]
                btn.configure(bg=new_color)
                on_color_chosen(new_color)

        btn.configure(command=_pick)
        return btn

    def _build_tc_appearance_section(self, parent):
        """Build the Temperatures Plot section inside the Appearance tab."""
        self._temp_min_var = tk.StringVar()
        self._temp_max_var = tk.StringVar()

        frame = ttk.LabelFrame(parent, text='Temperatures Plot', padding=8)
        frame.pack(fill=tk.X, pady=5)

        axis_frame = ttk.Frame(frame)
        axis_frame.pack(fill=tk.X, pady=(0, 5))
        self._create_entry_row(axis_frame, 'Temp Min (°C):', None, width=15, row=0,
                               var=self._temp_min_var)
        self._create_entry_row(axis_frame, 'Temp Max (°C):', None, width=15, row=1,
                               var=self._temp_max_var)

        ttk.Label(frame, text='Per-Channel Appearance',
                  font=('Arial', 9, 'bold')).pack(anchor='w', pady=(5, 2))

        hdr = ttk.Frame(frame)
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text='Channel', width=9, font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Color',   width=6, font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Style',   width=9, font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Width',   width=6, font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)

        tc_count = self._settings.tc_count
        default_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
                          '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']

        self._tc_color_vars = []
        self._tc_color_btns = []
        self._tc_style_vars = []
        self._tc_width_vars = []

        for i in range(tc_count):
            color = default_colors[i % len(default_colors)]
            style_var = tk.StringVar(value='solid')
            width_var = tk.StringVar(value='2')
            self._tc_color_vars.append(color)
            self._tc_style_vars.append(style_var)
            self._tc_width_vars.append(width_var)

            row = ttk.Frame(frame)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=f'TC_{i+1}', width=9).pack(side=tk.LEFT, padx=4)

            idx = i  # capture for closure

            def _make_color_setter(idx_):
                def _set(c):
                    self._tc_color_vars[idx_] = c
                return _set

            btn = self._make_color_picker_btn(row, color, _make_color_setter(idx))
            btn.pack(side=tk.LEFT, padx=4)
            self._tc_color_btns.append(btn)

            ttk.Combobox(row, textvariable=style_var, values=self._STYLE_CHOICES,
                         state='readonly', width=9).pack(side=tk.LEFT, padx=4)
            ttk.Spinbox(row, textvariable=width_var, from_=1, to=4, width=4).pack(
                side=tk.LEFT, padx=4)

    def _build_pressure_appearance_section(self, parent):
        """Build the Pressures Plot section inside the Appearance tab."""
        self._press_min_var = tk.StringVar()
        self._press_max_var = tk.StringVar()

        frame = ttk.LabelFrame(parent, text='Pressures Plot', padding=8)
        frame.pack(fill=tk.X, pady=5)

        axis_frame = ttk.Frame(frame)
        axis_frame.pack(fill=tk.X, pady=(0, 5))
        self._create_entry_row(axis_frame, 'Press Min:', None, width=15, row=0,
                               var=self._press_min_var)
        self._create_entry_row(axis_frame, 'Press Max:', None, width=15, row=1,
                               var=self._press_max_var)

        ttk.Label(frame, text='Per-Gauge Appearance',
                  font=('Arial', 9, 'bold')).pack(anchor='w', pady=(5, 2))

        hdr = ttk.Frame(frame)
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text='Gauge',  width=9, font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Color',  width=6, font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Style',  width=9, font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Width',  width=6, font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)

        frg_count = self._settings.frg_count
        default_colors = ['#17becf', '#bcbd22', '#7f7f7f', '#e377c2']

        self._press_color_vars = []
        self._press_color_btns = []
        self._press_style_vars = []
        self._press_width_vars = []

        for i in range(frg_count):
            color = default_colors[i % len(default_colors)]
            style_var = tk.StringVar(value='solid')
            width_var = tk.StringVar(value='2')
            self._press_color_vars.append(color)
            self._press_style_vars.append(style_var)
            self._press_width_vars.append(width_var)

            row = ttk.Frame(frame)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=f'FRG_{i+1}', width=9).pack(side=tk.LEFT, padx=4)

            idx = i

            def _make_press_color_setter(idx_):
                def _set(c):
                    self._press_color_vars[idx_] = c
                return _set

            btn = self._make_color_picker_btn(row, color, _make_press_color_setter(idx))
            btn.pack(side=tk.LEFT, padx=4)
            self._press_color_btns.append(btn)

            ttk.Combobox(row, textvariable=style_var, values=self._STYLE_CHOICES,
                         state='readonly', width=9).pack(side=tk.LEFT, padx=4)
            ttk.Spinbox(row, textvariable=width_var, from_=1, to=4, width=4).pack(
                side=tk.LEFT, padx=4)

    def _build_ps_appearance_section(self, parent):
        """Build the Power Supply Plot section inside the Appearance tab."""
        self._psv_min_var = tk.StringVar()
        self._psv_max_var = tk.StringVar()
        self._psi_min_var = tk.StringVar()
        self._psi_max_var = tk.StringVar()

        frame = ttk.LabelFrame(parent, text='Power Supply Plot', padding=8)
        frame.pack(fill=tk.X, pady=5)

        axis_frame = ttk.Frame(frame)
        axis_frame.pack(fill=tk.X, pady=(0, 5))
        self._create_entry_row(axis_frame, 'Voltage Min (V):', None, width=15, row=0,
                               var=self._psv_min_var)
        self._create_entry_row(axis_frame, 'Voltage Max (V):', None, width=15, row=1,
                               var=self._psv_max_var)
        self._create_entry_row(axis_frame, 'Current Min (A):', None, width=15, row=2,
                               var=self._psi_min_var)
        self._create_entry_row(axis_frame, 'Current Max (A):', None, width=15, row=3,
                               var=self._psi_max_var)

        ttk.Label(frame, text='Line Appearance',
                  font=('Arial', 9, 'bold')).pack(anchor='w', pady=(5, 2))

        hdr = ttk.Frame(frame)
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text='Signal',   width=11, font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Color',    width=6,  font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Style',    width=9,  font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Width',    width=6,  font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)

        # PS Voltage row
        v_row = ttk.Frame(frame)
        v_row.pack(fill=tk.X, pady=1)
        ttk.Label(v_row, text='PS Voltage', width=11).pack(side=tk.LEFT, padx=4)

        def _set_v_color(c):
            self._ps_v_color_var = c

        self._ps_v_color_btn = self._make_color_picker_btn(v_row, self._ps_v_color_var, _set_v_color)
        self._ps_v_color_btn.pack(side=tk.LEFT, padx=4)
        ttk.Combobox(v_row, textvariable=self._ps_v_style_var, values=self._STYLE_CHOICES,
                     state='readonly', width=9).pack(side=tk.LEFT, padx=4)
        ttk.Spinbox(v_row, textvariable=self._ps_v_width_var, from_=1, to=4, width=4).pack(
            side=tk.LEFT, padx=4)

        # PS Current row
        i_row = ttk.Frame(frame)
        i_row.pack(fill=tk.X, pady=1)
        ttk.Label(i_row, text='PS Current', width=11).pack(side=tk.LEFT, padx=4)

        def _set_i_color(c):
            self._ps_i_color_var = c

        self._ps_i_color_btn = self._make_color_picker_btn(i_row, self._ps_i_color_var, _set_i_color)
        self._ps_i_color_btn.pack(side=tk.LEFT, padx=4)
        ttk.Combobox(i_row, textvariable=self._ps_i_style_var, values=self._STYLE_CHOICES,
                     state='readonly', width=9).pack(side=tk.LEFT, padx=4)
        ttk.Spinbox(i_row, textvariable=self._ps_i_width_var, from_=1, to=4, width=4).pack(
            side=tk.LEFT, padx=4)

        # Safety limits at bottom
        ttk.Separator(frame, orient='horizontal').pack(fill=tk.X, pady=6)
        limit_frame = ttk.Frame(frame)
        limit_frame.pack(fill=tk.X)
        self._create_entry_row(limit_frame, 'Voltage Limit (V):', 'ps_voltage_limit', width=15, row=0)
        self._create_entry_row(limit_frame, 'Current Limit (A):', 'ps_current_limit', width=15, row=1)

    def _build_paths_tab(self, notebook):
        """Tab for file paths and power supply configuration."""
        tab = ttk.Frame(notebook, padding=15)
        notebook.add(tab, text="Paths & Resources")

        ttk.Label(tab, text="Keysight N5700 — Analog Connection",
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(0, 10))

        ps_int_frame = ttk.LabelFrame(tab, text="Power Supply (J1 DB25 → Phoenix Contact → T8)", padding=10)
        ps_int_frame.pack(fill=tk.X, pady=5)

        ttk.Label(ps_int_frame,
                  text="Physical wiring: J1 DB25 → Phoenix Contact breakout → T8 screw terminals",
                  font=('Arial', 8), foreground='#555555').grid(
                  row=0, column=0, columnspan=2, sticky='w', padx=5, pady=(0, 6))

        _AIN_OPTS = [f"AIN{i}" for i in range(8)]
        _DAC_OPTS = ["DAC0", "DAC1"]
        self._create_option_row(ps_int_frame, "Voltage Prog (DAC):", "ps_voltage_pin",
                               _DAC_OPTS, row=1)
        self._create_option_row(ps_int_frame, "Current Prog (DAC):", "ps_current_pin",
                               _DAC_OPTS, row=2)
        self._create_option_row(ps_int_frame, "Voltage Mon (AIN):", "ps_voltage_monitor_pin",
                               _AIN_OPTS, row=3)
        self._create_option_row(ps_int_frame, "Current Mon (AIN):", "ps_current_monitor_pin",
                               _AIN_OPTS, row=4)

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

        ttk.Label(tab, text="Startup Behaviour",
                 font=('Arial', 11, 'bold')).pack(anchor='w', pady=(15, 10))

        startup_frame = ttk.LabelFrame(tab, text="Pre-flight Check", padding=10)
        startup_frame.pack(fill=tk.X, pady=5)

        self._skip_preflight_check_var = tk.BooleanVar()
        ttk.Checkbutton(startup_frame,
                        text="Skip wiring pre-flight check on Start",
                        variable=self._skip_preflight_check_var).pack(anchor='w', padx=5, pady=5)

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
        """Create Save/Cancel/Apply buttons at the bottom."""
        btn_frame = ttk.Frame(self)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

        # Pack from right to left so they appear in the bottom right corner
        ttk.Button(btn_frame, text="Cancel", command=self.destroy,
                  width=12).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Save", command=self._on_save_click,
                  width=12).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Apply", command=self._on_apply_click,
                  width=12).pack(side=tk.RIGHT, padx=5)

    def _load_values(self):
        """Populate widgets from AppSettings."""
        s = self._settings

        self._tc_count_var.set(str(s.tc_count))
        self._tc_unit_var.set(s.tc_unit)
        # Build per-TC type+pin rows from stored values
        types = s.get_tc_type_list(s.tc_count)
        pins  = s.get_tc_pin_list(s.tc_count)
        self._rebuild_tc_type_rows(s.tc_count)
        for i, (type_var, pin_var) in enumerate(zip(self._tc_type_vars, self._tc_pin_vars)):
            type_var.set(types[i])
            pin_var.set(str(pins[i]))
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

        # ── Appearance: TC colors/styles/widths ───────────────────────────
        tc_colors  = [c.strip() for c in (s.tc_colors or '').split(',')]
        tc_styles  = [x.strip() for x in (s.tc_line_style or '').split(',')]
        tc_widths  = [x.strip() for x in (s.tc_line_width or '').split(',')]
        default_tc_colors = ['#1f77b4','#ff7f0e','#2ca02c','#d62728',
                              '#9467bd','#8c564b','#e377c2','#7f7f7f']
        for i, (svar, wvar) in enumerate(zip(self._tc_style_vars, self._tc_width_vars)):
            color = tc_colors[i] if i < len(tc_colors) else default_tc_colors[i % len(default_tc_colors)]
            style = tc_styles[i] if i < len(tc_styles) else 'solid'
            width = tc_widths[i] if i < len(tc_widths) else '2'
            self._tc_color_vars[i] = color
            if i < len(self._tc_color_btns):
                try:
                    self._tc_color_btns[i].configure(bg=color)
                except Exception:
                    pass
            svar.set(style)
            wvar.set(width)

        # ── Appearance: Pressure colors/styles/widths ─────────────────────
        press_colors = [c.strip() for c in (s.press_colors or '').split(',')]
        press_styles = [x.strip() for x in (s.press_line_style or '').split(',')]
        press_widths = [x.strip() for x in (s.press_line_width or '').split(',')]
        default_press_colors = ['#17becf','#bcbd22','#7f7f7f','#e377c2']
        for i, (svar, wvar) in enumerate(zip(self._press_style_vars, self._press_width_vars)):
            color = press_colors[i] if i < len(press_colors) else default_press_colors[i % len(default_press_colors)]
            style = press_styles[i] if i < len(press_styles) else 'solid'
            width = press_widths[i] if i < len(press_widths) else '2'
            self._press_color_vars[i] = color
            if i < len(self._press_color_btns):
                try:
                    self._press_color_btns[i].configure(bg=color)
                except Exception:
                    pass
            svar.set(style)
            wvar.set(width)

        # ── Appearance: PS colors/styles/widths ───────────────────────────
        self._ps_v_color_var = s.ps_voltage_color
        self._ps_i_color_var = s.ps_current_color
        try:
            self._ps_v_color_btn.configure(bg=s.ps_voltage_color)
            self._ps_i_color_btn.configure(bg=s.ps_current_color)
        except Exception:
            pass
        self._ps_v_style_var.set(s.ps_voltage_line_style)
        self._ps_i_style_var.set(s.ps_current_line_style)
        self._ps_v_width_var.set(s.ps_voltage_line_width)
        self._ps_i_width_var.set(s.ps_current_line_width)

        self._log_folder_var.set(s.log_folder)
        self._frg_interface_var.set(s.frg_interface)
        self._frg_pins_var.set(s.frg_pins)
        self._ps_voltage_pin_var.set(s.ps_voltage_pin)
        self._ps_current_pin_var.set(s.ps_current_pin)
        self._ps_voltage_monitor_pin_var.set(s.ps_voltage_monitor_pin)
        self._ps_current_monitor_pin_var.set(s.ps_current_monitor_pin)
        self._skip_preflight_check_var.set(s.skip_preflight_check)
        self._ps_enabled_var.set(s.ps_enabled)
        self._xgs_enabled_var.set(s.xgs_enabled)
        self._pp_profiles_folder_var.set(s.pp_profiles_folder)
        self._pp_default_ramp_duration_var.set(str(s.pp_default_ramp_duration))
        self._pp_default_start_v_var.set(str(s.pp_default_start_v))
        self._pp_default_start_a_var.set(str(s.pp_default_start_a))

    def _save_settings_from_gui(self):
        """Internal helper to read all GUI vars and write to AppSettings."""
        s = self._settings
        try:
            s.tc_count = int(self._tc_count_var.get())
            s.tc_types = ",".join(v.get() for v in self._tc_type_vars)
            s.tc_pins  = ",".join(v.get() for v in self._tc_pin_vars)
            s.tc_type = self._tc_type_vars[0].get() if self._tc_type_vars else s.tc_type
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

            # ── Appearance settings ───────────────────────────────────────
            s.tc_colors = ','.join(self._tc_color_vars)
            s.tc_line_style = ','.join(v.get() for v in self._tc_style_vars)
            s.tc_line_width = ','.join(v.get() for v in self._tc_width_vars)
            s.press_colors = ','.join(self._press_color_vars)
            s.press_line_style = ','.join(v.get() for v in self._press_style_vars)
            s.press_line_width = ','.join(v.get() for v in self._press_width_vars)
            s.ps_voltage_color = self._ps_v_color_var
            s.ps_current_color = self._ps_i_color_var
            s.ps_voltage_line_style = self._ps_v_style_var.get()
            s.ps_current_line_style = self._ps_i_style_var.get()
            s.ps_voltage_line_width = self._ps_v_width_var.get()
            s.ps_current_line_width = self._ps_i_width_var.get()

            s.log_folder = self._log_folder_var.get().strip()
            s.frg_interface = self._frg_interface_var.get()
            s.frg_pins = self._frg_pins_var.get().strip()
            s.ps_interface = "Analog"
            s.ps_voltage_pin = self._ps_voltage_pin_var.get().strip()
            s.ps_current_pin = self._ps_current_pin_var.get().strip()
            s.ps_voltage_monitor_pin = self._ps_voltage_monitor_pin_var.get().strip()
            s.ps_current_monitor_pin = self._ps_current_monitor_pin_var.get().strip()
            s.skip_preflight_check = self._skip_preflight_check_var.get()
            s.ps_enabled = self._ps_enabled_var.get()
            s.xgs_enabled = self._xgs_enabled_var.get()
            s.pp_profiles_folder = self._pp_profiles_folder_var.get().strip()
            s.pp_default_ramp_duration = int(self._pp_default_ramp_duration_var.get())
            s.pp_default_start_v = float(self._pp_default_start_v_var.get())
            s.pp_default_start_a = float(self._pp_default_start_a_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid Value",
                                f"Please check your entries:\n{exc}", parent=self)
            return False

        s.save()
        self._result_saved = True

        if callable(self._on_save):
            try:
                self._on_save()
            except Exception as e:
                print(f"Error in on_save_callback: {e}")
        return True

    def _on_save_click(self):
        """Validate and save all settings, then close."""
        if self._save_settings_from_gui():
            self.destroy()

    def _on_apply_click(self):
        """Validate and save settings without closing."""
        self._save_settings_from_gui()

    def _browse_pp_profiles_folder(self):
        """Open folder browser dialog for profiles."""
        folder = filedialog.askdirectory(
            parent=self,
            title="Select Profiles Folder",
            initialdir=self._pp_profiles_folder_var.get() or "."
        )
        if folder:
            self._pp_profiles_folder_var.set(folder)

    def _browse_log_folder(self):
        """Open folder browser dialog."""
        folder = filedialog.askdirectory(
            parent=self,
            title="Select Log Folder",
            initialdir=self._log_folder_var.get() or "."
        )
        if folder:
            self._log_folder_var.set(folder)

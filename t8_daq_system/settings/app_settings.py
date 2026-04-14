r"""
app_settings.py
PURPOSE: Persistent application settings stored in the Windows Registry.

All user-configurable values are persisted under:
    HKEY_CURRENT_USER\Software\T8_DAQ_System

No external JSON config files are used. On first launch (or if the registry
key has never been written) load() silently returns all defaults.
"""

import winreg

# Registry key path under HKCU
_REG_KEY = r"Software\T8_DAQ_System"

# ──────────────────────────────────────────────────────────────────────────────
# Defaults (used on first launch / missing keys)
# ──────────────────────────────────────────────────────────────────────────────
_DEFAULTS = {
    "tc_count":           ("int",   1),
    "tc_type":            ("str",   "C"),
    "tc_types":           ("str",   ""),
    "tc_pins":            ("str",   ""),
    "tc_unit":            ("str",   "C"),
    "frg_count":          ("int",   1),
    "p_unit":             ("str",   "mbar"),
    "sample_rate_ms":     ("int",   1000),
    "display_rate_ms":    ("int",   1000),
    "use_absolute_scales": ("bool", True),
    "temp_range_min":     ("float", 0.0),
    "temp_range_max":     ("float", 2500.0),
    "press_range_min":    ("float", 1e-9),
    "press_range_max":    ("float", 1e-3),
    "ps_v_range_min":     ("float", 0.0),
    "ps_v_range_max":     ("float", 6.0),
    "ps_i_range_min":     ("float", 0.0),
    "ps_i_range_max":     ("float", 180.0),
    "log_folder":         ("str",   ""),
    "xgs600_port":        ("str",   "COM4"),
    "xgs600_baudrate":    ("int",   9600),
    "xgs600_timeout":     ("float", 1.0),
    "xgs600_address":     ("str",   "00"),
    "turbo_pump_enabled": ("bool", True),
    "turbo_pump_start_delay_ms": ("int", 500),
    "turbo_pump_stop_delay_ms": ("int", 500),
    "turbo_pump_min_restart_delay_s": ("int", 30),
    "ps_voltage_limit":   ("float", 20.0),
    "ps_current_limit":   ("float", 50.0),
    "frg_interface":      ("str",   "XGS600"),
    "frg_pins":           ("str",   "AIN6,AIN7"),
    "ps_interface":       ("str",   "Analog"),
    "ps_voltage_pin":     ("str",   "DAC0"),
    "ps_current_pin":     ("str",   "DAC1"),
    "ps_voltage_monitor_pin": ("str", "AIN4"),
    "ps_current_monitor_pin": ("str", "AIN5"),
    "skip_preflight_check": ("bool", False),
    "ps_enabled":           ("bool", False),
    "xgs_enabled":          ("bool", False),
    "pp_profiles_folder":    ("str",   ""),
    "pp_default_ramp_duration": ("int", 60),
    "pp_default_start_v":    ("float", 0.0),
    "pp_default_current_a":  ("float", 180.0),
    # ── Appearance / Plot Style defaults ─────────────────────────────────
    # Custom sensor names (empty string = auto-generate from pin/type)
    "tc_names":             ("str", ""),
    "frg_names":            ("str", ""),
    # TC plot colors — one per channel, stored as comma-separated hex strings
    "tc_colors":            ("str", "#1f77b4,#ff7f0e,#2ca02c,#d62728,#9467bd,#8c564b,#e377c2,#7f7f7f"),
    "tc_line_style":        ("str", "solid,solid,solid,solid,solid,solid,solid,solid"),
    "tc_line_width":        ("str", "2,2,2,2,2,2,2,2"),
    # Pressure plot
    "press_colors":         ("str", "#17becf,#bcbd22,#7f7f7f,#e377c2"),
    "press_line_style":     ("str", "solid,solid,solid,solid"),
    "press_line_width":     ("str", "2,2,2,2"),
    # PS plot
    "ps_voltage_color":     ("str", "#d62728"),
    "ps_current_color":     ("str", "#ff7f0e"),
    "ps_voltage_line_style":("str", "solid"),
    "ps_current_line_style":("str", "solid"),
    "ps_voltage_line_width":("str", "2"),
    "ps_current_line_width":("str", "2"),
    # Power Programmer preview plot
    "pp_voltage_color":      ("str", "#1f77b4"),   # blue default
    "pp_voltage_line_style": ("str", "solid"),
    "pp_voltage_line_width": ("str", "2"),
    # ── Two-phase PID / Soft-Start settings ──────────────────────────────
    "soft_start_threshold_c":    ("float", 200.0),   # °C — phase switch point
    "soft_start_current_limit_a": ("float", 180.0),  # A — Phase 1 current ceiling
    "pid_kp":               ("float", 0.02),
    "pid_ki":               ("float", 0.0013),
    "pid_kd":               ("float", 0.005),
    "pid_windup_limit":     ("float", 0.4),
    "pid_output_max":       ("float", 6.0),
    # ── QMS Auto-Click settings ───────────────────────────────────────────
    "qms_auto_click_enabled": ("bool", False),
    "qms_auto_click_x":       ("int",  0),
    "qms_auto_click_y":       ("int",  0),
    # ── Logging behaviour ─────────────────────────────────────────────────
    "reset_graph_on_start_logging": ("bool", True),
}


class AppSettings:
    """
    Reads and writes all user-configurable settings to the Windows Registry.

    Usage
    -----
        settings = AppSettings()
        settings.load()           # Populate fields from registry (or defaults)
        settings.tc_count = 3     # Mutate a field
        settings.save()           # Persist all fields back to registry

    All fields are plain Python attributes; their types are enforced on save.
    """

    def __init__(self):
        # Populate with defaults first so the object is always fully initialised
        self.tc_count: int           = 1
        self.tc_type: str            = "C"
        self.tc_types: str           = ""
        self.tc_pins: str            = ""
        self.tc_unit: str            = "C"
        self.frg_count: int          = 1
        self.p_unit: str             = "mbar"
        self.sample_rate_ms: int     = 1000
        self.display_rate_ms: int    = 1000
        self.use_absolute_scales: bool = True
        self.temp_range_min: float   = 0.0
        self.temp_range_max: float   = 2500.0
        self.press_range_min: float  = 1e-9
        self.press_range_max: float  = 1e-3
        self.ps_v_range_min: float   = 0.0
        self.ps_v_range_max: float   = 6.0
        self.ps_i_range_min: float   = 0.0
        self.ps_i_range_max: float   = 180.0
        self.log_folder: str         = ""
        self.xgs600_port: str        = "COM4"
        self.xgs600_baudrate: int    = 9600
        self.xgs600_timeout: float   = 1.0
        self.xgs600_address: str     = "00"
        self.turbo_pump_enabled: bool = True
        self.turbo_pump_start_delay_ms: int = 500
        self.turbo_pump_stop_delay_ms: int = 500
        self.turbo_pump_min_restart_delay_s: int = 30
        self.ps_voltage_limit: float = 20.0
        self.ps_current_limit: float = 50.0
        self.frg_interface: str      = "XGS600"
        self.frg_pins: str           = "AIN6,AIN7"
        self.ps_interface: str       = "Analog"
        self.ps_voltage_pin: str     = "DAC0"
        self.ps_current_pin: str     = "DAC1"
        self.ps_voltage_monitor_pin: str = "AIN4"
        self.ps_current_monitor_pin: str = "AIN5"
        self.skip_preflight_check: bool = False
        self.ps_enabled: bool        = False
        self.xgs_enabled: bool       = False
        self.pp_profiles_folder: str = ""
        self.pp_default_ramp_duration: int = 60
        self.pp_default_start_v: float = 0.0
        self.pp_default_current_a: float = 180.0
        # Custom sensor names
        self.tc_names: str             = ""
        self.frg_names: str            = ""
        # Appearance / Plot Style
        self.tc_colors: str            = "#1f77b4,#ff7f0e,#2ca02c,#d62728,#9467bd,#8c564b,#e377c2,#7f7f7f"
        self.tc_line_style: str        = "solid,solid,solid,solid,solid,solid,solid,solid"
        self.tc_line_width: str        = "2,2,2,2,2,2,2,2"
        self.press_colors: str         = "#17becf,#bcbd22,#7f7f7f,#e377c2"
        self.press_line_style: str     = "solid,solid,solid,solid"
        self.press_line_width: str     = "2,2,2,2"
        self.ps_voltage_color: str     = "#d62728"
        self.ps_current_color: str     = "#ff7f0e"
        self.ps_voltage_line_style: str = "solid"
        self.ps_current_line_style: str = "solid"
        self.ps_voltage_line_width: str = "2"
        self.ps_current_line_width: str = "2"
        self.pp_voltage_color: str       = "#1f77b4"
        self.pp_voltage_line_style: str  = "solid"
        self.pp_voltage_line_width: str  = "2"
        # Two-phase PID / Soft-Start
        self.soft_start_threshold_c: float = 200.0   # °C — phase switch point
        self.soft_start_current_limit_a: float = 180.0  # A — Phase 1 current ceiling
        self.pid_kp: float = 0.02
        self.pid_ki: float = 0.0013
        self.pid_kd: float = 0.005
        self.pid_windup_limit: float = 0.4
        self.pid_output_max: float = 6.0
        # QMS Auto-Click
        self.qms_auto_click_enabled: bool = False
        self.qms_auto_click_x: int = 0
        self.qms_auto_click_y: int = 0
        # Logging behaviour
        self.reset_graph_on_start_logging: bool = True

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def load(self) -> "AppSettings":
        """
        Load settings from the registry.

        Silently returns defaults for any key that is missing (e.g. first
        launch).  Never raises — the caller always gets a fully populated
        object.
        """
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY)
        except FileNotFoundError:
            # Key doesn't exist yet — keep defaults, return self
            return self
        except OSError:
            # Registry unavailable (non-Windows environment, permissions) — keep defaults
            return self

        try:
            for field, (kind, default) in _DEFAULTS.items():
                try:
                    raw_value, _ = winreg.QueryValueEx(key, field)
                    val = _coerce(raw_value, kind, default)
                    setattr(self, field, val)
                    pass  # field loaded successfully
                except (FileNotFoundError, OSError):
                    # Individual value missing — keep default
                    pass
        finally:
            winreg.CloseKey(key)

        return self

    def save(self) -> None:
        """
        Write all settings atomically to the registry.

        Creates the registry key if it does not exist.
        Silently swallows any OS-level errors (e.g. non-Windows, permissions).
        """
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REG_KEY)
        except OSError:
            return  # Registry unavailable — fail silently

        try:
            for field, (kind, _default) in _DEFAULTS.items():
                value = getattr(self, field, _default)
                _write_value(key, field, value, kind)
        finally:
            winreg.CloseKey(key)

    # ──────────────────────────────────────────────────────────────────────────
    # Convenience helpers
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def temp_range(self):
        """Return temperature range as a (min, max) tuple."""
        return (self.temp_range_min, self.temp_range_max)

    @property
    def press_range(self):
        """Return pressure range as a (min, max) tuple."""
        return (self.press_range_min, self.press_range_max)

    @property
    def ps_v_range(self):
        """Return power-supply voltage range as a (min, max) tuple."""
        return (self.ps_v_range_min, self.ps_v_range_max)

    @property
    def ps_i_range(self):
        """Return power-supply current range as a (min, max) tuple."""
        return (self.ps_i_range_min, self.ps_i_range_max)

    def get_tc_type_list(self, count: int) -> list:
        """Return a list of TC types of length *count*.

        Parses the ``tc_types`` comma-separated string (e.g. ``"C,C,K,K"``),
        padding any missing entries with ``tc_type`` as the default.
        """
        if self.tc_types:
            parts = [t.strip() for t in self.tc_types.split(",") if t.strip()]
        else:
            parts = []
        while len(parts) < count:
            parts.append(self.tc_type)
        return parts[:count]

    def get_tc_pin_list(self, count: int) -> list:
        """Return a list of AIN channel numbers (as ints) for thermocouples.

        Parses the ``tc_pins`` comma-separated string (e.g. ``"0,1,7"``),
        padding any missing entries with sequential values starting from the
        highest already assigned + 1 (or from 0 if none are assigned yet).
        """
        if self.tc_pins:
            parts = [int(p.strip()) for p in self.tc_pins.split(",") if p.strip().isdigit()]
        else:
            parts = []
        while len(parts) < count:
            parts.append(len(parts))
        return parts[:count]

    def get_tc_name_list(self, count: int, pin_list: list, type_list: list) -> list:
        """Return custom TC names, falling back to auto-generated names."""
        saved = [n.strip() for n in self.tc_names.split(",") if n.strip()] if self.tc_names else []
        result = []
        for i in range(count):
            if i < len(saved) and saved[i]:
                result.append(saved[i])
            else:
                pin = pin_list[i] if i < len(pin_list) else i
                typ = type_list[i] if i < len(type_list) else self.tc_type
                result.append(f"TC_AIN{pin}_{typ}")
        return result

    def get_frg_name_list(self, count: int, interface: str, pin_list: list) -> list:
        """Return custom FRG names, falling back to auto-generated names."""
        saved = [n.strip() for n in self.frg_names.split(",") if n.strip()] if self.frg_names else []
        result = []
        for i in range(count):
            if i < len(saved) and saved[i]:
                result.append(saved[i])
            else:
                if interface == "XGS600":
                    result.append(f"FRG702_T{2*i+1}")
                else:
                    pin = pin_list[i] if i < len(pin_list) else f"AIN{i}"
                    result.append(f"FRG702_{pin}")
        return result

    def get_frg_pin_list(self, count: int) -> list:
        """Return a list of AIN pins for FRG gauges.
        
        Parses the ``frg_pins`` comma-separated string (e.g. ``"AIN2,AIN3"``),
        padding with default AIN values (starting from AIN2 to avoid TCs by default).
        """
        if self.frg_pins:
            parts = [p.strip() for p in self.frg_pins.split(",") if p.strip()]
        else:
            parts = []
        while len(parts) < count:
            parts.append(f"AIN{len(parts) + 2}")
        return parts[:count]

    def __repr__(self):
        fields = ", ".join(f"{k}={getattr(self, k)!r}" for k in _DEFAULTS)
        return f"AppSettings({fields})"


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _coerce(raw, kind: str, default):
    """Convert a raw registry value to the desired Python type."""
    try:
        if kind == "int":
            return int(raw)
        if kind == "float":
            return float(raw)
        if kind == "bool":
            # Stored as REG_DWORD (0/1) or as string "True"/"False"
            if isinstance(raw, int):
                return bool(raw)
            return str(raw).strip().lower() in ("1", "true", "yes")
        if kind == "str":
            return str(raw)
    except (ValueError, TypeError):
        pass
    return default


def _write_value(key, name: str, value, kind: str) -> None:
    """Write a single value to an open registry key."""
    try:
        if kind == "int":
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))
        elif kind == "float":
            # Registry has no native float type; store as string
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, repr(float(value)))
        elif kind == "bool":
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 1 if value else 0)
        elif kind == "str":
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
    except (OSError, TypeError):
        pass  # Fail silently for individual values

r"""
app_settings.py
PURPOSE: Persistent application settings stored in the Windows Registry.

All user-configurable values are persisted under:
    HKEY_CURRENT_USER\Software\T8_DAQ_System

No external JSON config files are used. On first launch (or if the registry
key has never been written) load() returns all defaults.

WHY THE REGISTRY WINS (ADR 0007)
--------------------------------
_DEFAULTS seeds only keys the registry lacks; no other module holds a default
for a setting. load() records in ``sources`` whether each key came from the
"registry" or a "default". Keys deleted from _DEFAULTS (ps_current_limit,
soft_start_current_limit_a, pid_output_max) may linger in an old registry; they
are never read and never written back.

save() logs one INFO line per key whose value differs from what was last loaded
or saved (old and new value), so the Diagnostic log shows what an operator
changed in Settings (ADR 0008).
"""

import copy
import logging
import winreg

logger = logging.getLogger(__name__)

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
    "camera_index":       ("int",   0),
    "camera_buttons_overlay": ("bool", False),
    "timelapse_interval_s":   ("int",  60),
    "timelapse_export_fps":   ("int",  10),
    "xgs600_port":        ("str",   "COM4"),
    "xgs600_baudrate":    ("int",   9600),
    "xgs600_timeout":     ("float", 1.0),
    "xgs600_address":     ("str",   "00"),
    "turbo_pump_enabled": ("bool", True),
    "turbo_pump_start_delay_ms": ("int", 500),
    "turbo_pump_stop_delay_ms": ("int", 500),
    "turbo_pump_min_restart_delay_s": ("int", 30),
    "ps_voltage_limit":   ("float", 20.0),
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
    "soft_start_ramp_v_per_s":   ("float", 0.02),    # V/s — Soft start voltage ramp
    "soft_start_handoff_current_a": ("float", 35.0), # A — Handoff to PID
    "soft_start_cap_enabled":    ("bool",  True),
    "soft_start_cap_a":          ("float", 40.0),    # A — Soft-start current cap
    "run_cap_enabled":           ("bool",  True),
    "run_cap_a":                 ("float", 120.0),   # A — Run current cap
    "pid_kp":               ("float", 0.014),
    "pid_ki":               ("float", 0.00078),
    "pid_kd":               ("float", 0.00845),
    "pid_windup_limit":     ("float", 0.4),
    # ── Diagnostics ───────────────────────────────────────────────────────
    "heartbeat_interval_s":      ("int",   30),
    "show_console":              ("bool",  False),
    "diagnostic_log_keep":       ("int",   30),
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
        # Values as last loaded or saved; None means "every key is its default"
        self._persisted = None
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
        self.camera_index: int       = 0
        self.camera_buttons_overlay: bool = False
        self.timelapse_interval_s: int = 60
        self.timelapse_export_fps: int = 10
        self.xgs600_port: str        = "COM4"
        self.xgs600_baudrate: int    = 9600
        self.xgs600_timeout: float   = 1.0
        self.xgs600_address: str     = "00"
        self.turbo_pump_enabled: bool = True
        self.turbo_pump_start_delay_ms: int = 500
        self.turbo_pump_stop_delay_ms: int = 500
        self.turbo_pump_min_restart_delay_s: int = 30
        self.ps_voltage_limit: float = 20.0
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
        self.soft_start_ramp_v_per_s: float = 0.02
        self.soft_start_handoff_current_a: float = 35.0
        self.soft_start_cap_enabled: bool = True
        self.soft_start_cap_a: float = 40.0
        self.run_cap_enabled: bool = True
        self.run_cap_a: float = 120.0
        self.pid_kp: float = 0.014
        self.pid_ki: float = 0.00078
        self.pid_kd: float = 0.00845
        self.pid_windup_limit: float = 0.4
        # Diagnostics
        self.heartbeat_interval_s: int = 30
        self.show_console: bool = False
        self.diagnostic_log_keep: int = 30
        # Where each loaded key came from: "registry" or "default" (ADR 0007)
        self.sources: dict = {k: "default" for k in _DEFAULTS}
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
            logger.info("Settings registry key absent; every setting is a default")
            return self
        except OSError as e:
            # Registry unavailable (non-Windows environment, permissions) — keep defaults
            logger.warning("Settings registry unavailable (%s); every setting is a default", e)
            return self

        try:
            for field, (kind, default) in _DEFAULTS.items():
                try:
                    raw_value, _ = winreg.QueryValueEx(key, field)
                    val = _coerce(raw_value, kind, default)
                    setattr(self, field, val)
                    self.sources[field] = "registry"
                except (FileNotFoundError, OSError) as e:
                    # Individual value missing — keep default
                    logger.debug("Registry value %s missing (%s); keeping default %r", field, e, default)
                    setattr(self, field, default)
                    self.sources[field] = "default"
        finally:

            winreg.CloseKey(key)

        # Migrate unsupported temperature unit: F is no longer selectable
        if getattr(self, 'tc_unit', 'C') == 'F':
            self.tc_unit = 'C'

        self._persisted = {f: copy.deepcopy(getattr(self, f, d)) for f, (_k, d) in _DEFAULTS.items()}
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
            baseline = self._persisted or {f: d for f, (_k, d) in _DEFAULTS.items()}
            for field, (kind, _default) in _DEFAULTS.items():
                value = getattr(self, field, _default)
                if value != baseline.get(field, _default):
                    logger.info("Setting %s changed: %r -> %r", field, baseline.get(field, _default), value)
                _write_value(key, field, value, kind)
            self._persisted = {f: copy.deepcopy(getattr(self, f, d)) for f, (_k, d) in _DEFAULTS.items()}
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
    except (ValueError, TypeError) as e:
        # Type coercion failed; use default value
        logger.debug("Coercion of %r to %s failed (%s); using default %r", raw, kind, e, default)
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
    except (OSError, TypeError) as e:
        # Failed to persist individual registry value; logged and skipped
        logger.warning("Failed to write registry value %s=%r (%s)", name, value, e)


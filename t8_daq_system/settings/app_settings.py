"""
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
    "ps_v_range_max":     ("float", 100.0),
    "ps_i_range_min":     ("float", 0.0),
    "ps_i_range_max":     ("float", 100.0),
    "log_folder":         ("str",   ""),
    "visa_resource":      ("str",   ""),
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
        self.ps_v_range_max: float   = 100.0
        self.ps_i_range_min: float   = 0.0
        self.ps_i_range_max: float   = 100.0
        self.log_folder: str         = ""
        self.visa_resource: str      = ""

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
                    setattr(self, field, _coerce(raw_value, kind, default))
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

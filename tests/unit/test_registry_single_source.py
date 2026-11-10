"""Ticket 24 / ADR 0007: the registry is the single source of settings."""

import importlib.util
import sys
from unittest.mock import MagicMock, patch

import pytest

from t8_daq_system.settings.run_settings import run_settings_from_app_settings
from t8_daq_system.settings import app_settings
from t8_daq_system.settings.app_settings import AppSettings, _DEFAULTS


class FakeWinreg:
    """In-memory stand-in for winreg holding one key's values."""

    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1
    REG_DWORD = 4

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.exists = values is not None

    def OpenKey(self, root, path):
        if not self.exists:
            raise FileNotFoundError(path)
        return self

    def CreateKey(self, root, path):
        self.exists = True
        return self

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, _res, _kind, value):
        self.values[name] = value

    def CloseKey(self, key):
        pass


@pytest.fixture
def registry(monkeypatch):
    def make(values=None):
        fake = FakeWinreg(values)
        monkeypatch.setattr(app_settings, "winreg", fake)
        return fake
    return make


def test_empty_registry_loads_new_defaults_with_default_source(registry):
    registry({})
    s = AppSettings().load()
    assert s.pid_kp == 0.014
    assert s.pid_ki == 0.00078
    assert s.pid_kd == 0.00845
    assert s.sources["pid_kp"] == "default"


def test_registry_value_wins_and_is_marked_registry(registry):
    registry({"pid_kp": "0.02"})
    s = AppSettings().load()
    assert s.pid_kp == 0.02
    assert s.sources["pid_kp"] == "registry"
    assert s.sources["pid_ki"] == "default"


def test_missing_registry_key_marks_everything_default(registry):
    registry(None)
    s = AppSettings().load()
    assert s.pid_kp == 0.014
    assert set(s.sources.values()) == {"default"}


def test_new_soft_start_and_cap_defaults(registry):
    registry({})
    s = AppSettings().load()
    assert s.soft_start_ramp_v_per_s == 0.02
    assert s.soft_start_handoff_current_a == 35.0
    assert s.soft_start_cap_enabled is True
    assert s.soft_start_cap_a == 40.0
    assert s.run_cap_enabled is True
    assert s.run_cap_a == 175.0
    assert s.heartbeat_interval_s == 30
    assert s.show_console is False
    assert s.diagnostic_log_keep == 30
    assert s.soft_start_threshold_c == 200.0


def test_retired_run_cap_in_registry_loads_as_175(registry):
    registry({"run_cap_a": "120.0"})
    s = AppSettings().load()
    assert s.run_cap_a == 175.0
    assert s.sources["run_cap_a"] == "migrated"


def test_custom_run_cap_in_registry_is_kept(registry):
    assert _DEFAULTS["run_cap_a"][1] == 175.0
    registry({"run_cap_a": "150.0"})
    s = AppSettings().load()
    assert s.run_cap_a == 150.0
    assert s.sources["run_cap_a"] == "registry"


def test_migrated_run_cap_is_written_on_next_save(registry):
    fake = registry({"run_cap_a": "120.0"})
    s = AppSettings().load()
    assert s.run_cap_a == 175.0
    s.save()
    assert fake.values["run_cap_a"] == "175.0"


def test_check_run_cap_a_bounds():
    from t8_daq_system.settings.app_settings import check_run_cap_a

    assert check_run_cap_a(175.0) == 175.0
    assert check_run_cap_a(180.0) == 180.0
    for bad in (0.0, -5.0, 180.5):
        with pytest.raises(ValueError, match="180 A"):
            check_run_cap_a(bad)


def test_deleted_keys_are_ignored_on_load_and_never_saved(registry):
    fake = registry({"pid_output_max": "6.0", "ps_current_limit": "50.0",
                     "soft_start_current_limit_a": "180.0"})
    s = AppSettings().load()
    for name in ("pid_output_max", "ps_current_limit", "soft_start_current_limit_a"):
        assert not hasattr(s, name)
    fake.values.clear()
    s.save()
    assert fake.values
    for name in ("pid_output_max", "ps_current_limit", "soft_start_current_limit_a"):
        assert name not in fake.values


def test_run_settings_reads_real_fields():
    s = AppSettings()
    s.run_cap_a = 150
    s.soft_start_cap_a = 33.0
    s.soft_start_ramp_v_per_s = 0.05
    s.soft_start_handoff_current_a = 22.0
    s.soft_start_threshold_c = 310.0
    s.soft_start_cap_enabled = False
    s.run_cap_enabled = False
    rs = run_settings_from_app_settings(s)
    assert rs.run_cap_a == 150
    assert rs.soft_start_cap_a == 33.0
    assert rs.soft_start_ramp_v_per_s == 0.05
    assert rs.soft_start_handoff_current_a == 22.0
    assert rs.soft_start_threshold_c == 310.0
    assert rs.soft_start_cap_enabled is False
    assert rs.run_cap_enabled is False


@pytest.fixture
def dialog(monkeypatch):
    """A SettingsDialog shell with ttk/tk replaced so widget calls are recorded."""
    ttk = MagicMock()
    tk = MagicMock()
    tk.StringVar.side_effect = lambda *a, **k: _Var()
    tk.BooleanVar.side_effect = lambda *a, **k: _Var()
    # Under the conftest Tk stub Toplevel is a MagicMock, so load a private
    # copy of the module whose Toplevel is a real class. patch.object, not
    # monkeypatch: pytest >= 9.2 undoes monkeypatch.setattr on a MagicMock
    # with delattr, which the MagicMock remembers for the rest of the session.
    spec = importlib.util.find_spec("t8_daq_system.gui.settings_dialog")
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys.modules["tkinter"], "Toplevel", type("Toplevel", (), {})):
        spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ttk", ttk)
    monkeypatch.setattr(module, "tk", tk)
    d = object.__new__(module.SettingsDialog)
    d._settings = AppSettings()
    d._ttk = ttk
    return d


class _Var:
    def __init__(self):
        self.v = None

    def set(self, v):
        self.v = v

    def get(self):
        return self.v


def _texts(ttk):
    out = []
    for call in ttk.mock_calls:
        for arg in list(call.args) + list(call.kwargs.values()):
            if isinstance(arg, str):
                out.append(arg)
    return out


def test_dialog_has_no_stale_widgets(dialog):
    notebook = MagicMock()
    dialog._build_power_programmer_tab(notebook)
    dialog._build_hardware_tab(notebook)
    texts = _texts(dialog._ttk)
    assert not [t for t in texts if "History may override" in t or "Max Output" in t]
    assert not [t for t in texts if "Current Limit (A)" in t and "Default" not in t]
    assert any("Soft start" in t for t in texts)


def test_reset_pid_handler_restores_default_gains(dialog):
    dialog._build_power_programmer_tab(MagicMock())
    dialog._pid_kp_var.set("9")
    dialog._pid_ki_var.set("9")
    dialog._pid_kd_var.set("9")
    dialog._reset_pid_to_defaults()
    assert float(dialog._pid_kp_var.get()) == _DEFAULTS["pid_kp"][1]
    assert float(dialog._pid_ki_var.get()) == _DEFAULTS["pid_ki"][1]
    assert float(dialog._pid_kd_var.get()) == _DEFAULTS["pid_kd"][1]


def test_save_logs_one_info_record_per_changed_key(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(app_settings, "winreg", FakeWinreg({}))
    s = AppSettings().load()
    s.run_cap_a = 111.0
    s.tc_unit = "K"
    with caplog.at_level(logging.INFO, logger=app_settings.logger.name):
        s.save()
    changed = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO and "changed" in r.getMessage()]
    assert len(changed) == 2
    cap = [m for m in changed if "run_cap_a" in m]
    assert len(cap) == 1
    assert str(_DEFAULTS["run_cap_a"][1]) in cap[0] and "111.0" in cap[0]
    assert any("tc_unit" in m and "'K'" in m for m in changed)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=app_settings.logger.name):
        s.save()
    assert not [r for r in caplog.records if "changed" in r.getMessage()]


def test_safety_tab_holds_both_caps_and_fixed_limits(dialog):
    from t8_daq_system.settings.safety_limits import fixed_limit_lines

    notebook = MagicMock()
    dialog._build_safety_tab(notebook)
    notebook.add.assert_called_once()
    assert notebook.add.call_args[1].get("text") == "Safety limits"
    texts = _texts(dialog._ttk)
    assert "Run current cap (A):" in texts
    assert "Enforce run current cap" in texts
    assert "Soft-start current cap (A):" in texts
    assert "Enforce soft-start current cap" in texts
    for line in fixed_limit_lines():
        assert line in texts


def test_power_programmer_tab_has_no_cap_editors(dialog):
    notebook = MagicMock()
    dialog._build_power_programmer_tab(notebook)
    texts = _texts(dialog._ttk)
    assert "Run current cap (A):" not in texts
    assert "Soft-start current cap (A):" not in texts
    assert any("Soft start" in t for t in texts)


def test_reset_run_cap_handler_restores_default(dialog):
    notebook = MagicMock()
    dialog._build_safety_tab(notebook)
    dialog._run_cap_a_var.set("99")
    dialog._reset_run_cap_to_default()
    assert float(dialog._run_cap_a_var.get()) == _DEFAULTS["run_cap_a"][1]


"""
Tests for the pure run_settings module (Ticket 38).
"""
import subprocess
import sys

from t8_daq_system.settings.app_settings import _DEFAULTS


def test_module_imports_without_tk_or_gui():
    cmd = [
        sys.executable,
        "-c",
        "import sys\n"
        "sys.modules['winreg'] = type('FakeWinreg', (), {})()\n"
        "ljm = type('FakeLJM', (), {})\n"
        "labjack = type('FakeLabjack', (), {'ljm': ljm})()\n"
        "sys.modules['labjack'] = labjack\n"
        "sys.modules['labjack.ljm'] = ljm\n"
        "sys.modules['pyvisa'] = type('FakePyVisa', (), {'ResourceManager': type('RM', (), {})})()\n"
        "import t8_daq_system.settings.run_settings\n"
        "print('tkinter' in sys.modules, any(m.startswith('t8_daq_system.gui') for m in sys.modules))"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=".")
    if res.returncode != 0:
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
    assert res.stdout.strip() == "False False"


def test_production_run_settings_match_defaults():
    from t8_daq_system.settings.run_settings import production_run_settings
    settings = production_run_settings()
    assert settings.kp == _DEFAULTS["pid_kp"][1]
    assert settings.ki == _DEFAULTS["pid_ki"][1]
    assert settings.kd == _DEFAULTS["pid_kd"][1]
    assert settings.windup_limit == _DEFAULTS["pid_windup_limit"][1]

    fields = [
        "soft_start_threshold_c",
        "soft_start_ramp_v_per_s",
        "soft_start_handoff_current_a",
        "soft_start_cap_enabled",
        "soft_start_cap_a",
        "run_cap_enabled",
        "run_cap_a"
    ]
    for field in fields:
        assert getattr(settings, field) == _DEFAULTS[field][1]


def test_production_run_settings_read_defaults_live(monkeypatch):
    import t8_daq_system.settings.app_settings as app_settings
    monkeypatch.setitem(app_settings._DEFAULTS, "run_cap_a", (float, 99.0))

    from t8_daq_system.settings.run_settings import production_run_settings
    settings = production_run_settings()
    assert settings.run_cap_a == 99.0

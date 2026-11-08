"""The shipped build must not look like malware to endpoint security.

A one-folder build was deleted by the lab's IT security. The build carried
three things such tools flag: input injection into other windows (pyautogui:
key presses, clicks, window enumeration, screenshots), a second unsigned
executable (imageio-ffmpeg's ffmpeg.exe), and copies of Windows system DLLs.
These tests keep them out of the source, the requirements and the spec.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BANNED_MODULES = ("pyautogui", "pygetwindow", "pyscreeze", "pymsgbox",
                  "pytweening", "imageio", "imageio_ffmpeg")


def _spec():
    return (ROOT / "tds.spec").read_text(encoding="utf-8")


def _excludes(spec):
    block = re.search(r"excludes=\[(.*?)\]", spec, re.S).group(1)
    return set(re.findall(r"'([^']+)'", block))


def _hiddenimports(spec):
    block = re.search(r"hiddenimports = \[(.*?)\n\]", spec, re.S).group(1)
    lines = [ln.split("#", 1)[0] for ln in block.splitlines()]
    return set(re.findall(r"'([^']+)'", "\n".join(lines)))


def test_application_source_imports_no_input_injection_or_ffmpeg():
    offenders = []
    for path in (ROOT / "t8_daq_system").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for mod in BANNED_MODULES:
            if re.search(rf"^\s*(import|from)\s+{mod}\b", text, re.M):
                offenders.append(f"{path.relative_to(ROOT)}: {mod}")
    assert offenders == []


def test_requirements_drop_input_injection_and_ffmpeg():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for name in ("pyautogui", "pygetwindow", "imageio"):
        assert name not in reqs


def test_spec_neither_requests_nor_lets_in_banned_modules():
    spec = _spec()
    hidden = _hiddenimports(spec)
    excluded = _excludes(spec)
    for mod in BANNED_MODULES:
        assert mod not in hidden
        assert mod in excluded


def test_spec_excludes_network_discovery():
    assert "zeroconf" in _excludes(_spec())


def test_spec_copies_nothing_out_of_the_windows_folder():
    spec = _spec()
    assert "System32" not in spec
    assert "SysWOW64" not in spec


def test_build_bat_calls_build_script_and_has_no_control_characters():
    raw = (ROOT / "build.bat").read_bytes()
    assert not [b for b in raw if b < 0x20 and b not in (0x0A, 0x0D)]
    assert b"scripts\\build.py" in raw


def test_timelapse_video_format_setting_defaults_to_mp4():
    from t8_daq_system.settings.app_settings import AppSettings, _DEFAULTS
    assert _DEFAULTS["timelapse_video_format"] == ("str", "mp4")
    assert AppSettings().timelapse_video_format == "mp4"


def test_qms_auto_click_settings_are_gone():
    from t8_daq_system.settings.app_settings import AppSettings, _DEFAULTS
    for key in ("qms_auto_click_enabled", "qms_auto_click_x", "qms_auto_click_y"):
        assert key not in _DEFAULTS
        assert not hasattr(AppSettings(), key)

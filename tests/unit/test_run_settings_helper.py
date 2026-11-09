"""Tests run on Production settings (field-realistic-testing ticket 39).

WHY THIS EXISTS: the 2026-11-06 lab trip went unseen because the test helper
disabled the Run current cap and used non-shipped gains. These tests keep the
helper tied to ``production_run_settings()`` and keep every deviation marked.
"""
from __future__ import annotations

import re
from pathlib import Path

from t8_daq_system.settings.run_settings import production_run_settings
from tests.run_settings_helper import make_run_settings

_TESTS = Path(__file__).resolve().parents[1]
_MARKER = "# not production:"
_NEEDLES = (
    "run_cap_enabled=False",
    "soft_start_cap_enabled=False",
    "soft_start_threshold_c=-273",
)


def test_make_run_settings_is_production():
    assert make_run_settings() == production_run_settings()


def test_non_production_overrides_are_marked():
    offenders = []
    for path in sorted(_TESTS.rglob("*.py")):
        if path.resolve() == Path(__file__).resolve():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(s in line for s in _NEEDLES) and _MARKER not in line:
                offenders.append(f"{path.relative_to(_TESTS.parent).as_posix()}:{n}")
    assert not offenders, "unmarked non-production overrides: " + ", ".join(offenders)


def test_helper_holds_no_gain_literals():
    text = (_TESTS / "run_settings_helper.py").read_text(encoding="utf-8")
    found = re.findall(r"\b(?:kp|ki|kd|windup_limit)\s*=", text)
    assert not found, f"gain literals in helper: {found}"

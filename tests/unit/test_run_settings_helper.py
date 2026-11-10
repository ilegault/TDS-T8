"""The test helper builds Production settings; overrides are marked (ticket 39).

WHY THIS EXISTS
---------------
The 2026-11-06 lab trip went unseen because the test helper's base settings
disabled the Run current cap and used gains that were not the shipped ones.
These tests keep ``tests/run_settings_helper.py`` pinned to
``production_run_settings()`` and keep every non-production override visible.
"""
from __future__ import annotations

import re
from pathlib import Path

from t8_daq_system.settings.run_settings import production_run_settings
from tests.run_settings_helper import make_run_settings

TESTS_DIR = Path(__file__).resolve().parents[1]
HELPER = TESTS_DIR / "run_settings_helper.py"

_MARKED_FIELDS = (
    "run_cap_enabled=False",
    "soft_start_cap_enabled=False",
    "soft_start_threshold_c=-273",
)


def test_make_run_settings_is_production():
    assert make_run_settings() == production_run_settings()


def test_non_production_overrides_are_marked():
    offenders = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if path.resolve() == Path(__file__).resolve():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(text in line for text in _MARKED_FIELDS) and "# not production:" not in line:
                offenders.append(f"{path.relative_to(TESTS_DIR.parent)}:{lineno}")
    assert not offenders, "unmarked non-production overrides: " + ", ".join(offenders)


def test_helper_holds_no_gain_literals():
    source = HELPER.read_text(encoding="utf-8")
    found = re.findall(r"\b(kp|ki|kd|windup_limit)\s*=", source)
    assert not found, f"gain fields assigned in the helper: {found}"

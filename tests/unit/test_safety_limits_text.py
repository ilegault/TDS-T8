"""
tests/unit/test_safety_limits_text.py
Contract tests for fixed_limit_lines (ticket 43).

WHY THIS EXISTS
---------------
ADR 0001 requires tests first. Ticket 43 introduces fixed_limit_lines()
to display all hard-coded system safety limits on the Safety limits tab in Settings.
This test ensures each limit string accurately quotes the canonical constants.
"""
from __future__ import annotations

import pytest

from t8_daq_system.settings.safety_limits import fixed_limit_lines

pytestmark = pytest.mark.unit


def test_fixed_limit_lines_quote_the_constants():
    lines = fixed_limit_lines()
    assert len(lines) == 6
    text = " ".join(lines)
    assert "2200 °C" in text
    assert "1.0e-04 Torr" in text
    assert "5 s" in text
    assert "180 A" in text
    assert "6 V" in text

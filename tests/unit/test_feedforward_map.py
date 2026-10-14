"""
tests/unit/test_feedforward_map.py

WHY THIS EXISTS
---------------
ADR 0006 point 6: below the Feedforward map's lowest point the answer is 0 V,
never the lowest point's voltage. A cold filament that was handed 0.29 V
(the 50 degC point) drew 60-70 A in one step.
"""
from __future__ import annotations

import pytest

from t8_daq_system.control.feedforward_map import FeedforwardMap

pytestmark = pytest.mark.unit


def test_voltage_for_is_zero_below_first_point_and_exact_at_it():
    ff_map = FeedforwardMap()
    ff_map._ss_curve = [[50.0, 0.29], [100.0, 0.6], [200.0, 1.2]]

    assert ff_map.voltage_for(10.0, 20.0) == 0.0
    assert ff_map.voltage_for(10.0, 50.0) == pytest.approx(0.29)


def test_voltage_for_above_last_point_is_unchanged():
    ff_map = FeedforwardMap()
    ff_map._ss_curve = [[50.0, 0.29], [200.0, 1.2]]

    assert ff_map.voltage_for(10.0, 500.0) == pytest.approx(1.2)


def test_voltage_for_empty_map_is_zero():
    assert FeedforwardMap().voltage_for(10.0, 20.0) == 0.0

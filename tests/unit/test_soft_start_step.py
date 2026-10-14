"""
Ticket 22: the pure Soft-start step.

WHY THIS EXISTS
---------------
step_soft_start has no clock or hardware (ADR 0006 points 1-2), so its decisions
are tested directly: ramp from the start voltage, no Feedforward, and the first of
threshold / handoff current ends it with a reason.
"""
from __future__ import annotations

import pytest

from tests.run_settings_helper import make_run_settings
from t8_daq_system.control.block_steps import step_soft_start


def _step(temp_c=26.0, amps=1.0, elapsed_s=10.0, start_v=0.1, **overrides):
    overrides.setdefault("soft_start_threshold_c", 200.0)
    return step_soft_start(
        make_run_settings(**overrides), temp_c, amps, elapsed_s, start_v
    )


def test_ramps_linearly_from_start_voltage_with_no_feedforward():
    res, reason = _step(elapsed_s=10.0, start_v=0.1, soft_start_ramp_v_per_s=0.02)
    assert res.volts == pytest.approx(0.3)
    assert res.sched.ff_voltage == 0.0
    assert res.finished is False
    assert reason is None


def test_voltage_is_clamped_to_rated_maximum():
    res, _ = _step(elapsed_s=1000.0, soft_start_ramp_v_per_s=0.02)
    assert res.volts == 6.0


def test_threshold_ends_soft_start():
    res, reason = _step(temp_c=200.0, soft_start_threshold_c=200.0)
    assert res.finished is True
    assert reason == "threshold 200.0 °C reached"


def test_handoff_current_ends_soft_start_with_temperature_in_reason():
    res, reason = _step(temp_c=143.24, amps=35.0, soft_start_handoff_current_a=35.0)
    assert res.finished is True
    assert reason == "handoff current 35.0 A reached at 143.2 °C"


def test_just_below_both_limits_keeps_ramping():
    res, reason = _step(temp_c=199.9, amps=34.9)
    assert res.finished is False
    assert reason is None

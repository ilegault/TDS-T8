"""
tests/unit/test_suggestion_engine.py

Pure-function tests for the one Suggestion engine (ticket
cold-start-and-traceability-31, ADR 0007 point 7).

WHY THIS EXISTS
---------------
Two engines used to disagree about the same run.  These tests pin the single rule
set: each rule is a +/-15 % step, and oscillations ignore the +/-2 K noise band.
"""
from __future__ import annotations

import pytest

from t8_daq_system.control.suggestion_engine import run_metrics, suggest

pytestmark = pytest.mark.unit

GAINS = (0.014, 0.00078, 0.00845)


def _log_oscillating(amplitude_k: float, n: int = 40):
    """Error alternates +amplitude / -amplitude around a 400 K setpoint."""
    return [
        (float(i), 400.0, 400.0 + (amplitude_k if i % 2 == 0 else -amplitude_k), 1.0)
        for i in range(n)
    ]


def _metrics(**overrides):
    base = {
        "overshoot_k": 0.0,
        "settling_time_sec": 30.0,
        "oscillation_count": 0,
        "rate_error_pct": 0.0,
    }
    base.update(overrides)
    return base


def test_one_kelvin_oscillation_is_inside_noise_band():
    assert run_metrics(_log_oscillating(1.0), 60.0)["oscillation_count"] == 0


def test_five_kelvin_oscillation_is_counted():
    assert run_metrics(_log_oscillating(5.0), 60.0)["oscillation_count"] > 0


def test_sign_change_through_samples_inside_band_is_not_counted():
    # +5, +1 (inside band), -1 (inside band), +5: no change between outside samples
    log = [
        (0.0, 400.0, 405.0, 1.0),
        (1.0, 400.0, 401.0, 1.0),
        (2.0, 400.0, 399.0, 1.0),
        (3.0, 400.0, 405.0, 1.0),
    ]
    assert run_metrics(log, 60.0, noise_band_k=2.0)["oscillation_count"] == 0


def test_rate_tracking_error_reported_in_percent():
    # climbs 0.8 K/s = 48 K/min against a 60 K/min target -> 20 % low
    log = [(float(i), 300.0 + 0.8 * i, 300.0 + 0.8 * i, 1.0) for i in range(60)]
    assert run_metrics(log, 60.0)["rate_error_pct"] == pytest.approx(20.0, abs=0.5)


def test_rate_error_raises_ki_with_rate_reason():
    s = suggest(_metrics(rate_error_pct=20.0), GAINS)
    assert s.ki > GAINS[1]
    assert s.ki == pytest.approx(GAINS[1] * 1.15)
    assert any("rate" in r for r in s.reasons)
    assert (s.kp, s.kd) == (GAINS[0], GAINS[2])


def test_overshoot_lowers_kp():
    s = suggest(_metrics(overshoot_k=8.0), GAINS)
    assert s.kp < GAINS[0]
    assert s.kp == pytest.approx(GAINS[0] * 0.85)


def test_oscillations_raise_kd_and_lower_ki_with_one_reason_each():
    s = suggest(_metrics(oscillation_count=6), GAINS)
    assert s.kd > GAINS[2]
    assert s.ki < GAINS[1]
    assert len(s.reasons) == 2


def test_oscillation_outranks_rate_error_for_ki():
    s = suggest(_metrics(oscillation_count=6, rate_error_pct=30.0), GAINS)
    assert s.ki < GAINS[1]


def test_slow_settling_with_small_overshoot_raises_kp():
    s = suggest(_metrics(settling_time_sec=200.0, overshoot_k=0.5), GAINS)
    assert s.kp > GAINS[0]


def test_slow_settling_with_overshoot_does_not_raise_kp():
    s = suggest(_metrics(settling_time_sec=200.0, overshoot_k=3.0), GAINS)
    assert s.kp == GAINS[0]


def test_no_rule_fires_leaves_gains_unchanged():
    s = suggest(_metrics(), GAINS)
    assert (s.kp, s.ki, s.kd) == GAINS
    assert s.reasons == ("stable — no change",)

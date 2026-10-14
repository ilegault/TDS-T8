"""
t8_daq_system/control/suggestion_engine.py

The one Suggestion engine (ticket cold-start-and-traceability-31, ADR 0007 point 7).

WHY THIS EXISTS
---------------
Two engines used to turn a finished TempRamp into tuning advice
(``PIDRunLogger._generate_suggestions`` and the post-run popup in the GUI) and they
could disagree: the popup could only lower Kp/Ki and raise Kd, and it counted every
zero crossing of the error as an oscillation, so thermocouple noise looked like
ringing.  This module is the only place that maps a run to suggested gains.

``run_metrics`` reduces a run log to numbers; ``suggest`` maps numbers plus the
Gains in use to a Suggestion.  Both are pure: no clock, hardware, file or Tk, so the
tests drive them directly.  Oscillations count only sign changes of the error where
the error exceeds the noise band on both sides of the change.

A run log is a sequence of ``(elapsed_s, setpoint_k, actual_k, volts)`` tuples.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

STEP_FRACTION = 0.15              # every rule moves one gain by +/- 15 %
RATE_ERROR_LIMIT_PCT = 10.0
OVERSHOOT_LIMIT_K = 5.0
OSCILLATION_LIMIT = 4
SLOW_SETTLING_S = 120.0
SMALL_OVERSHOOT_K = 1.0
SETTLE_BAND_K = 2.0
SETTLE_MIN_TICKS = 10
STABLE_REASON = "stable — no change"


@dataclass(frozen=True)
class Suggestion:
    """Suggested gains and one reason per changed gain (or the stable reason)."""

    kp: float
    ki: float
    kd: float
    reasons: tuple[str, ...]


def run_metrics(
    run_log: Sequence[tuple[float, float, float, float]],
    rate_k_per_min: float,
    noise_band_k: float = 2.0,
) -> dict[str, Any]:
    """Reduce a run log to overshoot, settling, oscillations and rate error."""
    errors = [actual - setpoint for _, setpoint, actual, _ in run_log]

    overshoot_k = max([e for e in errors if e > 0.0], default=0.0)

    settling_s = None
    consecutive = 0
    for (t, _, _, _), err in zip(run_log, errors):
        if abs(err) <= SETTLE_BAND_K:
            consecutive += 1
            if consecutive >= SETTLE_MIN_TICKS and settling_s is None:
                settling_s = t
        else:
            consecutive = 0

    # Samples inside the noise band are dropped, so a sign change is only counted
    # when the error is outside the band on both sides of it.
    outside = [e for e in errors if abs(e) > noise_band_k]
    oscillations = sum(
        1 for prev, cur in zip(outside, outside[1:]) if prev * cur < 0.0
    )

    achieved = 0.0
    if len(run_log) >= 2 and run_log[-1][0] > run_log[0][0]:
        span_min = (run_log[-1][0] - run_log[0][0]) / 60.0
        achieved = (run_log[-1][2] - run_log[0][2]) / span_min
    rate_error_pct = 0.0
    if rate_k_per_min > 0.0:
        rate_error_pct = abs(achieved - rate_k_per_min) / rate_k_per_min * 100.0

    return {
        "overshoot_k": overshoot_k,
        "settling_time_sec": settling_s,
        "oscillation_count": oscillations,
        "achieved_mean_rate_k_per_min": achieved,
        "rate_error_pct": rate_error_pct,
    }


def suggest(metrics: Mapping[str, Any], gains_in_use: tuple[float, float, float]) -> Suggestion:
    """Map run metrics and the Gains in use (kp, ki, kd) to a Suggestion."""
    kp, ki, kd = gains_in_use
    up, down = 1.0 + STEP_FRACTION, 1.0 - STEP_FRACTION
    overshoot = metrics.get("overshoot_k", 0.0)
    oscillations = metrics.get("oscillation_count", 0)
    settling = metrics.get("settling_time_sec")
    rate_error = metrics.get("rate_error_pct", 0.0)
    pct = f"{STEP_FRACTION:.0%}"

    new = {"kp": kp, "ki": ki, "kd": kd}
    reasons: dict[str, str] = {}

    def move(gain: str, factor: float, why: str) -> None:
        new[gain] = new[gain] * factor
        reasons[gain] = f"{gain.capitalize()} {'+' if factor > 1 else '-'}{pct}: {why}"

    oscillating = oscillations > OSCILLATION_LIMIT
    # Ringing outranks slow rate following: raising Ki would feed the oscillation.
    if rate_error > RATE_ERROR_LIMIT_PCT and not oscillating:
        move("ki", up, f"rate tracking error {rate_error:.0f}% > {RATE_ERROR_LIMIT_PCT:.0f}%")
    if overshoot > OVERSHOOT_LIMIT_K:
        move("kp", down, f"overshoot {overshoot:.1f} K > {OVERSHOOT_LIMIT_K:.0f} K")
    if oscillating:
        why = f"{oscillations} oscillations > {OSCILLATION_LIMIT}"
        move("kd", up, why)
        move("ki", down, why)
    if settling is not None and settling > SLOW_SETTLING_S and overshoot <= SMALL_OVERSHOOT_K:
        move("kp", up, f"slow settling {settling:.0f} s > {SLOW_SETTLING_S:.0f} s with little overshoot")

    if not reasons:
        return Suggestion(kp, ki, kd, (STABLE_REASON,))
    return Suggestion(new["kp"], new["ki"], new["kd"], tuple(reasons.values()))

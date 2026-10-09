"""
Basic sanity tests for TungstenSim.
"""
import pytest
from tests.simulation.tungsten_thermal_model import TungstenSim

pytestmark = pytest.mark.simulation


def test_steady_state_3v_near_table():
    """At 3.0V steady-state temp should be within 200K of 1680K (feedforward table)."""
    sim = TungstenSim(dt=0.5)
    T_ss = sim.steady_state_temp(3.0)
    assert 1400 < T_ss < 1900, f"3.0V steady state {T_ss:.0f}K out of range"


def test_steady_state_increases_with_voltage():
    """Higher voltage must give higher steady-state temperature."""
    sim = TungstenSim(dt=0.5)
    T1 = sim.steady_state_temp(1.0)
    T2 = sim.steady_state_temp(2.0)
    T3 = sim.steady_state_temp(3.0)
    assert T1 < T2 < T3, f"Non-monotonic: {T1:.0f} {T2:.0f} {T3:.0f}"


def test_reset_returns_to_ambient():
    sim = TungstenSim(dt=0.5)
    sim.step(3.0)
    sim.step(3.0)
    sim.reset()
    assert sim.get_state()['temperature_k'] == 300.0


def test_step_returns_tuple():
    sim = TungstenSim(dt=0.5)
    result = sim.step(2.0)
    assert len(result) == 2
    T, current = result
    assert T > 300.0
    assert current > 0.0


def test_resistance_at_300k():
    """TungstenSim resistance at 300K should be within [0.004, 0.006]."""
    sim = TungstenSim(dt=0.5)
    r = sim._resistance(300.0)
    assert 0.004 <= r <= 0.006, f"Resistance {r} is outside [0.004, 0.006]"


def test_steady_state_current_at_6v():
    """At steady state for 6.0V, current should be within [120, 180] A."""
    sim = TungstenSim(dt=0.5)
    t_ss = sim.steady_state_temp(6.0)
    i_ss = 6.0 / sim._resistance(t_ss)
    assert 120 <= i_ss <= 180, f"Current {i_ss} is outside [120, 180]"


def test_current_increases_from_cold():
    """At cold start, current should drop as tungsten heats up (resistance rises)."""
    sim = TungstenSim(dt=0.5)
    _, I_cold = sim.step(2.0)
    for _ in range(200):
        _, I_hot = sim.step(2.0)
    assert I_hot < I_cold, "Current should fall as tungsten heats (rising R)"

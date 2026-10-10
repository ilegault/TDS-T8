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


def test_current_increases_from_cold():
    """At cold start, current should drop as tungsten heats up (resistance rises)."""
    sim = TungstenSim(dt=0.5)
    _, I_cold = sim.step(2.0)
    for _ in range(200):
        _, I_hot = sim.step(2.0)
    assert I_hot < I_cold, "Current should fall as tungsten heats (rising R)"

def test_cold_resistance_is_realistic():
    """Resistance at 300K should be between 0.004 and 0.006 ohms (from March 2026 run logs)."""
    sim = TungstenSim(dt=0.5)
    r_cold = sim._resistance(300.0)
    assert 0.004 <= r_cold <= 0.006


def test_steady_state_6v_current():
    """At 6.0V steady-state, current should be between 120A and 180A."""
    sim = TungstenSim(dt=0.5)
    t_ss = sim.steady_state_temp(6.0)
    r_ss = sim._resistance(t_ss)
    current = 6.0 / r_ss
    assert 120 <= current <= 180

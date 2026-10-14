"""
Unit tests for safety limits module constants.
"""
from t8_daq_system.settings import safety_limits


def test_safety_limits_values():
    assert safety_limits.CONTROL_PERIOD_S == 0.5
    assert safety_limits.STALE_ALLOWANCE_S == 5.0
    assert safety_limits.PRESSURE_INTERLOCK_TORR == 1e-4
    assert safety_limits.TEMP_OVERRIDE_C == 2200.0
    assert safety_limits.TEMP_OVERRIDE_RESET_C == 2150.0
    assert safety_limits.DAC0_MAX_V == 6.0
    assert safety_limits.PS_CURRENT_CEILING_A == 180.0
    assert safety_limits.RECONNECT_INTERVAL_S == 30.0

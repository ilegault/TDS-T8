"""
Unit tests for SimulatedRig implementing RigAdapter over TungstenSim.
"""
import pytest

from t8_daq_system.rig.adapter import AdapterError, RigAdapter
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.simulated import SimulatedRig
from t8_daq_system.rig.tungsten_model import TungstenSim


def test_simulated_rig_implements_protocol():
    clock = ManualClock()
    rig = SimulatedRig(clock=clock)
    assert isinstance(rig, RigAdapter)
    assert rig.is_connected() is True


def test_cold_start_large_current():
    """At cold start (~20 °C), writing 0.29V draws a large current (> 40.0 A)."""
    clock = ManualClock()
    # At clock start, specimen is at 300K (~26.85 °C)
    rig = SimulatedRig(clock=clock)
    rig.set_output(True)
    rig.write_voltage(0.29)
    readings = rig.read()

    assert readings.ps_amps > 40.0, f"Expected ps_amps > 40.0, got {readings.ps_amps}"


def test_simulated_rig_settles_to_steady_state():
    """For a fixed voltage, SimulatedRig settles to TungstenSim.steady_state_temp within tolerance."""
    clock = ManualClock()
    sim = TungstenSim(dt=0.5)
    target_voltage = 2.0
    expected_t_ss = sim.steady_state_temp(target_voltage)  # Kelvin

    rig = SimulatedRig(clock=clock, tc_names=["TC_1", "TC_2"])
    rig.set_output(True)
    rig.write_voltage(target_voltage)

    # Advance clock in 0.5s ticks until settled
    prev_t = 0.0
    settled_t_k = 0.0
    for _ in range(20000):
        clock.advance(0.5)
        readings = rig.read()
        t_c = readings.tc_c["TC_1"]
        assert t_c is not None
        t_k = t_c + 273.15
        if abs(t_k - prev_t) < 0.01:
            settled_t_k = t_k
            break
        prev_t = t_k

    assert settled_t_k == pytest.approx(expected_t_ss, abs=0.05)


def test_output_false_gives_zero_current_and_cools():
    """set_output(False) gives zero current and the specimen cools toward ambient."""
    clock = ManualClock()
    rig = SimulatedRig(clock=clock, tc_names=["TC_1"])
    rig.set_output(True)
    rig.write_voltage(3.0)

    # Heat up for 100 steps
    for _ in range(100):
        clock.advance(0.5)
        rig.read()

    hot_readings = rig.read()
    assert hot_readings.tc_c["TC_1"] > 100.0  # Hotter than ambient Celsius
    assert hot_readings.ps_amps > 0.0
    assert hot_readings.shutoff_readback is True

    # Turn output off
    rig.set_output(False)

    off_readings = rig.read()
    assert off_readings.ps_amps == 0.0
    assert off_readings.ps_volts == 0.0
    assert off_readings.shutoff_readback is False

    # Specimen cools over time
    for _ in range(200):
        clock.advance(0.5)
        rig.read()

    cooled_readings = rig.read()
    assert cooled_readings.ps_amps == 0.0
    assert cooled_readings.tc_c["TC_1"] < hot_readings.tc_c["TC_1"]


def test_fault_injection_drop_and_restore_tc():
    clock = ManualClock()
    rig = SimulatedRig(clock=clock, tc_names=["TC_1", "TC_2"])
    readings = rig.read()
    assert readings.tc_c["TC_1"] is not None
    assert readings.tc_raw_v["TC_1"] is not None

    rig.drop_tc("TC_1")
    dropped = rig.read()
    assert dropped.tc_c["TC_1"] is None
    assert dropped.tc_raw_v["TC_1"] is None
    # TC_2 should still be intact
    assert dropped.tc_c["TC_2"] is not None

    rig.restore_tc("TC_1")
    restored = rig.read()
    assert restored.tc_c["TC_1"] is not None
    assert restored.tc_raw_v["TC_1"] is not None


def test_fault_injection_pressure_and_stall_gauge():
    clock = ManualClock()
    rig = SimulatedRig(clock=clock, gauge_names=["FRG702_Chamber"])
    readings = rig.read()
    assert readings.pressure_torr["FRG702_Chamber"] == 1e-7
    assert readings.pressure_valid["FRG702_Chamber"] is True

    rig.set_pressure("FRG702_Chamber", 2.5e-5)
    updated = rig.read()
    assert updated.pressure_torr["FRG702_Chamber"] == 2.5e-5
    assert updated.pressure_valid["FRG702_Chamber"] is True

    rig.stall_gauge("FRG702_Chamber")
    stalled = rig.read()
    assert stalled.pressure_valid["FRG702_Chamber"] is False


def test_fault_injection_fail_next_write():
    clock = ManualClock()
    rig = SimulatedRig(clock=clock)
    rig.fail_next_write()

    with pytest.raises(AdapterError, match="Simulated write failure"):
        rig.write_voltage(1.5)

    # Next write should succeed (fails once only)
    rig.write_voltage(1.5)

    # Works similarly for set_output
    rig.fail_next_write()
    with pytest.raises(AdapterError, match="Simulated write failure"):
        rig.set_output(False)
    rig.set_output(False)


def test_fault_injection_disconnect_and_reconnect():
    clock = ManualClock()
    rig = SimulatedRig(clock=clock)
    assert rig.is_connected() is True

    rig.disconnect()
    assert rig.is_connected() is False

    with pytest.raises(AdapterError, match="disconnected"):
        rig.read()

    with pytest.raises(AdapterError, match="disconnected"):
        rig.write_voltage(2.0)

    with pytest.raises(AdapterError, match="disconnected"):
        rig.set_output(True)

    with pytest.raises(AdapterError, match="disconnected"):
        rig.pin_current_limit()

    rig.reconnect()
    assert rig.is_connected() is True
    readings = rig.read()
    assert readings.tc_c["TC_1"] is not None

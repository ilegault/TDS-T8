import unittest
from unittest.mock import MagicMock, call
import sys

# Get the mock ljm that conftest.py already placed in sys.modules
mock_ljm = sys.modules['labjack'].ljm

from t8_daq_system.hardware.keysight_analog_controller import KeysightAnalogController


class TestKeysightAnalogController(unittest.TestCase):
    """Tests for KeysightAnalogController — the LJM-based analog PS interface."""

    def setUp(self):
        mock_ljm.reset_mock()
        mock_ljm.LJMError = type("LJMError", (Exception,), {})
        self.handle = 42  # Dummy LJM handle

        # Create controller with known ratings so scaling maths is easy to verify
        self.controller = KeysightAnalogController(
            self.handle,
            rated_max_volts=60.0,
            rated_max_amps=25.0,
            voltage_limit=20.0,
            current_limit=10.0,
        )

    # ── Initialisation ────────────────────────────────────────────────────────

    def test_init_configures_ain_negative_channels(self):
        """AIN4 and AIN5 must be set to GND reference (199) on init."""
        ain_calls = [c for c in mock_ljm.eWriteName.call_args_list
                     if 'NEGATIVE_CH' in str(c)]
        channels = {c[0][1]: c[0][2] for c in ain_calls}
        self.assertEqual(channels.get('AIN4_NEGATIVE_CH'), 199)
        self.assertEqual(channels.get('AIN5_NEGATIVE_CH'), 199)

    def test_init_enables_analog_mode(self):
        """EIO0 must be pulled LOW (0) on init to select analog programming mode."""
        eio0_calls = [c for c in mock_ljm.eWriteName.call_args_list
                      if c[0][1] == 'EIO0']
        self.assertTrue(eio0_calls, "EIO0 should be written during init")
        self.assertEqual(eio0_calls[0][0][2], 0)

    def test_init_with_none_handle_skips_configuration(self):
        """Passing handle=None must not call any LJM functions."""
        mock_ljm.reset_mock()
        KeysightAnalogController(None, rated_max_volts=60.0, rated_max_amps=25.0)
        mock_ljm.eWriteName.assert_not_called()

    # ── Voltage scaling ───────────────────────────────────────────────────────

    def test_set_voltage_scales_to_dac(self):
        """12 V on a 60 V supply should write exactly 2.0 V to DAC0."""
        # voltage_limit=20 V, so 12 V is within limit; scale = 12/60*10 = 2.0 V
        self.controller.set_voltage(12.0)
        mock_ljm.eWriteName.assert_any_call(self.handle, 'DAC0', 2.0)

    def test_set_voltage_full_scale(self):
        """60 V (full scale) should write 10 V to DAC0 — but only if limit allows."""
        ctrl = KeysightAnalogController(self.handle, rated_max_volts=60.0,
                                        rated_max_amps=25.0, voltage_limit=60.0)
        mock_ljm.reset_mock()
        ctrl.set_voltage(60.0)
        mock_ljm.eWriteName.assert_any_call(self.handle, 'DAC0', 10.0)

    def test_set_voltage_zero(self):
        """0 V should write 0 V to DAC0."""
        self.controller.set_voltage(0.0)
        mock_ljm.eWriteName.assert_any_call(self.handle, 'DAC0', 0.0)

    def test_set_voltage_validates_limit(self):
        """Values above voltage_limit (20 V) must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.controller.set_voltage(25.0)
        self.assertIn("exceeds limit", str(ctx.exception))

    def test_set_voltage_rejects_negative(self):
        """Negative voltages must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.controller.set_voltage(-1.0)
        self.assertIn("cannot be negative", str(ctx.exception))

    def test_set_voltage_returns_true_on_success(self):
        result = self.controller.set_voltage(10.0)
        self.assertTrue(result)

    def test_set_voltage_returns_false_on_ljm_error(self):
        mock_ljm.eWriteName.side_effect = Exception("LJM timeout")
        result = self.controller.set_voltage(10.0)
        self.assertFalse(result)
        mock_ljm.eWriteName.side_effect = None

    # ── Current scaling ───────────────────────────────────────────────────────

    def test_set_current_scales_to_dac(self):
        """5 A on a 25 A supply should write 2.0 V to DAC1."""
        self.controller.set_current(5.0)
        # 5 A / 25 A * 10 V = 2.0 V
        mock_ljm.eWriteName.assert_any_call(self.handle, 'DAC1', 2.0)

    def test_set_current_validates_limit(self):
        """Values above current_limit (10 A) must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.controller.set_current(15.0)
        self.assertIn("exceeds limit", str(ctx.exception))

    def test_set_current_rejects_negative(self):
        with self.assertRaises(ValueError):
            self.controller.set_current(-0.5)

    def test_set_current_returns_true_on_success(self):
        result = self.controller.set_current(5.0)
        self.assertTrue(result)

    # ── Setpoint readback ─────────────────────────────────────────────────────

    def test_get_voltage_setpoint_scales_dac_readback(self):
        """DAC0 returning 5 V should give 30 V setpoint on a 60 V supply."""
        mock_ljm.eReadName.return_value = 5.0
        result = self.controller.get_voltage_setpoint()
        self.assertAlmostEqual(result, 30.0)
        mock_ljm.eReadName.assert_called_with(self.handle, 'DAC0')

    def test_get_current_setpoint_scales_dac_readback(self):
        """DAC1 returning 4 V should give 10 A setpoint on a 25 A supply."""
        mock_ljm.eReadName.return_value = 4.0
        result = self.controller.get_current_setpoint()
        self.assertAlmostEqual(result, 10.0)
        mock_ljm.eReadName.assert_called_with(self.handle, 'DAC1')

    def test_get_voltage_setpoint_returns_none_on_error(self):
        mock_ljm.eReadName.side_effect = Exception("read error")
        result = self.controller.get_voltage_setpoint()
        self.assertIsNone(result)
        mock_ljm.eReadName.side_effect = None

    # ── Monitor readings ──────────────────────────────────────────────────────

    def test_get_voltage_scales_ain_reading(self):
        """AIN4 returning 2.5 V should report 30 V on a 60 V supply (5V monitor range)."""
        mock_ljm.eReadName.return_value = 2.5
        result = self.controller.get_voltage()
        self.assertAlmostEqual(result, 30.0)
        mock_ljm.eReadName.assert_called_with(self.handle, 'AIN4')

    def test_get_current_scales_ain_reading(self):
        """AIN5 returning 4.0 V should report 20 A on a 25 A supply (5V monitor range)."""
        mock_ljm.eReadName.return_value = 4.0
        result = self.controller.get_current()
        self.assertAlmostEqual(result, 20.0)
        mock_ljm.eReadName.assert_called_with(self.handle, 'AIN5')

    def test_get_voltage_returns_none_on_error(self):
        mock_ljm.eReadName.side_effect = Exception("AIN read failed")
        result = self.controller.get_voltage()
        self.assertIsNone(result)
        mock_ljm.eReadName.side_effect = None

    def test_get_current_returns_none_on_error(self):
        mock_ljm.eReadName.side_effect = Exception("AIN read failed")
        result = self.controller.get_current()
        self.assertIsNone(result)
        mock_ljm.eReadName.side_effect = None

    # ── Output enable / disable ───────────────────────────────────────────────

    def test_output_on_deasserts_shutoff_pin(self):
        """output_on() must write 0 to EIO1 (de-assert Shut Off)."""
        self.controller.output_on()
        mock_ljm.eWriteName.assert_any_call(self.handle, 'EIO1', 0)

    def test_output_on_returns_true_on_success(self):
        result = self.controller.output_on()
        self.assertTrue(result)

    def test_output_off_asserts_shutoff_pin(self):
        """output_off() must write 1 to EIO1 (assert Shut Off)."""
        mock_ljm.eReadName.return_value = 1.0  # read-back confirms off
        self.controller.output_off()
        mock_ljm.eWriteName.assert_any_call(self.handle, 'EIO1', 1)

    def test_output_off_returns_true_when_verified(self):
        mock_ljm.eReadName.return_value = 1.0  # EIO1=1 means output is off
        result = self.controller.output_off()
        self.assertTrue(result)

    def test_output_off_retries_until_verified(self):
        """output_off() should retry if the pin read-back still shows output ON."""
        # First two reads say output is still on (EIO1=0), third says off (EIO1=1)
        mock_ljm.reset_mock()
        mock_ljm.eReadName.side_effect = [0.0, 0.0, 1.0]
        result = self.controller.output_off()
        self.assertTrue(result)
        shutoff_writes = [c for c in mock_ljm.eWriteName.call_args_list
                          if c[0][1] == 'EIO1' and c[0][2] == 1]
        self.assertEqual(len(shutoff_writes), 3)
        mock_ljm.eReadName.side_effect = None

    def test_is_output_on_returns_true_when_eio1_is_zero(self):
        """EIO1=0 means Shut Off de-asserted → output is ON."""
        mock_ljm.eReadName.return_value = 0.0
        self.assertTrue(self.controller.is_output_on())

    def test_is_output_on_returns_false_when_eio1_is_one(self):
        """EIO1=1 means Shut Off asserted → output is OFF."""
        mock_ljm.eReadName.return_value = 1.0
        self.assertFalse(self.controller.is_output_on())

    def test_is_output_on_returns_false_on_error(self):
        mock_ljm.eReadName.side_effect = Exception("read error")
        result = self.controller.is_output_on()
        self.assertFalse(result)
        mock_ljm.eReadName.side_effect = None

    # ── Emergency shutdown ────────────────────────────────────────────────────

    def test_emergency_shutdown_zeros_dacs_and_asserts_shutoff(self):
        """emergency_shutdown() must: assert EIO1=1, DAC0=0, DAC1=0."""
        mock_ljm.eReadName.return_value = 1.0  # EIO1 read-back confirms off
        result = self.controller.emergency_shutdown()
        self.assertTrue(result)
        write_calls = {(c[0][1], c[0][2]) for c in mock_ljm.eWriteName.call_args_list}
        self.assertIn(('EIO1', 1), write_calls)
        self.assertIn(('DAC0', 0.0), write_calls)
        self.assertIn(('DAC1', 0.0), write_calls)

    # ── Reset ─────────────────────────────────────────────────────────────────

    def test_reset_zeros_dacs_and_deasserts_shutoff(self):
        """reset() must zero DAC0, DAC1 and write 0 to EIO1."""
        result = self.controller.reset()
        self.assertTrue(result)
        write_calls = {(c[0][1], c[0][2]) for c in mock_ljm.eWriteName.call_args_list}
        self.assertIn(('DAC0', 0.0), write_calls)
        self.assertIn(('DAC1', 0.0), write_calls)
        self.assertIn(('EIO1', 0), write_calls)

    # ── get_readings / get_status ─────────────────────────────────────────────

    def test_get_readings_returns_expected_keys(self):
        mock_ljm.eReadName.return_value = 5.0
        readings = self.controller.get_readings()
        self.assertIn('PS_Voltage', readings)
        self.assertIn('PS_Current', readings)
        self.assertIn('PS_Output_On', readings)

    def test_get_readings_voltage_value(self):
        """AIN4=5 V on 60 V supply → PS_Voltage=60 V (5V monitor range, full scale)."""
        mock_ljm.eReadName.return_value = 5.0
        readings = self.controller.get_readings()
        self.assertAlmostEqual(readings['PS_Voltage'], 60.0)

    def test_get_status_contains_required_keys(self):
        mock_ljm.eReadName.return_value = 0.0
        status = self.controller.get_status()
        for key in ('output_on', 'voltage_setpoint', 'current_setpoint',
                    'voltage_actual', 'current_actual', 'errors', 'in_current_limit'):
            self.assertIn(key, status)

    def test_get_errors_always_empty(self):
        """No error queue on the analog interface."""
        self.assertEqual(self.controller.get_errors(), [])

    def test_is_in_current_limit_always_false(self):
        """No current-limit detection on the analog interface."""
        self.assertFalse(self.controller._is_in_current_limit())

    # ── Limit management ─────────────────────────────────────────────────────

    def test_set_voltage_limit_updates_limit(self):
        self.controller.set_voltage_limit(15.0)
        self.assertEqual(self.controller.voltage_limit, 15.0)
        result = self.controller.set_voltage(14.0)
        self.assertTrue(result)

    def test_set_current_limit_updates_limit(self):
        self.controller.set_current_limit(8.0)
        self.assertEqual(self.controller.current_limit, 8.0)
        result = self.controller.set_current(7.5)
        self.assertTrue(result)

    def test_set_voltage_limit_ignores_zero_or_negative(self):
        self.controller.set_voltage_limit(0)
        self.assertEqual(self.controller.voltage_limit, 20.0)  # unchanged


class TestKeysightAnalogControllerDefaultRatings(unittest.TestCase):
    """Verify default rated_max values and that limits default to rated values."""

    def setUp(self):
        mock_ljm.reset_mock()
        self.handle = 1

    def test_default_limits_equal_rated_max(self):
        ctrl = KeysightAnalogController(self.handle, rated_max_volts=60.0,
                                        rated_max_amps=25.0)
        self.assertEqual(ctrl.voltage_limit, 60.0)
        self.assertEqual(ctrl.current_limit, 25.0)

    def test_explicit_limits_override_rated_max(self):
        ctrl = KeysightAnalogController(self.handle, rated_max_volts=60.0,
                                        rated_max_amps=25.0,
                                        voltage_limit=20.0, current_limit=10.0)
        self.assertEqual(ctrl.voltage_limit, 20.0)
        self.assertEqual(ctrl.current_limit, 10.0)


if __name__ == '__main__':
    unittest.main()

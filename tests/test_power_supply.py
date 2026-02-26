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
        # Now using the new 6V/180A range as default
        self.controller = KeysightAnalogController(
            self.handle,
            rated_max_volts=6.0,
            rated_max_amps=180.0,
            voltage_limit=5.0,
            current_limit=100.0,
        )

    # ── Initialisation ────────────────────────────────────────────────────────

    def test_init_enables_analog_mode(self):
        """EIO0 must be pulled LOW (0) on init to select analog programming mode."""
        eio0_calls = [c for c in mock_ljm.eWriteName.call_args_list
                      if c[0][1] == 'EIO0']
        self.assertTrue(eio0_calls, "EIO0 should be written during init")
        self.assertEqual(eio0_calls[0][0][2], 0)

    def test_init_with_none_handle_skips_configuration(self):
        """Passing handle=None must not call any LJM functions."""
        mock_ljm.reset_mock()
        KeysightAnalogController(None, rated_max_volts=6.0, rated_max_amps=180.0)
        mock_ljm.eWriteName.assert_not_called()

    # ── Voltage scaling ───────────────────────────────────────────────────────

    def test_set_voltage_scales_to_dac(self):
        """3.0 V on a 6.0 V supply should write exactly 2.5 V to DAC0."""
        # voltage_limit=5.0 V, so 3.0 V is within limit; scale = 3/6*5 = 2.5 V
        self.controller.set_voltage(3.0)
        mock_ljm.eWriteName.assert_any_call(self.handle, 'DAC0', 2.5)

    def test_set_voltage_full_scale(self):
        """6.0 V (full scale) should write 5.0 V to DAC0 — but only if limit allows."""
        ctrl = KeysightAnalogController(self.handle, rated_max_volts=6.0,
                                        rated_max_amps=180.0, voltage_limit=6.0)
        mock_ljm.reset_mock()
        # Mock readback to satisfy the new print/read logic in set_voltage
        mock_ljm.eReadName.return_value = 5.0
        ctrl.set_voltage(6.0)
        mock_ljm.eWriteName.assert_any_call(self.handle, 'DAC0', 5.0)

    def test_set_voltage_zero(self):
        """0 V should write 0 V to DAC0."""
        # Mock readback
        mock_ljm.eReadName.return_value = 0.0
        self.controller.set_voltage(0.0)
        mock_ljm.eWriteName.assert_any_call(self.handle, 'DAC0', 0.0)

    def test_set_voltage_validates_limit(self):
        """Values above voltage_limit (5.0 V) must return False."""
        result = self.controller.set_voltage(5.5)
        self.assertFalse(result)

    def test_set_voltage_rejects_negative(self):
        """Negative voltages must return False."""
        result = self.controller.set_voltage(-1.0)
        self.assertFalse(result)

    def test_set_voltage_returns_true_on_success(self):
        # Mock readback
        mock_ljm.eReadName.return_value = 2.5
        result = self.controller.set_voltage(3.0)
        self.assertTrue(result)

    def test_set_voltage_returns_false_on_ljm_error(self):
        mock_ljm.eWriteName.side_effect = Exception("LJM timeout")
        result = self.controller.set_voltage(3.0)
        self.assertFalse(result)
        mock_ljm.eWriteName.side_effect = None

    # ── Current scaling ───────────────────────────────────────────────────────

    def test_set_current_scales_to_dac(self):
        """90 A on a 180 A supply should write 2.5 V to DAC1."""
        # Mock readback
        mock_ljm.eReadName.return_value = 2.5
        self.controller.set_current(90.0)
        # 90 A / 180 A * 5 V = 2.5 V
        mock_ljm.eWriteName.assert_any_call(self.handle, 'DAC1', 2.5)

    def test_set_current_validates_limit(self):
        """Values above current_limit (100 A) must return False."""
        result = self.controller.set_current(110.0)
        self.assertFalse(result)

    def test_set_current_rejects_negative(self):
        result = self.controller.set_current(-0.5)
        self.assertFalse(result)

    def test_set_current_returns_true_on_success(self):
        # Mock readback
        mock_ljm.eReadName.return_value = 2.5
        result = self.controller.set_current(90.0)
        self.assertTrue(result)

    # ── Setpoint readback ─────────────────────────────────────────────────────

    def test_get_voltage_setpoint_scales_dac_readback(self):
        """DAC0 returning 2.5 V should give 3.0 V setpoint on a 6.0 V supply."""
        mock_ljm.eReadName.return_value = 2.5
        result = self.controller.get_voltage_setpoint()
        self.assertAlmostEqual(result, 3.0)
        mock_ljm.eReadName.assert_called_with(self.handle, 'DAC0')

    def test_get_current_setpoint_scales_dac_readback(self):
        """DAC1 returning 2.5 V should give 90.0 A setpoint on a 180.0 A supply."""
        mock_ljm.eReadName.return_value = 2.5
        result = self.controller.get_current_setpoint()
        self.assertAlmostEqual(result, 90.0)
        mock_ljm.eReadName.assert_called_with(self.handle, 'DAC1')

    def test_get_voltage_setpoint_returns_none_on_error(self):
        mock_ljm.eReadName.side_effect = Exception("read error")
        result = self.controller.get_voltage_setpoint()
        self.assertIsNone(result)
        mock_ljm.eReadName.side_effect = None

    # ── Monitor readings ──────────────────────────────────────────────────────

    def test_get_voltage_scales_ain_reading(self):
        """AIN4 returning 2.5 V should report 3.0 V on a 6.0 V supply (5V monitor range)."""
        mock_ljm.eReadName.return_value = 2.5
        result = self.controller.get_voltage()
        self.assertAlmostEqual(result, 3.0)
        mock_ljm.eReadName.assert_called_with(self.handle, 'AIN4')

    def test_get_current_scales_ain_reading(self):
        """AIN5 returning 2.5 V should report 90.0 A on a 180.0 A supply (5V monitor range)."""
        mock_ljm.eReadName.return_value = 2.5
        result = self.controller.get_current()
        self.assertAlmostEqual(result, 90.0)
        mock_ljm.eReadName.assert_called_with(self.handle, 'AIN5')

    def test_get_voltage_scales_ain_reading_switch_up(self):
        """AIN4 returning 5.0 V should report 3.0 V on a 6.0 V supply when switch 4 is UP (10V range)."""
        ctrl_up = KeysightAnalogController(
            self.handle,
            rated_max_volts=6.0,
            rated_max_amps=180.0,
            switch_4_position='up'
        )
        mock_ljm.eReadName.return_value = 5.0
        # 5V / 10V * 6V = 3V
        result = ctrl_up.get_voltage()
        self.assertAlmostEqual(result, 3.0)

    def test_get_current_scales_ain_reading_switch_up(self):
        """AIN5 returning 5.0 V should report 90.0 A on a 180.0 A supply when switch 4 is UP (10V range)."""
        ctrl_up = KeysightAnalogController(
            self.handle,
            rated_max_volts=6.0,
            rated_max_amps=180.0,
            switch_4_position='up'
        )
        mock_ljm.eReadName.return_value = 5.0
        # 5V / 10V * 180A = 90A
        result = ctrl_up.get_current()
        self.assertAlmostEqual(result, 90.0)

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

    def test_get_voltage_safety_warning_above_range(self):
        """A raw AIN reading that maps above 6.5V should trigger a warning print."""
        import io
        from contextlib import redirect_stdout
        # 5.5V / 5.0 * 6.0 = 6.6V — above 6.5V threshold
        mock_ljm.eReadName.return_value = 5.5
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = self.controller.get_voltage()
        output = buf.getvalue()
        self.assertIn("WARNING", output)
        self.assertAlmostEqual(result, 6.6, places=5)

    def test_get_current_safety_warning_above_range(self):
        """A raw AIN reading that maps above 185A should trigger a warning print."""
        import io
        from contextlib import redirect_stdout
        # 5.2V / 5.0 * 180.0 = 187.2A — above 185A threshold
        mock_ljm.eReadName.return_value = 5.2
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = self.controller.get_current()
        output = buf.getvalue()
        self.assertIn("WARNING", output)
        self.assertAlmostEqual(result, 187.2, places=4)

    def test_get_voltage_no_warning_in_range(self):
        """Normal reading (2.5V → 3.0V) must not trigger a WARNING."""
        import io
        from contextlib import redirect_stdout
        mock_ljm.eReadName.return_value = 2.5
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = self.controller.get_voltage()
        self.assertNotIn("WARNING", buf.getvalue())
        self.assertAlmostEqual(result, 3.0)

    def test_get_current_no_warning_in_range(self):
        """Normal reading (2.5V → 90A) must not trigger a WARNING."""
        import io
        from contextlib import redirect_stdout
        mock_ljm.eReadName.return_value = 2.5
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = self.controller.get_current()
        self.assertNotIn("WARNING", buf.getvalue())
        self.assertAlmostEqual(result, 90.0)

    # ── test_keysight_scaling ─────────────────────────────────────────────────

    def test_keysight_scaling_returns_true_with_correct_defaults(self):
        """test_keysight_scaling() must pass for default 6V/180A ratings."""
        result = self.controller.test_keysight_scaling()
        self.assertTrue(result)

    def test_keysight_scaling_prints_expected_voltage_values(self):
        """test_keysight_scaling() output must contain canonical voltage check values."""
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.controller.test_keysight_scaling()
        output = buf.getvalue()
        # 2.5V AIN → 3.000V at 50% scale
        self.assertIn("3.000V", output)
        # 5.0V AIN → 6.000V at full scale
        self.assertIn("6.000V", output)

    def test_keysight_scaling_prints_expected_current_values(self):
        """test_keysight_scaling() output must contain canonical current check values."""
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.controller.test_keysight_scaling()
        output = buf.getvalue()
        # 2.5V AIN → 90.00A at 50% scale
        self.assertIn("90.00A", output)
        # 5.0V AIN → 180.00A at full scale
        self.assertIn("180.00A", output)

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
        """AIN4=5 V on 6.0 V supply → PS_Voltage=6.0 V (5V monitor range, full scale)."""
        mock_ljm.eReadName.return_value = 5.0
        readings = self.controller.get_readings()
        self.assertAlmostEqual(readings['PS_Voltage'], 6.0)

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
        self.controller.set_voltage_limit(5.5)
        self.assertEqual(self.controller.voltage_limit, 5.5)
        # Mock readback to satisfy the new print/read logic in set_voltage
        mock_ljm.eReadName.return_value = 4.583333333
        result = self.controller.set_voltage(5.5)
        self.assertTrue(result)

    def test_set_current_limit_updates_limit(self):
        self.controller.set_current_limit(80.0)
        self.assertEqual(self.controller.current_limit, 80.0)
        # Mock readback
        mock_ljm.eReadName.return_value = 2.0
        result = self.controller.set_current(72.0)
        self.assertTrue(result)

    def test_set_voltage_limit_ignores_zero_or_negative(self):
        self.controller.set_voltage_limit(0)
        self.assertEqual(self.controller.voltage_limit, 5.0)  # unchanged (limit set in setUp)


class TestKeysightAnalogControllerDefaultRatings(unittest.TestCase):
    """Verify default rated_max values and that limits default to rated values."""

    def setUp(self):
        mock_ljm.reset_mock()
        self.handle = 1

    def test_default_limits_equal_rated_max(self):
        ctrl = KeysightAnalogController(self.handle, rated_max_volts=6.0,
                                        rated_max_amps=180.0)
        self.assertEqual(ctrl.voltage_limit, 6.0)
        self.assertEqual(ctrl.current_limit, 180.0)

    def test_explicit_limits_override_rated_max(self):
        ctrl = KeysightAnalogController(self.handle, rated_max_volts=6.0,
                                        rated_max_amps=180.0,
                                        voltage_limit=5.0, current_limit=100.0)
        self.assertEqual(ctrl.voltage_limit, 5.0)
        self.assertEqual(ctrl.current_limit, 100.0)


if __name__ == '__main__':
    unittest.main()

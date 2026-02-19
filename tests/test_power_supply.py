import unittest
from unittest.mock import MagicMock, patch, PropertyMock
import sys

# Use the mocks that conftest.py already placed in sys.modules
mock_pyvisa = sys.modules['pyvisa']

from t8_daq_system.hardware.keysight_connection import KeysightConnection
from t8_daq_system.hardware.power_supply_controller import PowerSupplyController


class TestKeysightConnection(unittest.TestCase):
    """Test cases for KeysightConnection class."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset the mock before each test
        mock_pyvisa.reset_mock()

        # Create mock resource manager and instrument
        self.mock_rm = MagicMock()
        self.mock_instrument = MagicMock()

        # Configure the mock resource manager
        mock_pyvisa.ResourceManager.return_value = self.mock_rm
        self.mock_rm.open_resource.return_value = self.mock_instrument

        # Standard IDN response for N5761A
        self.mock_instrument.query.return_value = "KEYSIGHT TECHNOLOGIES,N5761A,MY12345678,A.01.02\n"

    def test_connect_with_resource_string(self):
        """Test connection with explicit resource string."""
        resource_string = "USB0::0x0957::0x0F07::MY12345678::INSTR"
        conn = KeysightConnection(resource_string=resource_string)

        result = conn.connect()

        self.assertTrue(result)
        self.mock_rm.open_resource.assert_called_with(resource_string, open_timeout=2000)
        self.assertEqual(conn.get_resource_string(), resource_string)

    def test_connect_verifies_identity(self):
        """Test that connection verifies device with *IDN? query."""
        conn = KeysightConnection(resource_string="USB0::...")
        conn.connect()

        self.mock_instrument.query.assert_called_with("*IDN?")

    def test_connect_parses_device_info(self):
        """Test that device info is correctly parsed from IDN response."""
        conn = KeysightConnection(resource_string="USB0::...")
        conn.connect()

        info = conn.get_device_info()

        self.assertEqual(info['manufacturer'], 'KEYSIGHT TECHNOLOGIES')
        self.assertEqual(info['model'], 'N5761A')
        self.assertEqual(info['serial_number'], 'MY12345678')
        self.assertEqual(info['firmware'], 'A.01.02')

    def test_connect_failure_returns_false(self):
        """Test that connection failure returns False."""
        self.mock_rm.open_resource.side_effect = Exception("Connection failed")

        conn = KeysightConnection(resource_string="USB0::...")
        result = conn.connect()

        self.assertFalse(result)
        self.assertIsNone(conn.get_device_info())

    def test_disconnect_turns_off_output(self):
        """Test that disconnect sends OUTP OFF command for safety."""
        conn = KeysightConnection(resource_string="USB0::...")
        conn.connect()
        conn.disconnect()

        self.mock_instrument.write.assert_called_with("OUTP OFF")
        self.mock_instrument.close.assert_called()

    def test_is_connected_returns_true_after_connect(self):
        """Test that is_connected returns True after successful connect (no VISA query)."""
        conn = KeysightConnection(resource_string="USB0::...")
        conn.connect()

        result = conn.is_connected()

        self.assertTrue(result)
        # is_connected should NOT send an additional *IDN? query (only connect does)
        self.assertEqual(self.mock_instrument.query.call_count, 1)

    def test_is_connected_returns_false_after_disconnect(self):
        """Test that is_connected returns False after disconnect."""
        conn = KeysightConnection(resource_string="USB0::...")
        conn.connect()
        self.assertTrue(conn.is_connected())

        conn.disconnect()

        self.assertFalse(conn.is_connected())

    def test_mark_disconnected_clears_connected_state(self):
        """Test that mark_disconnected makes is_connected return False."""
        conn = KeysightConnection(resource_string="USB0::...")
        conn.connect()
        self.assertTrue(conn.is_connected())

        conn.mark_disconnected()

        self.assertFalse(conn.is_connected())

    def test_mark_connected_sets_connected_state(self):
        """Test that mark_connected makes is_connected return True."""
        conn = KeysightConnection(resource_string="USB0::...")
        conn.connect()
        conn.mark_disconnected()
        self.assertFalse(conn.is_connected())

        conn.mark_connected()

        self.assertTrue(conn.is_connected())

    def test_visa_lock_is_acquirable(self):
        """Test that visa_lock property returns an acquirable lock."""
        conn = KeysightConnection(resource_string="USB0::...")
        lock = conn.visa_lock
        self.assertIsNotNone(lock)
        acquired = lock.acquire(blocking=False)
        self.assertTrue(acquired)
        lock.release()

    def test_auto_detect_finds_n5761a(self):
        """Test auto-detection of N5761A power supply."""
        self.mock_rm.list_resources.return_value = (
            "ASRL1::INSTR",
            "USB0::0x0957::0x0F07::MY12345678::INSTR",
        )

        # First resource is not a power supply
        mock_instr1 = MagicMock()
        mock_instr1.query.return_value = "Some Other Device\n"

        # Second resource is the N5761A
        mock_instr2 = MagicMock()
        mock_instr2.query.return_value = "KEYSIGHT,N5761A,MY12345678,A.01.02\n"

        self.mock_rm.open_resource.side_effect = [mock_instr1, mock_instr2]

        conn = KeysightConnection()  # No resource string - will auto-detect
        result = conn.connect()

        self.assertTrue(result)
        self.assertEqual(conn.get_resource_string(), "USB0::0x0957::0x0F07::MY12345678::INSTR")

    def test_list_available_resources(self):
        """Test listing available VISA resources."""
        expected_resources = ("USB0::...", "GPIB0::5::INSTR")
        self.mock_rm.list_resources.return_value = expected_resources

        conn = KeysightConnection()
        resources = conn.list_available_resources()

        self.assertEqual(resources, expected_resources)


class TestPowerSupplyController(unittest.TestCase):
    """Test cases for PowerSupplyController class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_instrument = MagicMock()
        self.controller = PowerSupplyController(
            self.mock_instrument,
            voltage_limit=20.0,
            current_limit=50.0
        )

    def test_set_voltage_sends_command(self):
        """Test that set_voltage sends correct SCPI command."""
        result = self.controller.set_voltage(5.0)

        self.assertTrue(result)
        self.mock_instrument.write.assert_any_call("VOLT 5.0000")

    def test_set_voltage_validates_limit(self):
        """Test that set_voltage rejects values above limit."""
        with self.assertRaises(ValueError) as context:
            self.controller.set_voltage(25.0)

        self.assertIn("exceeds limit", str(context.exception))

    def test_set_voltage_rejects_negative(self):
        """Test that set_voltage rejects negative values."""
        with self.assertRaises(ValueError) as context:
            self.controller.set_voltage(-5.0)

        self.assertIn("cannot be negative", str(context.exception))

    def test_set_current_sends_command(self):
        """Test that set_current sends correct SCPI command."""
        result = self.controller.set_current(10.0)

        self.assertTrue(result)
        self.mock_instrument.write.assert_any_call("CURR 10.0000")

    def test_set_current_validates_limit(self):
        """Test that set_current rejects values above limit."""
        with self.assertRaises(ValueError) as context:
            self.controller.set_current(60.0)

        self.assertIn("exceeds limit", str(context.exception))

    def test_get_voltage_returns_measurement(self):
        """Test that get_voltage queries and returns measured voltage."""
        self.mock_instrument.query.return_value = "5.0234\n"

        result = self.controller.get_voltage()

        self.assertAlmostEqual(result, 5.0234, places=4)
        self.mock_instrument.query.assert_called_with("MEAS:VOLT?")

    def test_get_current_returns_measurement(self):
        """Test that get_current queries and returns measured current."""
        self.mock_instrument.query.return_value = "2.5678\n"

        result = self.controller.get_current()

        self.assertAlmostEqual(result, 2.5678, places=4)
        self.mock_instrument.query.assert_called_with("MEAS:CURR?")

    def test_get_voltage_returns_none_on_error(self):
        """Test that get_voltage returns None on communication error."""
        self.mock_instrument.query.side_effect = Exception("Timeout")

        result = self.controller.get_voltage()

        self.assertIsNone(result)

    def test_output_on_sends_command(self):
        """Test that output_on sends correct SCPI command."""
        result = self.controller.output_on()

        self.assertTrue(result)
        self.mock_instrument.write.assert_called_with("OUTP ON")

    def test_output_off_sends_command(self):
        """Test that output_off sends correct SCPI command."""
        self.mock_instrument.query.return_value = "0"  # Output is off

        result = self.controller.output_off()

        self.assertTrue(result)
        self.mock_instrument.write.assert_called_with("OUTP OFF")

    def test_output_off_retries_on_failure(self):
        """Test that output_off retries if verification fails."""
        # First two attempts fail to verify, third succeeds
        self.mock_instrument.query.side_effect = ["1", "1", "0"]

        # Reset call count after setUp
        self.mock_instrument.write.reset_mock()

        result = self.controller.output_off()

        self.assertTrue(result)
        # Should have called OUTP OFF 3 times (retrying until verified)
        outp_off_calls = [c for c in self.mock_instrument.write.call_args_list if c[0][0] == "OUTP OFF"]
        self.assertEqual(len(outp_off_calls), 3)

    def test_is_output_on_returns_true(self):
        """Test is_output_on returns True when output is enabled."""
        self.mock_instrument.query.return_value = "1"

        result = self.controller.is_output_on()

        self.assertTrue(result)
        self.mock_instrument.query.assert_called_with("OUTP?")

    def test_is_output_on_returns_false(self):
        """Test is_output_on returns False when output is disabled."""
        self.mock_instrument.query.return_value = "0"

        result = self.controller.is_output_on()

        self.assertFalse(result)

    def test_get_status_returns_comprehensive_info(self):
        """Test that get_status returns all status information."""
        self.mock_instrument.query.side_effect = [
            "0",        # OUTP?
            "5.0",      # VOLT?
            "10.0",     # CURR?
            "4.9876",   # MEAS:VOLT?
            "2.3456",   # MEAS:CURR?
            "0,No error",  # SYST:ERR?
            "0",        # STAT:OPER:COND?
        ]

        status = self.controller.get_status()

        self.assertFalse(status['output_on'])
        self.assertAlmostEqual(status['voltage_setpoint'], 5.0)
        self.assertAlmostEqual(status['current_setpoint'], 10.0)
        self.assertAlmostEqual(status['voltage_actual'], 4.9876)
        self.assertAlmostEqual(status['current_actual'], 2.3456)
        self.assertEqual(status['errors'], [])

    def test_emergency_shutdown_disables_output(self):
        """Test that emergency_shutdown turns off output and zeros setpoints."""
        self.mock_instrument.query.return_value = "0"  # Output is off

        result = self.controller.emergency_shutdown()

        self.assertTrue(result)
        # Should have called OUTP OFF, VOLT 0, CURR 0
        calls = [call[0][0] for call in self.mock_instrument.write.call_args_list]
        self.assertIn("OUTP OFF", calls)
        self.assertIn("VOLT 0", calls)
        self.assertIn("CURR 0", calls)

    def test_get_errors_returns_error_list(self):
        """Test that get_errors returns list of errors."""
        self.mock_instrument.query.side_effect = [
            "-100,Command error",
            "-200,Execution error",
            "0,No error",
        ]

        errors = self.controller.get_errors()

        self.assertEqual(len(errors), 2)
        self.assertIn("-100,Command error", errors)
        self.assertIn("-200,Execution error", errors)

    def test_reset_sends_reset_commands(self):
        """Test that reset sends *RST and *CLS commands."""
        result = self.controller.reset()

        self.assertTrue(result)
        calls = [call[0][0] for call in self.mock_instrument.write.call_args_list]
        self.assertIn("*RST", calls)
        self.assertIn("*CLS", calls)

    def test_get_readings_returns_dict(self):
        """Test that get_readings returns properly formatted dict for logging."""
        self.mock_instrument.query.side_effect = ["5.0\n", "2.5\n"]

        readings = self.controller.get_readings()

        self.assertIn('PS_Voltage', readings)
        self.assertIn('PS_Current', readings)
        self.assertAlmostEqual(readings['PS_Voltage'], 5.0)
        self.assertAlmostEqual(readings['PS_Current'], 2.5)

    def test_voltage_setpoint_query(self):
        """Test get_voltage_setpoint queries correct register."""
        self.mock_instrument.query.return_value = "12.5\n"

        result = self.controller.get_voltage_setpoint()

        self.assertAlmostEqual(result, 12.5)
        self.mock_instrument.query.assert_called_with("VOLT?")

    def test_current_setpoint_query(self):
        """Test get_current_setpoint queries correct register."""
        self.mock_instrument.query.return_value = "25.0\n"

        result = self.controller.get_current_setpoint()

        self.assertAlmostEqual(result, 25.0)
        self.mock_instrument.query.assert_called_with("CURR?")


class TestPowerSupplyControllerLimits(unittest.TestCase):
    """Test cases for voltage/current limit functionality."""

    def setUp(self):
        """Set up test fixtures with custom limits."""
        self.mock_instrument = MagicMock()
        self.controller = PowerSupplyController(
            self.mock_instrument,
            voltage_limit=10.0,
            current_limit=5.0
        )

    def test_custom_voltage_limit_enforced(self):
        """Test that custom voltage limit is enforced."""
        # Should succeed at limit
        result = self.controller.set_voltage(10.0)
        self.assertTrue(result)

        # Should fail above limit
        with self.assertRaises(ValueError):
            self.controller.set_voltage(10.1)

    def test_custom_current_limit_enforced(self):
        """Test that custom current limit is enforced."""
        # Should succeed at limit
        result = self.controller.set_current(5.0)
        self.assertTrue(result)

        # Should fail above limit
        with self.assertRaises(ValueError):
            self.controller.set_current(5.1)

    def test_update_voltage_limit(self):
        """Test that voltage limit can be updated."""
        self.controller.set_voltage_limit(15.0)

        # Now 12V should work
        result = self.controller.set_voltage(12.0)
        self.assertTrue(result)

    def test_update_current_limit(self):
        """Test that current limit can be updated."""
        self.controller.set_current_limit(10.0)

        # Now 8A should work
        result = self.controller.set_current(8.0)
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()

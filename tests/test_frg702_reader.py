"""
Unit tests for FRG702Reader class - logarithmic voltage-to-pressure conversion.
Tests the conversion logic without requiring hardware dependencies.
"""

import unittest
from t8_daq_system.hardware.frg702_reader import (
    FRG702Reader,
    STATUS_SENSOR_ERROR_NO_SUPPLY,
    STATUS_UNDERRANGE,
    STATUS_OVERRANGE,
    STATUS_SENSOR_ERROR_PIRANI_DEFECTIVE,
    STATUS_VALID,
    MODE_PIRANI_ONLY,
    MODE_COMBINED,
    MODE_UNKNOWN,
)


class TestFRG702VoltageToPresure(unittest.TestCase):
    """Test the logarithmic voltage-to-pressure conversion formula."""

    def test_voltage_5v_gives_1e_minus_3_mbar(self):
        """5.0V should give approximately 1.0e-3 mbar per the manual."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(5.0)
        self.assertEqual(status, STATUS_VALID)
        # p = 10^(1.667 * 5.0 - 11.33) = 10^(8.335 - 11.33) = 10^(-2.995)
        # ≈ 1.012e-3
        self.assertAlmostEqual(pressure, 1.0e-3, delta=0.05e-3)

    def test_voltage_6_8v_gives_1_mbar(self):
        """6.8V should give approximately 1.0 mbar per the manual."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(6.8)
        self.assertEqual(status, STATUS_VALID)
        # p = 10^(1.667 * 6.8 - 11.33) = 10^(11.3356 - 11.33) = 10^(0.0056)
        # ≈ 1.013
        self.assertAlmostEqual(pressure, 1.0, delta=0.1)

    def test_voltage_1_82v_gives_5e_minus_9_mbar(self):
        """1.82V (lower range limit) should give approximately 5.0e-9 mbar."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(1.82)
        self.assertEqual(status, STATUS_VALID)
        # p = 10^(1.667 * 1.82 - 11.33) = 10^(3.03394 - 11.33) = 10^(-8.29606)
        # ≈ 5.06e-9
        self.assertAlmostEqual(pressure, 5.0e-9, delta=1.0e-9)

    def test_voltage_8_6v_gives_1000_mbar(self):
        """8.6V (upper range limit) should give approximately 1000 mbar."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(8.6)
        self.assertEqual(status, STATUS_VALID)
        # p = 10^(1.667 * 8.6 - 11.33) = 10^(14.3362 - 11.33) = 10^(3.0062)
        # ≈ 1014
        self.assertAlmostEqual(pressure, 1000, delta=50)


class TestFRG702ErrorStates(unittest.TestCase):
    """Test error/status detection based on voltage ranges."""

    def test_voltage_0_3v_sensor_error_no_supply(self):
        """Voltage < 0.5V should return sensor error - no supply."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(0.3)
        self.assertIsNone(pressure)
        self.assertEqual(status, STATUS_SENSOR_ERROR_NO_SUPPLY)

    def test_voltage_0v_sensor_error_no_supply(self):
        """0V should return sensor error - no supply."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(0.0)
        self.assertIsNone(pressure)
        self.assertEqual(status, STATUS_SENSOR_ERROR_NO_SUPPLY)

    def test_voltage_1_0v_underrange(self):
        """Voltage between 0.5V and 1.82V should return underrange."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(1.0)
        self.assertIsNone(pressure)
        self.assertEqual(status, STATUS_UNDERRANGE)

    def test_voltage_0_5v_underrange(self):
        """0.5V exactly should return underrange."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(0.5)
        self.assertIsNone(pressure)
        self.assertEqual(status, STATUS_UNDERRANGE)

    def test_voltage_9_0v_overrange(self):
        """Voltage between 8.6V and 9.5V should return overrange."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(9.0)
        self.assertIsNone(pressure)
        self.assertEqual(status, STATUS_OVERRANGE)

    def test_voltage_10_0v_pirani_defective(self):
        """Voltage > 9.5V should return Pirani defective."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(10.0)
        self.assertIsNone(pressure)
        self.assertEqual(status, STATUS_SENSOR_ERROR_PIRANI_DEFECTIVE)

    def test_voltage_10_5v_pirani_defective(self):
        """High voltage should return Pirani defective."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(10.5)
        self.assertIsNone(pressure)
        self.assertEqual(status, STATUS_SENSOR_ERROR_PIRANI_DEFECTIVE)


class TestFRG702UnitConversions(unittest.TestCase):
    """Test mbar to Torr and Pa conversions."""

    def test_mbar_no_conversion(self):
        """mbar to mbar should be identity."""
        result = FRG702Reader.convert_pressure(1.0, 'mbar')
        self.assertEqual(result, 1.0)

    def test_mbar_to_torr(self):
        """1 mbar = 0.750062 Torr."""
        result = FRG702Reader.convert_pressure(1.0, 'Torr')
        self.assertAlmostEqual(result, 0.750062, places=5)

    def test_mbar_to_pa(self):
        """1 mbar = 100 Pa."""
        result = FRG702Reader.convert_pressure(1.0, 'Pa')
        self.assertAlmostEqual(result, 100.0, places=1)

    def test_atmospheric_pressure_torr(self):
        """1013.25 mbar (1 atm) should be ~760 Torr."""
        result = FRG702Reader.convert_pressure(1013.25, 'Torr')
        self.assertAlmostEqual(result, 760, delta=1)

    def test_small_pressure_torr(self):
        """Verify conversion works for very small pressures."""
        result = FRG702Reader.convert_pressure(1.0e-6, 'Torr')
        self.assertAlmostEqual(result, 7.50062e-7, delta=1e-10)

    def test_small_pressure_pa(self):
        """Verify conversion works for very small pressures in Pa."""
        result = FRG702Reader.convert_pressure(1.0e-6, 'Pa')
        self.assertAlmostEqual(result, 1.0e-4, delta=1e-8)


class TestFRG702OperatingMode(unittest.TestCase):
    """Test operating mode detection from Pin 6 status voltage."""

    def test_low_voltage_pirani_only(self):
        """~0V on Pin 6 means Pirani-only mode."""
        mode = FRG702Reader.read_operating_mode(0.0)
        self.assertEqual(mode, MODE_PIRANI_ONLY)

    def test_high_voltage_combined_mode(self):
        """High voltage on Pin 6 means combined mode."""
        mode = FRG702Reader.read_operating_mode(10.0)
        self.assertEqual(mode, MODE_COMBINED)

    def test_none_voltage_unknown(self):
        """None voltage returns unknown mode."""
        mode = FRG702Reader.read_operating_mode(None)
        self.assertEqual(mode, MODE_UNKNOWN)

    def test_mid_voltage_pirani_only(self):
        """Voltage below 5V is still Pirani-only."""
        mode = FRG702Reader.read_operating_mode(2.0)
        self.assertEqual(mode, MODE_PIRANI_ONLY)


class TestFRG702BoundaryValues(unittest.TestCase):
    """Test boundary conditions at voltage thresholds."""

    def test_boundary_valid_low(self):
        """1.82V is the lowest valid voltage."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(1.82)
        self.assertEqual(status, STATUS_VALID)
        self.assertIsNotNone(pressure)

    def test_boundary_valid_high(self):
        """8.6V is the highest valid voltage."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(8.6)
        self.assertEqual(status, STATUS_VALID)
        self.assertIsNotNone(pressure)

    def test_boundary_underrange_high(self):
        """Just below 1.82V should be underrange."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(1.81)
        self.assertEqual(status, STATUS_UNDERRANGE)
        self.assertIsNone(pressure)

    def test_boundary_overrange_low(self):
        """Just above 8.6V should be overrange."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(8.61)
        self.assertEqual(status, STATUS_OVERRANGE)
        self.assertIsNone(pressure)

    def test_boundary_overrange_high(self):
        """9.5V is still overrange."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(9.5)
        self.assertEqual(status, STATUS_OVERRANGE)
        self.assertIsNone(pressure)

    def test_boundary_pirani_defective_low(self):
        """Just above 9.5V should be Pirani defective."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(9.51)
        self.assertEqual(status, STATUS_SENSOR_ERROR_PIRANI_DEFECTIVE)
        self.assertIsNone(pressure)


class TestFRG702PrecisionNotRounded(unittest.TestCase):
    """Verify that FRG-702 readings are NOT rounded to 2 decimal places."""

    def test_small_pressure_not_rounded_to_zero(self):
        """Pressures like 5e-9 must not round to 0.0."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(1.82)
        self.assertEqual(status, STATUS_VALID)
        self.assertGreater(pressure, 0.0)
        # Should be on the order of 5e-9, not 0.00
        self.assertLess(pressure, 1e-7)

    def test_medium_small_pressure_preserved(self):
        """Pressures like 1e-3 should retain their precision."""
        pressure, status = FRG702Reader.voltage_to_pressure_mbar(5.0)
        self.assertEqual(status, STATUS_VALID)
        self.assertGreater(pressure, 1e-4)
        self.assertLess(pressure, 1e-2)


if __name__ == '__main__':
    unittest.main()

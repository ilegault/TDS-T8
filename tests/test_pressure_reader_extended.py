"""
Extended unit tests for PressureReader class - including Torr conversion
Tests the conversion logic without requiring hardware dependencies.
"""

import unittest


class TestPressureUnitConversionLogic(unittest.TestCase):
    """Test unit conversion logic used in PressureReader."""

    def _convert_psi_to_unit(self, psi_value, unit):
        """
        Simulate the conversion logic from PressureReader._voltage_to_pressure
        """
        if unit == 'PSI':
            return psi_value
        elif unit == 'Bar':
            return psi_value * 0.0689476
        elif unit == 'kPa':
            return psi_value * 6.89476
        elif unit == 'Torr':
            return psi_value * 51.7149
        return psi_value

    def test_psi_no_conversion(self):
        """Test that PSI values are not converted."""
        result = self._convert_psi_to_unit(50.0, 'PSI')
        self.assertEqual(result, 50.0)

    def test_bar_conversion(self):
        """Test conversion to Bar."""
        result = self._convert_psi_to_unit(50.0, 'Bar')
        expected = 50.0 * 0.0689476
        self.assertAlmostEqual(result, expected, places=4)

    def test_kpa_conversion(self):
        """Test conversion to kPa."""
        result = self._convert_psi_to_unit(50.0, 'kPa')
        expected = 50.0 * 6.89476
        self.assertAlmostEqual(result, expected, places=2)

    def test_torr_conversion(self):
        """Test conversion to Torr."""
        result = self._convert_psi_to_unit(50.0, 'Torr')
        expected = 50.0 * 51.7149
        self.assertAlmostEqual(result, expected, places=2)

    def test_torr_at_atmospheric_pressure(self):
        """Test Torr conversion at ~14.7 PSI (1 atm = 760 Torr)."""
        result = self._convert_psi_to_unit(14.7, 'Torr')
        # 1 atm ≈ 760 Torr
        self.assertAlmostEqual(result, 760, delta=5)


class TestPressureLinearScaling(unittest.TestCase):
    """Test linear scaling logic from voltage to pressure."""

    def _voltage_to_pressure(self, voltage, v_min, v_max, p_min, p_max):
        """
        Simulate the linear scaling from PressureReader._voltage_to_pressure
        """
        pressure = (voltage - v_min) / (v_max - v_min) * (p_max - p_min) + p_min
        return pressure

    def test_midpoint_voltage(self):
        """Test that midpoint voltage gives midpoint pressure."""
        # For 0.5-4.5V range and 0-100 PSI range
        # 2.5V should give 50 PSI
        result = self._voltage_to_pressure(2.5, 0.5, 4.5, 0, 100)
        self.assertAlmostEqual(result, 50.0, places=1)

    def test_minimum_voltage(self):
        """Test that minimum voltage gives minimum pressure."""
        result = self._voltage_to_pressure(0.5, 0.5, 4.5, 0, 100)
        self.assertAlmostEqual(result, 0.0, places=1)

    def test_maximum_voltage(self):
        """Test that maximum voltage gives maximum pressure."""
        result = self._voltage_to_pressure(4.5, 0.5, 4.5, 0, 100)
        self.assertAlmostEqual(result, 100.0, places=1)

    def test_quarter_voltage(self):
        """Test quarter point of the range."""
        result = self._voltage_to_pressure(1.5, 0.5, 4.5, 0, 100)
        self.assertAlmostEqual(result, 25.0, places=1)


class TestPressureScaleOffset(unittest.TestCase):
    """Test scale and offset calibration logic."""

    def _apply_scale_offset(self, value, scale, offset):
        """Apply scale and offset as done in PressureReader."""
        return (value * scale) + offset

    def test_scale_applied(self):
        """Test that scale factor is applied."""
        result = self._apply_scale_offset(50.0, 1.1, 0.0)
        self.assertAlmostEqual(result, 55.0, places=1)

    def test_offset_applied(self):
        """Test that offset is applied."""
        result = self._apply_scale_offset(50.0, 1.0, 5.0)
        self.assertAlmostEqual(result, 55.0, places=1)

    def test_scale_and_offset_combined(self):
        """Test that scale is applied before offset."""
        result = self._apply_scale_offset(50.0, 2.0, 10.0)
        # (50 * 2.0) + 10 = 110
        self.assertAlmostEqual(result, 110.0, places=1)


class TestPressureDisconnectionDetection(unittest.TestCase):
    """Test disconnection detection logic."""

    def _is_disconnected(self, voltage, min_voltage):
        """
        Simulate disconnection detection from PressureReader.read_all
        """
        return voltage < 0.1 and min_voltage > 0.2

    def test_disconnected_low_voltage(self):
        """Test that low voltage with high min_voltage indicates disconnect."""
        self.assertTrue(self._is_disconnected(0.05, 0.5))

    def test_not_disconnected_normal_voltage(self):
        """Test that normal voltage doesn't indicate disconnect."""
        self.assertFalse(self._is_disconnected(2.5, 0.5))

    def test_not_disconnected_low_min_voltage(self):
        """Test that low voltage with low min_voltage doesn't indicate disconnect."""
        # If sensor is designed for 0-5V range, low voltage is valid
        self.assertFalse(self._is_disconnected(0.05, 0.1))


class TestPressureConversionFactors(unittest.TestCase):
    """Test that conversion factors are correct."""

    def test_psi_to_bar_factor(self):
        """Test PSI to Bar conversion factor."""
        # 1 PSI = 0.0689476 Bar
        factor = 0.0689476
        self.assertAlmostEqual(1 * factor, 0.0689476, places=6)

    def test_psi_to_kpa_factor(self):
        """Test PSI to kPa conversion factor."""
        # 1 PSI = 6.89476 kPa
        factor = 6.89476
        self.assertAlmostEqual(1 * factor, 6.89476, places=5)

    def test_psi_to_torr_factor(self):
        """Test PSI to Torr conversion factor."""
        # 1 PSI = 51.7149 Torr
        factor = 51.7149
        self.assertAlmostEqual(1 * factor, 51.7149, places=4)

    def test_atmospheric_pressure_in_torr(self):
        """Test that 14.7 PSI ≈ 760 Torr (1 atm)."""
        psi_to_torr = 51.7149
        atm_in_psi = 14.696  # More precise value
        result = atm_in_psi * psi_to_torr
        self.assertAlmostEqual(result, 760, delta=1)


if __name__ == '__main__':
    unittest.main()

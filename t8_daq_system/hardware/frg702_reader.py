"""
frg702_reader.py
PURPOSE: Read Leybold FRG-702 full-range gauge (Pirani + Cold Cathode)
KEY CONCEPT: Logarithmic voltage-to-pressure conversion: p = 10^(1.667 * U - 11.33)
Valid voltage range: 1.82V to 8.6V, covering 5e-9 to 1000 mbar
"""

from labjack import ljm


# Status constants returned instead of numeric pressure when out of valid range
STATUS_SENSOR_ERROR_NO_SUPPLY = "sensor error - no supply"
STATUS_UNDERRANGE = "underrange"
STATUS_OVERRANGE = "overrange"
STATUS_SENSOR_ERROR_PIRANI_DEFECTIVE = "sensor error - Pirani defective"
STATUS_VALID = "valid"

# Operating mode constants from Pin 6 status channel
MODE_PIRANI_ONLY = "Pirani-only"
MODE_COMBINED = "Combined Pirani/Cold Cathode"
MODE_UNKNOWN = "Unknown"

# Unit conversion factors from mbar
UNIT_CONVERSIONS = {
    'mbar': 1.0,
    'Torr': 0.750062,
    'Pa': 100.0,
}


class FRG702Reader:
    def __init__(self, handle, frg702_config_list):
        """
        Initialize FRG-702 gauge reader.

        Args:
            handle: The LabJack connection handle
            frg702_config_list: List of FRG-702 gauge configs from JSON
        """
        self.handle = handle
        self.gauges = frg702_config_list
        self._configure_channels()

    def _configure_channels(self):
        """Set appropriate voltage ranges for FRG-702 gauges."""
        for gauge in self.gauges:
            if not gauge['enabled']:
                continue

            channel = gauge['channel']
            range_name = f"AIN{channel}_RANGE"

            try:
                # FRG-702 outputs up to 10.5V — must use +/-10V range
                ljm.eWriteName(self.handle, range_name, 10.0)
            except ljm.LJMError as e:
                print(f"Error configuring FRG-702 {gauge['name']} on AIN{channel}: {e}")
                raise e

            # Configure status channel if available
            status_channel = gauge.get('status_channel')
            if status_channel is not None:
                status_range_name = f"AIN{status_channel}_RANGE"
                try:
                    # Pin 6 can read 0-30V, use +/-10V range (will clip at ~10V
                    # but we only need to distinguish ~0V vs 15-30V)
                    ljm.eWriteName(self.handle, status_range_name, 10.0)
                except ljm.LJMError as e:
                    print(f"Error configuring FRG-702 status channel AIN{status_channel}: {e}")

    @staticmethod
    def voltage_to_pressure_mbar(voltage):
        """
        Convert FRG-702 voltage to pressure in mbar using logarithmic formula.

        Formula from manual: p = 10^(1.667 * U - 11.33)

        Args:
            voltage: Raw voltage reading in volts

        Returns:
            Tuple of (pressure_mbar or None, status_string)
            pressure_mbar is None for error/out-of-range states
        """
        if voltage < 0.5:
            return None, STATUS_SENSOR_ERROR_NO_SUPPLY
        elif voltage < 1.82:
            return None, STATUS_UNDERRANGE
        elif voltage <= 8.6:
            pressure_mbar = 10 ** (1.667 * voltage - 11.33)
            return pressure_mbar, STATUS_VALID
        elif voltage <= 9.5:
            return None, STATUS_OVERRANGE
        else:
            return None, STATUS_SENSOR_ERROR_PIRANI_DEFECTIVE

    @staticmethod
    def convert_pressure(mbar_value, to_unit):
        """
        Convert pressure from mbar to the specified unit.

        Args:
            mbar_value: Pressure in mbar
            to_unit: Target unit ('mbar', 'Torr', or 'Pa')

        Returns:
            Converted pressure value
        """
        factor = UNIT_CONVERSIONS.get(to_unit, 1.0)
        return mbar_value * factor

    @staticmethod
    def read_operating_mode(voltage):
        """
        Determine operating mode from Pin 6 status voltage.

        Args:
            voltage: Voltage read from Pin 6

        Returns:
            Operating mode string
        """
        if voltage is None:
            return MODE_UNKNOWN
        if voltage < 5.0:
            return MODE_PIRANI_ONLY
        else:
            # 15-30V indicates cold cathode active, but T8 clips at ~10V
            # so anything above ~5V means the pin is high
            return MODE_COMBINED

    def read_all(self):
        """
        Read all enabled FRG-702 gauges.

        Returns:
            dict like {'FRG702_Chamber': 1.5e-6} or {'FRG702_Chamber': None}
            Values are pressure in mbar, or None for error states.
        """
        readings = {}

        for gauge in self.gauges:
            if not gauge['enabled']:
                continue

            channel = gauge['channel']
            read_name = f"AIN{channel}"

            try:
                voltage = ljm.eReadName(self.handle, read_name)
                pressure_mbar, status = self.voltage_to_pressure_mbar(voltage)

                if status == STATUS_VALID:
                    readings[gauge['name']] = pressure_mbar
                else:
                    readings[gauge['name']] = None

            except ljm.LJMError as e:
                print(f"Error reading {gauge['name']}: {e}")
                readings[gauge['name']] = None

        return readings

    def read_all_with_status(self):
        """
        Read all enabled FRG-702 gauges, returning pressure, status, and mode.

        Returns:
            dict like {'FRG702_Chamber': {'pressure': 1.5e-6, 'status': 'valid', 'mode': 'Combined Pirani/Cold Cathode'}}
        """
        readings = {}

        for gauge in self.gauges:
            if not gauge['enabled']:
                continue

            channel = gauge['channel']
            read_name = f"AIN{channel}"

            try:
                voltage = ljm.eReadName(self.handle, read_name)
                pressure_mbar, status = self.voltage_to_pressure_mbar(voltage)

                # Read operating mode from status channel if configured
                mode = MODE_UNKNOWN
                status_channel = gauge.get('status_channel')
                if status_channel is not None:
                    try:
                        status_voltage = ljm.eReadName(self.handle, f"AIN{status_channel}")
                        mode = self.read_operating_mode(status_voltage)
                    except ljm.LJMError:
                        mode = MODE_UNKNOWN

                readings[gauge['name']] = {
                    'pressure': pressure_mbar,
                    'status': status,
                    'mode': mode,
                    'voltage': voltage,
                }

            except ljm.LJMError as e:
                print(f"Error reading {gauge['name']}: {e}")
                readings[gauge['name']] = {
                    'pressure': None,
                    'status': 'error',
                    'mode': MODE_UNKNOWN,
                    'voltage': None,
                }

        return readings

    def read_single(self, channel_name):
        """
        Read just one FRG-702 gauge by name.

        Args:
            channel_name: Name of the gauge to read

        Returns:
            Pressure in mbar, or None if not found/error
        """
        for gauge in self.gauges:
            if gauge['name'] == channel_name and gauge['enabled']:
                read_name = f"AIN{gauge['channel']}"
                try:
                    voltage = ljm.eReadName(self.handle, read_name)
                    pressure_mbar, status = self.voltage_to_pressure_mbar(voltage)
                    return pressure_mbar
                except ljm.LJMError as e:
                    print(f"Error reading {channel_name}: {e}")
                    return None
        return None

    def read_raw_voltage(self, channel_name):
        """
        Read raw voltage from an FRG-702 gauge (for debugging).

        Args:
            channel_name: Name of the gauge

        Returns:
            Raw voltage value or None
        """
        for gauge in self.gauges:
            if gauge['name'] == channel_name and gauge['enabled']:
                read_name = f"AIN{gauge['channel']}"
                try:
                    return ljm.eReadName(self.handle, read_name)
                except ljm.LJMError as e:
                    print(f"Error reading {channel_name}: {e}")
                    return None
        return None

    def get_enabled_channels(self):
        """Get list of enabled FRG-702 gauge names."""
        return [g['name'] for g in self.gauges if g['enabled']]

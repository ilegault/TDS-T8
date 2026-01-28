"""
pressure_reader.py
PURPOSE: Read pressure transducers (voltage output sensors)
KEY CONCEPT: Pressure sensors output 0.5-4.5V (or similar) that we scale to PSI
"""

from labjack import ljm


class PressureReader:
    def __init__(self, handle, pressure_config_list):
        """
        Initialize pressure reader.

        Args:
            handle: The LabJack connection handle
            pressure_config_list: List of pressure sensor configs from JSON
        """
        self.handle = handle
        self.sensors = pressure_config_list
        self._configure_channels()

    def _configure_channels(self):
        """Set appropriate voltage ranges for pressure sensors."""
        for sensor in self.sensors:
            if not sensor['enabled']:
                continue

            channel = sensor['channel']
            range_name = f"AIN{channel}_RANGE"

            # Most pressure transducers output 0-5V or 0-10V
            # Use +/-10V range to be safe
            ljm.eWriteName(self.handle, range_name, 10.0)

    def _voltage_to_pressure(self, voltage, sensor_config):
        """
        Convert voltage reading to pressure units.
        Uses linear scaling: pressure = (voltage - v_min) / (v_max - v_min) * (p_max - p_min) + p_min

        Args:
            voltage: Raw voltage reading
            sensor_config: Sensor configuration dict

        Returns:
            Pressure value in configured units
        """
        v_min = sensor_config['min_voltage']
        v_max = sensor_config['max_voltage']
        p_min = sensor_config['min_pressure']
        p_max = sensor_config['max_pressure']

        # Linear interpolation
        pressure = (voltage - v_min) / (v_max - v_min) * (p_max - p_min) + p_min
        return round(pressure, 2)

    def read_all(self):
        """
        Read all enabled pressure sensors.

        Returns:
            dict like {'P1_Chamber': 45.2}
        """
        readings = {}

        for sensor in self.sensors:
            if not sensor['enabled']:
                continue

            channel = sensor['channel']
            read_name = f"AIN{channel}"  # Plain AIN read for voltage

            try:
                voltage = ljm.eReadName(self.handle, read_name)
                pressure = self._voltage_to_pressure(voltage, sensor)
                readings[sensor['name']] = pressure

            except ljm.LJMError as e:
                print(f"Error reading {sensor['name']}: {e}")
                readings[sensor['name']] = None

        return readings

    def read_single(self, channel_name):
        """
        Read just one pressure sensor by name.

        Args:
            channel_name: Name of the pressure sensor to read

        Returns:
            Pressure value or None if not found/error
        """
        for sensor in self.sensors:
            if sensor['name'] == channel_name and sensor['enabled']:
                read_name = f"AIN{sensor['channel']}"
                try:
                    voltage = ljm.eReadName(self.handle, read_name)
                    return self._voltage_to_pressure(voltage, sensor)
                except ljm.LJMError as e:
                    print(f"Error reading {channel_name}: {e}")
                    return None
        return None

    def read_raw_voltage(self, channel_name):
        """
        Read raw voltage from a pressure sensor (for debugging).

        Args:
            channel_name: Name of the pressure sensor

        Returns:
            Raw voltage value or None
        """
        for sensor in self.sensors:
            if sensor['name'] == channel_name and sensor['enabled']:
                read_name = f"AIN{sensor['channel']}"
                try:
                    return ljm.eReadName(self.handle, read_name)
                except ljm.LJMError as e:
                    print(f"Error reading {channel_name}: {e}")
                    return None
        return None

    def get_enabled_channels(self):
        """Get list of enabled pressure sensor names."""
        return [s['name'] for s in self.sensors if s['enabled']]

"""
thermocouple_reader.py
PURPOSE: Read thermocouple temperatures from T8
KEY CONCEPT: T8 has "Extended Features" (EF) that do the math automatically
"""

from labjack import ljm


class ThermocoupleReader:
    # Thermocouple type codes for AIN_EF_INDEX register
    TC_TYPES = {
        'B': 20, 'E': 21, 'J': 22, 'K': 23,
        'N': 24, 'R': 25, 'S': 26, 'T': 27
    }

    def __init__(self, handle, tc_config_list):
        """
        Initialize thermocouple reader.

        Args:
            handle: The LabJack connection handle
            tc_config_list: List of thermocouple configs from JSON
        """
        self.handle = handle
        self.thermocouples = tc_config_list
        self._configure_channels()

    def _configure_channels(self):
        """
        Set up each thermocouple channel on the T8.
        This tells the T8 "this channel has a Type K thermocouple"
        """
        for tc in self.thermocouples:
            if not tc['enabled']:
                continue

            channel = tc['channel']
            tc_type = tc['type']

            # These are the register names we write to configure
            # AIN#_EF_INDEX = what type of extended feature
            # AIN#_EF_CONFIG_A = output units (0=K, 1=C, 2=F)

            index_name = f"AIN{channel}_EF_INDEX"
            config_name = f"AIN{channel}_EF_CONFIG_A"
            range_name = f"AIN{channel}_RANGE"

            # Set the voltage range (thermocouples use small voltages)
            ljm.eWriteName(self.handle, range_name, 0.075)  # +/-75mV range

            # Set the thermocouple type
            ljm.eWriteName(self.handle, index_name, self.TC_TYPES[tc_type])

            # Set output units: 0=Kelvin, 1=Celsius, 2=Fahrenheit
            units_code = {'K': 0, 'C': 1, 'F': 2}.get(tc['units'], 1)
            ljm.eWriteName(self.handle, config_name, units_code)

    def read_all(self):
        """
        Read all enabled thermocouples.

        Returns:
            dict like {'TC1_Inlet': 25.3, 'TC2_Outlet': 28.1}
        """
        readings = {}

        for tc in self.thermocouples:
            if not tc['enabled']:
                continue

            channel = tc['channel']
            # Reading AIN#_EF_READ_A gives us the temperature
            read_name = f"AIN{channel}_EF_READ_A"

            try:
                temp = ljm.eReadName(self.handle, read_name)

                # -9999 means the thermocouple isn't connected
                if temp == -9999:
                    readings[tc['name']] = None
                else:
                    readings[tc['name']] = round(temp, 2)

            except ljm.LJMError as e:
                print(f"Error reading {tc['name']}: {e}")
                readings[tc['name']] = None

        return readings

    def read_single(self, channel_name):
        """
        Read just one thermocouple by name.

        Args:
            channel_name: Name of the thermocouple to read

        Returns:
            Temperature value or None if not found/error
        """
        for tc in self.thermocouples:
            if tc['name'] == channel_name and tc['enabled']:
                read_name = f"AIN{tc['channel']}_EF_READ_A"
                try:
                    temp = ljm.eReadName(self.handle, read_name)
                    if temp == -9999:
                        return None
                    return round(temp, 2)
                except ljm.LJMError as e:
                    print(f"Error reading {channel_name}: {e}")
                    return None
        return None

    def get_enabled_channels(self):
        """Get list of enabled thermocouple names."""
        return [tc['name'] for tc in self.thermocouples if tc['enabled']]

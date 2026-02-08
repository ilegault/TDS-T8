"""
thermocouple_reader.py
PURPOSE: Read thermocouple temperatures from T8
KEY CONCEPT: T8 has "Extended Features" (EF) that do the math automatically
"""

from labjack import ljm


class ThermocoupleReader:
    # Thermocouple type codes for AIN_EF_INDEX register
    TC_TYPES = {
        'E': 20, 'J': 21, 'K': 22, 'R': 23,
        'T': 24, 'S': 25, 'N': 27, 'B': 28,
        'C': 30
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

            try:
                # Set the voltage range (thermocouples use small voltages)
                ljm.eWriteName(self.handle, range_name, 0.1)  # ±100mV range

                # Set the thermocouple type
                ljm.eWriteName(self.handle, index_name, self.TC_TYPES[tc_type])

                # Set output units: always Celsius (1) for internal consistency
                # Conversion for display is handled in the GUI
                ljm.eWriteName(self.handle, config_name, 1)
            except ljm.LJMError as e:
                print(f"Error configuring thermocouple {tc['name']} on AIN{channel}: {e}")
                raise e

    def read_all(self):
        """
        Read all enabled thermocouples using batch read for speed.

        Returns:
            dict like {'TC1_Inlet': 25.3, 'TC2_Outlet': 28.1}
        """
        enabled_tcs = [tc for tc in self.thermocouples if tc.get('enabled', True)]

        if not enabled_tcs:
            return {}

        # Build list of EF register names for batch read
        read_names = [f"AIN{tc['channel']}_EF_READ_A" for tc in enabled_tcs]

        try:
            # Single LJM call to read all thermocouple channels at once
            results = ljm.eReadNames(self.handle, len(read_names), read_names)
        except ljm.LJMError as e:
            print(f"Batch thermocouple read error: {e}")
            # Fall back to individual reads
            return self._read_all_sequential()

        # Process batch results
        readings = {}
        for i, tc in enumerate(enabled_tcs):
            temp = results[i]
            if temp == -9999:
                readings[tc['name']] = None
            else:
                readings[tc['name']] = round(temp, 3)

        return readings

    def _read_all_sequential(self):
        """
        Fallback: read thermocouples one at a time if batch read fails.

        Returns:
            dict like {'TC1_Inlet': 25.3, 'TC2_Outlet': 28.1}
        """
        readings = {}

        for tc in self.thermocouples:
            if not tc['enabled']:
                continue

            channel = tc['channel']
            read_name = f"AIN{channel}_EF_READ_A"

            try:
                temp = ljm.eReadName(self.handle, read_name)
                if temp == -9999:
                    readings[tc['name']] = None
                else:
                    readings[tc['name']] = round(temp, 3)
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
                    
                    return round(temp, 3)
                except ljm.LJMError as e:
                    print(f"Error reading {channel_name}: {e}")
                    return None
        return None

    def get_enabled_channels(self):
        """Get list of enabled thermocouple names."""
        return [tc['name'] for tc in self.thermocouples if tc['enabled']]

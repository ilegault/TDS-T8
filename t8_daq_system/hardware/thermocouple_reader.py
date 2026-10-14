"""
thermocouple_reader.py
PURPOSE: Read thermocouple temperatures from T8
KEY CONCEPT: T8 has "Extended Features" (EF) that do the math automatically
"""

import logging

from labjack import ljm

logger = logging.getLogger(__name__)

DEBUG_TC = False   # Set False to silence TC debug output


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
        self._debug_read_count = 0
        self._configure_channels()

    def _configure_channels(self):
        """
        Set up each thermocouple channel on the T8.
        This tells the T8 "this channel has a Type K thermocouple"
        """
        if DEBUG_TC:
            logger.debug(f"[TC DEBUG] Configuring {len([t for t in self.thermocouples if t['enabled']])} enabled TC channels")

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

                if DEBUG_TC:
                    neg_ch = ljm.eReadName(self.handle, f"AIN{channel}_NEGATIVE_CH")
                    logger.debug(f"[TC DEBUG] Configured {tc['name']}: AIN{channel}, type={tc_type} "
                          f"(EF_INDEX={self.TC_TYPES[tc_type]}), RANGE=0.1V, "
                          f"NEGATIVE_CH={int(neg_ch)}")
            except ljm.LJMError as e:
                logger.exception(f"Error configuring thermocouple {tc['name']} on AIN{channel}: {e}")
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
            logger.exception(f"Batch thermocouple read error: {e}")
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

        if DEBUG_TC:
            self._debug_read_count += 1
            # Print every 10th read to avoid flooding the log
            if self._debug_read_count % 10 == 1:
                logger.debug(f"[TC DEBUG] Read #{self._debug_read_count} — "
                      f"{len(enabled_tcs)} channels, registers: {read_names}")
                for name, val in readings.items():
                    status = f"{val:.3f} °C" if val is not None else "NONE (-9999 / open circuit)"
                    logger.debug(f"  {name}: {status}")

        return readings

    def read_raw_voltages(self):
        """
        Read the raw differential input voltage for each enabled thermocouple
        channel by reading the AIN# register directly (before EF conversion).

        The T8 extended-feature (EF) thermocouple mode converts the millivolt
        TC signal to temperature internally.  Reading AIN{channel} returns the
        actual differential voltage seen at the input pins so the user can
        verify the physical wiring and unit-conversion chain:

            physical wire → AIN# raw voltage → EF conversion → temperature

        Returns
        -------
        dict
            Keys are ``"<tc_name>_rawV"`` (e.g. ``"TC_1_rawV"``), values are
            voltages in Volts (typically in the ±100 mV range for thermocouples).
            Returns ``None`` for a channel that fails to read.
        """
        enabled_tcs = [tc for tc in self.thermocouples if tc.get('enabled', True)]
        if not enabled_tcs:
            return {}

        # Read AIN# (raw voltage) alongside AIN#_EF_READ_A (temperature)
        raw_names = [f"AIN{tc['channel']}" for tc in enabled_tcs]

        try:
            results = ljm.eReadNames(self.handle, len(raw_names), raw_names)
        except ljm.LJMError as e:
            logger.exception(f"Batch raw voltage read error: {e}")
            return {f"{tc['name']}_rawV": None for tc in enabled_tcs}

        raw_voltages = {}
        for i, tc in enumerate(enabled_tcs):
            v = results[i]
            # Clamp obviously-bad values (open circuit on ±100 mV range reads ~±0.1)
            raw_voltages[f"{tc['name']}_rawV"] = round(v, 8) if v is not None else None

        return raw_voltages

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
                logger.exception(f"Error reading {tc['name']}: {e}")
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
                    logger.exception(f"Error reading {channel_name}: {e}")
                    return None
        return None

    def get_enabled_channels(self):
        """Get list of enabled thermocouple names."""
        return [tc['name'] for tc in self.thermocouples if tc['enabled']]

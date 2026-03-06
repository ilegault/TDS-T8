"""
frg702_reader.py
PURPOSE: Read Leybold FRG-702 full-range gauge (Pirani + Cold Cathode) via XGS-600 controller
KEY CONCEPT: XGS-600 provides digital pressure readings over RS-232, eliminating
analog voltage conversion. Pressure values are read directly from the controller.
"""


DEBUG_PRESSURE = True   # Set False to silence once working correctly

# Unit conversion factors from mbar
UNIT_CONVERSIONS = {
    'mbar': 1.0,
    'Torr': 0.750062,
    'Pa': 100.0,
}

# Status constants
STATUS_VALID = 'valid'
STATUS_UNDERRANGE = 'underrange'
STATUS_OVERRANGE = 'overrange'
STATUS_SENSOR_ERROR_NO_SUPPLY = 'sensor_error_no_supply'
STATUS_SENSOR_ERROR_PIRANI_DEFECTIVE = 'sensor_error_pirani_defective'

# Operating mode constants
MODE_PIRANI_ONLY = 'Pirani'
MODE_COMBINED = 'Combined'
MODE_UNKNOWN = 'Unknown'


from labjack import ljm

class FRG702Reader:
    def __init__(self, xgs600_controller, frg702_config_list):
        """
        Initialize FRG-702 gauge reader via XGS-600.

        Args:
            xgs600_controller: The XGS600Controller instance
            frg702_config_list: List of FRG-702 gauge configs from JSON
        """
        self.controller = xgs600_controller
        self.gauges = frg702_config_list

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
    def voltage_to_pressure_mbar(voltage):
        """
        DEPRECATED: Used for analog readings. Convert voltage to pressure in mbar.
        Formula from Leybold FRG-702 manual: p = 10^(1.667*U - 11.33) [mbar]

        Returns:
            (pressure, status) - pressure is None if status is not valid
        """
        if voltage is None:
            return None, STATUS_VALID  # Or some other default

        if voltage < 0.5:
            return None, STATUS_SENSOR_ERROR_NO_SUPPLY
        if voltage < 1.82:
            return None, STATUS_UNDERRANGE
        if voltage > 9.5:
            return None, STATUS_SENSOR_ERROR_PIRANI_DEFECTIVE
        if voltage > 8.6:
            return None, STATUS_OVERRANGE

        # Valid range: 1.82V to 8.6V (5e-9 to 1000 mbar)
        pressure = 10 ** (1.667 * voltage - 11.33)
        return pressure, STATUS_VALID

    @staticmethod
    def read_operating_mode(status_voltage):
        """
        DEPRECATED: Used for analog readings. Determine mode from Pin 6 voltage.
        < 5V: Pirani only
        > 5V: Combined (Pirani + Cold Cathode)
        """
        if status_voltage is None:
            return MODE_UNKNOWN
        if status_voltage >= 5.0:
            return MODE_COMBINED
        return MODE_PIRANI_ONLY

    @staticmethod
    def _to_mbar(pressure, raw_unit):
        """
        Normalise a raw pressure reading to mbar.

        The XGS-600 outputs values in whatever unit is configured on its front
        panel (typically Torr).  All internal storage uses mbar so that the
        existing unit-conversion pipeline is always applied to a known baseline.

        Args:
            pressure: Raw float from the controller, or None.
            raw_unit: Unit string the controller is configured to output
                      ('Torr', 'mbar', 'Pa').  Comes from gauge config 'units'.

        Returns:
            Pressure converted to mbar, or None.
        """
        if pressure is None or raw_unit == 'mbar':
            return pressure
        factor = UNIT_CONVERSIONS.get(raw_unit, 1.0)
        # UNIT_CONVERSIONS maps mbar→unit (e.g. mbar→Torr = ×0.750062),
        # so to go unit→mbar we divide by the factor.
        return pressure / factor

    def read_all_with_status(self):
        """
        Read all enabled FRG-702 gauges, returning pressure (in mbar) and status.

        This is the single hardware-read method.  All values are converted from
        the gauge's configured output unit (e.g. Torr) to mbar before being
        returned so that the rest of the pipeline works with a consistent unit.

        Returns:
            dict like {'FRG702_Chamber': {'pressure': 1.5e-6, 'status': 'valid'}}
            Pressure values are always in mbar (or None on error).
        """
        readings = {}

        # Fail fast if controller not connected
        if not self.controller.is_connected():
            return {
                g['name']: {
                    'pressure': None,
                    'status': 'error',
                    'mode': MODE_UNKNOWN
                } for g in self.gauges if g.get('enabled', True)
            }

        for gauge in self.gauges:
            if not gauge.get('enabled', True):
                continue

            sensor_code = gauge['sensor_code']
            raw_unit = gauge.get('units', 'mbar')

            try:
                raw_pressure = self.controller.read_pressure(sensor_code)
                pressure = self._to_mbar(raw_pressure, raw_unit)

                if pressure is not None:
                    readings[gauge['name']] = {
                        'pressure': pressure,
                        'status': STATUS_VALID,
                        'mode': MODE_UNKNOWN,
                        '_raw_str':   str(raw_pressure) if raw_pressure is not None else '?',
                        '_raw_value': raw_pressure,
                        '_raw_unit':  raw_unit,
                    }
                else:
                    readings[gauge['name']] = {
                        'pressure': None,
                        'status': 'error',
                        'mode': MODE_UNKNOWN,
                        '_raw_str':   '?',
                        '_raw_value': None,
                        '_raw_unit':  raw_unit,
                    }

            except Exception as e:
                print(f"Error reading {gauge['name']}: {e}")
                readings[gauge['name']] = {
                    'pressure': None,
                    'status': 'error',
                    'mode': MODE_UNKNOWN,
                    '_raw_str':   '?',
                    '_raw_value': None,
                    '_raw_unit':  raw_unit,
                }

        if DEBUG_PRESSURE:
            for name, result in readings.items():
                raw_val  = result.get('_raw_value')
                raw_unit = result.get('_raw_unit', '?')
                mbar_val = result.get('pressure')
                print(
                    f"[PRESSURE DEBUG] Sensor: {name}\n"
                    f"  Serial raw string : {result.get('_raw_str', '?')}\n"
                    f"  Parsed float      : {raw_val}\n"
                    f"  XGS-600 unit      : {raw_unit}  (from gauge config 'units' field)\n"
                    f"  Conversion factor : UNIT_CONVERSIONS['{raw_unit}'] = "
                    f"{UNIT_CONVERSIONS.get(raw_unit, '???')}\n"
                    f"  mbar = raw / factor = {raw_val} / {UNIT_CONVERSIONS.get(raw_unit, 1.0)}"
                    f" = {mbar_val}\n"
                    f"  Status            : {result.get('status')}"
                )

        return readings

    def read_all(self):
        """
        Read all enabled FRG-702 gauges via XGS-600.

        Delegates to read_all_with_status() to avoid a second serial round-trip
        and keep the buffer and status panel in sync.

        Returns:
            dict like {'FRG702_Chamber': 1.5e-6} — pressure in mbar, or None.
        """
        detail = self.read_all_with_status()
        return {name: info['pressure'] for name, info in detail.items()}

    def read_single(self, channel_name):
        """
        Read just one FRG-702 gauge by name.

        Args:
            channel_name: Name of the gauge to read

        Returns:
            Pressure in mbar, or None if not found/error
        """
        for gauge in self.gauges:
            if gauge['name'] == channel_name and gauge.get('enabled', True):
                raw_unit = gauge.get('units', 'mbar')
                try:
                    raw = self.controller.read_pressure(gauge['sensor_code'])
                    return self._to_mbar(raw, raw_unit)
                except Exception as e:
                    print(f"Error reading {channel_name}: {e}")
                    return None
        return None

    def get_enabled_channels(self):
        """Get list of enabled FRG-702 gauge names."""
        return [g['name'] for g in self.gauges if g['enabled']]


class FRG702AnalogReader:
    """Read Leybold FRG-702 gauges via LabJack T8 analog inputs."""
    
    def __init__(self, handle, frg702_config_list):
        """
        Initialize FRG-702 analog reader.
        
        Args:
            handle: LJM device handle
            frg702_config_list: List of gauge configs (must include 'pin' key)
        """
        self.handle = handle
        self.gauges = frg702_config_list

    def read_all(self):
        """Read all enabled gauges. Returns {name: pressure_mbar}."""
        readings = {}
        for gauge in self.gauges:
            if not gauge.get('enabled', True):
                continue
            
            try:
                voltage = ljm.eReadName(self.handle, gauge['pin'])
                pressure, _ = FRG702Reader.voltage_to_pressure_mbar(voltage)
                readings[gauge['name']] = pressure
            except Exception as e:
                print(f"Error reading analog gauge {gauge['name']}: {e}")
                readings[gauge['name']] = None
        return readings

    def read_all_with_status(self):
        """Read all enabled gauges with status and voltage."""
        readings = {}
        for gauge in self.gauges:
            if not gauge.get('enabled', True):
                continue
            
            try:
                voltage = ljm.eReadName(self.handle, gauge['pin'])
                pressure, status = FRG702Reader.voltage_to_pressure_mbar(voltage)
                readings[gauge['name']] = {
                    'pressure': pressure,
                    'status': status,
                    'mode': 'Analog',
                    'voltage': voltage
                }
            except Exception as e:
                readings[gauge['name']] = {
                    'pressure': None,
                    'status': 'error',
                    'mode': 'Analog',
                    'voltage': None
                }
        return readings

    def get_enabled_channels(self):
        return [g['name'] for g in self.gauges if g.get('enabled', True)]

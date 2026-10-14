"""
frg702_reader.py
PURPOSE: Read Leybold FRG-702 full-range gauge (Pirani + Cold Cathode) via XGS-600 controller
KEY CONCEPT: XGS-600 provides digital pressure readings over RS-232, eliminating
analog voltage conversion. Pressure values are read directly from the controller.
"""

import logging

from labjack import ljm
from t8_daq_system.utils.helpers import (
    UNIT_CONVERSIONS,
    convert_pressure as _convert_pressure,
)

logger = logging.getLogger(__name__)

DEBUG_PRESSURE = False   # Set False to silence once working correctly

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
        self._device_unit = None  # Cached unit setting from XGS-600 hardware

    def _refresh_device_unit(self):
        """Query the XGS-600 for its current front-panel unit setting."""
        if self.controller and self.controller.is_connected():
            unit = self.controller.read_units()
            if unit:
                self._device_unit = unit
        return self._device_unit

    @property
    def target_unit(self):
        return 'Torr'

    @target_unit.setter
    def target_unit(self, val):
        pass

    @staticmethod
    def convert_pressure(value, from_unit, to_unit):
        """
        Convert pressure from one unit to another ('mbar', 'Torr', 'Pa').
        """
        return _convert_pressure(value, from_unit, to_unit)

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

    def read_all_with_status(self):
        """
        Read all enabled FRG-702 gauges, returning pressure and status.

        This is the single hardware-read method. Values are converted from
        the device's front-panel unit setting to the app's target unit
        (from gauge config) only if they differ.

        Returns:
            dict like {'FRG702_Chamber': {'pressure': 1.5e-6, 'status': 'valid'}}
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

        # Refresh device unit if not yet known
        if self._device_unit is None:
            self._refresh_device_unit()

        # Fallback to Torr if query fails or is not yet performed
        device_unit = self._device_unit or 'Torr'

        for gauge in self.gauges:
            if not gauge.get('enabled', True):
                continue

            sensor_code = gauge['sensor_code']

            try:
                raw_pressure = self.controller.read_pressure(sensor_code)
                pressure = self.convert_pressure(raw_pressure, device_unit, 'Torr')

                if pressure is not None:
                    readings[gauge['name']] = {
                        'pressure': pressure,
                        'status': STATUS_VALID,
                        'mode': MODE_UNKNOWN,
                        '_raw_str':   str(raw_pressure) if raw_pressure is not None else '?',
                        '_raw_value': raw_pressure,
                        '_raw_device_unit': device_unit,
                        '_target_unit': 'Torr',
                    }
                else:
                    readings[gauge['name']] = {
                        'pressure': None,
                        'status': 'error',
                        'mode': MODE_UNKNOWN,
                        '_raw_str':   '?',
                        '_raw_value': None,
                        '_raw_device_unit': device_unit,
                        '_target_unit': 'Torr',
                    }

            except Exception as e:
                logger.exception(f"Error reading {gauge['name']}: {e}")
                readings[gauge['name']] = {
                    'pressure': None,
                    'status': 'error',
                    'mode': MODE_UNKNOWN,
                    '_raw_str':   '?',
                    '_raw_value': None,
                    '_raw_device_unit': device_unit,
                    '_target_unit': 'Torr',
                }

        if DEBUG_PRESSURE:
            for name, result in readings.items():
                raw_val  = result.get('_raw_value')
                dev_u    = result.get('_raw_device_unit', '?')
                target_u = result.get('_target_unit', '?')
                conv_val = result.get('pressure')

                # Determine if conversion was actually applied
                if dev_u == target_u:
                    conv_str = f"No conversion needed (Device={dev_u}, App={target_u})"
                else:
                    f_factor = UNIT_CONVERSIONS.get(dev_u, 1.0)
                    t_factor = UNIT_CONVERSIONS.get(target_u, 1.0)
                    conv_str = (f"Converted {dev_u} -> {target_u}: "
                                f"raw / {f_factor} * {t_factor} = {conv_val}")

                logger.debug(
                    f"[PRESSURE DEBUG] Sensor: {name}\n"
                    f"  Serial raw string : {result.get('_raw_str', '?')}\n"
                    f"  Parsed float      : {raw_val}\n"
                    f"  XGS-600 unit      : {dev_u} (detected from hardware)\n"
                    f"  App target unit   : {target_u} (from settings)\n"
                    f"  Logic             : {conv_str}\n"
                    f"  Status            : {result.get('status')}"
                )

        return readings

    def read_all(self):
        """
        Read all enabled FRG-702 gauges via XGS-600.

        Delegates to read_all_with_status() to avoid a second serial round-trip
        and keep the buffer and status panel in sync.

        Returns:
            dict like {'FRG702_Chamber': 1.5e-6} — pressure in Torr, or None.
        """
        detail = self.read_all_with_status()
        return {name: info['pressure'] for name, info in detail.items()}

    def read_single(self, channel_name):
        """
        Read just one FRG-702 gauge by name in Torr.

        Args:
            channel_name: Name of the gauge to read

        Returns:
            Pressure in Torr, or None if not found/error
        """
        for gauge in self.gauges:
            if gauge['name'] == channel_name and gauge.get('enabled', True):
                # Ensure we know the device unit
                if self._device_unit is None:
                    self._refresh_device_unit()
                device_unit = self._device_unit or 'Torr'

                try:
                    raw = self.controller.read_pressure(gauge['sensor_code'])
                    return self.convert_pressure(raw, device_unit, 'Torr')
                except Exception as e:
                    logger.exception(f"Error reading {channel_name}: {e}")
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
        """Read all enabled gauges. Returns {name: pressure_torr}."""
        readings = {}
        for gauge in self.gauges:
            if not gauge.get('enabled', True):
                continue
            
            try:
                voltage = ljm.eReadName(self.handle, gauge['pin'])
                pressure_mbar, _ = FRG702Reader.voltage_to_pressure_mbar(voltage)
                pressure = FRG702Reader.convert_pressure(pressure_mbar, 'mbar', 'Torr') if pressure_mbar is not None else None
                readings[gauge['name']] = pressure
            except Exception as e:
                logger.exception(f"Error reading analog gauge {gauge['name']}: {e}")
                readings[gauge['name']] = None
        return readings

    def read_all_with_status(self):
        """Read all enabled gauges with status and voltage in Torr."""
        readings = {}
        for gauge in self.gauges:
            if not gauge.get('enabled', True):
                continue
            
            try:
                voltage = ljm.eReadName(self.handle, gauge['pin'])
                pressure_mbar, status = FRG702Reader.voltage_to_pressure_mbar(voltage)
                pressure = FRG702Reader.convert_pressure(pressure_mbar, 'mbar', 'Torr') if pressure_mbar is not None else None
                readings[gauge['name']] = {
                    'pressure': pressure,
                    'status': status,
                    'mode': 'Analog',
                    'voltage': voltage
                }
            except Exception as e:
                logger.exception(f"Error reading analog gauge {gauge['name']}: {e}")
                readings[gauge['name']] = {
                    'pressure': None,
                    'status': 'error',
                    'mode': 'Analog',
                    'voltage': None
                }
        return readings

    def get_enabled_channels(self):
        return [g['name'] for g in self.gauges if g.get('enabled', True)]

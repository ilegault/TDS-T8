"""
helpers.py
PURPOSE: Utility functions for timestamp formatting, unit conversions, etc.
"""

from datetime import datetime


def format_timestamp(dt=None, format_str="%Y-%m-%d %H:%M:%S"):
    """
    Format a datetime object as a string.

    Args:
        dt: datetime object (uses current time if None)
        format_str: strftime format string

    Returns:
        Formatted timestamp string
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime(format_str)


def format_timestamp_filename(dt=None):
    """
    Format a datetime for use in filenames (no special characters).

    Args:
        dt: datetime object (uses current time if None)

    Returns:
        Formatted string like '20231215_143022'
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y%m%d_%H%M%S")


def convert_temperature(value, from_unit, to_unit):
    """
    Convert temperature between units.

    Args:
        value: Temperature value to convert
        from_unit: Source unit ('C', 'F', or 'K')
        to_unit: Target unit ('C', 'F', or 'K')

    Returns:
        Converted temperature value
    """
    f = from_unit.upper()[0] if from_unit else 'C'
    t = to_unit.upper()[0] if to_unit else 'C'

    if f == t:
        return value

    # Convert to Celsius first
    if f == 'F':
        celsius = (value - 32) * 5/9
    elif f == 'K':
        celsius = value - 273.15
    else:
        celsius = value

    # Convert from Celsius to target
    if t == 'F':
        return celsius * 9/5 + 32
    elif t == 'K':
        return celsius + 273.15
    else:
        return celsius


def linear_scale(value, in_min, in_max, out_min, out_max):
    """
    Scale a value from one range to another using linear interpolation.

    Args:
        value: Input value to scale
        in_min: Input range minimum
        in_max: Input range maximum
        out_min: Output range minimum
        out_max: Output range maximum

    Returns:
        Scaled value in output range
    """
    return (value - in_min) / (in_max - in_min) * (out_max - out_min) + out_min


def clamp(value, min_val, max_val):
    """
    Clamp a value to a specified range.

    Args:
        value: Value to clamp
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Clamped value
    """
    return max(min_val, min(max_val, value))

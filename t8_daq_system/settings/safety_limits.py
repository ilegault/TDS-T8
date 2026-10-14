"""
Central safety limits and timing constants for the TDS-T8 rig.

WHY THIS EXISTS
---------------
Previously, magic numbers were scattered across multiple modules: PID timing
literals in the executor loop, pressure thresholds in display units inside
DataAcquisition, temperature overrides in SafetyMonitor, and clamp limits
duplicated across files.

Consolidating these numbers here ensures every tunable and safety threshold has
exactly one canonical home and one documented justification (ADRs 0002–0004).
"""

# PID gains tuned at 0.5 s (ADR 0002)
CONTROL_PERIOD_S: float = 0.5

# control TC and pressure staleness limit before trip (ADR 0003, 0004)
STALE_ALLOWANCE_S: float = 5.0

# Chamber pressure interlock threshold in Torr (ADR 0004)
PRESSURE_INTERLOCK_TORR: float = 1e-4

# Hard specimen temperature override limit in Celsius
TEMP_OVERRIDE_C: float = 2200.0

# Temperature restart threshold in Celsius (reset hysteresis)
TEMP_OVERRIDE_RESET_C: float = 2150.0

# Keysight N5700 DAC0 voltage maximum clamp (CV-only limit)
DAC0_MAX_V: float = 6.0

# Keysight N5700 rated current ceiling in Amperes (DAC1 pinned here, CV-only)
PS_CURRENT_CEILING_A: float = 180.0

# Interval between hardware reconnection attempts in seconds
RECONNECT_INTERVAL_S: float = 30.0

"""
Safety Monitor for Power Supply Control.

Monitors temperature readings and enforces safety limits.
Triggers emergency shutdown when limits are exceeded.
"""

import threading
import time
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SafetyStatus(Enum):
    """Safety monitor status."""
    OK = "ok"
    WARNING = "warning"
    LIMIT_EXCEEDED = "limit_exceeded"
    SHUTDOWN_TRIGGERED = "shutdown_triggered"
    ERROR = "error"


@dataclass
class SafetyEvent:
    """Record of a safety event."""
    timestamp: datetime
    event_type: str
    sensor_name: str
    value: float
    limit: float
    message: str


class SafetyMonitor:
    """
    Monitors sensor readings and enforces safety limits.

    The safety monitor tracks temperature (and optionally other) sensor readings
    against configurable limits. When any limit is exceeded, it can trigger
    an emergency shutdown of the power supply.

    Safety checks should be performed BEFORE any other processing in the read loop.

    Example usage:
        monitor = SafetyMonitor(power_supply_controller)
        monitor.set_temperature_limit("TC1", max_temp=200.0)
        monitor.set_temperature_limit("TC2", max_temp=180.0)

        # In read loop:
        readings = thermocouple_reader.read_all()
        if not monitor.check_limits(readings):
            # Shutdown already triggered, handle alert
            monitor.get_last_event()
    """

    def __init__(self, power_supply_controller=None, auto_shutoff: bool = True):
        """
        Initialize the safety monitor.

        Args:
            power_supply_controller: PowerSupplyController instance for emergency shutoff.
                                    If None, monitor runs in alert-only mode.
            auto_shutoff: Whether to automatically shut off power supply on limit breach
        """
        self.power_supply = power_supply_controller
        self.auto_shutoff = auto_shutoff

        # Temperature limits: {sensor_name: max_temperature}
        self._temperature_limits: Dict[str, float] = {}

        # Warning thresholds (percentage of limit, e.g., 0.9 = 90%)
        self._warning_threshold: float = 0.9

        # Current status
        self._status = SafetyStatus.OK
        self._last_event: Optional[SafetyEvent] = None
        self._event_history: List[SafetyEvent] = []
        self._max_history: int = 100

        # Watchdog sensor (primary sensor to monitor)
        self._watchdog_sensor: Optional[str] = None

        # Callbacks
        self._on_warning: Optional[Callable[[str, float, float], None]] = None
        self._on_limit_exceeded: Optional[Callable[[str, float, float], None]] = None
        self._on_shutdown: Optional[Callable[[SafetyEvent], None]] = None

        # Thread safety
        self._lock = threading.Lock()

        # Enabled state
        self._enabled = True

        # Consecutive violation tracking (for debouncing)
        self._violation_counts: Dict[str, int] = {}
        self._required_violations: int = 1  # Immediate action by default

    @property
    def status(self) -> SafetyStatus:
        """Get current safety status."""
        with self._lock:
            return self._status

    @property
    def is_safe(self) -> bool:
        """Check if system is currently in a safe state."""
        return self.status in [SafetyStatus.OK, SafetyStatus.WARNING]

    @property
    def enabled(self) -> bool:
        """Check if safety monitoring is enabled."""
        with self._lock:
            return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Enable or disable safety monitoring."""
        with self._lock:
            self._enabled = value

    def set_power_supply(self, power_supply_controller) -> None:
        """
        Set or update the power supply controller.

        Args:
            power_supply_controller: PowerSupplyController instance
        """
        self.power_supply = power_supply_controller

    def set_temperature_limit(self, sensor_name: str, max_temp: float) -> None:
        """
        Set the maximum temperature limit for a sensor.

        Args:
            sensor_name: Name of the sensor (e.g., "TC1", "TC_Inlet")
            max_temp: Maximum allowed temperature in degrees C

        Raises:
            ValueError: If max_temp is not positive
        """
        if max_temp <= 0:
            raise ValueError(f"Temperature limit must be positive: {max_temp}")

        with self._lock:
            self._temperature_limits[sensor_name] = max_temp
            self._violation_counts[sensor_name] = 0

    def remove_temperature_limit(self, sensor_name: str) -> None:
        """
        Remove the temperature limit for a sensor.

        Args:
            sensor_name: Name of the sensor
        """
        with self._lock:
            self._temperature_limits.pop(sensor_name, None)
            self._violation_counts.pop(sensor_name, None)

    def clear_all_limits(self) -> None:
        """Remove all temperature limits."""
        with self._lock:
            self._temperature_limits.clear()
            self._violation_counts.clear()

    def get_temperature_limit(self, sensor_name: str) -> Optional[float]:
        """
        Get the temperature limit for a sensor.

        Args:
            sensor_name: Name of the sensor

        Returns:
            Temperature limit or None if not set
        """
        with self._lock:
            return self._temperature_limits.get(sensor_name)

    def get_all_limits(self) -> Dict[str, float]:
        """
        Get all configured temperature limits.

        Returns:
            Dictionary of {sensor_name: max_temperature}
        """
        with self._lock:
            return self._temperature_limits.copy()

    def set_watchdog_sensor(self, sensor_name: str) -> None:
        """
        Set the primary watchdog sensor.

        The watchdog sensor is given priority in safety checks and its
        limit violations are always immediately acted upon.

        Args:
            sensor_name: Name of the sensor to use as watchdog
        """
        with self._lock:
            self._watchdog_sensor = sensor_name

    def set_warning_threshold(self, threshold: float) -> None:
        """
        Set the warning threshold as a fraction of the limit.

        Args:
            threshold: Fraction (0.0-1.0) at which to trigger warnings
                      e.g., 0.9 means warn at 90% of limit
        """
        if not 0.0 < threshold < 1.0:
            raise ValueError("Warning threshold must be between 0 and 1")
        with self._lock:
            self._warning_threshold = threshold

    def set_debounce_count(self, count: int) -> None:
        """
        Set the number of consecutive violations required before action.

        Args:
            count: Number of consecutive limit violations before shutdown
                  (1 = immediate, 2+ = debounced)
        """
        if count < 1:
            raise ValueError("Debounce count must be at least 1")
        with self._lock:
            self._required_violations = count

    def check_limits(self, sensor_readings: Dict[str, float]) -> bool:
        """
        Check all sensor readings against their limits.

        This method should be called at the START of every read cycle,
        BEFORE any other processing.

        Args:
            sensor_readings: Dictionary of {sensor_name: temperature_value}

        Returns:
            True if all readings are within limits (safe)
            False if any limit was exceeded (shutdown may have been triggered)
        """
        if not self.enabled:
            return True

        with self._lock:
            limits = self._temperature_limits.copy()
            warning_threshold = self._warning_threshold
            watchdog = self._watchdog_sensor

        warnings_found = []
        violations_found = []

        for sensor_name, limit in limits.items():
            if sensor_name not in sensor_readings:
                continue

            value = sensor_readings[sensor_name]

            # Skip invalid readings (None or disconnected sensor marker)
            if value is None or value == -9999:
                continue

            # Check for limit exceeded
            if value >= limit:
                violations_found.append((sensor_name, value, limit))
                continue

            # Check for warning threshold
            if value >= limit * warning_threshold:
                warnings_found.append((sensor_name, value, limit))

            # Reset violation count if within limits
            with self._lock:
                self._violation_counts[sensor_name] = 0

        # Process warnings
        for sensor_name, value, limit in warnings_found:
            self._handle_warning(sensor_name, value, limit)

        # Process violations
        for sensor_name, value, limit in violations_found:
            should_shutdown = self._handle_violation(sensor_name, value, limit)
            if should_shutdown:
                self._trigger_shutdown(sensor_name, value, limit)
                return False

        # Update status if no violations
        with self._lock:
            if warnings_found:
                self._status = SafetyStatus.WARNING
            elif self._status not in [SafetyStatus.SHUTDOWN_TRIGGERED]:
                self._status = SafetyStatus.OK

        return True

    def _handle_warning(self, sensor_name: str, value: float, limit: float) -> None:
        """Handle a warning condition."""
        with self._lock:
            self._status = SafetyStatus.WARNING

        if self._on_warning:
            try:
                self._on_warning(sensor_name, value, limit)
            except Exception:
                pass

    def _handle_violation(self, sensor_name: str, value: float, limit: float) -> bool:
        """
        Handle a limit violation.

        Returns:
            True if shutdown should be triggered, False to continue monitoring
        """
        with self._lock:
            # Watchdog sensor always triggers immediate shutdown
            if sensor_name == self._watchdog_sensor:
                self._violation_counts[sensor_name] = self._required_violations
            else:
                self._violation_counts[sensor_name] = \
                    self._violation_counts.get(sensor_name, 0) + 1

            violation_count = self._violation_counts[sensor_name]
            required = self._required_violations

        # Check if we've reached the required violation count
        if violation_count >= required:
            if self._on_limit_exceeded:
                try:
                    self._on_limit_exceeded(sensor_name, value, limit)
                except Exception:
                    pass
            return True

        return False

    def _trigger_shutdown(self, sensor_name: str, value: float, limit: float) -> None:
        """Trigger emergency shutdown."""
        event = SafetyEvent(
            timestamp=datetime.now(),
            event_type="limit_exceeded",
            sensor_name=sensor_name,
            value=value,
            limit=limit,
            message=f"Temperature limit exceeded on {sensor_name}: "
                   f"{value:.1f}°C >= {limit:.1f}°C"
        )

        with self._lock:
            self._last_event = event
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)
            self._status = SafetyStatus.LIMIT_EXCEEDED

        # Perform emergency shutdown
        if self.auto_shutoff:
            self.emergency_shutdown()

        with self._lock:
            self._status = SafetyStatus.SHUTDOWN_TRIGGERED

        # Notify callback
        if self._on_shutdown:
            try:
                self._on_shutdown(event)
            except Exception:
                pass

    def emergency_shutdown(self) -> bool:
        """
        Immediately shut off the power supply output.

        This is the critical safety function. It attempts to turn off
        the power supply output immediately, with retries if needed.

        Returns:
            True if shutdown was successful, False if it failed
        """
        if self.power_supply is None:
            print("WARNING: No power supply connected for emergency shutdown")
            return False

        # Record the shutdown event
        event = SafetyEvent(
            timestamp=datetime.now(),
            event_type="emergency_shutdown",
            sensor_name="",
            value=0.0,
            limit=0.0,
            message="Emergency shutdown initiated"
        )

        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)

        # Attempt shutdown - the PowerSupplyController.emergency_shutdown()
        # method already has retry logic built in
        try:
            success = self.power_supply.emergency_shutdown()
            if success:
                print("SAFETY: Emergency shutdown successful")
                return True
            else:
                print("SAFETY: Emergency shutdown may have failed - verify manually!")
                return False
        except Exception as e:
            print(f"SAFETY: Emergency shutdown error: {e}")
            # Try direct output off as fallback
            try:
                self.power_supply.output_off()
                return True
            except Exception:
                pass
            return False

    def reset(self) -> None:
        """
        Reset the safety monitor after a shutdown.

        This clears the shutdown state but preserves event history.
        Should only be called after the cause of the shutdown has been
        addressed.
        """
        with self._lock:
            self._status = SafetyStatus.OK
            self._violation_counts = {k: 0 for k in self._violation_counts}

    def get_last_event(self) -> Optional[SafetyEvent]:
        """
        Get the most recent safety event.

        Returns:
            SafetyEvent or None if no events have occurred
        """
        with self._lock:
            return self._last_event

    def get_event_history(self) -> List[SafetyEvent]:
        """
        Get the history of safety events.

        Returns:
            List of SafetyEvent objects (oldest first)
        """
        with self._lock:
            return self._event_history.copy()

    def clear_event_history(self) -> None:
        """Clear the event history."""
        with self._lock:
            self._event_history.clear()
            self._last_event = None

    # Callback registration methods
    def on_warning(self, callback: Callable[[str, float, float], None]) -> None:
        """
        Register callback for warning conditions.

        Args:
            callback: Function called with (sensor_name, value, limit)
        """
        self._on_warning = callback

    def on_limit_exceeded(self, callback: Callable[[str, float, float], None]) -> None:
        """
        Register callback for limit exceeded conditions.

        Args:
            callback: Function called with (sensor_name, value, limit)
        """
        self._on_limit_exceeded = callback

    def on_shutdown(self, callback: Callable[[SafetyEvent], None]) -> None:
        """
        Register callback for emergency shutdown.

        Args:
            callback: Function called with SafetyEvent
        """
        self._on_shutdown = callback

    def get_status_report(self) -> Dict:
        """
        Get a comprehensive status report.

        Returns:
            Dictionary with current status information
        """
        with self._lock:
            return {
                'status': self._status.value,
                'enabled': self._enabled,
                'auto_shutoff': self.auto_shutoff,
                'power_supply_connected': self.power_supply is not None,
                'temperature_limits': self._temperature_limits.copy(),
                'watchdog_sensor': self._watchdog_sensor,
                'warning_threshold': self._warning_threshold,
                'violation_counts': self._violation_counts.copy(),
                'last_event': self._last_event,
                'event_count': len(self._event_history)
            }

    def configure_from_dict(self, config: Dict) -> None:
        """
        Configure the safety monitor from a configuration dictionary.

        Expected format:
        {
            "enabled": true,
            "auto_shutoff": true,
            "max_temperature": 2300,  # Global default
            "warning_threshold": 0.9,
            "watchdog_sensor": "TC_1",
            "sensor_limits": {
                "TC_1": 200,
                "TC_2": 180
            }
        }

        Args:
            config: Configuration dictionary
        """
        self.enabled = config.get('enabled', True)
        self.auto_shutoff = config.get('auto_shutoff', True)

        if 'warning_threshold' in config:
            self.set_warning_threshold(config['warning_threshold'])

        if 'watchdog_sensor' in config:
            self.set_watchdog_sensor(config['watchdog_sensor'])

        if 'debounce_count' in config:
            self.set_debounce_count(config['debounce_count'])

        # Set individual sensor limits
        sensor_limits = config.get('sensor_limits', {})
        default_limit = config.get('max_temperature')

        for sensor_name, limit in sensor_limits.items():
            self.set_temperature_limit(sensor_name, limit)

        # Apply default limit to watchdog if not specifically set
        if default_limit and self._watchdog_sensor:
            if self._watchdog_sensor not in self._temperature_limits:
                self.set_temperature_limit(self._watchdog_sensor, default_limit)

    def __repr__(self) -> str:
        """String representation of the safety monitor."""
        return (f"SafetyMonitor(status={self.status.value}, "
                f"limits={len(self._temperature_limits)}, "
                f"enabled={self.enabled})")

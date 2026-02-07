"""
test_turbo_pump_controller.py
PURPOSE: Unit tests for TurboPumpController.

Tests cover:
- Start/stop command sending
- Status reading
- Restart delay enforcement
- Emergency stop
- Channel configuration
"""

import sys
from unittest.mock import MagicMock

# Mock the labjack library before any imports that depend on it
mock_ljm = MagicMock()
mock_ljm.LJMError = Exception
mock_labjack = MagicMock()
mock_labjack.ljm = mock_ljm
sys.modules['labjack'] = mock_labjack
sys.modules['labjack.ljm'] = mock_ljm

# Mock pyvisa before importing the modules that use it
mock_pyvisa = MagicMock()
mock_pyvisa.Error = Exception
sys.modules['pyvisa'] = mock_pyvisa

import pytest
import time

from t8_daq_system.hardware.turbo_pump_controller import TurboPumpController


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_ljm_mock():
    """Reset the ljm mock before each test."""
    mock_ljm.reset_mock()
    mock_ljm.eWriteName.side_effect = None
    mock_ljm.eWriteName.return_value = None
    mock_ljm.eReadName.side_effect = None
    mock_ljm.eReadName.return_value = 1.0  # Default: HIGH = not normal
    mock_ljm.LJMError = Exception
    yield mock_ljm


@pytest.fixture
def turbo_config():
    """Standard turbo pump config dict."""
    return {
        'enabled': True,
        'start_stop_channel': 'DIO0',
        'status_channel': 'DIO1',
        'start_delay_ms': 0,   # Zero delays for fast tests
        'stop_delay_ms': 0,
        'min_restart_delay_s': 2,
    }


@pytest.fixture
def controller(turbo_config):
    """Create a TurboPumpController with mocked LabJack."""
    return TurboPumpController(handle=12345, config=turbo_config)


# --------------------------------------------------------------------------
# Initialization Tests
# --------------------------------------------------------------------------

class TestTurboPumpInit:
    """Tests for controller initialization."""

    def test_init_sets_dio_low(self, turbo_config):
        """On init, the start/stop DIO should be set LOW (pump off)."""
        TurboPumpController(handle=12345, config=turbo_config)
        mock_ljm.eWriteName.assert_called_with(12345, 'DIO0', 0)

    def test_init_defaults(self, controller):
        """Controller should start with pump commanded OFF."""
        assert controller.is_commanded_on() is False
        assert controller._last_stop_time == 0

    def test_init_uses_config_channels(self):
        """Controller should use channel names from config."""
        config = {
            'start_stop_channel': 'DIO4',
            'status_channel': 'DIO5',
        }
        ctrl = TurboPumpController(handle=99, config=config)
        assert ctrl.start_stop_channel == 'DIO4'
        assert ctrl.status_channel == 'DIO5'


# --------------------------------------------------------------------------
# Start Tests
# --------------------------------------------------------------------------

class TestTurboPumpStart:
    """Tests for the start() method."""

    def test_start_sets_dio_high(self, controller):
        """Start should write 1 to the start/stop channel."""
        success, msg = controller.start()
        assert success is True
        mock_ljm.eWriteName.assert_called_with(12345, 'DIO0', 1)

    def test_start_sets_commanded_on(self, controller):
        """After start, is_commanded_on should be True."""
        controller.start()
        assert controller.is_commanded_on() is True

    def test_start_returns_message(self, controller):
        """Start should return a success message."""
        success, msg = controller.start()
        assert success is True
        assert "Start command sent" in msg

    def test_start_fails_on_ljm_error(self, turbo_config):
        """Start should return failure on LabJack error."""
        ctrl = TurboPumpController(handle=12345, config=turbo_config)
        mock_ljm.eWriteName.side_effect = Exception("LJM fail")
        success, msg = ctrl.start()
        assert success is False
        assert "error" in msg.lower() or "LJM" in msg


# --------------------------------------------------------------------------
# Stop Tests
# --------------------------------------------------------------------------

class TestTurboPumpStop:
    """Tests for the stop() method."""

    def test_stop_sets_dio_low(self, controller):
        """Stop should write 0 to the start/stop channel."""
        controller.start()
        mock_ljm.eWriteName.reset_mock()

        success, msg = controller.stop()
        assert success is True
        mock_ljm.eWriteName.assert_called_with(12345, 'DIO0', 0)

    def test_stop_sets_commanded_off(self, controller):
        """After stop, is_commanded_on should be False."""
        controller.start()
        controller.stop()
        assert controller.is_commanded_on() is False

    def test_stop_records_time(self, controller):
        """Stop should record the stop timestamp."""
        controller.stop()
        assert controller._last_stop_time > 0


# --------------------------------------------------------------------------
# Restart Delay Tests
# --------------------------------------------------------------------------

class TestRestartDelay:
    """Tests for the minimum restart delay safety feature."""

    def test_restart_blocked_within_delay(self, controller):
        """Starting too soon after a stop should fail."""
        controller.start()
        controller.stop()

        # Immediately try to start again (delay is 2s in fixture)
        success, msg = controller.start()
        assert success is False
        assert "wait" in msg.lower()

    def test_restart_allowed_after_delay(self, controller):
        """Starting after the delay period should succeed."""
        controller.start()
        controller.stop()

        # Manually set the stop time far in the past
        controller._last_stop_time = time.time() - 100

        success, msg = controller.start()
        assert success is True

    def test_first_start_has_no_delay(self, controller):
        """The very first start should not require any delay."""
        success, msg = controller.start()
        assert success is True


# --------------------------------------------------------------------------
# Status Reading Tests
# --------------------------------------------------------------------------

class TestTurboPumpStatus:
    """Tests for the read_status() method."""

    def test_status_off_when_not_commanded(self, controller):
        """Status should be OFF when pump hasn't been commanded ON."""
        status = controller.read_status()
        assert status == controller.STATE_OFF

    def test_status_normal_when_dio_low(self, controller):
        """When commanded ON and DIO reads LOW, status should be NORMAL."""
        controller.start()
        mock_ljm.eReadName.return_value = 0.0  # LOW = NORMAL
        status = controller.read_status()
        assert status == controller.STATE_NORMAL

    def test_status_starting_when_dio_high(self, controller):
        """When commanded ON and DIO reads HIGH, status should be STARTING."""
        controller.start()
        mock_ljm.eReadName.return_value = 1.0  # HIGH = not normal
        status = controller.read_status()
        assert status == controller.STATE_STARTING

    def test_status_unknown_on_error(self, controller):
        """Status should be UNKNOWN on LabJack read error."""
        controller.start()
        mock_ljm.eReadName.side_effect = Exception("read error")
        status = controller.read_status()
        assert status == controller.STATE_UNKNOWN


# --------------------------------------------------------------------------
# Status Dict Tests
# --------------------------------------------------------------------------

class TestStatusDict:
    """Tests for get_status_dict() used in data logging."""

    def test_status_dict_off(self, controller):
        """Status dict should show OFF when not commanded."""
        d = controller.get_status_dict()
        assert d['Turbo_Commanded'] == 'OFF'
        assert d['Turbo_Status'] == 'OFF'

    def test_status_dict_on_and_normal(self, controller):
        """Status dict should show ON + NORMAL when at speed."""
        controller.start()
        mock_ljm.eReadName.return_value = 0.0  # NORMAL
        d = controller.get_status_dict()
        assert d['Turbo_Commanded'] == 'ON'
        assert d['Turbo_Status'] == 'NORMAL'


# --------------------------------------------------------------------------
# Emergency Stop Tests
# --------------------------------------------------------------------------

class TestEmergencyStop:
    """Tests for the emergency_stop() method."""

    def test_emergency_stop_sets_dio_low(self, controller):
        """Emergency stop should force DIO LOW immediately."""
        controller.start()
        mock_ljm.eWriteName.reset_mock()

        controller.emergency_stop()
        mock_ljm.eWriteName.assert_called_with(12345, 'DIO0', 0)

    def test_emergency_stop_sets_commanded_off(self, controller):
        """Emergency stop should set commanded state to off."""
        controller.start()
        controller.emergency_stop()
        assert controller.is_commanded_on() is False

    def test_emergency_stop_survives_ljm_error(self, controller):
        """Emergency stop should not raise even if LabJack fails."""
        controller.start()
        mock_ljm.eWriteName.side_effect = Exception("hardware gone")
        # Should not raise
        controller.emergency_stop()
        assert controller.is_commanded_on() is False


# --------------------------------------------------------------------------
# Cleanup Tests
# --------------------------------------------------------------------------

class TestCleanup:
    """Tests for cleanup on application shutdown."""

    def test_cleanup_stops_pump(self, controller):
        """Cleanup should ensure the pump relay is off."""
        controller.start()
        mock_ljm.eWriteName.reset_mock()

        controller.cleanup()
        mock_ljm.eWriteName.assert_called_with(12345, 'DIO0', 0)

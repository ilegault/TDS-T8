"""
Unit tests for RampExecutor class.
"""

import unittest
import time
from unittest.mock import MagicMock, patch

from t8_daq_system.control.ramp_profile import RampProfile
from t8_daq_system.control.ramp_executor import RampExecutor, ExecutorState


class TestRampExecutorInit(unittest.TestCase):
    """Tests for RampExecutor initialization."""

    def test_create_without_power_supply(self):
        """Test creating executor without power supply (simulation mode)."""
        executor = RampExecutor()
        self.assertIsNone(executor.power_supply)
        self.assertEqual(executor.state, ExecutorState.IDLE)

    def test_create_with_power_supply(self):
        """Test creating executor with power supply."""
        mock_ps = MagicMock()
        executor = RampExecutor(power_supply_controller=mock_ps)
        self.assertEqual(executor.power_supply, mock_ps)

    def test_create_with_custom_interval(self):
        """Test creating executor with custom update interval."""
        executor = RampExecutor(update_interval_ms=50)
        self.assertEqual(executor.update_interval_sec, 0.05)


class TestRampExecutorProfileLoading(unittest.TestCase):
    """Tests for profile loading."""

    def setUp(self):
        """Set up test fixtures."""
        self.executor = RampExecutor()
        self.profile = RampProfile(name="Test", start_voltage=0.0)
        self.profile.add_ramp(5.0, 1.0)  # 1 second ramp
        self.profile.add_hold(1.0)  # 1 second hold

    def test_load_valid_profile(self):
        """Test loading a valid profile."""
        success = self.executor.load_profile(self.profile)
        self.assertTrue(success)
        self.assertEqual(self.executor.profile.name, "Test")

    def test_load_invalid_profile(self):
        """Test loading an invalid (empty) profile."""
        empty_profile = RampProfile()
        success = self.executor.load_profile(empty_profile)
        self.assertFalse(success)

    def test_cannot_load_while_running(self):
        """Test that profiles cannot be loaded while running."""
        self.executor.load_profile(self.profile)
        self.executor.start()

        try:
            new_profile = RampProfile()
            new_profile.add_ramp(10.0, 1.0)
            success = self.executor.load_profile(new_profile)
            self.assertFalse(success)
        finally:
            self.executor.stop()


class TestRampExecutorExecution(unittest.TestCase):
    """Tests for profile execution."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_ps = MagicMock()
        self.mock_ps.set_voltage.return_value = True
        self.mock_ps.set_current.return_value = True

        self.executor = RampExecutor(
            power_supply_controller=self.mock_ps,
            update_interval_ms=50  # Fast updates for testing
        )

        self.profile = RampProfile(name="Test", start_voltage=0.0, current_limit=25.0)
        self.profile.add_ramp(5.0, 0.2)  # 200ms ramp
        self.profile.add_hold(0.1)  # 100ms hold

    def tearDown(self):
        """Clean up after tests."""
        if self.executor.is_active():
            self.executor.stop()

    def test_start_without_profile(self):
        """Test that start fails without a loaded profile."""
        success = self.executor.start()
        self.assertFalse(success)

    def test_start_with_profile(self):
        """Test starting execution with a profile."""
        self.executor.load_profile(self.profile)
        success = self.executor.start()
        self.assertTrue(success)
        self.assertEqual(self.executor.state, ExecutorState.RUNNING)
        self.executor.stop()

    def test_start_sets_current_limit(self):
        """Test that start sets the current limit on power supply at startup."""
        self.executor.load_profile(self.profile)
        self.executor.start()

        # Give it time to initialize
        time.sleep(0.05)

        # The startup call with current_limit (25.0) must have happened.
        # The run loop also calls set_current() with interpolated per-step values,
        # so we use assert_any_call rather than assert_called_with (last-call check).
        self.mock_ps.set_current.assert_any_call(25.0)
        self.executor.stop()

    def test_stop_execution(self):
        """Test stopping execution."""
        self.executor.load_profile(self.profile)
        self.executor.start()
        time.sleep(0.05)

        success = self.executor.stop()
        self.assertTrue(success)
        self.assertEqual(self.executor.state, ExecutorState.ABORTED)

    def test_stop_sets_voltage_to_zero(self):
        """Test that stop sets voltage to 0."""
        self.executor.load_profile(self.profile)
        self.executor.start()
        time.sleep(0.05)
        self.executor.stop()

        # Last call to set_voltage should be 0.0
        self.mock_ps.set_voltage.assert_called_with(0.0)

    def test_pause_and_resume(self):
        """Test pausing and resuming execution."""
        self.executor.load_profile(self.profile)
        self.executor.start()
        time.sleep(0.05)

        # Pause
        success = self.executor.pause()
        self.assertTrue(success)
        self.assertEqual(self.executor.state, ExecutorState.PAUSED)

        # Resume
        success = self.executor.resume()
        self.assertTrue(success)
        self.assertEqual(self.executor.state, ExecutorState.RUNNING)

        self.executor.stop()

    def test_pause_while_not_running(self):
        """Test that pause fails when not running."""
        success = self.executor.pause()
        self.assertFalse(success)

    def test_resume_while_not_paused(self):
        """Test that resume fails when not paused."""
        success = self.executor.resume()
        self.assertFalse(success)

    def test_profile_completion(self):
        """Test that profile completes successfully."""
        self.executor.load_profile(self.profile)
        self.executor.start()

        # Wait for profile to complete (200ms + 100ms + buffer)
        time.sleep(0.5)

        self.assertEqual(self.executor.state, ExecutorState.COMPLETED)

    def test_voltage_commands_sent(self):
        """Test that voltage commands are sent to power supply."""
        self.executor.load_profile(self.profile)
        self.executor.start()

        # Wait for some updates
        time.sleep(0.15)
        self.executor.stop()

        # Should have called set_voltage multiple times
        self.assertGreater(self.mock_ps.set_voltage.call_count, 0)


class TestRampExecutorCallbacks(unittest.TestCase):
    """Tests for executor callbacks."""

    def setUp(self):
        """Set up test fixtures."""
        self.executor = RampExecutor(update_interval_ms=50)

        self.profile = RampProfile(name="Test", start_voltage=0.0)
        self.profile.add_ramp(5.0, 0.2)
        self.profile.add_hold(0.1)

    def tearDown(self):
        """Clean up after tests."""
        if self.executor.is_active():
            self.executor.stop()

    def test_on_setpoint_change_callback(self):
        """Test setpoint change callback."""
        callback = MagicMock()
        self.executor.on_setpoint_change(callback)
        self.executor.load_profile(self.profile)
        self.executor.start()

        time.sleep(0.15)
        self.executor.stop()

        self.assertGreater(callback.call_count, 0)

    def test_on_step_change_callback(self):
        """Test step change callback."""
        callback = MagicMock()
        self.executor.on_step_change(callback)
        self.executor.load_profile(self.profile)
        self.executor.start()

        time.sleep(0.4)
        self.executor.stop()

        # Should have been called at least once (for first step)
        self.assertGreater(callback.call_count, 0)

    def test_on_complete_callback(self):
        """Test completion callback."""
        callback = MagicMock()
        self.executor.on_complete(callback)
        self.executor.load_profile(self.profile)
        self.executor.start()

        # Wait for completion
        time.sleep(0.5)

        callback.assert_called_once()

    def test_on_state_change_callback(self):
        """Test state change callback."""
        states = []
        callback = lambda s: states.append(s)
        self.executor.on_state_change(callback)
        self.executor.load_profile(self.profile)
        self.executor.start()

        time.sleep(0.1)
        self.executor.stop()

        # Should have RUNNING in states
        self.assertIn(ExecutorState.RUNNING, states)


class TestRampExecutorStatus(unittest.TestCase):
    """Tests for executor status methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.executor = RampExecutor(update_interval_ms=50)

        self.profile = RampProfile(name="Test", start_voltage=0.0)
        self.profile.add_ramp(5.0, 1.0)  # 1 second ramp

    def tearDown(self):
        """Clean up after tests."""
        if self.executor.is_active():
            self.executor.stop()

    def test_get_elapsed_time(self):
        """Test getting elapsed time."""
        self.executor.load_profile(self.profile)
        self.executor.start()

        time.sleep(0.2)
        elapsed = self.executor.get_elapsed_time()

        self.assertGreater(elapsed, 0.1)
        self.assertLess(elapsed, 0.5)

        self.executor.stop()

    def test_get_progress(self):
        """Test getting progress percentage."""
        self.executor.load_profile(self.profile)
        self.executor.start()

        time.sleep(0.2)
        progress = self.executor.get_progress()

        self.assertGreater(progress, 0.0)
        self.assertLess(progress, 100.0)

        self.executor.stop()

    def test_get_remaining_time(self):
        """Test getting remaining time."""
        self.executor.load_profile(self.profile)
        self.executor.start()

        time.sleep(0.1)
        remaining = self.executor.get_remaining_time()

        # Should be less than total (1 second) but greater than 0
        self.assertGreater(remaining, 0.0)
        self.assertLess(remaining, 1.0)

        self.executor.stop()

    def test_get_status(self):
        """Test getting comprehensive status."""
        self.executor.load_profile(self.profile)
        status = self.executor.get_status()

        self.assertIn('state', status)
        self.assertIn('profile_name', status)
        self.assertIn('current_setpoint', status)
        self.assertIn('progress_percent', status)
        self.assertEqual(status['profile_name'], "Test")

    def test_is_running(self):
        """Test is_running property."""
        self.executor.load_profile(self.profile)

        self.assertFalse(self.executor.is_running())

        self.executor.start()
        self.assertTrue(self.executor.is_running())

        self.executor.pause()
        self.assertFalse(self.executor.is_running())

        self.executor.stop()

    def test_is_active(self):
        """Test is_active property (running or paused)."""
        self.executor.load_profile(self.profile)

        self.assertFalse(self.executor.is_active())

        self.executor.start()
        self.assertTrue(self.executor.is_active())

        self.executor.pause()
        self.assertTrue(self.executor.is_active())  # Still active when paused

        self.executor.stop()
        self.assertFalse(self.executor.is_active())


class TestRampExecutorErrorHandling(unittest.TestCase):
    """Tests for error handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_ps = MagicMock()
        self.executor = RampExecutor(
            power_supply_controller=self.mock_ps,
            update_interval_ms=50
        )

        # Use a longer profile so error can be detected before completion
        self.profile = RampProfile(name="Test", start_voltage=0.0)
        self.profile.add_ramp(5.0, 5.0)  # 5 second ramp

    def tearDown(self):
        """Clean up after tests."""
        if self.executor.is_active():
            self.executor.stop()

    def test_power_supply_error_triggers_error_state(self):
        """Test that power supply error triggers error state."""
        self.mock_ps.set_current.return_value = True
        self.mock_ps.set_voltage.side_effect = Exception("Connection lost")

        error_callback = MagicMock()
        self.executor.on_error(error_callback)

        self.executor.load_profile(self.profile)
        self.executor.start()

        # Wait for error to be detected (poll with timeout)
        for _ in range(20):  # Up to 1 second
            if self.executor.state == ExecutorState.ERROR:
                break
            time.sleep(0.05)

        self.assertEqual(self.executor.state, ExecutorState.ERROR)
        error_callback.assert_called()

    def test_current_limit_error_prevents_start(self):
        """Test that current limit error prevents start."""
        self.mock_ps.set_current.side_effect = Exception("Current limit error")

        self.executor.load_profile(self.profile)
        success = self.executor.start()

        self.assertFalse(success)
        self.assertEqual(self.executor.state, ExecutorState.ERROR)


if __name__ == '__main__':
    unittest.main()

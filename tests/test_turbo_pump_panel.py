"""
test_turbo_pump_panel.py
PURPOSE: Unit tests for TurboPumpPanel GUI widget.

Tests the panel's behavior without needing real hardware.
Uses a mock controller and a real tkinter root (hidden).
"""

import pytest
from unittest.mock import Mock, patch

tk = pytest.importorskip("tkinter", reason="tkinter not available")


@pytest.fixture
def root():
    """Create a hidden tkinter root for widget testing."""
    root = tk.Tk()
    root.withdraw()  # Don't show the window
    yield root
    root.destroy()


@pytest.fixture
def mock_controller():
    """Create a mock TurboPumpController."""
    ctrl = Mock()
    ctrl.start.return_value = (True, "Start command sent")
    ctrl.stop.return_value = (True, "Stop command sent")
    ctrl.read_status.return_value = "OFF"
    ctrl.is_commanded_on.return_value = False
    return ctrl


@pytest.fixture
def panel(root):
    """Create a TurboPumpPanel attached to the root window."""
    from t8_daq_system.gui.turbo_pump_panel import TurboPumpPanel
    p = TurboPumpPanel(root)
    p.pack()
    return p


class TestPanelInit:
    """Tests for panel initialization."""

    def test_buttons_disabled_without_controller(self, panel):
        """Buttons should be disabled until a controller is set."""
        assert panel.on_btn['state'] == 'disabled'
        assert panel.off_btn['state'] == 'disabled'

    def test_buttons_enabled_with_controller(self, panel, mock_controller):
        """Buttons should be enabled when controller is set."""
        panel.set_controller(mock_controller)
        assert panel.on_btn['state'] == 'normal'
        assert panel.off_btn['state'] == 'normal'

    def test_set_controller_none_disables(self, panel, mock_controller):
        """Setting controller to None should disable buttons."""
        panel.set_controller(mock_controller)
        panel.set_controller(None)
        assert panel.on_btn['state'] == 'disabled'


class TestPanelStatusDisplay:
    """Tests for the status indicator updates."""

    def test_status_shows_off(self, panel, mock_controller):
        """Panel should show OFF when pump is off."""
        mock_controller.read_status.return_value = "OFF"
        panel.set_controller(mock_controller)
        panel.update_status_display()
        assert panel.status_label['text'] == 'OFF'

    def test_status_shows_normal(self, panel, mock_controller):
        """Panel should show NORMAL when pump is at speed."""
        mock_controller.read_status.return_value = "NORMAL"
        panel.set_controller(mock_controller)
        panel.update_status_display()
        assert panel.status_label['text'] == 'NORMAL'

    def test_status_shows_starting(self, panel, mock_controller):
        """Panel should show STARTING during acceleration."""
        mock_controller.read_status.return_value = "STARTING"
        panel.set_controller(mock_controller)
        panel.update_status_display()
        assert panel.status_label['text'] == 'STARTING'


class TestPanelCommands:
    """Tests for button click handlers."""

    @patch('t8_daq_system.gui.turbo_pump_panel.messagebox')
    def test_on_calls_start_after_confirm(self, mock_msgbox, panel, mock_controller):
        """Clicking ON and confirming should call controller.start()."""
        mock_msgbox.askyesno.return_value = True
        panel.set_controller(mock_controller)
        panel._on_turbo_on()
        mock_controller.start.assert_called_once()

    @patch('t8_daq_system.gui.turbo_pump_panel.messagebox')
    def test_on_cancelled_does_not_start(self, mock_msgbox, panel, mock_controller):
        """Clicking ON but cancelling should NOT call controller.start()."""
        mock_msgbox.askyesno.return_value = False
        panel.set_controller(mock_controller)
        panel._on_turbo_on()
        mock_controller.start.assert_not_called()

    def test_off_calls_stop(self, panel, mock_controller):
        """Clicking OFF should call controller.stop()."""
        panel.set_controller(mock_controller)
        panel._on_turbo_off()
        mock_controller.stop.assert_called_once()

    def test_off_shows_error_on_failure(self, panel, mock_controller):
        """If stop fails, the error message should display."""
        mock_controller.stop.return_value = (False, "LabJack error")
        panel.set_controller(mock_controller)
        panel._on_turbo_off()
        assert 'red' in str(panel.message_label['foreground'])

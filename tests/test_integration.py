import unittest
from unittest.mock import MagicMock, patch
import sys
import json
import os
import tempfile

# conftest.py handles mocking of labjack, pyvisa, serial, tkinter, matplotlib
from t8_daq_system.gui.main_window import MainWindow

class TestIntegration(unittest.TestCase):
    def setUp(self):
        # We no longer need temp config files as MainWindow uses AppSettings (Registry-backed)
        pass

    def tearDown(self):
        pass

    def _make_mock_settings(self, mock_settings_cls):
        """Return a fully-configured mock AppSettings object."""
        mock_settings = mock_settings_cls.return_value
        mock_settings.tc_count = 1
        mock_settings.tc_unit = "C"
        mock_settings.frg_count = 1
        mock_settings.p_unit = "mbar"
        mock_settings.sample_rate_ms = 1000
        mock_settings.display_rate_ms = 1000
        mock_settings.use_absolute_scales = True
        mock_settings.temp_range = (0.0, 2500.0)
        mock_settings.press_range = (1e-9, 1e-3)
        mock_settings.ps_v_range = (0.0, 100.0)
        mock_settings.ps_i_range = (0.0, 100.0)
        mock_settings.get_tc_type_list.return_value = ["C"]
        mock_settings.get_frg_pin_list.return_value = ["AIN2"]
        mock_settings.visa_resource = ""
        mock_settings.frg_interface = "XGS600"
        mock_settings.ps_interface = "Analog"
        return mock_settings

    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.AppSettings')
    def test_main_window_init(self, mock_settings_cls, mock_sensor_panel, mock_plot, mock_tk):
        """Test that MainWindow can be instantiated with all GUI components mocked."""
        mock_settings = self._make_mock_settings(mock_settings_cls)
        app = MainWindow(settings=mock_settings)
        self.assertEqual(app.config['device']['type'], "T8")
        self.assertFalse(app.is_running)

    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.AppSettings')
    def test_no_start_stop_buttons(self, mock_settings_cls, mock_sensor_panel, mock_plot, mock_tk):
        """Verify that start_btn and stop_btn attributes no longer exist (buttons removed)."""
        mock_settings = self._make_mock_settings(mock_settings_cls)
        app = MainWindow(settings=mock_settings)
        self.assertFalse(hasattr(app, 'start_btn'),
                         "start_btn should not exist — Start button was removed")
        self.assertFalse(hasattr(app, 'stop_btn'),
                         "stop_btn should not exist — Stop button was removed")

    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.AppSettings')
    def test_log_btn_exists(self, mock_settings_cls, mock_sensor_panel, mock_plot, mock_tk):
        """Verify that the Start Logging button still exists."""
        mock_settings = self._make_mock_settings(mock_settings_cls)
        app = MainWindow(settings=mock_settings)
        self.assertTrue(hasattr(app, 'log_btn'),
                        "log_btn (Start Logging button) must exist")

    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.AppSettings')
    def test_slider_mode_btn_exists(self, mock_settings_cls, mock_sensor_panel, mock_plot, mock_tk):
        """Verify that the slider mode toggle button exists."""
        mock_settings = self._make_mock_settings(mock_settings_cls)
        app = MainWindow(settings=mock_settings)
        self.assertTrue(hasattr(app, '_slider_mode_btn'),
                        "_slider_mode_btn must exist (History % / 2-min Window toggle)")

    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.AppSettings')
    def test_auto_start_acquisition_not_running_without_hardware(
            self, mock_settings_cls, mock_sensor_panel, mock_plot, mock_tk):
        """Without hardware, acquisition should not auto-start (is_running stays False)."""
        mock_settings = self._make_mock_settings(mock_settings_cls)
        app = MainWindow(settings=mock_settings)
        # Deferred hardware init hasn't run (it's triggered by root.after which is mocked)
        # so is_running should still be False
        self.assertFalse(app.is_running)

    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.AppSettings')
    def test_auto_start_acquisition_method_exists(
            self, mock_settings_cls, mock_sensor_panel, mock_plot, mock_tk):
        """_auto_start_acquisition method must exist and be callable."""
        mock_settings = self._make_mock_settings(mock_settings_cls)
        app = MainWindow(settings=mock_settings)
        self.assertTrue(hasattr(app, '_auto_start_acquisition'))
        self.assertTrue(callable(app._auto_start_acquisition))

    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.AppSettings')
    def test_auto_start_idempotent(self, mock_settings_cls, mock_sensor_panel, mock_plot, mock_tk):
        """Calling _auto_start_acquisition twice should not double-start."""
        mock_settings = self._make_mock_settings(mock_settings_cls)
        app = MainWindow(settings=mock_settings)

        # Patch _on_start to count calls
        call_count = []
        original_on_start = app._on_start

        def counting_on_start():
            call_count.append(1)
            app.is_running = True  # simulate what _on_start does

        app._on_start = counting_on_start

        app._auto_start_acquisition()  # should call _on_start (is_running=False)
        app._auto_start_acquisition()  # should NOT call again (is_running=True)

        self.assertEqual(len(call_count), 1,
                         "_auto_start_acquisition should call _on_start only once")

if __name__ == '__main__':
    unittest.main()

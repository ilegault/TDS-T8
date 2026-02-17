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
        self.config = {
            "device": {"type": "T8", "connection": "USB", "identifier": "ANY"},
            "thermocouples": [{"name": "TC1", "channel": 0, "type": "K", "units": "C", "enabled": True}],
            "frg702_gauges": [{"name": "Gauge1", "channel": 0, "enabled": True}],
            "logging": {"interval_ms": 100, "file_prefix": "test_log", "auto_start": False},
            "display": {"update_rate_ms": 100, "history_seconds": 10}
        }
        self.temp_config = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        json.dump(self.config, self.temp_config)
        self.temp_config.close()

    def tearDown(self):
        if os.path.exists(self.temp_config.name):
            os.unlink(self.temp_config.name)

    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.RampPanel')
    @patch('t8_daq_system.gui.main_window.PowerSupplyPanel')
    def test_main_window_init(self, mock_ps_panel, mock_ramp_panel,
                               mock_panel, mock_plot, mock_tk):
        """Test that MainWindow can be instantiated with all GUI components mocked."""
        app = MainWindow(config_path=self.temp_config.name)
        self.assertEqual(app.config['device']['type'], "T8")
        self.assertFalse(app.is_running)

if __name__ == '__main__':
    unittest.main()

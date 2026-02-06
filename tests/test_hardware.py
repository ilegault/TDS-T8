import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock labjack and labjack.ljm before importing the modules that use them
mock_ljm = MagicMock()
mock_labjack = MagicMock()
mock_labjack.ljm = mock_ljm
sys.modules['labjack'] = mock_labjack
sys.modules['labjack.ljm'] = mock_ljm

from t8_daq_system.hardware.thermocouple_reader import ThermocoupleReader
from t8_daq_system.hardware.labjack_connection import LabJackConnection
import json
import os
import tempfile

class TestHardware(unittest.TestCase):
    def setUp(self):
        self.mock_handle = 1
        self.tc_config = [
            {
                "name": "TC1",
                "channel": 0,
                "type": "K",
                "units": "C",
                "enabled": True
            }
        ]
        self.full_config = {
            "device": {
                "type": "T8",
                "connection": "USB",
                "identifier": "ANY"
            },
            "thermocouples": self.tc_config
        }
        self.temp_config = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        json.dump(self.full_config, self.temp_config)
        self.temp_config.close()

    def tearDown(self):
        os.unlink(self.temp_config.name)

    def test_labjack_connection(self):
        # We use the mock_ljm we defined at the top
        mock_ljm.openS.return_value = self.mock_handle
        mock_ljm.getHandleInfo.return_value = ("T8", "USB", 12345, "1.1.1.1", 1, 1024)
        mock_ljm.LJMError = Exception # Mocking the error class
        
        conn = LabJackConnection()
        self.assertTrue(conn.connect())
        self.assertEqual(conn.get_handle(), self.mock_handle)
        self.assertTrue(conn.is_connected())
        
        info = conn.get_device_info()
        self.assertEqual(info['serial_number'], 12345)
        
        conn.disconnect()
        mock_ljm.close.assert_called_with(self.mock_handle)
        self.assertFalse(conn.is_connected())

    def test_tc_reader_init(self):
        reader = ThermocoupleReader(self.mock_handle, self.tc_config)
        # Check if some configuration calls were made
        self.assertTrue(mock_ljm.eWriteName.called)

    def test_tc_reader_read_all(self):
        mock_ljm.eReadName.return_value = 25.5
        reader = ThermocoupleReader(self.mock_handle, self.tc_config)
        readings = reader.read_all()
        
        self.assertEqual(readings['TC1'], 25.5)
        mock_ljm.eReadName.assert_called_with(self.mock_handle, "AIN0_EF_READ_A")

    def test_tc_reader_read_error(self):
        mock_ljm.eReadName.return_value = -9999
        reader = ThermocoupleReader(self.mock_handle, self.tc_config)
        readings = reader.read_all()
        
        self.assertIsNone(readings['TC1'])

if __name__ == '__main__':
    unittest.main()

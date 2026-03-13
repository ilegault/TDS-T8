import unittest
from t8_daq_system.data.data_buffer import DataBuffer
import time

class TestDataBuffer(unittest.TestCase):
    def test_buffer_initialization(self):
        buffer = DataBuffer(max_seconds=10, sample_rate_ms=1000)
        self.assertEqual(buffer.max_samples, 10)
        self.assertEqual(len(buffer.timestamps), 0)
        self.assertEqual(len(buffer.data), 0)

    def test_add_reading(self):
        buffer = DataBuffer(max_seconds=10, sample_rate_ms=1000)
        readings = {'TC1': 25.0, 'P1': 10.0}
        buffer.add_reading(readings)
        
        self.assertEqual(len(buffer.timestamps), 1)
        self.assertEqual(buffer.get_all_current(), readings)
        self.assertIn('TC1', buffer.data)
        self.assertIn('P1', buffer.data)

    def test_buffer_circularity(self):
        # Max 2 samples
        buffer = DataBuffer(max_seconds=2, sample_rate_ms=1000)
        buffer.add_reading({'TC1': 10})
        buffer.add_reading({'TC1': 20})
        buffer.add_reading({'TC1': 30}) # Should drop 10
        
        self.assertEqual(len(buffer.timestamps), 2)
        self.assertEqual(list(buffer.data['TC1']), [20, 30])

    def test_get_sensor_data(self):
        buffer = DataBuffer(max_seconds=10, sample_rate_ms=1000)
        buffer.add_reading({'TC1': 25.0})
        timestamps, values = buffer.get_sensor_data('TC1')
        self.assertEqual(len(timestamps), 1)
        self.assertEqual(values, [25.0])
        
        timestamps, values = buffer.get_sensor_data('NonExistent')
        self.assertEqual(timestamps, [])
        self.assertEqual(values, [])

    def test_clear(self):
        buffer = DataBuffer()
        buffer.add_reading({'TC1': 25.0})
        buffer.clear()
        self.assertEqual(len(buffer.timestamps), 0)
        self.assertEqual(len(buffer.data), 0)

    def test_synchronization_with_changing_sensors(self):
        """Verify all sensor deques stay the same length as timestamps."""
        buffer = DataBuffer(max_seconds=10, sample_rate_ms=1000)
        
        # 1. First reading: only TC1
        buffer.add_reading({'TC1': 1.0})
        self.assertEqual(len(buffer.timestamps), 1)
        self.assertEqual(len(buffer.data['TC1']), 1)
        
        # 2. Second reading: TC1 and new sensor TC2
        buffer.add_reading({'TC1': 2.0, 'TC2': 20.0})
        self.assertEqual(len(buffer.timestamps), 2)
        self.assertEqual(len(buffer.data['TC1']), 2)
        self.assertEqual(len(buffer.data['TC2']), 2)
        self.assertEqual(buffer.data['TC2'][0], None) # Should be padded
        self.assertEqual(buffer.data['TC2'][1], 20.0)
        
        # 3. Third reading: only TC2 (TC1 missing)
        buffer.add_reading({'TC2': 30.0})
        self.assertEqual(len(buffer.timestamps), 3)
        self.assertEqual(len(buffer.data['TC1']), 3)
        self.assertEqual(len(buffer.data['TC2']), 3)
        self.assertEqual(buffer.data['TC1'][2], None) # Should be padded
        self.assertEqual(buffer.data['TC2'][2], 30.0)

if __name__ == '__main__':
    unittest.main()

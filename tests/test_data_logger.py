import unittest
import os
import shutil
import tempfile
import csv
from t8_daq_system.data.data_logger import DataLogger

class TestDataLogger(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.logger = DataLogger(log_folder=self.test_dir)

    def tearDown(self):
        self.logger.stop_logging()
        shutil.rmtree(self.test_dir)

    def test_start_logging(self):
        sensor_names = ['TC1', 'P1']
        filepath = self.logger.start_logging(sensor_names)

        self.assertTrue(os.path.exists(filepath))
        self.assertTrue(self.logger.is_logging())

        # Check header (skip metadata line)
        with open(filepath, 'r') as f:
            lines = f.readlines()
            # First line is metadata, second line is header
            header_line = None
            for line in lines:
                if line.startswith('Timestamp'):
                    header_line = line.strip()
                    break

            self.assertIsNotNone(header_line)
            self.assertIn('Timestamp', header_line)
            self.assertIn('TC1', header_line)
            self.assertIn('P1', header_line)

    def test_log_reading(self):
        sensor_names = ['TC1', 'P1']
        filepath = self.logger.start_logging(sensor_names)

        readings = {'TC1': 25.5, 'P1': 100.2}
        self.logger.log_reading(readings)
        self.logger.stop_logging()

        with open(filepath, 'r') as f:
            lines = f.readlines()
            # Find the data line (not metadata, not header)
            data_line = None
            for line in lines:
                if not line.startswith('#') and not line.startswith('Timestamp'):
                    data_line = line.strip()
                    break

            self.assertIsNotNone(data_line)
            parts = data_line.split(',')
            # parts[0] is timestamp, parts[1] is TC1, parts[2] is P1
            self.assertEqual(parts[1], '25.5')
            self.assertEqual(parts[2], '100.2')

    def test_get_log_files(self):
        self.logger.start_logging(['S1'])
        self.logger.stop_logging()

        files = self.logger.get_log_files()
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith('.csv'))

if __name__ == '__main__':
    unittest.main()

"""
Extended unit tests for DataLogger class - metadata, custom names, CSV loading
"""

import unittest
import os
import shutil
import tempfile
import csv
import json
from datetime import datetime

from t8_daq_system.data.data_logger import DataLogger, create_metadata_dict


class TestDataLoggerMetadata(unittest.TestCase):
    """Test metadata functionality in DataLogger."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logger = DataLogger(log_folder=self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        self.logger.stop_logging()
        shutil.rmtree(self.test_dir)

    def test_start_logging_with_metadata(self):
        """Test starting logging with metadata."""
        sensor_names = ['TC_1', 'FRG702_1']
        metadata = create_metadata_dict(
            tc_count=1,
            tc_type="K",
            tc_unit="C",
            frg702_count=1,
            frg702_unit="mbar",
            sample_rate_ms=100,
            notes="Test run"
        )

        filepath = self.logger.start_logging(sensor_names, metadata=metadata)

        self.assertTrue(os.path.exists(filepath))

        # Read file and verify metadata
        with open(filepath, 'r') as f:
            first_line = f.readline()
            self.assertTrue(first_line.startswith(DataLogger.METADATA_PREFIX))

            # Parse metadata JSON
            json_str = first_line[len(DataLogger.METADATA_PREFIX):].strip()
            parsed_metadata = json.loads(json_str)

            self.assertEqual(parsed_metadata['tc_count'], 1)
            self.assertEqual(parsed_metadata['tc_type'], "K")
            self.assertEqual(parsed_metadata['notes'], "Test run")

    def test_metadata_includes_start_time(self):
        """Test that metadata includes start time."""
        sensor_names = ['TC_1']
        filepath = self.logger.start_logging(sensor_names)

        with open(filepath, 'r') as f:
            first_line = f.readline()
            json_str = first_line[len(DataLogger.METADATA_PREFIX):].strip()
            parsed_metadata = json.loads(json_str)

            self.assertIn('start_time', parsed_metadata)
            # Verify it's a valid ISO format datetime
            datetime.fromisoformat(parsed_metadata['start_time'])

    def test_stop_logging_adds_end_time(self):
        """Test that stop_logging adds end time comment."""
        sensor_names = ['TC_1']
        filepath = self.logger.start_logging(sensor_names)
        self.logger.log_reading({'TC_1': 25.0})
        self.logger.stop_logging()

        with open(filepath, 'r') as f:
            lines = f.readlines()
            last_line = lines[-1]
            self.assertTrue(last_line.startswith('#END_TIME:'))


class TestDataLoggerCustomFilenames(unittest.TestCase):
    """Test custom filename functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logger = DataLogger(log_folder=self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        self.logger.stop_logging()
        shutil.rmtree(self.test_dir)

    def test_custom_name_in_filename(self):
        """Test that custom name is included in filename."""
        sensor_names = ['TC_1']
        custom_name = "My Test Run"

        filepath = self.logger.start_logging(sensor_names, custom_name=custom_name)
        filename = os.path.basename(filepath)

        self.assertIn("My_Test_Run", filename)
        self.assertTrue(filename.endswith('.csv'))

    def test_custom_name_sanitization(self):
        """Test that unsafe characters are removed from custom name."""
        sensor_names = ['TC_1']
        custom_name = "Test/Run\\With:Bad*Chars?"

        filepath = self.logger.start_logging(sensor_names, custom_name=custom_name)
        filename = os.path.basename(filepath)

        # Should not contain any unsafe characters
        self.assertNotIn('/', filename)
        self.assertNotIn('\\', filename)
        self.assertNotIn(':', filename)
        self.assertNotIn('*', filename)
        self.assertNotIn('?', filename)

    def test_no_custom_name_uses_timestamp_only(self):
        """Test that no custom name uses timestamp-only format."""
        sensor_names = ['TC_1']

        filepath = self.logger.start_logging(sensor_names)
        filename = os.path.basename(filepath)

        # Should match pattern: data_log_YYYYMMDD_HHMMSS.csv
        self.assertTrue(filename.startswith('data_log_'))
        parts = filename.replace('.csv', '').split('_')
        # Should be: data, log, date, time
        self.assertEqual(len(parts), 4)


class TestDataLoggerCSVLoading(unittest.TestCase):
    """Test CSV loading functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logger = DataLogger(log_folder=self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        self.logger.stop_logging()
        shutil.rmtree(self.test_dir)

    def test_load_csv_with_metadata(self):
        """Test loading CSV with metadata."""
        # Create a test file
        sensor_names = ['TC_1', 'FRG702_1']
        metadata = create_metadata_dict(
            tc_count=1,
            tc_type="K",
            tc_unit="C",
            frg702_count=1,
            frg702_unit="mbar"
        )

        filepath = self.logger.start_logging(sensor_names, metadata=metadata)

        # Log some data
        self.logger.log_reading({'TC_1': 25.0, 'FRG702_1': 1.0e-5})
        self.logger.log_reading({'TC_1': 26.0, 'FRG702_1': 1.1e-5})
        self.logger.log_reading({'TC_1': 27.0, 'FRG702_1': 1.2e-5})
        self.logger.stop_logging()

        # Load the file
        loaded_metadata, loaded_data = DataLogger.load_csv_with_metadata(filepath)

        # Verify metadata - note: metadata is merged with logger's internal metadata
        self.assertIn('tc_count', loaded_metadata)
        self.assertEqual(loaded_metadata['tc_count'], 1)
        self.assertEqual(loaded_metadata['tc_type'], "K")
        self.assertIn('end_time', loaded_metadata)
        self.assertIn('start_time', loaded_metadata)

        # Verify data
        self.assertEqual(len(loaded_data['timestamps']), 3)
        self.assertEqual(len(loaded_data['TC_1']), 3)
        self.assertEqual(len(loaded_data['FRG702_1']), 3)
        self.assertEqual(loaded_data['TC_1'][0], 25.0)
        self.assertAlmostEqual(loaded_data['FRG702_1'][2], 1.2e-5)

    def test_load_csv_without_metadata(self):
        """Test loading CSV without metadata (legacy format)."""
        # Create a simple CSV file without metadata
        filepath = os.path.join(self.test_dir, 'legacy.csv')
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Timestamp', 'TC_1', 'FRG702_1'])
            writer.writerow(['2024-01-01T12:00:00', '25.0', '1.0e-5'])
            writer.writerow(['2024-01-01T12:00:01', '26.0', '1.1e-5'])

        # Load the file
        metadata, data = DataLogger.load_csv_with_metadata(filepath)

        # Should have empty metadata (except what we can infer)
        self.assertEqual(len(data['timestamps']), 2)
        self.assertEqual(data['TC_1'][0], 25.0)

    def test_load_csv_handles_empty_values(self):
        """Test that loading handles empty/missing values."""
        filepath = os.path.join(self.test_dir, 'with_gaps.csv')
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Timestamp', 'TC_1', 'FRG702_1'])
            writer.writerow(['2024-01-01T12:00:00', '25.0', ''])  # Missing FRG702_1
            writer.writerow(['2024-01-01T12:00:01', '', '1.1e-5'])  # Missing TC_1

        metadata, data = DataLogger.load_csv_with_metadata(filepath)

        self.assertEqual(len(data['timestamps']), 2)
        self.assertEqual(data['TC_1'][0], 25.0)
        self.assertIsNone(data['FRG702_1'][0])
        self.assertIsNone(data['TC_1'][1])
        self.assertAlmostEqual(data['FRG702_1'][1], 1.1e-5)


class TestDataLoggerGetCSVInfo(unittest.TestCase):
    """Test get_csv_info functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logger = DataLogger(log_folder=self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        self.logger.stop_logging()
        shutil.rmtree(self.test_dir)

    def test_get_csv_info_basic(self):
        """Test getting basic CSV info."""
        sensor_names = ['TC_1', 'TC_2', 'FRG702_1']
        metadata = create_metadata_dict(tc_count=2, frg702_count=1, notes="Test notes")

        filepath = self.logger.start_logging(sensor_names, custom_name="info_test", metadata=metadata)
        self.logger.log_reading({'TC_1': 25.0, 'TC_2': 26.0, 'FRG702_1': 1.0e-5})
        self.logger.log_reading({'TC_1': 25.5, 'TC_2': 26.5, 'FRG702_1': 1.1e-5})
        self.logger.stop_logging()

        info = DataLogger.get_csv_info(filepath)

        self.assertEqual(info['filename'], os.path.basename(filepath))
        self.assertEqual(info['row_count'], 2)
        self.assertEqual(len(info['sensors']), 3)
        self.assertIn('TC_1', info['sensors'])
        self.assertIn('size_kb', info)
        self.assertIn('modified', info)

    def test_get_csv_info_includes_settings(self):
        """Test that settings are extracted from metadata."""
        sensor_names = ['TC_1']
        metadata = create_metadata_dict(
            tc_count=1,
            tc_type="K",
            tc_unit="F",
            sample_rate_ms=500,
            notes="Important test"
        )

        filepath = self.logger.start_logging(sensor_names, metadata=metadata)
        self.logger.stop_logging()

        info = DataLogger.get_csv_info(filepath)

        self.assertEqual(info['settings']['tc_count'], 1)
        self.assertEqual(info['settings']['tc_type'], "K")
        self.assertEqual(info['settings']['tc_unit'], "F")
        self.assertEqual(info['settings']['sample_rate_ms'], 500)
        self.assertEqual(info['settings']['notes'], "Important test")


class TestCreateMetadataDict(unittest.TestCase):
    """Test create_metadata_dict helper function."""

    def test_creates_complete_dict(self):
        """Test that all fields are included."""
        metadata = create_metadata_dict(
            tc_count=3,
            tc_type="J",
            tc_unit="F",
            frg702_count=1,
            frg702_unit="torr",
            sample_rate_ms=200,
            notes="Test notes"
        )

        self.assertEqual(metadata['tc_count'], 3)
        self.assertEqual(metadata['tc_type'], "J")
        self.assertEqual(metadata['tc_unit'], "F")
        self.assertEqual(metadata['frg702_count'], 1)
        self.assertEqual(metadata['frg702_unit'], "torr")
        self.assertEqual(metadata['sample_rate_ms'], 200)
        self.assertEqual(metadata['notes'], "Test notes")

    def test_default_values(self):
        """Test default values."""
        metadata = create_metadata_dict()

        self.assertEqual(metadata['tc_count'], 0)
        self.assertEqual(metadata['tc_type'], "K")
        self.assertEqual(metadata['tc_unit'], "C")
        self.assertEqual(metadata['frg702_count'], 0)
        self.assertEqual(metadata['frg702_unit'], "mbar")
        self.assertEqual(metadata['sample_rate_ms'], 100)
        self.assertEqual(metadata['notes'], "")


if __name__ == '__main__':
    unittest.main()

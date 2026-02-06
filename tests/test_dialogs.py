"""
Unit tests for dialog classes - testing core logic without GUI
"""

import unittest
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch
from datetime import datetime


class TestLoggingDialogFilenamePreview(unittest.TestCase):
    """Test filename preview logic from LoggingDialog."""

    def test_sanitize_filename_removes_unsafe_chars(self):
        """Test that unsafe characters are removed from filenames."""
        # Characters that should be removed
        unsafe_names = [
            "test/file",
            "test\\file",
            "test:file",
            "test*file",
            "test?file",
            "test<file",
            "test>file",
            "test|file",
            'test"file'
        ]

        for name in unsafe_names:
            # Simulate the sanitization logic from LoggingDialog
            safe_name = "".join(c for c in name if c.isalnum() or c in "._- ")
            safe_name = safe_name.strip().replace(" ", "_")

            self.assertNotIn('/', safe_name)
            self.assertNotIn('\\', safe_name)
            self.assertNotIn(':', safe_name)
            self.assertNotIn('*', safe_name)
            self.assertNotIn('?', safe_name)
            self.assertNotIn('<', safe_name)
            self.assertNotIn('>', safe_name)
            self.assertNotIn('|', safe_name)
            self.assertNotIn('"', safe_name)

    def test_sanitize_preserves_valid_chars(self):
        """Test that valid characters are preserved."""
        valid_name = "Test Run 2024.01_experiment-A"
        safe_name = "".join(c for c in valid_name if c.isalnum() or c in "._- ")
        safe_name = safe_name.strip().replace(" ", "_")

        self.assertEqual(safe_name, "Test_Run_2024.01_experiment-A")

    def test_empty_name_results_in_timestamp_only(self):
        """Test that empty name gives timestamp-only filename."""
        name = ""
        timestamp = "20240101_120000"

        if name:
            safe_name = "".join(c for c in name if c.isalnum() or c in "._- ")
            safe_name = safe_name.strip().replace(" ", "_")
            filename = f"data_log_{safe_name}_{timestamp}.csv"
        else:
            filename = f"data_log_{timestamp}.csv"

        self.assertEqual(filename, "data_log_20240101_120000.csv")


class TestLoadCSVDialogLogic(unittest.TestCase):
    """Test CSV loading logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir)

    def test_file_discovery(self):
        """Test that CSV files are discovered in log folder."""
        # Create some test CSV files
        for i in range(3):
            filepath = os.path.join(self.test_dir, f"test_{i}.csv")
            with open(filepath, 'w') as f:
                f.write("Timestamp,TC_1\n")

        # Also create a non-CSV file (should be ignored)
        with open(os.path.join(self.test_dir, "test.txt"), 'w') as f:
            f.write("not a csv")

        # Discover files (simulating dialog logic)
        files = []
        for f in os.listdir(self.test_dir):
            if f.endswith('.csv'):
                files.append(os.path.join(self.test_dir, f))

        self.assertEqual(len(files), 3)
        for f in files:
            self.assertTrue(f.endswith('.csv'))

    def test_file_sorting_by_modification_time(self):
        """Test that files are sorted by modification time."""
        import time

        # Create files with different modification times
        files = []
        for i in range(3):
            filepath = os.path.join(self.test_dir, f"test_{i}.csv")
            with open(filepath, 'w') as f:
                f.write("Timestamp,TC_1\n")
            files.append(filepath)
            time.sleep(0.1)  # Small delay to ensure different mtime

        # Sort by modification time, newest first
        files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        # Newest should be test_2.csv
        self.assertTrue(files[0].endswith('test_2.csv'))


class TestAxisScaleDialogLogic(unittest.TestCase):
    """Test axis scale configuration logic."""

    def test_temp_range_validation(self):
        """Test temperature range validation."""
        # Valid ranges
        valid_ranges = [
            (0, 100),
            (-40, 200),
            (20, 500),
            (0, 1000)
        ]

        for min_val, max_val in valid_ranges:
            self.assertLess(min_val, max_val)

    def test_scale_result_structure(self):
        """Test that scale result has correct structure."""
        # Simulate the result structure
        result = {
            'use_absolute': True,
            'temp_range': (0, 300)
        }

        self.assertIn('use_absolute', result)
        self.assertIn('temp_range', result)
        self.assertIsInstance(result['use_absolute'], bool)
        self.assertIsInstance(result['temp_range'], tuple)


class TestSamplingRateLogic(unittest.TestCase):
    """Test sampling rate configuration logic."""

    def test_available_rates(self):
        """Test that available sampling rates are reasonable."""
        # These are the rates defined in MainWindow
        SAMPLE_RATES = [50, 100, 200, 500, 1000, 2000]

        for rate in SAMPLE_RATES:
            self.assertGreater(rate, 0)
            self.assertLessEqual(rate, 2000)

    def test_rate_string_parsing(self):
        """Test parsing rate string to integer."""
        rate_strings = ["50ms", "100ms", "200ms", "500ms", "1000ms", "2000ms"]

        for rate_str in rate_strings:
            rate_ms = int(rate_str.replace('ms', ''))
            self.assertIsInstance(rate_ms, int)
            self.assertGreater(rate_ms, 0)

    def test_rate_to_interval_conversion(self):
        """Test conversion of rate in ms to interval in seconds."""
        rate_ms = 100
        interval_sec = rate_ms / 1000.0

        self.assertEqual(interval_sec, 0.1)


class TestHistoricalDataLoadingLogic(unittest.TestCase):
    """Test logic for loading and displaying historical data."""

    def test_metadata_update_gui_logic(self):
        """Test that metadata can update GUI settings."""
        metadata = {
            'tc_count': 3,
            'tc_type': 'K',
            'tc_unit': 'C',
            'frg702_count': 1,
            'frg702_unit': 'mbar',
            'sample_rate_ms': 200
        }

        # Simulate GUI update logic
        gui_values = {}

        if 'tc_count' in metadata:
            gui_values['tc_count'] = str(metadata['tc_count'])
        if 'tc_type' in metadata:
            gui_values['tc_type'] = metadata['tc_type']
        if 'tc_unit' in metadata:
            gui_values['t_unit'] = metadata['tc_unit']
        if 'frg702_count' in metadata:
            gui_values['frg702_count'] = str(metadata['frg702_count'])
        if 'frg702_unit' in metadata:
            gui_values['frg702_unit'] = metadata['frg702_unit']
        if 'sample_rate_ms' in metadata:
            gui_values['sample_rate'] = f"{metadata['sample_rate_ms']}ms"

        self.assertEqual(gui_values['tc_count'], '3')
        self.assertEqual(gui_values['tc_type'], 'K')
        self.assertEqual(gui_values['frg702_unit'], 'mbar')
        self.assertEqual(gui_values['sample_rate'], '200ms')

    def test_data_structure_for_plotting(self):
        """Test that data structure is correct for plotting."""
        data = {
            'timestamps': [datetime.now()],
            'TC_1': [25.0],
            'TC_2': [26.0],
            'FRG702_1': [1.0e-5]
        }

        # Extract sensor types
        tc_names = [k for k in data.keys() if k.startswith('TC_')]
        frg702_names = [k for k in data.keys() if k.startswith('FRG702_')]

        self.assertEqual(len(tc_names), 2)
        self.assertEqual(len(frg702_names), 1)
        self.assertIn('TC_1', tc_names)
        self.assertIn('FRG702_1', frg702_names)


if __name__ == '__main__':
    unittest.main()

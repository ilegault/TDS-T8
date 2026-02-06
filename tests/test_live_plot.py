"""
Unit tests for LivePlot class - dynamic axes and absolute scales
"""

import unittest
from unittest.mock import MagicMock, patch, Mock
import sys
from datetime import datetime, timedelta

# Mock tkinter since it's not available in test environment
sys.modules['tkinter'] = MagicMock()
sys.modules['tk'] = MagicMock()


class TestLivePlotAxesConfiguration(unittest.TestCase):
    """Test dynamic axis configuration based on sensor selection."""

    @patch('t8_daq_system.gui.live_plot.FigureCanvasTkAgg')
    @patch('t8_daq_system.gui.live_plot.Figure')
    def setUp(self, mock_figure, mock_canvas):
        """Set up test fixtures."""
        # Create mock tkinter frame
        self.mock_frame = MagicMock()
        self.mock_data_buffer = MagicMock()

        # Set up mock figure and axes
        self.mock_ax = MagicMock()
        self.mock_ax2 = MagicMock()
        self.mock_fig = MagicMock()
        self.mock_fig.add_subplot.return_value = self.mock_ax
        mock_figure.return_value = self.mock_fig

        # Mock canvas
        self.mock_canvas_widget = MagicMock()
        mock_canvas.return_value = self.mock_canvas_widget
        self.mock_canvas_widget.get_tk_widget.return_value = MagicMock()

        from t8_daq_system.gui.live_plot import LivePlot
        self.plot = LivePlot(self.mock_frame, self.mock_data_buffer)

    def test_default_units(self):
        """Test that default units are set correctly."""
        self.assertEqual(self.plot._temp_unit, "°C")

    def test_set_units(self):
        """Test setting custom units."""
        self.plot.set_units("°F")
        self.assertEqual(self.plot._temp_unit, "°F")

    def test_set_absolute_scales_enabled(self):
        """Test enabling absolute scales."""
        self.plot.set_absolute_scales(True, (0, 500))

        self.assertTrue(self.plot._use_absolute_scales)
        self.assertEqual(self.plot._temp_range, (0, 500))

    def test_set_absolute_scales_with_defaults(self):
        """Test setting absolute scales with default ranges."""
        self.plot.set_absolute_scales(True)

        self.assertTrue(self.plot._use_absolute_scales)
        self.assertEqual(self.plot._temp_range, self.plot.DEFAULT_TEMP_RANGE)

    def test_set_absolute_scales_disabled(self):
        """Test disabling absolute scales."""
        self.plot.set_absolute_scales(False)
        self.assertFalse(self.plot._use_absolute_scales)


class TestLivePlotDynamicAxes(unittest.TestCase):
    """Test dynamic axis visibility based on sensor types."""

    @patch('t8_daq_system.gui.live_plot.FigureCanvasTkAgg')
    @patch('t8_daq_system.gui.live_plot.Figure')
    def setUp(self, mock_figure, mock_canvas):
        """Set up test fixtures."""
        self.mock_frame = MagicMock()
        self.mock_data_buffer = MagicMock()

        # Configure data buffer mock to return empty data
        self.mock_data_buffer.get_sensor_data.return_value = ([], [])

        self.mock_ax = MagicMock()
        self.mock_fig = MagicMock()
        self.mock_fig.add_subplot.return_value = self.mock_ax

        mock_figure.return_value = self.mock_fig

        mock_canvas_instance = MagicMock()
        mock_canvas_instance.get_tk_widget.return_value = MagicMock()
        mock_canvas.return_value = mock_canvas_instance

        from t8_daq_system.gui.live_plot import LivePlot
        self.plot = LivePlot(self.mock_frame, self.mock_data_buffer)

    def test_tc_only_shows_left_axis(self):
        """Test that selecting only TC sensors shows left axis."""
        sensor_names = ['TC_1', 'TC_2']

        self.plot.update(sensor_names)

        # Verify left axis is configured for temperature
        self.mock_ax.set_ylabel.assert_called()
        call_args = self.mock_ax.set_ylabel.call_args[0][0]
        self.assertIn('Temperature', call_args)


class TestLivePlotColorCycles(unittest.TestCase):
    """Test color cycles for different sensor types."""

    @patch('t8_daq_system.gui.live_plot.FigureCanvasTkAgg')
    @patch('t8_daq_system.gui.live_plot.Figure')
    def test_standard_colors_defined(self, mock_figure, mock_canvas):
        """Test that standard color cycle is defined."""
        mock_frame = MagicMock()
        mock_buffer = MagicMock()

        mock_ax = MagicMock()
        mock_fig = MagicMock()
        mock_fig.add_subplot.return_value = mock_ax
        mock_figure.return_value = mock_fig

        mock_canvas_instance = MagicMock()
        mock_canvas_instance.get_tk_widget.return_value = MagicMock()
        mock_canvas.return_value = mock_canvas_instance

        from t8_daq_system.gui.live_plot import LivePlot
        plot = LivePlot(mock_frame, mock_buffer)

        self.assertGreaterEqual(len(plot.colors), 7)
        for color in plot.colors:
            self.assertTrue(color.startswith('#'))

    @patch('t8_daq_system.gui.live_plot.FigureCanvasTkAgg')
    @patch('t8_daq_system.gui.live_plot.Figure')
    def test_ps_colors_defined(self, mock_figure, mock_canvas):
        """Test that power supply colors are defined."""
        mock_frame = MagicMock()
        mock_buffer = MagicMock()

        mock_ax = MagicMock()
        mock_fig = MagicMock()
        mock_fig.add_subplot.return_value = mock_ax
        mock_figure.return_value = mock_fig

        mock_canvas_instance = MagicMock()
        mock_canvas_instance.get_tk_widget.return_value = MagicMock()
        mock_canvas.return_value = mock_canvas_instance

        from t8_daq_system.gui.live_plot import LivePlot
        plot = LivePlot(mock_frame, mock_buffer)

        self.assertIn('PS_Voltage', plot.ps_colors)
        self.assertIn('PS_Current', plot.ps_colors)


class TestLivePlotUpdateFromLoadedData(unittest.TestCase):
    """Test updating plot with loaded historical data."""

    @patch('t8_daq_system.gui.live_plot.FigureCanvasTkAgg')
    @patch('t8_daq_system.gui.live_plot.Figure')
    def test_update_from_loaded_data_with_tc_only(self, mock_figure, mock_canvas):
        """Test loading data with only TC sensors."""
        mock_frame = MagicMock()
        mock_buffer = MagicMock()

        mock_ax = MagicMock()
        mock_fig = MagicMock()
        mock_fig.add_subplot.return_value = mock_ax
        mock_figure.return_value = mock_fig

        mock_canvas_instance = MagicMock()
        mock_canvas_instance.get_tk_widget.return_value = MagicMock()
        mock_canvas.return_value = mock_canvas_instance

        from t8_daq_system.gui.live_plot import LivePlot
        plot = LivePlot(mock_frame, mock_buffer)

        # Create test data
        now = datetime.now()
        loaded_data = {
            'timestamps': [now - timedelta(seconds=i) for i in range(10)],
            'TC_1': [25.0 + i for i in range(10)],
            'TC_2': [30.0 + i for i in range(10)]
        }

        # Should not raise exception
        plot.update_from_loaded_data(loaded_data)

    @patch('t8_daq_system.gui.live_plot.FigureCanvasTkAgg')
    @patch('t8_daq_system.gui.live_plot.Figure')
    def test_update_from_loaded_data_empty(self, mock_figure, mock_canvas):
        """Test loading empty data."""
        mock_frame = MagicMock()
        mock_buffer = MagicMock()

        mock_ax = MagicMock()
        mock_fig = MagicMock()
        mock_fig.add_subplot.return_value = mock_ax
        mock_figure.return_value = mock_fig

        mock_canvas_instance = MagicMock()
        mock_canvas_instance.get_tk_widget.return_value = MagicMock()
        mock_canvas.return_value = mock_canvas_instance

        from t8_daq_system.gui.live_plot import LivePlot
        plot = LivePlot(mock_frame, mock_buffer)

        # Empty data should not crash
        plot.update_from_loaded_data({'timestamps': []})


if __name__ == '__main__':
    unittest.main()

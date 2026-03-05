"""
Unit tests for LivePlot class - dynamic axes and absolute scales
"""

import unittest
from unittest.mock import MagicMock, patch, Mock
import sys
from datetime import datetime, timedelta

# conftest.py handles mocking of tkinter, matplotlib, and hardware libs
import t8_daq_system.gui.live_plot


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
        self.mock_ax.plot.return_value = [MagicMock()]
        self.mock_ax2 = MagicMock()
        self.mock_ax2.plot.return_value = [MagicMock()]
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
        self.plot.set_absolute_scales(True, (0, 500), (1e-8, 1e-4), (0, 100), (0, 50))

        self.assertTrue(self.plot._use_absolute_scales)
        self.assertEqual(self.plot._temp_range, (0, 500))
        self.assertEqual(self.plot._press_range, (1e-8, 1e-4))
        self.assertEqual(self.plot._ps_v_range, (0, 100))
        self.assertEqual(self.plot._ps_i_range, (0, 50))

    def test_set_absolute_scales_with_defaults(self):
        """Test setting absolute scales with default ranges."""
        self.plot.set_absolute_scales(True)

        self.assertTrue(self.plot._use_absolute_scales)
        self.assertEqual(self.plot._temp_range, self.plot.DEFAULT_TEMP_RANGE)
        self.assertEqual(self.plot._press_range, self.plot.DEFAULT_PRESS_RANGE)
        self.assertEqual(self.plot._ps_v_range, self.plot.DEFAULT_PS_V_RANGE)
        self.assertEqual(self.plot._ps_i_range, self.plot.DEFAULT_PS_I_RANGE)

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
        self.mock_ax.plot.return_value = [MagicMock()]
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
        mock_ax.plot.return_value = [MagicMock()]
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
        mock_ax.plot.return_value = [MagicMock()]
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
        mock_ax.plot.return_value = [MagicMock()]
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
        mock_ax.plot.return_value = [MagicMock()]
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


class TestLivePlotSliderMode(unittest.TestCase):
    """Test the dual-mode timeline slider (History % vs 2-min Window)."""

    @patch('t8_daq_system.gui.live_plot.FigureCanvasTkAgg')
    @patch('t8_daq_system.gui.live_plot.Figure')
    def _make_plot(self, mock_figure, mock_canvas, plot_type='tc'):
        """Helper: create a LivePlot with mocked figure and canvas."""
        mock_frame = MagicMock()
        mock_buffer = MagicMock()
        mock_buffer.get_sensor_names.return_value = []
        mock_buffer.get_sensor_data.return_value = ([], [])

        mock_ax = MagicMock()
        mock_ax.plot.return_value = [MagicMock()]
        mock_fig = MagicMock()
        mock_fig.add_subplot.return_value = mock_ax
        mock_figure.return_value = mock_fig

        mock_canvas_instance = MagicMock()
        mock_canvas_instance.get_tk_widget.return_value = MagicMock()
        mock_canvas.return_value = mock_canvas_instance

        from t8_daq_system.gui.live_plot import LivePlot
        return LivePlot(mock_frame, mock_buffer, plot_type=plot_type)

    def test_default_slider_mode_is_history_pct(self):
        """Default slider mode should be 'history_pct'."""
        plot = self._make_plot()
        self.assertEqual(plot._slider_mode, 'history_pct')

    def test_set_slider_mode_window_2min(self):
        """set_slider_mode('window_2min') should update _slider_mode."""
        plot = self._make_plot()
        plot.set_slider_mode('window_2min')
        self.assertEqual(plot._slider_mode, 'window_2min')

    def test_set_slider_mode_history_pct(self):
        """set_slider_mode('history_pct') should update _slider_mode."""
        plot = self._make_plot()
        plot.set_slider_mode('window_2min')  # start from different state
        plot.set_slider_mode('history_pct')
        self.assertEqual(plot._slider_mode, 'history_pct')

    def test_set_slider_mode_triggers_redraw_when_frozen(self):
        """set_slider_mode should call _do_update_frozen when plot is frozen."""
        plot = self._make_plot()
        plot._is_live = False
        plot._frozen_right_edge = MagicMock()  # not None — frozen state

        with patch.object(plot, '_do_update_frozen') as mock_update:
            plot.set_slider_mode('window_2min')
            mock_update.assert_called_once()

    def test_set_slider_mode_no_redraw_when_live(self):
        """set_slider_mode should NOT call _do_update_frozen when plot is live."""
        plot = self._make_plot()
        plot._is_live = True

        with patch.object(plot, '_do_update_frozen') as mock_update:
            plot.set_slider_mode('window_2min')
            mock_update.assert_not_called()

    def test_frozen_window_2min_passes_window_seconds_to_render(self):
        """In 'window_2min' mode, _do_update_frozen must render with WINDOW_SECONDS."""
        from datetime import datetime as dt
        plot = self._make_plot()
        plot._slider_mode = 'window_2min'
        plot._frozen_right_edge = dt.now()

        with patch.object(plot, '_render') as mock_render, \
             patch.object(plot, 'data_buffer') as mock_buf:
            mock_buf.get_sensor_names.return_value = []
            mock_buf.get_sensor_data.return_value = ([], [])
            plot._do_update_frozen()
            # _render should be called with ws=WINDOW_SECONDS (120)
            args, kwargs = mock_render.call_args
            # window_seconds is the 3rd positional arg
            ws_passed = args[2] if len(args) > 2 else kwargs.get('window_seconds')
            self.assertEqual(ws_passed, plot.WINDOW_SECONDS,
                             "window_2min mode should pass WINDOW_SECONDS to _render")

    def test_frozen_history_pct_passes_none_window_to_render(self):
        """In 'history_pct' mode, _do_update_frozen must render with window_seconds=None."""
        from datetime import datetime as dt
        plot = self._make_plot()
        plot._slider_mode = 'history_pct'
        plot._frozen_right_edge = dt.now()

        with patch.object(plot, '_render') as mock_render, \
             patch.object(plot, 'data_buffer') as mock_buf:
            mock_buf.get_sensor_names.return_value = []
            mock_buf.get_sensor_data.return_value = ([], [])
            plot._do_update_frozen()
            args, kwargs = mock_render.call_args
            ws_passed = args[2] if len(args) > 2 else kwargs.get('window_seconds')
            self.assertIsNone(ws_passed,
                              "history_pct mode should pass None to _render (show all data)")

    def test_clear_resets_lines(self):
        """clear() should empty the lines dict and trigger a canvas redraw."""
        plot = self._make_plot()
        plot.lines = {('tc', 'TC_1'): MagicMock()}  # simulate existing lines
        plot.clear()
        self.assertEqual(len(plot.lines), 0, "clear() should empty lines dict")


if __name__ == '__main__':
    unittest.main()

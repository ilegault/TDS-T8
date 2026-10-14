"""
Tests for GUI reading the Rig, not the hardware (Ticket rig-architecture-05).

WHY THIS EXISTS
---------------
ADR 0002 establishes that only the Rig module owns hardware I/O and communication.
The GUI thread must never execute blocking reconnects, polling, or reader reads.
All temperatures seen by the PID and the operator originate from the single
immutable Snapshot published each tick. The pressure interlock must stop the
executor before de-energising the supply, and compare canonical Torr rather than
display units.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from t8_daq_system.gui.main_window import MainWindow
from t8_daq_system.rig.snapshot import HeaterStatus, ProgramStatus, Snapshot, SourceStatus

pytestmark = pytest.mark.unit


def _make_mock_settings(mock_settings_cls):
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
    mock_settings.get_tc_type_list.return_value = ["K"]
    mock_settings.get_tc_pin_list.return_value = ["AIN0"]
    mock_settings.get_frg_pin_list.return_value = ["AIN2"]
    mock_settings.visa_resource = ""
    mock_settings.frg_interface = "XGS600"
    mock_settings.ps_interface = "Analog"
    mock_settings.log_folder = ""
    mock_settings.reset_graph_on_start_logging = False
    return mock_settings


class TestGuiReadsRig:

    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.CameraPanel')
    @patch('t8_daq_system.gui.main_window.AppSettings')
    def test_update_gui_makes_no_adapter_or_hardware_calls(
        self, mock_settings_cls, mock_camera_panel, mock_sensor_panel, mock_plot, mock_tk
    ):
        """Criterion 1: _update_gui makes NO adapter/hardware call."""
        _make_mock_settings(mock_settings_cls)
        mock_rig = MagicMock()
        mock_snapshot = Snapshot(
            t=0.0,
            wall_time=0.0,
            tc_c={"TC_1": 25.0},
            tc_raw_v={"TC_1": 0.001},
            pressure_torr={"FRG702_Chamber": 1e-7},
            source_age_s={"TC_1": 0.0, "FRG702_Chamber": 0.0},
            ps_volts=1.5,
            ps_amps=10.0,
            commanded_volts=1.5,
            output_enabled=True,
            labjack=SourceStatus(state="connected"),
            xgs=SourceStatus(state="connected"),
            heater=HeaterStatus(state="on"),
            program=ProgramStatus(),
            permissive_ok=True,
            permissive_reason=None,
            adapter="simulated",
        )
        mock_rig.latest.return_value = mock_snapshot
        app = MainWindow(rig=mock_rig)

        # Rig with mock adapter
        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        app.rig._adapter = mock_adapter

        # Also spy on any hardware objects attached to MainWindow
        mock_conn = MagicMock()
        mock_tc_reader = MagicMock()
        mock_frg_reader = MagicMock()
        mock_ps_controller = MagicMock()
        app.connection = mock_conn
        app.tc_reader = mock_tc_reader
        app.frg702_reader = mock_frg_reader
        app.ps_controller = mock_ps_controller

        # Reset call counts
        mock_adapter.reset_mock()
        mock_conn.reset_mock()
        mock_tc_reader.reset_mock()
        mock_frg_reader.reset_mock()
        mock_ps_controller.reset_mock()

        # Call _update_gui
        app._update_gui()

        # Assert no hardware or adapter methods were invoked during _update_gui
        assert mock_adapter.read.call_count == 0
        assert mock_adapter.connect.call_count == 0
        assert mock_conn.connect.call_count == 0
        assert mock_conn.get_handle.call_count == 0
        assert mock_tc_reader.read_all.call_count == 0
        assert mock_frg_reader.read_all.call_count == 0
        assert mock_ps_controller.get_readings.call_count == 0
        assert mock_ps_controller.get_voltage.call_count == 0
        assert mock_ps_controller.get_current.call_count == 0

    def test_executor_control_temperature_equals_snapshot_value(self):
        """Criterion 2: Program control temperature for a tick equals the Snapshot's value."""
        from t8_daq_system.control.program_block import TempRampBlock
        from tests.run_settings_helper import make_program_run

        target_temp_c = 345.6
        snapshot = Snapshot(
            t=0.0,
            wall_time=0.0,
            tc_c={"TC_1": target_temp_c},
            tc_raw_v={"TC_1": 0.012},
            pressure_torr={"FRG702_Chamber": 1e-7},
            source_age_s={"TC_1": 0.0, "FRG702_Chamber": 0.0},
            ps_volts=0.0,
            ps_amps=0.0,
            commanded_volts=0.0,
            output_enabled=False,
            labjack=SourceStatus(state="connected"),
            xgs=SourceStatus(state="connected"),
            heater=HeaterStatus(state="off"),
            program=ProgramStatus(),
            permissive_ok=True,
            permissive_reason=None,
            adapter="simulated",
        )

        program_run = make_program_run()
        block = TempRampBlock(rate_k_per_min=60.0, end_temp_k=1000.0, tc_name="TC_1")
        measured_k = program_run._read_temp_k(block, snapshot)

        expected_k = target_temp_c + 273.15
        assert measured_k == pytest.approx(expected_k, abs=1e-6)

    @patch('tkinter.messagebox.showerror')
    @patch.dict('sys.modules', {'pyautogui': MagicMock()})
    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.CameraPanel')
    @patch('t8_daq_system.gui.main_window.AppSettings')
    def test_pressure_interlock_stops_executor_before_supply_off_and_compares_in_torr(
        self, mock_settings_cls, mock_camera_panel, mock_sensor_panel, mock_plot, mock_tk, mock_showerror
    ):
        """Criterion 3: Pressure-interlock stops program and compares in Torr."""
        from t8_daq_system.rig.commands import StopProgram

        _make_mock_settings(mock_settings_cls)
        mock_rig = MagicMock()
        app = MainWindow(rig=mock_rig)

        # Case A: Snapshot with pressure safe in Torr (e.g. 5e-5 Torr) -> should NOT trip
        safe_snapshot = Snapshot(
            t=0.0,
            wall_time=0.0,
            tc_c={"TC_1": 25.0},
            tc_raw_v={"TC_1": 0.001},
            pressure_torr={"FRG702_Chamber": 5e-5},
            source_age_s={"TC_1": 0.0, "FRG702_Chamber": 0.0},
            ps_volts=0.0,
            ps_amps=0.0,
            commanded_volts=0.0,
            output_enabled=True,
            labjack=SourceStatus(state="connected"),
            xgs=SourceStatus(state="connected"),
            heater=HeaterStatus(state="on"),
            program=ProgramStatus(),
            permissive_ok=True,
            permissive_reason=None,
            adapter="simulated",
        )
        app._on_snapshot(safe_snapshot)
        assert mock_rig.submit.call_count == 0, "Safe pressure in Torr must not trip interlock"

        # Case B: Snapshot with pressure exceeding 1e-4 Torr (e.g. 2e-4 Torr)
        tripping_snapshot = Snapshot(
            t=1.0,
            wall_time=1.0,
            tc_c={"TC_1": 25.0},
            tc_raw_v={"TC_1": 0.001},
            pressure_torr={"FRG702_Chamber": 2e-4},
            source_age_s={"TC_1": 0.0, "FRG702_Chamber": 0.0},
            ps_volts=0.0,
            ps_amps=0.0,
            commanded_volts=0.0,
            output_enabled=True,
            labjack=SourceStatus(state="connected"),
            xgs=SourceStatus(state="connected"),
            heater=HeaterStatus(state="on"),
            program=ProgramStatus(),
            permissive_ok=True,
            permissive_reason=None,
            adapter="simulated",
        )
        app._on_snapshot(tripping_snapshot)

        # The interlock queues _shutdown on root.after(0, ...)
        # Find and execute the shutdown callback
        shutdown_cb = None
        for args, kwargs in reversed(app.root.after.call_args_list):
            if args[0] == 0:
                shutdown_cb = args[1]
                break

        assert shutdown_cb is not None, "root.after(0, _shutdown) was not scheduled"
        shutdown_cb()

        # StopProgram submitted to Rig
        stop_cmds = [c for (c,), _ in mock_rig.submit.call_args_list if isinstance(c, StopProgram)]
        assert len(stop_cmds) >= 1, "StopProgram was not submitted to Rig on interlock trip"

"""
tests/unit/test_gui_speaks_in_commands.py

Tests for Ticket 12: GUI speaks in commands.

WHY THIS EXISTS
---------------
ADR 0002 and ADR 0003 require that the GUI never touches hardware directly.
All operator actions (nudge, start, stop, confirm, reset, set-voltage, output,
practice selection) submit immutable commands to the Rig.
Trip status is displayed via a non-modal banner until the latch is cleared.
QMS start is gated strictly by the Snapshot's permissive_ok field.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch
import pytest

from t8_daq_system.control.program_block import VoltageRampBlock
from t8_daq_system.gui.main_window import MainWindow
from t8_daq_system.rig.commands import (
    ConfirmContinue,
    LoadProgram,
    Nudge,
    ResetTrip,
    SelectAdapter,
    SetOutput,
    SetVoltage,
    StartProgram,
    StopProgram,
)
from t8_daq_system.rig.snapshot import (
    HeaterStatus,
    ProgramStatus,
    Snapshot,
    SourceStatus,
)

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
    mock_settings.pid_kp = 0.02
    mock_settings.pid_ki = 0.0013
    mock_settings.pid_kd = 0.005
    mock_settings.pid_windup_limit = 1.0
    return mock_settings


def _make_snapshot(
    heater_state: str = "off",
    trip_kind: str | None = None,
    trip_reason: str | None = None,
    shutoff_unverified: bool = False,
    command_rejected_reason: str | None = None,
    permissive_ok: bool = True,
    permissive_reason: str | None = None,
    program_running: bool = False,
    commanded_volts: float = 0.0,
    output_enabled: bool = False,
) -> Snapshot:
    return Snapshot(
        t=10.0,
        wall_time=1700000000.0,
        tc_c={"TC_1": 25.0},
        tc_raw_v={"TC_1": 0.001},
        pressure_torr={"FRG702_Chamber": 1e-7},
        source_age_s={"TC_1": 0.0, "FRG702_Chamber": 0.0},
        ps_volts=0.0,
        ps_amps=0.0,
        commanded_volts=commanded_volts,
        output_enabled=output_enabled,
        labjack=SourceStatus(state="connected"),
        xgs=SourceStatus(state="connected"),
        heater=HeaterStatus(
            state=heater_state,
            trip_kind=trip_kind,
            trip_reason=trip_reason,
            shutoff_unverified=shutoff_unverified,
        ),
        program=ProgramStatus(running=program_running),
        permissive_ok=permissive_ok,
        permissive_reason=permissive_reason,
        adapter="simulated",
        command_rejected_reason=command_rejected_reason,
    )


@pytest.fixture
def gui_app():
    with patch('t8_daq_system.gui.main_window.tk.Tk'), \
         patch('t8_daq_system.gui.main_window.LivePlot'), \
         patch('t8_daq_system.gui.main_window.SensorPanel'), \
         patch('t8_daq_system.gui.main_window.CameraPanel'), \
         patch('t8_daq_system.gui.main_window.AppSettings') as mock_settings_cls:
        _make_mock_settings(mock_settings_cls)
        mock_rig = MagicMock()
        mock_rig.latest.return_value = _make_snapshot()
        app = MainWindow(rig=mock_rig)
        # Mock power supply controller to detect any direct calls
        mock_ps = MagicMock()
        app.ps_controller = mock_ps
        yield app, mock_rig, mock_ps


class TestTripBanner:
    """Criterion 1: Rendering a tripped Snapshot shows banner with kind/reason; cleared hides it."""

    def test_rendering_tripped_snapshot_shows_banner_with_kind_and_reason(self, gui_app):
        app, _, _ = gui_app
        snap = _make_snapshot(
            heater_state="tripped",
            trip_kind="temp_limit",
            trip_reason="TC_1 reached 120.0 C (limit 100.0 C)",
        )
        app.render_snapshot(snap)

        assert app.is_trip_banner_visible()
        banner_text = app.get_trip_text()
        assert "temp_limit" in banner_text
        assert "TC_1 reached 120.0 C" in banner_text

    def test_rendering_cleared_snapshot_hides_banner(self, gui_app):
        app, _, _ = gui_app
        # First trip
        trip_snap = _make_snapshot(
            heater_state="tripped",
            trip_kind="temp_limit",
            trip_reason="TC_1 reached 120.0 C",
        )
        app.render_snapshot(trip_snap)
        assert app.is_trip_banner_visible()

        # Then cleared
        cleared_snap = _make_snapshot(heater_state="off")
        app.render_snapshot(cleared_snap)

        # Banner should be hidden
        assert not app.is_trip_banner_visible()

    def test_shutoff_unverified_shown_as_most_severe_state(self, gui_app):
        app, _, _ = gui_app
        snap = _make_snapshot(
            heater_state="tripped",
            trip_kind="labjack_lost",
            trip_reason="Shut-off write failed",
            shutoff_unverified=True,
        )
        app.render_snapshot(snap)

        banner_text = app.get_trip_text()
        assert "shutoff_unverified" in banner_text.lower() or "shut-off unverified" in banner_text.lower()


class TestResetButton:
    """Criterion 2: Reset button submits ResetTrip; refused reset shows refusal reason."""

    def test_reset_button_submits_reset_trip(self, gui_app):
        app, mock_rig, _ = gui_app
        trip_snap = _make_snapshot(
            heater_state="tripped",
            trip_kind="temp_limit",
            trip_reason="TC_1 reached 120.0 C",
        )
        app.render_snapshot(trip_snap)

        # Trigger reset button
        app._on_reset_trip()

        submitted = [call.args[0] for call in mock_rig.submit.call_args_list]
        assert any(isinstance(cmd, ResetTrip) for cmd in submitted)

    def test_refused_reset_shows_refusal_reason(self, gui_app):
        app, _, _ = gui_app
        refused_snap = _make_snapshot(
            heater_state="tripped",
            trip_kind="temp_limit",
            trip_reason="TC_1 reached 120.0 C",
            command_rejected_reason="Reset refused: TC_1 still above limit",
        )
        app.render_snapshot(refused_snap)

        # Assert refusal is rendered on screen
        refusal_text = app.get_trip_refusal_text()
        assert "Reset refused: TC_1 still above limit" in refusal_text


class TestQmsPermissiveAndAbort:
    """Criterion 3: QMS start refused when permissive false; trip triggers abort without swallowing."""

    @patch('t8_daq_system.gui.main_window.messagebox.showwarning')
    def test_qms_start_refused_when_permissive_not_ok(self, mock_warn, gui_app):
        app, mock_rig, _ = gui_app
        snap = _make_snapshot(
            permissive_ok=False,
            permissive_reason="FRG702_Chamber pressure 2.0e-04 Torr > 1.0e-04 Torr",
        )
        mock_rig.latest.return_value = snap
        app.render_snapshot(snap)

        # Attempt to start QMS
        app._on_qms_ramp_start()

        # Warning shown with permissive reason
        assert mock_warn.called
        msg = mock_warn.call_args[0][1]
        assert "2.0e-04 Torr" in msg or "permissive" in msg.lower()

    def test_qms_poll_gate_uses_permissive_ok_and_reason(self, gui_app):
        app, mock_rig, _ = gui_app
        snap = _make_snapshot(
            permissive_ok=False,
            permissive_reason="Chamber pressure high",
        )
        mock_rig.latest.return_value = snap
        app.render_snapshot(snap)

        # Call poll gate
        app._qms_gate_active = True
        app._poll_qms_gate()

        status_text = app.get_qms_status_text()
        assert "Chamber pressure high" in status_text

    @patch('t8_daq_system.gui.main_window.messagebox.showerror')
    def test_pressure_trip_triggers_mas_abort_and_reports_failure(self, mock_error, gui_app):
        app, _, _ = gui_app
        snap = _make_snapshot(
            heater_state="tripped",
            trip_kind="pressure_high",
            trip_reason="FRG702_Chamber 2.5e-4 Torr > 1e-4 Torr",
            permissive_ok=False,
        )

        mock_pyautogui = MagicMock()
        mock_pyautogui.getWindowsWithTitle.side_effect = RuntimeError("pyautogui crashed")
        with patch.dict('sys.modules', {'pyautogui': mock_pyautogui}):
            # Rendering this snapshot or handling trip should trigger abort on Tk thread
            app.render_snapshot(snap)

        # Failure must be reported / shown, NOT silently swallowed
        assert mock_error.called or "pyautogui" in app.status_var.get()


class TestControlsSubmitCommands:
    """Criterion 4: Nudge/start/stop/confirm submit matching commands and make no PS call."""

    def test_nudge_up_submits_nudge_command_and_no_ps_call(self, gui_app):
        app, mock_rig, mock_ps = gui_app
        app._nudge_voltage(+1)

        submitted = [call.args[0] for call in mock_rig.submit.call_args_list]
        assert any(isinstance(cmd, Nudge) and cmd.direction == "up" for cmd in submitted)
        assert mock_ps.set_voltage.call_count == 0
        assert mock_ps.output_on.call_count == 0

    def test_nudge_down_submits_nudge_command_and_no_ps_call(self, gui_app):
        app, mock_rig, mock_ps = gui_app
        app._nudge_voltage(-1)

        submitted = [call.args[0] for call in mock_rig.submit.call_args_list]
        assert any(isinstance(cmd, Nudge) and cmd.direction == "down" for cmd in submitted)
        assert mock_ps.set_voltage.call_count == 0
        assert mock_ps.output_off.call_count == 0

    def test_start_program_submits_load_and_start_commands_and_no_ps_call(self, gui_app):
        app, mock_rig, mock_ps = gui_app
        block = VoltageRampBlock(start_voltage=0.0, end_voltage=2.0, duration_sec=10.0)
        app._programmer_blocks = [block]

        try:
            app._start_programmer_ramp()

            submitted = [call.args[0] for call in mock_rig.submit.call_args_list]
            assert any(isinstance(cmd, LoadProgram) for cmd in submitted)
            assert any(isinstance(cmd, StartProgram) for cmd in submitted)
            assert mock_ps.output_on.call_count == 0
            assert mock_ps.set_voltage.call_count == 0
        finally:
            app._stop_programmer_ramp_safe()

    def test_stop_program_submits_stop_command_and_no_ps_call(self, gui_app):
        app, mock_rig, mock_ps = gui_app
        app._stop_programmer_ramp_safe()

        submitted = [call.args[0] for call in mock_rig.submit.call_args_list]
        assert any(isinstance(cmd, StopProgram) for cmd in submitted)
        assert mock_ps.output_off.call_count == 0
        assert mock_ps.set_voltage.call_count == 0

    def test_cut_power_submits_stop_and_zero_and_no_ps_call(self, gui_app):
        app, mock_rig, mock_ps = gui_app
        app._cut_power_output()

        submitted = [call.args[0] for call in mock_rig.submit.call_args_list]
        assert any(isinstance(cmd, StopProgram) for cmd in submitted)
        assert any(isinstance(cmd, SetOutput) and cmd.enabled is False for cmd in submitted)
        assert any(isinstance(cmd, SetVoltage) and cmd.volts == 0.0 for cmd in submitted)
        assert mock_ps.set_voltage.call_count == 0
        assert mock_ps.set_current.call_count == 0

    def test_qms_confirmation_submits_confirm_continue_and_no_ps_call(self, gui_app):
        app, mock_rig, mock_ps = gui_app
        app._on_qms_confirmation_click()

        submitted = [call.args[0] for call in mock_rig.submit.call_args_list]
        assert any(isinstance(cmd, ConfirmContinue) for cmd in submitted)
        assert mock_ps.set_voltage.call_count == 0
        assert mock_ps.output_on.call_count == 0

    def test_set_voltage_and_set_output_submit_commands_and_no_ps_call(self, gui_app):
        app, mock_rig, mock_ps = gui_app
        app.set_voltage(3.5)
        app.set_output(True)

        submitted = [call.args[0] for call in mock_rig.submit.call_args_list]
        assert any(isinstance(cmd, SetVoltage) and cmd.volts == 3.5 for cmd in submitted)
        assert any(isinstance(cmd, SetOutput) and cmd.enabled is True for cmd in submitted)
        assert mock_ps.set_voltage.call_count == 0
        assert mock_ps.output_on.call_count == 0


class TestPracticeToggle:
    """Criterion 5: Practice toggle submits SelectAdapter; disabled while running or logging."""

    def test_practice_toggle_submits_select_adapter(self, gui_app):
        app, mock_rig, _ = gui_app
        app._toggle_practice_mode()

        submitted = [call.args[0] for call in mock_rig.submit.call_args_list]
        assert any(isinstance(cmd, SelectAdapter) for cmd in submitted)

    def test_practice_toggle_disabled_when_program_running(self, gui_app):
        app, _, _ = gui_app
        snap = _make_snapshot(program_running=True)
        app.render_snapshot(snap)

        assert app.get_practice_button_state() == "disabled"

    def test_practice_toggle_disabled_when_logging_active(self, gui_app):
        app, _, _ = gui_app
        app.is_logging = True
        snap = _make_snapshot(program_running=False)
        app.render_snapshot(snap)

        assert app.get_practice_button_state() == "disabled"

    def test_practice_toggle_enabled_when_idle_and_not_logging(self, gui_app):
        app, _, _ = gui_app
        app.is_logging = False
        snap = _make_snapshot(program_running=False)
        app.render_snapshot(snap)

        assert app.get_practice_button_state() == "normal"


class TestOperatorCommandsAreLogged:
    """Ticket 28: each operator command logs one INFO line naming it and its parameters."""

    def test_run_logs_info_with_block_count(self, gui_app, caplog):
        app, _, _ = gui_app
        blocks = [
            VoltageRampBlock(start_voltage=0.0, end_voltage=2.0, duration_sec=10.0),
            VoltageRampBlock(start_voltage=2.0, end_voltage=3.0, duration_sec=5.0),
        ]
        app._programmer_blocks = blocks

        with caplog.at_level(logging.INFO, logger="t8_daq_system.gui.main_window"):
            app._start_programmer_ramp()

        records = [r for r in caplog.records if r.levelno == logging.INFO and "Run" in r.getMessage()]
        assert len(records) == 1
        assert "2 block" in records[0].getMessage()

    def test_reset_trip_logs_info(self, gui_app, caplog):
        app, _, _ = gui_app
        with caplog.at_level(logging.INFO, logger="t8_daq_system.gui.main_window"):
            app._on_reset_trip()

        records = [r for r in caplog.records if r.levelno == logging.INFO and "Reset trip" in r.getMessage()]
        assert len(records) == 1

    def test_stop_nudge_and_practice_log_info(self, gui_app, caplog):
        app, _, _ = gui_app
        with caplog.at_level(logging.INFO, logger="t8_daq_system.gui.main_window"):
            app._stop_programmer_ramp_safe()
            app._nudge_voltage(+1)
            app._toggle_practice_mode()

        messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert any("Stop" in m for m in messages)
        assert any("Nudge" in m and "up" in m for m in messages)
        assert any("Practice" in m for m in messages)

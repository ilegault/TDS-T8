"""
Tests for Soft start and the current caps being visible to the operator
(Ticket cold-start-and-traceability-25).

WHY THIS EXISTS
---------------
ADR 0006 puts a Soft start in front of every run and caps current in two places.
An operator who cannot see that, or cannot tell which caps and gains the run
uses, cannot trust it.  These tests pin what is shown: the locked Soft-start row
in the Power Programmer, the Soft-start span in the pure preview, the status
line while Soft start runs, and the gains / cap labels.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from t8_daq_system.control.program_block import VoltageRampBlock
from t8_daq_system.control.program_run import compute_preview
from t8_daq_system.gui.main_window import MainWindow
from t8_daq_system.gui.power_programmer_panel import PowerProgrammerPanel
from t8_daq_system.rig.commands import RunSettings
from t8_daq_system.rig.snapshot import HeaterStatus, ProgramStatus, Snapshot, SourceStatus

from tests.unit.test_gui_reads_rig import _make_mock_settings

pytestmark = pytest.mark.unit


def _run_settings(**over) -> RunSettings:
    values = dict(
        kp=1.0, ki=0.05, kd=0.05, windup_limit=10.0,
        soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02,
        soft_start_handoff_current_a=35.0,
        soft_start_cap_enabled=True, soft_start_cap_a=40.0,
        run_cap_enabled=True, run_cap_a=120.0,
    )
    values.update(over)
    return RunSettings(**values)


def _app_settings(**over):
    values = dict(
        soft_start_threshold_c=200.0, soft_start_handoff_current_a=35.0,
        soft_start_cap_enabled=True, soft_start_cap_a=40.0,
        run_cap_enabled=True, run_cap_a=120.0,
        pid_kp=1.0, pid_ki=0.05, pid_kd=0.05,
        pp_default_ramp_duration=60, pp_default_start_v=0.0, pp_default_current_a=10.0,
    )
    values.update(over)
    return SimpleNamespace(**values)


def _panel(settings=None, blocks=None) -> PowerProgrammerPanel:
    panel = PowerProgrammerPanel(MagicMock(), settings or _app_settings(), MagicMock(), MagicMock())
    panel._tree = MagicMock()
    panel._blocks = blocks if blocks is not None else [
        {"type": "Ramp", "duration": 10, "start_v": 0.0, "end_v": 1.0, "current_a": 5.0},
        {"type": "Hold", "duration": 10, "start_v": 1.0, "end_v": 1.0, "current_a": 5.0},
    ]
    return panel


def _snapshot(program: ProgramStatus) -> Snapshot:
    return Snapshot(
        t=0.0, wall_time=0.0,
        tc_c={"TC_1": 25.0}, tc_raw_v={"TC_1": 0.001},
        pressure_torr={"FRG702_Chamber": 1e-7},
        source_age_s={"TC_1": 0.0, "FRG702_Chamber": 0.0},
        ps_volts=0.29, ps_amps=45.0, commanded_volts=0.29, output_enabled=True,
        labjack=SourceStatus(state="connected"), xgs=SourceStatus(state="connected"),
        heater=HeaterStatus(state="on"), program=program,
        permissive_ok=True, permissive_reason=None, adapter="simulated",
    )


class TestComputePreviewSoftStart:

    def test_soft_start_end_time_positive_and_voltage_rises_no_faster_than_ramp(self):
        blocks = [VoltageRampBlock(start_voltage=0.0, end_voltage=2.0, duration_sec=30.0)]
        settings = _run_settings()

        times, voltages, _temps, boundaries, soft_end_s = compute_preview(
            blocks, start_temp_k=293.15, start_voltage=0.0, soft_start=settings
        )

        assert soft_end_s > 0
        assert boundaries[0] == pytest.approx(soft_end_s)
        before = [(t, v) for t, v in zip(times, voltages) if t <= soft_end_s]
        assert len(before) > 2
        for (t0, v0), (t1, v1) in zip(before, before[1:]):
            assert (v1 - v0) <= settings.soft_start_ramp_v_per_s * (t1 - t0) + 1e-9
        # Blocks start after the Soft-start span, not on top of it.
        assert times[-1] == pytest.approx(soft_end_s + 30.0)

    def test_no_soft_start_segment_without_settings_or_when_already_hot(self):
        blocks = [VoltageRampBlock(start_voltage=0.0, end_voltage=2.0, duration_sec=30.0)]

        assert compute_preview(blocks)[4] == 0.0
        hot_k = 250.0 + 273.15
        assert compute_preview(blocks, start_temp_k=hot_k, soft_start=_run_settings())[4] == 0.0


class TestLockedSoftStartRow:

    def test_first_row_is_soft_start_row_with_threshold_and_handoff(self):
        panel = _panel()

        panel._refresh_table()

        first_values = panel._tree.insert.call_args_list[0].kwargs["values"]
        texts = [str(v) for v in first_values]
        soft = [t for t in texts if t.startswith("Soft start")]
        assert soft, texts
        assert "200" in soft[0] and "35" in soft[0]
        # Soft row plus the two blocks.
        assert panel._tree.insert.call_count == 3

    @pytest.mark.parametrize("handler", ["_delete_block", "_move_up", "_move_down"])
    def test_handlers_leave_blocks_unchanged_when_soft_start_row_selected(self, handler):
        panel = _panel()
        panel._refresh_table()
        soft_iid = panel._tree.insert.call_args_list[0].kwargs["iid"]
        panel._tree.selection.return_value = (soft_iid,)
        panel._tree.index.return_value = 0
        before = [dict(b) for b in panel._blocks]

        getattr(panel, handler)()

        assert panel._blocks == before

    def test_delete_removes_the_selected_block_not_the_one_above_it(self):
        panel = _panel()
        panel._refresh_table()
        panel._tree.selection.return_value = ("I002",)
        panel._tree.index.return_value = 1  # first block sits under the Soft-start row

        panel._delete_block()

        assert [b["type"] for b in panel._blocks] == ["Hold"]


class TestCapAndGainsLabels:

    def test_run_cap_off_label_when_disabled(self):
        panel = _panel(_app_settings(run_cap_enabled=False))

        panel.refresh_run_labels(None)

        text = panel.get_caps_text()
        assert "Run cap: OFF" in text
        assert "Soft-start cap: 40" in text

    def test_idle_labels_come_from_app_settings(self):
        panel = _panel(_app_settings(pid_kp=2.0, pid_ki=0.1, pid_kd=0.2, soft_start_cap_enabled=False))

        panel.refresh_run_labels(None)

        assert panel.get_gains_text() == "Gains in use: 2 / 0.1 / 0.2"
        assert "Soft-start cap: OFF" in panel.get_caps_text()
        assert "Run cap: 120 A" in panel.get_caps_text()

    def test_running_gains_come_from_snapshot(self):
        panel = _panel()
        program = ProgramStatus(running=True, gains_in_use=(3.0, 0.5, 0.25))

        panel.refresh_run_labels(_snapshot(program))

        assert panel.get_gains_text() == "Gains in use: 3 / 0.5 / 0.25"


class TestStatusLine:

    @patch('t8_daq_system.gui.main_window.tk.Tk')
    @patch('t8_daq_system.gui.main_window.LivePlot')
    @patch('t8_daq_system.gui.main_window.SensorPanel')
    @patch('t8_daq_system.gui.main_window.CameraPanel')
    @patch('t8_daq_system.gui.main_window.AppSettings')
    def test_soft_start_phase_sets_soft_start_status_then_handoff_reason(
        self, mock_settings_cls, _cam, _sensor, _plot, _tk
    ):
        _make_mock_settings(mock_settings_cls).soft_start_threshold_c = 200.0
        rig = MagicMock()
        rig.latest.return_value = _snapshot(ProgramStatus())
        app = MainWindow(rig=rig)
        app.status_var = MagicMock()

        app.render_snapshot(_snapshot(ProgramStatus(running=True, phase="soft_start")))
        text = app.status_var.set.call_args.args[0]
        assert text.startswith("SOFT START")
        assert "0.29 V" in text and "25.0 °C" in text and "PID at 200" in text

        handoff = ProgramStatus(running=True, phase="block", handoff_reason="threshold 200.0 °C reached")
        app.render_snapshot(_snapshot(handoff))
        assert "threshold 200.0 °C reached" in app.status_var.set.call_args.args[0]

        # Past the 30 s window the handoff reason is no longer written.
        app.status_var.reset_mock()
        with patch('t8_daq_system.gui.main_window.time.monotonic',
                   return_value=app._handoff_shown_at + MainWindow.HANDOFF_STATUS_S + 1.0):
            app.render_snapshot(_snapshot(handoff))
        app.status_var.set.assert_not_called()

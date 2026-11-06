"""
Soft start and the run's gains and current caps, shown in the panel the app builds.

WHY THIS EXISTS
---------------
Ticket 25 (ADR 0006) put a locked Soft-start row and a gains / current-caps readout
into ``PowerProgrammerPanel``, but MainWindow builds ``ProgramPanel``, so operators
saw neither, only the Soft-start span on the preview graph. These tests pin both on
``ProgramPanel`` and pin MainWindow feeding it each rendered Snapshot. Since the
2026-11-05 amendment to ADR 0006 the Soft-start row is an optional block: none by
default, added from Add Block as block 1, deleted like any other.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from t8_daq_system.control.program_block import StableHoldBlock, VoltageRampBlock
from t8_daq_system.gui.program_panel import ProgramPanel
from t8_daq_system.rig.commands import RunSettings
from t8_daq_system.rig.snapshot import ProgramStatus

from tests.unit.test_live_tiles_and_programmer import _snapshot, app  # noqa: F401

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


def _panel(settings=None, with_settings=True) -> ProgramPanel:
    fn = (lambda: settings or _run_settings()) if with_settings else None
    return ProgramPanel(MagicMock(), get_soft_start_settings_fn=fn)


class TestSoftStartRow:
    """Soft start is an optional block (ADR 0006, amended 2026-11-05): none by default."""

    def test_row_text_names_threshold_and_handoff_current(self):
        panel = _panel()
        _add(panel, "Soft Start")

        text = panel.get_soft_start_row_text()

        assert text.startswith("Soft start")
        assert "200" in text and "35" in text

    def test_row_text_follows_the_settings_a_run_would_use_now(self):
        settings = _run_settings()
        panel = ProgramPanel(MagicMock(), get_soft_start_settings_fn=lambda: settings)
        _add(panel, "Soft Start")
        settings = _run_settings(soft_start_threshold_c=150.0, soft_start_handoff_current_a=30.0)

        panel.refresh_run_labels(None)

        assert "150" in panel.get_soft_start_row_text()
        assert "30" in panel.get_soft_start_row_text()

    def test_no_row_without_soft_start_settings(self):
        panel = _panel(with_settings=False)

        assert panel.get_soft_start_row_text() == ""

    def test_row_is_not_a_block_and_survives_block_edits(self):
        # Rewritten in place: Soft start is now a block, so deleting it removes it
        # and the other blocks are untouched.
        panel = _panel()
        panel.load_blocks([VoltageRampBlock(0.0, 1.0, 60.0), StableHoldBlock(293.15, 2.0, 60.0)])
        _add(panel, "Soft Start")

        panel._delete_block(0)

        assert [b.block_type for b in panel.get_blocks()] == ["voltage_ramp", "stable_hold"]
        assert panel.get_soft_start_row_text() == ""

    def test_new_program_has_no_soft_start(self):
        panel = _panel()

        assert panel.get_blocks() == []
        assert panel.get_soft_start_row_text() == ""

    def test_added_soft_start_goes_first_whatever_was_there(self):
        panel = _panel()
        panel.load_blocks([VoltageRampBlock(0.0, 1.0, 60.0)])

        _add(panel, "Soft Start")

        assert [b.block_type for b in panel.get_blocks()] == ["soft_start", "voltage_ramp"]

    def test_a_program_holds_at_most_one_soft_start(self):
        panel = _panel()

        _add(panel, "Soft Start")
        _add(panel, "Soft Start")

        assert [b.block_type for b in panel.get_blocks()] == ["soft_start"]

    def test_soft_start_offered_in_add_block(self):
        assert "Soft Start" in ProgramPanel.BLOCK_TYPES


def _add(panel: ProgramPanel, label: str) -> None:
    panel._add_type_var = MagicMock()
    panel._add_type_var.get.return_value = label
    panel._add_block()


class TestGainsAndCapsReadout:

    def test_idle_readout_comes_from_run_settings(self):
        panel = _panel(_run_settings(kp=2.0, ki=0.1, kd=0.2, soft_start_cap_enabled=False))

        panel.refresh_run_labels(None)

        assert panel.get_gains_text() == "Gains in use: 2 / 0.1 / 0.2"
        assert "Soft-start cap: OFF" in panel.get_caps_text()
        assert "Run cap: 120 A" in panel.get_caps_text()

    def test_run_cap_off_when_disabled(self):
        panel = _panel(_run_settings(run_cap_enabled=False))

        panel.refresh_run_labels(None)

        assert "Run cap: OFF" in panel.get_caps_text()
        assert "Soft-start cap: 40 A" in panel.get_caps_text()

    def test_running_gains_come_from_snapshot(self):
        panel = _panel()

        panel.refresh_run_labels(_snapshot_with(ProgramStatus(running=True, gains_in_use=(3.0, 0.5, 0.25))))

        assert panel.get_gains_text() == "Gains in use: 3 / 0.5 / 0.25"

    def test_idle_snapshot_falls_back_to_run_settings(self):
        panel = _panel()

        panel.refresh_run_labels(_snapshot_with(ProgramStatus(running=False, gains_in_use=(3.0, 0.5, 0.25))))

        assert panel.get_gains_text() == "Gains in use: 1 / 0.05 / 0.05"

    def test_readout_filled_at_construction(self):
        panel = _panel()

        assert panel.get_gains_text().startswith("Gains in use:")
        assert panel.get_caps_text()


class TestMainWindowFeedsThePanel:

    def test_render_snapshot_refreshes_the_programmer_readout(self, app):  # noqa: F811
        window, _ = app
        window._activate_power_programmer()
        window._programmer_panel.refresh_run_labels = MagicMock()
        snap = _snapshot()

        window.render_snapshot(snap)

        window._programmer_panel.refresh_run_labels.assert_called_with(snap)


def _snapshot_with(program: ProgramStatus):
    snap = _snapshot()
    return snap.__class__(**{**snap.__dict__, "program": program})

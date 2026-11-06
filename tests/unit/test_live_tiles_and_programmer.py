"""
Regression tests: live readout tiles, the PowerSupply indicator, and block building.

WHY THIS EXISTS
---------------
Three operator-facing faults left over from moving hardware ownership into the Rig
(ADR 0002), none caught because each crossed a seam the old tests did not:

1. Adding any block in the Power Programmer raised AttributeError: the panel's
   initial-state callback read ``MainWindow._latest_snapshot``, which nothing
   assigned. Tk swallows callback errors in the windowed build, so the button
   simply did nothing.
2. Pressure tiles showed "-.--e--" while the plots trended: ``_on_snapshot``
   labelled every gauge reading 'OK', but ``SensorPanel.update_frg702_status``
   shows a number only for its STATUS_VALID ('valid').
3. The PowerSupply indicator never lit on live hardware: it asked for
   ``MainWindow.ps_controller``, which is always None now that the T8 adapter
   owns the controller. The same flag dropped the PS columns from CSV logs.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from t8_daq_system.gui.main_window import MainWindow
from t8_daq_system.gui.sensor_panel import STATUS_VALID, SensorPanel
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig
from t8_daq_system.rig.snapshot import HeaterStatus, ProgramStatus, Snapshot, SourceStatus

pytestmark = pytest.mark.unit

GAUGE = "FRG702_Chamber"


def _snapshot(adapter="t8", pressure=1.0e-7, ps_volts=1.25, tc_name="TC_1") -> Snapshot:
    return Snapshot(
        t=10.0,
        wall_time=1700000000.0,
        tc_c={tc_name: 25.0},
        tc_raw_v={tc_name: 0.001},
        pressure_torr={GAUGE: pressure},
        source_age_s={tc_name: 0.0, GAUGE: 0.0},
        ps_volts=ps_volts,
        ps_amps=4.0,
        commanded_volts=ps_volts,
        output_enabled=True,
        labjack=SourceStatus(state="connected"),
        xgs=SourceStatus(state="connected"),
        heater=HeaterStatus(state="on"),
        program=ProgramStatus(),
        permissive_ok=True,
        permissive_reason=None,
        adapter=adapter,
    )


def _settings(mock_settings_cls):
    s = mock_settings_cls.return_value
    s.tc_count = 1
    s.tc_unit = "C"
    s.frg_count = 1
    s.p_unit = "Torr"
    s.sample_rate_ms = 1000
    s.display_rate_ms = 1000
    s.use_absolute_scales = True
    s.temp_range = (0.0, 2500.0)
    s.press_range = (1e-9, 1e-3)
    s.ps_v_range = (0.0, 100.0)
    s.ps_i_range = (0.0, 100.0)
    s.get_tc_type_list.return_value = ["K"]
    s.get_tc_pin_list.return_value = ["AIN0"]
    s.get_frg_pin_list.return_value = ["AIN2"]
    s.visa_resource = ""
    s.frg_interface = "XGS600"
    s.ps_interface = "Analog"
    s.log_folder = ""
    s.reset_graph_on_start_logging = False
    s.pid_kp = 0.014
    s.pid_ki = 0.00078
    s.pid_kd = 0.00845
    s.pid_windup_limit = 1.0
    # Real values: the programmer formats these into its Soft-start row and readout
    s.soft_start_threshold_c = 200.0
    s.soft_start_ramp_v_per_s = 0.02
    s.soft_start_handoff_current_a = 35.0
    s.soft_start_cap_enabled = True
    s.soft_start_cap_a = 40.0
    s.run_cap_enabled = True
    s.run_cap_a = 120.0
    return s


@pytest.fixture
def app():
    with patch('t8_daq_system.gui.main_window.tk.Tk'), \
         patch('t8_daq_system.gui.main_window.LivePlot'), \
         patch('t8_daq_system.gui.main_window.SensorPanel'), \
         patch('t8_daq_system.gui.main_window.CameraPanel'), \
         patch('t8_daq_system.gui.main_window.AppSettings') as mock_settings_cls:
        _settings(mock_settings_cls)
        rig = MagicMock()
        rig.latest.return_value = _snapshot()
        window = MainWindow(rig=rig)
        yield window, rig


class TestBlockBuilding:
    """Adding a block in the Power Programmer must work for every block type."""

    @pytest.mark.parametrize("block_label", ["Linear Voltage Ramp", "Stable Hold", "Temp Ramp"])
    def test_add_block_adds_one_block(self, app, block_label):
        window, _ = app
        window._activate_power_programmer()
        panel = window._programmer_panel
        panel._add_type_var = MagicMock()
        panel._add_type_var.get.return_value = block_label

        panel._add_block()

        assert len(panel.get_blocks()) == 1

    def test_initial_state_comes_from_latest_snapshot(self, app):
        window, rig = app
        first_tc = window.config['thermocouples'][0]['name']
        rig.latest.return_value = _snapshot(ps_volts=1.25, tc_name=first_tc)

        temp_k, volts = window._programmer_initial_state()

        assert temp_k == pytest.approx(25.0 + 273.15)
        assert volts == pytest.approx(1.25)

    def test_initial_state_without_a_snapshot_is_cold_and_unpowered(self, app):
        window, rig = app
        rig.latest.return_value = None

        temp_k, volts = window._programmer_initial_state()

        assert temp_k == pytest.approx(293.15)
        assert volts == 0.0


class TestPressureTile:
    """A fresh pressure reading must reach the tile as a number."""

    def test_snapshot_gauge_detail_is_valid_when_reading_present(self, app):
        window, _ = app
        window._on_snapshot(_snapshot(pressure=1.0e-7))

        assert window._latest_frg702_details[GAUGE]["status"] == STATUS_VALID

    def test_snapshot_gauge_detail_is_not_valid_when_reading_missing(self, app):
        window, _ = app
        window._on_snapshot(_snapshot(pressure=None))

        assert window._latest_frg702_details[GAUGE]["status"] != STATUS_VALID

    def test_sensor_panel_shows_the_number_from_snapshot_details(self, app):
        window, _ = app
        window._on_snapshot(_snapshot(pressure=1.0e-7))
        panel = SensorPanel(MagicMock(), [], [{"name": GAUGE, "units": "Torr"}])
        panel.displays[GAUGE] = MagicMock()

        panel.update_frg702_status(window._latest_frg702_details)

        panel.displays[GAUGE].config.assert_called_with(text="1.00e-07", foreground="black")


class TestPowerSupplyPresence:
    """The PowerSupply indicator and CSV PS columns follow the Rig, not a stale GUI field."""

    def test_rig_reports_supply_for_simulated_adapter(self):
        clock = ManualClock()
        rig = Rig(adapter=SimulatedRig(clock=clock), clock=clock)
        assert rig.has_power_supply() is True

    def test_rig_reports_supply_when_t8_adapter_holds_a_controller(self):
        adapter = MagicMock(spec=["ps_controller", "is_connected"])
        adapter.ps_controller = MagicMock()
        rig = Rig(adapter=adapter, clock=ManualClock())
        assert rig.has_power_supply() is True

    def test_rig_reports_no_supply_when_t8_adapter_has_no_controller(self):
        adapter = MagicMock(spec=["ps_controller", "is_connected"])
        adapter.ps_controller = None
        rig = Rig(adapter=adapter, clock=ManualClock())
        assert rig.has_power_supply() is False

    def test_indicator_green_on_live_hardware_with_supply(self, app):
        window, rig = app
        window.ps_controller = None  # the GUI never holds the controller (ADR 0002)
        rig.latest.return_value = _snapshot(adapter="t8")
        rig.has_power_supply.return_value = True
        window.indicators['PowerSupply'] = MagicMock()

        window._update_gui()

        window.indicators['PowerSupply'].config.assert_called_with(bg='#00FF00')

    def test_indicator_dark_when_rig_has_no_supply(self, app):
        window, rig = app
        rig.latest.return_value = _snapshot(adapter="t8")
        rig.has_power_supply.return_value = False
        window.indicators['PowerSupply'] = MagicMock()

        window._update_gui()

        window.indicators['PowerSupply'].config.assert_called_with(bg='#333333')

    def test_csv_ps_columns_follow_the_rig(self, app):
        window, rig = app
        window.ps_controller = None
        rig.has_power_supply.return_value = True
        assert window._ps_present() is True
        rig.has_power_supply.return_value = False
        assert window._ps_present() is False


class TestPowerSupplyTilesWhenUnreachable:
    """With no T8 (or no supply) the PS tiles say so instead of a green 0.000 V.

    The Rig fills ps_volts/ps_amps with 0.0 when it cannot read the supply, and
    SensorPanel shows any number as CONNECTED, so the GUI must hand it None.
    """

    def _idle_ps_readings(self, window, rig, snap, has_ps=True):
        rig.latest.return_value = snap
        rig.has_power_supply.return_value = has_ps
        window.is_running = False
        window.sensor_panel = MagicMock()
        window._update_gui()
        return window.sensor_panel.update.call_args.args[0]

    def test_idle_tiles_none_when_labjack_disconnected(self, app):
        window, rig = app
        snap = _snapshot(ps_volts=0.0)
        snap = snap.__class__(**{**snap.__dict__, "labjack": SourceStatus(state="disconnected")})

        readings = self._idle_ps_readings(window, rig, snap)

        assert readings["PS_Voltage"] is None
        assert readings["PS_Current"] is None

    def test_idle_tiles_none_when_rig_has_no_supply(self, app):
        window, rig = app

        readings = self._idle_ps_readings(window, rig, _snapshot(ps_volts=0.0), has_ps=False)

        assert readings["PS_Voltage"] is None
        assert readings["PS_Current"] is None

    def test_idle_tiles_show_values_when_connected_with_supply(self, app):
        window, rig = app

        readings = self._idle_ps_readings(window, rig, _snapshot(ps_volts=1.25))

        assert readings["PS_Voltage"] == pytest.approx(1.25)
        assert readings["PS_Current"] == pytest.approx(4.0)

    def test_running_buffer_gets_none_when_labjack_disconnected(self, app):
        window, rig = app
        rig.has_power_supply.return_value = True
        window.data_buffer = MagicMock()
        window.is_running = True
        snap = _snapshot(ps_volts=0.0)
        snap = snap.__class__(**{**snap.__dict__, "labjack": SourceStatus(state="disconnected")})

        window._on_snapshot(snap)

        added = window.data_buffer.add_reading.call_args.args[0]
        assert added["PS_Voltage"] is None
        assert added["PS_Current"] is None

    def test_sensor_panel_shows_disconnected_for_none_voltage(self):
        panel = SensorPanel(MagicMock(), [], [])
        panel.displays["PS_Voltage"] = MagicMock()
        panel.status_labels["PS_Voltage"] = MagicMock()

        panel.update({"PS_Voltage": None})

        panel.displays["PS_Voltage"].config.assert_called_with(text="--- V", foreground="gray")
        panel.status_labels["PS_Voltage"].config.assert_called_with(text="DISCONNECTED", foreground="red")

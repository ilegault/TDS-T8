"""
Run settings travel with Start (ticket 19, ADR 0007).

WHY THIS EXISTS
---------------
The run must use exactly the RunSettings captured at Run. These tests drive a
real Rig + SimulatedRig + ManualClock and assert on published Snapshots.
"""
from __future__ import annotations

import pytest

from t8_daq_system.control.program_block import VoltageRampBlock
from t8_daq_system.control.temp_ramp_pid import PIDController
from t8_daq_system.rig.commands import LoadProgram, StartProgram
from t8_daq_system.settings.app_settings import AppSettings
from t8_daq_system.gui.main_window import run_settings_from_app_settings
from tests.integration.test_program_run_rig import make_rig_fixture, tick
from tests.run_settings_helper import make_run_settings


def _start(ns, settings) -> None:
    tick(ns)
    ns.rig.submit(LoadProgram(program=[
        VoltageRampBlock(start_voltage=0.0, end_voltage=0.1, duration_sec=20.0),
    ]))
    ns.rig.submit(StartProgram(settings=settings))
    tick(ns, n=3)


def test_gains_in_use_come_from_start_settings():
    ns = make_rig_fixture()
    _start(ns, make_run_settings(kp=0.5, ki=0.25, kd=0.125))
    snap = ns.rig.latest()
    assert snap.program.running is True
    assert snap.program.gains_in_use == (0.5, 0.25, 0.125)
    assert snap.program.gains_in_use[0] == 0.5


def test_gains_in_use_unchanged_when_app_settings_change_after_run():
    ns = make_rig_fixture()
    app = AppSettings()
    app.pid_kp = 0.5
    _start(ns, run_settings_from_app_settings(app))
    assert ns.rig.latest().program.gains_in_use[0] == 0.5

    app.pid_kp = 9.0
    app.pid_ki = 9.0
    app.pid_kd = 9.0
    tick(ns, n=4)
    assert ns.rig.latest().program.gains_in_use[0] == 0.5


def test_run_settings_from_app_settings_copies_gains_and_windup():
    app = AppSettings()
    app.pid_kp, app.pid_ki, app.pid_kd, app.pid_windup_limit = 0.1, 0.2, 0.3, 0.4
    rs = run_settings_from_app_settings(app)
    assert (rs.kp, rs.ki, rs.kd, rs.windup_limit) == (0.1, 0.2, 0.3, 0.4)


def test_pid_controller_requires_gains():
    with pytest.raises(TypeError):
        PIDController()

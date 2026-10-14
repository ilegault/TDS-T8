"""
Ticket 23: the Soft-start and Run current caps trip the heater.

WHY THIS EXISTS
---------------
ADR 0006 point 4: a cold tungsten filament that draws more than the configured
cap (shorted lead, voltage step on a cold filament) must be cut off in the same
tick, latched, with a reason naming the numbers. These tests drive a real Rig +
SimulatedRig + ManualClock and force the measured current with
SimulatedRig.force_current.
"""
from __future__ import annotations

import pytest

from tests.integration.test_run_record_integration import _advance, _make_fixture
from tests.run_settings_helper import make_run_settings
from t8_daq_system.control.program_block import TempRampBlock
from t8_daq_system.rig.commands import LoadProgram, ResetTrip, StartProgram

pytestmark = pytest.mark.integration

BLOCKS = [TempRampBlock(rate_k_per_min=60.0, end_temp_k=1500.0, tc_name="TC_1")]


def _start(tmp_path, **settings):
    rig, rr, logger_, clock, sim, _ = _make_fixture(tmp_path)
    rig.submit_command(LoadProgram(program=BLOCKS))
    _advance(rig, clock, 1)
    rig.submit_command(StartProgram(settings=make_run_settings(**settings)))
    _advance(rig, clock, 3)
    return rig, rr, logger_, clock, sim


def _stop(rr, logger_):
    rr.stop()
    logger_.stop_logging()


def test_soft_start_overcurrent_trips_in_the_same_snapshot(tmp_path):
    rig, rr, logger_, clock, sim = _start(
        tmp_path, soft_start_threshold_c=200.0, soft_start_cap_a=40.0
    )
    assert rig.latest().program.phase == "soft_start"
    sim.force_current(45.0)
    _advance(rig, clock, 1)
    snap = rig.latest()
    _stop(rr, logger_)

    assert snap.heater.state == "tripped"
    assert snap.heater.trip_kind == "soft_start_overcurrent"
    assert snap.output_enabled is False
    assert snap.commanded_volts == 0.0
    assert "45" in snap.heater.trip_reason
    assert "40" in snap.heater.trip_reason
    assert "soft_start" in snap.heater.trip_reason
    assert "check for a shorted lead or a voltage step on a cold filament" in (
        snap.heater.trip_reason
    )


def test_run_overcurrent_trips_after_handoff(tmp_path):
    rig, rr, logger_, clock, sim = _start(
        tmp_path, soft_start_threshold_c=-273.0, run_cap_enabled=True, run_cap_a=120.0
    )
    assert rig.latest().program.phase == "block"
    sim.force_current(125.0)
    _advance(rig, clock, 1)
    snap = rig.latest()
    _stop(rr, logger_)

    assert snap.heater.state == "tripped"
    assert snap.heater.trip_kind == "run_overcurrent"
    assert snap.output_enabled is False
    assert snap.commanded_volts == 0.0
    assert "125" in snap.heater.trip_reason
    assert "120" in snap.heater.trip_reason
    assert "check filament and leads" in snap.heater.trip_reason


def test_disabled_soft_start_cap_does_not_trip(tmp_path):
    rig, rr, logger_, clock, sim = _start(
        tmp_path,
        soft_start_threshold_c=200.0,
        soft_start_cap_enabled=False,
        soft_start_cap_a=40.0,
        soft_start_handoff_current_a=100.0,
    )
    sim.force_current(45.0)
    _advance(rig, clock, 3)
    snap = rig.latest()
    _stop(rr, logger_)

    assert snap.program.phase == "soft_start"
    assert snap.heater.state != "tripped"


def test_disabled_run_cap_does_not_trip(tmp_path):
    rig, rr, logger_, clock, sim = _start(
        tmp_path,
        soft_start_threshold_c=-273.0,
        run_cap_enabled=False,
        run_cap_a=120.0,
    )
    sim.force_current(125.0)
    _advance(rig, clock, 3)
    snap = rig.latest()
    _stop(rr, logger_)

    assert snap.heater.state != "tripped"


def test_reset_refused_while_current_above_cap_then_accepted(tmp_path):
    rig, rr, logger_, clock, sim = _start(
        tmp_path, soft_start_threshold_c=200.0, soft_start_cap_a=40.0
    )
    sim.force_current(45.0)
    _advance(rig, clock, 1)
    assert rig.latest().heater.trip_kind == "soft_start_overcurrent"

    rig.submit_command(ResetTrip())
    _advance(rig, clock, 1)
    refused = rig.latest()
    assert refused.heater.state == "tripped"
    assert refused.command_rejected_reason is not None
    assert "refused" in refused.command_rejected_reason.lower()

    sim.release_current()
    rig.submit_command(ResetTrip())
    _advance(rig, clock, 1)
    accepted = rig.latest()
    _stop(rr, logger_)

    assert accepted.heater.state == "off"
    assert accepted.heater.trip_kind is None

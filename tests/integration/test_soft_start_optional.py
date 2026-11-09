"""
Soft start is an optional block, not part of every run.

WHY THIS EXISTS
---------------
ADR 0006 (amended 2026-11-05): short PID tests need to step the voltage on purpose to
see transients, and a Soft start forced on every run made that impossible. Soft start
is now a SoftStartBlock the operator adds as block 1; a program without one starts
closed-loop (or open-loop for a Voltage ramp) on the first tick, with the Run current
cap active from that tick. These tests drive a real Rig + SimulatedRig + ManualClock
and assert on published Snapshots.
"""
from __future__ import annotations

import pytest

from tests.integration.test_run_record_integration import _advance, _make_fixture
from tests.run_settings_helper import make_run_settings
from t8_daq_system.control.program_block import (
    SoftStartBlock,
    TempRampBlock,
    VoltageRampBlock,
)
from t8_daq_system.rig.commands import LoadProgram, StartProgram

pytestmark = pytest.mark.integration

RAMP = TempRampBlock(rate_k_per_min=60.0, end_temp_k=1500.0, tc_name="TC_1")


def _start(tmp_path, blocks, **settings):
    rig, rr, logger_, clock, sim, program_run = _make_fixture(tmp_path)
    rig.submit_command(LoadProgram(program=blocks))
    _advance(rig, clock, 1)
    rig.submit_command(StartProgram(settings=make_run_settings(**settings)))
    _advance(rig, clock, 1)
    return rig, rr, logger_, clock, sim


def _stop(rr, logger_):
    rr.stop()
    logger_.stop_logging()


def test_program_without_soft_start_block_starts_in_block_phase_while_cold(tmp_path):
    # Threshold well above the cold sim: only the missing block can skip Soft start.
    rig, rr, logger_, clock, sim = _start(tmp_path, [RAMP], soft_start_threshold_c=200.0)
    snap = rig.latest()
    _stop(rr, logger_)

    assert snap.program.running
    assert snap.program.phase == "block"
    assert snap.program.block_type == "temp_ramp"
    assert snap.program.handoff_reason == ""


def test_voltage_step_without_soft_start_reaches_the_block_voltage_at_once(tmp_path):
    step = VoltageRampBlock(start_voltage=0.5, end_voltage=0.5, duration_sec=60.0)
    rig, rr, logger_, clock, sim = _start(tmp_path, [step], soft_start_threshold_c=200.0)
    _advance(rig, clock, 3)  # two warm-up ticks, then the first real step
    snap = rig.latest()
    _stop(rr, logger_)

    assert snap.commanded_volts == pytest.approx(0.5, abs=1e-6)


def test_run_cap_is_active_from_the_first_tick_without_soft_start(tmp_path):
    rig, rr, logger_, clock, sim = _start(
        tmp_path, [RAMP], soft_start_threshold_c=200.0, run_cap_enabled=True, run_cap_a=120.0
    )
    sim.force_current(125.0)
    _advance(rig, clock, 1)
    snap = rig.latest()
    _stop(rr, logger_)

    assert snap.heater.state == "tripped"
    assert snap.heater.trip_kind == "run_overcurrent"


def test_soft_start_block_is_block_one_and_handoff_advances_to_block_two(tmp_path):
    rig, rr, logger_, clock, sim = _start(
        tmp_path, [SoftStartBlock(), RAMP], soft_start_threshold_c=200.0
    )
    first = rig.latest().program
    seen = []
    for _ in range(3000):
        _advance(rig, clock, 1)
        seen.append(rig.latest().program)
        if seen[-1].phase == "block":
            break
    _stop(rr, logger_)

    assert first.phase == "soft_start"
    assert first.block_index == 0
    assert first.block_type == "soft_start"
    assert seen[-1].phase == "block"
    assert seen[-1].block_index == 1
    assert seen[-1].block_type == "temp_ramp"
    assert seen[-1].handoff_reason.startswith(("threshold", "handoff current"))


def test_program_of_only_a_soft_start_block_completes_at_handoff(tmp_path):
    rig, rr, logger_, clock, sim = _start(
        tmp_path, [SoftStartBlock()], soft_start_threshold_c=200.0
    )
    for _ in range(3000):
        _advance(rig, clock, 1)
        if not rig.latest().program.running:
            break
    snap = rig.latest()
    _stop(rr, logger_)

    assert not snap.program.running


def test_soft_start_cap_off_warning_only_when_the_program_has_a_soft_start(tmp_path, caplog):
    caplog.set_level("WARNING", logger="t8_daq_system.control.program_run")
    rig, rr, logger_, clock, sim = _start(tmp_path, [RAMP], soft_start_cap_enabled=False)  # not production: this test is about the disabled-Soft-start-cap warning
    _stop(rr, logger_)

    assert "Soft-start current cap is OFF" not in caplog.text

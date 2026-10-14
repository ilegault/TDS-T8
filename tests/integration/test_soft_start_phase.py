"""
Ticket 22: every Program run begins with a Soft start.

WHY THIS EXISTS
---------------
ADR 0006 points 1-3: a cold filament must never be hit with a voltage step. Soft
start ramps DAC0 open-loop, with no Feedforward, until the control TC reaches the
threshold or the measured current reaches the handoff current, then hands off to
block 0 without a voltage step. These tests drive a real Rig + SimulatedRig +
ManualClock + RunRecord and assert on published Snapshots and the CSV.
"""
from __future__ import annotations

import csv

import pytest

from tests.integration.test_run_record_integration import _advance, _make_fixture
from tests.run_settings_helper import make_run_settings
from t8_daq_system.control.program_block import TempRampBlock
from t8_daq_system.rig.commands import LoadProgram, StartProgram

pytestmark = pytest.mark.integration

RAMP_V_PER_S = 0.02
BLOCKS = [TempRampBlock(rate_k_per_min=60.0, end_temp_k=1500.0, tc_name="TC_1")]


def _event_rows(csv_file) -> list[list[str]]:
    rows = []
    with open(csv_file, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            row = next(csv.reader([line]))
            if len(row) >= 2 and row[1].startswith("EVENT:"):
                rows.append(row)
    return rows


def _run(tmp_path, *, threshold_c=200.0, ticks=3000, hot_tc_c=None):
    rig, rr, logger_, clock, sim, program_run = _make_fixture(tmp_path)
    rig.submit_command(LoadProgram(program=BLOCKS))
    _advance(rig, clock, 1)
    rig.submit_command(
        StartProgram(
            settings=make_run_settings(
                soft_start_threshold_c=threshold_c,
                soft_start_ramp_v_per_s=RAMP_V_PER_S,
            )
        )
    )
    seen = []
    for _ in range(ticks):
        _advance(rig, clock, 1)
        snap = rig.latest()
        seen.append(snap)
        if snap.program.phase == "block" and len(seen) > 40:
            break
    rr.stop()
    logger_.stop_logging()
    return seen, list(tmp_path.glob("*.csv"))[0]


def test_soft_start_voltage_ramps_no_faster_than_the_configured_rate(tmp_path):
    seen, _ = _run(tmp_path)
    soft = [s for s in seen if s.program.phase == "soft_start"]
    assert len(soft) > 3, "run never entered soft start"
    volts = [s.commanded_volts for s in soft]
    for prev, cur in zip(volts, volts[1:]):
        assert cur - prev <= RAMP_V_PER_S * 0.5 + 1e-9, volts


def test_soft_start_hands_off_with_a_reason(tmp_path):
    seen, _ = _run(tmp_path)
    final = seen[-1].program
    assert final.phase == "block"
    assert final.handoff_reason.startswith(("handoff current", "threshold"))


def test_handoff_reason_wording_names_the_numbers(tmp_path):
    seen, _ = _run(tmp_path)
    reason = seen[-1].program.handoff_reason
    if reason.startswith("threshold"):
        assert reason == "threshold 200.0 °C reached"
    else:
        assert reason.startswith("handoff current 35.0 A reached at ")
        assert reason.endswith(" °C")


def test_first_block_voltage_equals_last_soft_start_voltage(tmp_path):
    seen, _ = _run(tmp_path)
    soft = [s for s in seen if s.program.phase == "soft_start"]
    first_block = next(s for s in seen if s.program.phase == "block")
    assert first_block.commanded_volts == pytest.approx(
        soft[-1].commanded_volts, abs=0.0001
    )


def test_run_started_above_threshold_skips_soft_start(tmp_path):
    seen, csv_file = _run(tmp_path, threshold_c=10.0, ticks=3)
    first = seen[0].program
    assert first.phase == "block"
    assert first.handoff_reason.startswith("skipped: control TC ")
    assert first.handoff_reason.endswith(" °C ≥ threshold")
    events = _event_rows(csv_file)
    handoffs = [r for r in events if first.handoff_reason in r[2]]
    assert len(handoffs) == 1


def test_handoff_writes_exactly_one_event_row_with_the_reason(tmp_path):
    seen, csv_file = _run(tmp_path)
    reason = seen[-1].program.handoff_reason
    handoffs = [r for r in _event_rows(csv_file) if reason in r[2]]
    assert len(handoffs) == 1

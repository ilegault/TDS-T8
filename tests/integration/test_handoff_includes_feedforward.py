"""
Ticket 21: the bumpless handoff includes Feedforward.

WHY THIS EXISTS
---------------
ADR 0006 point 5: at every closed-loop block boundary the first commanded voltage
equals the last one, Feedforward included. Before this, the PID was seeded with the
previous voltage and step_temp_ramp then added Feedforward on top, so voltage jumped
by FF on entry to a TempRamp (and the PID's 0 V floor stopped it pulling back down).
"""
from __future__ import annotations

import pytest

from tests.integration.test_block_transitions import make_rig_fixture
from tests.run_settings_helper import make_run_settings
from t8_daq_system.control.feedforward_map import FeedforwardMap
from t8_daq_system.control.program_block import (
    StableHoldBlock,
    TempRampBlock,
    VoltageRampBlock,
)
from t8_daq_system.rig.commands import LoadProgram, StartProgram

pytestmark = pytest.mark.integration

TEMP_K = 300.0
# Tiny rate and end so the setpoint hugs the (fixed) measurement: the only thing
# that can move the voltage at a boundary is the Feedforward handling.
GENTLE_RAMP = dict(rate_k_per_min=0.06, end_temp_k=TEMP_K + 0.002, tc_name="TC_1")


def _flat_ff(volts: float) -> FeedforwardMap:
    ff_map = FeedforwardMap()
    ff_map._ss_curve = [[-100.0, volts], [2000.0, volts]]
    return ff_map


def _run(blocks, ff_volts: float, ticks: int = 40):
    """Return [(block_index, commanded_volts)] per running tick."""
    fix = make_rig_fixture(initial_temp_k=TEMP_K)
    fix.program_run._ff_map = _flat_ff(ff_volts)
    fix.spy.override_tc_c = {"TC_1": TEMP_K - 273.15}
    fix.clock.advance(0.5)
    fix.rig.run_tick()
    fix.rig.submit(LoadProgram(blocks))
    fix.rig.submit(StartProgram(settings=make_run_settings()))
    seen = []
    for _ in range(ticks):
        fix.clock.advance(0.5)
        fix.rig.run_tick()
        snap = fix.rig.latest()
        if not snap.program.running:
            break
        seen.append((snap.program.block_index, snap.commanded_volts))
    return seen


def _assert_continuous(seen, old: int, new: int, reference: float | None = None):
    old_v = [v for b, v in seen if b == old]
    new_v = [v for b, v in seen if b == new]
    assert old_v and len(new_v) > 5, f"blocks did not run: {seen}"
    ref = old_v[-1] if reference is None else reference
    # The new block's index is published on the tick its predecessor finishes
    # (nothing is commanded) plus two warm-up ticks: those three only hold the old
    # value. The ticks after them are the first real closed-loop outputs.
    for v in new_v[3:]:
        assert v == pytest.approx(ref, abs=1e-4), (new_v, ref)


@pytest.mark.parametrize("ff_volts", [1.5, 0.5], ids=["ff-above", "ff-below"])
def test_voltage_ramp_to_temp_ramp_is_continuous(ff_volts):
    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=1.0, duration_sec=1),
        TempRampBlock(**GENTLE_RAMP),
    ]
    _assert_continuous(_run(blocks, ff_volts), 0, 1, reference=1.0)


@pytest.mark.parametrize("ff_volts", [1.5, 0.5], ids=["ff-above", "ff-below"])
def test_stable_hold_to_temp_ramp_is_continuous(ff_volts):
    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=1.0, duration_sec=1),
        StableHoldBlock(target_temp_k=TEMP_K, tolerance_k=50.0, hold_duration_sec=0.1),
        TempRampBlock(**GENTLE_RAMP),
    ]
    seen = _run(blocks, ff_volts)
    _assert_continuous(seen, 1, 2)


@pytest.mark.parametrize("ff_volts", [1.5, 0.5], ids=["ff-above", "ff-below"])
def test_temp_ramp_to_stable_hold_is_continuous(ff_volts):
    blocks = [
        VoltageRampBlock(start_voltage=0.0, end_voltage=1.0, duration_sec=1),
        TempRampBlock(**GENTLE_RAMP),
        StableHoldBlock(target_temp_k=TEMP_K, tolerance_k=50.0, hold_duration_sec=5.0),
    ]
    seen = _run(blocks, ff_volts)
    _assert_continuous(seen, 1, 2)

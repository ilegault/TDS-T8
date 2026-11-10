"""
tests/scenarios/test_low_power_programs.py

Low power program scenario tests (ticket 42).

WHY THIS EXISTS
---------------
Proves that a conservative, low-power temperature ramp and hold program
runs to completion without tripping under production settings.
"""
from __future__ import annotations

import pytest

from t8_daq_system.control.program_block import StableHoldBlock, TempRampBlock
from t8_daq_system.settings.run_settings import production_run_settings
from tests.scenarios.harness import run_scenario

pytestmark = pytest.mark.scenario


def test_low_power_ramp_and_hold_completes() -> None:
    """
    A 10 K/min ramp to 373.15 K (100 C) followed by a 60 s hold completes
    normally on the calibrated simulator without tripping and stays below
    the production run_cap_a.
    """
    blocks = [
        TempRampBlock(rate_k_per_min=10.0, end_temp_k=373.15, tc_name="TC_1"),
        StableHoldBlock(target_temp_k=373.15, tolerance_k=5.0, hold_duration_sec=60.0),
    ]
    prod_settings = production_run_settings()
    res = run_scenario(blocks, settings=prod_settings)

    assert res.completed is True, f"Program did not complete: trip={res.trip_kind} ({res.trip_reason})"
    assert res.trip_kind is None, f"Expected no trip, got {res.trip_kind}"
    assert res.peak_amps < prod_settings.run_cap_a, (
        f"Peak amps {res.peak_amps:.1f} A exceeded run_cap_a {prod_settings.run_cap_a:.1f} A"
    )

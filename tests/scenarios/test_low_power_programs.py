"""Scenario tests for low-power programs (ticket 42).

WHY THIS EXISTS
---------------
Verifies that a low-power ramp and stable hold completes from cold to the end
under production settings without any trip, and stays below the production
Run current cap.
"""
from __future__ import annotations

import pytest

from tests.scenarios.harness import run_scenario
from t8_daq_system.control.program_block import StableHoldBlock, TempRampBlock
from t8_daq_system.settings.run_settings import production_run_settings

pytestmark = pytest.mark.scenario


def test_low_power_ramp_and_hold_completes() -> None:
    blocks = [
        TempRampBlock(rate_k_per_min=10.0, end_temp_k=373.15, tc_name="TC_1"),
        StableHoldBlock(target_temp_k=373.15, tolerance_k=5.0, hold_duration_sec=60.0),
    ]
    res = run_scenario(blocks)
    assert res.completed is True
    assert res.trip_kind is None
    assert res.peak_amps < production_run_settings().run_cap_a

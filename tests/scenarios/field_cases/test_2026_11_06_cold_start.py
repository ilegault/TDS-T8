"""
tests/scenarios/field_cases/test_2026_11_06_cold_start.py

Field case reproducing the 2026-11-06 lab cold start trip (ticket 42).

WHY THIS EXISTS
---------------
On 2026-11-06, starting a 30 K/min program from cold without soft start tripped
the Keysight power supply with "SO" (Shut Off) within ~1 minute of start while
the thermocouple was still cold.

Diagnostic log TRIP line:
    TRIP run_overcurrent: Run overcurrent: measured 120.0 A > cap 120.0 A (phase block, commanded ... V, control TC TC_1 ... °C); check filament and leads
"""
from __future__ import annotations

import pytest

from t8_daq_system.control.program_block import TempRampBlock
from tests.scenarios.harness import run_scenario

pytestmark = pytest.mark.scenario


def test_field_case_2026_11_06_cold_start() -> None:
    """
    Assert the 2026-11-06 cold-start trip reproduced on the calibrated simulator:
    trip_kind == "run_overcurrent" and tc_c_at_trip < 100.0.
    """
    blocks = [TempRampBlock(rate_k_per_min=30.0, end_temp_k=1500.0, tc_name="TC_1")]
    res = run_scenario(blocks)

    assert res.trip_kind == "run_overcurrent", f"Expected run_overcurrent trip, got {res.trip_kind}"
    assert res.tc_c_at_trip is not None, "Expected trip to record tc_c_at_trip"
    assert res.tc_c_at_trip < 100.0, f"Expected cold start trip with TC < 100 C, got {res.tc_c_at_trip:.1f} C"

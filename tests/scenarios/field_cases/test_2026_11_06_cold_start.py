"""Field case 2026-11-06: Cold start 30 K/min ramp trips run_overcurrent.

WHY THIS EXISTS
---------------
On 2026-11-06, a 30 K/min TempRamp from cold with no Soft start tripped
run_overcurrent within 60 s while the control TC was still cold (<30 °C), because
the Run current cap defaults to 120 A while normal runs require higher current.
Ticket 42 reproduces this trip; ticket 43 rewrites this test in place to assert the fix.

Diagnostic log TRIP line:
    TRIP run_overcurrent: measured 120.x A > cap 120.0 A (phase block, commanded ... V, control TC TC_1 ... °C); check filament and leads
"""
from __future__ import annotations

import pytest

from tests.scenarios.harness import run_scenario
from t8_daq_system.control.program_block import TempRampBlock

pytestmark = pytest.mark.scenario


def test_field_case_2026_11_06_cold_start() -> None:
    res = run_scenario([TempRampBlock(rate_k_per_min=30.0, end_temp_k=1500.0, tc_name="TC_1")])
    assert res.trip_kind == "run_overcurrent"
    assert res.tc_c_at_trip is not None
    assert res.tc_c_at_trip < 100.0

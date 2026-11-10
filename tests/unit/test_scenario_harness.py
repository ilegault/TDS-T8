"""
tests/unit/test_scenario_harness.py

Unit tests for the Scenario test harness (ticket 42).

WHY THIS EXISTS
---------------
Proves that run_scenario() correctly reports trips and metrics, and that the
'scenario' pytest marker accurately selects only scenario test files.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from t8_daq_system.control.program_block import TempRampBlock
from tests.run_settings_helper import make_run_settings
from tests.scenarios.harness import run_scenario

pytestmark = pytest.mark.unit


def test_harness_reports_a_trip() -> None:
    """Harness returns completed=False and trip details when a cap trips."""
    blocks = [TempRampBlock(rate_k_per_min=30.0, end_temp_k=1500.0, tc_name="TC_1")]
    settings = make_run_settings(
        run_cap_enabled=True, run_cap_a=1.0
    )  # not production: proves a trip is reported

    res = run_scenario(blocks, settings=settings)

    assert res.completed is False
    assert res.trip_kind == "run_overcurrent"
    assert res.trip_reason is not None and "Run overcurrent" in res.trip_reason
    assert res.tc_c_at_trip is not None


def test_scenario_marker_selects_the_scenarios_folder() -> None:
    """pytest -m scenario --collect-only -q runs in a subprocess and selects tests/scenarios/."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-m",
        "scenario",
        "--collect-only",
        "-q",
        "-o",
        "addopts=",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"pytest collect failed: {proc.stderr}"

    collected = [
        line.strip()
        for line in proc.stdout.splitlines()
        if "::" in line and not line.startswith("=")
    ]
    assert len(collected) >= 2, f"Expected at least two scenario tests collected, got: {collected}"
    for node_id in collected:
        normalized = node_id.replace("\\", "/")
        assert normalized.startswith("tests/scenarios/"), (
            f"Node id {node_id} does not start with tests/scenarios/"
        )

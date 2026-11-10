"""Unit tests for the Scenario test harness (ticket 42).

WHY THIS EXISTS
---------------
Scenario tests run full programs from cold to completion on the calibrated
simulator using production settings (or explicit overrides). This test verifies
that the harness correctly reports trips, captures metrics, and that the
pytest marker `scenario` selects the scenarios folder.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from tests.run_settings_helper import make_run_settings
from tests.scenarios.harness import run_scenario
from t8_daq_system.control.program_block import TempRampBlock

pytestmark = pytest.mark.unit


def test_harness_reports_a_trip() -> None:
    settings = make_run_settings(
        run_cap_enabled=True, run_cap_a=1.0
    )  # not production: proves a trip is reported
    res = run_scenario(
        [TempRampBlock(rate_k_per_min=30.0, end_temp_k=500.0, tc_name="TC_1")],
        settings=settings,
    )
    assert res.completed is False
    assert res.trip_kind == "run_overcurrent"
    assert res.trip_reason is not None and "Run overcurrent" in res.trip_reason


def test_scenario_marker_selects_the_scenarios_folder() -> None:
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
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    node_ids = [
        line.strip()
        for line in proc.stdout.splitlines()
        if "::" in line and not line.startswith("=")
    ]
    assert len(node_ids) >= 2, f"Expected at least 2 scenario tests, found: {node_ids}"
    for node_id in node_ids:
        assert node_id.startswith(
            "tests/scenarios/"
        ), f"Node id {node_id} does not start with tests/scenarios/"

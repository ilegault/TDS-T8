"""
tests/field_runs.py
Re-exports Field run fixtures and loader from t8_daq_system.data.field_runs (ticket 40).

WHY THIS EXISTS
---------------
Field runs provide real lab hardware traces (downsampled to stay under 200 kB)
to calibrate the two-node tungsten simulator (ticket 41), run scenario tests (ticket 42),
and check safety limits against field operational bounds (ticket 43).

This module re-exports the pure loader from t8_daq_system.data.field_runs.
"""
from __future__ import annotations

from t8_daq_system.data.field_runs import (
    FIELD_RUN_NAMES,
    FieldRun,
    all_field_runs,
    load_field_run,
)

__all__ = ["FIELD_RUN_NAMES", "FieldRun", "all_field_runs", "load_field_run"]

"""Shared RunSettings factory for tests that submit StartProgram or start a ProgramRun."""
from __future__ import annotations

from dataclasses import replace

from t8_daq_system.rig.commands import RunSettings

# Gains match the values the old PIDController defaults gave these tests.
_BASE = RunSettings(
    kp=0.02,
    ki=0.0013,
    kd=0.005,
    windup_limit=30.0,
    soft_start_threshold_c=200.0,
    soft_start_ramp_v_per_s=0.02,
    soft_start_handoff_current_a=35.0,
    soft_start_cap_enabled=True,
    soft_start_cap_a=40.0,
    run_cap_enabled=True,
    run_cap_a=120.0,
)


def make_run_settings(**overrides) -> RunSettings:
    """Return a RunSettings with test defaults, overriding any named field."""
    return replace(_BASE, **overrides)


# The Run history file for the running test: tests/conftest.py points this at a
# file under that test's tmp_path before every test, so nothing under test can
# write the real logs/pid_runs.json (ADR 0007 point 7).
_pid_log_file: str | None = None


def set_pid_log_file(path: str | None) -> None:
    """Called by the autouse fixture in conftest.py."""
    global _pid_log_file
    _pid_log_file = path


def make_program_run(**kwargs):
    """Return a ProgramRun whose Run history file lies under the test's tmp_path."""
    from t8_daq_system.control.program_run import ProgramRun

    if _pid_log_file is None:
        raise RuntimeError("make_program_run() needs the per-test tmp_path fixture")
    return ProgramRun(_pid_log_file, **kwargs)

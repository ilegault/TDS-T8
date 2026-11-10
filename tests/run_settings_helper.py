"""Shared RunSettings factory for tests that submit StartProgram or start a ProgramRun.

WHY THIS EXISTS
---------------
Every test starts from Production settings (``production_run_settings()``, built from
``_DEFAULTS`` only), so a test cannot pass on settings the operator never runs
(ticket 39, ADR 0007). A test overrides a field only for a reason, and says so on that
line with ``# not production: <why>``; ``tests/unit/test_run_settings_helper.py``
enforces that. The helper holds no gain or cap literals.
"""
from __future__ import annotations

from dataclasses import replace

from t8_daq_system.rig.commands import RunSettings
from t8_daq_system.settings.run_settings import production_run_settings

_BASE = production_run_settings()


def make_run_settings(**overrides) -> RunSettings:
    """Return Production settings, overriding any named field."""
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

"""Ticket 26 / ADR 0008: the Diagnostic log foundation."""

import logging
import re
import threading

import pytest

from t8_daq_system.data.data_logger import (
    DataLogger,
    create_metadata_dict,
)
from t8_daq_system.data.run_record import RunRecord, build_header
from t8_daq_system.settings import app_settings
from t8_daq_system.settings.app_settings import AppSettings
from t8_daq_system.utils import diagnostic_log
from t8_daq_system.utils.diagnostic_log import new_run_id, start_session

from tests.unit.test_registry_single_source import FakeWinreg


@pytest.fixture(autouse=True)
def restore_root_logger():
    """start_session configures the root logger and the excepthooks; undo that."""
    import sys
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    hooks = (sys.excepthook, threading.excepthook)
    yield
    for h in list(root.handlers):
        if h not in handlers:
            root.removeHandler(h)
            h.close()
    root.setLevel(level)
    sys.excepthook, threading.excepthook = hooks


def _flush():
    for h in logging.getLogger().handlers:
        h.flush()


def test_new_run_id_format():
    assert re.fullmatch(r"\d{8}_\d{6}", new_run_id())


def test_start_session_first_line_has_build_adapter_and_run_id(tmp_path):
    path = start_session(tmp_path, keep=30, build_id="dev", run_id="20261013_101500",
                         adapter="simulated")
    _flush()
    assert path.parent == tmp_path / "console"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_20261013_101500\.log", path.name)
    first = path.read_text(encoding="utf-8").splitlines()[0]
    assert first == "Build dev · adapter simulated · run 20261013_101500" or \
        first.endswith("Build dev · adapter simulated · run 20261013_101500")


def test_rotation_keeps_only_newest_keep_files(tmp_path):
    console = tmp_path / "console"
    console.mkdir()
    for i in range(5):
        old = console / f"2020-01-0{i + 1}_old{i}.log"
        old.write_text("x")
        import os
        os.utime(old, (1_000_000 + i, 1_000_000 + i))
    path = start_session(tmp_path, keep=3, build_id="dev", run_id="20261013_101501",
                         adapter="simulated")
    _flush()
    remaining = sorted(console.glob("*.log"))
    assert len(remaining) == 3
    assert path in remaining


def test_settings_dump_names_key_value_and_source(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "winreg", FakeWinreg({"pid_kp": "0.5"}))
    settings = AppSettings().load()
    path = start_session(tmp_path, keep=30, build_id="dev", run_id="20261013_101502",
                         adapter="simulated", settings=settings)
    _flush()
    lines = path.read_text(encoding="utf-8").splitlines()
    kp = [ln for ln in lines if "setting pid_kp=" in ln]
    assert len(kp) == 1 and "(registry)" in kp[0]
    ki = [ln for ln in lines if "setting pid_ki=" in ln]
    assert len(ki) == 1 and "(default)" in ki[0]


def test_uncaught_thread_exception_is_logged_with_traceback(tmp_path):
    path = start_session(tmp_path, keep=30, build_id="dev", run_id="20261013_101503",
                         adapter="simulated")

    def boom():
        raise RuntimeError("thread blew up 4711")

    t = threading.Thread(target=boom)
    t.start()
    t.join()
    _flush()
    text = path.read_text(encoding="utf-8")
    assert "ERROR" in text and "thread blew up 4711" in text and "Traceback" in text


def test_run_record_csv_metadata_carries_run_id(tmp_path):
    run_id = "20261013_101504"
    tc_names, gauge_names = ["TC_1"], ["FRG702_Chamber"]
    logger_ = DataLogger(log_folder=str(tmp_path))
    logger_.start_logging(
        build_header(tc_names, gauge_names, has_ps=True),
        metadata=create_metadata_dict(tc_count=1, run_id=run_id),
    )
    rr = RunRecord(logger_=logger_, tc_names=tc_names, gauge_names=gauge_names,
                   t_unit="C", p_unit="mbar", sample_rate_ms=500.0, has_ps=True)
    rr.start()
    rr.stop()
    logger_.stop_logging()
    metadata, _ = DataLogger.load_csv_with_metadata(logger_.current_filepath)
    assert metadata["run_id"] == run_id


def test_module_has_no_gui_imports():
    src = open(diagnostic_log.__file__, encoding="utf-8").read()
    assert "tkinter" not in src and "gui" not in src

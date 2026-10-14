"""
tests/unit/test_build_id.py

Build ID on every artifact (ticket cold-start-and-traceability-33, ADR 0008).

WHY THIS EXISTS
---------------
A 2026-10-01 run could not be diagnosed because nobody knew which build was
installed.  These tests pin the Build ID format, the refusal to build from a
dirty tree, and that the ID reaches the window title and the CSV header.
git and PyInstaller are faked through the injectable ``run``; everything
written is real, under tmp_path.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from t8_daq_system import build_info
from t8_daq_system.data.data_logger import DataLogger, create_metadata_dict
from t8_daq_system.data.run_record import RunRecord, build_header
from t8_daq_system.rig.snapshot import HeaterStatus, ProgramStatus, Snapshot, SourceStatus

pytestmark = pytest.mark.unit

_BUILD_PY = Path(__file__).resolve().parents[2] / "scripts" / "build.py"


def _load_build():
    spec = importlib.util.spec_from_file_location("tds_build_script", _BUILD_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tds_build_script"] = mod
    spec.loader.exec_module(mod)
    return mod


build = _load_build()


def test_build_id_format_clean_and_dirty():
    assert build.build_id("7656f09", date(2026, 10, 5), False) == "2026-10-05_7656f09"
    assert build.build_id("7656f09", date(2026, 10, 5), True).endswith("-dirty")


def test_build_info_text_names_id_branch_and_every_file():
    text = build.build_info_text(
        "2026-10-05_7656f09", "main", "2026-10-05 12:00:00", ["a.exe", "lib/b.dll"]
    )
    for needle in ("2026-10-05_7656f09", "main", "a.exe", "lib/b.dll"):
        assert needle in text


class FakeRun:
    """Records calls; answers the three git queries; fakes PyInstaller output."""

    def __init__(self, root: Path, porcelain: str):
        self.root = root
        self.porcelain = porcelain
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if cmd[:2] == ["git", "status"]:
            return self.porcelain
        if cmd[:3] == ["git", "rev-parse", "--short"]:
            return "7656f09\n"
        if cmd[:2] == ["git", "rev-parse"]:
            return "main\n"
        if "PyInstaller" in cmd:
            out = self.root / "dist" / "T8_DAQ_System"
            out.mkdir(parents=True)
            (out / "T8_DAQ_System.exe").write_text("exe")
            return ""
        raise AssertionError(f"unexpected command {cmd}")

    def pyinstaller_called(self) -> bool:
        return any("PyInstaller" in c for c in self.calls)


def test_dirty_tree_refused_without_allow_dirty(tmp_path, capsys):
    run = FakeRun(tmp_path, " M foo.py\n")
    code = build.main([], run=run, root=tmp_path, today=date(2026, 10, 5))
    assert code != 0
    assert "uncommitted" in capsys.readouterr().err
    assert not run.pyinstaller_called()


def test_allow_dirty_reaches_pyinstaller_and_names_artifacts(tmp_path):
    (tmp_path / "t8_daq_system").mkdir()
    run = FakeRun(tmp_path, " M foo.py\n")
    code = build.main(["--allow-dirty"], run=run, root=tmp_path, today=date(2026, 10, 5))
    assert code == 0
    assert run.pyinstaller_called()
    bid = "2026-10-05_7656f09-dirty"
    assert f'BUILD_ID = "{bid}"' in (tmp_path / "t8_daq_system" / "_build_info.py").read_text()
    out = tmp_path / "dist" / f"T8_DAQ_System_{bid}"
    assert (out / f"T8_DAQ_System_{bid}.exe").exists()
    info = (out / "BUILD_INFO.txt").read_text()
    assert bid in info and "main" in info and f"T8_DAQ_System_{bid}.exe" in info


def test_clean_tree_builds_without_flag(tmp_path):
    (tmp_path / "t8_daq_system").mkdir()
    run = FakeRun(tmp_path, "")
    assert build.main([], run=run, root=tmp_path, today=date(2026, 10, 5)) == 0
    assert (tmp_path / "dist" / "T8_DAQ_System_2026-10-05_7656f09").is_dir()


def test_get_build_id_is_dev_without_generated_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "t8_daq_system._build_info", None)
    assert build_info.get_build_id() == "dev"


def test_get_build_id_reads_generated_module(monkeypatch):
    fake = MagicMock(BUILD_ID="2026-10-05_abc1234")
    monkeypatch.setitem(sys.modules, "t8_daq_system._build_info", fake)
    assert build_info.get_build_id() == "2026-10-05_abc1234"


def test_window_title_ends_with_build_id(monkeypatch):
    monkeypatch.setitem(sys.modules, "t8_daq_system._build_info", None)
    from t8_daq_system.gui.main_window import MainWindow

    rig = MagicMock()
    rig.latest.return_value = Snapshot(
        t=0.0, wall_time=0.0, tc_c={"TC_1": 25.0}, tc_raw_v={"TC_1": 0.001},
        pressure_torr={"FRG702_Chamber": 1e-7},
        source_age_s={"TC_1": 0.0, "FRG702_Chamber": 0.0},
        ps_volts=1.5, ps_amps=10.0, commanded_volts=1.5, output_enabled=True,
        labjack=SourceStatus(state="connected"), xgs=SourceStatus(state="connected"),
        heater=HeaterStatus(state="on"), program=ProgramStatus(),
        permissive_ok=True, permissive_reason=None, adapter="simulated",
    )
    app = MainWindow(rig=rig)
    titles = [c.args[0] for c in app.root.title.call_args_list]
    assert titles and titles[0].endswith("dev")


def test_csv_metadata_carries_build_id(tmp_path):
    tc_names, gauge_names = ["TC_1"], ["FRG702_Chamber"]
    logger_ = DataLogger(log_folder=str(tmp_path))
    logger_.start_logging(
        build_header(tc_names, gauge_names, has_ps=True),
        metadata=create_metadata_dict(tc_count=1, build_id="2026-10-05_7656f09"),
    )
    rr = RunRecord(logger_=logger_, tc_names=tc_names, gauge_names=gauge_names,
                   t_unit="C", p_unit="mbar", sample_rate_ms=500.0, has_ps=True)
    rr.start()
    rr.stop()
    logger_.stop_logging()
    text = Path(logger_.current_filepath).read_text(encoding="utf-8")
    assert "build_id" in text
    metadata, _ = DataLogger.load_csv_with_metadata(logger_.current_filepath)
    assert metadata["build_id"] == "2026-10-05_7656f09"

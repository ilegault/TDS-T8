"""
t8_daq_system/utils/diagnostic_log.py

The per-session Diagnostic log (ticket cold-start-and-traceability-26, ADR 0008).

WHY THIS EXISTS
---------------
A run on the deployed lab PC could not be diagnosed: the console was hidden, the
CSV was never started and nobody knew which build was installed.  Every session now
writes one file, ``<log_dir>/console/<YYYY-MM-DD>_<run id>.log``, that the operator
can send with the CSV.  Its first line names the Build ID, adapter and Run ID; the
next lines dump every setting with where it came from (registry or default), so a
silent default is visible.  Uncaught exceptions on any thread are logged with a
traceback rather than lost with a hidden console.

No GUI imports: this module is pure so it can run before any window exists.
"""
from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def new_run_id() -> str:
    """Return a Run ID, ``YYYYMMDD_HHMMSS``; shared by the log file and the CSV."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _log_uncaught(exc_type, exc_value, exc_tb) -> None:
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))


def _log_uncaught_thread(args) -> None:
    logger.error(
        "Uncaught exception in thread %s",
        args.thread.name if args.thread else "?",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _rotate(console_dir: Path, keep: int) -> None:
    """Delete the oldest ``*.log`` files so at most ``keep`` remain."""
    files = sorted(console_dir.glob("*.log"), key=lambda p: (p.stat().st_mtime, p.name))
    for old in files[: max(0, len(files) - keep)]:
        old.unlink()


def start_session(log_dir, keep: int, build_id: str, run_id: str, adapter: str,
                  settings=None) -> Path:
    """
    Configure the root logger to write this session's Diagnostic log; return its path.

    ``settings`` (an AppSettings) is dumped one INFO line per key with its source.
    """
    console_dir = Path(log_dir) / "console"
    console_dir.mkdir(parents=True, exist_ok=True)
    path = console_dir / f"{datetime.now():%Y-%m-%d}_{run_id}.log"

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    sys.excepthook = _log_uncaught
    threading.excepthook = _log_uncaught_thread

    logger.info("Build %s · adapter %s · run %s", build_id, adapter, run_id)
    if settings is not None:
        for key, source in settings.sources.items():
            logger.info("setting %s=%s (%s)", key, getattr(settings, key, None), source)

    _rotate(console_dir, keep)
    return path

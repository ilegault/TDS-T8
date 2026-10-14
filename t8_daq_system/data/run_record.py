"""
t8_daq_system/data/run_record.py

CSV log writer for the Rig's step-7 Snapshot stream (ticket rig-architecture-11).

WHY THIS EXISTS
---------------
Previously, CSV rows were assembled inside a closure in MainWindow._on_snapshot,
running on the Rig thread and computing Block_Index in three separate places.
Display-unit conversion, sched-state extraction, and raw-voltage lookup were all
interleaved with the GUI callback, making the column schema impossible to test
in isolation and coupling the log format to GUI state.

RunRecord owns the column schema.  build_row() is a pure function (no I/O, no
state) that converts a Snapshot into a column dict.  The writer thread drains a
queue of Snapshots and events, writes one data row per sample_rate_ms, and writes
event rows immediately.  Shutdown is sentinel-based: stop() enqueues _STOP and
joins the thread — no time.sleep, testable with ManualClock.
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from t8_daq_system.data.data_logger import DataLogger
from t8_daq_system.rig.snapshot import Snapshot
from t8_daq_system.settings.safety_limits import PS_CURRENT_CEILING_A
from t8_daq_system.utils.helpers import convert_pressure, convert_temperature

logger = logging.getLogger(__name__)

# Sentinel placed on the queue by stop() to signal the writer thread to exit.
_STOP = object()


@dataclass
class _Event:
    name: str
    detail: str = ""


def build_row(snapshot: Snapshot, t_unit: str, p_unit: str) -> dict:
    """
    Build one CSV data row dict from a Snapshot.

    Pure function: no I/O, no global state, no side effects.  Display-unit
    conversion happens here and only here for the written file; safety and control
    logic always see Celsius and Torr.

    Column order matches build_header() — both must be kept in sync.
    """
    row: dict = {}

    # Thermocouple temperatures (Celsius in Snapshot → display unit)
    for tc_name, val in snapshot.tc_c.items():
        row[tc_name] = (
            convert_temperature(val, "C", t_unit) if val is not None else None
        )

    # Gauge pressures (Torr in Snapshot → display unit)
    for g_name, val in snapshot.pressure_torr.items():
        row[g_name] = (
            convert_pressure(val, "Torr", p_unit) if val is not None else None
        )

    # Power supply
    row["PS_Voltage"] = snapshot.ps_volts
    row["PS_Current"] = snapshot.ps_amps
    row["PS_Voltage_Setpoint"] = snapshot.commanded_volts
    row["PS_CC_Limit"] = PS_CURRENT_CEILING_A

    # Block index (1-based) and scheduler diagnostics
    prog = snapshot.program
    if prog.running:
        row["Block_Index"] = prog.block_index + 1
        row["Sched_Kp"] = prog.sched_kp
        row["Sched_Ki"] = prog.sched_ki
        row["Sched_Kd"] = prog.sched_kd
        row["Sched_Zone"] = prog.sched_zone
        row["FF_Voltage"] = prog.ff_voltage
        row["PID_Correction"] = prog.pid_correction
    else:
        row["Block_Index"] = None
        row["Sched_Kp"] = None
        row["Sched_Ki"] = None
        row["Sched_Kd"] = None
        row["Sched_Zone"] = None
        row["FF_Voltage"] = None
        row["PID_Correction"] = None

    # Raw TC voltages (one column per TC, same order as TC columns)
    for tc_name in snapshot.tc_c:
        row[f"{tc_name}_rawV"] = snapshot.tc_raw_v.get(tc_name)

    # Heater state and trip reason (new columns appended at end)
    row["Heater_State"] = snapshot.heater.state
    row["Trip_Reason"] = snapshot.heater.trip_reason

    return row


def build_header(
    tc_names: Sequence[str],
    gauge_names: Sequence[str],
    has_ps: bool = True,
) -> list[str]:
    """
    Return the sensor column names (without Timestamp) in canonical order.

    Pass the result to DataLogger.start_logging(sensor_names=...).
    The full CSV header is ['Timestamp'] + build_header(...).

    The first len(result) - 2 entries are identical to the ticket-01 pinned
    header for the same configuration; Heater_State and Trip_Reason are appended.
    """
    names: list[str] = list(tc_names)
    names += list(gauge_names)
    if has_ps:
        names += ["PS_Voltage", "PS_Current", "PS_Voltage_Setpoint", "PS_CC_Limit"]
    names += ["Block_Index"]
    names += ["Sched_Kp", "Sched_Ki", "Sched_Kd", "Sched_Zone", "FF_Voltage", "PID_Correction"]
    names += [f"{tc}_rawV" for tc in tc_names]
    names += ["Heater_State", "Trip_Reason"]
    return names


class RunRecord:
    """
    Step-7 consumer for the Rig loop: turns Snapshots and events into CSV rows.

    Usage:
        sensor_names = build_header(tc_names, gauge_names)
        logger.start_logging(sensor_names, ...)
        rr = RunRecord(logger, tc_names, gauge_names, t_unit, p_unit, sample_rate_ms)
        rig.set_run_record(rr)
        rr.start()
        ...
        rr.stop()          # flushes queue, joins writer thread
        logger.stop_logging()

    The writer thread is sentinel-driven: stop() enqueues _STOP, which causes
    the thread to exit after draining all previously queued items.  No sleep.
    """

    def __init__(
        self,
        logger_: DataLogger,
        tc_names: Sequence[str],
        gauge_names: Sequence[str],
        t_unit: str,
        p_unit: str,
        sample_rate_ms: float,
        has_ps: bool = True,
    ) -> None:
        self._logger = logger_
        self._tc_names = list(tc_names)
        self._gauge_names = list(gauge_names)
        self._t_unit = t_unit
        self._p_unit = p_unit
        self._sample_rate_s = sample_rate_ms / 1000.0
        self._has_ps = has_ps

        self._queue: queue.Queue[object] = queue.Queue()
        self._thread: threading.Thread | None = None
        # Initialise to -infinity so the very first snapshot is always written.
        self._last_written_t: float = float("-inf")

    # ── Public interface ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background writer thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("RunRecord.start() called while writer thread is already running")
            return
        self._thread = threading.Thread(
            target=self._writer_loop,
            name="RunRecord-Writer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """
        Signal the writer thread to exit, flush all queued items, and join.

        Returns only after the thread has written every item that was enqueued
        before this call.  Never sleeps.
        """
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def put_snapshot(self, snapshot: Snapshot) -> None:
        """Enqueue a Snapshot for possible data-row write (throttled by sample_rate_ms)."""
        self._queue.put(snapshot)

    def put_event(self, name: str, detail: str = "") -> None:
        """Enqueue an event row to be written immediately (not throttled)."""
        self._queue.put(_Event(name=name, detail=detail))

    # ── Writer loop ────────────────────────────────────────────────────────────

    def _writer_loop(self) -> None:
        """
        Drain the queue until _STOP is received.

        All items enqueued before _STOP are processed (FIFO).  Sentinel-based
        stop guarantees flush without any time.sleep.
        """
        while True:
            item = self._queue.get()
            if item is _STOP:
                break
            self._process_item(item)

    def _process_item(self, item: object) -> None:
        if isinstance(item, _Event):
            self._logger.log_event(item.name, item.detail)
        elif isinstance(item, Snapshot):
            elapsed = item.t - self._last_written_t
            if elapsed >= self._sample_rate_s:
                row = build_row(item, self._t_unit, self._p_unit)
                ts = datetime.fromtimestamp(item.wall_time).isoformat()
                self._logger.log_reading(row, timestamp=ts)
                self._last_written_t = item.t
        else:
            logger.warning("RunRecord: unknown queue item type %s", type(item))

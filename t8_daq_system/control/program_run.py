"""
t8_daq_system/control/program_run.py

Pure block-execution engine that runs inside the Rig control step.

WHY THIS EXISTS
---------------
ProgramExecutor ran its own background thread with time.sleep(0.5) and direct
hardware writes, making it impossible to test control math faster than real-time
and violating ADR 0002 (one Rig loop owns hardware I/O).

ProgramRun replaces that thread with a pure step() method called by the Rig on
every control tick.  It advances blocks using the pure block-step functions from
block_steps.py, returns a ProgramHeaterRequest for HeaterOutput to arbitrate, and
returns a Trip if a block step raises.  No I/O, no clock reads, no sleep.

TIMING MODEL (two-tick warm-up)
---------------------------------
ProgramExecutor consumed two fake_time() calls before its first while-loop tick,
yielding elapsed=0.5 at the first real step.  ProgramRun replicates this via a
two-phase just-started mechanism:

  Phase 2 (first step() call after start or block transition): no-op, return None.
  Phase 1 (second step() call): record block_start_time_s = now_s, set up
      StepContext and PID bumpless transfer, return None.
  Phase 0: compute real step; elapsed = now_s - block_start_time_s = 0.5.

This produces identical per-tick voltage literals to the old executor (AC 5,
ticket rig-architecture-10).
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

import t8_daq_system.control.block_steps as _block_steps
from t8_daq_system.control.block_steps import (
    SchedValues,
    StepContext,
    c_to_k,
)
from t8_daq_system.control.feedforward_map import FeedforwardMap
from t8_daq_system.control.heater_output import ProgramHeaterRequest
from t8_daq_system.control.safety_monitor import Trip
from t8_daq_system.control.temp_ramp_pid import PIDController, PIDRunLogger
from t8_daq_system.rig.snapshot import ProgramStatus, Snapshot

logger = logging.getLogger(__name__)


class ProgramRun:
    """
    Block-execution engine for the Rig control loop (ADRs 0002, 0003).

    Owns: block list and index, block-start time and temperature,
    per-block gain resolution, bumpless PID transfer, the FIX-2 two-second
    completion guard, run history saving, and QMS confirmation pause.

    Driven by:
      load(blocks)          — called when LoadProgram is drained
      start(snap, now_s)    — called when StartProgram is drained
      stop()                — called on StopProgram or when HeaterOutput stops program
      confirm_continue()    — called when ConfirmContinue is drained
      step(snap, now_s)     — called by Rig on every control tick while running;
                              returns ProgramHeaterRequest, Trip, or None
    """

    def __init__(self) -> None:
        self._blocks: list[Any] = []
        self._running: bool = False
        self._block_index: int = 0

        self._pid: PIDController | None = None
        self._ff_map = FeedforwardMap()
        self._ff_map.load()
        self._pid_logger = PIDRunLogger()

        # Two-tick warm-up state (see module docstring)
        self._just_started_phase: int = 0  # 2 -> 1 -> 0

        self._block_start_time_s: float = 0.0
        self._ctx: StepContext | None = None
        self._last_step_volts: float = 0.0
        self._block_rate_k_per_min: float = 0.0

        # QMS confirmation gate
        self._waiting_for_confirmation: bool = False
        self._confirmation_ready: bool = False

        # Per-tick diagnostics exposed in ProgramStatus
        self._sched: SchedValues = SchedValues()
        self._setpoint_k: float = 0.0
        self._elapsed_s: float = 0.0

        # TempRamp run history for feedforward learning
        self._run_log: list[tuple[float, float, float, float]] = []
        self._last_run_record: dict[str, Any] | None = None

        # Events accumulated between take_events() calls.
        # The Rig reads these after each step() and relays them to RunRecord.
        self._pending_events: list[tuple[str, str]] = []

    def get_pid_logger(self) -> PIDRunLogger:
        """Return the PIDRunLogger instance."""
        return self._pid_logger

    def compute_preview(
        self,
        blocks: list[Any],
        start_temp_k: float = 293.15,
        start_voltage: float = 0.0,
    ) -> tuple[list[float], list[float], list[float], list[float]]:
        """Compute expected voltage/temperature profile for given blocks."""
        return compute_preview(blocks, start_temp_k=start_temp_k, start_voltage=start_voltage)

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        """True while a program is executing."""
        return self._running

    def load(self, blocks: list[Any]) -> None:
        """Load a block sequence.  Safe to call at any time; takes effect on next start()."""
        self._blocks = list(blocks)

    def start(self, snapshot: Snapshot, now_s: float, *, commanded_volts: float = 0.0, settings: Any = None) -> None:
        """
        Begin execution from block 0.

        commanded_volts is the last voltage sent to the adapter — used to seed
        bumpless PID transfer at the first closed-loop block.
        """
        if not self._blocks:
            logger.warning("ProgramRun.start() called with no blocks loaded")
            return
        if self._running:
            logger.debug("ProgramRun.start() ignored: already running")
            return

        self._running = True
        self._block_index = 0
        self._just_started_phase = 2
        self._last_step_volts = commanded_volts

        if settings is not None:
            self._pid = PIDController(
                kp=settings.kp,
                ki=settings.ki,
                kd=settings.kd,
                integral_windup_limit=settings.windup_limit
            )
        else:
            self._pid = PIDController(kp=0.014, ki=0.00078, kd=0.00845) # fallback if called directly in tests without settings

        self._pid.reset()
        self._sched = SchedValues()
        self._setpoint_k = 0.0
        self._elapsed_s = 0.0
        self._waiting_for_confirmation = False
        self._confirmation_ready = False
        self._run_log = []

    def stop(self) -> None:
        """Stop execution immediately (called on StopProgram or trip)."""
        self._running = False

    def confirm_continue(self) -> None:
        """Release a QMS confirmation pause (called on ConfirmContinue)."""
        self._confirmation_ready = True

    def take_events(self) -> list[tuple[str, str]]:
        """
        Return and clear all pending (event_name, detail) pairs.

        Called by the Rig after each step() to relay BLOCK_START,
        PROGRAM_COMPLETE, and RAMP_START events to RunRecord.
        """
        events = self._pending_events
        self._pending_events = []
        return events

    # ------------------------------------------------------------------
    # Step function — called by Rig on every control tick
    # ------------------------------------------------------------------

    def step(self, snapshot: Snapshot, now_s: float) -> ProgramHeaterRequest | Trip | None:
        """
        Advance the program by one control tick.

        Returns:
          ProgramHeaterRequest  — voltage request for HeaterOutput
          Trip                  — program_error trip (block step raised)
          None                  — nothing to write this tick (warm-up, transition,
                                  QMS pause, or finished)
        """
        if not self._running:
            return None

        # QMS confirmation pause: hold until operator releases
        if self._waiting_for_confirmation:
            if self._confirmation_ready:
                self._waiting_for_confirmation = False
                self._confirmation_ready = False
                self._block_index += 1
                self._just_started_phase = 2
            else:
                return None

        block = self._blocks[self._block_index]

        # ---- Phase 2: first tick after start/transition — no-op ----
        if self._just_started_phase == 2:
            self._just_started_phase = 1
            return None

        # ---- Phase 1: second tick — set up context and bumpless ----
        if self._just_started_phase == 1:
            self._block_start_time_s = now_s
            self._ctx = self._setup_block(block, snapshot, now_s)
            self._just_started_phase = 0
            return None

        # ---- Phase 0: real computation tick ----
        elapsed_s = now_s - self._block_start_time_s
        self._elapsed_s = elapsed_s
        temp_k = self._read_temp_k(block, snapshot)

        try:
            res = self._call_step(block, temp_k, elapsed_s, now_s)
        except Exception as exc:
            self._running = False
            reason = f"{type(exc).__name__}: {exc}"
            logger.error("ProgramRun block step raised: %s", reason)
            return Trip(kind="program_error", reason=reason)

        self._last_step_volts = res.volts
        self._sched = res.sched
        self._setpoint_k = res.setpoint_k

        # Track run log for TempRamp history
        if block.block_type == "temp_ramp":
            self._run_log.append((elapsed_s, res.setpoint_k, temp_k, res.volts))

        if res.finished:
            self._on_block_finished(block, elapsed_s, temp_k)
            return None

        return ProgramHeaterRequest(volts=res.volts)

    # ------------------------------------------------------------------
    # Status property for Snapshot.program
    # ------------------------------------------------------------------

    @property
    def status(self) -> ProgramStatus:
        """Current ProgramStatus for embedding in a Snapshot."""
        if not self._running and self._block_index >= len(self._blocks):
            return ProgramStatus()

        block_index = min(self._block_index, max(0, len(self._blocks) - 1))
        block = self._blocks[block_index] if self._blocks else None
        block_type = getattr(block, "block_type", "") if block else ""
        control_tc = self._get_control_tc()

        gains_in_use = (self._pid._kp, self._pid._ki, self._pid._kd) if self._pid else (0.0, 0.0, 0.0)

        return ProgramStatus(
            running=self._running,
            block_index=block_index,
            block_type=block_type,
            waiting_for_confirmation=self._waiting_for_confirmation,
            elapsed_in_block=self._elapsed_s,
            setpoint_k=self._setpoint_k,
            gains_in_use=gains_in_use,
            sched_kp=self._sched.kp,
            sched_ki=self._sched.ki,
            sched_kd=self._sched.kd,
            sched_zone=str(self._sched.zone),
            ff_voltage=self._sched.ff_voltage,
            pid_correction=self._sched.pid_correction,
            control_tc=control_tc,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _setup_block(self, block: Any, snapshot: Snapshot, now_s: float) -> StepContext:
        """Resolve per-block gain/rate, build StepContext, apply bumpless PID."""
        # Emit BLOCK_START and RAMP_START events for the Run record.
        block_type = getattr(block, "block_type", "")
        self._pending_events.append(
            (f"BLOCK_START {self._block_index} {block_type}", "")
        )
        if block_type in ("temp_ramp", "voltage_ramp"):
            self._pending_events.append(("RAMP_START", ""))

        # Per-block feedforward rate (mirrors ProgramExecutor._resolve_block_control)
        if block.block_type == "temp_ramp":
            self._block_rate_k_per_min = getattr(block, "rate_k_per_min", 0.0)
        else:
            self._block_rate_k_per_min = 0.0

        # Start temperature from snapshot for TempRamp setpoint calculation
        start_temp_k = self._read_temp_k(block, snapshot)

        # Bumpless PID transfer for closed-loop blocks
        if block.block_type in ("temp_ramp", "stable_hold"):
            self._pid.reset_bumpless(self._last_step_volts, now_s)

        # Reset TempRamp run log
        if block.block_type == "temp_ramp":
            self._run_log = []

        return StepContext(
            pid=self._pid,
            ff_map=self._ff_map,
            start_temp_k=start_temp_k,
            rate_k_per_min=self._block_rate_k_per_min,
        )

    def _call_step(self, block: Any, temp_k: float, elapsed_s: float, now_s: float):
        """Dispatch to the correct pure block-step function.

        Uses module-attribute lookup (_block_steps.step_xxx) so that test
        monkeypatching of block_steps.step_voltage_ramp is honoured.
        """
        if block.block_type == "voltage_ramp":
            return _block_steps.step_voltage_ramp(block, temp_k, elapsed_s, now_s, self._ctx)
        if block.block_type == "stable_hold":
            return _block_steps.step_stable_hold(block, temp_k, elapsed_s, now_s, self._ctx)
        if block.block_type == "temp_ramp":
            return _block_steps.step_temp_ramp(block, temp_k, elapsed_s, now_s, self._ctx)
        raise ValueError(f"Unknown block type: {block.block_type!r}")

    def _on_block_finished(self, block: Any, elapsed_s: float, temp_k: float) -> None:
        """Handle block completion: save history, check QMS gate, advance index."""
        if block.block_type == "temp_ramp" and elapsed_s > 0 and self._ctx is not None:
            achieved_rate = (temp_k - self._ctx.start_temp_k) / (elapsed_s / 60.0)
            overshoot_k = max(
                (e[2] - e[1] for e in self._run_log),
                default=0.0,
            )
            self._save_run_to_history(
                block.rate_k_per_min, achieved_rate, overshoot_k, elapsed_s
            )

        next_idx = self._block_index + 1

        # QMS confirmation gate: StableHold with qms_trigger before a TempRamp
        if (
            getattr(block, "qms_trigger", False)
            and next_idx < len(self._blocks)
            and self._blocks[next_idx].block_type == "temp_ramp"
        ):
            self._waiting_for_confirmation = True
            logger.info(
                "ProgramRun: waiting for QMS confirmation before block %d", next_idx
            )
            return  # Don't advance yet; wait for confirm_continue()

        if next_idx >= len(self._blocks):
            # All blocks complete — program ends
            self._running = False
            self._pending_events.append(("PROGRAM_COMPLETE", ""))
            logger.info("ProgramRun: program complete after block %d", self._block_index)
        else:
            # Advance to next block
            self._block_index = next_idx
            self._just_started_phase = 2

    def _read_temp_k(self, block: Any, snapshot: Snapshot) -> float:
        """Read temperature in Kelvin from the snapshot for the given block."""
        tc_name = getattr(block, "tc_name", None)
        if tc_name is None:
            tc_name = self._get_control_tc()
        temp_c = snapshot.tc_c.get(tc_name) if snapshot.tc_c else None
        if temp_c is None and snapshot.tc_c:
            # Fallback to any available TC
            temp_c = next(iter(v for v in snapshot.tc_c.values() if v is not None), None)
        return c_to_k(temp_c) if temp_c is not None else 293.15

    def _get_control_tc(self) -> str:
        """Return the TC name for the current or any temp-measuring block."""
        if self._block_index < len(self._blocks):
            tc = getattr(self._blocks[self._block_index], "tc_name", None)
            if tc:
                return tc
        for block in self._blocks:
            tc = getattr(block, "tc_name", None)
            if tc:
                return tc
        return "TC_1"

    def _save_run_to_history(
        self,
        target_rate: float,
        achieved_rate: float,
        overshoot_k: float,
        elapsed_span: float,
    ) -> None:
        """Compute settling/oscillation metrics and save to PIDRunLogger + FeedforwardMap."""
        SETTLE_BAND_K = 2.0
        SETTLE_MIN_TICKS = 10
        settling_time_sec = None
        consecutive = 0
        for entry in self._run_log:
            t, sp, actual, _ = entry
            if abs(actual - sp) <= SETTLE_BAND_K:
                consecutive += 1
                if consecutive >= SETTLE_MIN_TICKS and settling_time_sec is None:
                    settling_time_sec = t
            else:
                consecutive = 0

        errors = [e[2] - e[1] for e in self._run_log]
        oscillation_count = sum(
            1 for i in range(1, len(errors)) if errors[i - 1] * errors[i] < 0
        )

        record = {
            "timestamp": datetime.datetime.now().isoformat(),
            "target_rate_k_per_min": target_rate,
            "achieved_mean_rate_k_per_min": achieved_rate,
            "overshoot_k": overshoot_k,
            "settling_time_sec": settling_time_sec,
            "oscillation_count": oscillation_count,
            "duration_sec": elapsed_span,
            "kp_used": self._pid._kp,
            "ki_used": self._pid._ki,
            "kd_used": self._pid._kd,
        }
        self._last_run_record = record
        try:
            self._pid_logger.save_run(record)
        except Exception as exc:
            logger.warning("ProgramRun: failed to save PID run record: %s", exc)

        try:
            self._ff_map.append_run(self._run_log, target_rate)
        except Exception as exc:
            logger.warning("ProgramRun: feedforward map append_run failed: %s", exc)


def compute_preview(
    blocks: list[Any],
    start_temp_k: float = 293.15,
    start_voltage: float = 0.0,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """
    Compute the expected voltage and temperature profile for the given blocks.

    Returns:
        (times, voltages, temps_k, block_boundaries)
    """
    times = [0.0]
    voltages = [start_voltage]
    temps_k = [start_temp_k]
    boundaries = [0.0]

    current_time = 0.0
    current_v = start_voltage
    current_t = start_temp_k

    for block in blocks:
        if block.block_type == "voltage_ramp":
            dur = block.duration_sec
            steps = max(1, int(dur))
            v_start = block.start_voltage
            v_end = block.end_voltage
            for i in range(1, steps + 1):
                t = current_time + i
                p = i / steps
                v = v_start + (v_end - v_start) * p
                times.append(t)
                voltages.append(v)
                temps_k.append(current_t)
            current_time += steps
            current_v = v_end

        elif block.block_type == "stable_hold":
            dur = block.hold_duration_sec
            steps = max(1, int(dur))
            for i in range(1, steps + 1):
                times.append(current_time + i)
                voltages.append(current_v)
                temps_k.append(block.target_temp_k)
            current_time += steps
            current_t = block.target_temp_k

        elif block.block_type == "temp_ramp":
            rate_k_per_sec = abs(block.rate_k_per_min / 60.0)
            if rate_k_per_sec > 0:
                dur = abs(block.end_temp_k - current_t) / rate_k_per_sec
            else:
                dur = 0

            steps = max(1, int(dur))
            t_start = current_t
            t_end = block.end_temp_k
            for i in range(1, steps + 1):
                t = current_time + i
                p = i / steps
                temp = t_start + (t_end - t_start) * p
                times.append(t)
                voltages.append(current_v)
                temps_k.append(temp)
            current_time += steps
            current_t = t_end

        boundaries.append(current_time)

    return times, voltages, temps_k, boundaries

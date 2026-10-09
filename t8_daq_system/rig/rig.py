"""
Rig module — single owner of hardware communication, timing loop, and Snapshot publication.

WHY THIS EXISTS
---------------
Previously, four separate threads (GUI, DAQ, executor, and safety thread) performed
hardware I/O independently with no owner or synchronization. This caused UI lockups
during reconnects, race conditions between PID voltage writes and safety shutdowns,
and discrepancies between on-screen readings and recorded CSV logs.

The Rig module owns the hardware adapter on a single thread running a single loop:
drain commands -> reconnect safely -> read -> publish immutable Snapshot -> safety
-> control step & heater output -> hand Snapshot to Run record (ADRs 0002, 0003).
"""
from __future__ import annotations

from dataclasses import replace
import logging
import queue
import threading
from typing import TYPE_CHECKING, Any, Callable, Sequence

if TYPE_CHECKING:
    from t8_daq_system.control.heater_output import HeaterOutput
    from t8_daq_system.control.program_run import ProgramRun
    from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.rig.adapter import AdapterError, RawReadings, RigAdapter
from t8_daq_system.rig.clock import Clock
from t8_daq_system.rig.commands import (
    ConfirmContinue,
    LoadProgram,
    Nudge,
    ResetTrip,
    SelectAdapter,
    SetOutput,
    SetVoltage,
    StartProgram,
    StopProgram,
    UpdateConfig,
)
from t8_daq_system.rig.simulated import SimulatedRig
from t8_daq_system.rig.snapshot import (
    HeaterStatus,
    ProgramStatus,
    Snapshot,
    SourceStatus,
)
from t8_daq_system.settings.safety_limits import (
    CONTROL_PERIOD_S,
    RECONNECT_INTERVAL_S,
)

logger = logging.getLogger(__name__)


class Rig:
    """
    Central Rig orchestrator.

    Owns the active RigAdapter and runs the single hardware I/O loop.
    All external consumers interact via commands (put into the command queue)
    and by reading the latest immutable Snapshot published each tick.
    """

    def __init__(
        self,
        adapter: RigAdapter,
        clock: Clock,
        sample_rate_ms: float = 1000.0,
        snapshot_consumer: queue.Queue[Snapshot] | Callable[[Snapshot], None] | None = None,
        practice_adapter: RigAdapter | None = None,
        hardware_adapter: RigAdapter | None = None,
        tc_names: Sequence[str] | None = None,
        gauge_names: Sequence[str] | None = None,
        heater_output: HeaterOutput | None = None,
        safety_evaluator: SafetyEvaluator | None = None,
        program_executor: Any | None = None,
        program_run: ProgramRun | None = None,
    ) -> None:
        self._adapter = adapter
        self._clock = clock
        self._sample_rate_ms = float(sample_rate_ms)
        self._snapshot_consumer = snapshot_consumer
        self._practice_adapter = practice_adapter or (
            adapter if isinstance(adapter, SimulatedRig) else None
        )
        self._hardware_adapter = hardware_adapter or (
            adapter if not isinstance(adapter, SimulatedRig) else None
        )
        if heater_output is not None:
            self._heater_output = heater_output
        else:
            from t8_daq_system.control.heater_output import HeaterOutput

            self._heater_output = HeaterOutput()

        if safety_evaluator is not None:
            self._safety_evaluator = safety_evaluator
        else:
            from t8_daq_system.control.safety_monitor import SafetyEvaluator

            self._safety_evaluator = SafetyEvaluator()

        self._program_executor = program_executor
        self._program_run = program_run

        if tc_names is not None:
            self._tc_names = list(tc_names)
        elif hasattr(adapter, "_tc_names"):
            self._tc_names = list(getattr(adapter, "_tc_names"))
        else:
            self._tc_names = ["TC_1"]

        if gauge_names is not None:
            self._gauge_names = list(gauge_names)
        elif hasattr(adapter, "_gauge_names"):
            self._gauge_names = list(getattr(adapter, "_gauge_names"))
        else:
            self._gauge_names = ["FRG702_Chamber"]

        self._command_queue: queue.Queue[Any] = queue.Queue()
        self._latest: Snapshot | None = None
        self._latest_lock = threading.Lock()

        # Lifecycle & state flags
        self._logging_active: bool = False
        self._program_status = ProgramStatus()
        self._heater_status = HeaterStatus(state="off")
        self._commanded_volts: float = 0.0
        self._output_enabled: bool = False
        self._shutoff_unverified: bool = False

        self._adapter_connected: bool = adapter.is_connected()
        self._labjack_status = SourceStatus(
            state="connected" if self._adapter_connected else "lost"
        )
        self._xgs_status = SourceStatus(state="connected")

        # Staleness & reconnect timers
        self._start_time: float = clock.now()
        self._last_reconnect_attempt: float = -float("inf")
        self._last_valid_time: dict[str, float] = {}
        self._last_control_step: float = -float("inf")

        self._trip_kind: str | None = None
        self._trip_reason: str | None = None
        self._adapter_refusal_reason: str | None = None
        self._command_rejected_reason: str | None = None

        self._stop_requested: bool = False
        self._thread: threading.Thread | None = None

        # Run record: step-7 consumer for CSV logging (set via set_run_record)
        self._run_record: Any | None = None
        # Track which trip kind has already been emitted to avoid duplicate events
        self._last_emitted_trip_kind: str | None = None

    # --- Properties & public methods ---

    @property
    def heater_output(self) -> HeaterOutput:
        """The HeaterOutput instance arbitrating requests and latching trips."""
        return self._heater_output

    @property
    def safety_evaluator(self) -> SafetyEvaluator:
        """The pure SafetyEvaluator evaluating Snapshots."""
        return self._safety_evaluator

    def set_program_executor(self, executor: Any) -> None:
        """Set the ProgramExecutor to be stopped on trip."""
        self._program_executor = executor

    @property
    def tick_period_s(self) -> float:
        """Tick period in seconds: min(sample_rate_ms / 1000, CONTROL_PERIOD_S)."""
        return min(self._sample_rate_ms / 1000.0, CONTROL_PERIOD_S)

    @property
    def logging_active(self) -> bool:
        """True if CSV logging is currently active."""
        return self._logging_active

    @logging_active.setter
    def logging_active(self, active: bool) -> None:
        self._logging_active = bool(active)

    def set_logging_active(self, active: bool) -> None:
        """Set whether CSV logging is active."""
        self._logging_active = bool(active)


    def get_ff_map(self) -> Any:
        if self._program_run is not None:
            return getattr(self._program_run, '_ff_map', None)
        return None

    def get_pid_logger(self) -> Any:
        if self._program_run is not None:
            return self._program_run.get_pid_logger()
        return None

    def get_last_run_record(self) -> dict | None:
        if self._program_run is not None:
            return getattr(self._program_run, '_last_run_record', None)
        return None

    def set_run_record(self, run_record: Any) -> None:
        """Attach a RunRecord as the step-7 Snapshot consumer for CSV logging."""
        self._run_record = run_record
        if run_record is not None:
            adapter_name = "simulated" if isinstance(self._adapter, SimulatedRig) else "t8"
            self._run_record.put_event(f"ADAPTER {adapter_name}")

    def clear_run_record(self) -> None:
        """Detach the RunRecord; no more snapshots will be forwarded."""
        self._run_record = None

    def submit_command(self, cmd: Any) -> None:
        """Submit a command to the Rig command queue."""
        self._command_queue.put(cmd)

    def submit(self, cmd: Any) -> None:
        """Convenience alias for submit_command."""
        self.submit_command(cmd)

    def latest(self) -> Snapshot | None:
        """Return the most recently published Snapshot (thread-safe)."""
        with self._latest_lock:
            return self._latest

    def start(self) -> None:
        """Start the background Rig loop thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_requested = False
        self._thread = threading.Thread(target=self._loop, name="RigThread", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the Rig loop thread to stop and wait for termination."""
        self._stop_requested = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    # --- Single Rig Loop pass ---

    def run_tick(self) -> None:
        """
        Execute a single pass of the Rig loop in spec order.

        Steps:
        1. Drain command queue
        2. Reconnect if disconnected (at most every RECONNECT_INTERVAL_S)
        3. Read from adapter
        4. Calculate staleness and publish Snapshot
        5. Safety evaluation
        6. Control step & Heater output write
        7. Hand Snapshot to consumer queue
        """
        now = self._clock.now()

        # ---------------------------------------------------------
        # Step 1: Drain command queue
        # ---------------------------------------------------------
        self._adapter_refusal_reason = None
        self._command_rejected_reason = None
        drained_heater_cmds: list[Any] = []

        while not self._command_queue.empty():
            try:
                cmd = self._command_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(cmd, (ResetTrip, SetOutput, SetVoltage, Nudge, StartProgram, StopProgram)):
                drained_heater_cmds.append(cmd)
            elif isinstance(cmd, (LoadProgram, ConfirmContinue)):
                self._handle_command(cmd)
            else:
                self._handle_command(cmd)

        # ---------------------------------------------------------
        # Step 2: Reconnection
        # ---------------------------------------------------------
        if not self._adapter_connected or not self._adapter.is_connected():
            if self._adapter_connected:
                # Connection loss just noticed
                self._adapter_connected = False
                self._last_reconnect_attempt = now

            self._labjack_status = SourceStatus(state="lost", message="Disconnected")

            if (now - self._last_reconnect_attempt) >= RECONNECT_INTERVAL_S:
                self._last_reconnect_attempt = now
                try:
                    connected = self._adapter.connect()
                except AdapterError as err:
                    logger.warning("Adapter reconnection failed: %s", err)
                    connected = False

                if connected:
                    try:
                        # Safety invariant (ADR 0002/0003):
                        # First three calls MUST be: off, 0 V, pin current limit
                        self._adapter.set_output(False)
                        self._adapter.write_voltage(0.0)
                        self._adapter.pin_current_limit()
                        self._adapter_connected = True
                        self._labjack_status = SourceStatus(state="connected", message="OK")
                        self._shutoff_unverified = False
                    except AdapterError as err:
                        logger.error("Failed to initialize adapter after connect: %s", err)
                        self._adapter_connected = False
                        self._labjack_status = SourceStatus(state="lost", message=str(err))
                        self._shutoff_unverified = True

        # ---------------------------------------------------------
        # Step 3: Read
        # ---------------------------------------------------------
        read_failed = False
        readings: RawReadings | None = None

        if not self._adapter_connected:
            read_failed = True
        else:
            try:
                readings = self._adapter.read()
            except AdapterError as err:
                read_failed = True
                self._adapter_connected = False
                self._last_reconnect_attempt = now
                self._labjack_status = SourceStatus(state="lost", message=str(err))

        # ---------------------------------------------------------
        # Step 4: Staleness + interim Snapshot
        # ---------------------------------------------------------
        source_age_s: dict[str, float] = {}
        tc_c: dict[str, float | None] = {}
        tc_raw_v: dict[str, float | None] = {}
        pressure_torr: dict[str, float | None] = {}

        if readings is not None:
            # Thermocouple readings & staleness
            for tc in self._tc_names:
                t_val = readings.tc_c.get(tc)
                tc_c[tc] = t_val
                tc_raw_v[tc] = readings.tc_raw_v.get(tc)
                if t_val is not None:
                    self._last_valid_time[tc] = now
                    source_age_s[tc] = 0.0
                else:
                    last_t = self._last_valid_time.get(tc)
                    source_age_s[tc] = (
                        (now - last_t) if last_t is not None else (now - self._start_time)
                    )

            # Gauge readings & staleness
            for g in self._gauge_names:
                p_val = readings.pressure_torr.get(g)
                p_valid = readings.pressure_valid.get(g, False)
                pressure_torr[g] = p_val
                if p_val is not None and p_valid:
                    self._last_valid_time[g] = now
                    source_age_s[g] = 0.0
                else:
                    last_t = self._last_valid_time.get(g)
                    source_age_s[g] = (
                        (now - last_t) if last_t is not None else (now - self._start_time)
                    )

            ps_volts = readings.ps_volts
            ps_amps = readings.ps_amps
        else:
            for tc in self._tc_names:
                tc_c[tc] = None
                tc_raw_v[tc] = None
                last_t = self._last_valid_time.get(tc)
                source_age_s[tc] = (
                    (now - last_t) if last_t is not None else (now - self._start_time)
                )

            for g in self._gauge_names:
                pressure_torr[g] = None
                last_t = self._last_valid_time.get(g)
                source_age_s[g] = (
                    (now - last_t) if last_t is not None else (now - self._start_time)
                )

            ps_volts = 0.0
            ps_amps = 0.0

        adapter_name = "simulated" if isinstance(self._adapter, SimulatedRig) else "t8"

        current_trip_kind = self._heater_output.active_trip_kind
        current_trip_reason = self._heater_output.active_trip_reason
        current_heater_state = (
            "tripped"
            if self._heater_output.is_latched
            else ("on" if self._output_enabled else "off")
        )
        current_heater_status = HeaterStatus(
            state=current_heater_state,
            trip_kind=current_trip_kind,
            trip_reason=current_trip_reason,
            shutoff_unverified=self._shutoff_unverified,
        )

        snap_interim = Snapshot(
            t=now,
            wall_time=self._clock.wall_time(),
            tc_c=tc_c,
            tc_raw_v=tc_raw_v,
            pressure_torr=pressure_torr,
            source_age_s=source_age_s,
            ps_volts=ps_volts,
            ps_amps=ps_amps,
            commanded_volts=self._commanded_volts,
            output_enabled=self._output_enabled,
            labjack=self._labjack_status,
            xgs=self._xgs_status,
            heater=current_heater_status,
            program=self._program_status,
            permissive_ok=False,
            permissive_reason=None,
            adapter=adapter_name,
            adapter_refusal_reason=self._adapter_refusal_reason,
            command_rejected_reason=self._adapter_refusal_reason,
        )

        # ---------------------------------------------------------
        # Step 5: Safety evaluation (pure function)
        # ---------------------------------------------------------
        from t8_daq_system.control.safety_monitor import Trip

        eval_result = self._safety_evaluator.evaluate(snap_interim)
        trips = list(eval_result.trips)

        if not self._adapter_connected or read_failed:
            trips.insert(
                0,
                Trip(
                    kind="labjack_lost",
                    reason=self._labjack_status.message or "LabJack communication lost",
                ),
            )

        # Update interim snapshot with actual permissive from evaluator
        snap_for_heater = replace(
            snap_interim,
            permissive_ok=eval_result.permissive_ok,
            permissive_reason=eval_result.permissive_reason,
        )

        # ---------------------------------------------------------
        # Step 6: Control step & Heater output resolution
        # ---------------------------------------------------------
        is_control_step = (now - self._last_control_step) >= (CONTROL_PERIOD_S - 1e-9)
        new_trip_appeared = bool(trips)
        should_resolve = new_trip_appeared or bool(drained_heater_cmds) or is_control_step

        if should_resolve:
            if is_control_step:
                self._last_control_step = now

            # ProgramRun lifecycle: start/stop from drained commands
            if self._program_run is not None:
                has_stop = any(isinstance(c, StopProgram) for c in drained_heater_cmds)
                start_cmd = next((c for c in drained_heater_cmds if isinstance(c, StartProgram)), None)
                if has_stop:
                    self._program_run.stop()
                if start_cmd and not self._program_run.running:
                    self._program_run.start(
                        snap_for_heater, now, commanded_volts=self._commanded_volts, settings=start_cmd.settings
                    )

            # ProgramRun step: get voltage request or program_error trip
            _pr_was_running = (
                self._program_run is not None and self._program_run.running
            )
            if is_control_step and self._program_run is not None and self._program_run.running:
                from t8_daq_system.control.safety_monitor import Trip as _Trip
                pr_result = self._program_run.step(snap_for_heater, now)
                if isinstance(pr_result, _Trip):
                    trips = list(trips) + [pr_result]
                    new_trip_appeared = True
                elif pr_result is not None:
                    drained_heater_cmds = list(drained_heater_cmds) + [pr_result]

            # Relay ProgramRun events to RunRecord (BLOCK_START, PROGRAM_COMPLETE, etc.)
            if self._run_record is not None and self._program_run is not None:
                for evt_name, evt_detail in self._program_run.take_events():
                    self._run_record.put_event(evt_name, evt_detail)

            requests = trips + drained_heater_cmds
            _was_latched_before = self._heater_output.is_latched
            _had_reset = any(isinstance(c, ResetTrip) for c in drained_heater_cmds)
            cmd = self._heater_output.resolve(requests, snap_for_heater)

            # Trip or stop_program: halt ProgramRun and legacy ProgramExecutor
            _program_stopped_by_cmd = False
            if self._heater_output.is_latched or cmd.stop_program:
                if self._program_run is not None and self._program_run.running:
                    self._program_run.stop()
                    _program_stopped_by_cmd = True
                if self._program_executor is not None and hasattr(self._program_executor, "stop"):
                    try:
                        self._program_executor.stop()
                    except Exception as err:
                        logger.error("Failed to stop ProgramExecutor on trip: %s", err)

            if cmd.refusal_reason:
                self._command_rejected_reason = cmd.refusal_reason

            # Emit events to RunRecord for trips, resets and program stops
            if self._run_record is not None:
                # New trip: emit TRIP event once per latched kind
                new_trip_kind = cmd.trip_kind
                if (
                    new_trip_kind is not None
                    and new_trip_kind != self._last_emitted_trip_kind
                ):
                    self._run_record.put_event(
                        f"TRIP {new_trip_kind}",
                        cmd.trip_reason or "",
                    )
                    self._last_emitted_trip_kind = new_trip_kind
                # Latch cleared: reset tracking
                if _was_latched_before and not self._heater_output.is_latched:
                    self._last_emitted_trip_kind = None
                    self._run_record.put_event("RESET")
                # Reset refused
                elif (
                    _had_reset
                    and self._heater_output.is_latched
                    and cmd.refusal_reason
                    and "Reset refused" in cmd.refusal_reason
                ):
                    self._run_record.put_event("RESET_REFUSED", cmd.refusal_reason)
                # Program stopped by operator or trip (but not program_complete)
                if _program_stopped_by_cmd and not cmd.trip_kind:
                    self._run_record.put_event("PROGRAM_STOPPED")

            # Adapter writes (through Rig only)
            # Write if state changed, or if a trip appeared this tick
            needs_write = (
                new_trip_appeared
                or (cmd.output_enabled != self._output_enabled)
                or (cmd.volts != self._commanded_volts)
            )

            if needs_write and self._adapter_connected:
                # 1. Output enable (Shut Off pin)
                try:
                    self._adapter.set_output(cmd.output_enabled)
                    if not cmd.output_enabled:
                        self._shutoff_unverified = False
                except AdapterError as err:
                    logger.error("Adapter set_output(%s) failed: %s", cmd.output_enabled, err)
                    if not cmd.output_enabled:
                        self._shutoff_unverified = True
                    self._adapter_connected = False
                    self._labjack_status = SourceStatus(state="lost", message=str(err))
                    self._heater_output.resolve(
                        [Trip(kind="labjack_lost", reason=f"Shut-off write failed: {err}")],
                        snap_for_heater,
                    )
                    if self._program_run is not None:
                        self._program_run.stop()
                    from t8_daq_system.control.heater_output import HeaterCommand
                    cmd = HeaterCommand(output_enabled=False, volts=0.0)

                # 2. Voltage (DAC0)
                try:
                    self._adapter.write_voltage(cmd.volts)
                except AdapterError as err:
                    logger.error("Adapter write_voltage(%s) failed: %s", cmd.volts, err)
                    self._adapter_connected = False
                    self._labjack_status = SourceStatus(state="lost", message=str(err))
                    self._heater_output.resolve(
                        [Trip(kind="labjack_lost", reason=f"Voltage write failed: {err}")],
                        snap_for_heater,
                    )
                    if self._program_run is not None:
                        self._program_run.stop()
                    from t8_daq_system.control.heater_output import HeaterCommand
                    cmd = HeaterCommand(output_enabled=False, volts=0.0)

            self._output_enabled = cmd.output_enabled
            self._commanded_volts = cmd.volts

            # Update program status after control step (reflects current tick)
            if self._program_run is not None:
                self._program_status = self._program_run.status

        # Determine final heater status
        if self._heater_output.is_latched:
            final_heater_state = "tripped"
            final_trip_kind = self._heater_output.active_trip_kind
            final_trip_reason = self._heater_output.active_trip_reason
        else:
            final_heater_state = "on" if self._output_enabled else "off"
            final_trip_kind = None
            final_trip_reason = None

        final_heater_status = HeaterStatus(
            state=final_heater_state,
            trip_kind=final_trip_kind,
            trip_reason=final_trip_reason,
            shutoff_unverified=self._shutoff_unverified,
        )

        final_snap = replace(
            snap_for_heater,
            heater=final_heater_status,
            program=self._program_status,
            output_enabled=self._output_enabled,
            commanded_volts=self._commanded_volts,
            labjack=self._labjack_status,
            command_rejected_reason=self._command_rejected_reason or self._adapter_refusal_reason,
        )

        with self._latest_lock:
            self._latest = final_snap

        # ---------------------------------------------------------
        # Step 7: Hand Snapshot to consumer queue and RunRecord
        # ---------------------------------------------------------
        if self._snapshot_consumer is not None:
            if hasattr(self._snapshot_consumer, "put"):
                self._snapshot_consumer.put(final_snap)
            elif callable(self._snapshot_consumer):
                self._snapshot_consumer(final_snap)

        if self._run_record is not None:
            self._run_record.put_snapshot(final_snap)

    def _handle_command(self, cmd: Any) -> None:
        """Handle a single drained command."""
        if isinstance(cmd, LoadProgram):
            if self._program_run is not None:
                self._program_run.load(cmd.program)
            return

        if isinstance(cmd, ConfirmContinue):
            if self._program_run is not None:
                self._program_run.confirm_continue()
            return

        if isinstance(cmd, SelectAdapter):
            if self._logging_active or self._program_status.running:
                reason = "Cannot change adapter while " + (
                    "logging is active" if self._logging_active else "program is running"
                )
                self._adapter_refusal_reason = reason
                logger.warning("SelectAdapter refused: %s", reason)
            else:
                if cmd.practice:
                    if self._practice_adapter is not None:
                        self._adapter = self._practice_adapter
                else:
                    if self._hardware_adapter is not None:
                        self._adapter = self._hardware_adapter
                self._adapter_connected = self._adapter.is_connected()
                self._labjack_status = SourceStatus(
                    state="connected" if self._adapter_connected else "lost"
                )
                logger.info("SelectAdapter accepted (practice=%s)", cmd.practice)
                adapter_name = "simulated" if cmd.practice else "t8"
                if self._run_record is not None:
                    self._run_record.put_event(f"ADAPTER {adapter_name}")

        elif isinstance(cmd, UpdateConfig):
            if cmd.sample_rate_ms is not None:
                self._sample_rate_ms = float(cmd.sample_rate_ms)
            if cmd.tc_names is not None:
                self._tc_names = list(cmd.tc_names)
            if cmd.gauge_names is not None:
                self._gauge_names = list(cmd.gauge_names)

    def _loop(self) -> None:
        """Daemon thread loop for Rig execution."""
        while not self._stop_requested:
            next_tick = self._clock.now() + self.tick_period_s
            self.run_tick()
            self._clock.sleep_until(next_tick)

"""
Integration tests for Rig loop trips, latching, instant cutoff, and recovery.

WHY THIS EXISTS
---------------
ADR 0003 and ADR 0004 establish that any safety trip must immediately cut the heater
(Shut Off asserted, DAC0 = 0 V) on the exact tick it is detected, latch until an
explicit reset is accepted, and reflect its reason in the Snapshot. No 5-minute
rampdown exists.

These tests prove Ticket 08 end-to-end: real Rig + SimulatedRig + ManualClock +
real HeaterOutput + SafetyEvaluator, driven by tick(n).
"""
import re
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from t8_daq_system.control.heater_output import HeaterOutput
from t8_daq_system.control.safety_monitor import SafetyEvaluator
from t8_daq_system.rig.adapter import RawReadings, RigAdapter
from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.commands import (
    Nudge,
    ResetTrip,
    SetOutput,
    SetVoltage,
)
from t8_daq_system.rig.rig import Rig
from t8_daq_system.rig.simulated import SimulatedRig
from t8_daq_system.settings.safety_limits import RECONNECT_INTERVAL_S


class CallSpyAdapter(RigAdapter):
    """Spy wrapper around RigAdapter to record call sequence and arguments."""

    def __init__(self, target: RigAdapter) -> None:
        self._target = target
        self.calls: list[object] = []

    def connect(self) -> bool:
        self.calls.append("connect")
        return self._target.connect()

    def disconnect(self) -> None:
        self.calls.append("disconnect")
        self._target.disconnect()

    def is_connected(self) -> bool:
        return self._target.is_connected()

    def read(self) -> RawReadings:
        self.calls.append("read")
        return self._target.read()

    def write_voltage(self, volts: float) -> None:
        self.calls.append(("write_voltage", volts))
        self._target.write_voltage(volts)

    def set_output(self, enabled: bool) -> None:
        self.calls.append(("set_output", enabled))
        self._target.set_output(enabled)

    def pin_current_limit(self) -> None:
        self.calls.append("pin_current_limit")
        self._target.pin_current_limit()

    def __getattr__(self, name: str):
        return getattr(self._target, name)


def make_test_rig():
    clock = ManualClock(start_time=100.0)
    sim_rig = SimulatedRig(
        clock=clock,
        tc_names=["TC_1"],
        gauge_names=["FRG702_Chamber"],
    )
    spy = CallSpyAdapter(sim_rig)
    heater_output = HeaterOutput()
    safety_evaluator = SafetyEvaluator(limits={"TC_1": 1200.0})
    rig = Rig(
        adapter=spy,
        clock=clock,
        tc_names=["TC_1"],
        gauge_names=["FRG702_Chamber"],
        heater_output=heater_output,
        safety_evaluator=safety_evaluator,
    )
    return clock, sim_rig, spy, heater_output, safety_evaluator, rig


def test_pressure_above_threshold_trips_pressure_high_and_cuts_heater_same_tick():
    """set_pressure above threshold -> pressure_high trip; adapter receives set_output(False) and write_voltage(0.0) same tick."""
    clock, sim_rig, spy, heater_out, evaluator, rig = make_test_rig()

    # Initial tick to publish baseline snapshot
    rig.run_tick()
    assert rig.latest().heater.state == "off"

    # Energise output via Rig commands
    rig.submit(SetOutput(enabled=True))
    rig.submit(SetVoltage(volts=2.0))
    clock.advance(0.5)
    rig.run_tick()

    snap = rig.latest()
    assert snap.output_enabled is True
    assert snap.commanded_volts == 2.0
    assert snap.heater.state == "on"

    # Set pressure above 1e-4 Torr
    sim_rig.set_pressure("FRG702_Chamber", 2.5e-4)
    spy.calls.clear()

    clock.advance(0.5)
    rig.run_tick()

    # On that exact tick:
    # 1. Snapshot shows tripped state, kind, and reason
    snap_tripped = rig.latest()
    assert snap_tripped.heater.state == "tripped"
    assert snap_tripped.heater.trip_kind == "pressure_high"
    assert "FRG702_Chamber" in snap_tripped.heater.trip_reason
    assert "2.50e-04" in snap_tripped.heater.trip_reason
    assert snap_tripped.output_enabled is False
    assert snap_tripped.commanded_volts == 0.0
    assert snap_tripped.permissive_ok is False

    # 2. Adapter received set_output(False) and write_voltage(0.0) in that same tick
    assert ("set_output", False) in spy.calls
    assert ("write_voltage", 0.0) in spy.calls


def test_stall_gauge_trips_at_5_1s_not_at_4_9s():
    """stall_gauge -> no trip at 4.9 s, pressure_stale at 5.1 s."""
    clock, sim_rig, spy, heater_out, evaluator, rig = make_test_rig()

    # Establish baseline
    rig.run_tick()
    assert rig.latest().heater.state == "off"

    # Stall gauge at t = 100.0
    sim_rig.stall_gauge("FRG702_Chamber")

    # Advance to t = 104.9 (4.9 s stale)
    clock.advance(4.9)
    rig.run_tick()
    snap_4_9 = rig.latest()
    assert snap_4_9.heater.state == "off"
    assert snap_4_9.heater.trip_kind is None

    # Advance to t = 105.1 (5.1 s stale -> exceeds 5.0 s STALE_ALLOWANCE_S)
    clock.advance(0.2)
    rig.run_tick()
    snap_5_1 = rig.latest()
    assert snap_5_1.heater.state == "tripped"
    assert snap_5_1.heater.trip_kind == "pressure_stale"
    assert "FRG702_Chamber" in snap_5_1.heater.trip_reason


def test_disconnect_trips_labjack_lost_reconnect_first_three_calls_then_reset():
    """disconnect -> labjack_lost; reconnect -> first calls off / 0 V / pin; reset accepted afterwards, not before."""
    clock, sim_rig, spy, heater_out, evaluator, rig = make_test_rig()

    rig.run_tick()
    assert rig.latest().labjack.state == "connected"

    # Disconnect
    sim_rig.disconnect()
    clock.advance(0.5)
    rig.run_tick()

    snap = rig.latest()
    assert snap.labjack.state == "lost"
    assert snap.heater.state == "tripped"
    assert snap.heater.trip_kind == "labjack_lost"

    # Reset while still disconnected must be refused
    rig.submit(ResetTrip())
    clock.advance(0.5)
    rig.run_tick()

    snap_refused = rig.latest()
    assert snap_refused.heater.state == "tripped"
    assert snap_refused.command_rejected_reason is not None
    assert "refused" in snap_refused.command_rejected_reason.lower()

    # Reconnect hardware link
    sim_rig.reconnect()
    # Advance past RECONNECT_INTERVAL_S so Rig reconnects
    clock.advance(RECONNECT_INTERVAL_S + 1.0)
    spy.calls.clear()
    rig.run_tick()

    # Verify first calls upon reconnect
    assert spy.calls[0] == "connect"
    assert spy.calls[1] == ("set_output", False)
    assert spy.calls[2] == ("write_voltage", 0.0)
    assert spy.calls[3] == "pin_current_limit"

    # Reconnect restored link, but latch remains tripped until reset
    snap_reconnected = rig.latest()
    assert snap_reconnected.labjack.state == "connected"
    assert snap_reconnected.heater.state == "tripped"
    assert snap_reconnected.heater.trip_kind == "labjack_lost"

    # Now reset is accepted
    rig.submit(ResetTrip())
    clock.advance(0.5)
    rig.run_tick()

    snap_cleared = rig.latest()
    assert snap_cleared.heater.state == "off"
    assert snap_cleared.heater.trip_kind is None
    assert snap_cleared.command_rejected_reason is None


def test_failed_shutoff_write_sets_shutoff_unverified():
    """fail_next_write on set_output(False) -> shutoff_unverified in the Snapshot."""
    clock, sim_rig, spy, heater_out, evaluator, rig = make_test_rig()

    rig.run_tick()
    # Turn output on
    rig.submit(SetOutput(enabled=True))
    clock.advance(0.5)
    rig.run_tick()
    assert rig.latest().output_enabled is True

    # Inject failure on next write and trip the heater
    sim_rig.fail_next_write()
    sim_rig.set_pressure("FRG702_Chamber", 2.0e-4)

    clock.advance(0.5)
    rig.run_tick()

    snap = rig.latest()
    assert snap.heater.shutoff_unverified is True
    assert snap.heater.state == "tripped"


def test_reset_refused_while_trip_persists_accepted_after_cleared():
    """Reset while the condition persists -> refused with reason; after it clears -> accepted."""
    clock, sim_rig, spy, heater_out, evaluator, rig = make_test_rig()

    rig.run_tick()
    sim_rig.set_pressure("FRG702_Chamber", 5.0e-4)
    clock.advance(0.5)
    rig.run_tick()

    assert rig.latest().heater.state == "tripped"
    assert rig.latest().heater.trip_kind == "pressure_high"

    # Reset attempt while pressure is still high -> refused
    rig.submit(ResetTrip())
    clock.advance(0.5)
    rig.run_tick()

    snap_refused = rig.latest()
    assert snap_refused.heater.state == "tripped"
    assert snap_refused.command_rejected_reason is not None
    assert "pressure" in snap_refused.command_rejected_reason.lower()

    # Pressure returns to safe level
    sim_rig.set_pressure("FRG702_Chamber", 1.0e-7)
    clock.advance(0.5)
    rig.run_tick()

    # Now reset -> accepted
    rig.submit(ResetTrip())
    clock.advance(0.5)
    rig.run_tick()

    snap_accepted = rig.latest()
    assert snap_accepted.heater.state == "off"
    assert snap_accepted.heater.trip_kind is None
    assert snap_accepted.command_rejected_reason is None


def test_executor_stopped_on_trip_in_same_tick():
    """The executor (ProgramExecutor) is stopped via the Rig when a trip latches, in the same tick."""
    clock, sim_rig, spy, heater_out, evaluator, rig = make_test_rig()

    mock_executor = MagicMock()
    mock_executor.is_running.return_value = True
    rig.set_program_executor(mock_executor)

    rig.run_tick()
    mock_executor.stop.assert_not_called()

    # Trip occurs
    sim_rig.set_pressure("FRG702_Chamber", 3.0e-4)
    clock.advance(0.5)
    rig.run_tick()

    # Executor must be stopped in the same tick
    mock_executor.stop.assert_called_once()


def test_operator_commands_reach_heater_output_and_adapter_writes():
    """SetOutput, SetVoltage, and Nudge reach HeaterOutput, adapter writes go through Rig only."""
    clock, sim_rig, spy, heater_out, evaluator, rig = make_test_rig()

    rig.run_tick()

    # SetOutput(True) and SetVoltage(0.5) - low enough to not trigger 180A cold limit
    rig.submit(SetOutput(enabled=True))
    rig.submit(SetVoltage(volts=0.5))
    clock.advance(0.5)
    rig.run_tick()

    assert rig.latest().output_enabled is True
    assert rig.latest().commanded_volts == 0.5
    assert ("set_output", True) in spy.calls
    assert ("write_voltage", 0.5) in spy.calls

    # Nudge up
    spy.calls.clear()
    rig.submit(Nudge(direction="up"))
    clock.advance(0.5)
    rig.run_tick()

    assert rig.latest().commanded_volts == pytest.approx(0.55)
    assert ("write_voltage", pytest.approx(0.55)) in spy.calls


def test_no_rampdown_references_remain_in_t8_daq_system():
    """Criterion 6: No reference to ramp-down remains in t8_daq_system/."""
    pkg_dir = Path(__file__).resolve().parents[2] / "t8_daq_system"
    pattern = re.compile(r"ramp[-_]?down", re.IGNORECASE)
    violating_lines = []

    for file_path in pkg_dir.rglob("*.py"):
        text = file_path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                violating_lines.append(f"{file_path.relative_to(pkg_dir)}:{line_no}: {line.strip()}")

    assert not violating_lines, (
        f"Found {len(violating_lines)} ramp-down references in t8_daq_system/:\n"
        + "\n".join(violating_lines)
    )

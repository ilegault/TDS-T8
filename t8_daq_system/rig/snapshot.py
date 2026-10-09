"""
Immutable Snapshot and Status dataclasses for the Rig module.

WHY THIS EXISTS
---------------
Previously, GUI, DAQ, and executor threads polled hardware independently, reading
different temperatures, pressures, and power supply voltages for the exact same
instant. In addition, mutable dictionaries passed across threads created race
conditions and torn reads.

A Snapshot is an immutable, frozen capture of all hardware readings, program
progress, and heater states for a single Rig tick. Every downstream consumer
(the GUI, safety evaluator, Program run, and CSV logger) reads the exact same
Snapshot (ADRs 0002–0004).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SourceStatus:
    """Status of an external hardware communication link (LabJack, XGS-600)."""

    state: str  # "connected" | "reconnecting" | "lost"
    message: str = ""


@dataclass(frozen=True)
class HeaterStatus:
    """Current state and trip status of the specimen heater output."""

    state: str  # "off" | "on" | "tripped"
    trip_kind: str | None = None
    trip_reason: str | None = None
    shutoff_unverified: bool = False


@dataclass(frozen=True)
class ProgramStatus:
    """Current state and parameters of a running Program."""

    running: bool = False
    block_index: int = 0
    block_type: str = ""
    waiting_for_confirmation: bool = False
    elapsed_in_block: float = 0.0
    setpoint_k: float = 0.0
    gains_in_use: tuple[float, float, float] = (0.0, 0.0, 0.0)
    sched_kp: float = 0.0
    sched_ki: float = 0.0
    sched_kd: float = 0.0
    sched_zone: str = ""
    ff_voltage: float = 0.0
    pid_correction: float = 0.0
    control_tc: str = "TC_1"


@dataclass(frozen=True)
class Snapshot:
    """
    Immutable state of all rig inputs and outputs for one tick.

    Temperatures are in Celsius (as read from T8 EF registers).
    Pressures are canonically in Torr.
    """

    t: float
    wall_time: float
    tc_c: Mapping[str, float | None]
    tc_raw_v: Mapping[str, float | None]
    pressure_torr: Mapping[str, float | None]
    source_age_s: Mapping[str, float]
    ps_volts: float
    ps_amps: float
    commanded_volts: float
    output_enabled: bool
    labjack: SourceStatus
    xgs: SourceStatus
    heater: HeaterStatus
    program: ProgramStatus
    permissive_ok: bool
    permissive_reason: str | None
    adapter: str  # "t8" | "simulated"
    adapter_refusal_reason: str | None = None
    command_rejected_reason: str | None = None

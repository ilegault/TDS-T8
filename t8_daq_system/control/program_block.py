"""
program_block.py
PURPOSE: Unified data containers for the block-based program executor.

SoftStartBlock is optional (ADR 0006, amended 2026-11-05). A program without one
starts on its first block from the first tick, which is what a short PID test that
steps the voltage on purpose needs. It has no fields of its own: its threshold, ramp
rate and handoff current are Settings, frozen in the run's RunSettings (ADR 0007).
"""

from dataclasses import dataclass, asdict

@dataclass
class VoltageRampBlock:
    start_voltage: float
    end_voltage: float
    duration_sec: float
    pid_active: bool = False
    block_type: str = "voltage_ramp"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k != 'block_type'})

@dataclass
class StableHoldBlock:
    target_temp_k: float
    tolerance_k: float
    hold_duration_sec: float
    qms_trigger: bool = False
    block_type: str = "stable_hold"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k != 'block_type'})

@dataclass
class TempRampBlock:
    rate_k_per_min: float
    end_temp_k: float
    tc_name: str
    block_type: str = "temp_ramp"
    entry_mode: str = "Rate"
    duration_min: float = 0.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k != 'block_type'})

@dataclass
class SoftStartBlock:
    block_type: str = "soft_start"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k != 'block_type'})

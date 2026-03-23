"""
program_block.py
PURPOSE: Unified data containers for the block-based program executor.
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

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k != 'block_type'})

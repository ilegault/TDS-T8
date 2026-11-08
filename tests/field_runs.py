"""
tests/field_runs.py
Loader for checked-in Field run fixtures (ticket 40).

WHY THIS EXISTS
---------------
Field runs provide real lab hardware traces (downsampled to stay under 200 kB)
to calibrate the two-node tungsten simulator (ticket 41), run scenario tests (ticket 42),
and check safety limits against field operational bounds (ticket 43).

This module is pure: it has no dependencies on Rig, hardware adapters, or Tkinter.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import functools
import json
import pathlib
from typing import Any

_FIXTURES_DIR = pathlib.Path(__file__).resolve().parent / "fixtures" / "field_runs"

FIELD_RUN_NAMES = (
    "2026-03-26_temp_ramp_1550",
    "2026-03-28_tds_5k_per_min",
    "2026-03-29_tds_unirradiated_33h",
    "2026-03-30_tds_irradiated_33h",
    "2026-04-15_ramp_hold_down",
)


@dataclass(frozen=True)
class FieldRun:
    """
    Downsampled field run recorded from the TDS rig.

    Fields:
        name: Unique run fixture identifier
        t_s: Elapsed time in seconds from run start (monotonic, starts at 0.0)
        filament_c: Filament thermocouple readings in Celsius
        ps_volts: Power supply measured voltage in Volts
        ps_amps: Power supply measured current in Amperes
        manifest: Manifest entry dict containing metadata and peak values
    """

    name: str
    t_s: tuple[float, ...]
    filament_c: tuple[float, ...]
    ps_volts: tuple[float, ...]
    ps_amps: tuple[float, ...]
    manifest: dict[str, Any]

    @property
    def manifest_entry(self) -> dict[str, Any]:
        """Alias for manifest entry dict."""
        return self.manifest


def _load_manifest() -> dict[str, Any]:
    manifest_path = _FIXTURES_DIR / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Field runs manifest not found: {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {item["name"]: item for item in data}
    return data


@functools.lru_cache(maxsize=None)
def load_field_run(name: str) -> FieldRun:
    """
    Load a single FieldRun fixture by name.

    Args:
        name: Name of the field run fixture

    Returns:
        FieldRun dataclass with immutable tuples of floats
    """
    manifest_data = _load_manifest()
    if name not in manifest_data:
        raise KeyError(f"Field run {name!r} not found in manifest")

    csv_path = _FIXTURES_DIR / f"{name}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Field run CSV not found: {csv_path}")

    t_s_list: list[float] = []
    fil_c_list: list[float] = []
    volts_list: list[float] = []
    amps_list: list[float] = []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx_t = header.index("t_s")
        idx_f = header.index("Filament_C")
        idx_v = header.index("PS_Voltage")
        idx_i = header.index("PS_Current")

        for row in reader:
            if not row:
                continue
            t_s_list.append(float(row[idx_t]))
            fil_c_list.append(float(row[idx_f]))
            volts_list.append(float(row[idx_v]))
            amps_list.append(float(row[idx_i]))

    return FieldRun(
        name=name,
        t_s=tuple(t_s_list),
        filament_c=tuple(fil_c_list),
        ps_volts=tuple(volts_list),
        ps_amps=tuple(amps_list),
        manifest=manifest_data[name],
    )


def all_field_runs() -> list[FieldRun]:
    """Return all five FieldRun instances in standard order."""
    return [load_field_run(name) for name in FIELD_RUN_NAMES]

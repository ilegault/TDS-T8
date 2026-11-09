"""
scripts/make_field_runs.py
Generate downsampled Field run fixture CSVs and manifest from real lab CSV logs.

WHY THIS EXISTS
---------------
Real lab runs contain 20,000–35,000 rows (1–4 MB each), which are gitignored and
exist only on the lab-office PC.

Field runs provide checked-in, downsampled excerpts of real lab CSVs so tests can:
1. Calibrate the two-node simulator (ticket 41).
2. Run scenario tests against realistic thermal traces (ticket 42).
3. Validate safety limits against real hardware operational envelopes (ticket 43).

Downsampling preserves the cold-start transient (first 300 s) at full recorded
resolution (~0.5 s) and retains one row every 5 s thereafter, keeping each
fixture file under 200 kB.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import pathlib
import sys
from typing import Any

SOURCES = [
    {
        "name": "2026-03-26_temp_ramp_1550",
        "source_file": "data_log_Fuller_Temp_Ramp_with_1550_Target_20260326_122133.csv",
    },
    {
        "name": "2026-03-28_tds_5k_per_min",
        "source_file": "data_log_Unirradiated_Bulk_W_Sample_TDS___5k.min_20260328_085521.csv",
    },
    {
        "name": "2026-03-29_tds_unirradiated_33h",
        "source_file": "data_log_Unirradiated_Bulk_W_Sample_-_33_hr_D2_Exposure_-_TDS_20260329_151315.csv",
    },
    {
        "name": "2026-03-30_tds_irradiated_33h",
        "source_file": "data_log_Ion_Irradiated_DiMES_Bulk_W_-_33_hr_D2_Exposed_-_TDS_20260330_073924.csv",
    },
    {
        "name": "2026-04-15_ramp_hold_down",
        "source_file": "data_log_H_and_D_Chamber_Background_Check_-_Temp_Ramp_Up_and_Hold_and_Down_20260415_094625.csv",
        # Active experiment completed at t=7875 s; subsequent data in raw log is post-run
        # floating monitor readings after the Keysight power supply was turned off.
        "max_t_s": 7875.0,
    },
]


def process_source_file(
    source_path: pathlib.Path,
    max_t_s: float | None = None,
) -> tuple[list[tuple[float, float, float, float]], dict[str, Any]]:
    """
    Read a lab CSV file, extract columns, downsample after 300 s, and return rows + manifest entry.
    """
    with open(source_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = None
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            if row[0] == "Timestamp":
                header = row
                break

        if not header:
            raise ValueError(f"No CSV header found in {source_path}")

        idx_t = header.index("Timestamp")
        idx_f = header.index("Filament")
        idx_v = header.index("PS_Voltage")
        idx_i = header.index("PS_Current")

        rows_in = 0
        rows_dropped = 0
        t0: datetime | None = None
        parsed_rows: list[tuple[float, float, float, float]] = []

        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            rows_in += 1
            try:
                ts_dt = datetime.fromisoformat(row[idx_t])
                fil_val = float(row[idx_f])
                v_val = float(row[idx_v])
                i_val = float(row[idx_i])
            except (ValueError, IndexError):
                rows_dropped += 1
                continue

            if t0 is None:
                t0 = ts_dt
            t_s = (ts_dt - t0).total_seconds()
            if max_t_s is not None and t_s > max_t_s:
                break
            parsed_rows.append((t_s, fil_val, v_val, i_val))

    # Downsample:
    # First 300 s: keep every recorded row.
    # After 300 s: keep one row every 5 s.
    downsampled: list[tuple[float, float, float, float]] = []
    last_kept_t = -999.0
    for t_s, fil_val, v_val, i_val in parsed_rows:
        if t_s <= 300.0:
            downsampled.append((round(t_s, 3), round(fil_val, 3), round(v_val, 4), round(i_val, 3)))
            last_kept_t = t_s
        else:
            if t_s - last_kept_t >= 5.0:
                downsampled.append((round(t_s, 3), round(fil_val, 3), round(v_val, 4), round(i_val, 3)))
                last_kept_t = t_s

    rows_out = len(downsampled)
    peak_current_a = max(r[3] for r in downsampled)
    peak_filament_c = max(r[1] for r in downsampled)

    stats = {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rows_dropped": rows_dropped,
        "peak_current_a": peak_current_a,
        "peak_filament_c": peak_filament_c,
        "control_tc": "Filament",
    }
    return downsampled, stats


def generate_field_runs(logs_dir: pathlib.Path, output_dir: pathlib.Path) -> None:
    """Generate all Field run fixtures and write manifest.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, Any]] = {}

    for source in SOURCES:
        name = source["name"]
        source_file = source["source_file"]
        source_path = logs_dir / source_file
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        print(f"Processing {name} from {source_file}...")
        rows, stats = process_source_file(source_path, max_t_s=source.get("max_t_s"))

        csv_path = output_dir / f"{name}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["t_s", "Filament_C", "PS_Voltage", "PS_Current"])
            for row in rows:
                writer.writerow(row)

        file_size = csv_path.stat().st_size
        print(f"  Written {len(rows)} rows to {csv_path.name} ({file_size} bytes)")
        if file_size >= 200_000:
            raise ValueError(f"File size {file_size} exceeds 200 kB limit for {csv_path.name}")

        manifest[name] = {
            "name": name,
            "source_file": source_file,
            **stats,
        }

    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"Manifest written to {manifest_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate downsampled Field run fixtures from real lab CSVs."
    )
    parser.add_argument(
        "logs_folder",
        type=pathlib.Path,
        help="Path to the logs folder containing raw CSV files.",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=None,
        help="Directory to write fixture files (default: tests/fixtures/field_runs).",
    )
    args = parser.parse_args()

    repo_root = pathlib.Path(__file__).resolve().parent.parent
    output_dir = args.output_dir or (repo_root / "tests" / "fixtures" / "field_runs")

    try:
        generate_field_runs(args.logs_folder, output_dir)
    except Exception as e:
        print(f"Error generating field runs: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

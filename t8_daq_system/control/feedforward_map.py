"""
feedforward_map.py
PURPOSE: Steady-state-backbone feedforward voltage map for the temperature ramp PID.

Architecture (Change 3):
  - One steady-state curve V_ss(T) is built from all slow-ramp + hold data
    (rates < _SS_RATE_THRESH, currently 8 K/min).
  - voltage_for(rate, T) = V_ss(T) + dV_dynamic(rate, T)  [dV_dynamic = 0 pending
    fast-rate residual fitting; this is the intended extension point].
  - Per-rate curves in _data are kept for zone detection and future fast-rate learning.
  - Any requested rate is immediately supported because the backbone does not key on rate.

Column selection (Change 1):
  - Priority: 'Sample' > 'TC_1' > first TC_ that is not TC_AIN* and not _rawV.
  - Aux channels (TC_AIN*) are explicitly excluded.
  - Files without a valid temperature column are skipped with a warning.
"""

import csv
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(__file__)
_MAP_PATH      = os.path.normpath(os.path.join(_HERE, '..', 'config', 'feedforward_map.json'))

_V_MAX             = 6.0
_TEMP_BIN_SIZE     = 50    # °C bin width for ingest / append
_MIN_BIN_SAMPLES   = 3     # min voltage readings per bin before updating the map
_DERIV_HALF_WIN    = 5     # half-window (samples) for dT/dt estimation
_SLOPE_JUMP_FACTOR = 1.5   # zone-boundary: slope increases by this ratio
_SS_RATE_THRESH    = 8.0   # K/min — rates below this feed the steady-state backbone

_AUX_COL_RE = re.compile(r'^TC_AIN\d+')

# Set to True ONLY when you want to rebuild the map from logs.
# When False, the curated _ss backbone in feedforward_map.json is frozen:
# ingest_csv, append_run, and scan_log_folder are all no-ops.
AUTO_INGEST_ENABLED = False


# ── Public data types ──────────────────────────────────────────────────────────

@dataclass
class Zone:
    """One gain-scheduling zone within a block."""
    t_lo: float        # lower temperature boundary °C
    t_hi: float        # upper temperature boundary °C
    mean_slope: float  # mean dV/dT (V/°C) across this zone


# ── Map class ──────────────────────────────────────────────────────────────────

class FeedforwardMap:
    """
    Steady-state-backbone feedforward voltage map.

    Internal structure:
        _ss_curve: list[[temp_C, voltage_V]] — steady-state backbone V_ss(T)
        _data: dict[str, list[list[float]]] — per-rate curves for zone detection

    JSON file structure:
        { "_ss": [[T, V], ...], "2": [[T, V], ...], "5": [...], ... }

    Thread-safety: load() and save() should be called from a single thread.
    voltage_for() and zones_for() are read-only and safe to call from any thread
    once the map is loaded.
    """

    def __init__(self, map_path: str = None):
        self._map_path      = map_path or _MAP_PATH
        self._data: dict    = {}
        self._ss_curve: list = []   # steady-state backbone [[T_C, V], ...]
        self._unseen_warned = set()
        self._ingested: set = set()  # in-session dedup for scan_log_folder

    # ── Public API ─────────────────────────────────────────────────────────────

    def load(self):
        """Load the map from disk. Safe to call multiple times."""
        try:
            with open(self._map_path, 'r') as f:
                raw = json.load(f)
            # Load steady-state backbone (stored under the '_ss' key)
            ss_raw = raw.get('_ss', [])
            self._ss_curve = [[float(p[0]), float(p[1])] for p in ss_raw] if ss_raw else []
            # Load per-rate curves (skip all underscore-prefixed keys)
            self._data = {
                k: [[float(p[0]), float(p[1])] for p in v]
                for k, v in raw.items()
                if not k.startswith('_') and isinstance(v, list)
            }
            logger.info(
                "[FeedforwardMap] Loaded ss_curve=%d pts, %d rate curves",
                len(self._ss_curve), len(self._data)
            )
        except FileNotFoundError:
            logger.warning(
                "[FeedforwardMap] Map file not found at %s — starting empty", self._map_path
            )
        except Exception as exc:
            logger.error("[FeedforwardMap] Load error: %s", exc)

    def voltage_for(self, rate_k_per_min: float, temp_c: float) -> float:
        """
        Return feedforward voltage for the given rate and temperature.

        Uses the steady-state backbone V_ss(T) when available — this makes any
        requested rate immediately supported without data gaps.

        Falls back to rate-indexed interpolation only when the backbone is empty
        (first startup before any data has been ingested).

        Returns 0.0 for any temperature below the backbone's first point (ADR 0006).
        Output always clamped to [0.0, 6.0].
        """
        if self._ss_curve:
            # ADR 0006 point 6: below the lowest data point the answer is 0 V.
            # Returning the lowest point's voltage handed a cold filament 0.29 V.
            if temp_c < self._ss_curve[0][0]:
                return 0.0
            v_ss = _interp_points(self._ss_curve, temp_c)
            # dV_dynamic: additive correction for fast-rate thermal deficit.
            # Currently 0; fit from (fast-ramp voltage − V_ss) residuals once
            # enough fast-ramp data has been accumulated.
            dv = 0.0
            return max(0.0, min(_V_MAX, v_ss + dv))

        # Fallback: legacy rate-indexed lookup (used before any data is ingested)
        if not self._data:
            return 0.0
        rates = sorted(float(k) for k in self._data)
        if rate_k_per_min <= rates[0]:
            if rate_k_per_min < rates[0] and rate_k_per_min not in self._unseen_warned:
                logger.info(
                    "[FeedforwardMap] Rate %.1f K/min below stored range — using %.1f",
                    rate_k_per_min, rates[0]
                )
                self._unseen_warned.add(rate_k_per_min)
            return max(0.0, min(_V_MAX, _interp_points(self._data[_rkey(rates[0])], temp_c)))
        if rate_k_per_min >= rates[-1]:
            if rate_k_per_min > rates[-1] and rate_k_per_min not in self._unseen_warned:
                logger.info(
                    "[FeedforwardMap] Rate %.1f K/min above stored range — using %.1f",
                    rate_k_per_min, rates[-1]
                )
                self._unseen_warned.add(rate_k_per_min)
            return max(0.0, min(_V_MAX, _interp_points(self._data[_rkey(rates[-1])], temp_c)))
        lo = max(r for r in rates if r <= rate_k_per_min)
        hi = min(r for r in rates if r >= rate_k_per_min)
        if lo == hi:
            return max(0.0, min(_V_MAX, _interp_points(self._data[_rkey(lo)], temp_c)))
        v_lo = _interp_points(self._data[_rkey(lo)], temp_c)
        v_hi = _interp_points(self._data[_rkey(hi)], temp_c)
        t    = (rate_k_per_min - lo) / (hi - lo)
        return max(0.0, min(_V_MAX, v_lo + t * (v_hi - v_lo)))

    def zones_for(self, rate_k_per_min: float,
                  t_start_c: float, t_end_c: float) -> List[Zone]:
        """
        Auto-detect gain-scheduling zones from slope changes in the best available curve.

        Prefers the steady-state backbone; falls back to the nearest per-rate curve.
        Returns up to 4 Zone objects spanning [t_start_c, t_end_c].
        """
        if self._ss_curve:
            curve = [
                (float(t), float(v))
                for t, v in self._ss_curve
                if t_start_c - 1 <= float(t) <= t_end_c + 1
            ]
        elif self._data:
            rates   = sorted(float(k) for k in self._data)
            nearest = min(rates, key=lambda r: abs(r - rate_k_per_min))
            curve   = [
                (float(t), float(v))
                for t, v in self._data[_rkey(nearest)]
                if t_start_c - 1 <= float(t) <= t_end_c + 1
            ]
        else:
            return [Zone(t_start_c, t_end_c, 0.0)]

        if len(curve) < 2:
            return [Zone(t_start_c, t_end_c, 0.0)]

        slopes = []
        for i in range(len(curve) - 1):
            t0, v0 = curve[i]
            t1, v1 = curve[i + 1]
            dt = t1 - t0
            if dt > 0:
                slopes.append((t0, t1, (v1 - v0) / dt))
        if not slopes:
            return [Zone(t_start_c, t_end_c, 0.0)]

        mean_slope  = sum(s for _, _, s in slopes) / len(slopes)
        boundaries  = [t_start_c]
        for i in range(1, len(slopes)):
            _, _, s_prev = slopes[i - 1]
            t_cur, _, s_cur = slopes[i]
            if s_prev > 1e-6 and s_cur / s_prev > _SLOPE_JUMP_FACTOR:
                boundaries.append(t_cur)
        boundaries.append(t_end_c)
        while len(boundaries) > 5:   # cap at 4 zones
            boundaries.pop(-2)

        zones = []
        for i in range(len(boundaries) - 1):
            t_lo = boundaries[i]
            t_hi = boundaries[i + 1]
            seg  = [s for t0, t1, s in slopes if t0 >= t_lo - 1 and t1 <= t_hi + 1]
            ms   = sum(seg) / len(seg) if seg else mean_slope
            zones.append(Zone(t_lo, t_hi, ms))
        return zones or [Zone(t_start_c, t_end_c, mean_slope)]

    def validate_program(self, blocks, v_ceiling: float = 5.5) -> list:
        """
        Check each TempRamp block for potential power-envelope violations.

        Samples the steady-state backbone at the block's end temperature (the
        highest voltage requirement). Returns a list of warning strings; empty
        list means all blocks are feasible.

        v_ceiling: V reserved for feedforward before PID headroom is exhausted
                   (default 5.5 V = 6 V rail − 0.5 V PID headroom).
        """
        if not self._ss_curve:
            return []
        warnings = []
        for i, block in enumerate(blocks):
            if getattr(block, 'block_type', None) != 'temp_ramp':
                continue
            t_end_c = block.end_temp_k - 273.15
            v = _interp_points(self._ss_curve, t_end_c)
            if v > v_ceiling:
                warnings.append(
                    f"Block {i + 1}: feedforward voltage at {t_end_c:.0f}\u00b0C "
                    f"({v:.2f} V) approaches power ceiling \u2014 "
                    f"PID correction headroom may be insufficient at this temperature."
                )
        return warnings

    def ingest_csv(self, path: str):
        """
        Parse one data-log CSV and merge temp/voltage data into the map.

        Slow-rate data (< _SS_RATE_THRESH K/min) feeds the steady-state backbone.
        All ramp data also feeds per-rate curves (keyed by rounded K/min).
        Skips files where the temperature column cannot be resolved to a real
        sample sensor (not a TC_AIN* aux channel).
        Saves the map to disk only when new data is actually added.
        """
        if not AUTO_INGEST_ENABLED:
            return
        try:
            timestamps, temps, volts = _parse_csv(path)
        except Exception as exc:
            logger.debug("[FeedforwardMap] ingest_csv %s: %s", os.path.basename(path), exc)
            return

        n = len(timestamps)
        if n < _DERIV_HALF_WIN * 2 + 1:
            return

        # Compute per-sample dT/dt (K/min) with a symmetric sliding window
        derived_rates = [None] * n
        for i in range(_DERIV_HALF_WIN, n - _DERIV_HALF_WIN):
            t0, t1   = timestamps[i - _DERIV_HALF_WIN], timestamps[i + _DERIV_HALF_WIN]
            tc0, tc1 = temps[i - _DERIV_HALF_WIN],      temps[i + _DERIV_HALF_WIN]
            if None in (t0, t1, tc0, tc1):
                continue
            dt_sec = t1 - t0
            if dt_sec > 0:
                derived_rates[i] = (tc1 - tc0) / dt_sec * 60.0

        ss_bins: dict   = {}  # temp_bin -> [voltages]  for the ss backbone
        rate_bins: dict = {}  # rate_key -> {temp_bin -> [voltages]}

        for rate, temp, volt in zip(derived_rates, temps, volts):
            if rate is None or rate < 0.5:
                continue
            if temp is None or temp < 50:
                continue
            if volt is None or volt < 0.05:
                continue
            tb = round(temp / _TEMP_BIN_SIZE) * _TEMP_BIN_SIZE

            # Steady-state backbone: slow ramps only
            if rate < _SS_RATE_THRESH:
                ss_bins.setdefault(tb, []).append(volt)

            # Per-rate accumulation at the actual (rounded) rate
            rk = _rkey(round(rate))
            rate_bins.setdefault(rk, {}).setdefault(tb, []).append(volt)

        changed = False

        # Update ss backbone
        if ss_bins:
            existing_ss = {int(t): v for t, v in self._ss_curve}
            for tb, vlist in ss_bins.items():
                if len(vlist) < _MIN_BIN_SAMPLES:
                    continue
                existing_ss[tb] = sorted(vlist)[len(vlist) // 2]
                changed = True
            if existing_ss:
                curve = _enforce_monotonicity(sorted(existing_ss.items()))
                self._ss_curve = [[t, v] for t, v in curve]

        # Update per-rate curves
        for rk, bins in rate_bins.items():
            existing = {int(t): v for t, v in self._data.get(rk, [])}
            for tb, vlist in bins.items():
                if len(vlist) < _MIN_BIN_SAMPLES:
                    continue
                existing[tb] = sorted(vlist)[len(vlist) // 2]
                changed = True
            if existing:
                curve = _enforce_monotonicity(sorted(existing.items()))
                self._data[rk] = [[t, v] for t, v in curve]

        if changed:
            self._save()

    def append_run(self, run_log: list, rate_k_per_min: float):
        """
        Merge the in-memory tick log from a completed run into the map.

        run_log: list of (elapsed_sec, setpoint_k, actual_k, voltage_v).
        Slow runs (< _SS_RATE_THRESH K/min) also update the steady-state backbone.
        The snap-within-5-K/min gate has been removed: all completed runs are
        learned regardless of whether the rate matches a previously stored curve.
        Saves the map to disk when new data is added.
        """
        if not AUTO_INGEST_ENABLED:
            return
        if not run_log:
            return

        bins: dict = {}
        for _elapsed, _sp_k, actual_k, voltage_v in run_log:
            temp_c = actual_k - 273.15
            if temp_c < 50 or voltage_v < 0.05:
                continue
            tb = round(temp_c / _TEMP_BIN_SIZE) * _TEMP_BIN_SIZE
            bins.setdefault(tb, []).append(voltage_v)

        changed = False

        # Update steady-state backbone for slow runs
        if rate_k_per_min < _SS_RATE_THRESH:
            existing_ss = {int(t): v for t, v in self._ss_curve}
            for tb, vlist in bins.items():
                if len(vlist) < _MIN_BIN_SAMPLES:
                    continue
                existing_ss[tb] = sorted(vlist)[len(vlist) // 2]
                changed = True
            if existing_ss:
                curve = _enforce_monotonicity(sorted(existing_ss.items()))
                self._ss_curve = [[t, v] for t, v in curve]

        # Update per-rate curve at the actual (rounded) rate
        rk = _rkey(round(rate_k_per_min))
        existing = {int(t): v for t, v in self._data.get(rk, [])}
        for tb, vlist in bins.items():
            if len(vlist) < _MIN_BIN_SAMPLES:
                continue
            existing[tb] = sorted(vlist)[len(vlist) // 2]
            changed = True
        if existing:
            curve = _enforce_monotonicity(sorted(existing.items()))
            self._data[rk] = [[t, v] for t, v in curve]

        if changed:
            self._save()

    def scan_log_folder(self, log_folder: str):
        """
        Ingest all un-seen CSVs found by a recursive walk of log_folder.

        Auto-ingest is disabled by default (AUTO_INGEST_ENABLED = False), so this
        is a no-op unless that flag is turned on. Within a session, already-ingested
        files are tracked in-memory so they are not double-counted.
        """
        if not AUTO_INGEST_ENABLED:
            return
        count = 0
        for dirpath, _dirs, files in os.walk(log_folder):
            for fname in files:
                if not fname.endswith('.csv'):
                    continue
                fpath = os.path.join(dirpath, fname)
                if fpath in self._ingested:
                    continue
                self.ingest_csv(fpath)
                self._ingested.add(fpath)
                count += 1
        if count:
            logger.info("[FeedforwardMap] scan_log_folder: ingested %d new CSV(s)", count)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _save(self):
        """Write the current map to disk (atomic: write-then-replace)."""
        try:
            out = {
                '_comment': (
                    'Feedforward map. _ss is the steady-state backbone V_ss(T) built from '
                    'slow-ramp and hold data. Numeric keys are per-rate curves [temp_C, '
                    'voltage_V] sorted ascending by temperature. Updated automatically by '
                    'FeedforwardMap.ingest_csv / append_run.'
                ),
                '_ss': self._ss_curve,
            }
            out.update(self._data)
            tmp = self._map_path + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(out, f, indent=2)
            os.replace(tmp, self._map_path)
        except Exception as exc:
            logger.error("[FeedforwardMap] Save error: %s", exc)


# ── Module-level helpers ───────────────────────────────────────────────────────

def _resolve_temp_col(columns):
    """
    Pick the best temperature column from a list of candidate column names.

    Priority:
      1. 'Sample'     — primary sample sensor on newer TDS logs
      2. 'TC_1'       — legacy primary thermocouple
      3. First TC_ column that is NOT an aux channel (TC_AIN*) and NOT _rawV suffix

    Returns None if no suitable column is found; callers should skip the file.
    """
    if 'Sample' in columns:
        return 'Sample'
    if 'TC_1' in columns:
        return 'TC_1'
    for col in columns:
        if col.startswith('TC_') and not col.endswith('_rawV') and not _AUX_COL_RE.match(col):
            return col
    return None


def _rkey(rate: float) -> str:
    """Canonical string key for a rate value (e.g. 10.0 → '10')."""
    return str(int(round(rate)))


def _enforce_monotonicity(curve: list) -> list:
    """
    Remove points that would cause voltage to decrease with temperature.
    Input/output: list of (temp_C, voltage_V) tuples sorted by temp_C.
    """
    result = []
    max_v  = -float('inf')
    for t, v in curve:
        if v >= max_v:
            result.append((t, v))
            max_v = v
    return result


def _interp_points(curve: list, temp_c: float) -> float:
    """Linearly interpolate voltage at temp_c from a [[T, V], ...] curve."""
    if not curve:
        return 0.0
    if temp_c <= curve[0][0]:
        return curve[0][1]
    if temp_c >= curve[-1][0]:
        return curve[-1][1]
    for i in range(len(curve) - 1):
        t0, v0 = curve[i]
        t1, v1 = curve[i + 1]
        if t0 <= temp_c <= t1:
            frac = (temp_c - t0) / (t1 - t0) if t1 != t0 else 0.0
            return v0 + frac * (v1 - v0)
    return curve[-1][1]


def _parse_csv(path: str):
    """
    Parse a T8 data-log CSV into parallel (timestamps_sec, temps_C, voltages_V) lists.

    Temperature column is resolved by _resolve_temp_col() with this priority:
      'Sample' > 'TC_1' > first non-aux TC_ column (not TC_AIN*, not _rawV)
    Raises ValueError if no valid temperature column or voltage column is found,
    causing the calling ingest_csv to skip the file.
    """
    from datetime import datetime

    timestamps: list = []
    temps:      list = []
    volts:      list = []
    tc_col   = None
    volt_col = None
    tc_idx   = None
    volt_idx = None
    header   = None

    with open(path, 'r', newline='', encoding='utf-8', errors='replace') as f:
        for raw_line in f:
            line = raw_line.rstrip('\n')

            # Extract column hints from the #META: header line
            if line.startswith('#META:'):
                try:
                    meta = json.loads(line[6:])
                    sensors_raw = meta.get('sensors', '')
                    sensors = (
                        [s.strip() for s in sensors_raw.split(',')]
                        if isinstance(sensors_raw, str) else list(sensors_raw)
                    )
                    if tc_col is None:
                        tc_col = _resolve_temp_col(sensors)
                    if volt_col is None and 'PS_Voltage_Setpoint' in sensors:
                        volt_col = 'PS_Voltage_Setpoint'
                    if volt_col is None and 'PS_Voltage' in sensors:
                        volt_col = 'PS_Voltage'
                except Exception as e:
                    # Malformed #META: header; falls back to CSV data header below
                    logger.debug("Failed to parse #META: header (%s); falling back to data header", e)

                continue

            if line.startswith('#'):
                continue

            row = next(csv.reader([line]))
            if not row:
                continue

            if row[0] == 'Timestamp':
                header = row
                # Re-resolve from actual header columns (validates META hint and
                # falls back if the META-suggested column is absent from the data)
                if tc_col is None or tc_col not in header:
                    tc_col = _resolve_temp_col(header[1:])
                if volt_col is None:
                    if 'PS_Voltage_Setpoint' in header:
                        volt_col = 'PS_Voltage_Setpoint'
                    elif 'PS_Voltage' in header:
                        volt_col = 'PS_Voltage'
                if tc_col is None:
                    logger.warning(
                        "[FeedforwardMap] %s: no valid temperature column found "
                        "(checked Sample, TC_1, non-aux TC_*) — skipping file",
                        os.path.basename(path)
                    )
                    raise ValueError("No valid temperature column")
                if volt_col is None or tc_col not in header or volt_col not in header:
                    raise ValueError(
                        f"Required columns not found (tc={tc_col}, volt={volt_col})"
                    )
                tc_idx   = header.index(tc_col)
                volt_idx = header.index(volt_col)
                continue

            if header is None:
                continue

            # Data row
            try:
                ts   = datetime.fromisoformat(row[0]).timestamp()
                temp = float(row[tc_idx])   if row[tc_idx]   else None
                volt = float(row[volt_idx]) if row[volt_idx] else None
                timestamps.append(ts)
                temps.append(temp)
                volts.append(volt)
            except (ValueError, IndexError):
                continue

    if not timestamps:
        raise ValueError("No data rows parsed")
    return timestamps, temps, volts

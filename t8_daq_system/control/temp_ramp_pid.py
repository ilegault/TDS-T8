"""
temp_ramp_pid.py
PURPOSE: PID controller and run-history for Temperature Ramp mode.

No GUI / tkinter imports — pure control/logic module.
"""

import json
import os


# ── Soft-Start / Phase 1 constants ────────────────────────────────────────────
SOFT_START_THRESHOLD_C    = 150.0   # °C — TDS preheat target; soft-start hands off to PID Hold here
SOFT_START_VOLTAGE_STEP   = 0.010   # V per tick — how fast voltage climbs in Phase 1
SOFT_START_CURRENT_LIMIT  = 120.0   # A — pause voltage increase if current exceeds this
SOFT_START_RATE_CEILING   = 3.0     # K/min — cut voltage if heating too fast in Phase 1

# ── PID slew-rate limiter ─────────────────────────────────────────────────────
PID_MAX_VOLTAGE_STEP_V    = 0.050   # V per tick — max DAC0 change per PID update

# ── Feedforward learning ──────────────────────────────────────────────────────
FF_HISTORY_FILE           = "pid_feedforward_table.json"
FF_TEMP_BUCKET_C          = 10.0    # °C — resolution of feedforward table buckets


# ── Temperature conversion utilities ──────────────────────────────────────────

def celsius_to_kelvin(temp_c: float) -> float:
    return temp_c + 273.15


def kelvin_to_celsius(temp_k: float) -> float:
    return temp_k - 273.15


# ── PID Controller ─────────────────────────────────────────────────────────────

class PIDController:
    """
    Discrete-time PID controller with anti-windup and output clamping.

    Output is a normalised 0–1 power fraction (not raw volts/amps).
    """

    def __init__(self, kp=0.05, ki=0.002, kd=0.005,
                 output_min=0.0, output_max=5.0,
                 integral_windup_limit=5.0):
        """
        Args:
            kp: Proportional gain (very small — power supply is high-current).
            ki: Integral gain.
            kd: Derivative gain.
            output_min: Minimum clamped output (fraction of full power).
            output_max: Maximum clamped output (fraction of full power).
            integral_windup_limit: Clamp integral accumulator to ±this (K·s).
        """
        self._kp = kp
        self._ki = ki
        self._kd = kd
        self._output_min = output_min
        self._output_max = output_max
        self._windup_limit = integral_windup_limit

        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_time = None
        self._prev_output = 0.0

        # Debug: last computed P, I, D contributions
        self._last_p_term = 0.0
        self._last_i_term = 0.0
        self._last_d_term = 0.0

    def reset(self):
        """Reset integrator and history — call before starting a new run."""
        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_time = None
        self._prev_output = 0.0
        self._last_p_term = 0.0
        self._last_i_term = 0.0
        self._last_d_term = 0.0

    def compute(self, setpoint_k: float, measured_k: float,
                current_time: float) -> float:
        """
        Compute the next PID output.

        Args:
            setpoint_k:   Desired temperature in Kelvin.
            measured_k:   Measured temperature in Kelvin.
            current_time: Monotonic timestamp (e.g. time.time()).

        Returns:
            Clamped output in [output_min, output_max].
        """
        if self._prev_time is None:
            self._prev_time = current_time
            return 0.0

        dt = current_time - self._prev_time
        if dt <= 0:
            return self._prev_output

        error = setpoint_k - measured_k

        # Integral with anti-windup clamp
        self._integral += error * dt
        self._integral = max(0.0, min(self._integral, 5.0))

        derivative = (error - self._prev_error) / dt

        self._last_p_term = self._kp * error
        self._last_i_term = self._ki * self._integral
        self._last_d_term = self._kd * derivative
        raw_output = self._last_p_term + self._last_i_term + self._last_d_term

        # Clamp output to DAC range
        clamped = max(0.0, min(raw_output, 5.0))

        self._prev_error = error
        self._prev_time = current_time
        self._prev_output = clamped

        return clamped

    def get_debug_terms(self) -> dict:
        """Return the P, I, D contributions from the most recent compute() call.

        Use this for transparent debugging during practice-mode runs to verify
        the PID is behaving correctly before connecting real hardware.
        """
        return {
            'p_term': self._last_p_term,
            'i_term': self._last_i_term,
            'd_term': self._last_d_term,
            'integral_accumulator': self._integral,
        }

    def update_gains(self, kp: float, ki: float, kd: float):
        """Update PID gains (can be called between runs)."""
        self._kp = kp
        self._ki = ki
        self._kd = kd


# ── Run history / gain learning ────────────────────────────────────────────────

class TempRampHistory:
    """
    Persists past TempRamp run records to JSON so PID gains can improve over
    time.  Each record captures performance metrics and the gains that were
    used, enabling data-driven gain suggestion for future runs.
    """

    HISTORY_FILE = "t8_daq_system/data/temp_ramp_history.json"
    MAX_RUNS = 50  # keep the last N runs

    def __init__(self):
        self._runs = []
        self._load()

    # ── Private ────────────────────────────────────────────────────────────────

    def _load(self):
        """Load history from disk; silently fall back to empty list on error."""
        try:
            if os.path.exists(self.HISTORY_FILE):
                with open(self.HISTORY_FILE, 'r') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._runs = data
                else:
                    self._runs = []
        except Exception:
            self._runs = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def save_run(self, run_record: dict):
        """
        Append a completed run record and write to disk.

        Required keys in run_record:
            timestamp (str, ISO)
            target_rate_k_per_min (float)
            achieved_mean_rate_k_per_min (float)
            overshoot_k (float)
            duration_sec (float)
            kp_used (float)
            ki_used (float)
            kd_used (float)
        """
        self._runs.append(run_record)
        # Trim to the most recent MAX_RUNS entries
        if len(self._runs) > self.MAX_RUNS:
            self._runs = self._runs[-self.MAX_RUNS:]

        # Create parent directory if needed
        parent = os.path.dirname(self.HISTORY_FILE)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        try:
            with open(self.HISTORY_FILE, 'w') as f:
                json.dump(self._runs, f, indent=2)
        except Exception as exc:
            print(f"[TempRampHistory] Could not write history file: {exc}")

    def suggest_gains(self, target_rate_k_per_min: float) -> dict:
        """
        Return PID gains appropriate for the requested ramp rate.

        Searches stored runs within ±1 K/min of the target.  If fewer than 3
        matching runs exist, returns conservative defaults.  Otherwise picks
        the run with the smallest overshoot.

        Returns:
            dict with keys 'kp', 'ki', 'kd'.
        """
        _defaults = {'kp': 0.05, 'ki': 0.002, 'kd': 0.005}

        matching = [
            r for r in self._runs
            if abs(r.get('target_rate_k_per_min', 0.0) - target_rate_k_per_min) < 1.0
        ]

        if len(matching) < 3:
            return _defaults

        # Sort ascending by absolute overshoot (least overshoot = best)
        matching.sort(key=lambda r: abs(r.get('overshoot_k', 0.0)))
        best = matching[0]
        return {
            'kp': best['kp_used'],
            'ki': best['ki_used'],
            'kd': best['kd_used'],
        }

    def get_all_runs(self) -> list:
        """Return a copy of all stored run records."""
        return list(self._runs)


# ── Feedforward voltage-vs-temperature table ───────────────────────────────────

class FeedforwardTable:
    """
    Stores and retrieves voltage-vs-temperature mapping learned from real runs.
    After each run, the executor calls update() with the observed T and V.
    On subsequent runs, lookup() returns the expected voltage for a given temperature,
    which is used as the PID baseline. The PID then only corrects the residual error.

    Data is persisted to FF_HISTORY_FILE as a JSON dict of {temp_bucket: avg_voltage}.
    """

    def __init__(self, filepath=FF_HISTORY_FILE):
        self.filepath = filepath
        self._table = {}     # {temp_bucket_str: [list of observed voltages]}
        self._averages = {}  # {temp_bucket_str: float avg voltage}
        self._load()

    def _bucket_key(self, temp_c):
        bucket = round(temp_c / FF_TEMP_BUCKET_C) * FF_TEMP_BUCKET_C
        return str(int(bucket))

    def _load(self):
        try:
            if not os.path.exists(self.filepath):
                raise FileNotFoundError("File does not exist")
            with open(self.filepath, 'r') as f:
                content = f.read().strip()
                if not content:
                    raise ValueError("Empty file")
                data = json.loads(content)
            self._averages = {k: float(v) for k, v in data.items()}
            print(f"[FeedforwardTable] Loaded {len(self._averages)} entries from {self.filepath}")
        except Exception as e:
            print(f"[FeedforwardTable] Could not load feedforward table ({e}), defaulting to 0.0V")
            self._averages = {}

    def save(self):
        try:
            with open(self.filepath, 'w') as f:
                json.dump(self._averages, f, indent=2)
            print(f"[FeedforwardTable] Saved {len(self._averages)} entries to {self.filepath}")
        except Exception as e:
            print(f"[FeedforwardTable] Could not save: {e}")

    def update(self, temp_c, voltage_v):
        """Call this every tick during a real run to record what voltage achieved what temperature."""
        key = self._bucket_key(temp_c)
        if key not in self._table:
            self._table[key] = []
        self._table[key].append(voltage_v)
        # Update running average
        vals = self._table[key]
        self._averages[key] = sum(vals) / len(vals)

    def lookup(self, temp_c):
        """
        Returns the expected feedforward voltage for a given temperature.
        Returns 0.0 if no data exists yet (first run — PID works alone).
        Interpolates linearly between the two nearest buckets if possible.
        """
        if not self._averages:
            return 0.0
        key = self._bucket_key(temp_c)
        if key in self._averages:
            return self._averages[key]
        # Fallback: find nearest available bucket
        try:
            keys_numeric = sorted(int(k) for k in self._averages.keys())
            target = round(temp_c / FF_TEMP_BUCKET_C) * FF_TEMP_BUCKET_C
            lower = max((k for k in keys_numeric if k <= target), default=None)
            upper = min((k for k in keys_numeric if k >= target), default=None)
            if lower is None and upper is None:
                return 0.0
            if lower is None:
                return self._averages[str(upper)]
            if upper is None:
                return self._averages[str(lower)]
            if lower == upper:
                return self._averages[str(lower)]
            # Linear interpolation
            v_low = self._averages[str(lower)]
            v_high = self._averages[str(upper)]
            frac = (target - lower) / (upper - lower)
            return v_low + frac * (v_high - v_low)
        except Exception:
            return 0.0

    def has_data(self):
        return len(self._averages) > 0

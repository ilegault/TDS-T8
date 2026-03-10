"""
temp_ramp_pid.py
PURPOSE: PID controller and run-history for Temperature Ramp mode.

No GUI / tkinter imports — pure control/logic module.
"""

import json
import os


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

    def __init__(self, kp=0.005, ki=0.0005, kd=0.001,
                 output_min=0.0, output_max=1.0,
                 integral_windup_limit=50.0):
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
        self._integral = max(-self._windup_limit,
                             min(self._windup_limit, self._integral))

        derivative = (error - self._prev_error) / dt

        self._last_p_term = self._kp * error
        self._last_i_term = self._ki * self._integral
        self._last_d_term = self._kd * derivative
        raw_output = self._last_p_term + self._last_i_term + self._last_d_term

        clamped = max(self._output_min, min(self._output_max, raw_output))

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
        _defaults = {'kp': 0.005, 'ki': 0.0005, 'kd': 0.001}

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

"""
temp_ramp_pid.py
PURPOSE: PID controller and run-logging for Temperature Ramp mode.

No GUI / tkinter imports — pure control/logic module.
"""

import json
import os
import sys


# ── Soft-Start / Phase 1 constants ────────────────────────────────────────────
SOFT_START_THRESHOLD_C    = 150.0   # °C — TDS preheat target; soft-start hands off to PID Hold here
SOFT_START_VOLTAGE_STEP   = 0.010   # V per tick — how fast voltage climbs in Phase 1
SOFT_START_CURRENT_LIMIT  = 180.0   # A — pause voltage increase if current exceeds this
SOFT_START_RATE_CEILING   = 3.0     # K/min — cut voltage if heating too fast in Phase 1

# ── PID slew-rate limiter ─────────────────────────────────────────────────────
PID_MAX_VOLTAGE_STEP_V    = 0.050   # V per tick — max DAC0 change per PID update

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

    # FF-1 START — reconcile gain source of truth
    def __init__(self, kp: float, ki: float, kd: float,
                 output_min=0.0, output_max=6.0,
                 integral_windup_limit=30.0):
        """
        Args:
            kp: Proportional gain (very small — power supply is high-current).
            ki: Integral gain.
            kd: Derivative gain (0.005 — best oscillation result, 2026-06-30 run).
            output_min: Minimum clamped output (fraction of full power).
            output_max: Maximum clamped output (fraction of full power).
            integral_windup_limit: Clamp integral accumulator to ±this (K·s).
        """
        # FF-1 END
        self._kp = kp
        self._ki = ki
        self._kd = kd
        self._output_min = output_min
        self._output_max = output_max
        self._windup_limit = integral_windup_limit

        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_measurement = None
        self._prev_time = None
        self._prev_output = 0.0

        # Fix 1: rolling buffer for derivative smoothing
        self._temp_filter_size = 12   # ~6 seconds at 500 ms sample rate
        self._temp_buffer = []
        self._last_smoothed_temp = None

        # Debug: last computed P, I, D contributions
        self._last_p_term = 0.0
        self._last_i_term = 0.0
        self._last_d_term = 0.0

    def reset(self):
        """Reset integrator and history — call before starting a new run."""
        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_measurement = None
        self._prev_time = None
        self._prev_output = 0.0
        self._temp_buffer = []
        self._last_smoothed_temp = None
        self._last_p_term = 0.0
        self._last_i_term = 0.0
        self._last_d_term = 0.0

    def reset_bumpless(self, seed_output: float, current_time: float = None):
        """
        Re-initialise for a new block WITHOUT dropping the output to zero.

        Unlike reset(), which zeros the integrator (and, because compute()
        returns 0.0 on its first call, forces the output to 0 for a tick or
        more), this seeds the integrator so the controller's next output
        equals ``seed_output`` — the voltage already being commanded. That
        gives a bumpless transfer across block boundaries: no visible
        power-off/power-on glitch, so the heater and PID stay continuous.

        Stale derivative and timing history are still cleared so the new
        block does not inherit a rate-of-change term from the previous one.

        Args:
            seed_output:  Output value (volts) to hold across the transition —
                          normally the last commanded voltage.
            current_time: Monotonic timestamp to prime the loop timer with.
                          Priming it (instead of leaving it None) is what
                          stops compute()'s first call from returning 0.0.
        """
        seed = max(self._output_min, min(seed_output, self._output_max))

        # Seed the integrator so the I-term alone reproduces the held output,
        # respecting the same windup clamp compute() enforces.
        if self._ki > 1e-12:
            integral = seed / self._ki
            integral_limit = self._windup_limit / self._ki
            self._integral = max(-integral_limit, min(integral, integral_limit))
        else:
            self._integral = 0.0

        self._prev_error = 0.0
        self._prev_measurement = None
        self._prev_time = current_time
        self._prev_output = seed
        self._temp_buffer = []
        self._last_smoothed_temp = None
        self._last_p_term = 0.0
        self._last_i_term = self._ki * self._integral
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

        # Fix 2b: integral windup clamp expressed in voltage units.
        # Cap is on (ki * integral); clamp the raw integral accordingly.
        self._integral += error * dt
        if self._ki > 1e-12:
            integral_limit = self._windup_limit / self._ki
        else:
            integral_limit = float('inf')
        self._integral = max(-integral_limit, min(self._integral, integral_limit))

        # Fix 1: smooth temperature for derivative only (rolling mean).
        self._temp_buffer.append(measured_k)
        if len(self._temp_buffer) > self._temp_filter_size:
            self._temp_buffer.pop(0)
        smoothed_temp = sum(self._temp_buffer) / len(self._temp_buffer)

        # Derivative-on-measurement using smoothed temperature.
        if self._last_smoothed_temp is None:
            derivative = 0.0
        else:
            derivative = -(smoothed_temp - self._last_smoothed_temp) / dt
        self._last_smoothed_temp = smoothed_temp

        self._last_p_term = self._kp * error
        self._last_i_term = self._ki * self._integral
        self._last_d_term = self._kd * derivative
        raw_output = self._last_p_term + self._last_i_term + self._last_d_term

        # FF-6 START — per-tick dvdt gain scaling retired; feedforward handled by executor
        # (FeedforwardMap.voltage_for is added to v_out in program_executor._execute_block)
        # FF-6 END

        # Clamp output (0 to output_max — voltage must never go negative)
        clamped = max(self._output_min, min(raw_output, self._output_max))

        self._prev_error = error
        self._prev_measurement = measured_k
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

    def update_gains(self, kp: float, ki: float, kd: float,
                     output_max: float = None, windup_limit: float = None):
        """Update PID gains and optional limits (can be called between runs)."""
        self._kp = kp
        self._ki = ki
        self._kd = kd
        if output_max is not None:
            self._output_max = output_max
        if windup_limit is not None:
            self._windup_limit = windup_limit


# ── PID Run Logger ─────────────────────────────────────────────────────────────

class PIDRunLogger:
    """
    Persists completed TempRamp run records to logs/pid_runs.json.

    Each record captures performance metrics, the gains used, and auto-generated
    tuning suggestions — giving a clean review of every ramp after the fact.
    The log is kept at a fixed path inside the logs/ folder so the GUI can
    display it without any extra configuration.
    """

    LOG_FILENAME = "pid_runs.json"
    MAX_RUNS = 100  # keep the last N runs

    @staticmethod
    def _default_log_file() -> str:
        """Resolve logs/pid_runs.json relative to the exe (frozen) or project root (dev)."""
        if getattr(sys, 'frozen', False):
            appdata = os.environ.get('APPDATA', os.path.dirname(sys.executable))
            logs_dir = os.path.join(appdata, 'T8_DAQ_System', 'logs')
        else:
            # Two levels up from this file: t8_daq_system/control/ → project root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            logs_dir = os.path.join(project_root, 'logs')
        return os.path.join(logs_dir, PIDRunLogger.LOG_FILENAME)

    def __init__(self, log_file: str = None):
        self.log_file = log_file or self._default_log_file()
        self._runs = []
        self._load()

    # ── Private ────────────────────────────────────────────────────────────────

    def _load(self):
        """Load existing run log from disk; silently fall back to empty list."""
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._runs = data
        except Exception:
            self._runs = []

    def _generate_suggestions(self, record: dict) -> list:
        """Auto-generate tuning suggestions based on this run's metrics."""
        suggestions = []
        overshoot = record.get('overshoot_k', 0.0)
        oscillations = record.get('oscillation_count', 0)
        settling = record.get('settling_time_sec')
        target_rate = record.get('target_rate_k_per_min', 0.0)
        achieved_rate = record.get('achieved_mean_rate_k_per_min', 0.0)

        # Rate tracking accuracy
        if target_rate and target_rate > 0:
            rate_error_pct = abs(achieved_rate - target_rate) / target_rate * 100
            if rate_error_pct > 25:
                suggestions.append(
                    f"Rate tracking error {rate_error_pct:.0f}% — increase Ki to improve "
                    "steady-state following of the ramp setpoint."
                )
            elif rate_error_pct > 10:
                suggestions.append(
                    f"Minor rate tracking error ({rate_error_pct:.0f}%) — a small Ki increase "
                    "may tighten this up."
                )

        # Overshoot
        if overshoot > 10:
            suggestions.append(
                f"Large overshoot ({overshoot:.1f} K) — reduce Kp or increase Kd to damp "
                "the response."
            )
        elif overshoot > 5:
            suggestions.append(
                f"Moderate overshoot ({overshoot:.1f} K) — slight Kp reduction or small Kd "
                "increase should help."
            )

        # Oscillations
        if oscillations > 8:
            suggestions.append(
                f"High oscillation count ({oscillations}) — reduce Ki or increase Kd to "
                "damp ringing."
            )
        elif oscillations > 4:
            suggestions.append(
                f"Some oscillations ({oscillations}) — a small Kd increase may smooth the "
                "response without sacrificing speed."
            )

        # Settling
        if settling is None:
            suggestions.append(
                "Temperature never settled within ±2 K — gains may need significant "
                "re-tuning or the ramp rate exceeds what the heater can follow."
            )
        elif settling > 120:
            suggestions.append(
                f"Slow settling ({settling:.0f} s) — increase Ki to reduce steady-state error "
                "and speed up convergence."
            )

        if not suggestions:
            suggestions.append(
                "Performance looks good — rate tracking, overshoot, and settling all within "
                "acceptable bounds. Current gains appear well-tuned for this ramp rate."
            )

        return suggestions

    # ── Public API ─────────────────────────────────────────────────────────────

    def save_run(self, run_record: dict):
        """
        Append a completed run record (with auto-suggestions) and write to disk.

        Expected keys in run_record:
            timestamp (str, ISO)
            target_rate_k_per_min (float)
            achieved_mean_rate_k_per_min (float)
            overshoot_k (float)
            settling_time_sec (float | None)
            oscillation_count (int)
            duration_sec (float)
            kp_used (float)
            ki_used (float)
            kd_used (float)
        """
        record = dict(run_record)
        record['suggestions'] = self._generate_suggestions(record)

        self._runs.append(record)
        if len(self._runs) > self.MAX_RUNS:
            self._runs = self._runs[-self.MAX_RUNS:]

        # Ensure the logs/ directory exists
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        try:
            with open(self.log_file, 'w') as f:
                json.dump(self._runs, f, indent=2)
        except Exception as exc:
            print(f"[PIDRunLogger] Could not write log: {exc}")

    def get_all_runs(self) -> list:
        """Return a copy of all stored run records, newest last."""
        return list(self._runs)

    def get_log_path(self) -> str:
        """Return the absolute path to the log file."""
        return os.path.abspath(self.log_file)

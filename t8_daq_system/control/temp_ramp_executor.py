"""
temp_ramp_executor.py
PURPOSE: Background-thread execution engine for Temperature Ramp PID mode.

Reads live thermocouple data, runs a PID loop, and drives the Keysight N5700
via DAC outputs to achieve a user-specified temperature ramp rate (K/min).

No GUI / tkinter imports — all GUI updates are routed through on_status_callback
which the caller (main_window) must forward to the main thread via root.after().
"""

import threading
import time
import random

from .temp_ramp_pid import (PIDController, TempRampHistory, FeedforwardTable,
                             SOFT_START_THRESHOLD_C, SOFT_START_VOLTAGE_STEP,
                             SOFT_START_CURRENT_LIMIT, SOFT_START_RATE_CEILING,
                             PID_MAX_VOLTAGE_STEP_V)

# ── Module-level constants ─────────────────────────────────────────────────────

TICK_INTERVAL_SEC    = 2.0      # PID update rate — slow for W->SiC->W thermal mass
PHASE1_COMPLETE_TEMP_C    = SOFT_START_THRESHOLD_C  # alias for readability
DTEMP_SMOOTHING_ALPHA     = 0.2   # low-pass filter for measured dT/dt (0=heavy smooth, 1=raw)
MAX_VOLTAGE          = 6.0      # Keysight N5700 max output voltage
MAX_CURRENT          = 180.0    # Keysight N5700 max output current
DAC_MAX_VOLTS        = 5.0      # T8 DAC output ceiling (0–5 V)
MIN_RAMP_RATE_K_PER_MIN = 0.05  # Safety floor — ignore noise below this
PRACTICE_THERMAL_MASS   = 120.0  # Seconds for simulated temperature to respond

# ── Debug / Safety Configuration ─────────────────────────────────────────────
# Set DEBUG_TEMP_RAMP = True to print PID internals every tick to the terminal.
# Set to False before real hardware runs if terminal output becomes too verbose.
DEBUG_TEMP_RAMP = False

# Current limit fraction for DAC1 (Pin 10, Current Program) during a TempRamp run.
#
# TUNGSTEN (positive TCR, 17:1 resistance ratio cold-to-hot):
# Must be 1.0 (= full 5.0V DAC output = 180A ceiling).
# Tungsten runs in CV mode. As it heats, resistance rises 17x and current
# self-limits naturally via Ohm's law. Artificially capping DAC1 below full
# scale causes the Keysight to flip into CC mode while tungsten is still cold,
# which fights the PID voltage ramp.
#
# The CV→CC crossover seen when using front panel knobs is NORMAL Keysight
# behavior (supply hits the current ceiling and switches modes). Keeping DAC1
# at 1.0 prevents this from happening during a software-controlled ramp.
#
# Only reduce below 1.0 for NEGATIVE TCR materials (some ceramics, VO2) where
# fast current clamping is required to prevent thermal runaway.
TEMP_RAMP_CURRENT_LIMIT_FRACTION = 1.0  # 1.0 = 180A full scale — correct for tungsten

# ── Safe Test Mode limits ──────────────────────────────────────────────────────
# When safe_test_mode=True is passed to TempRampExecutor, these override the
# normal MAX_VOLTAGE and TEMP_RAMP_CURRENT_LIMIT_FRACTION values.
SAFE_TEST_MAX_VOLTAGE            = 1.0   # V — hard ceiling in safe test mode
SAFE_TEST_CURRENT_LIMIT_FRACTION = 0.05  # × 180 A = 9 A ceiling in safe test mode


class TempRampExecutor:
    """
    Executes a list of Ramp/Hold blocks using PID temperature control.

    Each block dict must contain:
        'type'           : "Ramp" or "Hold"
        'duration_sec'   : float > 0  (seconds)
        'rate_k_per_min' : float       (only used for Ramp blocks)

    The executor runs in a daemon thread.  Status updates are delivered to the
    caller via on_status_callback(status_dict) which is called from that thread;
    the caller is responsible for marshalling back to the main thread.
    """

    def __init__(self, power_supply, get_temperature_celsius_fn,
                 history: TempRampHistory,
                 on_status_callback=None,
                 practice_mode=False,
                 safe_test_mode=False):
        """
        Args:
            power_supply:
                ps_controller instance (real KeysightAnalogController or Mock).
                Pass None to run without hardware output (useful for unit tests).
            get_temperature_celsius_fn:
                Zero-argument callable returning the most recent TC reading in °C,
                or None if no reading is available.
            history:
                TempRampHistory instance for gain learning / persistence.
            on_status_callback:
                Optional callable(status_dict).  Called each tick.  status_dict
                contains: elapsed_sec, current_temp_k, setpoint_k, pid_output,
                block_index, total_blocks, saturated_warning (bool),
                tc_missing_error (bool).
            practice_mode:
                If True, temperature is simulated (no real TC needed, no real
                power supply output).
        """
        self._power_supply = power_supply
        self._get_temp_fn = get_temperature_celsius_fn
        self._history = history
        self._on_status = on_status_callback
        self.practice_mode = practice_mode
        self.safe_test_mode = safe_test_mode

        self._blocks = []
        self._pid = PIDController()
        self._thread = None
        self._running = False
        self._lock = threading.Lock()

        # Simulated temperature for practice mode (Kelvin)
        self._practice_temp_k = None

        # Log of (elapsed_sec, setpoint_k, actual_k, pid_output) per tick
        self._run_log = []

        # Last computed DAC voltages and derived real-world V/I values.
        # Written every tick by _run_loop; read by DataAcquisition for
        # practice-mode power supply simulation.
        self._last_voltage_dac = 0.0
        self._last_current_dac = 0.0
        self._last_voltage_setpoint_v = 0.0
        self._last_current_limit_a = 0.0

        # Two-phase smart PID state
        self._feedforward = FeedforwardTable()
        self._phase = 1               # 1 = soft-start, 2 = PID
        self._soft_start_voltage = 0.0  # current voltage during Phase 1
        self._last_temp_for_rate = None
        self._last_temp_time = None
        self._smoothed_dT_dt = 0.0    # K/min, low-pass filtered
        self._prev_voltage_output = 0.0  # for slew-rate limiting in Phase 2

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_blocks(self, blocks: list) -> bool:
        """
        Validate and store the block list.

        Returns True if valid, False otherwise (caller should show an error).
        """
        if not blocks:
            print("[TempRampExecutor] load_blocks: empty block list.")
            return False

        for i, block in enumerate(blocks):
            if not isinstance(block, dict):
                print(f"[TempRampExecutor] Block {i+1} is not a dict.")
                return False
            if block.get('type') not in ("Ramp", "Hold"):
                print(f"[TempRampExecutor] Block {i+1}: 'type' must be 'Ramp' or 'Hold'.")
                return False
            try:
                dur = float(block['duration_sec'])
                if dur <= 0:
                    raise ValueError("non-positive duration")
            except (KeyError, TypeError, ValueError) as exc:
                print(f"[TempRampExecutor] Block {i+1}: invalid duration_sec — {exc}")
                return False
            if 'rate_k_per_min' not in block:
                print(f"[TempRampExecutor] Block {i+1}: missing 'rate_k_per_min'.")
                return False
            try:
                float(block['rate_k_per_min'])
            except (TypeError, ValueError):
                print(f"[TempRampExecutor] Block {i+1}: 'rate_k_per_min' is not numeric.")
                return False

        self._blocks = list(blocks)
        return True

    def start(self) -> bool:
        """
        Start the PID execution thread.

        Returns False if already running.
        """
        with self._lock:
            if self._running:
                return False

            self._pid.reset()
            self._run_log = []

            # Reset two-phase state for fresh run
            self._phase = 1
            self._soft_start_voltage = 0.0
            self._last_temp_for_rate = None
            self._last_temp_time = None
            self._smoothed_dT_dt = 0.0
            self._prev_voltage_output = 0.0

            # Initialise practice temperature from live reading or default to 20°C
            if self.practice_mode and self._practice_temp_k is None:
                tc_k = self._get_temp_fn()
                if tc_k is not None:
                    self._practice_temp_k = tc_k  # Already in Kelvin
                else:
                    self._practice_temp_k = 293.15  # 20°C fallback

            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop, daemon=True, name="TempRampPID"
            )
            self._thread.start()
            return True

    def stop(self):
        """Signal the PID thread to stop and wait for it to exit."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)

        # Zero the power supply as a safety measure
        if self._power_supply is not None:
            try:
                self._power_supply.set_voltage(0.0)
                self._power_supply.set_current(0.0)
            except Exception:
                pass

    def is_running(self) -> bool:
        """Return True if the PID thread is alive."""
        return (self._running
                and self._thread is not None
                and self._thread.is_alive())

    def get_run_log(self) -> list:
        """Return a copy of the per-tick run log."""
        return list(self._run_log)

    # ── Private: two-phase voltage helpers ────────────────────────────────────

    def _compute_phase1_voltage(self, current_temp_c, measured_current_a, measured_dT_dt_k_per_min):
        """
        Soft-start voltage logic for Phase 1 (room temp → SOFT_START_THRESHOLD_C).
        Returns the new voltage setpoint (V) to command to DAC0.

        Rules:
        - If current > SOFT_START_CURRENT_LIMIT → hold voltage (don't increase)
        - If measured dT/dt > SOFT_START_RATE_CEILING → decrease voltage one step
        - Otherwise → increase voltage by SOFT_START_VOLTAGE_STEP
        """
        v = self._soft_start_voltage

        if measured_current_a > SOFT_START_CURRENT_LIMIT:
            # Current too high — hold
            if DEBUG_TEMP_RAMP:
                print(f"[Phase1] Current {measured_current_a:.1f}A > limit {SOFT_START_CURRENT_LIMIT}A — holding V={v:.3f}V")
        elif measured_dT_dt_k_per_min > SOFT_START_RATE_CEILING:
            # Heating too fast — back off one step
            v = max(0.0, v - SOFT_START_VOLTAGE_STEP)
            if DEBUG_TEMP_RAMP:
                print(f"[Phase1] dT/dt {measured_dT_dt_k_per_min:.2f} K/min too fast — reduced V to {v:.3f}V")
        else:
            # Safe to increase
            v = min(MAX_VOLTAGE, v + SOFT_START_VOLTAGE_STEP)
            if DEBUG_TEMP_RAMP:
                print(f"[Phase1] Increasing V to {v:.3f}V  (T={current_temp_c:.1f}°C, I={measured_current_a:.1f}A)")

        self._soft_start_voltage = v
        return v

    def _apply_slew_limit(self, new_voltage, previous_voltage):
        """
        Prevents the PID from commanding a voltage jump larger than PID_MAX_VOLTAGE_STEP_V
        per tick. This protects against integral windup causing a sudden surge.
        """
        delta = new_voltage - previous_voltage
        if abs(delta) > PID_MAX_VOLTAGE_STEP_V:
            clamped = previous_voltage + (PID_MAX_VOLTAGE_STEP_V * (1 if delta > 0 else -1))
            if DEBUG_TEMP_RAMP:
                print(f"[SlewLimit] Clamped ΔV from {delta:+.4f}V to {clamped - previous_voltage:+.4f}V")
            return clamped
        return new_voltage

    # ── Private: core loop ─────────────────────────────────────────────────────

    def _run_loop(self):
        """Main PID execution loop — runs in daemon thread."""
        run_start_time    = time.time()
        current_block_idx = 0
        block_start_time  = run_start_time

        # Determine initial temperature
        if self.practice_mode:
            initial_temp_k = self._practice_temp_k
        else:
            tc_k = self._get_temp_fn()
            initial_temp_k = tc_k if tc_k is not None else 293.15  # Already in Kelvin

        block_start_temp_k = initial_temp_k
        current_temp_k     = initial_temp_k

        # Safety counters
        consecutive_none_tc   = 0
        consecutive_saturated = 0

        while self._running:
            loop_start   = time.time()
            elapsed_total = loop_start - run_start_time

            # ── 1. Determine current block ─────────────────────────────────────
            block           = self._blocks[current_block_idx]
            elapsed_in_block = loop_start - block_start_time

            if elapsed_in_block >= block['duration_sec']:
                current_block_idx += 1
                if current_block_idx >= len(self._blocks):
                    break  # All blocks completed normally

                block             = self._blocks[current_block_idx]
                block_start_time  = loop_start
                elapsed_in_block  = 0.0
                block_start_temp_k = current_temp_k

            # ── 2. Compute setpoint_k ──────────────────────────────────────────
            if block['type'] == "Hold":
                setpoint_k = block_start_temp_k
            else:
                rate_k_per_sec = float(block['rate_k_per_min']) / 60.0
                setpoint_k = block_start_temp_k + rate_k_per_sec * elapsed_in_block

            # ── 3. Read / simulate temperature ────────────────────────────────
            if self.practice_mode:
                current_temp_k = self._simulate_practice_temp(setpoint_k, loop_start)
                consecutive_none_tc = 0
            else:
                tc_k = self._get_temp_fn()
                if tc_k is None:
                    consecutive_none_tc += 1
                    if consecutive_none_tc >= 5:
                        # No TC for 5 consecutive ticks (10 s) — abort safely
                        self._running = False
                        if self._on_status:
                            self._on_status({
                                'elapsed_sec':    elapsed_total,
                                'current_temp_k': current_temp_k,
                                'setpoint_k':     setpoint_k,
                                'pid_output':     0.0,
                                'block_index':    current_block_idx,
                                'total_blocks':   len(self._blocks),
                                'saturated_warning': False,
                                'tc_missing_error':  True,
                            })
                        break
                    # Freeze block timer so the setpoint doesn't race ahead
                    # while the TC is missing — prevents overshoot on reconnect.
                    block_start_time += TICK_INTERVAL_SEC
                    time.sleep(TICK_INTERVAL_SEC)
                    continue
                else:
                    consecutive_none_tc = 0
                    current_temp_k = tc_k  # Already in Kelvin from get_tc_kelvin_by_name()

            # ── 4. Compute smoothed dT/dt ──────────────────────────────────────
            current_temp_c = current_temp_k - 273.15
            now = loop_start

            if self._last_temp_for_rate is not None and self._last_temp_time is not None:
                dt_sec = now - self._last_temp_time
                if dt_sec > 0.01:
                    raw_dT_dt = ((current_temp_k - self._last_temp_for_rate) / dt_sec) * 60.0
                    self._smoothed_dT_dt = (DTEMP_SMOOTHING_ALPHA * raw_dT_dt
                                             + (1.0 - DTEMP_SMOOTHING_ALPHA) * self._smoothed_dT_dt)
            self._last_temp_for_rate = current_temp_k
            self._last_temp_time = now

            # ── 5. Read current from power supply ──────────────────────────────
            measured_current = 0.0
            try:
                if self._power_supply is not None:
                    measured_current = self._power_supply.get_current()
            except Exception:
                pass

            # ── 6. Select active limits based on safe_test_mode ───────────────
            if self.safe_test_mode:
                _active_max_v  = SAFE_TEST_MAX_VOLTAGE
                _active_i_frac = SAFE_TEST_CURRENT_LIMIT_FRACTION
            else:
                _active_max_v  = MAX_VOLTAGE
                _active_i_frac = TEMP_RAMP_CURRENT_LIMIT_FRACTION

            # ── 7. Phase determination ─────────────────────────────────────────
            if self._phase == 1 and current_temp_c >= PHASE1_COMPLETE_TEMP_C:
                self._phase = 2
                # Seed slew limiter with soft-start voltage to avoid a jump
                self._prev_voltage_output = self._soft_start_voltage
                print(f"[Phase] Switched to Phase 2 (PID) at T={current_temp_c:.1f}°C")

            # ── 8. Phase 1: Soft-Start ─────────────────────────────────────────
            pid_output = 0.0
            if self._phase == 1:
                voltage_cmd_v = self._compute_phase1_voltage(
                    current_temp_c, measured_current, self._smoothed_dT_dt
                )
                # Clamp to active max (handles safe_test_mode)
                voltage_cmd_v = min(voltage_cmd_v, _active_max_v)
                if not self.practice_mode:
                    self._feedforward.update(current_temp_c, voltage_cmd_v)

            # ── 9. Phase 2: Feedforward + PID ─────────────────────────────────
            else:
                # Feedforward lookup (0.0 on first run — pure PID)
                ff_voltage = self._feedforward.lookup(current_temp_c)

                # PID update — output is 0-1 fraction, scaled to voltage
                pid_output = self._pid.compute(setpoint_k, current_temp_k, loop_start)
                pid_correction_v = pid_output * _active_max_v  # scale to supply volts

                raw_voltage = max(0.0, min(_active_max_v, ff_voltage + pid_correction_v))

                # Apply slew-rate limiter
                voltage_cmd_v = self._apply_slew_limit(raw_voltage, self._prev_voltage_output)
                self._prev_voltage_output = voltage_cmd_v

                if not self.practice_mode:
                    self._feedforward.update(current_temp_c, voltage_cmd_v)

            # ── 10. Convert voltage_cmd_v to DAC voltages (0–5 V range) ───────
            #
            # DAC0 → Pin 9 (Voltage Program): supply_v → dac_v via linear scale.
            voltage_dac = min((voltage_cmd_v / MAX_VOLTAGE) * DAC_MAX_VOLTS, DAC_MAX_VOLTS)

            # DAC1 → Pin 10 (Current Program): FIXED ceiling, NOT tied to pid_output.
            current_dac = min(_active_i_frac * DAC_MAX_VOLTS, DAC_MAX_VOLTS)

            # Derive real-world values for status reporting and practice simulation
            voltage_setpoint_v = (voltage_dac / DAC_MAX_VOLTS) * MAX_VOLTAGE
            current_limit_a    = (current_dac / DAC_MAX_VOLTS) * MAX_CURRENT

            # Cache on instance so DataAcquisition can read from outside this thread
            self._last_voltage_dac        = voltage_dac
            self._last_current_dac        = current_dac
            self._last_voltage_setpoint_v = voltage_setpoint_v
            self._last_current_limit_a    = current_limit_a

            # ── 11. Safety: hard DAC ceiling ───────────────────────────────────
            if voltage_dac > DAC_MAX_VOLTS or current_dac > DAC_MAX_VOLTS:
                print(f"[TempRampExecutor] CRITICAL: DAC ceiling exceeded "
                      f"(V={voltage_dac:.3f}, I={current_dac:.3f}). Stopping.")
                self._running = False
                break

            # ── 12. Safety: PID saturation warning ────────────────────────────
            saturation_fraction = voltage_cmd_v / _active_max_v if _active_max_v > 0 else 0.0
            if saturation_fraction > 0.95:
                consecutive_saturated += 1
            else:
                consecutive_saturated = 0

            saturated_warning = consecutive_saturated >= 15  # 30 seconds
            if saturated_warning and consecutive_saturated == 30:
                print("[TempRampExecutor] WARNING: PID output saturated — "
                      "possible runaway. Check thermocouple.")

            # ── 13. Send to power supply (live mode only) ──────────────────────
            if self._power_supply is not None and not self.practice_mode:
                try:
                    self._power_supply.set_voltage(voltage_dac)
                    self._power_supply.set_current(current_dac)
                except Exception as exc:
                    print(f"[TempRampExecutor] PS write error: {exc}")

            # ── 10. Log tick ───────────────────────────────────────────────────
            self._run_log.append(
                (elapsed_total, setpoint_k, current_temp_k, pid_output)
            )

            # ── 11. Status callback ────────────────────────────────────────────
            if self._on_status:
                self._on_status({
                    'elapsed_sec':       elapsed_total,
                    'current_temp_k':    current_temp_k,
                    'setpoint_k':        setpoint_k,
                    'pid_output':        pid_output,
                    'block_index':       current_block_idx,
                    'total_blocks':      len(self._blocks),
                    'saturated_warning': saturated_warning,
                    'tc_missing_error':  False,
                    # V/I values for GUI display and practice-mode simulation
                    'voltage_setpoint_v': voltage_setpoint_v,
                    'current_limit_a':   current_limit_a,
                    'voltage_dac':       voltage_dac,
                    'current_dac':       current_dac,
                    'error_k':           setpoint_k - current_temp_k,
                    'pid_debug':         self._pid.get_debug_terms(),
                    'safe_test_mode':    self.safe_test_mode,
                })

            # ── 11b. Debug terminal output ────────────────────────────────────
            if DEBUG_TEMP_RAMP:
                _dbg = self._pid.get_debug_terms()
                _sat = (pid_output >= 1.0 - 1e-6) or (pid_output <= 1e-6 and elapsed_total > 1.0)
                print(
                    f"[TempRamp DBG] "
                    f"t={elapsed_total:7.1f}s | "
                    f"SP={setpoint_k:.2f}K T={current_temp_k:.2f}K "
                    f"err={setpoint_k - current_temp_k:+.2f}K | "
                    f"P={_dbg['p_term']:+.5f} "
                    f"I={_dbg['i_term']:+.5f} "
                    f"D={_dbg['d_term']:+.5f} "
                    f"accum={_dbg['integral_accumulator']:+.3f} | "
                    f"out={pid_output:.4f}{' ⚠SAT' if _sat else ''} | "
                    f"V_set={voltage_setpoint_v:.4f}V "
                    f"I_lim={current_limit_a:.2f}A | "
                    f"DAC0={voltage_dac:.4f}V DAC1={current_dac:.4f}V"
                )

            # ── 12. Sleep remainder of tick ────────────────────────────────────
            elapsed_tick = time.time() - loop_start
            sleep_time   = max(0.0, TICK_INTERVAL_SEC - elapsed_tick)
            time.sleep(sleep_time)

        # ── Post-loop teardown ─────────────────────────────────────────────────
        self._running = False
        self._save_run_to_history()

        # Save feedforward learning data for next run
        if not self.practice_mode:
            self._feedforward.save()
            print("[FeedforwardTable] Run data saved for future feedforward use.")

        if self._power_supply is not None:
            try:
                self._power_supply.set_voltage(0.0)
                self._power_supply.set_current(0.0)
            except Exception:
                pass

    # ── Private: practice-mode temperature simulation ──────────────────────────

    def _simulate_practice_temp(self, setpoint_k: float, now: float) -> float:
        """
        First-order thermal lag toward setpoint with small Gaussian noise.

        Uses PRACTICE_THERMAL_MASS as the time constant (seconds).
        """
        if self._practice_temp_k is None:
            self._practice_temp_k = setpoint_k

        delta = ((setpoint_k - self._practice_temp_k)
                 * (TICK_INTERVAL_SEC / PRACTICE_THERMAL_MASS))
        self._practice_temp_k += delta + random.gauss(0, 0.05)
        return self._practice_temp_k

    # ── Private: persist run to history ───────────────────────────────────────

    def _save_run_to_history(self):
        """Compute performance metrics from the run log and persist them."""
        if len(self._run_log) < 5:
            return  # Too short to be useful

        import datetime

        # Compute mean ramp rate: slope of actual_k vs elapsed_sec × 60
        first = self._run_log[0]
        last  = self._run_log[-1]
        elapsed_span = last[0] - first[0]
        if elapsed_span <= 0:
            return

        achieved_rate = (last[2] - first[2]) / elapsed_span * 60.0  # K/min

        # Compute peak overshoot: max(actual_k - setpoint_k)
        overshoot_k = max(
            (entry[2] - entry[1]) for entry in self._run_log
        )

        # Target rate: from the first Ramp block (0.0 if all Hold)
        target_rate = 0.0
        for block in self._blocks:
            if block['type'] == "Ramp":
                target_rate = float(block['rate_k_per_min'])
                break

        record = {
            'timestamp':                    datetime.datetime.now().isoformat(),
            'target_rate_k_per_min':        target_rate,
            'achieved_mean_rate_k_per_min': achieved_rate,
            'overshoot_k':                  overshoot_k,
            'duration_sec':                 elapsed_span,
            'kp_used':                      self._pid._kp,
            'ki_used':                      self._pid._ki,
            'kd_used':                      self._pid._kd,
        }

        try:
            self._history.save_run(record)
            print(f"[TempRampExecutor] Run saved to history — "
                  f"rate={achieved_rate:.2f} K/min, overshoot={overshoot_k:.2f} K")
        except Exception as exc:
            print(f"[TempRampExecutor] Failed to save run: {exc}")

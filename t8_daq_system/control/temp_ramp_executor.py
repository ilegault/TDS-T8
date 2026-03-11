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

from .temp_ramp_pid import PIDController, TempRampHistory, celsius_to_kelvin

# ── Module-level constants ─────────────────────────────────────────────────────

TICK_INTERVAL_SEC    = 0.5      # PID update rate
MAX_VOLTAGE          = 6.0      # Keysight N5700 max output voltage
MAX_CURRENT          = 180.0    # Keysight N5700 max output current
DAC_MAX_VOLTS        = 5.0      # T8 DAC output ceiling (0–5 V)
MIN_RAMP_RATE_K_PER_MIN = 0.05  # Safety floor — ignore noise below this
PRACTICE_THERMAL_MASS   = 120.0  # Seconds for simulated temperature to respond

# ── Debug / Safety Configuration ─────────────────────────────────────────────
# Set DEBUG_TEMP_RAMP = True to print PID internals every tick to the terminal.
# Set to False before real hardware runs if terminal output becomes too verbose.
DEBUG_TEMP_RAMP = True

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

            # Initialise practice temperature from live reading or default to 20°C
            if self.practice_mode and self._practice_temp_k is None:
                tc_c = self._get_temp_fn()
                if tc_c is not None:
                    self._practice_temp_k = celsius_to_kelvin(tc_c)
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
            tc_c = self._get_temp_fn()
            initial_temp_k = celsius_to_kelvin(tc_c) if tc_c is not None else 293.15

        block_start_temp_k = initial_temp_k
        current_temp_k     = initial_temp_k

        # Safety counters
        consecutive_none_tc   = 0
        consecutive_saturated = 0

        # Startup ramp limiter: track ticks within first 10 of each Ramp block
        ramp_block_tick_count = 0
        in_startup_phase = True

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
                ramp_block_tick_count = 0
                in_startup_phase  = True

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
                tc_c = self._get_temp_fn()
                if tc_c is None:
                    consecutive_none_tc += 1
                    if consecutive_none_tc >= 5:
                        # No TC for 5 consecutive ticks — abort safely
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
                    # Skip this tick but keep the loop alive
                    time.sleep(TICK_INTERVAL_SEC)
                    continue
                else:
                    consecutive_none_tc = 0
                    current_temp_k = celsius_to_kelvin(tc_c)

            # ── 4. PID compute ─────────────────────────────────────────────────
            pid_output = self._pid.compute(setpoint_k, current_temp_k, loop_start)

            # ── 5. Startup ramp limiter (first 10 ticks of a Ramp block) ──────
            if block['type'] == "Ramp":
                ramp_block_tick_count += 1
                if ramp_block_tick_count <= 10:
                    pid_output = min(pid_output, 0.1)
                else:
                    in_startup_phase = False
            else:
                in_startup_phase = False

            # ── 6. Convert PID output to DAC voltages (0–5 V range) ───────────
            #
            # Select active limits based on safe_test_mode
            if self.safe_test_mode:
                _active_max_v  = SAFE_TEST_MAX_VOLTAGE
                _active_i_frac = SAFE_TEST_CURRENT_LIMIT_FRACTION
            else:
                _active_max_v  = MAX_VOLTAGE
                _active_i_frac = TEMP_RAMP_CURRENT_LIMIT_FRACTION

            # DAC0 → Pin 9 (Voltage Program): PID output scaled to active voltage ceiling.
            # In normal mode 1.0 → 5.0 V DAC → 6.0 V supply.
            # In safe mode 1.0 → (1.0/6.0)×5.0 = 0.833 V DAC → 1.0 V supply.
            voltage_dac = min(pid_output * (_active_max_v / MAX_VOLTAGE) * DAC_MAX_VOLTS,
                              DAC_MAX_VOLTS)

            # DAC1 → Pin 10 (Current Program): FIXED ceiling, NOT tied to pid_output.
            current_dac = min(_active_i_frac * DAC_MAX_VOLTS, DAC_MAX_VOLTS)

            # Derive real-world values for status reporting and practice simulation
            voltage_setpoint_v = (voltage_dac / DAC_MAX_VOLTS) * MAX_VOLTAGE
            current_limit_a    = (current_dac / DAC_MAX_VOLTS) * MAX_CURRENT

            # Cache on instance so DataAcquisition can read from outside this thread
            self._last_voltage_dac      = voltage_dac
            self._last_current_dac      = current_dac
            self._last_voltage_setpoint_v = voltage_setpoint_v
            self._last_current_limit_a  = current_limit_a

            # ── 7. Safety: hard DAC ceiling ────────────────────────────────────
            if voltage_dac > DAC_MAX_VOLTS or current_dac > DAC_MAX_VOLTS:
                print(f"[TempRampExecutor] CRITICAL: DAC ceiling exceeded "
                      f"(V={voltage_dac:.3f}, I={current_dac:.3f}). Stopping.")
                self._running = False
                break

            # ── 8. Safety: PID saturation warning ─────────────────────────────
            if pid_output > 0.95:
                consecutive_saturated += 1
            else:
                consecutive_saturated = 0

            saturated_warning = consecutive_saturated >= 30  # 15 seconds
            if saturated_warning and consecutive_saturated == 30:
                print("[TempRampExecutor] WARNING: PID output saturated — "
                      "possible runaway. Check thermocouple.")

            # ── 9. Send to power supply (live mode only) ───────────────────────
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

"""
Ramp Executor for Power Supply Control.

Runs ramp profiles in a background thread, calculating interpolated setpoints
and sending voltage commands to the power supply controller.
"""

import threading
import time
from typing import Optional, Callable
from enum import Enum

from .ramp_profile import RampProfile, ControlMode


class ExecutorState(Enum):
    """States for the ramp executor."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    ABORTED = "aborted"


class RampExecutor:
    """
    Executes ramp profiles in a background thread.

    The executor manages the timing and interpolation of voltage setpoints,
    sending commands to the power supply at regular intervals. It supports
    start, stop, pause, and resume operations.

    Callbacks can be registered to receive updates on:
    - Setpoint changes
    - Step transitions
    - Profile completion
    - Errors
    """

    def __init__(self, power_supply_controller=None, update_interval_ms: int = 100):
        """
        Initialize the ramp executor.

        Args:
            power_supply_controller: PowerSupplyController instance for sending commands.
                                    If None, executor runs in simulation mode.
            update_interval_ms: How often to update setpoint in milliseconds (default 100ms)
        """
        self.power_supply = power_supply_controller
        self.update_interval_sec = update_interval_ms / 1000.0

        # Current state
        self._state = ExecutorState.IDLE
        self._profile: Optional[RampProfile] = None
        self._start_time: Optional[float] = None
        self._pause_time: Optional[float] = None
        self._paused_elapsed: float = 0.0
        self._current_setpoint: float = 0.0
        self._current_step_index: int = 0
        self._error_message: str = ""

        # Thread management
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._lock = threading.RLock()

        # Callbacks
        self._on_setpoint_change: Optional[Callable[[float], None]] = None
        self._on_step_change: Optional[Callable[[int, int], None]] = None
        self._on_complete: Optional[Callable[[], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_state_change: Optional[Callable[[ExecutorState], None]] = None

    @property
    def state(self) -> ExecutorState:
        """Get current executor state."""
        with self._lock:
            return self._state

    @property
    def current_setpoint(self) -> float:
        """Get current voltage setpoint."""
        with self._lock:
            return self._current_setpoint

    @property
    def current_step(self) -> int:
        """Get current step index (0-based)."""
        with self._lock:
            return self._current_step_index

    @property
    def profile(self) -> Optional[RampProfile]:
        """Get the currently loaded profile."""
        with self._lock:
            return self._profile

    @property
    def error_message(self) -> str:
        """Get the last error message."""
        with self._lock:
            return self._error_message

    def _set_state(self, new_state: ExecutorState) -> None:
        """Set state and trigger callback."""
        with self._lock:
            self._state = new_state
        if self._on_state_change:
            try:
                self._on_state_change(new_state)
            except Exception:
                pass

    def load_profile(self, profile: RampProfile) -> bool:
        """
        Load a ramp profile for execution.

        Args:
            profile: RampProfile to execute

        Returns:
            True if profile loaded successfully, False otherwise
        """
        if self.is_running():
            print("Cannot load profile while executor is running")
            return False

        is_valid, errors = profile.validate()
        if not is_valid:
            print(f"Invalid profile: {errors}")
            return False

        with self._lock:
            self._profile = profile
            self._current_step_index = 0
            self._current_setpoint = profile.start_voltage
            self._error_message = ""

        self._set_state(ExecutorState.IDLE)
        return True

    def set_power_supply(self, power_supply_controller) -> None:
        """
        Set or update the power supply controller.

        Args:
            power_supply_controller: PowerSupplyController instance
        """
        if self.is_running():
            print("Cannot change power supply while executor is running")
            return
        self.power_supply = power_supply_controller

    def is_running(self) -> bool:
        """Check if executor is currently running (not paused)."""
        return self.state == ExecutorState.RUNNING

    def is_active(self) -> bool:
        """Check if executor is running or paused (profile in progress)."""
        return self.state in [ExecutorState.RUNNING, ExecutorState.PAUSED]

    def get_elapsed_time(self) -> float:
        """
        Get elapsed time since profile start (excluding paused time).

        Returns:
            Elapsed time in seconds, or 0 if not running
        """
        with self._lock:
            if self._start_time is None:
                return 0.0
            if self._state == ExecutorState.PAUSED and self._pause_time is not None:
                return self._pause_time - self._start_time - self._paused_elapsed
            return time.time() - self._start_time - self._paused_elapsed

    def get_progress(self) -> float:
        """
        Get profile progress as a percentage.

        Returns:
            Progress from 0.0 to 100.0
        """
        with self._lock:
            if self._profile is None:
                return 0.0
            total_duration = self._profile.get_total_duration()
            if total_duration <= 0:
                return 100.0
        elapsed = self.get_elapsed_time()
        return min(100.0, (elapsed / total_duration) * 100.0)

    def get_remaining_time(self) -> float:
        """
        Get remaining time in the profile.

        Returns:
            Remaining time in seconds
        """
        with self._lock:
            if self._profile is None:
                return 0.0
            total_duration = self._profile.get_total_duration()
        elapsed = self.get_elapsed_time()
        return max(0.0, total_duration - elapsed)

    def get_current_setpoint(self) -> float:
        """
        Get the current voltage setpoint.

        Returns:
            Current setpoint in Volts
        """
        with self._lock:
            return self._current_setpoint

    def start(self) -> bool:
        """
        Start executing the loaded profile.

        Returns:
            True if started successfully, False otherwise
        """
        with self._lock:
            if self._profile is None:
                print("No profile loaded")
                return False

            if self._state == ExecutorState.RUNNING:
                print("Executor already running")
                return False

            if self._state == ExecutorState.PAUSED:
                # Resume from pause
                return self.resume()

        # Set initial limits if power supply is connected
        if self.power_supply:
            try:
                with self._lock:
                    is_current_mode = self._profile.control_mode == ControlMode.CURRENT.value
                    current_limit = self._profile.current_limit
                    voltage_limit = self._profile.voltage_limit
                
                if is_current_mode:
                    # In current mode, we ramp current and set a voltage limit
                    self.power_supply.set_voltage(voltage_limit)
                    # Initial setpoint is start current
                    self._current_setpoint = self._profile.start_current
                else:
                    # In voltage mode, we ramp voltage and set a current limit
                    self.power_supply.set_current(current_limit)
                    # Initial setpoint is start voltage
                    self._current_setpoint = self._profile.start_voltage
            except Exception as e:
                self._error_message = f"Failed to set initial power supply limits: {e}"
                self._set_state(ExecutorState.ERROR)
                return False

        # Start the execution thread
        self._stop_event.clear()
        self._pause_event.clear()

        with self._lock:
            self._start_time = time.time()
            self._paused_elapsed = 0.0
            self._current_step_index = 0
            # Setpoint already initialized above, but ensuring it matches profile
            is_current_mode = self._profile.control_mode == ControlMode.CURRENT.value
            self._current_setpoint = self._profile.start_current if is_current_mode else self._profile.start_voltage

        # Enable output before starting ramp
        if self.power_supply is not None:
            try:
                self.power_supply.output_on()
            except Exception as e:
                print(f"[RampExecutor] Warning: output_on() failed: {e}")

        # Set state to RUNNING before starting thread to avoid race condition
        # where thread sets ERROR and then we overwrite it with RUNNING
        self._set_state(ExecutorState.RUNNING)

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        return True

    def stop(self) -> bool:
        """
        Stop the executor and optionally turn off power supply output.

        Returns:
            True if stopped successfully
        """
        self._stop_event.set()
        self._pause_event.set()  # Unblock if paused

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        # Set voltage/current to 0 and turn off output for safety
        if self.power_supply:
            try:
                self.power_supply.set_voltage(0.0)
                self.power_supply.set_current(0.0)
                self.power_supply.output_off()
            except Exception:
                pass

        with self._lock:
            self._start_time = None
            self._pause_time = None
            self._paused_elapsed = 0.0
            self._current_step_index = 0

        self._set_state(ExecutorState.ABORTED)
        return True

    def pause(self) -> bool:
        """
        Pause the executor (holds current setpoint).

        Returns:
            True if paused successfully
        """
        if self.state != ExecutorState.RUNNING:
            return False

        self._pause_event.set()
        with self._lock:
            self._pause_time = time.time()

        self._set_state(ExecutorState.PAUSED)
        return True

    def resume(self) -> bool:
        """
        Resume the executor from paused state.

        Returns:
            True if resumed successfully
        """
        if self.state != ExecutorState.PAUSED:
            return False

        with self._lock:
            if self._pause_time is not None:
                self._paused_elapsed += time.time() - self._pause_time
                self._pause_time = None

        self._pause_event.clear()
        self._set_state(ExecutorState.RUNNING)
        return True

    def _run_loop(self) -> None:
        """Main execution loop running in background thread."""
        last_step_index = -1

        while not self._stop_event.is_set():
            # Check for pause
            if self._pause_event.is_set():
                time.sleep(0.05)
                continue

            elapsed = self.get_elapsed_time()

            with self._lock:
                if self._profile is None:
                    break

                # Check if profile complete
                if elapsed >= self._profile.get_total_duration():
                    self._current_setpoint = self._profile.get_final_voltage()
                    break

                # Calculate current setpoint
                self._current_setpoint = self._profile.get_setpoint_at_time(elapsed)

                # Get current step info
                step_info = self._profile.get_step_at_time(elapsed)
                if step_info[0] is not None:
                    self._current_step_index = step_info[0]

            # Notify step change
            if self._current_step_index != last_step_index:
                last_step_index = self._current_step_index
                if self._on_step_change:
                    try:
                        with self._lock:
                            total_steps = len(self._profile.steps) if self._profile else 0
                        self._on_step_change(self._current_step_index, total_steps)
                    except Exception:
                        pass

            # Send setpoint to power supply
            if self.power_supply:
                try:
                    with self._lock:
                        is_current_mode = self._profile.control_mode == ControlMode.CURRENT.value
                    
                    if is_current_mode:
                        self.power_supply.set_current(self._current_setpoint)
                    else:
                        self.power_supply.set_voltage(self._current_setpoint)
                except Exception as e:
                    with self._lock:
                        mode_str = "current" if is_current_mode else "voltage"
                        self._error_message = f"Failed to set {mode_str}: {e}"
                    if self._on_error:
                        try:
                            self._on_error(self._error_message)
                        except Exception:
                            pass
                    self._set_state(ExecutorState.ERROR)
                    return

            # Notify setpoint change
            if self._on_setpoint_change:
                try:
                    self._on_setpoint_change(self._current_setpoint)
                except Exception:
                    pass

            # Wait for next update
            time.sleep(self.update_interval_sec)

        # Profile completed normally
        if not self._stop_event.is_set():
            # Ramp is done - set voltage/current to 0 and turn off output
            if self.power_supply:
                try:
                    self.power_supply.set_voltage(0.0)
                    self.power_supply.set_current(0.0)
                    self.power_supply.output_off()
                except Exception:
                    pass

            with self._lock:
                self._current_setpoint = 0.0

            self._set_state(ExecutorState.COMPLETED)

            if self._on_complete:
                try:
                    self._on_complete()
                except Exception:
                    pass

    # Callback registration methods
    def on_setpoint_change(self, callback: Callable[[float], None]) -> None:
        """
        Register callback for setpoint changes.

        Args:
            callback: Function called with new setpoint value
        """
        self._on_setpoint_change = callback

    def on_step_change(self, callback: Callable[[int, int], None]) -> None:
        """
        Register callback for step transitions.

        Args:
            callback: Function called with (current_step, total_steps)
        """
        self._on_step_change = callback

    def on_complete(self, callback: Callable[[], None]) -> None:
        """
        Register callback for profile completion.

        Args:
            callback: Function called when profile completes
        """
        self._on_complete = callback

    def on_error(self, callback: Callable[[str], None]) -> None:
        """
        Register callback for errors.

        Args:
            callback: Function called with error message
        """
        self._on_error = callback

    def on_state_change(self, callback: Callable[[ExecutorState], None]) -> None:
        """
        Register callback for state changes.

        Args:
            callback: Function called with new state
        """
        self._on_state_change = callback

    def get_status(self) -> dict:
        """
        Get comprehensive status of the executor.

        Returns:
            Dictionary with current status information
        """
        with self._lock:
            return {
                'state': self._state.value,
                'profile_name': self._profile.name if self._profile else None,
                'current_setpoint': self._current_setpoint,
                'current_step': self._current_step_index,
                'total_steps': len(self._profile.steps) if self._profile else 0,
                'elapsed_time': self.get_elapsed_time(),
                'remaining_time': self.get_remaining_time(),
                'progress_percent': self.get_progress(),
                'error_message': self._error_message
            }

    def __repr__(self) -> str:
        """String representation of the executor."""
        return (f"RampExecutor(state={self.state.value}, "
                f"profile={self._profile.name if self._profile else 'None'})")

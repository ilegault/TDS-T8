"""
ramp_panel.py
PURPOSE: Display and control ramp profile execution

Provides profile selection, progress display, execution controls,
embedded real-time V/I plot, and safety interlock enforcement.
This is the ONLY power control interface.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import time
from typing import Optional, Callable, List
from collections import deque

from t8_daq_system.control.ramp_profile import RampProfile
from t8_daq_system.control.ramp_executor import RampExecutor, ExecutorState

try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


class RampPanel:
    """
    GUI panel for ramp profile control.

    Contains:
    - Profile selector dropdown
    - Progress bar and current step info
    - Start/Pause/Stop buttons (with safety interlock)
    - Embedded real-time voltage/current plot
    - Safety status indicator
    """

    # Max data points to keep in the embedded plot history
    PLOT_MAX_POINTS = 600
    VOLTAGE_LIMIT = 60.0
    CURRENT_LIMIT = 100.0

    def __init__(self, parent_frame, ramp_executor: RampExecutor = None,
                 profiles_folder: str = None):
        self.parent = parent_frame
        self.executor = ramp_executor
        self.profiles_folder = profiles_folder

        # Loaded profiles
        self._profiles: dict = {}
        self._current_profile: Optional[RampProfile] = None

        # Callbacks
        self._on_ramp_start: Optional[Callable[[], None]] = None
        self._on_ramp_stop: Optional[Callable[[], None]] = None

        # Safety interlock state
        self._emergency_shutdown_active = False

        # Embedded plot data
        self._plot_times: deque = deque(maxlen=self.PLOT_MAX_POINTS)
        self._plot_voltages: deque = deque(maxlen=self.PLOT_MAX_POINTS)
        self._plot_currents: deque = deque(maxlen=self.PLOT_MAX_POINTS)
        self._plot_start_time: Optional[float] = None

        # Build the GUI
        self._build_gui()

        # Load available profiles
        if profiles_folder:
            self._load_available_profiles()

        # Register executor callbacks if available
        if self.executor:
            self._register_executor_callbacks()

    def _build_gui(self):
        """Create all GUI elements."""
        main_frame = ttk.Frame(self.parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Safety interlock indicator at the top
        interlock_frame = ttk.Frame(main_frame)
        interlock_frame.pack(fill=tk.X, pady=(0, 2))

        self.ramp_interlock_indicator = tk.Canvas(
            interlock_frame, width=12, height=12,
            bg='#00FF00', highlightthickness=1, highlightbackground='black'
        )
        self.ramp_interlock_indicator.pack(side=tk.LEFT, padx=5)

        self.ramp_interlock_label = ttk.Label(
            interlock_frame,
            text="RAMP READY",
            font=('Arial', 8, 'bold'), foreground='green'
        )
        self.ramp_interlock_label.pack(side=tk.LEFT)

        # Profile selection
        profile_frame = ttk.Frame(main_frame)
        profile_frame.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(profile_frame, text="Profile:", font=('Arial', 8, 'bold')).pack(side=tk.LEFT)

        self.profile_var = tk.StringVar(value="(No profile loaded)")
        self.profile_combo = ttk.Combobox(
            profile_frame, textvariable=self.profile_var,
            state='readonly', width=17
        )
        self.profile_combo.pack(side=tk.LEFT, padx=2)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)

        self.load_btn = ttk.Button(
            profile_frame, text="Load...", command=self._on_load_profile, width=8
        )
        self.load_btn.pack(side=tk.LEFT, padx=1)

        self.refresh_btn = ttk.Button(
            profile_frame, text="Refresh", command=self._load_available_profiles, width=8
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=1)

        # Profile info display
        info_frame = ttk.LabelFrame(main_frame, text="Profile Info")
        info_frame.pack(fill=tk.X, pady=1)

        self.profile_info = ttk.Label(
            info_frame, text="No profile loaded",
            font=('Arial', 8), wraplength=350
        )
        self.profile_info.pack(fill=tk.X, padx=5, pady=2)

        # Progress section
        progress_frame = ttk.LabelFrame(main_frame, text="Execution Progress")
        progress_frame.pack(fill=tk.X, pady=1)

        status_row = ttk.Frame(progress_frame)
        status_row.pack(fill=tk.X, padx=5, pady=(2, 0))

        ttk.Label(status_row, text="Status:", font=('Arial', 8)).pack(side=tk.LEFT)
        self.state_label = ttk.Label(
            status_row, text="IDLE", font=('Arial', 8, 'bold')
        )
        self.state_label.pack(side=tk.LEFT, padx=2)

        self.step_label = ttk.Label(status_row, text="Step: --/--", font=('Arial', 8))
        self.step_label.pack(side=tk.RIGHT)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var,
            maximum=100, mode='determinate'
        )
        self.progress_bar.pack(fill=tk.X, padx=5, pady=2)

        time_row = ttk.Frame(progress_frame)
        time_row.pack(fill=tk.X, padx=5, pady=(0, 2))

        self.elapsed_label = ttk.Label(time_row, text="Elapsed: 00:00", font=('Arial', 8))
        self.elapsed_label.pack(side=tk.LEFT)

        self.setpoint_label = ttk.Label(
            time_row, text="Setpoint: 0.000 V", font=('Arial', 8, 'bold')
        )
        self.setpoint_label.pack(side=tk.LEFT, padx=10)

        self.remaining_label = ttk.Label(time_row, text="Remaining: 00:00", font=('Arial', 8))
        self.remaining_label.pack(side=tk.RIGHT)

        # Embedded V/I plot
        self._build_embedded_plot(main_frame)

        # Control buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(2, 1))

        self.start_btn = tk.Button(
            button_frame, text="Start Ramp", command=self._on_start,
            bg='#4CAF50', fg='white', font=('Arial', 8, 'bold'),
            width=10, height=1
        )
        self.start_btn.pack(side=tk.LEFT, expand=True, padx=2)

        self.pause_btn = tk.Button(
            button_frame, text="Pause", command=self._on_pause,
            bg='#FF9800', fg='white', font=('Arial', 8, 'bold'),
            width=10, height=1, state='disabled'
        )
        self.pause_btn.pack(side=tk.LEFT, expand=True, padx=2)

        self.stop_btn = tk.Button(
            button_frame, text="Stop Ramp", command=self._on_stop,
            bg='#f44336', fg='white', font=('Arial', 8, 'bold'),
            width=10, height=1, state='disabled'
        )
        self.stop_btn.pack(side=tk.LEFT, expand=True, padx=2)

        # Emergency Stop Button (separate row below)
        emergency_frame = ttk.Frame(main_frame)
        emergency_frame.pack(fill=tk.X, pady=(0, 2))

        self.emergency_stop_btn = tk.Button(
            emergency_frame, text="EMERGENCY STOP", command=self._on_emergency_stop,
            bg='#D32F2F', fg='white', font=('Arial', 9, 'bold'),
            width=25, height=1
        )
        self.emergency_stop_btn.pack(side=tk.TOP, expand=True, padx=2)

        # Initially disable start button until profile is loaded
        self.start_btn.config(state='disabled')

        # Emergency shutdown warning label (hidden by default)
        self.emergency_label = ttk.Label(
            main_frame,
            text="",
            font=('Arial', 9, 'bold'),
            foreground='red'
        )
        self.emergency_label.pack(fill=tk.X, pady=2)

    def _build_embedded_plot(self, parent):
        """Build the embedded real-time voltage/current plot."""
        plot_frame = ttk.LabelFrame(parent, text="Voltage / Current Monitor")
        plot_frame.pack(fill=tk.X, pady=1)

        if not HAS_MATPLOTLIB:
            ttk.Label(
                plot_frame,
                text="(matplotlib not available - install for real-time V/I plot)",
                font=('Arial', 8, 'italic'), foreground='gray'
            ).pack(padx=20, pady=10)
            self._has_plot = False
            return

        self._has_plot = True

        self._fig = Figure(figsize=(4, 2.5), dpi=80)
        self._fig.subplots_adjust(left=0.15, right=0.85, top=0.92, bottom=0.18)

        self._ax_v = self._fig.add_subplot(111)
        self._ax_v.set_xlabel('Time (s)', fontsize=7)
        self._ax_v.set_ylabel('Voltage (V)', fontsize=7, color='tab:blue')
        self._ax_v.tick_params(axis='y', labelcolor='tab:blue', labelsize=6)
        self._ax_v.tick_params(axis='x', labelsize=6)

        self._ax_a = self._ax_v.twinx()
        self._ax_a.set_ylabel('Current (A)', fontsize=7, color='tab:red')
        self._ax_a.tick_params(axis='y', labelcolor='tab:red', labelsize=6)

        self._line_v, = self._ax_v.plot([], [], 'b-', linewidth=1, label='Voltage')
        self._line_a, = self._ax_a.plot([], [], 'r-', linewidth=1, label='Current')

        # Legend
        lines = [self._line_v, self._line_a]
        labels = [l.get_label() for l in lines]
        self._ax_v.legend(lines, labels, loc='upper left', fontsize=6)

        self._canvas = FigureCanvasTkAgg(self._fig, master=plot_frame)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def update_plot_data(self, voltage: float, current: float):
        """Add new voltage/current data point to the embedded plot.

        Args:
            voltage: Current voltage reading
            current: Current current reading
        """
        if not getattr(self, '_has_plot', False):
            return

        if self._plot_start_time is None:
            self._plot_start_time = time.time()

        t = time.time() - self._plot_start_time
        self._plot_times.append(t)
        self._plot_voltages.append(voltage if voltage is not None else 0.0)
        self._plot_currents.append(current if current is not None else 0.0)

    def refresh_plot(self):
        """Redraw the embedded plot with current data. Call from GUI update loop."""
        if not getattr(self, '_has_plot', False):
            return
        if not self._plot_times:
            return

        times = list(self._plot_times)
        voltages = list(self._plot_voltages)
        currents = list(self._plot_currents)

        self._line_v.set_data(times, voltages)
        self._line_a.set_data(times, currents)

        # Use absolute scales to prevent "bouncing"
        self._ax_v.set_xlim(left=0, right=max(60, times[-1] if times else 60))
        self._ax_v.set_ylim(0, self.VOLTAGE_LIMIT)
        self._ax_a.set_ylim(0, self.CURRENT_LIMIT)

        try:
            self._canvas.draw_idle()
        except Exception:
            pass

    def clear_plot_data(self):
        """Clear the embedded plot data."""
        self._plot_times.clear()
        self._plot_voltages.clear()
        self._plot_currents.clear()
        self._plot_start_time = None
        if getattr(self, '_has_plot', False):
            self._line_v.set_data([], [])
            self._line_a.set_data([], [])
            try:
                self._canvas.draw_idle()
            except Exception:
                pass

    def set_turbo_interlock(self, turbo_ready: bool):
        """Update the safety interlock state (deprecated - for backward compatibility).

        Args:
            turbo_ready: Unused (kept for backward compatibility)
        """
        # Turbo pump functionality has been removed
        pass

    def set_emergency_shutdown(self, active: bool, message: str = ""):
        """Set the emergency shutdown state.

        Args:
            active: True if emergency shutdown is active
            message: Warning message to display
        """
        self._emergency_shutdown_active = active
        if active:
            self.emergency_label.config(text=message)
        else:
            self.emergency_label.config(text="")
        self._update_start_button_state()

    def _update_start_button_state(self):
        """Update the start button based on all interlock conditions."""
        if self._emergency_shutdown_active:
            self.start_btn.config(state='disabled')
            return
        if self._current_profile and self.executor and not self.executor.is_active():
            self.start_btn.config(state='normal')
        elif not self.executor or not self.executor.is_active():
            self.start_btn.config(state='disabled')

    def set_executor(self, ramp_executor: RampExecutor):
        self.executor = ramp_executor
        if ramp_executor:
            self._register_executor_callbacks()

    def set_profiles_folder(self, folder: str):
        self.profiles_folder = folder
        self._load_available_profiles()

    def _register_executor_callbacks(self):
        if not self.executor:
            return
        self.executor.on_state_change(self._on_executor_state_change)
        self.executor.on_step_change(self._on_executor_step_change)
        self.executor.on_setpoint_change(self._on_executor_setpoint_change)
        self.executor.on_complete(self._on_executor_complete)
        self.executor.on_error(self._on_executor_error)

    def _load_available_profiles(self):
        self._profiles.clear()
        profile_names = ["(No profile loaded)"]

        if self.profiles_folder and os.path.isdir(self.profiles_folder):
            for filename in os.listdir(self.profiles_folder):
                if filename.endswith('.json'):
                    filepath = os.path.join(self.profiles_folder, filename)
                    try:
                        profile = RampProfile.load(filepath)
                        if profile:
                            self._profiles[profile.name] = profile
                            profile_names.append(profile.name)
                    except Exception as e:
                        print(f"Error loading profile {filename}: {e}")

        self.profile_combo['values'] = profile_names
        if self._current_profile and self._current_profile.name in profile_names:
            self.profile_var.set(self._current_profile.name)
        else:
            self.profile_var.set("(No profile loaded)")

    def _on_profile_selected(self, event=None):
        name = self.profile_var.get()
        if name == "(No profile loaded)":
            self._current_profile = None
            self._update_profile_info()
            self.start_btn.config(state='disabled')
            return

        if name in self._profiles:
            self._current_profile = self._profiles[name]
            self._update_profile_info()

            if self.executor:
                if self.executor.load_profile(self._current_profile):
                    self._update_start_button_state()
                else:
                    self.start_btn.config(state='disabled')
                    messagebox.showwarning("Profile Error", "Failed to load profile into executor")
            else:
                self._update_start_button_state()

    def _on_load_profile(self):
        initial_dir = self.profiles_folder if self.profiles_folder else os.getcwd()
        filepath = filedialog.askopenfilename(
            title="Load Ramp Profile",
            initialdir=initial_dir,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if filepath:
            try:
                profile = RampProfile.load(filepath)
                if profile:
                    self._profiles[profile.name] = profile
                    self._current_profile = profile

                    current_values = list(self.profile_combo['values'])
                    if profile.name not in current_values:
                        current_values.append(profile.name)
                        self.profile_combo['values'] = current_values

                    self.profile_var.set(profile.name)
                    self._update_profile_info()

                    if self.executor:
                        if self.executor.load_profile(profile):
                            self._update_start_button_state()
                        else:
                            messagebox.showwarning("Profile Error",
                                                   "Failed to load profile into executor")
                else:
                    messagebox.showerror("Load Error", "Failed to load profile from file")
            except Exception as e:
                messagebox.showerror("Load Error", f"Error loading profile: {e}")

    def _update_profile_info(self):
        if not self._current_profile:
            self.profile_info.config(text="No profile loaded")
            return

        p = self._current_profile
        duration = p.get_total_duration()
        mins = int(duration // 60)
        secs = int(duration % 60)

        info = (
            f"Name: {p.name}\n"
            f"Steps: {p.get_step_count()}  |  Duration: {mins}m {secs}s\n"
            f"Start: {p.start_voltage:.3f}V  |  End: {p.get_final_voltage():.3f}V\n"
            f"Current Limit: {p.current_limit:.3f}A"
        )
        if p.description:
            info += f"\n{p.description}"

        self.profile_info.config(text=info)

    def _on_start(self):
        if not self.executor:
            messagebox.showwarning("Not Ready", "Ramp executor not initialized")
            return

        if not self._current_profile:
            messagebox.showwarning("No Profile", "Please select a profile first")
            return

        # Check emergency shutdown
        if self._emergency_shutdown_active:
            messagebox.showwarning(
                "Cannot Start Power Supply",
                "Cannot start power supply - Emergency shutdown is active.\n\n"
                "Wait for temperature to drop below 2150\u00b0C before restarting."
            )
            return

        if not messagebox.askyesno(
            "Confirm Start",
            f"Start ramp profile '{self._current_profile.name}'?\n\n"
            "This will begin controlling the power supply output."
        ):
            return

        if self.executor.profile is None or self.executor.profile.name != self._current_profile.name:
            if not self.executor.load_profile(self._current_profile):
                messagebox.showerror("Error", "Failed to load profile")
                return

        # Clear plot data for new ramp
        self.clear_plot_data()

        if self.executor.start():
            self._update_button_states(ExecutorState.RUNNING)
            if self._on_ramp_start:
                self._on_ramp_start()
        else:
            messagebox.showerror("Error", "Failed to start ramp execution")

    def _on_pause(self):
        if not self.executor:
            return

        if self.executor.state == ExecutorState.RUNNING:
            self.executor.pause()
            self.pause_btn.config(text="Resume")
        elif self.executor.state == ExecutorState.PAUSED:
            self.executor.resume()
            self.pause_btn.config(text="Pause")

    def _on_stop(self):
        if not self.executor:
            return

        if messagebox.askyesno(
            "Confirm Stop",
            "Stop the current ramp execution?\n\n"
            "Voltage will be set to 0V."
        ):
            self.executor.stop()
            self._update_button_states(ExecutorState.ABORTED)
            if self._on_ramp_stop:
                self._on_ramp_stop()

    def _on_emergency_stop(self):
        """Immediately stop everything and shut down the power supply."""
        if self.executor:
            # 1. Stop the executor thread
            self.executor.stop()
            
            # 2. Directly call emergency shutdown on the hardware if available
            if hasattr(self.executor, 'power_supply') and self.executor.power_supply:
                try:
                    self.executor.power_supply.emergency_shutdown()
                except Exception as e:
                    messagebox.showerror("Emergency Error", f"Failed to shut down PS hardware: {e}")
        
        # 3. Update UI
        self.set_emergency_shutdown(True, "EMERGENCY STOP ACTIVATED")
        messagebox.showwarning("Emergency Stop", "Emergency stop activated! Power supply output should be disabled.")

    def _update_button_states(self, state: ExecutorState):
        if state in [ExecutorState.RUNNING, ExecutorState.PAUSED]:
            self.start_btn.config(state='disabled')
            self.pause_btn.config(state='normal')
            self.stop_btn.config(state='normal')
            self.profile_combo.config(state='disabled')
            self.load_btn.config(state='disabled')
        else:
            self._update_start_button_state()
            self.pause_btn.config(state='disabled')
            self.stop_btn.config(state='disabled')
            self.profile_combo.config(state='readonly')
            self.load_btn.config(state='normal')
            self.pause_btn.config(text="Pause")

    def _on_executor_state_change(self, state: ExecutorState):
        try:
            self.parent.after(0, lambda: self._handle_state_change(state))
        except Exception:
            pass

    def _handle_state_change(self, state: ExecutorState):
        state_display = {
            ExecutorState.IDLE: ("IDLE", "black"),
            ExecutorState.RUNNING: ("RUNNING", "green"),
            ExecutorState.PAUSED: ("PAUSED", "orange"),
            ExecutorState.COMPLETED: ("COMPLETED", "blue"),
            ExecutorState.ERROR: ("ERROR", "red"),
            ExecutorState.ABORTED: ("STOPPED", "gray")
        }

        text, color = state_display.get(state, ("UNKNOWN", "black"))
        self.state_label.config(text=text, foreground=color)
        self._update_button_states(state)

    def _on_executor_step_change(self, current_step: int, total_steps: int):
        try:
            self.parent.after(0, lambda: self.step_label.config(
                text=f"Step: {current_step + 1}/{total_steps}"
            ))
        except Exception:
            pass

    def _on_executor_setpoint_change(self, setpoint: float):
        try:
            self.parent.after(0, lambda: self.setpoint_label.config(
                text=f"Setpoint: {setpoint:.3f} V"
            ))
        except Exception:
            pass

    def _on_executor_complete(self):
        try:
            self.parent.after(0, lambda: messagebox.showinfo(
                "Ramp Complete",
                f"Profile '{self._current_profile.name}' completed successfully."
            ))
        except Exception:
            pass

    def _on_executor_error(self, error_message: str):
        try:
            self.parent.after(0, lambda: messagebox.showerror(
                "Ramp Error",
                f"Error during ramp execution:\n{error_message}"
            ))
        except Exception:
            pass

    def update(self):
        """Update the display with current executor status."""
        if not self.executor:
            return

        progress = self.executor.get_progress()
        self.progress_var.set(progress)

        elapsed = self.executor.get_elapsed_time()
        e_mins = int(elapsed // 60)
        e_secs = int(elapsed % 60)
        self.elapsed_label.config(text=f"Elapsed: {e_mins:02d}:{e_secs:02d}")

        remaining = self.executor.get_remaining_time()
        r_mins = int(remaining // 60)
        r_secs = int(remaining % 60)
        self.remaining_label.config(text=f"Remaining: {r_mins:02d}:{r_secs:02d}")

        setpoint = self.executor.get_current_setpoint()
        self.setpoint_label.config(text=f"Setpoint: {setpoint:.3f} V")

        if self.executor.profile:
            current_step = self.executor.current_step
            total_steps = self.executor.profile.get_step_count()
            self.step_label.config(text=f"Step: {current_step + 1}/{total_steps}")

        # Refresh the embedded plot
        self.refresh_plot()

    def on_ramp_start(self, callback: Callable[[], None]):
        self._on_ramp_start = callback

    def on_ramp_stop(self, callback: Callable[[], None]):
        self._on_ramp_stop = callback

    def get_current_profile(self) -> Optional[RampProfile]:
        return self._current_profile

    def is_running(self) -> bool:
        if not self.executor:
            return False
        return self.executor.is_active()

    def stop_execution(self):
        """Stop the current ramp execution without confirmation."""
        if self.executor and self.executor.is_active():
            self.executor.stop()
            self._update_button_states(ExecutorState.ABORTED)

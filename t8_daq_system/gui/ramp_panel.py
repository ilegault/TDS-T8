"""
ramp_panel.py
PURPOSE: Display and control ramp profile execution

Provides profile selection, progress display, and execution controls
for the heating/cooling ramp profiles.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
from typing import Optional, Callable, List

from t8_daq_system.control.ramp_profile import RampProfile
from t8_daq_system.control.ramp_executor import RampExecutor, ExecutorState


class RampPanel:
    """
    GUI panel for ramp profile control.

    Contains:
    - Profile selector dropdown
    - Progress bar
    - Current step info
    - Start/Pause/Stop buttons
    - Estimated time remaining
    """

    def __init__(self, parent_frame, ramp_executor: RampExecutor = None,
                 profiles_folder: str = None):
        """
        Initialize the ramp control panel.

        Args:
            parent_frame: tkinter frame to put the panel in
            ramp_executor: RampExecutor instance (can be None initially)
            profiles_folder: Path to folder containing profile JSON files
        """
        self.parent = parent_frame
        self.executor = ramp_executor
        self.profiles_folder = profiles_folder

        # Loaded profiles
        self._profiles: dict = {}  # name -> RampProfile
        self._current_profile: Optional[RampProfile] = None

        # Callbacks
        self._on_ramp_start: Optional[Callable[[], None]] = None
        self._on_ramp_stop: Optional[Callable[[], None]] = None

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
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Top row: Profile selection
        profile_frame = ttk.Frame(main_frame)
        profile_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(profile_frame, text="Profile:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT)

        self.profile_var = tk.StringVar(value="(No profile loaded)")
        self.profile_combo = ttk.Combobox(
            profile_frame, textvariable=self.profile_var,
            state='readonly', width=25
        )
        self.profile_combo.pack(side=tk.LEFT, padx=5)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)

        self.load_btn = ttk.Button(
            profile_frame, text="Load...", command=self._on_load_profile, width=8
        )
        self.load_btn.pack(side=tk.LEFT, padx=2)

        self.refresh_btn = ttk.Button(
            profile_frame, text="Refresh", command=self._load_available_profiles, width=8
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=2)

        # Profile info display
        info_frame = ttk.LabelFrame(main_frame, text="Profile Info")
        info_frame.pack(fill=tk.X, pady=5)

        self.profile_info = ttk.Label(
            info_frame, text="No profile loaded",
            font=('Arial', 9), wraplength=350
        )
        self.profile_info.pack(fill=tk.X, padx=10, pady=5)

        # Progress section
        progress_frame = ttk.LabelFrame(main_frame, text="Execution Progress")
        progress_frame.pack(fill=tk.X, pady=5)

        # Status row
        status_row = ttk.Frame(progress_frame)
        status_row.pack(fill=tk.X, padx=10, pady=(5, 0))

        ttk.Label(status_row, text="Status:").pack(side=tk.LEFT)
        self.state_label = ttk.Label(
            status_row, text="IDLE", font=('Arial', 9, 'bold')
        )
        self.state_label.pack(side=tk.LEFT, padx=5)

        self.step_label = ttk.Label(status_row, text="Step: --/--", font=('Arial', 9))
        self.step_label.pack(side=tk.RIGHT)

        # Progress bar
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var,
            maximum=100, mode='determinate', length=300
        )
        self.progress_bar.pack(fill=tk.X, padx=10, pady=5)

        # Time and setpoint row
        time_row = ttk.Frame(progress_frame)
        time_row.pack(fill=tk.X, padx=10, pady=(0, 5))

        self.elapsed_label = ttk.Label(time_row, text="Elapsed: 00:00", font=('Arial', 9))
        self.elapsed_label.pack(side=tk.LEFT)

        self.setpoint_label = ttk.Label(
            time_row, text="Setpoint: 0.00 V", font=('Arial', 9, 'bold')
        )
        self.setpoint_label.pack(side=tk.LEFT, padx=20)

        self.remaining_label = ttk.Label(time_row, text="Remaining: 00:00", font=('Arial', 9))
        self.remaining_label.pack(side=tk.RIGHT)

        # Control buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)

        self.start_btn = tk.Button(
            button_frame, text="Start Ramp", command=self._on_start,
            bg='#4CAF50', fg='white', font=('Arial', 10, 'bold'),
            width=12, height=1
        )
        self.start_btn.pack(side=tk.LEFT, expand=True, padx=5)

        self.pause_btn = tk.Button(
            button_frame, text="Pause", command=self._on_pause,
            bg='#FF9800', fg='white', font=('Arial', 10, 'bold'),
            width=12, height=1, state='disabled'
        )
        self.pause_btn.pack(side=tk.LEFT, expand=True, padx=5)

        self.stop_btn = tk.Button(
            button_frame, text="Stop Ramp", command=self._on_stop,
            bg='#f44336', fg='white', font=('Arial', 10, 'bold'),
            width=12, height=1, state='disabled'
        )
        self.stop_btn.pack(side=tk.LEFT, expand=True, padx=5)

        # Initially disable start button until profile is loaded
        self.start_btn.config(state='disabled')

    def set_executor(self, ramp_executor: RampExecutor):
        """
        Set or update the ramp executor.

        Args:
            ramp_executor: RampExecutor instance
        """
        self.executor = ramp_executor
        if ramp_executor:
            self._register_executor_callbacks()

    def set_profiles_folder(self, folder: str):
        """
        Set the profiles folder and reload available profiles.

        Args:
            folder: Path to folder containing profile JSON files
        """
        self.profiles_folder = folder
        self._load_available_profiles()

    def _register_executor_callbacks(self):
        """Register callbacks with the executor."""
        if not self.executor:
            return

        self.executor.on_state_change(self._on_executor_state_change)
        self.executor.on_step_change(self._on_executor_step_change)
        self.executor.on_setpoint_change(self._on_executor_setpoint_change)
        self.executor.on_complete(self._on_executor_complete)
        self.executor.on_error(self._on_executor_error)

    def _load_available_profiles(self):
        """Load all profile files from the profiles folder."""
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
        """Handle profile selection from dropdown."""
        name = self.profile_var.get()
        if name == "(No profile loaded)":
            self._current_profile = None
            self._update_profile_info()
            self.start_btn.config(state='disabled')
            return

        if name in self._profiles:
            self._current_profile = self._profiles[name]
            self._update_profile_info()

            # Load into executor if available
            if self.executor:
                if self.executor.load_profile(self._current_profile):
                    self.start_btn.config(state='normal')
                else:
                    self.start_btn.config(state='disabled')
                    messagebox.showwarning("Profile Error", "Failed to load profile into executor")
            else:
                self.start_btn.config(state='normal')

    def _on_load_profile(self):
        """Handle Load button click - open file dialog."""
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

                    # Update combo box
                    current_values = list(self.profile_combo['values'])
                    if profile.name not in current_values:
                        current_values.append(profile.name)
                        self.profile_combo['values'] = current_values

                    self.profile_var.set(profile.name)
                    self._update_profile_info()

                    # Load into executor
                    if self.executor:
                        if self.executor.load_profile(profile):
                            self.start_btn.config(state='normal')
                        else:
                            messagebox.showwarning("Profile Error", "Failed to load profile into executor")
                else:
                    messagebox.showerror("Load Error", "Failed to load profile from file")

            except Exception as e:
                messagebox.showerror("Load Error", f"Error loading profile: {e}")

    def _update_profile_info(self):
        """Update the profile info display."""
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
            f"Start: {p.start_voltage:.1f}V  |  End: {p.get_final_voltage():.1f}V\n"
            f"Current Limit: {p.current_limit:.1f}A"
        )
        if p.description:
            info += f"\n{p.description}"

        self.profile_info.config(text=info)

    def _on_start(self):
        """Handle Start Ramp button click."""
        if not self.executor:
            messagebox.showwarning("Not Ready", "Ramp executor not initialized")
            return

        if not self._current_profile:
            messagebox.showwarning("No Profile", "Please select a profile first")
            return

        # Confirm start
        if not messagebox.askyesno(
            "Confirm Start",
            f"Start ramp profile '{self._current_profile.name}'?\n\n"
            "This will begin controlling the power supply output."
        ):
            return

        # Ensure profile is loaded in executor
        if self.executor.profile is None or self.executor.profile.name != self._current_profile.name:
            if not self.executor.load_profile(self._current_profile):
                messagebox.showerror("Error", "Failed to load profile")
                return

        # Start execution
        if self.executor.start():
            self._update_button_states(ExecutorState.RUNNING)
            if self._on_ramp_start:
                self._on_ramp_start()
        else:
            messagebox.showerror("Error", "Failed to start ramp execution")

    def _on_pause(self):
        """Handle Pause/Resume button click."""
        if not self.executor:
            return

        if self.executor.state == ExecutorState.RUNNING:
            self.executor.pause()
            self.pause_btn.config(text="Resume")
        elif self.executor.state == ExecutorState.PAUSED:
            self.executor.resume()
            self.pause_btn.config(text="Pause")

    def _on_stop(self):
        """Handle Stop Ramp button click."""
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

    def _update_button_states(self, state: ExecutorState):
        """Update button states based on executor state."""
        if state in [ExecutorState.RUNNING, ExecutorState.PAUSED]:
            self.start_btn.config(state='disabled')
            self.pause_btn.config(state='normal')
            self.stop_btn.config(state='normal')
            self.profile_combo.config(state='disabled')
            self.load_btn.config(state='disabled')
        else:
            self.start_btn.config(state='normal' if self._current_profile else 'disabled')
            self.pause_btn.config(state='disabled')
            self.stop_btn.config(state='disabled')
            self.profile_combo.config(state='readonly')
            self.load_btn.config(state='normal')
            self.pause_btn.config(text="Pause")

    def _on_executor_state_change(self, state: ExecutorState):
        """Handle executor state change callback."""
        # Update UI on main thread
        try:
            self.parent.after(0, lambda: self._handle_state_change(state))
        except Exception:
            pass

    def _handle_state_change(self, state: ExecutorState):
        """Handle state change on main thread."""
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
        """Handle executor step change callback."""
        try:
            self.parent.after(0, lambda: self.step_label.config(
                text=f"Step: {current_step + 1}/{total_steps}"
            ))
        except Exception:
            pass

    def _on_executor_setpoint_change(self, setpoint: float):
        """Handle executor setpoint change callback."""
        try:
            self.parent.after(0, lambda: self.setpoint_label.config(
                text=f"Setpoint: {setpoint:.2f} V"
            ))
        except Exception:
            pass

    def _on_executor_complete(self):
        """Handle executor completion callback."""
        try:
            self.parent.after(0, lambda: messagebox.showinfo(
                "Ramp Complete",
                f"Profile '{self._current_profile.name}' completed successfully."
            ))
        except Exception:
            pass

    def _on_executor_error(self, error_message: str):
        """Handle executor error callback."""
        try:
            self.parent.after(0, lambda: messagebox.showerror(
                "Ramp Error",
                f"Error during ramp execution:\n{error_message}"
            ))
        except Exception:
            pass

    def update(self):
        """
        Update the display with current executor status.

        Should be called periodically from the main update loop.
        """
        if not self.executor:
            return

        # Update progress
        progress = self.executor.get_progress()
        self.progress_var.set(progress)

        # Update elapsed time
        elapsed = self.executor.get_elapsed_time()
        e_mins = int(elapsed // 60)
        e_secs = int(elapsed % 60)
        self.elapsed_label.config(text=f"Elapsed: {e_mins:02d}:{e_secs:02d}")

        # Update remaining time
        remaining = self.executor.get_remaining_time()
        r_mins = int(remaining // 60)
        r_secs = int(remaining % 60)
        self.remaining_label.config(text=f"Remaining: {r_mins:02d}:{r_secs:02d}")

        # Update setpoint
        setpoint = self.executor.get_current_setpoint()
        self.setpoint_label.config(text=f"Setpoint: {setpoint:.2f} V")

        # Update step info
        if self.executor.profile:
            current_step = self.executor.current_step
            total_steps = self.executor.profile.get_step_count()
            self.step_label.config(text=f"Step: {current_step + 1}/{total_steps}")

    def on_ramp_start(self, callback: Callable[[], None]):
        """
        Register callback for when ramp execution starts.

        Args:
            callback: Function to call when ramp starts
        """
        self._on_ramp_start = callback

    def on_ramp_stop(self, callback: Callable[[], None]):
        """
        Register callback for when ramp execution stops.

        Args:
            callback: Function to call when ramp stops
        """
        self._on_ramp_stop = callback

    def get_current_profile(self) -> Optional[RampProfile]:
        """Get the currently selected profile."""
        return self._current_profile

    def is_running(self) -> bool:
        """Check if a ramp is currently running."""
        if not self.executor:
            return False
        return self.executor.is_active()

    def stop_execution(self):
        """Stop the current ramp execution without confirmation."""
        if self.executor and self.executor.is_active():
            self.executor.stop()
            self._update_button_states(ExecutorState.ABORTED)

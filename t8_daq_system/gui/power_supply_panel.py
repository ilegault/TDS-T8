"""
power_supply_panel.py
PURPOSE: Display and control Keysight N5761A DC Power Supply

Provides manual voltage/current entry, output ON/OFF buttons,
status indicators, and current readings display.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Callable


class PowerSupplyPanel:
    """
    GUI panel for power supply control.

    Contains:
    - Manual voltage/current entry boxes
    - Output ON/OFF buttons (big and obvious)
    - Status indicator (connected, output state, errors)
    - Current readings display (actual V and A)
    """

    def __init__(self, parent_frame, power_supply_controller=None):
        """
        Initialize the power supply control panel.

        Args:
            parent_frame: tkinter frame to put the panel in
            power_supply_controller: PowerSupplyController instance (can be None initially)
        """
        self.parent = parent_frame
        self.controller = power_supply_controller

        # State tracking
        self._connected = False
        self._output_on = False
        self._last_voltage = 0.0
        self._last_current = 0.0

        # Callbacks for external notifications
        self._on_output_change: Optional[Callable[[bool], None]] = None

        # Build the GUI
        self._build_gui()

    def _build_gui(self):
        """Create all GUI elements."""
        main_frame = ttk.Frame(self.parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Top row: Connection status
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(status_frame, text="Status:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT)

        self.status_indicator = tk.Canvas(
            status_frame, width=16, height=16,
            bg='#333333', highlightthickness=1, highlightbackground='black'
        )
        self.status_indicator.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(status_frame, text="Disconnected", font=('Arial', 9))
        self.status_label.pack(side=tk.LEFT)

        # Output state indicator on the right
        self.output_indicator = ttk.Label(
            status_frame, text="OUTPUT OFF",
            font=('Arial', 9, 'bold'), foreground='gray'
        )
        self.output_indicator.pack(side=tk.RIGHT, padx=5)

        # Separator
        ttk.Separator(main_frame, orient='horizontal').pack(fill=tk.X, pady=5)

        # Current readings display (actual measured values)
        readings_frame = ttk.LabelFrame(main_frame, text="Actual Output")
        readings_frame.pack(fill=tk.X, pady=5)

        readings_inner = ttk.Frame(readings_frame)
        readings_inner.pack(fill=tk.X, padx=10, pady=5)

        # Voltage reading
        v_frame = ttk.Frame(readings_inner)
        v_frame.pack(side=tk.LEFT, expand=True)
        ttk.Label(v_frame, text="Voltage", font=('Arial', 8)).pack()
        self.voltage_display = ttk.Label(
            v_frame, text="---.--", font=('Arial', 16, 'bold')
        )
        self.voltage_display.pack()
        ttk.Label(v_frame, text="V", font=('Arial', 10)).pack()

        # Current reading
        a_frame = ttk.Frame(readings_inner)
        a_frame.pack(side=tk.LEFT, expand=True)
        ttk.Label(a_frame, text="Current", font=('Arial', 8)).pack()
        self.current_display = ttk.Label(
            a_frame, text="---.--", font=('Arial', 16, 'bold')
        )
        self.current_display.pack()
        ttk.Label(a_frame, text="A", font=('Arial', 10)).pack()

        # Separator
        ttk.Separator(main_frame, orient='horizontal').pack(fill=tk.X, pady=5)

        # Setpoint controls
        setpoint_frame = ttk.LabelFrame(main_frame, text="Setpoints")
        setpoint_frame.pack(fill=tk.X, pady=5)

        setpoint_inner = ttk.Frame(setpoint_frame)
        setpoint_inner.pack(fill=tk.X, padx=10, pady=5)

        # Voltage setpoint
        v_set_frame = ttk.Frame(setpoint_inner)
        v_set_frame.pack(side=tk.LEFT, expand=True, padx=5)

        ttk.Label(v_set_frame, text="Voltage (V):").pack(side=tk.LEFT)
        self.voltage_var = tk.StringVar(value="0.0")
        self.voltage_entry = ttk.Entry(
            v_set_frame, textvariable=self.voltage_var, width=8,
            font=('Arial', 11)
        )
        self.voltage_entry.pack(side=tk.LEFT, padx=5)
        self.set_voltage_btn = ttk.Button(
            v_set_frame, text="Set", command=self._on_set_voltage, width=5
        )
        self.set_voltage_btn.pack(side=tk.LEFT)

        # Current setpoint
        a_set_frame = ttk.Frame(setpoint_inner)
        a_set_frame.pack(side=tk.LEFT, expand=True, padx=5)

        ttk.Label(a_set_frame, text="Current (A):").pack(side=tk.LEFT)
        self.current_var = tk.StringVar(value="10.0")
        self.current_entry = ttk.Entry(
            a_set_frame, textvariable=self.current_var, width=8,
            font=('Arial', 11)
        )
        self.current_entry.pack(side=tk.LEFT, padx=5)
        self.set_current_btn = ttk.Button(
            a_set_frame, text="Set", command=self._on_set_current, width=5
        )
        self.set_current_btn.pack(side=tk.LEFT)

        # Separator
        ttk.Separator(main_frame, orient='horizontal').pack(fill=tk.X, pady=5)

        # Output control buttons - big and obvious
        output_frame = ttk.Frame(main_frame)
        output_frame.pack(fill=tk.X, pady=5)

        # Create custom styles for the buttons
        style = ttk.Style()
        style.configure('On.TButton', font=('Arial', 12, 'bold'))
        style.configure('Off.TButton', font=('Arial', 12, 'bold'))

        self.output_on_btn = tk.Button(
            output_frame, text="OUTPUT ON", command=self._on_output_on,
            bg='#4CAF50', fg='white', font=('Arial', 11, 'bold'),
            width=12, height=1, activebackground='#45a049'
        )
        self.output_on_btn.pack(side=tk.LEFT, expand=True, padx=10, pady=5)

        self.output_off_btn = tk.Button(
            output_frame, text="OUTPUT OFF", command=self._on_output_off,
            bg='#f44336', fg='white', font=('Arial', 11, 'bold'),
            width=12, height=1, activebackground='#da190b'
        )
        self.output_off_btn.pack(side=tk.LEFT, expand=True, padx=10, pady=5)

        # Error display
        self.error_label = ttk.Label(
            main_frame, text="", font=('Arial', 8, 'italic'),
            foreground='red'
        )
        self.error_label.pack(fill=tk.X, pady=2)

        # Initially disable controls
        self._set_controls_enabled(False)

    def set_controller(self, power_supply_controller):
        """
        Set or update the power supply controller.

        Args:
            power_supply_controller: PowerSupplyController instance
        """
        self.controller = power_supply_controller
        if power_supply_controller:
            self._connected = True
            self._set_controls_enabled(True)
            self._update_status_display()
        else:
            self._connected = False
            self._set_controls_enabled(False)
            self._update_status_display()

    def _set_controls_enabled(self, enabled: bool):
        """Enable or disable all control widgets."""
        state = 'normal' if enabled else 'disabled'
        self.voltage_entry.config(state=state)
        self.current_entry.config(state=state)
        self.set_voltage_btn.config(state=state)
        self.set_current_btn.config(state=state)
        self.output_on_btn.config(state=state)
        self.output_off_btn.config(state=state)

    def _update_status_display(self):
        """Update the connection status display."""
        if self._connected:
            self.status_indicator.config(bg='#00FF00')
            self.status_label.config(text="Connected")
        else:
            self.status_indicator.config(bg='#333333')
            self.status_label.config(text="Disconnected")
            self.voltage_display.config(text="---.--")
            self.current_display.config(text="---.--")

        self._update_output_indicator()

    def _update_output_indicator(self):
        """Update the output state indicator."""
        if self._output_on:
            self.output_indicator.config(text="OUTPUT ON", foreground='green')
        else:
            self.output_indicator.config(text="OUTPUT OFF", foreground='gray')

    def _on_set_voltage(self):
        """Handle Set Voltage button click."""
        if not self.controller:
            return

        try:
            voltage = float(self.voltage_var.get())
            if voltage < 0:
                self._show_error("Voltage cannot be negative")
                return

            success = self.controller.set_voltage(voltage)
            if success:
                self._clear_error()
            else:
                self._show_error("Failed to set voltage")

        except ValueError:
            self._show_error("Invalid voltage value")
        except Exception as e:
            self._show_error(f"Error: {str(e)}")

    def _on_set_current(self):
        """Handle Set Current button click."""
        if not self.controller:
            return

        try:
            current = float(self.current_var.get())
            if current < 0:
                self._show_error("Current cannot be negative")
                return

            success = self.controller.set_current(current)
            if success:
                self._clear_error()
            else:
                self._show_error("Failed to set current limit")

        except ValueError:
            self._show_error("Invalid current value")
        except Exception as e:
            self._show_error(f"Error: {str(e)}")

    def _on_output_on(self):
        """Handle Output ON button click."""
        if not self.controller:
            return

        # Confirm before turning on
        if messagebox.askyesno(
            "Confirm Output ON",
            "Are you sure you want to enable the power supply output?"
        ):
            success = self.controller.output_on()
            if success:
                self._output_on = True
                self._update_output_indicator()
                self._clear_error()
                if self._on_output_change:
                    self._on_output_change(True)
            else:
                self._show_error("Failed to enable output")

    def _on_output_off(self):
        """Handle Output OFF button click."""
        if not self.controller:
            return

        success = self.controller.output_off()
        if success:
            self._output_on = False
            self._update_output_indicator()
            self._clear_error()
            if self._on_output_change:
                self._on_output_change(False)
        else:
            self._show_error("CRITICAL: Failed to disable output!")

    def _show_error(self, message: str):
        """Display an error message."""
        self.error_label.config(text=message)

    def _clear_error(self):
        """Clear the error message."""
        self.error_label.config(text="")

    def update(self, readings: dict = None):
        """
        Update the display with current readings.

        Should be called periodically from the main update loop.

        Args:
            readings: Optional dict with 'PS_Voltage' and 'PS_Current' keys
        """
        if not self.controller:
            self._connected = False
            self._update_status_display()
            return

        # Update connection status
        self._connected = True
        self.status_indicator.config(bg='#00FF00')
        self.status_label.config(text="Connected")

        # Update readings display
        if readings:
            voltage = readings.get('PS_Voltage')
            current = readings.get('PS_Current')

            if voltage is not None:
                self._last_voltage = voltage
                self.voltage_display.config(text=f"{voltage:.2f}")
            else:
                self.voltage_display.config(text="---.--")

            if current is not None:
                self._last_current = current
                self.current_display.config(text=f"{current:.2f}")
            else:
                self.current_display.config(text="---.--")

        # Update output state
        try:
            self._output_on = self.controller.is_output_on()
            self._update_output_indicator()
        except Exception:
            pass

    def update_output_state(self, is_on: bool):
        """
        Update the output state indicator without querying hardware.

        Args:
            is_on: Whether the output is currently on
        """
        self._output_on = is_on
        self._update_output_indicator()

    def set_connected(self, connected: bool):
        """
        Set the connection status.

        Args:
            connected: Whether the power supply is connected
        """
        self._connected = connected
        self._set_controls_enabled(connected)
        self._update_status_display()

    def on_output_change(self, callback: Callable[[bool], None]):
        """
        Register callback for output state changes.

        Args:
            callback: Function called with True (on) or False (off)
        """
        self._on_output_change = callback

    def get_voltage_setpoint(self) -> float:
        """Get the voltage setpoint from the entry field."""
        try:
            return float(self.voltage_var.get())
        except ValueError:
            return 0.0

    def get_current_setpoint(self) -> float:
        """Get the current setpoint from the entry field."""
        try:
            return float(self.current_var.get())
        except ValueError:
            return 0.0

    def set_voltage_setpoint(self, voltage: float):
        """
        Set the voltage entry field value.

        Args:
            voltage: Voltage value to display
        """
        self.voltage_var.set(f"{voltage:.2f}")

    def set_current_setpoint(self, current: float):
        """
        Set the current entry field value.

        Args:
            current: Current value to display
        """
        self.current_var.set(f"{current:.2f}")

    def emergency_off(self):
        """
        Emergency output off - called by safety monitor.
        Does not show confirmation dialog.
        """
        if self.controller:
            self.controller.output_off()
        self._output_on = False
        self._update_output_indicator()
        self._show_error("EMERGENCY SHUTDOWN TRIGGERED")

"""
power_supply_panel.py
PURPOSE: Display power supply status and readings (read-only).

Shows connection status, actual V/A readings, output state, and safety
interlock indicators. All control is done through the Ramp Panel.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable


class PowerSupplyPanel:
    """
    GUI panel for power supply status display (read-only).

    Contains:
    - Connection status indicator
    - Actual V/A readings display
    - Output state indicator
    - Safety status
    """

    def __init__(self, parent_frame, power_supply_controller=None):
        self.parent = parent_frame
        self.controller = power_supply_controller

        # State tracking
        self._connected = False
        self._output_on = False
        self._last_voltage = 0.0
        self._last_current = 0.0
        self._locked = False

        # Callbacks for external notifications
        self._on_output_change: Optional[Callable[[bool], None]] = None

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

        # Safety interlock indicator
        interlock_frame = ttk.Frame(main_frame)
        interlock_frame.pack(fill=tk.X, pady=(0, 5))

        self.interlock_indicator = tk.Canvas(
            interlock_frame, width=16, height=16,
            bg='#00FF00', highlightthickness=1, highlightbackground='black'
        )
        self.interlock_indicator.pack(side=tk.LEFT, padx=5)

        self.interlock_label = ttk.Label(
            interlock_frame,
            text="POWER SUPPLY READY",
            font=('Arial', 8, 'bold'), foreground='green'
        )
        self.interlock_label.pack(side=tk.LEFT)

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
            v_frame, text="---.---", font=('Arial', 16, 'bold')
        )
        self.voltage_display.pack()
        ttk.Label(v_frame, text="V", font=('Arial', 10)).pack()

        # Current reading
        a_frame = ttk.Frame(readings_inner)
        a_frame.pack(side=tk.LEFT, expand=True)
        ttk.Label(a_frame, text="Current", font=('Arial', 8)).pack()
        self.current_display = ttk.Label(
            a_frame, text="---.---", font=('Arial', 16, 'bold')
        )
        self.current_display.pack()
        ttk.Label(a_frame, text="A", font=('Arial', 10)).pack()

        # Error display
        self.error_label = ttk.Label(
            main_frame, text="", font=('Arial', 8, 'italic'),
            foreground='red'
        )
        self.error_label.pack(fill=tk.X, pady=2)

    def set_controller(self, power_supply_controller):
        self.controller = power_supply_controller
        if power_supply_controller:
            self._connected = True
            self._update_status_display()
        else:
            self._connected = False
            self._update_status_display()

    def _update_status_display(self):
        """Update the connection status display."""
        if self._connected:
            self.status_indicator.config(bg='#00FF00')
            self.status_label.config(text="Connected")
        else:
            self.status_indicator.config(bg='#333333')
            self.status_label.config(text="Disconnected")
            self.voltage_display.config(text="---.---")
            self.current_display.config(text="---.---")

        self._update_output_indicator()

    def _update_output_indicator(self):
        """Update the output state indicator."""
        if self._output_on:
            self.output_indicator.config(text="OUTPUT ON", foreground='green')
        else:
            self.output_indicator.config(text="OUTPUT OFF", foreground='gray')

    def set_interlock_state(self, ready: bool):
        """Update the safety interlock display.

        Args:
            ready: True if power supply is ready, False if locked
        """
        self._locked = not ready
        if ready:
            self.interlock_indicator.config(bg='#00FF00')
            self.interlock_label.config(
                text="POWER SUPPLY READY",
                foreground='green'
            )
        else:
            self.interlock_indicator.config(bg='#FF0000')
            self.interlock_label.config(
                text="POWER SUPPLY LOCKED",
                foreground='red'
            )

    def is_locked(self) -> bool:
        """Check if the power supply is locked by interlock."""
        return self._locked

    def _show_error(self, message: str):
        self.error_label.config(text=message)

    def _clear_error(self):
        self.error_label.config(text="")

    def update(self, readings: dict = None):
        """Update the display with current readings."""
        if not self.controller:
            self._connected = False
            self._update_status_display()
            return

        self._connected = True
        self.status_indicator.config(bg='#00FF00')
        self.status_label.config(text="Connected")

        if readings:
            voltage = readings.get('PS_Voltage')
            current = readings.get('PS_Current')

            if voltage is not None:
                self._last_voltage = voltage
                self.voltage_display.config(text=f"{voltage:.3f}")
            else:
                self.voltage_display.config(text="---.---")

            if current is not None:
                self._last_current = current
                self.current_display.config(text=f"{current:.3f}")
            else:
                self.current_display.config(text="---.---")

        try:
            self._output_on = self.controller.is_output_on()
            self._update_output_indicator()
        except Exception:
            pass

    def update_output_state(self, is_on: bool):
        self._output_on = is_on
        self._update_output_indicator()

    def set_connected(self, connected: bool):
        self._connected = connected
        self._update_status_display()

    def on_output_change(self, callback: Callable[[bool], None]):
        self._on_output_change = callback

    def emergency_off(self):
        """Emergency output off - called by safety monitor."""
        if self.controller:
            self.controller.output_off()
        self._output_on = False
        self._update_output_indicator()
        self._show_error("EMERGENCY SHUTDOWN TRIGGERED")

"""
turbo_pump_panel.py
PURPOSE: GUI panel with ON/OFF buttons and status display for the turbo pump.

Matches the style of power_supply_panel.py -- big colored buttons,
status indicator that changes color based on pump state.
"""

import tkinter as tk
from tkinter import ttk, messagebox


class TurboPumpPanel(ttk.LabelFrame):
    """
    GUI panel for turbo pump control.

    Provides:
    - TURBO ON button (green) -- sends start command
    - TURBO OFF button (red) -- sends stop command
    - Status indicator showing: OFF / STARTING / NORMAL / UNKNOWN
    - Confirmation dialog before turning ON (safety)
    """

    # Color mapping for status indicator
    STATUS_COLORS = {
        'OFF': '#666666',       # Gray
        'STARTING': '#FFA500',  # Orange (accelerating)
        'NORMAL': '#00FF00',    # Green (at speed)
        'UNKNOWN': '#FF0000',   # Red (error/unknown)
    }

    def __init__(self, parent, **kwargs):
        """
        Initialize the turbo pump control panel.

        Args:
            parent: Parent tkinter widget
        """
        super().__init__(parent, text="Turbo Pump", **kwargs)
        self.controller = None  # Set later via set_controller()
        self._build_widgets()

    def _build_widgets(self):
        """Build the panel UI elements."""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Status display row
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(status_frame, text="Status:", font=('Arial', 10)).pack(side=tk.LEFT)

        self.status_indicator = tk.Label(
            status_frame, text=" \u25cf ", font=('Arial', 14),
            fg=self.STATUS_COLORS['OFF'], bg='black'
        )
        self.status_indicator.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(
            status_frame, text="OFF", font=('Arial', 10, 'bold')
        )
        self.status_label.pack(side=tk.LEFT)

        # ON / OFF buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        self.on_btn = tk.Button(
            btn_frame, text="TURBO ON", command=self._on_turbo_on,
            bg='#4CAF50', fg='white', font=('Arial', 11, 'bold'),
            width=12, height=1, activebackground='#45a049'
        )
        self.on_btn.pack(side=tk.LEFT, expand=True, padx=10, pady=5)

        self.off_btn = tk.Button(
            btn_frame, text="TURBO OFF", command=self._on_turbo_off,
            bg='#f44336', fg='white', font=('Arial', 11, 'bold'),
            width=12, height=1, activebackground='#da190b'
        )
        self.off_btn.pack(side=tk.LEFT, expand=True, padx=10, pady=5)

        # Error/info message label
        self.message_label = ttk.Label(
            main_frame, text="", font=('Arial', 8, 'italic'),
            foreground='gray'
        )
        self.message_label.pack(fill=tk.X, pady=2)

        # Start with buttons disabled until controller is connected
        self._set_controls_enabled(False)

    def set_controller(self, turbo_controller):
        """
        Attach the TurboPumpController instance.

        Args:
            turbo_controller: TurboPumpController instance (or None to disconnect)
        """
        self.controller = turbo_controller
        if turbo_controller:
            self._set_controls_enabled(True)
            self.update_status_display()
        else:
            self._set_controls_enabled(False)
            self._update_indicator('OFF')

    def _set_controls_enabled(self, enabled):
        """Enable or disable the ON/OFF buttons."""
        state = 'normal' if enabled else 'disabled'
        self.on_btn.config(state=state)
        self.off_btn.config(state=state)

    def _on_turbo_on(self):
        """Handle TURBO ON button click."""
        if not self.controller:
            return

        # Safety confirmation dialog
        result = messagebox.askyesno(
            "Confirm Turbo Pump Start",
            "Are you sure you want to START the turbo pump?\n\n"
            "Ensure:\n"
            "\u2022 Cooling water is flowing\n"
            "\u2022 Backing pump is running\n"
            "\u2022 System is under rough vacuum",
            icon='warning'
        )
        if not result:
            return

        success, message = self.controller.start()
        self.message_label.config(
            text=message,
            foreground='green' if success else 'red'
        )
        self.update_status_display()

    def _on_turbo_off(self):
        """Handle TURBO OFF button click."""
        if not self.controller:
            return

        success, message = self.controller.stop()
        self.message_label.config(
            text=message,
            foreground='green' if success else 'red'
        )
        self.update_status_display()

    def update_status_display(self):
        """
        Refresh the status indicator and label.
        Call this periodically from the main GUI update loop.
        """
        if not self.controller:
            self._update_indicator('OFF')
            return

        status = self.controller.read_status()
        self._update_indicator(status)

    def _update_indicator(self, status):
        """Update the colored dot and text label."""
        color = self.STATUS_COLORS.get(status, self.STATUS_COLORS['UNKNOWN'])
        self.status_indicator.config(fg=color)
        self.status_label.config(text=status)

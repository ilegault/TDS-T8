"""
power_programmer_panel.py
PURPOSE: Power Programmer Panel

A table-based block editor where each row defines a power profile segment.
Block types:
  "Ramp" - linearly interpolates from Start V/A to End V/A over Duration
  "Hold" - stays at Start V/A for Duration

In TempRamp mode each block specifies a ramp rate (K/min); a PID controller
drives the actual power supply to achieve that temperature rise rate.

Every run begins with a Soft start (ADR 0006).  It is not a block and is not
saved in profiles; the table shows it as a locked first row that the delete and
move handlers refuse to touch, and two labels show the gains and the two current
caps the run will use (from AppSettings when idle, from the Snapshot while
running).

Computes a time-series preview from the block list.
Provides Save/Load of profiles as JSON files.
Fires a callback with the computed preview data when the profile is confirmed.
"""

import json
import logging
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

logger = logging.getLogger(__name__)


class PowerProgrammerPanel:
    """
    Block editor UI and preview logic for Power Programmer mode.

    Voltage mode — each block is a dict:
        {
            "type":       "Ramp" or "Hold",
            "duration":   float (seconds, min 1, max 86400),
            "start_v":    float (volts, 0.0-6.0),
            "end_v":      float (volts, 0.0-6.0),
            "current_a":  float (amps, 0.0-180.0)  # fixed ceiling, never ramped
        }

    TempRamp mode — each block is a dict:
        {
            "type":          "Ramp" or "Hold",
            "duration_sec":  float (seconds, > 0),
            "rate_k_per_min": float (K/min; only meaningful for Ramp blocks)
        }
    """

    # Hard limits for Keysight N5700
    MAX_VOLTAGE = 6.0
    MAX_CURRENT = 180.0
    MAX_DURATION = 86400

    # Treeview item id of the locked Soft-start row (always the first row)
    SOFT_START_IID = "soft_start"

    def __init__(self, parent_frame, settings, on_profile_confirmed_callback,
                 on_panel_closed_callback):
        """
        Args:
            parent_frame: tkinter frame to build into
            settings: AppSettings instance
            on_profile_confirmed_callback(times, voltages, currents):
                Called when user confirms the profile. Receives three lists of floats.
            on_panel_closed_callback():
                Called when the panel is hidden/closed.
        """
        self._parent = parent_frame
        self._settings = settings
        self._on_confirmed = on_profile_confirmed_callback
        self._on_closed = on_panel_closed_callback

        self._blocks = []  # list of block dicts
        self._mode = "Voltage"  # "Voltage" or "TempRamp"
        self._safe_test_mode = False  # Controlled by Safe Test Mode checkbox

        self._entry_mode = "Rate"   # "Rate" or "TimeTarget"
        self._start_temp_var = None  # tk.StringVar for the starting temperature entry
        self._start_temp_frame = None

        self._table_frame = None  # kept as ref so _rebuild_table_columns can destroy/recreate
        self._tree = None
        self._tree_vsb = None
        self._gains_text = ""
        self._caps_text = ""

        self._build_gui()

    # ──────────────────────────────────────────────────────────────────────
    # GUI construction
    # ──────────────────────────────────────────────────────────────────────

    def _build_gui(self):
        """Build the entire programmer panel UI inside self._parent."""
        # ── Row 1: Title bar ─────────────────────────────────────────────
        title_frame = ttk.Frame(self._parent)
        title_frame.pack(fill=tk.X, padx=4, pady=(4, 0))

        ttk.Label(
            title_frame, text="Power Programmer",
            font=('Arial', 12, 'bold')
        ).pack(side=tk.LEFT)

        self._duration_label = ttk.Label(title_frame, text="Total: 0s")
        self._duration_label.pack(side=tk.RIGHT)

        # ── Row 2: Toolbar ────────────────────────────────────────────────
        toolbar = ttk.Frame(self._parent)
        toolbar.pack(fill=tk.X, padx=4, pady=2)

        ttk.Button(toolbar, text="Add Block",
                   command=self._add_block).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Delete Block",
                   command=self._delete_block).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Move Up",
                   command=self._move_up).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Move Down",
                   command=self._move_down).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Save Profile",
                   command=self._save_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Load Profile",
                   command=self._load_profile).pack(side=tk.LEFT, padx=2)

        ttk.Label(toolbar, text="Mode:").pack(side=tk.LEFT, padx=(10, 2))
        self._mode_var = tk.StringVar(value="Voltage")
        mode_cb = ttk.Combobox(
            toolbar, textvariable=self._mode_var,
            values=["Voltage", "TempRamp"], state='readonly', width=12
        )
        mode_cb.pack(side=tk.LEFT, padx=2)
        mode_cb.bind("<<ComboboxSelected>>", self._on_mode_change)

        # ── Row 2b: Safe Test Mode checkbox (TempRamp only) ───────────────
        self._safe_test_frame = ttk.Frame(self._parent)
        # Not packed initially — shown only in TempRamp mode via _on_mode_change

        self._safe_test_var = tk.BooleanVar(value=False)
        self._safe_test_cb = ttk.Checkbutton(
            self._safe_test_frame,
            text="⚠ Safe Test Mode  (max 1 V / 9 A — for wiring verification only)",
            variable=self._safe_test_var,
            command=self._on_safe_test_toggle,
        )
        self._safe_test_cb.pack(side=tk.LEFT, padx=6)

        # TC channel selector row (inside _safe_test_frame, TempRamp only)
        tc_row = tk.Frame(self._safe_test_frame)
        tc_row.pack(fill=tk.X, pady=2)

        tk.Label(tc_row, text="PID Thermocouple:", font=("Arial", 9)).pack(side=tk.LEFT, padx=4)

        self._tc_names_var = tk.StringVar(value="(select TC...)")
        self._tc_selector = ttk.Combobox(
            tc_row,
            textvariable=self._tc_names_var,
            values=["(select TC...)"],
            state="readonly",
            width=20
        )
        self._tc_selector.pack(side=tk.LEFT, padx=4)
        self._tc_selector.bind("<<ComboboxSelected>>", lambda e: self._refresh_status())

        self._tc_refresh_btn = ttk.Button(
            tc_row,
            text="Refresh TC List",
            command=self._refresh_tc_list
        )
        self._tc_refresh_btn.pack(side=tk.LEFT, padx=10)

        self._get_tc_names_fn = None

        # ── Row 2c: Safe Mode checkbox (Voltage/Current mode only) ────────
        self._safe_mode_frame = ttk.Frame(self._parent)
        # Packed immediately (Voltage is the default mode)
        self._safe_mode_frame.pack(fill=tk.X, pady=(2, 0), padx=4)

        self._safe_mode_var = tk.BooleanVar(value=False)
        self._safe_mode_check = tk.Checkbutton(
            self._safe_mode_frame,
            text="Safe Mode (≤1V / ≤10A)",
            variable=self._safe_mode_var,
            fg="orange",
            font=("Arial", 9, "bold")
        )
        self._safe_mode_check.pack(side=tk.LEFT, padx=8)

        # ── Row 2d: Entry mode row (TempRamp only — always built, shown conditionally) ─
        self._entry_mode_bar = tk.Frame(self._parent)
        # Not packed initially — shown only in TempRamp mode

        tk.Label(self._entry_mode_bar, text="Block input:", font=("Arial", 9)).pack(side=tk.LEFT, padx=4)
        self._entry_mode_var = tk.StringVar(value="Rate")
        ttk.Radiobutton(
            self._entry_mode_bar, text="Rate + Duration",
            variable=self._entry_mode_var, value="Rate",
            command=self._on_entry_mode_changed
        ).pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(
            self._entry_mode_bar, text="Target Temp + Duration",
            variable=self._entry_mode_var, value="TimeTarget",
            command=self._on_entry_mode_changed
        ).pack(side=tk.LEFT, padx=4)

        # Starting temp row (only visible in TimeTarget mode)
        self._start_temp_frame = tk.Frame(self._parent)
        # Not packed initially

        self._start_temp_var = tk.StringVar(value="25")
        self._start_temp_var.trace_add("write", lambda *_: self._on_start_temp_changed())
        tk.Label(self._start_temp_frame, text="Starting Temp (\u00b0C or K):", font=("Arial", 9)).pack(side=tk.LEFT, padx=4)
        ttk.Entry(self._start_temp_frame, textvariable=self._start_temp_var, width=8).pack(side=tk.LEFT, padx=2)
        tk.Label(self._start_temp_frame, text="(temperature before first block)", font=("Arial", 8), foreground='gray').pack(side=tk.LEFT, padx=4)

        # ── Row 3: Table ──────────────────────────────────────────────────
        self._table_frame = ttk.Frame(self._parent)
        self._table_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        self._build_table_for_mode()

        # ── Row 4: Interpolation selection ────────────────────────────────
        interp_frame = ttk.Frame(self._parent)
        interp_frame.pack(fill=tk.X, padx=4, pady=2)

        ttk.Label(interp_frame, text="Interpolation:").pack(side=tk.LEFT)
        self._interp_var = tk.StringVar(value="Linear")
        interp_cb = ttk.Combobox(
            interp_frame, textvariable=self._interp_var,
            values=["Linear"], state='readonly', width=10
        )
        interp_cb.pack(side=tk.LEFT, padx=4)

        # ── Row 5: Status row ─────────────────────────────────────────────
        status_frame = ttk.Frame(self._parent)
        status_frame.pack(fill=tk.X, padx=4, pady=(0, 4))

        self._ready_label = ttk.Label(
            status_frame, text="Profile ready: NO",
            foreground='red', font=('Arial', 9, 'bold')
        )
        self._ready_label.pack(side=tk.LEFT)

        # ── Row 6: Gains and current caps the run will use ────────────────
        run_frame = ttk.Frame(self._parent)
        run_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        self._gains_label = ttk.Label(run_frame, text="")
        self._gains_label.pack(side=tk.LEFT)
        self._caps_label = ttk.Label(run_frame, text="")
        self._caps_label.pack(side=tk.LEFT, padx=(12, 0))
        self.refresh_run_labels(None)

    def _build_table_for_mode(self):
        """Build (or rebuild) the Treeview columns for the current mode."""
        # Destroy existing tree and scrollbar widgets inside table_frame
        for widget in self._table_frame.winfo_children():
            widget.destroy()

        if self._mode == "TempRamp":
            if getattr(self, '_entry_mode', 'Rate') == "TimeTarget":
                columns = ('#', 'Type', 'Duration (min)', 'Target Temp', 'Rate (auto)')
                col_widths = [30, 70, 100, 110, 100]
            else:
                columns = ('#', 'Type', 'Duration (s)', 'Rate (\u00b0C or K)/min')
                col_widths = [30, 70, 90, 120]
        else:
            columns = ('#', 'Type', 'Duration (s)', 'Start V', 'End V', 'Current (A)')
            col_widths = [30, 70, 90, 70, 70, 80]

        self._tree = ttk.Treeview(
            self._table_frame, columns=columns, show='headings', height=6,
            selectmode='browse'
        )
        for col, width in zip(columns, col_widths):
            self._tree.heading(col, text=col)
            self._tree.column(
                col, width=260 if col == 'Type' else width, anchor='center', stretch=False
            )

        vsb = ttk.Scrollbar(self._table_frame, orient='vertical',
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._tree.bind('<Double-1>', self._on_double_click)

    def _on_mode_change(self, event=None):
        """Handle control mode change from the UI (combobox)."""
        new_mode = self._mode_var.get()
        self.set_mode(new_mode, clear_blocks=True)

    def set_mode(self, mode: str, clear_blocks: bool = True):
        """
        Switch between Voltage and TempRamp modes.
        If clear_blocks=True, the block list is emptied (recommended when manually
        changing modes as the data structures differ).
        """
        old_mode = self._mode
        self._mode = mode
        self._mode_var.set(mode)

        # Rebuild table columns when crossing TempRamp boundary
        if mode == "TempRamp" or old_mode == "TempRamp":
            if clear_blocks:
                self._blocks = []
            self._build_table_for_mode()

        # Show safe test checkbox only in TempRamp mode
        if hasattr(self, '_safe_test_frame'):
            if mode == "TempRamp":
                self._safe_test_frame.pack(fill=tk.X, pady=(2, 0), padx=4,
                                           before=self._table_frame)
            else:
                self._safe_test_frame.pack_forget()

        # Show entry mode bar only in TempRamp mode
        if hasattr(self, '_entry_mode_bar'):
            if mode == "TempRamp":
                self._entry_mode_bar.pack(fill=tk.X, pady=2, before=self._table_frame)
            else:
                self._entry_mode_bar.pack_forget()
                if self._start_temp_frame:
                    self._start_temp_frame.pack_forget()

        # Show Safe Mode checkbox only in Voltage/Current mode
        if hasattr(self, '_safe_mode_frame'):
            if mode == "TempRamp":
                self._safe_mode_frame.pack_forget()
            else:
                self._safe_mode_frame.pack(fill=tk.X, pady=(2, 0), padx=4,
                                           before=self._table_frame)

        self._refresh_status()

    def _on_safe_test_toggle(self):
        """Update internal flag when Safe Test Mode checkbox changes."""
        self._safe_test_mode = self._safe_test_var.get()
        state = "ENABLED" if self._safe_test_mode else "DISABLED"
        logger.info("Safe Test Mode %s (max 1.0 V / 9.0 A ceiling)", state)

    def get_safe_test_mode(self) -> bool:
        """Return True if Safe Test Mode is currently checked."""
        return self._safe_test_mode

    def get_programmer_safe_mode(self) -> bool:
        """Return True if Safe Mode is checked for the Voltage/Current programmer."""
        return self._safe_mode_var.get()

    def _refresh_tc_list(self):
        """Populate the TC selector from the DAQ's available channels."""
        names = []
        if hasattr(self, '_get_tc_names_fn') and self._get_tc_names_fn:
            names = self._get_tc_names_fn()
        if names:
            # names = ["TC1", "TC2", ...]
            self._tc_selector['values'] = ["(select TC...)"] + names
            # If current selection is invalid, set to placeholder
            curr = self._tc_names_var.get()
            if not curr or curr not in names:
                if curr != "(select TC...)":
                    self._tc_names_var.set("(select TC...)")
        else:
            self._tc_selector['values'] = ["(no TCs found)"]
            self._tc_names_var.set("(no TCs found)")
        self._refresh_status()

    def get_selected_tc_name(self) -> str:
        """Return the currently selected TC name for the PID loop."""
        return self._tc_names_var.get()

    def set_selected_tc_name(self, name: str):
        """Set the selected TC name for the PID loop."""
        if name:
            # Check if name is in current values
            current_values = self._tc_selector['values']
            if name in current_values:
                self._tc_names_var.set(name)
            else:
                # If not in values, maybe it needs a refresh or it's a stale name
                # We'll set it anyway so it's ready if/when the list populates
                self._tc_names_var.set(name)
        self._refresh_status()

    def set_tc_names_callback(self, fn):
        """
        Register a callback that returns a list of available TC names.
        Called when the user clicks the refresh button.
        """
        self._get_tc_names_fn = fn
        self._refresh_tc_list()  # Auto-populate on registration

    # ──────────────────────────────────────────────────────────────────────
    # Block operations
    # ──────────────────────────────────────────────────────────────────────

    def _add_block(self):
        """Append a default block and refresh."""
        if self._mode == "TempRamp":
            if getattr(self, '_entry_mode', 'Rate') == "TimeTarget":
                try:
                    chain_temp = float(self._start_temp_var.get())
                except (ValueError, TypeError):
                    chain_temp = 25.0
                for b in self._blocks:
                    if b["type"] == "Ramp":
                        chain_temp = b.get("target_temp_disp", chain_temp + b.get("rate_k_per_min", 1.0) * b.get("duration_sec", 60.0) / 60.0)
                default = {
                    "type": "Ramp",
                    "duration_sec": float(getattr(self._settings, 'pp_default_ramp_duration', 60)),
                    "rate_k_per_min": 1.0,
                    "target_temp_disp": chain_temp + 100.0
                }
            else:
                default = {
                    "type": "Ramp",
                    "duration_sec": float(getattr(self._settings, 'pp_default_ramp_duration', 60)),
                    "rate_k_per_min": 1.0
                }
        else:
            default = {
                "type": "Ramp",
                "duration": self._settings.pp_default_ramp_duration,
                "start_v": self._settings.pp_default_start_v,
                "end_v": self._settings.pp_default_start_v,
                "current_a": self._settings.pp_default_current_a
            }
        self._blocks.append(default)
        self._refresh_table()
        self._refresh_status()

    def _delete_block(self):
        """Remove the currently selected block."""
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a block to delete.")
            return
        if sel[0] == self.SOFT_START_IID:
            return  # Soft start is locked
        idx = self._tree.index(sel[0]) - 1  # row 0 is the Soft-start row
        del self._blocks[idx]
        self._refresh_table()
        self._refresh_status()

    def _move_up(self):
        """Swap selected block with the one above."""
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a block to move.")
            return
        if sel[0] == self.SOFT_START_IID:
            return  # Soft start is locked
        idx = self._tree.index(sel[0]) - 1  # row 0 is the Soft-start row
        if idx == 0:
            return
        self._blocks[idx - 1], self._blocks[idx] = (
            self._blocks[idx], self._blocks[idx - 1]
        )
        self._refresh_table()
        # Re-select moved item
        children = self._tree.get_children()
        if idx < len(children):  # block idx - 1 sits at row idx (Soft-start row first)
            self._tree.selection_set(children[idx])
        self._refresh_status()

    def _move_down(self):
        """Swap selected block with the one below."""
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a block to move.")
            return
        if sel[0] == self.SOFT_START_IID:
            return  # Soft start is locked
        idx = self._tree.index(sel[0]) - 1  # row 0 is the Soft-start row
        if idx >= len(self._blocks) - 1:
            return
        self._blocks[idx], self._blocks[idx + 1] = (
            self._blocks[idx + 1], self._blocks[idx]
        )
        self._refresh_table()
        # Re-select moved item
        children = self._tree.get_children()
        if idx + 2 < len(children):  # block idx + 1 sits at row idx + 2
            self._tree.selection_set(children[idx + 2])
        self._refresh_status()

    # ──────────────────────────────────────────────────────────────────────
    # Table rendering
    # ──────────────────────────────────────────────────────────────────────

    def _refresh_table(self):
        """Clear and re-populate the Treeview from self._blocks."""
        for item in self._tree.get_children():
            self._tree.delete(item)

        self._tree.insert(
            '', 'end', iid=self.SOFT_START_IID,
            values=("", self._soft_start_row_text()),
        )

        if self._mode == "TempRamp":
            if getattr(self, '_entry_mode', 'Rate') == "TimeTarget":
                try:
                    chain_temp = float(self._start_temp_var.get())
                except (ValueError, TypeError, AttributeError):
                    chain_temp = 25.0

                for i, block in enumerate(self._blocks):
                    dur_min = block.get("duration_sec", 60.0) / 60.0
                    rate = block.get("rate_k_per_min", 0.0)
                    target_temp = block.get("target_temp_disp", chain_temp + rate * dur_min)
                    rate_auto = (
                        f"{(target_temp - chain_temp) / dur_min:.2f}" if dur_min > 0 else "—"
                    ) if block["type"] == "Ramp" else "—"
                    row = (i + 1, block["type"], f"{dur_min:.1f}", f"{target_temp:.1f}", rate_auto)
                    self._tree.insert('', 'end', values=row)
                    if block["type"] == "Ramp":
                        chain_temp = target_temp
            else:
                for i, block in enumerate(self._blocks):
                    rate_display = (
                        block.get("rate_k_per_min", 1.0)
                        if block["type"] == "Ramp"
                        else "—"
                    )
                    row = (
                        i + 1,
                        block["type"],
                        block.get("duration_sec", 0.0),
                        rate_display
                    )
                    self._tree.insert('', 'end', values=row)
        else:
            for i, block in enumerate(self._blocks):
                row = (
                    i + 1,
                    block["type"],
                    block["duration"],
                    block.get("start_v", 0.0),
                    block.get("end_v", 0.0),
                    block.get("current_a", 0.0)
                )
                self._tree.insert('', 'end', values=row)

    def _soft_start_row_text(self) -> str:
        """Text of the locked first row, from the thresholds a run would use now."""
        s = self._settings
        return (
            f"Soft start → PID at {s.soft_start_threshold_c:g} °C "
            f"or {s.soft_start_handoff_current_a:g} A"
        )

    @staticmethod
    def _cap_text(name: str, enabled: bool, amps: float) -> str:
        return f"{name}: {amps:g} A" if enabled else f"{name}: OFF"

    def refresh_run_labels(self, snapshot) -> None:
        """
        Show the gains and caps the run uses: from AppSettings when idle, from the
        Snapshot's gains_in_use while a program is running.  The caps always come
        from AppSettings, the same values RunSettings freezes at Run.
        """
        s = self._settings
        if snapshot is not None and snapshot.program is not None and snapshot.program.running:
            kp, ki, kd = snapshot.program.gains_in_use
        else:
            kp, ki, kd = s.pid_kp, s.pid_ki, s.pid_kd
        self._gains_text = f"Gains in use: {kp:g} / {ki:g} / {kd:g}"
        self._caps_text = "  ".join((
            self._cap_text("Soft-start cap", s.soft_start_cap_enabled, s.soft_start_cap_a),
            self._cap_text("Run cap", s.run_cap_enabled, s.run_cap_a),
        ))
        self._gains_label.config(text=self._gains_text)
        self._caps_label.config(text=self._caps_text)

    def get_gains_text(self) -> str:
        """Return the text shown in the gains label."""
        return self._gains_text

    def get_caps_text(self) -> str:
        """Return the text shown in the current-caps label."""
        return self._caps_text

    def _refresh_status(self):
        """Update the duration label and ready indicator."""
        # Handle both key styles (duration_sec for TempRamp, duration for V/I)
        total_seconds = sum(
            block.get("duration_sec", block.get("duration", 0))
            for block in self._blocks
        )
        minutes, secs = divmod(int(total_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        dur_str = f"Total: {hours}h {minutes}m {secs}s" if hours else (f"Total: {minutes}m {secs}s" if minutes else f"Total: {secs}s")
        self._duration_label.config(text=dur_str)

        if self.get_profile_ready():
            self._ready_label.config(
                text="Profile ready: YES", foreground='green'
            )
        else:
            # Construct why not ready
            msg = " NO"
            if not self._blocks:
                msg += " (No blocks)"
            elif self._mode == "TempRamp":
                sel_tc = self.get_selected_tc_name()
                if not sel_tc or sel_tc in ["(no TCs found)", "(select TC...)"]:
                    msg += " (Choose PID TC)"
                else:
                    msg += " (TC Invalid)"

            self._ready_label.config(
                text=f"Profile ready:{msg}", foreground='red'
            )

    # ──────────────────────────────────────────────────────────────────────
    # Cell editor (double-click)
    # ──────────────────────────────────────────────────────────────────────

    def _on_double_click(self, event):
        """Open a popup editor for the clicked cell."""
        region = self._tree.identify_region(event.x, event.y)
        if region != 'cell':
            return

        row_id = self._tree.identify_row(event.y)
        col_id = self._tree.identify_column(event.x)
        if not row_id or not col_id:
            return

        col_index = int(col_id.replace('#', '')) - 1  # 0-based
        if col_index == 0:
            return  # '#' column is read-only

        if row_id == self.SOFT_START_IID:
            return  # Soft start is locked
        row_index = self._tree.index(row_id) - 1  # row 0 is the Soft-start row
        block = self._blocks[row_index]

        # Get cell bounding box for popup placement
        bbox = self._tree.bbox(row_id, col_id)
        if not bbox:
            return

        if self._mode == "TempRamp":
            if getattr(self, '_entry_mode', 'Rate') == "TimeTarget":
                col_names = ['#', 'Type', 'Duration (min)', 'Target Temp', 'Rate (auto)']
                col_name = col_names[col_index] if col_index < len(col_names) else ''
                if col_name == 'Rate (auto)':
                    return  # read-only column
                self._open_timetarget_cell_editor(row_index, col_name, block, bbox)
            else:
                col_names = ['#', 'Type', 'Duration (s)', 'Rate (\u00b0C or K)/min']
                col_name = col_names[col_index] if col_index < len(col_names) else ''
                self._open_tempramp_cell_editor(row_index, col_name, block, bbox)
        else:
            col_names = ['#', 'Type', 'Duration (s)', 'Start V', 'End V', 'Current (A)']
            col_name = col_names[col_index]
            self._open_cell_editor(row_index, col_name, block, bbox)

    def _open_cell_editor(self, row_index, col_name, block, bbox):
        """Create a toplevel popup for editing a single V/I cell."""
        popup = tk.Toplevel(self._parent)
        popup.title(f"Edit {col_name}")
        popup.resizable(False, False)
        popup.grab_set()

        # Position near the cell
        x = self._tree.winfo_rootx() + bbox[0]
        y = self._tree.winfo_rooty() + bbox[1]
        popup.geometry(f"+{x}+{y}")

        ttk.Label(popup, text=f"{col_name}:").grid(row=0, column=0, padx=6, pady=6, sticky='w')

        edit_var = tk.StringVar()

        if col_name == 'Type':
            widget = ttk.Combobox(
                popup, textvariable=edit_var,
                values=["Ramp", "Hold"], state='readonly', width=10
            )
            edit_var.set(block["type"])
            widget.grid(row=0, column=1, padx=6, pady=6)
            widget.focus_set()
        elif col_name == 'Duration (s)':
            # H, M, S editor
            h_var = tk.StringVar()
            m_var = tk.StringVar()
            s_var = tk.StringVar()
            
            total_sec = block.get("duration", 0.0)
            h, rem = divmod(int(total_sec), 3600)
            m, s = divmod(rem, 60)
            # Add back fractional part of seconds
            s += total_sec - int(total_sec)
            
            h_var.set(str(h))
            m_var.set(str(m))
            s_var.set(f"{s:.1f}".rstrip('0').rstrip('.'))
            
            hms_frame = ttk.Frame(popup)
            hms_frame.grid(row=0, column=1, padx=6, pady=6)
            
            h_entry = ttk.Entry(hms_frame, textvariable=h_var, width=3)
            h_entry.pack(side=tk.LEFT)
            ttk.Label(hms_frame, text="h").pack(side=tk.LEFT)
            
            m_entry = ttk.Entry(hms_frame, textvariable=m_var, width=3)
            m_entry.pack(side=tk.LEFT)
            ttk.Label(hms_frame, text="m").pack(side=tk.LEFT)
            
            s_entry = ttk.Entry(hms_frame, textvariable=s_var, width=5)
            s_entry.pack(side=tk.LEFT)
            ttk.Label(hms_frame, text="s").pack(side=tk.LEFT)
            
            h_entry.focus_set()
            h_entry.select_range(0, tk.END)
        else:
            # Map column name to block key
            key_map = {
                'Start V': 'start_v',
                'End V': 'end_v',
                'Current (A)': 'current_a'
            }
            key = key_map[col_name]
            default_val = 180.0 if col_name == 'Current (A)' else 0.0
            edit_var.set(str(block.get(key, default_val)))
            widget = ttk.Entry(popup, textvariable=edit_var, width=14)
            widget.select_range(0, tk.END)
            widget.grid(row=0, column=1, padx=6, pady=6)
            widget.focus_set()

        def _apply():
            if col_name == 'Type':
                val_str = edit_var.get().strip()
                if val_str not in ("Ramp", "Hold"):
                    messagebox.showerror("Invalid", "Type must be 'Ramp' or 'Hold'.",
                                         parent=popup)
                    return
                block["type"] = val_str
                # Sync end_v for Hold
                if val_str == "Hold":
                    block["end_v"] = block["start_v"]
            elif col_name == 'Duration (s)':
                try:
                    h = float(h_var.get() or 0)
                    m = float(m_var.get() or 0)
                    s = float(s_var.get() or 0)
                    v = h * 3600 + m * 60 + s
                    if v <= 0 or v > self.MAX_DURATION:
                        raise ValueError
                except ValueError:
                    messagebox.showerror(
                        "Invalid",
                        f"Duration must be a number between 1 and {self.MAX_DURATION}s.",
                        parent=popup
                    )
                    return
                block["duration"] = v
            else:
                val_str = edit_var.get().strip()
                if col_name == 'Start V':
                    try:
                        v = float(val_str)
                        if v < 0.0 or v > self.MAX_VOLTAGE:
                            raise ValueError
                    except ValueError:
                        messagebox.showerror(
                            "Invalid",
                            f"Start V must be between 0.0 and {self.MAX_VOLTAGE}V.",
                            parent=popup
                        )
                        return
                    block["start_v"] = v
                    if block["type"] == "Hold":
                        block["end_v"] = v
                elif col_name == 'End V':
                    try:
                        v = float(val_str)
                        if v < 0.0 or v > self.MAX_VOLTAGE:
                            raise ValueError
                    except ValueError:
                        messagebox.showerror(
                            "Invalid",
                            f"End V must be between 0.0 and {self.MAX_VOLTAGE}V.",
                            parent=popup
                        )
                        return
                    block["end_v"] = v
                elif col_name == 'Current (A)':
                    try:
                        v = float(val_str)
                        if v < 0.0 or v > self.MAX_CURRENT:
                            raise ValueError
                    except ValueError:
                        messagebox.showerror(
                            "Invalid",
                            f"Current (A) must be between 0.0 and {self.MAX_CURRENT}A.",
                            parent=popup
                        )
                        return
                    block["current_a"] = v

            self._refresh_table()
            self._refresh_status()
            popup.destroy()

        btn_frame = ttk.Frame(popup)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=4)
        ttk.Button(btn_frame, text="OK", command=_apply).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel",
                   command=popup.destroy).pack(side=tk.LEFT, padx=4)

        popup.bind('<Return>', lambda e: _apply())
        popup.bind('<Escape>', lambda e: popup.destroy())

    def _open_tempramp_cell_editor(self, row_index, col_name, block, bbox):
        """Create a toplevel popup for editing a single TempRamp cell."""
        popup = tk.Toplevel(self._parent)
        popup.title(f"Edit {col_name}")
        popup.resizable(False, False)
        popup.grab_set()

        x = self._tree.winfo_rootx() + bbox[0]
        y = self._tree.winfo_rooty() + bbox[1]
        popup.geometry(f"+{x}+{y}")

        ttk.Label(popup, text=f"{col_name}:").grid(row=0, column=0, padx=6, pady=6, sticky='w')

        edit_var = tk.StringVar()

        if col_name == 'Type':
            widget = ttk.Combobox(
                popup, textvariable=edit_var,
                values=["Ramp", "Hold"], state='readonly', width=10
            )
            edit_var.set(block["type"])
            widget.grid(row=0, column=1, padx=6, pady=6)
            widget.focus_set()
        elif col_name == 'Duration (s)':
            # H, M, S editor
            h_var = tk.StringVar()
            m_var = tk.StringVar()
            s_var = tk.StringVar()
            
            total_sec = block.get("duration_sec", 60.0)
            h, rem = divmod(int(total_sec), 3600)
            m, s = divmod(rem, 60)
            # Add back fractional part of seconds
            s += total_sec - int(total_sec)
            
            h_var.set(str(h))
            m_var.set(str(m))
            s_var.set(f"{s:.1f}".rstrip('0').rstrip('.'))
            
            hms_frame = ttk.Frame(popup)
            hms_frame.grid(row=0, column=1, padx=6, pady=6)
            
            h_entry = ttk.Entry(hms_frame, textvariable=h_var, width=3)
            h_entry.pack(side=tk.LEFT)
            ttk.Label(hms_frame, text="h").pack(side=tk.LEFT)
            
            m_entry = ttk.Entry(hms_frame, textvariable=m_var, width=3)
            m_entry.pack(side=tk.LEFT)
            ttk.Label(hms_frame, text="m").pack(side=tk.LEFT)
            
            s_entry = ttk.Entry(hms_frame, textvariable=s_var, width=5)
            s_entry.pack(side=tk.LEFT)
            ttk.Label(hms_frame, text="s").pack(side=tk.LEFT)
            
            h_entry.focus_set()
            h_entry.select_range(0, tk.END)
        elif col_name in ('Rate (K/min)', 'Rate (\u00b0C or K)/min'):
            current_rate = str(block.get("rate_k_per_min", 1.0))
            edit_var.set(current_rate)
            widget = ttk.Combobox(
                popup, textvariable=edit_var,
                values=["-10", "-5", "-1", "-0.1", "0.1", "1", "5", "10"], width=10
            )
            if block["type"] == "Hold":
                widget.config(state='disabled')
            widget.grid(row=0, column=1, padx=6, pady=6)
            widget.focus_set()
        else:
            popup.destroy()
            return

        def _apply():
            val_str = edit_var.get().strip()
            if col_name == 'Type':
                if val_str not in ("Ramp", "Hold"):
                    messagebox.showerror("Invalid", "Type must be 'Ramp' or 'Hold'.",
                                         parent=popup)
                    return
                block["type"] = val_str
                if val_str == "Hold":
                    block["rate_k_per_min"] = 0.0

            elif col_name == 'Duration (s)':
                try:
                    h = float(h_var.get() or 0)
                    m = float(m_var.get() or 0)
                    s = float(s_var.get() or 0)
                    v = h * 3600 + m * 60 + s
                    if v <= 0:
                        raise ValueError
                except ValueError:
                    messagebox.showerror(
                        "Invalid", "Duration must be a positive number.",
                        parent=popup
                    )
                    return
                block["duration_sec"] = v

            elif col_name in ('Rate (K/min)', 'Rate (\u00b0C or K)/min'):
                if block["type"] == "Hold":
                    popup.destroy()
                    return
                try:
                    v = float(val_str)
                except ValueError:
                    messagebox.showerror(
                        "Invalid", "Rate must be a number.",
                        parent=popup
                    )
                    return
                block["rate_k_per_min"] = v

            self._refresh_table()
            self._refresh_status()
            popup.destroy()

        btn_frame = ttk.Frame(popup)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=4)
        ttk.Button(btn_frame, text="OK", command=_apply).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel",
                   command=popup.destroy).pack(side=tk.LEFT, padx=4)

        popup.bind('<Return>', lambda e: _apply())
        popup.bind('<Escape>', lambda e: popup.destroy())

    def _on_entry_mode_changed(self):
        """Switch between Rate+Duration and TimeTarget+Duration block entry."""
        self._entry_mode = self._entry_mode_var.get()

        if self._entry_mode == "TimeTarget":
            self._start_temp_frame.pack(fill=tk.X, pady=2, before=self._table_frame)
        else:
            self._start_temp_frame.pack_forget()

        self._build_table_for_mode()
        self._refresh_table()
        self._refresh_status()

    def _on_start_temp_changed(self):
        """Triggered when starting temp entry changes in TimeTarget mode."""
        if getattr(self, '_entry_mode', 'Rate') == "TimeTarget":
            self._recompute_timetarget_rates()
            self._refresh_table()

    def _recompute_timetarget_rates(self):
        """
        Walk all blocks in TimeTarget mode and set rate_k_per_min from the
        target_temp_disp chain. Safe to call when in Rate mode — does nothing.
        """
        if getattr(self, '_entry_mode', 'Rate') != "TimeTarget":
            return
        try:
            chain_temp = float(self._start_temp_var.get())
        except (ValueError, TypeError, AttributeError):
            chain_temp = 25.0

        for block in self._blocks:
            dur_min = block.get("duration_sec", 60.0) / 60.0
            if block["type"] == "Ramp":
                target = block.get("target_temp_disp", chain_temp)
                if dur_min > 0:
                    block["rate_k_per_min"] = (target - chain_temp) / dur_min
                else:
                    block["rate_k_per_min"] = 0.0
                chain_temp = target
            else:
                # Hold block: target stays at current temp
                block["target_temp_disp"] = chain_temp

    def _open_timetarget_cell_editor(self, row_index, col_name, block, bbox):
        """
        Popup editor for Time+Target mode blocks.
        Edits Type, Duration (min), and Target Temp.
        Recomputes rate_k_per_min from the full chain after apply.
        """
        popup = tk.Toplevel(self._parent)
        popup.title(f"Edit {col_name}")
        popup.resizable(False, False)
        popup.grab_set()

        x = self._tree.winfo_rootx() + bbox[0]
        y = self._tree.winfo_rooty() + bbox[1]
        popup.geometry(f"+{x}+{y}")

        ttk.Label(popup, text=f"{col_name}:").grid(row=0, column=0, padx=6, pady=6, sticky='w')
        edit_var = tk.StringVar()

        if col_name == 'Type':
            widget = ttk.Combobox(
                popup, textvariable=edit_var,
                values=["Ramp", "Hold"], state='readonly', width=10
            )
            edit_var.set(block["type"])
            widget.grid(row=0, column=1, padx=6, pady=6)
            widget.focus_set()

        elif col_name == 'Duration (min)':
            edit_var.set(f"{block.get('duration_sec', 60.0) / 60.0:.2f}")
            widget = ttk.Entry(popup, textvariable=edit_var, width=10)
            widget.grid(row=0, column=1, padx=6, pady=6)
            widget.focus_set()
            widget.select_range(0, tk.END)
            ttk.Label(popup, text="minutes", font=("Arial", 8)).grid(row=0, column=2, padx=2)

        elif col_name == 'Target Temp':
            current_target = block.get("target_temp_disp", "")
            edit_var.set(str(current_target) if current_target != "" else "")
            widget = ttk.Entry(popup, textvariable=edit_var, width=10)
            widget.grid(row=0, column=1, padx=6, pady=6)
            widget.focus_set()
            widget.select_range(0, tk.END)
            ttk.Label(popup, text="\u00b0C or K", font=("Arial", 8)).grid(row=0, column=2, padx=2)

        else:
            popup.destroy()
            return

        def _apply():
            val_str = edit_var.get().strip()
            if col_name == 'Type':
                if val_str not in ("Ramp", "Hold"):
                    messagebox.showerror("Invalid", "Type must be Ramp or Hold.", parent=popup)
                    return
                block["type"] = val_str

            elif col_name == 'Duration (min)':
                try:
                    dur_min = float(val_str)
                    if dur_min <= 0:
                        raise ValueError
                except ValueError:
                    messagebox.showerror("Invalid", "Duration must be a positive number of minutes.", parent=popup)
                    return
                block["duration_sec"] = dur_min * 60.0

            elif col_name == 'Target Temp':
                try:
                    target = float(val_str)
                except ValueError:
                    messagebox.showerror("Invalid", "Target temperature must be a number.", parent=popup)
                    return
                block["target_temp_disp"] = target

            self._recompute_timetarget_rates()
            self._refresh_table()
            self._refresh_status()
            popup.destroy()

        btn_frame = ttk.Frame(popup)
        btn_frame.grid(row=1, column=0, columnspan=3, pady=4)
        ttk.Button(btn_frame, text="OK", command=_apply).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=popup.destroy).pack(side=tk.LEFT, padx=4)
        popup.bind('<Return>', lambda e: _apply())
        popup.bind('<Escape>', lambda e: popup.destroy())

    # ──────────────────────────────────────────────────────────────────────
    # Save / Load
    # ──────────────────────────────────────────────────────────────────────

    def _save_profile(self):
        """Save the current block list to a JSON file."""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Profile", "*.json"), ("All Files", "*.*")],
            title="Save Power Profile",
            initialdir=self._settings.pp_profiles_folder or "."
        )
        if not filepath:
            return
        try:
            data = {
                "mode": self._mode,
                "blocks": self._blocks
            }
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Saved", f"Profile saved to:\n{filepath}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save profile:\n{e}")

    def _load_profile(self):
        """Load a block list from a JSON file."""
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON Profile", "*.json"), ("All Files", "*.*")],
            title="Load Power Profile",
            initialdir=self._settings.pp_profiles_folder or "."
        )
        if not filepath:
            return

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            if isinstance(data, dict):
                mode = data.get("mode", "Voltage")
                blocks = data.get("blocks", [])
            elif isinstance(data, list):
                mode = "Voltage"
                blocks = data
            else:
                messagebox.showerror("Load Error", "Invalid profile format.")
                return

            # ── TempRamp profile ──────────────────────────────────────────
            if mode == "TempRamp":
                validated = []
                for i, block in enumerate(blocks):
                    if not isinstance(block, dict):
                        messagebox.showerror("Load Error",
                                             f"Block {i+1} is not a valid object.")
                        return
                    if block.get("type") not in ("Ramp", "Hold"):
                        messagebox.showerror("Load Error",
                                             f"Block {i+1}: type must be 'Ramp' or 'Hold'.")
                        return
                    try:
                        dur = float(block["duration_sec"])
                        if dur <= 0:
                            raise ValueError
                    except (KeyError, ValueError, TypeError):
                        messagebox.showerror("Load Error",
                                             f"Block {i+1}: invalid duration_sec.")
                        return
                    try:
                        rate = float(block.get("rate_k_per_min", 0.0))
                    except (ValueError, TypeError):
                        messagebox.showerror("Load Error",
                                             f"Block {i+1}: invalid rate_k_per_min.")
                        return
                    validated.append({
                        "type": block["type"],
                        "duration_sec": dur,
                        "rate_k_per_min": rate
                    })

                old_mode = self._mode
                self._mode = "TempRamp"
                self._mode_var.set("TempRamp")
                if old_mode != "TempRamp":
                    self._build_table_for_mode()
                self._blocks = validated
                self._refresh_table()
                self._refresh_status()
                return

            # ── Voltage profile (treat any non-TempRamp mode as Voltage) ──────
            self._mode = "Voltage"
            self._mode_var.set("Voltage")

            validated = []
            for i, block in enumerate(blocks):
                if not isinstance(block, dict):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1} is not a valid object.")
                    return
                if not {"type", "duration", "start_v", "end_v"}.issubset(block.keys()):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1} is missing required fields.")
                    return
                if block["type"] not in ("Ramp", "Hold"):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1}: type must be 'Ramp' or 'Hold'.")
                    return
                try:
                    duration = float(block["duration"])
                    start_v = float(block["start_v"])
                    end_v = float(block["end_v"])
                except (ValueError, TypeError):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1}: numeric values are invalid.")
                    return

                # Support old format (start_a / end_a) and new format (current_a)
                if "current_a" in block:
                    try:
                        current_a = float(block["current_a"])
                    except (ValueError, TypeError):
                        messagebox.showerror("Load Error",
                                             f"Block {i+1}: invalid current_a value.")
                        return
                elif "start_a" in block:
                    # Old profile: collapse to single ceiling value
                    try:
                        current_a = float(block.get("start_a", 0.0))
                    except (ValueError, TypeError):
                        current_a = 0.0
                else:
                    current_a = 0.0

                if not (0 < duration <= self.MAX_DURATION):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1}: duration out of range.")
                    return
                if not (0.0 <= start_v <= self.MAX_VOLTAGE):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1}: Start V out of range (0–{self.MAX_VOLTAGE}V).")
                    return
                if not (0.0 <= end_v <= self.MAX_VOLTAGE):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1}: End V out of range (0–{self.MAX_VOLTAGE}V).")
                    return
                if not (0.0 <= current_a <= self.MAX_CURRENT):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1}: Current (A) out of range.")
                    return

                validated.append({
                    "type": block["type"],
                    "duration": duration,
                    "start_v": start_v,
                    "end_v": end_v,
                    "current_a": current_a
                })

            self._blocks = validated
            self._refresh_table()
            self._refresh_status()

        except json.JSONDecodeError as e:
            messagebox.showerror("Load Error", f"Invalid JSON file:\n{e}")
        except Exception as e:
            messagebox.showerror("Load Error", f"Could not load profile:\n{e}")

    # ──────────────────────────────────────────────────────────────────────
    # Preview computation
    # ──────────────────────────────────────────────────────────────────────

    def compute_preview(self):
        """
        Compute the voltage/current waveform at 1-second intervals.

        Returns:
            (times, voltages, currents) — three lists of floats
        """
        times = []
        voltages = []
        currents = []
        t = 0
        end_v = 0.0
        block_a = 0.0

        for block in self._blocks:
            duration = block["duration"]
            start_v = block["start_v"]
            end_v = block["end_v"] if block["type"] == "Ramp" else block["start_v"]
            block_a = block.get("current_a", 0.0)

            for second in range(int(duration)):
                fraction = second / duration if duration > 0 else 0
                if block["type"] == "Ramp":
                    v = start_v + (end_v - start_v) * fraction
                else:
                    v = start_v
                a = block_a
                times.append(t)
                voltages.append(v)
                currents.append(a)
                t += 1

        # Append final point
        times.append(t)
        voltages.append(end_v)
        currents.append(block_a)

        return times, voltages, currents

    def _compute_temp_preview(self) -> tuple:
        """
        Compute the temperature (K) vs time preview for TempRamp mode.

        Returns:
            (times, temps_k) — two lists of floats
        """
        times = [0.0]
        temps = [293.15]  # start at room temperature (20°C = 293.15 K)

        for block in self._blocks:
            duration = block['duration_sec']
            n_points = max(2, int(duration / 10))  # one point every ~10 seconds
            t_start = times[-1]
            temp_start = temps[-1]

            if block['type'] == "Hold":
                for i in range(1, n_points + 1):
                    times.append(t_start + duration * i / n_points)
                    temps.append(temp_start)
            else:
                rate_k_per_sec = block['rate_k_per_min'] / 60.0
                for i in range(1, n_points + 1):
                    dt = duration * i / n_points
                    times.append(t_start + dt)
                    temps.append(temp_start + rate_k_per_sec * dt)

        return times, temps

    def get_temp_preview_with_blocks(self):
        """Return (times, temps_k, blocks) for the enhanced preview graph."""
        times, temps_k = self._compute_temp_preview()
        return times, temps_k, list(self._blocks)

    def get_profile_ready(self):
        """
        Return True if the profile has at least one block AND
        (if in TempRamp mode) a valid thermocouple is selected.
        """
        if len(self._blocks) < 1:
            return False

        if self._mode == "TempRamp":
            sel_tc = self.get_selected_tc_name()
            placeholders = ["(no TCs found)", "(select TC...)"]
            if not sel_tc or sel_tc in placeholders:
                return False
            # Check if selection is actually in the list of available TCs
            all_vals = list(self._tc_selector['values'])
            valid_list = [v for v in all_vals if v not in placeholders]
            if not valid_list or sel_tc not in valid_list:
                return False

        return True

    def get_preview_data(self):
        """
        Return preview data appropriate for the current mode.

        For Voltage/Current: returns (times, voltages, currents) if ready.
        For TempRamp: returns (times, temps_k, None) if ready.
        Returns ([], [], []) if not ready.
        """
        if not self.get_profile_ready():
            return [], [], []

        if self._mode == "TempRamp":
            times, temps_k = self._compute_temp_preview()
            return times, temps_k, None

        return self.compute_preview()

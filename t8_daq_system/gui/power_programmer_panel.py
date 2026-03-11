"""
power_programmer_panel.py
PURPOSE: Power Programmer Panel

A table-based block editor where each row defines a power profile segment.
Block types:
  "Ramp" - linearly interpolates from Start V/A to End V/A over Duration
  "Hold" - stays at Start V/A for Duration

In TempRamp mode each block specifies a ramp rate (K/min); a PID controller
drives the actual power supply to achieve that temperature rise rate.

Computes a time-series preview from the block list.
Provides Save/Load of profiles as JSON files.
Fires a callback with the computed preview data when the profile is confirmed.
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


class PowerProgrammerPanel:
    """
    Block editor UI and preview logic for Power Programmer mode.

    Voltage/Current mode — each block is a dict:
        {
            "type": "Ramp" or "Hold",
            "duration": float (seconds, min 1, max 86400),
            "start_v": float (volts, 0.0–6.0),
            "end_v":   float (volts, 0.0–6.0),
            "start_a": float (amps, 0.0–180.0),
            "end_a":   float (amps, 0.0–180.0)
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
        self._mode = "Voltage"  # "Voltage", "Current", or "TempRamp"
        self._safe_test_mode = False  # Controlled by Safe Test Mode checkbox

        self._table_frame = None  # kept as ref so _rebuild_table_columns can destroy/recreate
        self._tree = None
        self._tree_vsb = None

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
            values=["Voltage", "Current", "TempRamp"], state='readonly', width=12
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

    def _build_table_for_mode(self):
        """Build (or rebuild) the Treeview columns for the current mode."""
        # Destroy existing tree and scrollbar widgets inside table_frame
        for widget in self._table_frame.winfo_children():
            widget.destroy()

        if self._mode == "TempRamp":
            columns = ('#', 'Type', 'Duration (s)', 'Rate (K/min)')
            col_widths = [30, 70, 90, 90]
        else:
            columns = ('#', 'Type', 'Duration (s)', 'Start V', 'End V', 'Start A', 'End A')
            col_widths = [30, 70, 90, 60, 60, 60, 60]

        self._tree = ttk.Treeview(
            self._table_frame, columns=columns, show='headings', height=6,
            selectmode='browse'
        )
        for col, width in zip(columns, col_widths):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=width, anchor='center', stretch=False)

        vsb = ttk.Scrollbar(self._table_frame, orient='vertical',
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._tree.bind('<Double-1>', self._on_double_click)

    def _on_mode_change(self, event=None):
        """Handle control mode change."""
        new_mode = self._mode_var.get()
        old_mode = self._mode
        self._mode = new_mode

        # Rebuild table columns when crossing TempRamp boundary
        if new_mode == "TempRamp" or old_mode == "TempRamp":
            self._blocks = []
            self._build_table_for_mode()

        # Show safe test checkbox only in TempRamp mode
        if hasattr(self, '_safe_test_frame'):
            if new_mode == "TempRamp":
                self._safe_test_frame.pack(fill=tk.X, pady=(2, 0), padx=4,
                                           before=self._table_frame)
            else:
                self._safe_test_frame.pack_forget()

        self._refresh_status()

    def _on_safe_test_toggle(self):
        """Update internal flag when Safe Test Mode checkbox changes."""
        self._safe_test_mode = self._safe_test_var.get()
        state = "ENABLED" if self._safe_test_mode else "DISABLED"
        print(f"[PowerProgrammerPanel] Safe Test Mode {state} "
              f"(max 1.0 V / 9.0 A ceiling)")

    def get_safe_test_mode(self) -> bool:
        """Return True if Safe Test Mode is currently checked."""
        return self._safe_test_mode

    # ──────────────────────────────────────────────────────────────────────
    # Block operations
    # ──────────────────────────────────────────────────────────────────────

    def _add_block(self):
        """Append a default block and refresh."""
        if self._mode == "TempRamp":
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
                "start_a": self._settings.pp_default_start_a,
                "end_a": self._settings.pp_default_start_a
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
        idx = self._tree.index(sel[0])
        del self._blocks[idx]
        self._refresh_table()
        self._refresh_status()

    def _move_up(self):
        """Swap selected block with the one above."""
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a block to move.")
            return
        idx = self._tree.index(sel[0])
        if idx == 0:
            return
        self._blocks[idx - 1], self._blocks[idx] = (
            self._blocks[idx], self._blocks[idx - 1]
        )
        self._refresh_table()
        # Re-select moved item
        children = self._tree.get_children()
        if idx - 1 < len(children):
            self._tree.selection_set(children[idx - 1])
        self._refresh_status()

    def _move_down(self):
        """Swap selected block with the one below."""
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a block to move.")
            return
        idx = self._tree.index(sel[0])
        if idx >= len(self._blocks) - 1:
            return
        self._blocks[idx], self._blocks[idx + 1] = (
            self._blocks[idx + 1], self._blocks[idx]
        )
        self._refresh_table()
        # Re-select moved item
        children = self._tree.get_children()
        if idx + 1 < len(children):
            self._tree.selection_set(children[idx + 1])
        self._refresh_status()

    # ──────────────────────────────────────────────────────────────────────
    # Table rendering
    # ──────────────────────────────────────────────────────────────────────

    def _refresh_table(self):
        """Clear and re-populate the Treeview from self._blocks."""
        for item in self._tree.get_children():
            self._tree.delete(item)

        if self._mode == "TempRamp":
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
                    block.get("start_a", 0.0),
                    block.get("end_a", 0.0)
                )
                self._tree.insert('', 'end', values=row)

    def _refresh_status(self):
        """Update the duration label and ready indicator."""
        # Handle both key styles (duration_sec for TempRamp, duration for V/I)
        total_seconds = sum(
            block.get("duration_sec", block.get("duration", 0))
            for block in self._blocks
        )
        minutes, secs = divmod(int(total_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            dur_str = f"Total: {hours}h {minutes}m {secs}s"
        elif minutes:
            dur_str = f"Total: {minutes}m {secs}s"
        else:
            dur_str = f"Total: {secs}s"
        self._duration_label.config(text=dur_str)

        if self.get_profile_ready():
            self._ready_label.config(
                text="Profile ready: YES", foreground='green'
            )
        else:
            self._ready_label.config(
                text="Profile ready: NO", foreground='red'
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

        row_index = self._tree.index(row_id)
        block = self._blocks[row_index]

        # Get cell bounding box for popup placement
        bbox = self._tree.bbox(row_id, col_id)
        if not bbox:
            return

        if self._mode == "TempRamp":
            col_names = ['#', 'Type', 'Duration (s)', 'Rate (K/min)']
            col_name = col_names[col_index]
            self._open_tempramp_cell_editor(row_index, col_name, block, bbox)
        else:
            col_names = ['#', 'Type', 'Duration (s)', 'Start V', 'End V', 'Start A', 'End A']
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
                'Start A': 'start_a',
                'End A': 'end_a'
            }
            key = key_map[col_name]
            edit_var.set(str(block.get(key, 0.0)))
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
                # Sync end values for Hold
                if val_str == "Hold":
                    block["end_v"] = block["start_v"]
                    block["end_a"] = block.get("start_a", 0.0)
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
                elif col_name == 'Start A':
                    try:
                        v = float(val_str)
                        if v < 0.0 or v > self.MAX_CURRENT:
                            raise ValueError
                    except ValueError:
                        messagebox.showerror(
                            "Invalid",
                            f"Start A must be between 0.0 and {self.MAX_CURRENT}A.",
                            parent=popup
                        )
                        return
                    block["start_a"] = v
                    if block["type"] == "Hold":
                        block["end_a"] = v
                elif col_name == 'End A':
                    try:
                        v = float(val_str)
                        if v < 0.0 or v > self.MAX_CURRENT:
                            raise ValueError
                    except ValueError:
                        messagebox.showerror(
                            "Invalid",
                            f"End A must be between 0.0 and {self.MAX_CURRENT}A.",
                            parent=popup
                        )
                        return
                    block["end_a"] = v

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
        elif col_name == 'Rate (K/min)':
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

            elif col_name == 'Rate (K/min)':
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

            # ── Voltage / Current profile ─────────────────────────────────
            self._mode = mode
            self._mode_var.set(mode)
            if self._mode == "TempRamp":
                # Shouldn't reach here, but guard anyway
                self._build_table_for_mode()

            validated = []
            for i, block in enumerate(blocks):
                if not isinstance(block, dict):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1} is not a valid object.")
                    return
                # Allow both old (current_a) and new (start_a, end_a) formats
                has_old = "current_a" in block
                has_new = "start_a" in block and "end_a" in block
                if not ({"type", "duration", "start_v", "end_v"}.issubset(block.keys()) and (has_old or has_new)):
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
                    start_a = float(block.get("start_a", block.get("current_a", 0.0)))
                    end_a = float(block.get("end_a", block.get("current_a", 0.0)))
                except (ValueError, TypeError):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1}: numeric values are invalid.")
                    return

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
                if not (0.0 <= start_a <= self.MAX_CURRENT):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1}: Start A out of range (0–{self.MAX_CURRENT}A).")
                    return
                if not (0.0 <= end_a <= self.MAX_CURRENT):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1}: End A out of range (0–{self.MAX_CURRENT}A).")
                    return

                validated.append({
                    "type": block["type"],
                    "duration": duration,
                    "start_v": start_v,
                    "end_v": end_v,
                    "start_a": start_a,
                    "end_a": end_a
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
        end_a = 0.0

        for block in self._blocks:
            duration = block["duration"]
            start_v = block["start_v"]
            end_v = block["end_v"] if block["type"] == "Ramp" else block["start_v"]
            start_a = block.get("start_a", 0.0)
            end_a = block.get("end_a", start_a) if block["type"] == "Ramp" else start_a

            for second in range(int(duration)):
                fraction = second / duration if duration > 0 else 0
                if block["type"] == "Ramp":
                    v = start_v + (end_v - start_v) * fraction
                    a = start_a + (end_a - start_a) * fraction
                else:
                    v = start_v
                    a = start_a
                times.append(t)
                voltages.append(v)
                currents.append(a)
                t += 1

        # Append final point
        times.append(t)
        voltages.append(end_v)
        currents.append(end_a)

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

    def get_profile_ready(self):
        """Return True if the profile has at least one block."""
        return len(self._blocks) >= 1

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

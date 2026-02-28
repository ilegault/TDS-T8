"""
power_programmer_panel.py
PURPOSE: Power Programmer Panel

A table-based block editor where each row defines a power profile segment.
Block types:
  "Ramp" - linearly interpolates from Start V to End V over Duration
  "Hold" - stays at Start V for Duration

Computes a time-series preview of voltage and current from the block list.
Provides Save/Load of profiles as JSON files.
Fires a callback with the computed preview data when the profile is confirmed.
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


class PowerProgrammerPanel:
    """
    Block editor UI and preview logic for Power Programmer mode.

    Each block is a dict:
        {
            "type": "Ramp" or "Hold",
            "duration": float (seconds, min 1, max 86400),
            "start_v": float (volts, 0.0–6.0),
            "end_v":   float (volts, 0.0–6.0),
            "current_a": float (amps, 0.0–180.0)
        }
    """

    # Hard limits for Keysight N5700
    MAX_VOLTAGE = 6.0
    MAX_CURRENT = 180.0
    MAX_DURATION = 86400

    def __init__(self, parent_frame, on_profile_confirmed_callback,
                 on_panel_closed_callback):
        """
        Args:
            parent_frame: tkinter frame to build into
            on_profile_confirmed_callback(times, voltages, currents):
                Called when user confirms the profile. Receives three lists of floats.
            on_panel_closed_callback():
                Called when the panel is hidden/closed.
        """
        self._parent = parent_frame
        self._on_confirmed = on_profile_confirmed_callback
        self._on_closed = on_panel_closed_callback

        self._blocks = []  # list of block dicts

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
            title_frame, text="⚡ Power Programmer",
            font=('Arial', 12, 'bold')
        ).pack(side=tk.LEFT)

        self._duration_label = ttk.Label(title_frame, text="Total: 0s")
        self._duration_label.pack(side=tk.RIGHT)

        # ── Row 2: Toolbar ────────────────────────────────────────────────
        toolbar = ttk.Frame(self._parent)
        toolbar.pack(fill=tk.X, padx=4, pady=2)

        ttk.Button(toolbar, text="➕ Add Block",
                   command=self._add_block).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="➖ Delete Block",
                   command=self._delete_block).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="⬆ Move Up",
                   command=self._move_up).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="⬇ Move Down",
                   command=self._move_down).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="💾 Save Profile",
                   command=self._save_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="📂 Load Profile",
                   command=self._load_profile).pack(side=tk.LEFT, padx=2)

        # ── Row 3: Table ──────────────────────────────────────────────────
        table_frame = ttk.Frame(self._parent)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        columns = ('#', 'Type', 'Duration (s)', 'Start V', 'End V', 'Current (A)')
        col_widths = [30, 70, 90, 70, 70, 90]

        self._tree = ttk.Treeview(
            table_frame, columns=columns, show='headings', height=6,
            selectmode='browse'
        )
        for col, width in zip(columns, col_widths):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=width, anchor='center', stretch=False)

        vsb = ttk.Scrollbar(table_frame, orient='vertical',
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._tree.bind('<Double-1>', self._on_double_click)

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

    # ──────────────────────────────────────────────────────────────────────
    # Block operations
    # ──────────────────────────────────────────────────────────────────────

    def _add_block(self):
        """Append a default block and refresh."""
        default = {
            "type": "Ramp",
            "duration": 60,
            "start_v": 0.0,
            "end_v": 1.0,
            "current_a": 0.5
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
        for i, block in enumerate(self._blocks):
            row = (
                i + 1,
                block["type"],
                block["duration"],
                block["start_v"],
                block["end_v"],
                block["current_a"]
            )
            self._tree.insert('', 'end', values=row)

    def _refresh_status(self):
        """Update the duration label and ready indicator."""
        total_seconds = sum(b["duration"] for b in self._blocks)
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
                text="Profile ready: YES ✓", foreground='green'
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

        col_names = ['#', 'Type', 'Duration (s)', 'Start V', 'End V', 'Current (A)']
        col_name = col_names[col_index]

        self._open_cell_editor(row_index, col_name, block, bbox)

    def _open_cell_editor(self, row_index, col_name, block, bbox):
        """Create a toplevel popup for editing a single cell."""
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
        else:
            # Map column name to block key
            key_map = {
                'Duration (s)': 'duration',
                'Start V': 'start_v',
                'End V': 'end_v',
                'Current (A)': 'current_a'
            }
            key = key_map[col_name]
            edit_var.set(str(block[key]))
            widget = ttk.Entry(popup, textvariable=edit_var, width=14)
            widget.select_range(0, tk.END)

        widget.grid(row=0, column=1, padx=6, pady=6)
        widget.focus_set()

        def _apply():
            val_str = edit_var.get().strip()

            if col_name == 'Type':
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
                    v = float(val_str)
                    if v <= 0 or v > self.MAX_DURATION:
                        raise ValueError
                except ValueError:
                    messagebox.showerror(
                        "Invalid",
                        f"Duration must be a number between 1 and {self.MAX_DURATION}.",
                        parent=popup
                    )
                    return
                block["duration"] = v
            elif col_name == 'Start V':
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
                        f"Current must be between 0.0 and {self.MAX_CURRENT}A.",
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

    # ──────────────────────────────────────────────────────────────────────
    # Save / Load
    # ──────────────────────────────────────────────────────────────────────

    def _save_profile(self):
        """Save the current block list to a JSON file."""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Profile", "*.json"), ("All Files", "*.*")],
            title="Save Power Profile"
        )
        if not filepath:
            return
        try:
            with open(filepath, 'w') as f:
                json.dump(self._blocks, f, indent=2)
            messagebox.showinfo("Saved", f"Profile saved to:\n{filepath}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save profile:\n{e}")

    def _load_profile(self):
        """Load a block list from a JSON file."""
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON Profile", "*.json"), ("All Files", "*.*")],
            title="Load Power Profile"
        )
        if not filepath:
            return
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            if not isinstance(data, list):
                messagebox.showerror("Load Error", "Invalid profile file format.")
                return

            validated = []
            required_keys = {"type", "duration", "start_v", "end_v", "current_a"}
            for i, block in enumerate(data):
                if not isinstance(block, dict):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1} is not a valid object.")
                    return
                if not required_keys.issubset(block.keys()):
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
                    current_a = float(block["current_a"])
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
                if not (0.0 <= current_a <= self.MAX_CURRENT):
                    messagebox.showerror("Load Error",
                                         f"Block {i+1}: Current out of range (0–{self.MAX_CURRENT}A).")
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
        current_a = 0.0

        for block in self._blocks:
            duration = block["duration"]
            start_v = block["start_v"]
            end_v = block["end_v"] if block["type"] == "Ramp" else block["start_v"]
            current_a = block["current_a"]

            for second in range(int(duration)):
                fraction = second / duration if duration > 0 else 0
                if block["type"] == "Ramp":
                    v = start_v + (end_v - start_v) * fraction
                else:
                    v = start_v
                times.append(t)
                voltages.append(v)
                currents.append(current_a)
                t += 1

        # Append final point
        times.append(t)
        voltages.append(end_v)
        currents.append(current_a)

        return times, voltages, currents

    def get_profile_ready(self):
        """Return True if the profile has at least one block."""
        return len(self._blocks) >= 1

    def get_preview_data(self):
        """Return compute_preview() if profile ready, else ([], [], [])."""
        if self.get_profile_ready():
            return self.compute_preview()
        return [], [], []

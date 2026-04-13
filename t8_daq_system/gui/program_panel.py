"""
program_panel.py
PURPOSE: Unified Program Mode UI for the block-based editor.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from ..control.program_block import VoltageRampBlock, StableHoldBlock, TempRampBlock
from ..control.program_executor import ProgramExecutor


def _k_to_disp(temp_k, unit):
    """Convert Kelvin to display value and return (value, unit_str)."""
    if unit == 'C':
        return temp_k - 273.15, '\u00b0C'
    return temp_k, 'K'


def _disp_to_k(value, unit):
    """Convert display value back to Kelvin."""
    if unit == 'C':
        return value + 273.15
    return value


class BlockEditDialog(tk.Toplevel):
    def __init__(self, parent, block, tc_names=None, entry_mode='Rate',
                 start_temp_k=293.15, display_unit='K'):
        super().__init__(parent)
        self.block = block
        self.result = None
        self._tc_names = list(tc_names) if tc_names else ["TC_1"]
        # Use block's own mode if it's a temp ramp, otherwise fall back to panel default
        self._entry_mode = getattr(block, 'entry_mode', entry_mode)
        self._start_temp_k = start_temp_k  # chain temp at start of this block
        self._unit = display_unit           # 'C' or 'K'
        self.title(f"Edit {block.block_type.replace('_', ' ').title()}")
        self.geometry("370x320")
        self.grab_set()
        self.transient(parent)
        self._build_ui()

        # Center dialog
        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self._vars = {}
        _, unit_str = _k_to_disp(0, self._unit)

        if self.block.block_type == "voltage_ramp":
            self._add_entry(main_frame, "Start Voltage (V):", "start_voltage", self.block.start_voltage)
            self._add_entry(main_frame, "End Voltage (V):", "end_voltage", self.block.end_voltage)
            self._add_entry(main_frame, "Duration (s):", "duration_sec", self.block.duration_sec)
            self._add_check(main_frame, "PID Active (Runaway monitor):", "pid_active", self.block.pid_active)

        elif self.block.block_type == "stable_hold":
            disp_val, _ = _k_to_disp(self.block.target_temp_k, self._unit)
            self._add_entry(main_frame, f"Target Temp ({unit_str}):", "target_temp_k",
                            round(disp_val, 2))
            self._add_entry(main_frame, f"Tolerance ({unit_str}):", "tolerance_k",
                            self.block.tolerance_k)
            self._add_entry(main_frame, "Hold Duration (s):", "hold_duration_sec",
                            self.block.hold_duration_sec)

        elif self.block.block_type == "temp_ramp":
            self._add_mode_selector(main_frame, "Input Mode:", "entry_mode", self._entry_mode)
            
            self.dynamic_container = ttk.Frame(main_frame)
            self.dynamic_container.pack(fill=tk.X)
            
            disp_end, _ = _k_to_disp(self.block.end_temp_k, self._unit)
            self._add_entry(main_frame, f"Target Temp ({unit_str}):", "_end_temp_disp",
                            round(disp_end, 2))
            self._add_tc_dropdown(main_frame, "TC Name:", "tc_name", self.block.tc_name)
            
            self._update_temp_ramp_fields()

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(20, 0))

        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side=tk.RIGHT, padx=5)

    def _add_mode_selector(self, parent, label, key, initial_val):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=5)
        ttk.Label(frame, text=label, width=22).pack(side=tk.LEFT)
        var = tk.StringVar(value=initial_val)
        cb = ttk.Combobox(frame, textvariable=var, values=["Rate", "TimeTarget"], state="readonly")
        cb.pack(side=tk.LEFT, fill=tk.X, expand=True)
        cb.bind("<<ComboboxSelected>>", lambda e: self._update_temp_ramp_fields())
        self._vars[key] = var

    def _update_temp_ramp_fields(self):
        for w in self.dynamic_container.winfo_children():
            w.destroy()
        
        mode = self._vars["entry_mode"].get()
        if mode == "Rate":
            self._add_entry(self.dynamic_container, "Rate (K/min):", "rate_k_per_min", self.block.rate_k_per_min)
        else:
            # Duration hint
            delta = abs(self.block.end_temp_k - self._start_temp_k)
            rate = max(abs(self.block.rate_k_per_min), 0.01)
            hint_min = getattr(self.block, 'duration_min', 0.0)
            if hint_min <= 0:
                hint_min = round(delta / rate, 2) if delta > 0 else 10.0
            self._add_entry(self.dynamic_container, "Duration (min):", "_duration_min", hint_min)

    def _add_entry(self, parent, label, key, initial_val):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=5)
        ttk.Label(frame, text=label, width=22).pack(side=tk.LEFT)
        var = tk.StringVar(value=str(initial_val))
        ttk.Entry(frame, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._vars[key] = var

    def _add_tc_dropdown(self, parent, label, key, initial_val):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=5)
        ttk.Label(frame, text=label, width=22).pack(side=tk.LEFT)
        var = tk.StringVar(value=str(initial_val))
        cb = ttk.Combobox(frame, textvariable=var, values=self._tc_names, state="readonly")
        cb.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._vars[key] = var

    def _add_check(self, parent, label, key, initial_val):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=5)
        var = tk.BooleanVar(value=initial_val)
        ttk.Checkbutton(frame, text=label, variable=var).pack(side=tk.LEFT)
        self._vars[key] = var

    def _on_ok(self):
        try:
            if self.block.block_type == "voltage_ramp":
                self.block.start_voltage = float(self._vars["start_voltage"].get())
                self.block.end_voltage   = float(self._vars["end_voltage"].get())
                self.block.duration_sec  = float(self._vars["duration_sec"].get())
                self.block.pid_active    = bool(self._vars["pid_active"].get())

            elif self.block.block_type == "stable_hold":
                disp_val = float(self._vars["target_temp_k"].get())
                self.block.target_temp_k   = _disp_to_k(disp_val, self._unit)
                self.block.tolerance_k     = float(self._vars["tolerance_k"].get())
                self.block.hold_duration_sec = float(self._vars["hold_duration_sec"].get())

            elif self.block.block_type == "temp_ramp":
                self.block.tc_name = self._vars["tc_name"].get()
                end_disp = float(self._vars["_end_temp_disp"].get())
                self.block.end_temp_k = _disp_to_k(end_disp, self._unit)

                mode = self._vars["entry_mode"].get()
                self.block.entry_mode = mode

                if mode == 'TimeTarget':
                    dur_min = float(self._vars["_duration_min"].get())
                    if dur_min <= 0:
                        raise ValueError("Duration must be positive")
                    self.block.duration_min = dur_min
                    delta_k = self.block.end_temp_k - self._start_temp_k
                    self.block.rate_k_per_min = delta_k / dur_min
                else:
                    self.block.rate_k_per_min = float(self._vars["rate_k_per_min"].get())
                    # Optionally compute duration_min for consistency
                    delta_k = abs(self.block.end_temp_k - self._start_temp_k)
                    rate = abs(self.block.rate_k_per_min)
                    self.block.duration_min = delta_k / rate if rate > 0 else 0.0

            self.result = self.block
            self.destroy()
        except ValueError as e:
            messagebox.showerror("Error", f"Please enter valid values.\n{e}")


class ProgramPanel:
    def __init__(self, parent_frame, preview_plot=None, get_initial_state_fn=None,
                 on_program_change=None, tc_names=None, get_unit_fn=None,
                 get_tc_temp_k_fn=None):
        self.parent = parent_frame
        self.preview_plot = preview_plot
        self.get_initial_state_fn = get_initial_state_fn
        # get_tc_temp_k_fn(tc_name) → current temperature in Kelvin from live DAQ
        self._get_tc_temp_k = get_tc_temp_k_fn
        self._on_change = on_program_change
        self._tc_names = list(tc_names) if tc_names else ["TC_1"]
        self._get_unit = get_unit_fn or (lambda: 'K')
        self._blocks = []

        self._build_gui()

    def _build_gui(self):
        main_frame = ttk.Frame(self.parent, padding=4)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Toolbar row 1: block controls
        toolbar = ttk.Frame(main_frame)
        toolbar.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(toolbar, text="Program Blocks", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=(0, 8))

        self._add_type_var = tk.StringVar(value="Stable Hold")
        add_cb = ttk.Combobox(toolbar, textvariable=self._add_type_var,
                              values=["Linear Voltage Ramp", "Stable Hold", "Temp Ramp"], state="readonly", width=12)
        add_cb.pack(side=tk.LEFT, padx=2)

        ttk.Button(toolbar, text="Add Block", command=self._add_block).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Preview", command=self._on_preview).pack(side=tk.RIGHT, padx=2)

        # Block list frame (scrollable)
        list_container = ttk.Frame(main_frame)
        list_container.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(list_container, highlightthickness=0, height=160)
        self._scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self._canvas.yview)
        self._scrollable_frame = ttk.Frame(self._canvas)

        self._scrollable_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )

        self._canvas.create_window((0, 0), window=self._scrollable_frame, anchor="nw")
        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        self._canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")

        # Status bar: PID-ready indicator + live TC reading
        status_bar = ttk.Frame(main_frame)
        status_bar.pack(fill=tk.X, pady=(4, 0))

        self._pid_status_label = ttk.Label(
            status_bar, text="PID: Not Ready", foreground='red',
            font=('Arial', 9, 'bold')
        )
        self._pid_status_label.pack(side=tk.LEFT, padx=(0, 12))

        self._tc_live_label = ttk.Label(
            status_bar, text="", foreground='gray', font=('Arial', 9)
        )
        self._tc_live_label.pack(side=tk.LEFT)

        self._refresh_list()
        self._update_pid_status()

    def _chain_start_temp_k(self, up_to_idx):
        """Return the start temperature (K) at block up_to_idx based on prior blocks."""
        if self.get_initial_state_fn:
            t = self.get_initial_state_fn()[0] or 293.15
        else:
            t = 293.15
        for block in self._blocks[:up_to_idx]:
            if block.block_type == "temp_ramp":
                t = block.end_temp_k
            elif block.block_type == "stable_hold":
                t = block.target_temp_k
        return t

    def _add_block(self):
        btype = self._add_type_var.get()
        if btype == "Linear Voltage Ramp":
            self._blocks.append(VoltageRampBlock(0.0, 1.0, 60.0))
        elif btype == "Stable Hold":
            self._blocks.append(StableHoldBlock(293.15, 2.0, 60.0))
        else:
            default_tc = self._tc_names[0] if self._tc_names else "TC_1"
            self._blocks.append(TempRampBlock(1.0, 500.0, default_tc))
        self._recompute_all_blocks()
        self._refresh_list()
        self._update_pid_status()
        if self._on_change:
            self._on_change()

    def _delete_block(self, idx):
        del self._blocks[idx]
        self._recompute_all_blocks()
        self._refresh_list()
        self._update_pid_status()
        if self._on_change:
            self._on_change()

    def _edit_block(self, idx):
        unit = self._get_unit()
        start_k = self._chain_start_temp_k(idx)
        dialog = BlockEditDialog(
            self.parent.winfo_toplevel(),
            self._blocks[idx],
            tc_names=self._tc_names,
            start_temp_k=start_k,
            display_unit=unit
        )
        self.parent.wait_window(dialog)
        if dialog.result:
            self._blocks[idx] = dialog.result
            self._recompute_all_blocks()
            self._refresh_list()
            self._update_pid_status()
            if self._on_change:
                self._on_change()

    def _refresh_list(self):
        for widget in self._scrollable_frame.winfo_children():
            widget.destroy()
        for i, block in enumerate(self._blocks):
            self._build_block_row(i, block)
            # After a StableHold that is followed by a TempRamp, show QMS toggle
            if (block.block_type == "stable_hold" and
                    i + 1 < len(self._blocks) and
                    self._blocks[i + 1].block_type == "temp_ramp"):
                self._build_qms_trigger_row(i, block)

    def _build_block_row(self, i, block):
        unit = self._get_unit()
        row = ttk.Frame(self._scrollable_frame, padding=5)
        row.pack(fill=tk.X, expand=True)

        ttk.Label(row, text=f"{i+1}.", width=3).pack(side=tk.LEFT)

        display_name = block.block_type.replace('_', ' ').title()
        ttk.Label(row, text=display_name, width=15).pack(side=tk.LEFT)

        if block.block_type == "voltage_ramp":
            summary = f"{block.start_voltage}V -> {block.end_voltage}V over {block.duration_sec}s"
        elif block.block_type == "stable_hold":
            disp, unit_str = _k_to_disp(block.target_temp_k, unit)
            summary = f"Hold {disp:.1f}{unit_str} (\u00b1{block.tolerance_k}{unit_str}) for {block.hold_duration_sec}s"
        elif block.block_type == "temp_ramp":
            disp_end, unit_str = _k_to_disp(block.end_temp_k, unit)
            if getattr(block, 'entry_mode', 'Rate') == 'TimeTarget':
                summary = f"Ramp {block.duration_min:.1f}min to {disp_end:.1f}{unit_str} (using {block.tc_name})"
            else:
                summary = f"Ramp {block.rate_k_per_min:.2f}K/min to {disp_end:.1f}{unit_str} (using {block.tc_name})"

        ttk.Label(row, text=summary).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        ttk.Button(row, text="Edit", width=6, command=lambda idx=i: self._edit_block(idx)).pack(side=tk.RIGHT, padx=2)
        ttk.Button(row, text="Del", width=6, command=lambda idx=i: self._delete_block(idx)).pack(side=tk.RIGHT, padx=2)

    def _build_qms_trigger_row(self, i, block):
        """Add a QMS trigger toggle row between StableHold and the next TempRamp."""
        row = ttk.Frame(self._scrollable_frame, padding=(0, 1, 5, 1))
        row.pack(fill=tk.X, expand=True)

        # Indent marker
        ttk.Label(row, text="  \u21b3", width=4, foreground='#9b59b6').pack(side=tk.LEFT)

        var = tk.BooleanVar(value=getattr(block, 'qms_trigger', False))

        def _on_toggle(b=block, v=var):
            b.qms_trigger = v.get()
            if self._on_change:
                self._on_change()

        ttk.Checkbutton(
            row,
            text="Pause for QMS trigger before next ramp",
            variable=var,
            command=_on_toggle,
        ).pack(side=tk.LEFT, padx=4)

        # Show indicator if active
        if getattr(block, 'qms_trigger', False):
            ttk.Label(row, text="[QMS \u25b6]", foreground='#9b59b6',
                      font=('Arial', 8, 'bold')).pack(side=tk.LEFT, padx=4)

    def _recompute_all_blocks(self):
        """Re-calculate rates for any 'TimeTarget' blocks in the chain."""
        # Get start temp from live or initial state
        curr_t = 293.15
        if self.get_initial_state_fn:
            curr_t = self.get_initial_state_fn()[0] or 293.15
        
        for block in self._blocks:
            if block.block_type == "temp_ramp":
                if getattr(block, 'entry_mode', 'Rate') == 'TimeTarget':
                    dur = getattr(block, 'duration_min', 10.0)
                    if dur > 0:
                        delta = block.end_temp_k - curr_t
                        block.rate_k_per_min = delta / dur
                curr_t = block.end_temp_k
            elif block.block_type == "stable_hold":
                curr_t = block.target_temp_k
            # voltage_ramp doesn't change temperature chain

    def _on_preview(self):
        if not self.preview_plot:
            return

        start_t = 293.15
        start_v = 0.0
        if self.get_initial_state_fn:
            start_t, start_v = self.get_initial_state_fn()

        # Override start_t with live TC reading from the first block's selected TC
        if self._get_tc_temp_k is not None:
            tc_name = self._tc_names[0] if self._tc_names else "TC_1"
            for block in self._blocks:
                if hasattr(block, 'tc_name'):
                    tc_name = block.tc_name
                    break
            try:
                live_t = self._get_tc_temp_k(tc_name)
                if live_t and live_t > 0:
                    start_t = live_t
            except Exception:
                pass

        executor = ProgramExecutor(None, lambda: 293.15)
        times, voltages, temps_k, boundaries = executor.compute_preview(
            self._blocks, start_temp_k=start_t, start_voltage=start_v
        )

        unit = self._get_unit()
        self.preview_plot.update_unified_preview(times, voltages, temps_k, self._blocks, boundaries,
                                                 display_unit=unit)

    def _update_pid_status(self):
        """Refresh the PID-ready indicator and live TC reading."""
        if not self._blocks:
            self._pid_status_label.config(text="Program: Not Ready — no blocks", foreground='red')
            self._tc_live_label.config(text="")
            return

        # Show live readings for any TC used by temp_ramp blocks (optional)
        tc_names_used = [b.tc_name for b in self._blocks if hasattr(b, 'tc_name')]
        live_parts = []
        if tc_names_used and self._get_tc_temp_k is not None:
            for tc in dict.fromkeys(tc_names_used):
                try:
                    temp_k = self._get_tc_temp_k(tc)
                    unit = self._get_unit()
                    if unit == 'C':
                        disp = f"{temp_k - 273.15:.1f}°C"
                    else:
                        disp = f"{temp_k:.1f} K"
                    live_parts.append(f"{tc}: {disp}")
                except Exception:
                    live_parts.append(f"{tc}: ---")

        block_summary = f"{len(self._blocks)} block{'s' if len(self._blocks) != 1 else ''}"
        self._pid_status_label.config(text=f"Program Ready — {block_summary}", foreground='green')
        self._tc_live_label.config(
            text=("  " + "  |  ".join(live_parts)) if live_parts else ""
        )

    def get_blocks(self):
        return self._blocks

    def load_blocks(self, blocks):
        """Restore a previously saved list of block objects."""
        self._blocks = list(blocks)
        self._refresh_list()
        self._update_pid_status()

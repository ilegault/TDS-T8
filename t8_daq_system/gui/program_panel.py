"""
program_panel.py
PURPOSE: Unified Program Mode UI for the block-based editor.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from ..control.program_block import VoltageRampBlock, StableHoldBlock, TempRampBlock
from ..control.program_executor import ProgramExecutor

class BlockEditDialog(tk.Toplevel):
    def __init__(self, parent, block):
        super().__init__(parent)
        self.block = block
        self.result = None
        self.title(f"Edit {block.block_type.replace('_', ' ').title()}")
        self.geometry("350x300")
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
        
        if self.block.block_type == "voltage_ramp":
            self._add_entry(main_frame, "Start Voltage (V):", "start_voltage", self.block.start_voltage)
            self._add_entry(main_frame, "End Voltage (V):", "end_voltage", self.block.end_voltage)
            self._add_entry(main_frame, "Duration (s):", "duration_sec", self.block.duration_sec)
            self._add_check(main_frame, "PID Active (Runaway monitor):", "pid_active", self.block.pid_active)
            
        elif self.block.block_type == "stable_hold":
            self._add_entry(main_frame, "Target Temp (K):", "target_temp_k", self.block.target_temp_k)
            self._add_entry(main_frame, "Tolerance (K):", "tolerance_k", self.block.tolerance_k)
            self._add_entry(main_frame, "Hold Duration (s):", "hold_duration_sec", self.block.hold_duration_sec)
            
        elif self.block.block_type == "temp_ramp":
            self._add_entry(main_frame, "Rate (K/min):", "rate_k_per_min", self.block.rate_k_per_min)
            self._add_entry(main_frame, "End Temp (K):", "end_temp_k", self.block.end_temp_k)
            self._add_entry(main_frame, "TC Name:", "tc_name", self.block.tc_name)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(20, 0))
        
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="OK", command=self._on_ok).pack(side=tk.RIGHT, padx=5)

    def _add_entry(self, parent, label, key, initial_val):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=5)
        ttk.Label(frame, text=label, width=20).pack(side=tk.LEFT)
        var = tk.StringVar(value=str(initial_val))
        ttk.Entry(frame, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._vars[key] = var

    def _add_check(self, parent, label, key, initial_val):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=5)
        var = tk.BooleanVar(value=initial_val)
        ttk.Checkbutton(frame, text=label, variable=var).pack(side=tk.LEFT)
        self._vars[key] = var

    def _on_ok(self):
        try:
            updates = {}
            for k, var in self._vars.items():
                val = var.get()
                if k == "tc_name":
                    updates[k] = val
                elif k == "pid_active":
                    updates[k] = bool(val)
                else:
                    updates[k] = float(val)
            
            for k, v in updates.items():
                setattr(self.block, k, v)
            
            self.result = self.block
            self.destroy()
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numeric values")

class ProgramPanel:
    def __init__(self, parent_frame, preview_plot=None, get_initial_state_fn=None, on_program_change=None):
        self.parent = parent_frame
        self.preview_plot = preview_plot
        self.get_initial_state_fn = get_initial_state_fn
        self._on_change = on_program_change
        self._blocks = []
        
        # Block 1 is always VoltageRampBlock
        self._blocks.append(VoltageRampBlock(0.0, 0.3, 300.0, pid_active=True))
        
        self._build_gui()

    def _build_gui(self):
        main_frame = ttk.Frame(self.parent, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Toolbar
        toolbar = ttk.Frame(main_frame)
        toolbar.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(toolbar, text="Program Blocks", font=('Arial', 12, 'bold')).pack(side=tk.LEFT)
        
        # Add Block dropdown
        self._add_type_var = tk.StringVar(value="Stable Hold")
        add_cb = ttk.Combobox(toolbar, textvariable=self._add_type_var, 
                              values=["Stable Hold", "Temp Ramp"], state="readonly", width=12)
        add_cb.pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(toolbar, text="Add Block", command=self._add_block).pack(side=tk.RIGHT, padx=5)
        ttk.Button(toolbar, text="Preview", command=self._on_preview).pack(side=tk.RIGHT, padx=5)

        # Block list frame (scrollable)
        list_container = ttk.Frame(main_frame)
        list_container.pack(fill=tk.BOTH, expand=True)
        
        self._canvas = tk.Canvas(list_container, highlightthickness=0)
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

        self._refresh_list()

    def _add_block(self):
        btype = self._add_type_var.get()
        if btype == "Stable Hold":
            self._blocks.append(StableHoldBlock(293.15, 2.0, 60.0))
        else:
            self._blocks.append(TempRampBlock(1.0, 500.0, "TC_1"))
        self._refresh_list()
        if self._on_change: self._on_change()

    def _delete_block(self, idx):
        if idx == 0:
            messagebox.showwarning("Warning", "Block 1 (Voltage Ramp) cannot be deleted")
            return
        del self._blocks[idx]
        self._refresh_list()
        if self._on_change: self._on_change()

    def _edit_block(self, idx):
        dialog = BlockEditDialog(self.parent.winfo_toplevel(), self._blocks[idx])
        self.parent.wait_window(dialog)
        if dialog.result:
            self._blocks[idx] = dialog.result
            self._refresh_list()
            if self._on_change: self._on_change()

    def _refresh_list(self):
        for widget in self._scrollable_frame.winfo_children():
            widget.destroy()
            
        for i, block in enumerate(self._blocks):
            self._build_block_row(i, block)

    def _build_block_row(self, i, block):
        row = ttk.Frame(self._scrollable_frame, padding=5)
        row.pack(fill=tk.X, expand=True)
        
        ttk.Label(row, text=f"{i+1}.", width=3).pack(side=tk.LEFT)
        
        display_name = block.block_type.replace('_', ' ').title()
        ttk.Label(row, text=display_name, width=15).pack(side=tk.LEFT)
        
        # Summary text
        if block.block_type == "voltage_ramp":
            summary = f"{block.start_voltage}V -> {block.end_voltage}V over {block.duration_sec}s"
        elif block.block_type == "stable_hold":
            summary = f"Hold {block.target_temp_k}K (±{block.tolerance_k}K) for {block.hold_duration_sec}s"
        elif block.block_type == "temp_ramp":
            summary = f"Ramp {block.rate_k_per_min}K/min to {block.end_temp_k}K (using {block.tc_name})"
            
        ttk.Label(row, text=summary).pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        
        ttk.Button(row, text="Edit", width=6, command=lambda idx=i: self._edit_block(idx)).pack(side=tk.RIGHT, padx=2)
        if i > 0:
            ttk.Button(row, text="Del", width=6, command=lambda idx=i: self._delete_block(idx)).pack(side=tk.RIGHT, padx=2)

    def _on_preview(self):
        if not self.preview_plot:
            return
            
        start_t = 293.15
        start_v = 0.0
        if self.get_initial_state_fn:
            start_t, start_v = self.get_initial_state_fn()
            
        # We need a temp executor instance to use the method, or just make it static.
        # For now I'll just instantiate a dummy one or use the class method if I change it.
        # Let's just use it through a temporary instance.
        executor = ProgramExecutor(None, lambda: 293.15)
        times, voltages, temps_k, boundaries = executor.compute_preview(
            self._blocks, start_temp_k=start_t, start_voltage=start_v
        )
        
        self.preview_plot.update_unified_preview(times, voltages, temps_k, self._blocks, boundaries)

    def get_blocks(self):
        return self._blocks

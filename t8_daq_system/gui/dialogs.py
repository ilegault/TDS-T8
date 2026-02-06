"""
dialogs.py
PURPOSE: Custom dialog windows for the T8 DAQ System
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
from datetime import datetime

from t8_daq_system.data.data_logger import DataLogger


class LoggingDialog(tk.Toplevel):
    """Dialog for configuring data logging with custom filename and notes."""

    def __init__(self, parent, default_prefix="data_log"):
        super().__init__(parent)
        self.title("Start Logging")
        self.transient(parent)
        self.grab_set()

        self.result = None  # Will contain (custom_name, notes) or None if cancelled

        # Configure dialog size
        self.geometry("400x300")
        self.resizable(False, False)

        self._build_ui(default_prefix)

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        # Focus on name entry
        self.name_entry.focus_set()

        # Bind Enter key
        self.bind('<Return>', lambda e: self._on_ok())
        self.bind('<Escape>', lambda e: self._on_cancel())

    def _build_ui(self, default_prefix):
        """Build the dialog UI."""
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Run Name
        ttk.Label(main_frame, text="Run Name (optional):").pack(anchor='w', pady=(0, 5))

        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(main_frame, textvariable=self.name_var, width=40)
        self.name_entry.pack(fill=tk.X, pady=(0, 5))

        # Preview of filename
        preview_frame = ttk.Frame(main_frame)
        preview_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(preview_frame, text="Preview:", font=('Arial', 8)).pack(anchor='w')
        self.preview_var = tk.StringVar()
        self._update_preview()
        self.name_var.trace('w', lambda *args: self._update_preview())

        self.preview_label = ttk.Label(preview_frame, textvariable=self.preview_var,
                                       font=('Arial', 8, 'italic'), foreground='gray')
        self.preview_label.pack(anchor='w')

        # Notes
        ttk.Label(main_frame, text="Notes (optional):").pack(anchor='w', pady=(10, 5))

        self.notes_text = tk.Text(main_frame, height=5, width=40)
        self.notes_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(button_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Start Logging", command=self._on_ok).pack(side=tk.RIGHT)

    def _update_preview(self):
        """Update the filename preview."""
        name = self.name_var.get().strip()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if name:
            safe_name = "".join(c for c in name if c.isalnum() or c in "._- ")
            safe_name = safe_name.strip().replace(" ", "_")
            filename = f"data_log_{safe_name}_{timestamp}.csv"
        else:
            filename = f"data_log_{timestamp}.csv"

        self.preview_var.set(filename)

    def _on_ok(self):
        """Handle OK button click."""
        custom_name = self.name_var.get().strip() or None
        notes = self.notes_text.get("1.0", tk.END).strip() or None
        self.result = (custom_name, notes)
        self.destroy()

    def _on_cancel(self):
        """Handle Cancel button click."""
        self.result = None
        self.destroy()


class LoadCSVDialog(tk.Toplevel):
    """Dialog for loading and viewing historical CSV data."""

    def __init__(self, parent, log_folder):
        super().__init__(parent)
        self.title("Load Historical Data")
        self.transient(parent)
        self.grab_set()

        self.log_folder = log_folder
        self.result = None  # Will contain filepath or None if cancelled

        # Configure dialog size
        self.geometry("600x450")
        self.minsize(500, 350)

        self._build_ui()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        # Load initial file list
        self._refresh_file_list()

        # Bind keys
        self.bind('<Escape>', lambda e: self._on_cancel())
        self.bind('<Return>', lambda e: self._on_load())

    def _build_ui(self):
        """Build the dialog UI."""
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top buttons
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(top_frame, text="Refresh", command=self._refresh_file_list).pack(side=tk.LEFT)
        ttk.Button(top_frame, text="Browse...", command=self._on_browse).pack(side=tk.LEFT, padx=5)

        # File list with scrollbar
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        # Treeview for file list
        columns = ('filename', 'date', 'size', 'sensors')
        self.file_tree = ttk.Treeview(list_frame, columns=columns, show='headings',
                                       selectmode='browse')

        self.file_tree.heading('filename', text='Filename')
        self.file_tree.heading('date', text='Date')
        self.file_tree.heading('size', text='Size')
        self.file_tree.heading('sensors', text='Sensors')

        self.file_tree.column('filename', width=200)
        self.file_tree.column('date', width=150)
        self.file_tree.column('size', width=70)
        self.file_tree.column('sensors', width=150)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=scrollbar.set)

        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_tree.bind('<<TreeviewSelect>>', self._on_select)
        self.file_tree.bind('<Double-1>', lambda e: self._on_load())

        # Info panel
        info_frame = ttk.LabelFrame(main_frame, text="File Info", padding=5)
        info_frame.pack(fill=tk.X, pady=(10, 0))

        self.info_text = tk.Text(info_frame, height=5, state='disabled', wrap='word')
        self.info_text.pack(fill=tk.X)

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(button_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT, padx=5)
        self.load_btn = ttk.Button(button_frame, text="Load", command=self._on_load, state='disabled')
        self.load_btn.pack(side=tk.RIGHT)

    def _refresh_file_list(self):
        """Refresh the list of CSV files."""
        # Clear existing items
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)

        # Get files
        if not os.path.exists(self.log_folder):
            return

        files = []
        for f in os.listdir(self.log_folder):
            if f.endswith('.csv'):
                filepath = os.path.join(self.log_folder, f)
                files.append(filepath)

        # Sort by modification time, newest first
        files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        # Add to treeview
        for filepath in files:
            try:
                info = DataLogger.get_csv_info(filepath)
                date_str = info.get('start_time', info.get('modified', 'Unknown'))
                if date_str and len(date_str) > 19:
                    date_str = date_str[:19]  # Truncate to remove microseconds
                size_str = f"{info.get('size_kb', 0):.1f} KB"
                sensors = info.get('sensors', [])
                sensor_str = ', '.join(sensors[:3])
                if len(sensors) > 3:
                    sensor_str += f" (+{len(sensors)-3})"

                self.file_tree.insert('', 'end', values=(
                    info['filename'],
                    date_str,
                    size_str,
                    sensor_str
                ), tags=(filepath,))
            except Exception as e:
                print(f"Error reading {filepath}: {e}")

    def _on_browse(self):
        """Handle Browse button click."""
        filepath = filedialog.askopenfilename(
            title="Open CSV File",
            initialdir=self.log_folder,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filepath:
            self.result = filepath
            self.destroy()

    def _on_select(self, event):
        """Handle file selection."""
        selection = self.file_tree.selection()
        if not selection:
            self.load_btn.config(state='disabled')
            return

        self.load_btn.config(state='normal')

        # Get filepath from tags
        item = selection[0]
        tags = self.file_tree.item(item, 'tags')
        if not tags:
            return

        filepath = tags[0]

        # Show file info
        try:
            info = DataLogger.get_csv_info(filepath)
            info_text = f"File: {info['filename']}\n"
            info_text += f"Rows: {info.get('row_count', 'Unknown')}\n"
            info_text += f"Sensors: {', '.join(info.get('sensors', []))}\n"

            settings = info.get('settings', {})
            if settings.get('notes'):
                info_text += f"Notes: {settings['notes']}\n"

            self.info_text.config(state='normal')
            self.info_text.delete("1.0", tk.END)
            self.info_text.insert("1.0", info_text)
            self.info_text.config(state='disabled')
        except Exception as e:
            self.info_text.config(state='normal')
            self.info_text.delete("1.0", tk.END)
            self.info_text.insert("1.0", f"Error reading file: {e}")
            self.info_text.config(state='disabled')

    def _on_load(self):
        """Handle Load button click."""
        selection = self.file_tree.selection()
        if not selection:
            return

        item = selection[0]
        tags = self.file_tree.item(item, 'tags')
        if tags:
            self.result = tags[0]
            self.destroy()

    def _on_cancel(self):
        """Handle Cancel button click."""
        self.result = None
        self.destroy()


class AxisScaleDialog(tk.Toplevel):
    """Dialog for configuring axis scale settings."""

    def __init__(self, parent, current_temp_range, use_absolute=False):
        super().__init__(parent)
        self.title("Configure Axis Scales")
        self.transient(parent)
        self.grab_set()

        self.result = None

        # Configure dialog size
        self.geometry("350x180")
        self.resizable(False, False)

        self._build_ui(current_temp_range, use_absolute)

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        # Bind keys
        self.bind('<Escape>', lambda e: self._on_cancel())
        self.bind('<Return>', lambda e: self._on_ok())

    def _build_ui(self, temp_range, use_absolute):
        """Build the dialog UI."""
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Use absolute scales checkbox
        self.use_absolute_var = tk.BooleanVar(value=use_absolute)
        ttk.Checkbutton(main_frame, text="Use absolute (fixed) scales",
                       variable=self.use_absolute_var,
                       command=self._on_toggle_absolute).pack(anchor='w', pady=(0, 10))

        # Temperature range
        temp_frame = ttk.LabelFrame(main_frame, text="Temperature Range", padding=5)
        temp_frame.pack(fill=tk.X, pady=5)

        ttk.Label(temp_frame, text="Min:").grid(row=0, column=0, padx=5)
        self.temp_min_var = tk.StringVar(value=str(temp_range[0] if temp_range else 0))
        self.temp_min_entry = ttk.Entry(temp_frame, textvariable=self.temp_min_var, width=10)
        self.temp_min_entry.grid(row=0, column=1, padx=5)

        ttk.Label(temp_frame, text="Max:").grid(row=0, column=2, padx=5)
        self.temp_max_var = tk.StringVar(value=str(temp_range[1] if temp_range else 300))
        self.temp_max_entry = ttk.Entry(temp_frame, textvariable=self.temp_max_var, width=10)
        self.temp_max_entry.grid(row=0, column=3, padx=5)

        # Update entry states
        self._on_toggle_absolute()

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))

        ttk.Button(button_frame, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Apply", command=self._on_ok).pack(side=tk.RIGHT)

    def _on_toggle_absolute(self):
        """Handle toggle of absolute scales checkbox."""
        state = 'normal' if self.use_absolute_var.get() else 'disabled'
        self.temp_min_entry.config(state=state)
        self.temp_max_entry.config(state=state)

    def _on_ok(self):
        """Handle OK button click."""
        try:
            temp_range = (
                float(self.temp_min_var.get()),
                float(self.temp_max_var.get())
            )
            self.result = {
                'use_absolute': self.use_absolute_var.get(),
                'temp_range': temp_range
            }
            self.destroy()
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid numeric values.")

    def _on_cancel(self):
        """Handle Cancel button click."""
        self.result = None
        self.destroy()

"""
live_plot.py
PURPOSE: Display real-time updating graphs of sensor data
KEY CONCEPT: Use matplotlib's FigureCanvasTkAgg to embed plots in tkinter
"""

import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates


class LivePlot:
    def __init__(self, parent_frame, data_buffer):
        """
        Initialize the live plot.

        Args:
            parent_frame: tkinter frame to put the plot in
            data_buffer: DataBuffer object to get data from
        """
        self.data_buffer = data_buffer
        self.parent = parent_frame

        # Create matplotlib figure
        self.fig = Figure(figsize=(10, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)

        # Embed in tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Store line objects for each sensor (for efficient updating)
        self.lines = {}

        # Configure the plot appearance
        self.ax.set_xlabel('Time')
        self.ax.set_ylabel('Value')
        self.ax.grid(True, alpha=0.3)

        # Format x-axis to show time nicely
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))

        # Color cycle for different sensors
        self.colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
                       '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']

    def update(self, sensor_names):
        """
        Refresh the plot with current data.
        Call this periodically (e.g., every 500ms).

        Args:
            sensor_names: List of sensor names to plot
        """
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('Time')
        self.ax.set_ylabel('Value')

        for i, name in enumerate(sensor_names):
            timestamps, values = self.data_buffer.get_sensor_data(name)
            if timestamps and values:
                # Filter out None values
                valid_data = [(t, v) for t, v in zip(timestamps, values) if v is not None]
                if valid_data:
                    times, vals = zip(*valid_data)
                    color = self.colors[i % len(self.colors)]
                    self.ax.plot(times, vals, label=name, linewidth=2, color=color)

        self.ax.legend(loc='upper left')
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.fig.autofmt_xdate()  # Angle the time labels

        self.canvas.draw()

    def clear(self):
        """Clear the plot."""
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('Time')
        self.ax.set_ylabel('Value')
        self.canvas.draw()

    def set_y_label(self, label):
        """Set the y-axis label."""
        self.ax.set_ylabel(label)
        self.canvas.draw()

    def set_title(self, title):
        """Set the plot title."""
        self.ax.set_title(title)
        self.canvas.draw()

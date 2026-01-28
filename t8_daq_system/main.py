"""
main.py
PURPOSE: Application entry point for the T8 DAQ System
"""

import sys
import os

# Add the package directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.main_window import MainWindow


def main():
    """Launch the T8 DAQ System application."""
    app = MainWindow()
    app.run()


if __name__ == "__main__":
    main()

"""
main.py
PURPOSE: Application entry point for the T8 DAQ System
"""

import sys
import os

# Add the project root directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t8_daq_system.gui.main_window import MainWindow


def main():
    """Launch the T8 DAQ System application."""
    # Load sensor configuration if it exists
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config", "sensor_config.json")
    
    app = MainWindow(config_path=config_path if os.path.exists(config_path) else None)
    app.run()


if __name__ == "__main__":
    main()

"""
main.py
PURPOSE: Application entry point for the T8 DAQ System

Integrates LabJack T8 DAQ with Keysight N5761A power supply for
specimen heating control with safety interlocks.
"""

import sys
import os
import argparse

# Add the project root directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t8_daq_system.gui.main_window import MainWindow


def main():
    """Launch the T8 DAQ System application."""
    parser = argparse.ArgumentParser(
        description='T8 DAQ System with Power Supply Control'
    )
    parser.add_argument(
        '-c', '--config',
        help='Path to configuration file (default: config/sensor_config.json)',
        default=None
    )
    args = parser.parse_args()

    # Determine config path
    if args.config:
        config_path = args.config
    else:
        # Default to config/sensor_config.json relative to this file
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, 'config', 'sensor_config.json')

    # Check if config exists, warn if not
    if not os.path.exists(config_path):
        print(f"Note: Config file not found at {config_path}")
        print("Using default configuration. Create config/sensor_config.json to customize.")
        config_path = None

    app = MainWindow(config_path=config_path)
    app.run()


if __name__ == "__main__":
    main()

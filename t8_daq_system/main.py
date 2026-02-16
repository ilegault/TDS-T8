"""
main.py
PURPOSE: Application entry point for the T8 DAQ System
"""

import sys
import os
import shutil

# ============================================================================
# FROZEN EXE OPTIMIZATIONS - MUST BE BEFORE OTHER IMPORTS
# ============================================================================
if getattr(sys, 'frozen', False):
    print("[FROZEN MODE] Applying performance optimizations...")

    # 1. MATPLOTLIB: Disable font scanning (biggest bottleneck)
    os.environ['MPLBACKEND'] = 'TkAgg'
    if hasattr(sys, '_MEIPASS'):
        mpl_data_dir = os.path.join(sys._MEIPASS, 'mpl-data')
        os.makedirs(mpl_data_dir, exist_ok=True)
        os.environ['MPLCONFIGDIR'] = mpl_data_dir

    import matplotlib
    matplotlib.use('TkAgg', force=True)

    # Force matplotlib to skip font manager scanning
    import matplotlib.font_manager as fm
    try:
        fm._load_fontmanager = lambda try_read_cache=True: fm.FontManager()
    except:
        pass

    print("[FROZEN MODE] Matplotlib optimization complete")

# 2. PYVISA: Disable slow network discovery
os.environ['PYVISA_PY_SKIP_TCPIP'] = '1'
os.environ['PYVISA_PY_SKIP_HISLIP'] = '1'

# ============================================================================
# Continue with existing code below
# ============================================================================

def get_base_dir():
    """Get the base directory for the application (where the EXE or Project Root is)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_bundle_dir():
    """Get the directory where bundled files are extracted (PyInstaller _MEIPASS)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def setup_external_config(base_dir):
    """Copy bundled config and profiles to the external folder if they don't exist."""
    external_config = os.path.join(base_dir, "config")
    bundle_config = os.path.join(get_bundle_dir(), "config")
    
    # If the external config folder doesn't exist, copy the entire bundled config
    if not os.path.exists(external_config) and os.path.exists(bundle_config):
        try:
            shutil.copytree(bundle_config, external_config)
        except Exception:
            pass # Silently fail if we can't create it (e.g. permissions)

# Add the project root directory to the path for imports
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t8_daq_system.startup_profiler import profiler

profiler.log("About to import MainWindow...")
from t8_daq_system.gui.main_window import MainWindow
profiler.log("MainWindow import complete")

def main():
    """Launch the T8 DAQ System application."""
    profiler.log("Entering main() function")

    base_dir = get_base_dir()
    profiler.log(f"Base directory resolved: {base_dir}")

    # Create the external config folder and copy defaults if missing
    profiler.log("Setting up config directory")
    setup_external_config(base_dir)
    profiler.log("Config directory ready")

    # Ensure logs folder exists in the base directory
    profiler.log("Creating logs directory")
    logs_dir = os.path.join(base_dir, "logs")
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir, exist_ok=True)
    profiler.log("Logs directory ready")

    config_path = os.path.join(base_dir, "config", "sensor_config.json")
    profiler.log(f"Config path: {config_path}")

    profiler.log("Creating MainWindow instance...")
    app = MainWindow(config_path=config_path if os.path.exists(config_path) else None)
    profiler.log("MainWindow instance created")

    # Print profiling summary before GUI loop
    profiler.summary()

    # Also show detailed MainWindow profiler summary
    print("\n" + "="*80)
    print("DETAILED MAINWINDOW PROFILER OUTPUT SHOWN ABOVE")
    print("="*80 + "\n")

    profiler.disable()

    profiler.log("Starting GUI main loop")
    app.run()


if __name__ == "__main__":
    main()

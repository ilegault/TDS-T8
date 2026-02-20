"""
main.py
PURPOSE: Application entry point for the T8 DAQ System
"""

import sys
import os

# ============================================================================
# ENVIRONMENT VARIABLES — MUST BE FIRST, BEFORE ANY OTHER IMPORTS
# These suppress slow pyvisa network discovery and zeroconf scanning on every
# launch regardless of frozen/script mode.  USB is kept enabled for LabJack.
# ============================================================================
os.environ['PYVISA_PY_SKIP_TCPIP'] = '1'
os.environ['PYVISA_PY_SKIP_HISLIP'] = '1'
os.environ['PYVISA_PY_SKIP_USB']  = '0'    # Keep USB so LabJack still works
os.environ['ZEROCONF_DISABLE']    = '1'

# ============================================================================
# FROZEN EXE OPTIMIZATIONS
# ============================================================================
if getattr(sys, 'frozen', False):
    print("[FROZEN MODE] Applying performance optimizations...")

    # Matplotlib: disable font scanning (biggest startup bottleneck)
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
    except Exception:
        pass

    print("[FROZEN MODE] Matplotlib optimization complete")

# ============================================================================
# PATH SETUP
# ============================================================================

def get_base_dir():
    """Get the base directory for the application (where the EXE or project root is)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Add the project root directory to the path for imports (script mode only)
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t8_daq_system.startup_profiler import profiler

profiler.log("About to import MainWindow...")
from t8_daq_system.gui.main_window import MainWindow
profiler.log("MainWindow import complete")

profiler.log("About to import AppSettings...")
from t8_daq_system.settings.app_settings import AppSettings
profiler.log("AppSettings import complete")


def main():
    """Launch the T8 DAQ System application."""
    profiler.log("Entering main() function")

    base_dir = get_base_dir()
    profiler.log(f"Base directory resolved: {base_dir}")

    # Ensure logs folder exists in the base directory
    profiler.log("Creating logs directory")
    logs_dir = os.path.join(base_dir, "logs")
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir, exist_ok=True)
    profiler.log("Logs directory ready")

    # Load persistent settings from Windows Registry (silent defaults on first launch)
    profiler.log("Loading AppSettings from registry...")
    settings = AppSettings()
    settings.load()
    profiler.log("AppSettings loaded")

    profiler.log("Creating MainWindow instance...")
    app = MainWindow(settings=settings)
    profiler.log("MainWindow instance created")

    # Print profiling summary before GUI loop
    profiler.summary()

    print("\n" + "="*80)
    print("DETAILED MAINWINDOW PROFILER OUTPUT SHOWN ABOVE")
    print("="*80 + "\n")

    profiler.disable()

    profiler.log("Starting GUI main loop")
    app.run()


if __name__ == "__main__":
    main()

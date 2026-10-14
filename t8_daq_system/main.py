"""
main.py
PURPOSE: Application entry point for the T8 DAQ System
"""

import sys
import os
import logging
import multiprocessing

logger = logging.getLogger(__name__)

# PyInstaller Windows fix: must be called before any other code when frozen
# Prevents recursive subprocess spawning (numpy/matplotlib internals) that
# causes the instant-close flicker on first launch.
if __name__ == "__main__":
    multiprocessing.freeze_support()

# ============================================================================
# ENVIRONMENT VARIABLES — MUST BE FIRST, BEFORE ANY OTHER IMPORTS
# pyvisa is no longer used; power supply is controlled via analog I/O on the
# LabJack T8 (DAC0/DAC1 for programming, AIN4/AIN5 for monitoring).
# ============================================================================
os.environ['ZEROCONF_DISABLE'] = '1'

# ============================================================================
# FROZEN EXE OPTIMIZATIONS
# ============================================================================
if getattr(sys, 'frozen', False):
    logger.info("Frozen mode: applying performance optimizations")

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
    except Exception as e:
        # Best-effort startup speedup in frozen mode; safe to continue if matplotlib internals changed
        logger.warning("Frozen mode: FontManager override skipped: %s", e)


    logger.info("Frozen mode: matplotlib optimization complete")

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

from t8_daq_system.utils.startup_profiler import profiler

class Logger:
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "w", encoding="utf-8")

    def write(self, message):
        if self.terminal is not None:
            self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        if self.terminal is not None:
            self.terminal.flush()
        self.log.flush()

profiler.log("About to import MainWindow...")
from t8_daq_system.gui.main_window import MainWindow
profiler.log("MainWindow import complete")

profiler.log("About to import AppSettings...")
from t8_daq_system.settings.app_settings import AppSettings
from t8_daq_system.build_info import get_build_id
from t8_daq_system.utils.diagnostic_log import attach_console, new_run_id, start_session
profiler.log("AppSettings import complete")


def main():
    """Launch the T8 DAQ System application."""
    profiler.log("Entering main() function")

    base_dir = get_base_dir()
    profiler.log(f"Base directory resolved: {base_dir}")

    # Ensure logs folder exists — use APPDATA so it works without admin rights
    profiler.log("Creating logs directory")
    if getattr(sys, 'frozen', False):
        appdata = os.environ.get('APPDATA', base_dir)
        logs_dir = os.path.join(appdata, 'T8_DAQ_System', 'logs')
    else:
        logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    profiler.log("Logs directory ready")

    # Initialize terminal logging to log.txt
    log_file = os.path.join(logs_dir, "log.txt")
    sys.stdout = Logger(log_file)
    sys.stderr = sys.stdout

    # Load persistent settings from Windows Registry (silent defaults on first launch)
    profiler.log("Loading AppSettings from registry...")
    settings = AppSettings()
    settings.load()
    profiler.log("AppSettings loaded")

    # One Run ID names this session's Diagnostic log and the CSV metadata (ADR 0008)
    run_id = new_run_id()
    start_session(logs_dir, settings.diagnostic_log_keep, build_id=get_build_id(),
                  run_id=run_id, adapter="hardware", settings=settings)
    attach_console(settings.show_console)

    profiler.log("Creating MainWindow instance...")
    app = MainWindow(settings=settings, run_id=run_id)
    profiler.log("MainWindow instance created")

    # Print profiling summary before GUI loop
    profiler.summary()

    logger.info("Detailed MainWindow profiler output shown above")

    profiler.disable()

    profiler.log("Starting GUI main loop")
    app.run()


if __name__ == "__main__":
    main()

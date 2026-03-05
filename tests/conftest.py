"""
Shared pytest fixtures and configuration for TDS-T8 unit tests.

This conftest.py provides automatic mocking of hardware dependencies
(labjack, serial, tkinter, matplotlib) so that tests can run in any
environment -- even without the physical hardware or a display.

Usage:
    Simply run ``pytest`` from the project root.  The mocks below are
    applied **before** any test module is collected, so import-time
    side-effects in the production code are neutralised.
"""

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock heavy / hardware dependencies that are unavailable in CI or
# headless environments.  These must be inserted into sys.modules
# BEFORE the test collector tries to import test files.
# ---------------------------------------------------------------------------

# ---- winreg (Windows registry — unavailable on Linux/macOS) ----
if "winreg" not in sys.modules:
    sys.modules["winreg"] = MagicMock()

# ---- LabJack LJM ----
_mock_ljm = MagicMock()
_mock_ljm.LJMError = type("LJMError", (Exception,), {})
_mock_labjack = MagicMock()
_mock_labjack.ljm = _mock_ljm
sys.modules.setdefault("labjack", _mock_labjack)
sys.modules.setdefault("labjack.ljm", _mock_ljm)

# ---- PySerial (used by xgs600_controller) ----
_mock_serial = MagicMock()
_mock_serial.Serial = MagicMock
_mock_serial.SerialException = type("SerialException", (Exception,), {})
sys.modules.setdefault("serial", _mock_serial)
sys.modules.setdefault("serial.tools", MagicMock())
sys.modules.setdefault("serial.tools.list_ports", MagicMock())

# ---- tkinter (GUI framework) ----
if "tkinter" not in sys.modules:
    _mock_tk = MagicMock()
    _mock_tk.__path__ = []
    sys.modules["tkinter"] = _mock_tk
    sys.modules["tkinter.ttk"] = MagicMock()
    sys.modules["tkinter.messagebox"] = MagicMock()
    sys.modules["tkinter.filedialog"] = MagicMock()
    sys.modules["tkinter.font"] = MagicMock()
    sys.modules["tkinter.commondialog"] = MagicMock()
    sys.modules["tkinter.simpledialog"] = MagicMock()

# ---- matplotlib (plotting library) ----
if "matplotlib" not in sys.modules:
    _mock_mpl = MagicMock()
    _mock_mpl.__path__ = []
    sys.modules["matplotlib"] = _mock_mpl
    sys.modules["matplotlib.pyplot"] = MagicMock()
    sys.modules["matplotlib.figure"] = MagicMock()
    sys.modules["matplotlib.backends"] = MagicMock()
    sys.modules["matplotlib.backends.backend_tkagg"] = MagicMock()
    sys.modules["matplotlib.dates"] = MagicMock()

"""
setup_firewall.py
PURPOSE: Add Windows Firewall exceptions for T8_DAQ_System.exe (Python alternative
         to add_firewall_rule.bat for machines that block .bat execution).

HOW TO USE
----------
Run this script ONCE as Administrator after placing the distribution folder on
the target machine.  If you are not already running as Administrator, a UAC
prompt will appear automatically asking for elevation.

    python setup_firewall.py

After it runs successfully Windows will no longer show a firewall prompt for
T8_DAQ_System.exe regardless of which ethernet cable is plugged in.

REQUIREMENTS
------------
Python 3 on Windows.  T8_DAQ_System.exe must be in the same folder as this
script.
"""

import ctypes
import os
import subprocess
import sys


# ---------------------------------------------------------------------------
# Admin / elevation helpers
# ---------------------------------------------------------------------------

def _is_admin():
    """Return True if the current process has Administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin():
    """Re-launch this script with UAC elevation and exit the current process."""
    script = os.path.abspath(__file__)
    # ShellExecuteW with "runas" triggers the Windows UAC prompt
    ret = ctypes.windll.shell32.ShellExecuteW(
        None,           # parent window handle
        "runas",        # verb — request elevation
        sys.executable, # program to run (python.exe)
        f'"{script}"',  # parameters (this script)
        None,           # working directory (inherit)
        1,              # SW_SHOWNORMAL
    )
    # ShellExecuteW returns > 32 on success
    if ret <= 32:
        print(f"ERROR: Could not request elevation (ShellExecuteW returned {ret}).")
        print("Try right-clicking a Command Prompt and choosing 'Run as administrator',")
        print("then run:  python setup_firewall.py")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Firewall rule helpers
# ---------------------------------------------------------------------------

def _add_rule(name, direction, exe_path, description):
    """
    Add a single Windows Firewall rule via netsh.

    Args:
        name:        Rule name string
        direction:   "in" or "out"
        exe_path:    Absolute path to the executable
        description: Rule description string

    Returns:
        True on success, False on failure
    """
    cmd = [
        "netsh", "advfirewall", "firewall", "add", "rule",
        f"name={name}",
        f"dir={direction}",
        "action=allow",
        f"program={exe_path}",
        "enable=yes",
        "profile=any",
        f"description={description}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print()
    print("T8 DAQ System — Windows Firewall Rule Installer (Python)")
    print("=========================================================")
    print()

    # --- Elevation check ---------------------------------------------------
    if not _is_admin():
        print("Not running as Administrator — requesting elevation via UAC...")
        print()
        _relaunch_as_admin()
        return  # unreachable; _relaunch_as_admin exits

    # --- Locate the executable ---------------------------------------------
    script_dir = os.path.dirname(os.path.abspath(__file__))
    exe_path = os.path.join(script_dir, "T8_DAQ_System.exe")

    if not os.path.isfile(exe_path):
        print(f"ERROR: T8_DAQ_System.exe not found at:")
        print(f"  {exe_path}")
        print()
        print("Make sure this script is in the same folder as T8_DAQ_System.exe")
        print()
        input("Press Enter to exit...")
        sys.exit(1)

    # --- Add inbound rule --------------------------------------------------
    print("Adding inbound firewall rule...")
    if _add_rule(
        name="T8_DAQ_System",
        direction="in",
        exe_path=exe_path,
        description="T8 DAQ System — allows pyvisa TCPIP instrument discovery",
    ):
        print("  [OK] Inbound rule added.")
    else:
        print("  WARNING: Inbound rule may have failed.")

    # --- Add outbound rule -------------------------------------------------
    print("Adding outbound firewall rule...")
    if _add_rule(
        name="T8_DAQ_System",
        direction="out",
        exe_path=exe_path,
        description="T8 DAQ System — allows pyvisa TCPIP instrument communication",
    ):
        print("  [OK] Outbound rule added.")
    else:
        print("  WARNING: Outbound rule may have failed.")

    # --- Done --------------------------------------------------------------
    print()
    print("Done!  Firewall rules added for:")
    print(f"  {exe_path}")
    print()
    print("You only need to run this script once.")
    print("Windows will no longer prompt about network access for T8_DAQ_System.exe.")
    print()
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()

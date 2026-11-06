# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for T8 DAQ System
Handles Python runtime DLL dependencies and hardware library bundling
"""

import os
import sys
import matplotlib
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

# Project root and entry point
project_root = SPECPATH
main_script = os.path.join(project_root, 't8_daq_system', 'main.py')

# Detect Python environment DLL directories
# Primary: the DLLs folder next to the base Python interpreter
python_exe = Path(sys.executable)
# Resolve through venv to the base interpreter's directory
python_base = Path(sys.base_prefix)
python_dlls = str(python_base / 'DLLs')

print(f"Project root: {project_root}")
print(f"Main script: {main_script}")
print(f"Python base: {python_base}")
print(f"Python DLLs: {python_dlls}")

# ============================================================================
# BINARIES COLLECTION
# ============================================================================

binaries = []

# 1. PYTHON RUNTIME DLLS (from Python's own DLLs directory)
# ---------------------------------------------------------
# libffi is required for _ctypes; libcrypto/libssl for _ssl/_hashlib
python_dlls_list = [
    'libffi-8.dll',        # Foreign Function Interface (Python 3.14)
    'libcrypto-3.dll',     # OpenSSL 3.x
    'libssl-3.dll',        # OpenSSL 3.x
]

for dll_name in python_dlls_list:
    dll_path = os.path.join(python_dlls, dll_name)
    if os.path.exists(dll_path):
        binaries.append((dll_path, '.'))
        print(f"[OK] Found {dll_name} in {python_dlls}")
    else:
        print(f"[!!] Warning: {dll_name} not found in {python_dlls}")

# 2. TKINTER DEPENDENCIES
# ------------------------
# TCL/TK runtime files required for tkinter
tcl_dll_names = ['tcl86t.dll', 'tk86t.dll', 'tcl86.dll', 'tk86.dll']
for dll_name in tcl_dll_names:
    dll_path = os.path.join(python_dlls, dll_name)
    if os.path.exists(dll_path):
        binaries.append((dll_path, '.'))
        print(f"[OK] Found tkinter DLL: {dll_name}")

# 3. LABJACK LJM LIBRARY
# -----------------------
# NOT bundled. LabJackM.dll comes from the LJM installer, which the lab PC needs
# anyway for the T8's USB driver; labjack.ljm loads it from the system path.
# Copying vendor and Windows DLLs out of C:\Windows into an unsigned app folder
# is a pattern endpoint security flags (DLL side-loading).

# 4. ADDITIONAL RUNTIME DLLS
# ---------------------------
# The VC++ runtime ships beside python.exe; bundle that copy so the lab PC
# does not need the redistributable installed.
runtime_dlls = [
    'msvcp140.dll',
    'vcruntime140.dll',
    'vcruntime140_1.dll',
]

# Python's own copies only, never the Windows folder (see section 3).
runtime_search_paths = [
    python_dlls,
    str(python_base),
]

for dll_name in runtime_dlls:
    found = False
    for search_path in runtime_search_paths:
        dll_path = os.path.join(search_path, dll_name)
        if os.path.exists(dll_path):
            binaries.append((dll_path, '.'))
            print(f"[OK] Found runtime DLL: {dll_name} in {search_path}")
            found = True
            break
    if not found:
        print(f"[!!] Warning: {dll_name} not found in any search path")

print(f"\nTotal binaries to bundle: {len(binaries)}")

# ============================================================================
# DATA FILES (Config and Resources)
# ============================================================================
# sensor_config.json is intentionally NOT bundled — sensor config now comes from
# AppSettings (Windows Registry). feedforward_map.json IS bundled: it is read at
# runtime by FeedforwardMap.load(); without it the frozen exe loads an empty map
# and feedforward silently does nothing.
datas = [
    (os.path.join(matplotlib.get_data_path(), 'fonts'), 'matplotlib/mpl-data/fonts'),
    (os.path.join(project_root, 't8_daq_system', 'config', 'feedforward_map.json'),
     't8_daq_system/config'),
]

print(f"Data files to bundle: {len(datas)}")

# ============================================================================
# HIDDEN IMPORTS
# ============================================================================

hiddenimports = [
    # Core Python modules that may be missed
    '_ctypes',
    'ctypes',
    'ctypes.util',
    'multiprocessing',

    # Tkinter and GUI
    'tkinter',
    'tkinter.ttk',
    'tkinter.filedialog',
    'tkinter.messagebox',
    '_tkinter',

    # Matplotlib and backends
    'matplotlib',
    'matplotlib.backends.backend_tkagg',
    'matplotlib.backends.backend_agg',
    'matplotlib.figure',
    'matplotlib.dates',
    'matplotlib.pyplot',

    # LabJack hardware library
    'labjack',
    'labjack.ljm',
    'labjack.ljm.ljm',

    # PyVISA (instrument control)
    'pyvisa',
    'pyvisa_py',  # Critical: pyvisa uses dynamic import
    'pyvisa.ctwrapper',
    'pyvisa.resources',

    # Serial communication
    'serial',
    'serial.tools',
    'serial.tools.list_ports',

    # Data handling
    'numpy',
    'numpy._core._methods',
    'numpy.lib.format',

    # Standard library modules
    'json',
    'csv',
    'threading',
    'queue',
    'collections',
    'dataclasses',
    'typing',
    'enum',
    'datetime',
    'winreg',    # Windows Registry — used by AppSettings for persistent settings

    # Missing dependencies for pyvisa and serial
    'pyvisa.resources.serial',
    'serial.serialwin32',   # Windows serial backend
    'serial.serialutil',
    'encodings',
    'encodings.utf_8',
    'encodings.ascii',
    'encodings.latin_1',

    # Camera — Logitech C920s via OpenCV + PIL display. Timelapse export uses
    # OpenCV's in-process encoder (data/timelapse_video.py), not imageio-ffmpeg:
    # its bundled ffmpeg.exe is a second unsigned executable.
    'cv2',
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
    'PIL._tkinter_finder',

    # zeroconf removed — network service discovery is disabled in frozen mode
    # to prevent background network scanning that degrades performance.
    # 'zeroconf',
    # 'zeroconf._services',
    # 'zeroconf._utils',
]

print(f"Hidden imports: {len(hiddenimports)}")

# ============================================================================
# MATPLOTLIB HOOKS CONFIGURATION
# ============================================================================

hooksconfig = {
    'matplotlib': {
        'backends': 'TkAgg',  # Explicitly include TkAgg backend
    },
}

# ============================================================================
# ANALYSIS
# ============================================================================

a = Analysis(
    [main_script],
    pathex=[
        project_root,
    ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig=hooksconfig,
    runtime_hooks=[],
    excludes=[
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'sphinx',
        'setuptools',
        # Endpoint security deleted a build that carried these (see
        # tests/unit/test_edr_safe_build.py). Excluded so a stray install in the
        # build environment can never bring them back.
        'pyautogui',      # key/mouse injection into other windows
        'pygetwindow',    # window enumeration
        'pyscreeze',      # screenshots
        'pymsgbox',
        'pytweening',
        'imageio',
        'imageio_ffmpeg', # ships ffmpeg.exe
        'zeroconf',       # mDNS network discovery, pulled in by pyvisa_py
    ],
    noarchive=False,
)

# ============================================================================
# PYZ (Python Archive)
# ============================================================================

pyz = PYZ(
    a.pure,
    a.zipped_data,
)

# ============================================================================
# EXE (Folder-based Executable - Fast Launch)
# ============================================================================

exe = EXE(
    pyz,
    a.scripts,
    [],          # Binaries go to COLLECT, not here
    exclude_binaries=True,  # Enable folder mode for faster startup
    name='T8_DAQ_System',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,   # Disable UPX - compression causes DLL decompression overhead
    console=False,  # No console window for end-users; set True only to debug crashes
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='tds_t8.ico',  # Add .ico file path here if you have an icon
)

# ============================================================================
# COLLECT (Bundle all files into a folder)
# ============================================================================

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='T8_DAQ_System',
)

print("\n" + "="*80)
print("PyInstaller spec file configuration complete!")
print("="*80)
print("\nBuild through scripts/build.py (or build.bat), not pyinstaller directly:")
print("  python scripts/build.py")
print("\nOutput: dist/T8_DAQ_System_<Build ID>/ (ADR 0008).")
print("Ship that whole folder (zip it up if needed).")
print("The .exe inside the folder is what users run.")
print("\nIf you encounter issues, enable debug mode:")
print("  1. Set console=True in the EXE section above")
print("  2. Set debug=True in the EXE section above")
print("  3. Rebuild and run from command line to see errors")
print("="*80)

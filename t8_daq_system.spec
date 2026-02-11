# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for T8 DAQ System
Handles Anaconda DLL dependencies and hardware library bundling
"""

import os
import sys
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================

# Project root and entry point
project_root = os.path.abspath(os.path.dirname(__file__))
main_script = os.path.join(project_root, 't8_daq_system', 'main.py')

# Detect Anaconda/Python environment
conda_base = os.environ.get('CONDA_PREFIX', '')
if not conda_base:
    # Try to detect from Python executable path
    python_exe = Path(sys.executable)
    if 'anaconda3' in str(python_exe).lower() or 'miniconda' in str(python_exe).lower():
        conda_base = str(python_exe.parent.parent)

# Define critical DLL paths for Anaconda
if conda_base:
    conda_bin = os.path.join(conda_base, 'Library', 'bin')
    conda_dlls = os.path.join(conda_base, 'DLLs')
else:
    # Fallback to hardcoded user path
    conda_bin = r'C:\Users\IGLeg\anaconda3\Library\bin'
    conda_dlls = r'C:\Users\IGLeg\anaconda3\DLLs'

print(f"Project root: {project_root}")
print(f"Main script: {main_script}")
print(f"Conda base: {conda_base if conda_base else 'Not detected, using fallback'}")
print(f"Conda bin: {conda_bin}")
print(f"Conda DLLs: {conda_dlls}")

# ============================================================================
# BINARIES COLLECTION
# ============================================================================

binaries = []

# 1. CTYPES DEPENDENCIES (Critical Fix)
# --------------------------------------
# These DLLs are required for _ctypes module to work
ctypes_dlls = [
    'libffi-7.dll',      # Foreign Function Interface (older)
    'libffi-8.dll',      # Foreign Function Interface (newer)
    'ffi.dll',           # Alternative name
    'libcrypto-1_1-x64.dll',  # OpenSSL dependency
    'libssl-1_1-x64.dll',     # OpenSSL dependency
]

for dll_name in ctypes_dlls:
    # Try conda Library/bin first
    dll_path = os.path.join(conda_bin, dll_name)
    if os.path.exists(dll_path):
        binaries.append((dll_path, '.'))
        print(f"✓ Found {dll_name} in {conda_bin}")
    # Try conda DLLs folder
    elif os.path.exists(os.path.join(conda_dlls, dll_name)):
        dll_path = os.path.join(conda_dlls, dll_name)
        binaries.append((dll_path, '.'))
        print(f"✓ Found {dll_name} in {conda_dlls}")
    else:
        print(f"⚠ Warning: {dll_name} not found")

# 2. TKINTER DEPENDENCIES
# ------------------------
# TCL/TK runtime files required for tkinter
tcl_dll_names = ['tcl86t.dll', 'tk86t.dll', 'tcl86.dll', 'tk86.dll']
for dll_name in tcl_dll_names:
    dll_path = os.path.join(conda_bin, dll_name)
    if os.path.exists(dll_path):
        binaries.append((dll_path, '.'))
        print(f"✓ Found tkinter DLL: {dll_name}")

# 3. LABJACK LJM LIBRARY
# -----------------------
# LabJack hardware driver DLL
ljm_dll_locations = [
    r'C:\Program Files (x86)\LabJack\LJM\ljm.dll',
    r'C:\Program Files\LabJack\LJM\ljm.dll',
    os.path.join(conda_bin, 'ljm.dll'),
]

for ljm_path in ljm_dll_locations:
    if os.path.exists(ljm_path):
        binaries.append((ljm_path, '.'))
        print(f"✓ Found LabJack LJM: {ljm_path}")
        break
else:
    print("⚠ Warning: LabJack LJM DLL not found - hardware features may not work")

# 4. ADDITIONAL RUNTIME DLLS
# ---------------------------
# Other Anaconda runtime dependencies
runtime_dlls = [
    'msvcp140.dll',       # Microsoft Visual C++ Runtime
    'vcruntime140.dll',   # Visual C++ Runtime
    'vcruntime140_1.dll', # Visual C++ Runtime (additional)
]

for dll_name in runtime_dlls:
    dll_path = os.path.join(conda_bin, dll_name)
    if os.path.exists(dll_path):
        binaries.append((dll_path, '.'))
        print(f"✓ Found runtime DLL: {dll_name}")

print(f"\nTotal binaries to bundle: {len(binaries)}")

# ============================================================================
# DATA FILES (Config and Resources)
# ============================================================================

datas = [
    (os.path.join(project_root, 't8_daq_system', 'config'), 't8_daq_system/config'),
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
    'numpy.core',
    'numpy.core._methods',
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

block_cipher = None

a = Analysis(
    [main_script],
    pathex=[
        project_root,
        conda_bin,  # Add Anaconda bin to search path
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
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ============================================================================
# PYZ (Python Archive)
# ============================================================================

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

# ============================================================================
# EXE (Single File Executable)
# ============================================================================

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='T8_DAQ_System',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True if you want a console window for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add .ico file path here if you have an icon
)

print("\n" + "="*80)
print("PyInstaller spec file configuration complete!")
print("="*80)
print("\nTo build the executable, run:")
print("  pyinstaller t8_daq_system.spec --clean")
print("\nIf you encounter issues, enable debug mode:")
print("  1. Set console=True in the EXE section above")
print("  2. Set debug=True in the EXE section above")
print("  3. Rebuild and run from command line to see errors")
print("="*80)

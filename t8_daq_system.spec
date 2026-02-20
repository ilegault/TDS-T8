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
project_root = SPECPATH
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
    r'C:\Windows\System32\LabJackM.dll',
    r'C:\Program Files\LabJack\LJM\LabJackM.dll',
    r'C:\Program Files (x86)\LabJack\LJM\LabJackM.dll',
    os.path.join(conda_bin, 'LabJackM.dll'),
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
# Search multiple locations for runtime DLLs to ensure compatibility on other PCs
runtime_dlls = [
    'msvcp140.dll',
    'vcruntime140.dll',
    'vcruntime140_1.dll',
]

runtime_search_paths = [
    conda_bin,
    r'C:\Windows\System32',
    r'C:\Windows\SysWOW64',
    os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'System32'),
]

for dll_name in runtime_dlls:
    found = False
    for search_path in runtime_search_paths:
        dll_path = os.path.join(search_path, dll_name)
        if os.path.exists(dll_path):
            binaries.append((dll_path, '.'))
            print(f"✓ Found runtime DLL: {dll_name} in {search_path}")
            found = True
            break
    if not found:
        print(f"⚠ Warning: {dll_name} not found in any search path")

# 5. MISSING CRYPTO/COMPRESSION DLLS
# ------------------------------------
# These are needed by Python's _hashlib, _ssl, _lzma, and _bz2 modules.
# Without them, modules retry loading repeatedly, adding overhead.
crypto_dlls = [
    'libcrypto-3-x64.dll',
    'libssl-3-x64.dll',
    'liblzma.dll',
    'LIBBZ2.dll',
]

for dll_name in crypto_dlls:
    found = False
    for search_path in [conda_bin, conda_dlls, os.path.join(conda_base, '') if conda_base else '', r'C:\Windows\System32']:
        if not search_path:
            continue
        dll_path = os.path.join(search_path, dll_name)
        if os.path.exists(dll_path):
            binaries.append((dll_path, '.'))
            print(f"✓ Found {dll_name} in {search_path}")
            found = True
            break
    if not found:
        print(f"⚠ Warning: {dll_name} not found")

print(f"\nTotal binaries to bundle: {len(binaries)}")

# ============================================================================
# DATA FILES (Config and Resources)
# ============================================================================
# NOTE: The external sensor_config.json has been replaced by Windows Registry
# persistence (AppSettings / winreg).  No config files need to be bundled.

datas = []

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
    'winreg',    # Windows Registry — used by AppSettings for persistent settings

    # Missing dependencies for pyvisa and serial
    'pyvisa.resources.serial',
    'pyvisa.resources.gpib',
    'pyvisa.resources.usb',
    'pyvisa.resources.tcpip',
    'serial.serialwin32',   # Windows serial backend
    'serial.serialutil',
    'encodings',
    'encodings.utf_8',
    'encodings.ascii',
    'encodings.latin_1',

    # PyVISA network optimization (reduce startup time)
    'psutil',
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
    console=True,  # Set to True temporarily to see errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add .ico file path here if you have an icon
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
print("\nTo build the executable, run:")
print("  pyinstaller t8_daq_system.spec --clean")
print("\nOutput will be a dist/T8_DAQ_System/ folder instead of a single file.")
print("Ship that whole folder (zip it up if needed).")
print("The .exe inside the folder is what users run.")
print("\nIf you encounter issues, enable debug mode:")
print("  1. Set console=True in the EXE section above")
print("  2. Set debug=True in the EXE section above")
print("  3. Rebuild and run from command line to see errors")
print("="*80)

"""
t8_daq_system/build_info.py

The running application's Build ID (ticket cold-start-and-traceability-33, ADR 0008).

WHY THIS EXISTS
---------------
A run could not be diagnosed because nobody could tell which build was installed on
the rig PC.  scripts/build.py writes the gitignored ``_build_info.py`` holding
``BUILD_ID`` before it packages the app.  A development run has no such module, so
the Build ID is ``dev``.  Pure: no clock, hardware or Tk.
"""
from __future__ import annotations

DEV_BUILD_ID = "dev"


def get_build_id() -> str:
    """Return the generated Build ID, or ``dev`` when no build generated one."""
    try:
        from t8_daq_system import _build_info
    except ImportError:
        return DEV_BUILD_ID
    return _build_info.BUILD_ID

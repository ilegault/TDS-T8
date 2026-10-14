"""
AGENTS.md documentation test suite.

WHY THIS EXISTS
---------------
AGENTS.md is the only conventions file agents read (ticket 35).  After the
cold-start-and-traceability effort it must describe the code as it is: the
Soft start and the two current caps (ADR 0006), the registry-wins settings rule
and the ADR 0007 default gains, and the versioned build (ADR 0008).  Each
assertion is scoped to the section the ticket names, so a mention elsewhere
cannot satisfy it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

AGENTS_MD = Path(__file__).resolve().parents[2] / "AGENTS.md"


def _section(heading_prefix: str) -> str:
    """Return the text from the heading starting with ``heading_prefix`` to the next
    heading of the same or higher level."""
    text = AGENTS_MD.read_text(encoding="utf-8")
    match = re.search(rf"^(#+) {re.escape(heading_prefix)}.*$", text, re.MULTILINE)
    assert match, f"AGENTS.md has no heading starting with {heading_prefix!r}"
    level = len(match.group(1))
    rest = text[match.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


@pytest.mark.parametrize("heading, filename", [
    ("### `control/`", "suggestion_engine.py"),
    ("### `utils/`", "diagnostic_log.py"),
    ("### Build and traceability", "build_info.py"),
    ("### Build and traceability", "scripts/build.py"),
])
def test_codebase_map_lists_new_modules(heading, filename):
    """Each new module is listed under the directory table it belongs to."""
    section = _section(heading.lstrip("# "))
    assert f"`{filename}`" in section or f"/{filename}`" in section


def test_appsettings_section_states_registry_wins():
    section = _section("5.6 AppSettings")
    assert "registry wins" in section
    assert "sources" in section


def test_pid_gains_section_uses_adr_0007_defaults():
    section = _section("6.3")
    assert "0.014" in section
    assert "0.00078" in section
    assert "0.00845" in section
    assert "Kp=1.0" not in section


def test_build_section_uses_build_script_and_build_id():
    section = _section("11. PyInstaller Build")
    assert "scripts/build.py" in section
    assert "Build ID" in section


def test_invariants_name_soft_start_and_both_caps():
    section = _section("12.1")
    assert "Soft start" in section
    assert "Soft-start current cap" in section
    assert "Run current cap" in section

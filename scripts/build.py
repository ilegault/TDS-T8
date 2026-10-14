"""
scripts/build.py

Versioned build of the PyInstaller distribution (ticket cold-start-and-traceability-33).

WHY THIS EXISTS
---------------
Deployed builds were indistinguishable on disk (ADR 0008).  This script derives a
Build ID, ``YYYY-MM-DD_<git short hash>`` (suffixed ``-dirty`` for an uncommitted
tree, which is refused unless ``--allow-dirty``), writes it to the gitignored
``t8_daq_system/_build_info.py``, runs ``pyinstaller tds.spec --clean``, renames the
dist folder and exe to carry the ID, and writes BUILD_INFO.txt listing every shipped
file.  ``build_id`` and ``build_info_text`` are pure; git and PyInstaller go through
one injectable ``run`` so tests can fake them.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional, Sequence

APP_NAME = "T8_DAQ_System"
REPO_ROOT = Path(__file__).resolve().parent.parent


def build_id(short_hash: str, today: date, dirty: bool) -> str:
    """Return ``YYYY-MM-DD_<hash>``, plus ``-dirty`` for an uncommitted tree."""
    result = f"{today.isoformat()}_{short_hash}"
    return f"{result}-dirty" if dirty else result


def build_info_text(build_id: str, branch: str, built_at: str, files: list[str]) -> str:
    """Return the BUILD_INFO.txt body: ID, branch, build time, every shipped file."""
    lines = [
        f"Build ID: {build_id}",
        f"Branch: {branch}",
        f"Built at: {built_at}",
        "",
        "Files:",
    ]
    lines += [f"  {name}" for name in files]
    return "\n".join(lines) + "\n"


def default_run(cmd: Sequence[str], cwd: Optional[Path] = None) -> str:
    """Run ``cmd`` and return its stdout; raises CalledProcessError on failure."""
    return subprocess.run(
        list(cmd), cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def main(
    argv: Optional[Sequence[str]] = None,
    run: Callable[..., str] = default_run,
    root: Path = REPO_ROOT,
    today: Optional[date] = None,
) -> int:
    parser = argparse.ArgumentParser(description="Build the T8 DAQ System distribution")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="build from an uncommitted tree; the Build ID gets -dirty")
    args = parser.parse_args(argv)

    short_hash = run(["git", "rev-parse", "--short", "HEAD"], cwd=root).strip()
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root).strip()
    dirty = bool(run(["git", "status", "--porcelain"], cwd=root).strip())
    if dirty and not args.allow_dirty:
        print("Refusing to build: the working tree has uncommitted changes. "
              "Commit them, or pass --allow-dirty.", file=sys.stderr)
        return 1

    bid = build_id(short_hash, today or date.today(), dirty)
    info_module = root / "t8_daq_system" / "_build_info.py"
    info_module.write_text(f'BUILD_ID = "{bid}"\n', encoding="utf-8")

    run([sys.executable, "-m", "PyInstaller", "tds.spec", "--clean"], cwd=root)

    dist = root / "dist"
    out = dist / f"{APP_NAME}_{bid}"
    (dist / APP_NAME).rename(out)
    (out / f"{APP_NAME}.exe").rename(out / f"{APP_NAME}_{bid}.exe")

    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    files.append("BUILD_INFO.txt")
    built_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (out / "BUILD_INFO.txt").write_text(
        build_info_text(bid, branch, built_at, sorted(files)), encoding="utf-8")
    print(f"Built {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

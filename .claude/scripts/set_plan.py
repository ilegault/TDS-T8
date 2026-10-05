#!/usr/bin/env python3
"""
Writes the active implementation plan into a project's AGENTS.md.

AGENTS.md, not CLAUDE.md: this repo is worked by more than one agentic tool.
Antigravity reads AGENTS.md and cannot read CLAUDE.md; Claude Code reads
CLAUDE.md and cannot read AGENTS.md, but does follow an `@AGENTS.md` import.
So AGENTS.md holds everything and CLAUDE.md is a one-line import of it.
See docs/agents/multi-tool-setup.md. Do not point this back at CLAUDE.md
without reading that first — it would make the active plan invisible to
every non-Claude tool.

Two ways in:

  1. HOOK MODE (Claude Code). No arguments. Claude Code pipes the ExitPlanMode
     tool call in as JSON on stdin; we dig the plan text out of it.

         python3 set_plan.py

  2. FILE MODE (Cowork, or you, by hand). Pass a plan file and the project dir.

         python3 set_plan.py --plan-file plan.md --project-dir /path/to/repo

Either way the same two things happen: the plan is archived under
.claude/plans/<timestamp>.md, and the ACTIVE-PLAN block in AGENTS.md is
replaced with the new plan. Replaced, not appended — AGENTS.md is loaded into
every session's context, so only one plan should ever be live in it.

Exits 0 on anything short of a total failure. This is bookkeeping; it should
never take your session down with it.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

START = "<!-- ACTIVE-PLAN:START -->"
END = "<!-- ACTIVE-PLAN:END -->"

# Flip to True, run one plan, then read ~/.claude/plan-hook-debug.json to see
# exactly what Claude Code sends. Only relevant in hook mode.
DEBUG = False


def plan_from_hook(payload):
    """Plan text lives at tool_input.plan. If that field name ever changes,
    fall back to the longest string in tool_input."""
    tool_input = payload.get("tool_input") or {}
    if isinstance(tool_input.get("plan"), str):
        return tool_input["plan"]
    strings = [v for v in tool_input.values() if isinstance(v, str)]
    return max(strings, key=len) if strings else ""


def project_dir_from_hook(payload):
    """The process cwd is unreliable for ExitPlanMode hooks, so trust the
    exported env var first and the JSON field second."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    cwd = payload.get("cwd")
    if cwd and Path(cwd).is_dir():
        return Path(cwd)
    return Path.cwd()


def build_block(plan, stamp):
    return (
        f"{START}\n"
        f"## Active implementation plan\n\n"
        f"_Written by the planning model on {stamp}. Implement this. "
        f"If something in it is wrong, say so before changing course._\n\n"
        f"{plan.strip()}\n"
        f"{END}"
    )


def write_agents_md(project_dir, block):
    path = project_dir / "AGENTS.md"
    if not path.exists():
        path.write_text(block + "\n", encoding="utf-8")
        return path

    text = path.read_text(encoding="utf-8")
    if START in text and END in text:
        head = text.split(START)[0]
        tail = text.split(END, 1)[1]
        path.write_text(head + block + tail, encoding="utf-8")
    else:
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        path.write_text(text + sep + block + "\n", encoding="utf-8")
    return path


def commit(project_dir, plan):
    if not plan.strip():
        return None

    now = datetime.now()
    stamp_file = now.strftime("%Y-%m-%d_%H%M%S")

    archive_dir = project_dir / ".claude" / "plans"
    archive_dir.mkdir(parents=True, exist_ok=True)

    target = archive_dir / f"{stamp_file}.md"
    n = 1
    while target.exists():  # two plans in the same second shouldn't clobber
        target = archive_dir / f"{stamp_file}-{n}.md"
        n += 1
    target.write_text(plan.strip() + "\n", encoding="utf-8")
    stamp_file = target.stem

    write_agents_md(project_dir, build_block(plan, now.strftime("%Y-%m-%d %H:%M")))
    return stamp_file


def publish(project_dir, plan):
    """Commit and push ONLY the plan files, so a cloud session can see them.

    A Claude Code cloud session clones your repo from GitHub — it never sees
    your laptop's working tree. An uncommitted plan is invisible to it.

    Deliberately narrow: stages AGENTS.md and .claude/plans/ and nothing else,
    so your half-finished code never gets swept into a plan commit.
    """
    def git(*args, check=True):
        return subprocess.run(
            ["git", "-C", str(project_dir), *args],
            capture_output=True, text=True, check=check,
        )

    try:
        git("rev-parse", "--git-dir")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Not a git repo (or git missing) — skipping push.", file=sys.stderr)
        return

    git("add", "--", "AGENTS.md", "CLAUDE.md", ".claude/plans")

    staged = git("diff", "--cached", "--name-only", check=False).stdout.strip()
    if not staged:
        print("Plan files unchanged — nothing to commit.")
        return

    headline = next(
        (ln.strip() for ln in plan.splitlines()
         if ln.strip() and not ln.strip().startswith(("*", "#", "_"))),
        "update plan",
    )[:60]
    git("commit", "-m", f"plan: {headline}")

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    pushed = git("push", "origin", branch, check=False)
    if pushed.returncode == 0:
        print(f"Committed and pushed plan to origin/{branch}.")
    else:
        print(f"Committed locally, but push failed:\n{pushed.stderr.strip()}",
              file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--plan-file", help="Markdown file holding the plan (file mode)")
    ap.add_argument("--project-dir", help="Repo root containing AGENTS.md (file mode)")
    ap.add_argument("--git", action="store_true",
                    help="Also commit and push the plan files, so a Claude Code "
                         "cloud session can see them")
    args = ap.parse_args()

    if args.plan_file:
        # ---- FILE MODE ----
        plan = Path(args.plan_file).read_text(encoding="utf-8")
        project_dir = Path(args.project_dir or Path.cwd())
        stamp = commit(project_dir, plan)
        print(f"Plan written to {project_dir / 'AGENTS.md'}")
        if stamp:
            print(f"Archived to {project_dir}/.claude/plans/{stamp}.md")
        if args.git:
            publish(project_dir, plan)
        return

    # ---- HOOK MODE ----
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"set_plan: could not parse hook input ({exc})", file=sys.stderr)
        return

    if DEBUG:
        Path.home().joinpath(".claude/plan-hook-debug.json").write_text(
            raw, encoding="utf-8"
        )

    plan = plan_from_hook(payload)
    stamp = commit(project_dir_from_hook(payload), plan)
    if stamp:
        # systemMessage shows in your transcript; Claude doesn't see it.
        print(json.dumps({
            "systemMessage": f"Plan written to AGENTS.md, archived to "
                             f".claude/plans/{stamp}.md"
        }))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"set_plan failed: {exc}", file=sys.stderr)
    sys.exit(0)
"""
scripts/ticket_conductor.py
Drive every ready ticket of an effort through implement -> CI -> auto-fix -> merge.

WHY THIS EXISTS
---------------
AGENTS.md section 12.4 makes the developer babysit each ticket: start a worker, watch
CI, re-prompt on red, merge on green, then find the next unblocked ticket. This script
is that babysitter. It reads the tracker from origin/main (never the working tree),
works the dependency frontier, runs one headless `claude -p` worker per ticket in
parallel, and then owns the PR:

    red CI or merge conflict -> fix agent (at most --max-fix cycles, then escalate)
    green CI                 -> squash-merge, but only if the ticket says Auto-merge: yes

ESCALATION
----------
After --max-fix failed cycles the PR is converted to draft and the ticket is left for
the developer (AGENTS.md 12.4 step 8). The fix agent is told to write the escalation
report into the ticket file; the conductor only flips the PR to draft and logs it.
It never mutes a test (ADR 0001) - that rule is repeated in every prompt.

USAGE
-----
    python scripts/ticket_conductor.py --dry-run            # show the frontier, do nothing
    python scripts/ticket_conductor.py --only 19 20 34      # just these tickets
    python scripts/ticket_conductor.py --max-parallel 3     # everything, 3 at a time

Per-worker transcripts are written to logs/conductor/ (git-ignored).
Requires: git, gh (authenticated), claude (Claude Code CLI).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("conductor")

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = REPO_ROOT / "logs" / "conductor"
DEFAULT_EFFORT = "cold-start-and-traceability"
POLL_SECONDS = 30
CI_TIMEOUT_SECONDS = 40 * 60
AUTO_MERGE_WAIT_SECONDS = 10 * 60
MAX_BRANCH_UPDATES = 3
PASS_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL"}

DEFAULT_CLAUDE_ARGS = (
    "--permission-mode acceptEdits "
    "--allowedTools Bash,Edit,Write,Read,Glob,Grep,Skill"
)

RULES = (
    "Binding rules: AGENTS.md section 12 and docs/adr/0001-tests-first-and-no-muted-failures.md. "
    "Never xfail, skip, delete, weaken or loosen a test, and never hide an error with try/except. "
    "Never commit to main. Never enable auto-merge - the conductor merges. "
    "Run `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` locally "
    "with 0 failures before every push."
)


@dataclass
class Ticket:
    number: int
    path: str  # repo-relative, forward slashes
    status: str
    blocked_by: list[int]
    auto_merge: bool

    @property
    def stem(self) -> str:
        return Path(self.path).stem


def run(cmd: list[str], cwd: Path = REPO_ROOT, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def read_tickets(effort: str) -> dict[int, Ticket]:
    """Parse every ticket from origin/main so local checkouts never skew the view."""
    run(["git", "fetch", "origin", "main", "--quiet"])
    folder = f".scratch/{effort}/issues"
    names = run(["git", "ls-tree", "--name-only", f"origin/main:{folder}"]).split()
    tickets: dict[int, Ticket] = {}
    for name in names:
        match = re.match(r"(\d+)-.*\.md$", name)
        if not match:
            continue
        text = run(["git", "show", f"origin/main:{folder}/{name}"])
        status = re.search(r"\*\*Status:\*\*\s*([\w-]+)", text)
        blocked = re.search(r"\*\*Blocked by:\*\*\s*(.*)", text)
        merge = re.search(r"\*\*Auto-merge:\*\*\s*(\w+)", text)
        number = int(match.group(1))
        tickets[number] = Ticket(
            number=number,
            path=f"{folder}/{name}",
            status=status.group(1) if status else "unknown",
            blocked_by=[int(n) for n in re.findall(r"\d+", blocked.group(1))] if blocked else [],
            auto_merge=bool(merge and merge.group(1).lower() == "yes"),
        )
    return tickets


def open_ticket_prs(effort: str) -> dict[int, int]:
    """Map ticket number -> open PR number, from the `ticket/<effort>-NN-` branch prefix."""
    out = run(["gh", "pr", "list", "--state", "open", "--json", "number,headRefName", "--limit", "100"])
    prs: dict[int, int] = {}
    for pr in json.loads(out):
        match = re.match(rf"ticket/{re.escape(effort)}-(\d+)-", pr["headRefName"])
        if match:
            prs[int(match.group(1))] = pr["number"]
    return prs


def frontier(tickets: dict[int, Ticket], skip: set[int]) -> list[Ticket]:
    ready = []
    for ticket in tickets.values():
        if ticket.status != "ready-for-agent" or ticket.number in skip:
            continue
        if all(tickets.get(b) is not None and tickets[b].status == "done" for b in ticket.blocked_by):
            ready.append(ticket)
    return sorted(ready, key=lambda t: t.number)


def claude(prompt: str, label: str, claude_args: str, cwd: Path = REPO_ROOT) -> int:
    """Run one headless worker; the full transcript goes to logs/conductor/<label>.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cmd = ["claude", "-p", prompt, *claude_args.split()]
    log.info("[%s] worker started", label)
    with open(LOG_DIR / f"{label}.log", "ab") as fh:
        proc = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    log.info("[%s] worker exited %s", label, proc.returncode)
    return proc.returncode


def pr_state(pr: int) -> tuple[str, str]:
    """Return (ci, mergeable): ci is 'green' | 'red' | 'pending'."""
    data = json.loads(run(["gh", "pr", "view", str(pr), "--json", "statusCheckRollup,mergeable"]))
    checks = data.get("statusCheckRollup") or []
    if not checks:
        return "pending", data["mergeable"]
    verdicts = []
    for check in checks:
        if check.get("status") not in (None, "COMPLETED") and "state" not in check:
            verdicts.append("pending")
            continue
        outcome = check.get("conclusion") or check.get("state") or ""
        if outcome in PASS_CONCLUSIONS:
            verdicts.append("green")
        elif outcome in ("PENDING", "EXPECTED", ""):
            verdicts.append("pending")
        else:
            verdicts.append("red")
    if "red" in verdicts:
        return "red", data["mergeable"]
    if "pending" in verdicts:
        return "pending", data["mergeable"]
    return "green", data["mergeable"]


def pr_lifecycle(pr: int) -> tuple[str, str]:
    """Return (state, mergeStateStatus): state is OPEN | MERGED | CLOSED."""
    data = json.loads(run(["gh", "pr", "view", str(pr), "--json", "state,mergeStateStatus"]))
    return data["state"], data["mergeStateStatus"]


def wait_for_verdict(pr: int) -> tuple[str, str]:
    """Return 'merged' | 'closed' | 'green' | 'red'; someone else may merge while we wait.

    The repo's own dispatch engine auto-merges green ticket PRs, so a PR can vanish from
    OPEN between two polls. That is success, not a failure to wait out.
    """
    deadline = time.monotonic() + CI_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        state, _ = pr_lifecycle(pr)
        if state in ("MERGED", "CLOSED"):
            return state.lower(), state
        ci, mergeable = pr_state(pr)
        if ci == "red" or mergeable == "CONFLICTING":
            return "red", mergeable
        if ci == "green" and mergeable != "UNKNOWN":
            return "green", mergeable
        time.sleep(POLL_SECONDS)
    return "red", "TIMEOUT"


def branch_worktree(branch: str) -> Path:
    """Reuse the worktree that already has `branch` checked out, or add one."""
    listing = run(["git", "worktree", "list", "--porcelain"])
    current = None
    for line in listing.splitlines():
        if line.startswith("worktree "):
            current = Path(line.split(" ", 1)[1])
        elif line == f"branch refs/heads/{branch}" and current:
            return current
    run(["git", "fetch", "origin", branch, "--quiet"])
    target = REPO_ROOT.parent / "tds-conductor-worktrees" / branch.replace("/", "_")[:80]
    target.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "worktree", "add", "-B", branch, str(target), f"origin/{branch}"])
    return target


def fix_prompt(ticket: Ticket, pr: int, branch: str, mergeable: str, attempt: int, last: bool) -> str:
    escalate = (
        " This is the LAST allowed attempt: if it still cannot go green, do the four-step escalation "
        "from AGENTS.md 12.4 (commit, `Status: blocked`, append what was tried / what failed (quoted) / "
        "what decision is needed under `## Comments` in the ticket file, push)."
        if last else ""
    )
    return (
        f"PR #{pr} (branch {branch}) for ticket {ticket.path} is not mergeable: "
        f"CI is red or mergeable={mergeable}. Fix attempt {attempt}. "
        "You are in a worktree of that branch. Read the failing logs with `gh pr checks "
        f"{pr}` and `gh run view <id> --log-failed`; fix the ROOT CAUSE. If mergeable=CONFLICTING, "
        "`git fetch origin main && git merge origin/main` and resolve the conflicts faithfully to both "
        f"sides' intent. Then push. {RULES}{escalate}"
    )


def implement_prompt(ticket: Ticket) -> str:
    return (
        f"Use the implement-ticket-parallel skill to implement exactly ONE ticket: {ticket.path} "
        "(read it, its spec.md and the ADRs it names). Follow AGENTS.md section 12.4. Write the test first. "
        "Set `Status: in-progress` when starting and `Status: done` in the same PR. Push and open the PR "
        "against main with `gh pr create`, then STOP - a conductor watches CI and merges. "
        f"{RULES}"
    )


def merge_pr(label: str, pr: int) -> str:
    """Land a green PR: squash-merge, refresh a stale branch, or arm auto-merge and wait.

    Three things can stand in the way, all seen on real runs:
    - the ruleset is strict, so a branch behind main is refused ("not up to date"):
      `gh pr update-branch`, wait for CI on the new head, retry;
    - the dispatch engine may merge the PR first: that counts as merged;
    - a ruleset can demand a status that never arrives: report the contexts instead of hanging.
    """
    merge = ["gh", "pr", "merge", str(pr), "--squash", "--delete-branch"]
    for _ in range(MAX_BRANCH_UPDATES + 1):
        if pr_lifecycle(pr)[0] == "MERGED":
            log.info("[%s] PR #%d merged (by someone else)", label, pr)
            return "merged"
        first = subprocess.run(merge, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        if first.returncode == 0:
            log.info("[%s] PR #%d merged", label, pr)
            return "merged"
        reason = first.stderr.strip().splitlines()[0] if first.stderr.strip() else "unknown"
        log.warning("[%s] PR #%d refused: %s", label, pr, reason)
        if "not up to date" not in reason and pr_lifecycle(pr)[1] != "BEHIND":
            break
        log.info("[%s] PR #%d is behind main - updating the branch and re-running CI", label, pr)
        run(["gh", "pr", "update-branch", str(pr)], check=False)
        time.sleep(POLL_SECONDS)  # let CI register the new head
        verdict, _ = wait_for_verdict(pr)
        if verdict == "merged":
            log.info("[%s] PR #%d merged (by someone else)", label, pr)
            return "merged"
        if verdict != "green":
            log.error("[%s] PR #%d went %s after updating the branch", label, pr, verdict)
            return "blocked"
    else:
        log.error("[%s] PR #%d keeps falling behind main", label, pr)
        return "blocked"

    armed = subprocess.run([*merge, "--auto"], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if armed.returncode != 0:
        log.error("[%s] cannot arm auto-merge either: %s", label, armed.stderr.strip())
        return "blocked"
    log.info("[%s] auto-merge armed on PR #%d, waiting for branch rules", label, pr)
    deadline = time.monotonic() + AUTO_MERGE_WAIT_SECONDS
    while time.monotonic() < deadline:
        state, merge_state = pr_lifecycle(pr)
        if state == "MERGED":
            log.info("[%s] PR #%d merged", label, pr)
            return "merged"
        if merge_state == "BEHIND":
            run(["gh", "pr", "update-branch", str(pr)], check=False)
        time.sleep(POLL_SECONDS)
    sha = json.loads(run(["gh", "pr", "view", str(pr), "--json", "headRefOid"]))["headRefOid"]
    seen = run(["gh", "api", f"repos/{{owner}}/{{repo}}/commits/{sha}/status", "--jq",
                "[.statuses[].context]"], check=False).strip()
    log.error("[%s] PR #%d still unmerged; statuses posted on head: %s. Compare with the "
              "required contexts in the repo rulesets.", label, pr, seen)
    return "blocked"


def drive_ticket(ticket: Ticket, effort: str, args: argparse.Namespace) -> str:
    """Lifecycle of one ticket; returns 'merged' | 'ready' | 'escalated' | 'failed'."""
    label = ticket.stem
    prs = open_ticket_prs(effort)
    if ticket.number not in prs:
        claude(implement_prompt(ticket), f"{label}-implement", args.claude_args)
        prs = open_ticket_prs(effort)
        if ticket.number not in prs:
            log.error("[%s] worker finished without opening a PR", label)
            return "failed"
    pr = prs[ticket.number]
    branch = json.loads(run(["gh", "pr", "view", str(pr), "--json", "headRefName"]))["headRefName"]
    log.info("[%s] watching PR #%d", label, pr)

    for attempt in range(1, args.max_fix + 2):
        verdict, mergeable = wait_for_verdict(pr)
        if verdict == "merged":
            log.info("[%s] PR #%d merged (by the engine or you)", label, pr)
            return "merged"
        if verdict == "closed":
            log.error("[%s] PR #%d was closed without merging", label, pr)
            return "failed"
        if verdict == "green":
            if not ticket.auto_merge:
                log.info("[%s] PR #%d green but Auto-merge is not 'yes' - left for the developer", label, pr)
                return "ready"
            return merge_pr(label, pr)
        if attempt > args.max_fix:
            break
        last = attempt == args.max_fix
        log.warning("[%s] PR #%d red (%s) - fix attempt %d/%d", label, pr, mergeable, attempt, args.max_fix)
        worktree = branch_worktree(branch)
        claude(fix_prompt(ticket, pr, branch, mergeable, attempt, last),
               f"{label}-fix{attempt}", args.claude_args, cwd=worktree)
        time.sleep(POLL_SECONDS)  # let CI register the new push

    run(["gh", "pr", "ready", str(pr), "--undo"], check=False)
    log.error("[%s] PR #%d escalated to draft - needs the developer (see the ticket's ## Comments)", label, pr)
    return "escalated"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--effort", default=DEFAULT_EFFORT)
    parser.add_argument("--only", type=int, nargs="*", help="restrict to these ticket numbers")
    parser.add_argument("--max-parallel", type=int, default=3)
    parser.add_argument("--max-fix", type=int, default=2, help="fix cycles before escalating (AGENTS.md 12.4)")
    parser.add_argument("--claude-args", default=DEFAULT_CLAUDE_ARGS,
                        help="extra flags for `claude -p`; pass '--dangerously-skip-permissions' for fully unattended")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    only = set(args.only) if args.only else None
    finished: set[int] = set()  # tickets this run is done with (merged or parked)
    running: dict[Future, Ticket] = {}
    results: dict[int, str] = {}

    with ThreadPoolExecutor(max_workers=args.max_parallel) as pool:
        while True:
            tickets = read_tickets(args.effort)
            in_flight = {t.number for t in running.values()}
            todo = [
                t for t in frontier(tickets, finished | in_flight)
                if only is None or t.number in only
            ]
            if args.dry_run:
                for t in todo:
                    log.info("would start %s (auto-merge=%s)", t.stem, t.auto_merge)
                return 0
            for t in todo:
                if len(running) >= args.max_parallel:
                    break
                running[pool.submit(drive_ticket, t, args.effort, args)] = t
            if not running:
                break
            done, _ = wait(list(running), return_when=FIRST_COMPLETED, timeout=POLL_SECONDS * 4)
            for fut in done:
                t = running.pop(fut)
                try:
                    results[t.number] = fut.result()
                except Exception:
                    log.exception("[%s] conductor error", t.stem)
                    results[t.number] = "failed"
                finished.add(t.number)

    log.info("summary: %s", ", ".join(f"{n}={r}" for n, r in sorted(results.items())) or "nothing to do")
    return 0 if all(r in ("merged", "ready") for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

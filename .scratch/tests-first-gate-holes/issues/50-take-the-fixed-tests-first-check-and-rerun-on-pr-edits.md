# 50: Take ticket-engine's fixed tests-first check, and re-run CI on PR edits and labels

**Status:** done

**Runner:** any

**Auto-merge:** no

**Blocked by:** None (can start immediately)

**Was waiting on:** ticket 87 in `ilegault/ticket-engine`. It is merged; the canonical file's
SHA-256 at the time of writing is
`ab072943baad008881a06373b4d8b632dc05c7efee2513adc0773b850b18e2c8`.

**Spec:** `.scratch/tests-first-gate-holes/spec.md` in `ilegault/ticket-engine` (D1–D7)
**Binding:** `docs/adr/0001-tests-first-and-no-muted-failures.md`

## What to build

This repo's `scripts/check_tests_first.py` passes when git cannot work out what changed,
ignores commit-message tags on PR runs, lets one tag exempt every later commit, and
treats a docstring-only edit as code. Ticket-engine's canonical copy fixes all four.
This repo takes that file unedited, so every repo runs the same gate.

1. Replace `scripts/check_tests_first.py` with the canonical file, byte for byte:
   `curl -fsSL https://raw.githubusercontent.com/ilegault/ticket-engine/master/scripts/check_tests_first.py -o scripts/check_tests_first.py`.
   Do not edit it, not even for lint. If the download fails, or `ruff check .` flags
   the file, set `Status: blocked` and say what failed under `## Comments`.
2. `.github/workflows/tests.yml`: under `pull_request:`, after its `branches:` line,
   add
   `    types: [opened, synchronize, reopened, edited, labeled, unlabeled]`.
   Nothing else in the workflow changes. The checkout already has `fetch-depth: 0`; leave it.
3. `docs/adr/0001-tests-first-and-no-muted-failures.md`, decision 1: the text from "a change under `t8_daq_system/` must also touch" through "or the `tests-exempt` PR label." (keep the words before it, ending in "CI enforces this with `scripts/check_tests_first.py`", and change the colon after them to a full stop): replace it with:

   > A change under `t8_daq_system/` must also touch `tests/`. A `.py` file whose code is
   > unchanged once docstrings and comments are removed does not count as a change.
   > Otherwise the escape is explicit and visible, and its reach depends on where it is
   > written: a tag (`[no-test-needed: <reason>]`, `[tests-exempt: <reason>]` or
   > `[skip-test-gate]`) in a commit message covers only the files that commit changed,
   > and a file is exempt only when every commit that changed it is tagged; the same tag
   > in the PR title or body, or the `tests-exempt` / `skip-test-gate` label, covers the
   > whole PR, and CI re-runs when the PR text or labels change. The check fails, never
   > passes, when it cannot work out what changed.

4. `AGENTS.md`, `### 12.3 Tests-first CI gate`: the sentence that starts "A change under `t8_daq_system/` must also touch `tests/`" and ends "the `tests-exempt` PR label.": replace it with the same text as step 3.

## Acceptance criteria

The canonical file's own tests live in ticket-engine. Here, prove the copy and the
wiring with the commands below on the PR branch; paste their output under
`## Comments`.

- [x] `scripts/check_tests_first.py` is byte-identical to the canonical file: the
  SHA-256 of the local file equals the SHA-256 of a fresh download of the URL in step 1
  (`python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`
  on each). (no test: the two hashes, pasted under Comments)
- [x] `python scripts/check_tests_first.py --files t8_daq_system/main.py` exits 1 and its output
  names `t8_daq_system/main.py`; adding `tests/test_x.py` to `--files` exits 0. (no test: the command output, pasted under Comments)
- [x] `.ticket-engine.toml` still has `source_paths = ["t8_daq_system"]` (the canonical file reads it; without it the check would look for `src/`). (no test: config line, checked by reading it)
- [x] `.github/workflows/tests.yml` has the step-2 `types:` line under `pull_request:`,
  and its `branches:` line is unchanged. (no test: workflow file)
- [x] ADR 0001 and `AGENTS.md` carry the step-3 text in place of the passages named in
  steps 3 and 4. (no test: documentation)
- [x] The gate below passes on the PR branch (this PR changes `scripts/`, `.github/`,
  `docs/` and `AGENTS.md` only, so the tests-first check passes with no tag). (no test: the gate itself)

## Gate

Run all of them, in CI's order (`.github/workflows/tests.yml`). All must pass.

```
ruff check .
python scripts/check_tests_first.py
pytest --tb=short -q
```

## Comments

### Verification Summary — 2026-11-10

1. **Criterion 1 (SHA-256 hash comparison):**
   - Local `scripts/check_tests_first.py`: `ab072943baad008881a06373b4d8b632dc05c7efee2513adc0773b850b18e2c8`
   - Canonical fresh download: `ab072943baad008881a06373b4d8b632dc05c7efee2513adc0773b850b18e2c8`
   - Both match byte for byte.

2. **Criterion 2 (CLI behavior on modified files):**
   - Command: `python scripts/check_tests_first.py --files t8_daq_system/main.py`
     - Output:
       ```
       FAIL: Application source files modified under 't8_daq_system/' without corresponding test changes under 'tests/':
         - t8_daq_system/main.py

       Tests-first rule violation (see ADR 0001 under docs/adr/):
       1. Write tests under 'tests/' covering the application changes.
       2. If this change is genuinely exempt from test updates, provide an explicit escape reason:
          - PR Label: 'tests-exempt' or 'skip-test-gate'
          - Commit message or PR body: [no-test-needed: <reason>], [tests-exempt: <reason>], or [skip-test-gate]
            (a commit tag covers only the files that commit changed)
       ```
     - Exit code: 1
   - Command: `python scripts/check_tests_first.py --files t8_daq_system/main.py tests/test_x.py`
     - Output:
       ```
       OK: Application source changes (1 file(s)) accompanied by test changes (1 file(s)).
       ```
     - Exit code: 0

3. **Criterion 3 (.ticket-engine.toml):**
   - Line 8 retains `source_paths = ["t8_daq_system"]`.

4. **Criterion 4 (.github/workflows/tests.yml):**
   - Added `types: [opened, synchronize, reopened, edited, labeled, unlabeled]` under `pull_request:`.
   - `branches: [main]` remains unchanged.

5. **Criterion 5 (ADR 0001 & AGENTS.md):**
   - Step 3 replacement text applied to ADR 0001 decision 1 and AGENTS.md §12.3.

6. **Criterion 6 (Full Gate):**
   - `ruff check .`: passed (All checks passed!)
   - `python scripts/check_tests_first.py`: passed (`OK: No code changes under 't8_daq_system/'.`)
   - `pytest --tb=short -q`: 636 passed in 16.65s (updated direct test calls in `tests/unit/test_check_tests_first.py` to supply `source_paths=_SRC`).

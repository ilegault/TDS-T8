# 45: Lab programs become scenarios

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 42, 43, 47

**Spec:** `.scratch/field-realistic-testing/spec.md`
**Binding:** ADR 0006. `docs/adr/0001-tests-first-and-no-muted-failures.md` is binding on all test work.

## What to build

The programs the operators really run become Scenario tests, so a change that breaks
one of them fails before a build. The programmer the app builds
(`t8_daq_system/gui/program_panel.py` `ProgramPanel`) has no save/load, so ticket 47
records each program as a JSON list of block dicts in `tests/fixtures/programs/`, in
the shape each block's `to_dict()` writes (`t8_daq_system/control/program_block.py`:
`asdict` of the dataclass, including `block_type`).

Requirements:
- Add `block_from_dict(d: dict)` and `blocks_from_list(items: list[dict])` to
  `t8_daq_system/control/program_block.py`: dispatch on `d["block_type"]`
  (`voltage_ramp`, `stable_hold`, `temp_ramp`, `soft_start`) to that class's existing
  `from_dict`; an unknown `block_type` raises `ValueError` naming it. Pure, no Tk.
- `tests/scenarios/test_lab_programs.py`, parametrised over every
  `tests/fixtures/programs/*.json`: load with `blocks_from_list`, run through
  `run_scenario` (ticket 42) with production settings and `max_s` equal to the
  program's planned duration (the last value of the `times` list returned by
  `compute_preview` in `t8_daq_system/control/program_run.py`) plus 50 %.
- A block whose `tc_name` is not `TC_1` is rewritten to `TC_1` for the simulator,
  and the test id says so.

Tests may fake: time (`ManualClock`). Must be real: the JSON files, `blocks_from_list`,
`run_scenario`, production settings.

## Acceptance criteria

- [ ] `test_blocks_round_trip_through_dicts` and `test_unknown_block_type_is_refused` in
      `tests/unit/test_program_block.py` (create if absent): `blocks_from_list([b.to_dict() for b in blocks]) == blocks`
      for one block of each of the four types, and `block_from_dict({"block_type": "nope"})`
      raises `ValueError` whose message contains `nope`.
- [ ] `test_lab_program_completes_without_trip`, for each JSON under `tests/fixtures/programs/`: `completed is True` and
      `trip_kind is None`; the assertion message names the file, `trip_reason`,
      `t_end_s` and `peak_amps`.
- [ ] `test_lab_programs_folder_is_not_empty` asserts `tests/fixtures/programs/` holds at least one JSON, so the
      parametrised test cannot silently collect nothing.
- [ ] `ruff check .`, `python scripts/check_tests_first.py` and `pytest --tb=short -q` all pass (no test: the CI gate itself)

## Gate

Run in this order, as CI does (`.github/workflows/tests.yml`):

    ruff check .
    python scripts/check_tests_first.py
    pytest --tb=short -q

## Comments

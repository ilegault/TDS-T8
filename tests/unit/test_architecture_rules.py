"""
Architecture rules test suite.

Enforces package boundary invariants using AST scanning.

WHY THIS EXISTS
---------------
ADR 0002 mandates that only the Rig module owns hardware I/O and communicates
with labjack / serial devices. Leaking hardware calls or UI imports into
pure logic packages degrades testability, causes race conditions, and violates
the target single-thread single-loop architecture.
"""
from __future__ import annotations

import ast
from pathlib import Path
import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "t8_daq_system"


def _iter_python_files(base_dir: Path):
    """Yield all .py files under base_dir."""
    for p in base_dir.rglob("*.py"):
        if "__pycache__" not in p.parts:
            yield p


def _get_imports(file_path: Path) -> list[tuple[int, str]]:
    """Parse a python file and return list of (lineno, imported_module_name)."""
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))
    imports: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((node.lineno, node.module))
    return imports


def test_labjack_and_serial_only_under_hardware():
    """
    Rule 1: `labjack` and `serial` can be imported ONLY under `t8_daq_system/hardware/`.
    No other package in t8_daq_system may import them.
    """
    forbidden_modules = ("labjack", "serial")
    violations = []

    for py_file in _iter_python_files(PACKAGE_ROOT):
        rel_parts = py_file.relative_to(PACKAGE_ROOT).parts
        if rel_parts[0] == "hardware":
            continue

        for lineno, mod_name in _get_imports(py_file):
            root_mod = mod_name.split(".")[0]
            if root_mod in forbidden_modules:
                violations.append(f"{py_file.relative_to(REPO_ROOT)}:{lineno} imports {mod_name}")

    assert not violations, "Forbidden hardware library imports outside hardware/:\n" + "\n".join(violations)


def test_hardware_imported_only_under_rig():
    """
    Rule 2: `t8_daq_system.hardware` is imported only under `rig/` (ADR 0002).
    No transitional exceptions remain (Ticket 14).
    """
    violations = []

    for py_file in _iter_python_files(PACKAGE_ROOT):
        rel_parts = py_file.relative_to(PACKAGE_ROOT).parts
        rel_path = py_file.relative_to(REPO_ROOT)

        if rel_parts[0] in ("hardware", "rig"):
            continue

        for lineno, mod_name in _get_imports(py_file):
            if mod_name.startswith("t8_daq_system.hardware") or mod_name.startswith("hardware"):
                violations.append(f"{rel_path}:{lineno} imports {mod_name}")

    assert not violations, "Forbidden t8_daq_system.hardware imports outside rig/:\n" + "\n".join(violations)


def test_heater_calls_only_under_rig_and_hardware():
    """
    Rule 4: Calls to write_voltage, set_output, set_voltage, output_on, output_off,
    and emergency_shutdown appear only under rig/ and hardware/.

    These method calls represent direct hardware control. Any caller outside those
    two packages violates ADR 0003 (one writer of the heater).
    No transitional exceptions remain (Ticket 14).
    """
    FORBIDDEN_CALL_NAMES = {
        "write_voltage",
        "set_output",
        "set_voltage",
        "output_on",
        "output_off",
        "emergency_shutdown",
    }

    violations = []
    for py_file in _iter_python_files(PACKAGE_ROOT):
        rel_parts = py_file.relative_to(PACKAGE_ROOT).parts
        rel_path = py_file.relative_to(REPO_ROOT)

        if rel_parts[0] in ("hardware", "rig"):
            continue

        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_CALL_NAMES:
                    violations.append(
                        f"{rel_path}:{node.lineno} calls {func.attr!r}"
                    )

    assert not violations, (
        "Hardware-control calls outside rig/ and hardware/:\n"
        + "\n".join(violations)
    )


def test_no_sleep_under_control_run_record_and_rig():
    """
    Rule 6: The only `time.sleep` under `control/`, `data/run_record.py` and `rig/`
    is inside `RealClock.sleep_until` (ADR 0002, Ticket 14).
    """
    targets: list[Path] = []
    control_dir = PACKAGE_ROOT / "control"
    if control_dir.exists():
        targets.extend(_iter_python_files(control_dir))
    run_record_file = PACKAGE_ROOT / "data" / "run_record.py"
    if run_record_file.exists():
        targets.append(run_record_file)
    rig_dir = PACKAGE_ROOT / "rig"
    if rig_dir.exists():
        targets.extend(_iter_python_files(rig_dir))

    violations = []
    real_clock_path = PACKAGE_ROOT / "rig" / "clock.py"

    for py_file in targets:
        rel_path = py_file.relative_to(REPO_ROOT)
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))

        class SleepVisitor(ast.NodeVisitor):
            def __init__(self):
                self.current_class: str | None = None
                self.current_func: str | None = None

            def visit_ClassDef(self, node: ast.ClassDef):
                old_cls = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = old_cls

            def visit_FunctionDef(self, node: ast.FunctionDef):
                old_func = self.current_func
                self.current_func = node.name
                self.generic_visit(node)
                self.current_func = old_func

            def visit_Call(self, node: ast.Call):
                func = node.func
                # Check for time.sleep(...) or sleep(...)
                is_sleep = False
                if isinstance(func, ast.Attribute) and func.attr == "sleep":
                    is_sleep = True
                elif isinstance(func, ast.Name) and func.id == "sleep":
                    is_sleep = True

                if is_sleep:
                    # Allowed only inside RealClock.sleep_until in rig/clock.py
                    if (
                        py_file == real_clock_path
                        and self.current_class == "RealClock"
                        and self.current_func == "sleep_until"
                    ):
                        return
                    violations.append(
                        f"{rel_path}:{node.lineno} calls sleep in "
                        f"{self.current_class or ''}.{self.current_func or ''}"
                    )
                self.generic_visit(node)

        SleepVisitor().visit(tree)

    assert not violations, (
        "Forbidden time.sleep found (only RealClock.sleep_until may sleep):\n"
        + "\n".join(violations)
    )


def test_data_acquisition_and_program_executor_retired():
    """
    DataAcquisition and ProgramExecutor modules no longer exist and nothing imports them.
    """
    assert not (PACKAGE_ROOT / "core" / "data_acquisition.py").exists(), (
        "t8_daq_system/core/data_acquisition.py must be deleted"
    )
    assert not (PACKAGE_ROOT / "control" / "program_executor.py").exists(), (
        "t8_daq_system/control/program_executor.py must be deleted"
    )


def test_no_tkinter_or_gui_under_control_data_rig_settings():
    """
    Rule 3: No tkinter or gui imports under control/, data/, rig/, settings/.
    """
    forbidden_roots = ("tkinter", "t8_daq_system.gui", "gui")
    pure_subpackages = ("control", "data", "rig", "settings")
    violations = []

    for subpkg in pure_subpackages:
        subpkg_dir = PACKAGE_ROOT / subpkg
        if not subpkg_dir.exists():
            continue
        for py_file in _iter_python_files(subpkg_dir):
            rel_path = py_file.relative_to(REPO_ROOT)
            for lineno, mod_name in _get_imports(py_file):
                for f_root in forbidden_roots:
                    if mod_name == f_root or mod_name.startswith(f"{f_root}."):
                        violations.append(f"{rel_path}:{lineno} imports {mod_name}")

    assert not violations, "Forbidden GUI imports in pure logic packages:\n" + "\n".join(violations)


def test_practice_mode_identifier_only_under_rig_and_gui_toggle():
    """
    Rule 5: The identifier `practice_mode` appears only under `rig/` and in
    `gui/main_window.py`'s toggle handler (`_toggle_practice_mode`).
    """
    violations = []
    main_window_path = Path("t8_daq_system/gui/main_window.py")

    for py_file in _iter_python_files(PACKAGE_ROOT):
        rel_parts = py_file.relative_to(PACKAGE_ROOT).parts
        rel_path = py_file.relative_to(REPO_ROOT)

        if rel_parts[0] == "rig":
            continue

        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))

        is_main_window = (rel_path == main_window_path)

        class Visitor(ast.NodeVisitor):
            def __init__(self):
                self.current_func: str | None = None

            def visit_FunctionDef(self, node: ast.FunctionDef):
                old_func = self.current_func
                self.current_func = node.name
                self.generic_visit(node)
                self.current_func = old_func

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
                old_func = self.current_func
                self.current_func = node.name
                self.generic_visit(node)
                self.current_func = old_func

            def check_name(self, name: str, lineno: int):
                if name in ("practice_mode", "_practice_mode"):
                    if is_main_window and self.current_func == "_toggle_practice_mode":
                        return
                    violations.append(f"{rel_path}:{lineno} has identifier {name!r}")

            def visit_Name(self, node: ast.Name):
                self.check_name(node.id, node.lineno)
                self.generic_visit(node)

            def visit_Attribute(self, node: ast.Attribute):
                self.check_name(node.attr, node.lineno)
                self.generic_visit(node)

            def visit_arg(self, node: ast.arg):
                self.check_name(node.arg, node.lineno)
                self.generic_visit(node)

        Visitor().visit(tree)

    assert not violations, (
        "Identifier practice_mode appears outside rig/ and main_window.py:_toggle_practice_mode:\n"
        + "\n".join(violations)
    )


def test_no_silent_exceptions():
    """
    Rule 7: No `except` handler whose body is only `pass` or `...` anywhere
    under `t8_daq_system/` (AGENTS.md §12.1 item 6, ADR 0003, Ticket 15).
    """
    violations = []

    def is_silent_body(body: list[ast.stmt]) -> bool:
        if not body:
            return True
        return all(
            isinstance(stmt, ast.Pass)
            or (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value is ...
            )
            for stmt in body
        )

    for py_file in _iter_python_files(PACKAGE_ROOT):
        rel_path = py_file.relative_to(REPO_ROOT)
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if is_silent_body(node.body):
                    exc_name = ast.unparse(node.type) if node.type else "bare"
                    violations.append(f"{rel_path}:{node.lineno} except {exc_name}")

    assert not violations, (
        "Forbidden silent except handler(s) found under t8_daq_system/:\n"
        + "\n".join(violations)
    )



def test_no_program_run_in_gui():
    """No file under t8_daq_system/gui/ contains the text _program_run."""
    import pathlib
    gui_dir = pathlib.Path("t8_daq_system/gui")
    for file_path in gui_dir.glob("**/*.py"):
        content = file_path.read_text(encoding="utf-8")
        assert "_program_run" not in content, f"{file_path} contains forbidden text '_program_run'"

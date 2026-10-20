"""S8 code health: no dead functions in run_farm.py, and the test time budget.

MEASURED 2 Nov: of the 556 functions and classes defined in scripts/run_farm.py
(top level and nested inside main()), one was never referenced anywhere:
_resources_resting, left behind on 26 Sep (8021f72c) when its one caller
switched to _rest_left. pyflakes does not report an unused function, so this
test does: a def whose name is never loaded, used as an attribute or named in
a string in run_farm.py fails here. Dunder methods are called by Python.
"""
from __future__ import annotations

import ast
import pathlib
import re

import hivemind

ROOT = pathlib.Path(hivemind.__file__).resolve().parents[2]
CONFTEST = ROOT / "tests" / "conftest.py"


def dead_defs(source: str) -> list[str]:
    tree = ast.parse(source)
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            used.update(re.findall(r"\w+", node.value))
    return sorted(node.name for node in ast.walk(tree)
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and node.name not in used
                  and not (node.name.startswith("__") and node.name.endswith("__")))


def test_dead_defs_finds_an_unused_function():
    src = "def used():\n    pass\n\ndef unused():\n    pass\n\nused()\n"
    assert dead_defs(src) == ["unused"]


def test_run_farm_has_no_dead_functions():
    found = dead_defs((ROOT / "scripts/run_farm.py").read_text())
    assert not found, f"defined in run_farm.py but never used: {found}"


def test_slow_tests_are_reported_not_failed():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_s8_conftest", CONFTEST)
    conf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conf)

    class Report:
        def __init__(self, when, duration, nodeid):
            self.when, self.duration, self.nodeid = when, duration, nodeid

    lines: list[str] = []

    class Terminal:
        def write_sep(self, sep, title):
            lines.append(title)

        def write_line(self, line):
            lines.append(line)

    conf.pytest_terminal_summary(Terminal())
    assert lines == []                                   # nothing slow: silent
    conf.pytest_runtest_logreport(Report("call", 0.2, "t::fast"))
    conf.pytest_runtest_logreport(Report("setup", 60.0, "t::fixture"))
    conf.pytest_runtest_logreport(Report("call", conf.TEST_BUDGET_S + 1, "t::slow"))
    conf.pytest_runtest_logreport(Report("call", conf.TEST_BUDGET_S + 9, "t::slower"))
    conf.pytest_terminal_summary(Terminal())
    assert "2 test(s) over" in lines[0]
    assert lines[1].endswith("t::slower") and lines[2].endswith("t::slow")

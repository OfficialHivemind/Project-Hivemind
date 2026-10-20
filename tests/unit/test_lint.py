"""Names that shadow names, imports nobody uses: caught here, not in a live run.

MEASURED 2026-09-22 19:38-19:41, attempts 234-236: the bot joined the private
server three times and crashed three times on the same line --

    token_tracker = Tracker()
    TypeError: Tracker.__init__() missing 1 required positional argument: 'locator'

`scripts/run_farm.py` imported `vision.tracks.Tracker` and, eight lines later,
`vision.whereami.Tracker`; the second silently replaced the first. 1,682 unit
tests were green, because none of them import the script. pyflakes reports
exactly this ("redefinition of unused 'Tracker'") and was already installed in
the venv; it had simply never been run over the scripts.

So this test runs it, over `src/` and `scripts/`, and fails on any finding. The
cost is under two seconds. The alternative was three wasted joins.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGETS = ("src", "scripts")


def _pyflakes_available() -> bool:
    return subprocess.run([sys.executable, "-m", "pyflakes", "--version"],
                          capture_output=True).returncode == 0


@pytest.mark.skipif(not _pyflakes_available(), reason="pyflakes is not installed")
def test_pyflakes_finds_nothing_in_src_or_scripts():
    done = subprocess.run([sys.executable, "-m", "pyflakes", *TARGETS],
                          cwd=ROOT, capture_output=True, text=True)
    findings = [line for line in (done.stdout + done.stderr).splitlines() if line.strip()]
    assert not findings, "pyflakes:\n  " + "\n  ".join(findings)


def test_run_farm_imports_no_name_twice():
    """The specific fault, checked without pyflakes: every name bound by a
    top-level import in run_farm.py is bound exactly once."""
    import ast
    tree = ast.parse((ROOT / "scripts/run_farm.py").read_text())
    bound: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                bound[name] = bound.get(name, 0) + 1
    twice = sorted(n for n, c in bound.items() if c > 1)
    assert not twice, f"imported more than once at top level: {twice}"


# NEW TESTS FIND THE CODE THROUGH THE PACKAGE (2026-10-19). The deploy gate runs
# tests from the LIVE tree with the new code on PYTHONPATH, so a test that finds
# scripts/, src/ or data/ by Path(__file__) reads the old live copy and fails
# the gate on a correct change -- it refused 4 deploys on 19 Oct. Locate the repo
# with Path(hivemind.__file__).parents[2]. The files below did it before this
# rule (some read screenshots that only the live tree has) and are left alone.
GRANDFATHERED = set("""test_beemenu.py test_benchmark.py test_boostwindow.py test_cannon.py test_crab_sight.py test_dapper_talk.py test_gameguard.py test_hive.py test_home_from_fix.py test_honey_bee_own_walk.py test_honey_short_rate.py test_hud_earning.py test_layering.py test_lint.py test_memory_bounds.py test_memorymatch_play.py test_merge_coin_review.py test_mob_drops.py test_patterns_natro.py test_planter_switch.py test_pollen_big_slash.py test_settings_effect.py test_telegram_tab.py""".split())


def test_no_would_line_opens_on_a_clause_that_can_be_empty():
    """A look-only "... would: " string glued straight to `(x if c else "")`
    prints "would: and ..." when c is false (run-1250.log:90, the claim retry
    line). Put both clauses in the sentence instead."""
    import ast
    src_root = pathlib.Path(__import__("hivemind").__file__).resolve().parents[2]

    def parts(node):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return parts(node.left) + parts(node.right)
        if isinstance(node, ast.JoinedStr):
            return [v.value if isinstance(v, ast.FormattedValue) else v for v in node.values]
        return [node]

    def can_be_empty(node):
        return isinstance(node, ast.IfExp) and any(
            isinstance(b, ast.Constant) and b.value == "" for b in (node.body, node.orelse))

    bad = []
    for top in TARGETS:
        for f in sorted((src_root / top).rglob("*.py")):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if not isinstance(node, (ast.BinOp, ast.JoinedStr)):
                    continue
                seq = parts(node)
                for a, b in zip(seq, seq[1:]):
                    if (isinstance(a, ast.Constant) and isinstance(a.value, str)
                            and a.value.rstrip().endswith("would:") and can_be_empty(b)):
                        bad.append(f"{f.relative_to(src_root)}:{a.lineno}")
    assert not bad, f"'would:' followed by a clause that can be empty: {sorted(set(bad))}"


def test_new_tests_find_the_repo_through_the_package():
    import re
    here = pathlib.Path(__import__("hivemind").__file__).resolve().parents[2] / "tests" / "unit"
    bad = []
    for f in sorted(here.glob("test_*.py")):
        if f.name in GRANDFATHERED:
            continue
        text = f.read_text(errors="ignore")
        if "Path(__file__)" in text and re.search(r"[\"']scripts[\"'/]|/ [\"']src[\"']|scripts/|[\"']data[\"']", text):
            bad.append(f.name)
    assert not bad, f"use Path(hivemind.__file__).resolve().parents[2], not Path(__file__): {bad}"

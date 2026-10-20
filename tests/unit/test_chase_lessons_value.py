"""tools/analysis/chase_lessons.py --detour-cost and --value: the evidence
the shadow value chooser (tokenbrain VALUE_CHOOSER) needs before going live."""
from __future__ import annotations

import importlib.util
import json
import math
import pathlib

import hivemind

TOOL = pathlib.Path(hivemind.__file__).resolve().parents[2] / "tools" / "analysis" / "chase_lessons.py"


def tool():
    spec = importlib.util.spec_from_file_location("chase_lessons", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def lesson(x, outcome="nothing", evidence="", before=None, during=None):
    return {"attempt": 7, "x": x, "y": 669, "kind": "honey", "outcome": outcome,
            "evidence": evidence, "rate_before": before, "rate_during": during,
            "px": math.hypot(x - 960, 0)}


def test_detour_cost_is_one_minus_the_median_rate_kept(capsys):
    rows = [lesson(1200, before=1000.0, during=d) for d in (200.0, 400.0, 600.0)]
    rows.append(lesson(1200, outcome="collected", before=1000.0, during=5000.0))
    assert tool().detour_cost(rows) == 0
    assert "LOSS_FRACTION = 0.60" in capsys.readouterr().out


def test_value_joins_the_would_line_to_the_chase_it_followed(tmp_path, capsys):
    (tmp_path / "night").mkdir()
    (tmp_path / "night" / "run-7.log").write_text(
        "  1:00:00  token brain: chase honey#3 at (1660, 669) — top\n"
        "  1:00:00  token brain value would: skip honey at (1660, 669) (-9/s: worth 1, "
        "detour 3.4s, gather 50,000/s, risk 0.10) -- the score chases\n"
        "  1:00:05  token brain: hold — nothing\n"
        "  1:00:09  token brain: chase honey#4 at (1100, 669) — top\n"
        "  1:00:09  token brain value would: chase honey at (1100, 669) (+9/s: worth 1, "
        "detour 1.9s, gather 50,000/s, risk 0.04)\n", encoding="utf-8")
    rows = [lesson(1660, "collected", "honey rose 70,000 in 3.0s against 2,000 expected from the trickle"),
            lesson(1100)]
    assert tool().value(rows, tmp_path) == 0
    out = capsys.readouterr().out
    assert "2 joined" in out
    skip = next(ln for ln in out.splitlines() if ln.strip().startswith("skip"))
    assert "100.0%" in skip and "20,000" in skip            # 68,000 over 3.4 s


def test_detour_cost_drops_a_chase_inside_the_last_ones_rate_window(capsys):
    rows = [lesson(1200, before=1000.0, during=d) for d in (200.0, 400.0, 900.0)]
    for r, at in zip(rows, (0.0, 100.0, 110.0)):     # the third began 10 s after the second
        r["at"] = at
    assert tool().detour_cost(rows) == 0
    assert "2 chases" in capsys.readouterr().out

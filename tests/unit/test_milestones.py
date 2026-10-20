"""The progression proof: telemetry/milestones, tools/progression_report and
the new-account gaps it found (docs/pending/progression-proof.md)."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
from datetime import datetime

from hivemind.brain.decide import Planner
from hivemind.brain.fieldnotes import FieldNotes
from hivemind.telemetry import milestones as ms

ROOT = pathlib.Path(__import__("hivemind").__file__).resolve().parents[2]

# the bot's own lines, as the run logs print them (var/night/run-*.log)
LINES = {
    "buying at the Mountain Top Shop: bought it — 'Hive Slot | 2.0B Honey | Buy for":
        ("bought", "Hive Slot for 2.0B Honey"),
    "buying a Basic Egg: bought it — 'Basic Egg | 10.000.000 Honey | Buy fo":
        ("bought", "Basic Egg for 10.000.000 Honey"),
    "egg hatch: answered Yes to 'hatch basic egg'; the count read 2 -> 1":
        ("hatched", "basic egg"),
    "royal jelly: 2 rolled on the cell at (1141, 292); it now holds the Shocked Bee":
        ("jelly", "Shocked Bee"),
    "a dialogue was read at the Polar Bear, so it leaves the hand-in queue until":
        ("quest", "Polar Bear"),
    "badges: collected 2 complete badge(s); the page is kept in /nowhere/x":
        ("badge", "2"),
    "the Blender: collected the finished 7 Blue Extract": ("crafted", "7 Blue Extract"),
    "goals: the Hive Slot (bee 38) is ready to buy at the Mountain Top Shop for 5":
        ("goal_ready", "Hive Slot (bee 38)"),
}


def test_the_bots_lines_are_matched():
    for line, (kind, what) in LINES.items():
        got = ms.match(line)
        assert got and got[:2] == (kind, what), line
    for line in ("buying a Basic Egg: not now — economy.buy is off",
                 "royal jelly: 0 rolled", "egg hatch would: hatch the held Basic Egg",
                 "buying a Basic Egg would: buy one for 1,000 honey"):
        assert ms.match(line) is None, line


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def write(path, body):
    path.write_text(json.dumps(body), encoding="utf-8")


def test_recorder_rows_frames_and_files(tmp_path):
    var = tmp_path / "var"
    var.mkdir()
    live = tmp_path / "live.jpg"
    live.write_bytes(b"jpg")
    write(var / "bees.json", {"total": 4, "verified": True, "gifted": []})
    write(var / "balance.json", {"honey": 5_000})
    said = []
    clock = Clock(os.path.getmtime(live) + 5)
    rec = ms.Recorder(var, live, emit=said.append, clock=clock)
    # the first line: its row, then the files' first look = the baseline
    row = rec.see(next(iter(LINES)))
    assert row["kind"] == "bought" and row["proof"] == "proven"
    assert pathlib.Path(row["frame"]).exists() and row["frame_age_s"] == 5.0
    kinds = [r["kind"] for r in ms.rows(var)]
    assert kinds == ["bought", "baseline"]
    # a quest hand-in is an inference: likely however fresh the frame
    clock.t += 1
    line = "a dialogue was read at the Black Bear, so it leaves the hand-in queue"
    assert rec.see(line)["proof"] == "likely"
    # a stale live frame is no proof
    clock.t += ms.FRESH_S + 10
    assert rec.see("the Blender: collected the finished 1 Glue")["proof"] == "likely"
    # a goal said twice is one row
    goal = "goals: the Bubble Mask is ready to buy at the Blue HQ for 1"
    assert rec.see(goal) and rec.see(goal) is None
    # the files: 4 -> 6 bees opens the 5-bee fields; a gifted type; honey 10^6
    write(var / "bees.json", {"total": 6, "verified": True, "gifted": ["basic"]})
    write(var / "balance.json", {"honey": 1_200_000})
    got = rec.check()
    kinds = [r["kind"] for r in got]
    assert kinds[0] == "bees" and got[0]["what"] == "4 -> 6 bees"
    assert "field_gate" in kinds and "gifted" in kinds and kinds[-1] == "honey"
    assert all("(5 bees)" in r["what"] for r in got if r["kind"] == "field_gate")
    assert rec.check() == []                    # nothing new, nothing written
    # the day after: yesterday's summary is said once
    clock.t += 86400
    rec.check()
    assert any(s.startswith("progress proof: ") and " proven by a frame" in s for s in said)


def test_recorder_never_raises(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("x")
    said = []
    rec = ms.Recorder(blocked, None, emit=said.append)   # var root is a file
    assert rec.see(next(iter(LINES))) is None
    assert any("could not keep a row" in s for s in said)


def test_run_log_dating_steps_back_over_midnight(tmp_path):
    log = tmp_path / "run-1.log"
    log.write_text("    23:59:50  a\nnoise\n    00:00:10  b\n", encoding="utf-8")
    end = datetime(2026, 10, 26, 0, 0, 20).timestamp()
    os.utime(log, (end, end))
    (a_at, a), (b_at, b) = ms.dated_lines(log)
    assert (a, b) == ("a", "b") and b_at - a_at == 20


def test_report_backfill(tmp_path):
    spec = importlib.util.spec_from_file_location("progression_report",
                                                  ROOT / "tools" / "progression_report.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    var = tmp_path / "var"
    (var / "night").mkdir(parents=True)
    (var / "shoplook").mkdir()
    log = var / "night" / "run-1.log"
    log.write_text("    07:25:41  buying at the Mountain Top Shop: bought it — 'Hive Slot | "
                   "283.309.237 Honey | Buy'\n    07:30:00  the hive: 36 bees (26 blue)\n",
                   encoding="utf-8")
    end = datetime(2026, 10, 4, 7, 30, 0).timestamp()
    os.utime(log, (end, end))
    (var / "shoplook" / "20261004-072541-mts-bought.jpg").write_bytes(b"x")
    rows = tool.backfill(var)
    assert [r["kind"] for r in rows] == ["bought", "bees"]
    assert rows[0]["proof"] == "proven" and rows[0]["frame"].endswith("mts-bought.jpg")
    assert rows[1]["proof"] == "likely"
    text = tool.report(rows, var, "t")
    assert "| bought | 1 | 1 |" in text and "PROVEN" in text


def test_bee_gates_take_the_bee_menus_count():
    """Gap F1: a new hive grown to 6 bees is past the 5-bee gate before it
    has gathered in any 5-bee field."""
    fields = {"sunflower": {"bees_required": 0}, "bamboo": {"bees_required": 5}}
    p = Planner(fields, FieldNotes(), reachable=set(fields))
    assert p.bees_at_least() == 0
    p.bees_read = lambda: 6
    assert p.bees_at_least() == 6
    p.bees_read = lambda: None
    assert p.bees_at_least() == 0


def test_new_account_eggs_ship_look_only():
    """Gap F2: buying and hatching for a new hive's free cells says 'would'."""
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert re.search(r"^FREE_CELL_EGGS_LIVE = False$", src, re.M)
    assert "buying a Basic Egg would:" in src and "egg hatch would:" in src


def test_stats_page_lists_the_rows(tmp_path):
    from hivemind.gui.panels.proof import page_html
    assert page_html(tmp_path).startswith("Nothing recorded yet")
    ms.Recorder(tmp_path, None).record("hatched", "basic egg", "the game asked")
    text = page_html(tmp_path)
    assert "hatched: basic egg" in text and "LIKELY" in text and "(no frame)" in text

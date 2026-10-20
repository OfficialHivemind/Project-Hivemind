"""brain/itemreport: the item report and the rare drops, on RECORDED reads --
counts in the shape of var/inventory.json "reads" (values altered),
with times rebuilt in local time so a day is a day in any timezone."""
from __future__ import annotations

import json
import time
from pathlib import Path

from hivemind.brain import itemreport as ir

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]


def _at(stamp: str) -> float:
    return time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M"))


# the shape of measured reads, values altered ("-": that read did not count it)
STAMPS = ["2026-01-04 21:59", "2026-01-05 18:43", "2026-01-05 20:04", "2026-01-05 20:26",
          "2026-01-05 20:52", "2026-01-05 23:51", "2026-01-06 00:54", "2026-01-06 01:57",
          "2026-01-06 03:02", "2026-01-06 03:52"]
RECORDED = {
    "strawberry": [12051, 2155, "-", "-", 2227, 12307, 12325, "-", "-", 2405],
    "royal_jelly": [5, 5, 30, 1, 1, 2, 2, 22, 5, 5],
    "tickets": [157, 207, 209, 209, 209, 218, 218, 224, 230, 235],
    "neonberry": [40, 40, 40, 40, 40, 40, 41, 41, 41, 41],
    "diamond_egg": [2] * 10,
}


def _reads(rows=RECORDED, stamps=STAMPS):
    return [[_at(s), {k: v[i] for k, v in rows.items() if v[i] != "-"}]
            for i, s in enumerate(stamps)]


def test_a_dropped_digit_is_not_a_spend():
    pts = ir.series(_reads())["strawberry"]
    # 2155 and 2227 (a "1" lost from 12,155 / 12,227) gone; 2405 waits for a read
    assert [n for _t, n in ir.settled(pts)] == [12051, 12307, 12325]
    day = ir.by_day(_reads())
    assert day["2026-01-05"]["strawberry"] == [256, 0]      # the naive diff: +10,152 / -9,896
    assert day["2026-01-06"]["strawberry"] == [18, 0]       # naive: +18 / -9,920


def test_a_one_read_jump_is_not_a_gain_and_real_moves_stay():
    rj = [n for _t, n in ir.settled(ir.series(_reads())["royal_jelly"])]
    assert 30 not in rj and 22 not in rj and rj[-1] == 5
    # a real spend of this size stays (e.g. tickets 288 -> 374 -> 35 -> 44 -> 53)
    pts = [(float(i), n) for i, n in enumerate([288, 374, 35, 44, 53, 53])]
    assert [n for _t, n in ir.settled(pts)] == [288, 374, 35, 44, 53]
    assert ir.by_day(_reads())["2026-01-05"]["tickets"] == [61, 0]


def test_report_text_lists_the_day_and_says_when_unread(tmp_path):
    path = tmp_path / "inventory.json"
    assert "not been read" in ir.report_text(path)
    path.write_text(json.dumps({"items": {"tickets": {"count": 235, "label": "Ticket"}},
                                "reads": _reads()}))
    text = ir.report_text(path, "2026-01-05")
    assert text.startswith("Items 2026-01-05") and "Ticket +61" in text
    assert "Strawberry +256" in text and "-9," not in text
    assert "no change confirmed" in ir.report_text(path, "2026-01-01")


def test_a_rare_drop_is_told_once_by_the_read_that_confirms_it():
    rare = {"neonberry": "Neonberry", "diamond_egg": "Diamond Egg"}
    reads = _reads()
    told = [(i, ir.rare_drops(reads[:i], rare)) for i in range(1, len(reads) + 1)]
    told = [(i, t) for i, t in told if t]
    # 40 -> 41 at read 7 (00:54), told at read 8 (01:57) when it held
    assert told == [(8, [("neonberry", 1, 41)])]


def test_a_rare_misread_is_never_told():
    rare = {"diamond_egg": "Diamond Egg"}
    rows = {"diamond_egg": [2, 2, 3, 2, 2, 2, 2, 2, 2, 2]}
    reads = _reads(rows)
    assert not any(ir.rare_drops(reads[:i], rare) for i in range(1, len(reads) + 1))


def test_rare_lines_carry_the_item_and_count_only(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"reads": _reads()[:8]}))
    assert ir.rare_lines(path, {"neonberry": "Neonberry"}) == ["rare drop: +1 Neonberry (now 41)"]


def test_the_rare_list_loads_with_the_menus_spellings():
    rare = ir.load_rare()
    assert rare["star_jelly"] == "Star Jelly" and rare["mythic_egg"] == "Mythic Egg"
    assert "diamond_egg" in rare and "neonberry" in rare
    # never a bare word another row contains ("Treat" inside "Star Treat" is fine:
    # the read matches a line's name exactly)
    assert all(label.strip() == label and label for label in rare.values())


def test_telegram_sends_the_rare_drop_line(tmp_path):
    import importlib.util
    import os
    import tempfile
    os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
    spec = importlib.util.spec_from_file_location("tg_itemrep", ROOT / "scripts" / "telegram_alerts.py")
    tg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tg)
    on = tmp_path / "settings.yaml"
    on.write_text("telegram.alerts: true\n")
    line = "    01:57:52  rare drop: +1 Neonberry (now 41)"
    assert tg.triage(line, {}, 0.0, on) == ("telegram.alerts", False,
                                             "Rare drop: +1 Neonberry (now 41)")
    off = tmp_path / "off.yaml"
    off.write_text("telegram.alerts: false\n")
    assert tg.triage(line, {}, 0.0, off) is None


def test_the_stats_page_shows_each_day(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from hivemind.gui.panels import items
    assert "No inventory read yet" in items.page_html(tmp_path)
    (tmp_path / "inventory.json").write_text(json.dumps({"reads": _reads()}))
    page = items.page_html(tmp_path)
    assert "<h3>2026-01-05</h3>" in page and "Strawberry +256" in page

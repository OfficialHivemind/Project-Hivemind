"""X3 Sticker Printer and X4 Honeystorm: priced errands, look-only."""
from __future__ import annotations

import re
from pathlib import Path

import hivemind
from hivemind.act import errands
from hivemind.brain import value

ROOT = Path(hivemind.__file__).resolve().parents[2]


def test_both_are_look_only_and_never_pressed():
    assert errands.HONEYSTORM_LIVE is False and errands.STICKER_PRINTER_LIVE is False
    assert not {"honeystorm", "sticker_printer"} & errands.FREE_TO_USE
    # no recon or errand walks there: not in run_farm's PLACE_ROUTES order
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    order = src[src.index('for _node in ("sticker_stack",'):]
    order = order[:order.index("if f\"natro_out_{_node}\"")]
    assert '"honeystorm"' not in order and '"sticker_printer"' not in order


def test_the_table_and_the_routes():
    table = errands.load(ROOT / "data" / "knowledge" / "errands.yaml")
    assert table["honeystorm"].every_hours == 4.0
    assert table["sticker_printer"].every_hours == 1.0
    assert table["sticker_printer"].bees_required == 25
    assert errands.gate(table["sticker_printer"], 24)
    assert not errands.gate(table["sticker_printer"], 34)
    routes = (ROOT / "data" / "world" / "natro_paths.yaml").read_text(encoding="utf-8")
    for name in ("natro_out_honeystorm", "natro_out_sticker_printer"):
        assert re.search(rf"^- name: {name}$", routes, re.M), name
    assert errands.PLACE_SETTINGS["honeystorm"] == "economy.honeystorm"
    assert errands.PLACE_SETTINGS["sticker_printer"] == "economy.sticker_printer"


def test_their_panels_name_them():
    assert errands.names_place("honeystorm", "Summon a Honeystorm")
    assert errands.names_place("sticker_printer", "Use the Sticker Printer (12:03)")
    assert not errands.names_place("sticker_printer", "Add a Sticker to the Sticker Stack")


def test_the_prices():
    storm = value.payout("honeystorm", 34)
    assert storm == 8409 + 2 / 22 * value.PRICES["ticket"]
    # measured payouts (B2) replace the honey
    assert value.payout("honeystorm", 34, 20_000.0) == 20_000 + 2 / 22 * value.PRICES["ticket"]
    printer = value.payout("sticker_printer", 34)
    assert printer == 1.93 * value.PRICES["ticket"] - value.PRICES["basic_egg"]
    assert printer < 0                       # a 10M egg for ~2 tickets of reward


def test_the_planner_skips_both_at_todays_rate():
    rate = 29_352.0                          # var/benchmark.json 105.7M honey/h
    rows = [value.score("honeystorm", bees=34, p=None, seconds=6 + 0.0483 * 629 + 20 + 70,
                        rho=rate),
            value.score("sticker_printer", bees=34, p=None, seconds=6 + 0.0483 * 1997 + 10 + 70,
                        rho=rate)]
    first, seq, skipped = value.plan(rows, rate)
    assert first is None and not seq and {r.name for r in skipped} == {"honeystorm", "sticker_printer"}
    # and at a slow hive's rate the storm pays
    slow = value.score("honeystorm", bees=34, p=0.9, seconds=60, rho=50)
    assert slow.q > 0


def test_the_would_line():
    r = value.score("honeystorm", bees=34, p=None, seconds=126, rho=29_352.0)
    line = errands.would("honeystorm", q=r.q, v=r.v, seconds=r.seconds, rate=29_352.0)
    assert line.startswith("honeystorm would: ")
    assert "would skip it" in line and "HONEYSTORM_LIVE is False" in line
    line = errands.would("sticker_printer", q=None, v=None, seconds=10, rate=1.0)
    assert "unpriced" in line and "BASIC egg" in line

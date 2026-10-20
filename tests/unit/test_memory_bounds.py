"""Long-run memory: containers that grew for as long as the bot ran."""
import json

import numpy as np
import pytest

from hivemind.economy.prices import HONEY, PriceGraph


def test_reobserving_an_exchange_replaces_it():
    """Dashboard.refresh re-observes the same exchanges every 60 s."""
    g = PriceGraph()
    for minute in range(500):
        g.observe_exchange("Ticket", HONEY, 5_000, source="ticket shop", at=minute * 60.0)
        g.observe_shop_price("Treat", 10, at=minute * 60.0)
    assert len(g) == 3
    assert g.price("Ticket", now=500 * 60.0).honey == pytest.approx(5_000)
    g.observe_exchange("Ticket", HONEY, 6_000, source="ticket shop", at=0.0)
    assert g.price("Ticket", now=0.0).honey == pytest.approx(6_000)  # the newest counts


def test_goal_watch_keeps_only_the_fields_the_plan_reads(tmp_path):
    from hivemind.brain.goals import TRIP_FIELDS, Watch
    rows = [{"at": 1000.0 + i, "convert_note": "settled at 1,000 honey",
             "frames": ["x" * 200] * 5, "route": "natro_out_pine_tree"} for i in range(50)]
    (tmp_path / "trips.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    w = Watch.__new__(Watch)
    w.var_root, w._rows_key, w._rows = tmp_path, None, []
    got = w._ledger_rows()
    assert len(got) == 50 and all(set(r) == set(TRIP_FIELDS) for r in got)
    assert got[0]["convert_note"] == "settled at 1,000 honey"


def test_feed_drops_forget_lines_that_have_left_the_feed():
    from hivemind.act import bugrun

    class Book:
        def slug_for(self, name):
            return "mantis"
    t = [0.0]
    drops = bugrun.FeedDrops(Book(), clock=lambda: t[0], line_seconds=10.0)
    for i in range(300):
        t[0] = i * 20.0
        assert drops.seen(f"+{i + 1} Honey (from Mantis)")
    assert len(drops._lines) == 1


def test_locator_history_is_bounded_and_still_counts(monkeypatch):
    from hivemind.vision import whereami
    monkeypatch.setattr(whereami.feed, "strip", lambda frame: frame)
    monkeypatch.setattr(whereami, "field_in", lambda text, known: "pine_tree")
    loc = whereami.Locator(lambda img: "+5 Honey (from Pine Tree Forest)", known={})
    for _ in range(whereami.HISTORY_KEPT + 50):
        loc.look(np.zeros((4, 4, 3), np.uint8))
    assert len(loc.history) == whereami.HISTORY_KEPT
    assert loc.fixes == whereami.HISTORY_KEPT + 50


def test_run_farm_bounds_the_drops_list():
    """bugrun_box["drops"] is a closure in run_farm.main; the bound is a
    source check (the same splice as the run's own `del drops[:-N]`)."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "scripts/run_farm.py").read_text()
    assert "del drops[:-MOB_DROPS_KEPT]" in src
    assert "MOB_DROPS_KEPT = 100" in src

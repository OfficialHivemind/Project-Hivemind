"""ROADMAP V4: the stream overlay shows the progression proof's milestones
(TG7: "new gifted bee", "1B honey") as toasts, and today's time-accounting
pie (P10) as a page of the bottom card."""
from __future__ import annotations

import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


def test_only_new_viewer_news_rows_become_toasts():
    from hivemind.gui.stream_extras import milestone_toasts
    rows = [{"at": 50, "kind": "gifted", "what": "gifted Old Bee"},        # before the window
            {"at": 100, "kind": "baseline", "what": "10 bees"},
            {"at": 110, "kind": "gifted", "what": "gifted Basic Bee"},
            {"at": 120, "kind": "honey", "what": "1,000,000,000 honey (HUD 1,234,567,890)"},
            {"at": 130, "kind": "quest", "what": "Black Bear"}]           # show toasts it already
    toasts, newest = milestone_toasts(rows, after=60)
    assert [(t.kind, t.title, t.body) for t in toasts] == [
        ("milestone", "New gifted bee", "gifted Basic Bee"),
        ("milestone", "Honey milestone", "1,000,000,000 honey")]
    assert newest == 130
    assert milestone_toasts(rows, after=newest)[0] == []


def _extras(tmp_path, pushed):
    from PySide6.QtWidgets import QWidget
    from hivemind.gui.stream_extras import StreamExtras
    view = QWidget()
    ex = StreamExtras(view, push=pushed.append, path=lambda n: tmp_path / n,
                      board=dict, get=lambda k: None, opened_at=time.time() - 5)
    ex.pager(QWidget())
    return ex, view


def test_a_row_written_while_streaming_is_toasted_once(qt_app, tmp_path):
    pushed: list = []
    ex, _view = _extras(tmp_path, pushed)
    ex.progress()                                    # no file yet: nothing, no error
    (tmp_path / "progression").mkdir()
    rows = tmp_path / "progression" / "milestones.jsonl"
    rows.write_text(json.dumps({"at": time.time() - 3600, "kind": "gifted",
                                "what": "gifted Old Bee"}) + "\n"
                    + json.dumps({"at": time.time(), "kind": "bees",
                                  "what": "24 -> 25 bees"}) + "\n", encoding="utf-8")
    ex.progress()
    ex.progress()
    assert [(t.title, t.body) for t in pushed] == [("The hive grew", "24 -> 25 bees")]


def test_the_time_page_draws_the_benchmarks_groups(qt_app):
    from hivemind.gui.stream_extras import TimePage
    page = TimePage()
    assert page.show_time(None) is False
    assert page.show_time({"groups": {"gather": {"s": 0, "pct": 0}}}) is False
    acc = {"running_h": 2.0, "slices": {}, "biggest_non_gather": None,
           "groups": {"gather": {"s": 5400, "pct": 75.0},
                      "walking": {"s": 1800, "pct": 25.0}}}
    assert page.show_time(acc) is True
    assert [s[0] for s in page.pie.slices] == ["gather", "walking"]
    assert page.rows[0]._raw.strip() == "75%  gather"
    assert page.subtitle.text() == "2.0 h running"
    assert "gather" in page.note._raw


def test_time_today_is_the_benchmarks_sum_and_empty_var_gives_no_page(qt_app, tmp_path):
    from hivemind.gui.stream_extras import TimePage, time_today
    acc = time_today(tmp_path, time.time())
    assert "groups" in acc
    assert TimePage().show_time(acc) is False

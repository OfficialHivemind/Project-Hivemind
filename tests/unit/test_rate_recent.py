"""The planner's "recent" rate source (brain/decide._rate_source, brain/ledger)."""
from __future__ import annotations

from hivemind.brain import decide
from hivemind.brain.decide import _rate_source
from hivemind.brain.fieldnotes import Note
from hivemind.brain.ledger import RECENT_SECONDS, RECENT_TRIPS, Ledger

STALE = Note(field="pine_tree", proven=True, visits=40, seconds=100_000.0, pollen=19_000_000,
             paid_seconds=5_800.0, paid_pollen=19_330_000)          # 3,333/s, days old


def _trips(n, per_second, seconds_each=430.0):
    return {"pollen": 0, "seconds": 0.0, "trips": 0, "recent_trips": n,
            "recent_pollen": int(per_second * seconds_each * n), "recent_seconds": seconds_each * n}


def test_the_latest_trips_win_over_a_stale_pair():
    rate, source = _rate_source(STALE, trips=_trips(10, 9_481))
    assert source == "recent" and round(rate) == 9_481


def test_too_few_recent_trips_keep_the_old_order():
    rate, source = _rate_source(STALE, trips=_trips(decide.RECENT_TRIPS_ENOUGH - 1, 9_481))
    assert source == "paid" and round(rate) == 3_333
    rate, source = _rate_source(STALE, trips=_trips(10, 9_481, seconds_each=100.0))
    assert source == "paid"                               # under RECENT_SECONDS_ENOUGH


def test_the_ledger_totals_the_last_trips_alone(tmp_path):
    rows = [{"at": float(i), "credited": "pine_tree", "pollen": 1000 * (i + 1),
             "gather_seconds": 200.0} for i in range(15)]
    got = Ledger(tmp_path / "trips.jsonl").pollen_by_field(rows=rows)["pine_tree"]
    assert got["trips"] == 15 and got["recent_trips"] == RECENT_TRIPS == 10
    assert got["recent_pollen"] == sum(1000 * (i + 1) for i in range(5, 15))
    assert got["recent_seconds"] == 2000.0


def test_short_trips_reach_back_until_they_cover_the_bar(tmp_path):
    # Mountain Top, 2026-10-20: ten bag-full trips of ~165 s cover 1,645 s,
    # under RECENT_SECONDS, and the planner fell back to a 3,158/s lifetime
    # pair against the trips' ~30,000/s. The window takes whole older trips.
    rows = [{"at": float(i), "credited": "mountain_top", "pollen": 5_000_000,
             "gather_seconds": 165.0} for i in range(122)]
    got = Ledger(tmp_path / "trips.jsonl").pollen_by_field(rows=rows)["mountain_top"]
    assert got["recent_trips"] == 11 and got["recent_seconds"] >= RECENT_SECONDS
    stale = Note(field="mountain_top", proven=True, seconds=44_079.0, pollen=5_300_000,
                 paid_seconds=1_686.0, paid_pollen=5_324_000)       # 3,158/s
    rate, source = _rate_source(stale, trips=got)
    assert source == "recent" and round(rate) == round(5_000_000 / 165.0)
    # too few trips altogether still leaves the old order
    few = Ledger(tmp_path / "trips.jsonl").pollen_by_field(rows=rows[:3])["mountain_top"]
    assert few["recent_trips"] == 3 and _rate_source(stale, trips=few)[1] == "paid"


def test_the_why_keeps_the_shape_the_stream_reads():
    from hivemind.stream.voice import because_of
    said = because_of("measured 9,481 pollen/s over its last 10 trips here (3616s of gathering)")
    assert "9,500" in said or "9,481" in said

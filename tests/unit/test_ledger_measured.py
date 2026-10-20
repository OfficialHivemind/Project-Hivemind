"""The ledger's rate counts the seconds of trips whose honey was measured."""
from hivemind.brain.ledger import Ledger


def test_unmeasured_trips_add_no_seconds_to_the_rate(tmp_path):
    ledger = Ledger(path=tmp_path / "ledger.jsonl")
    rows = [{"honey": 5_000_000, "seconds": 600.0, "gather_seconds": 400.0, "passes": 20,
             "credited": "pine_tree", "converted": True},
            {"honey": None, "seconds": 600.0, "gather_seconds": 400.0, "passes": 20,
             "credited": "pine_tree", "converted": True}]
    t = ledger.totals(rows=rows)
    assert t.earning_seconds == 600.0
    assert t.honey_per_hour == 5_000_000 * 6.0

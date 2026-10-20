"""U3: the Why page replays a trip with its decision, legs and frames."""
import json
import os
import time

from hivemind.gui.panels import whytrips


def test_trip_replay_has_decision_legs_and_frames(tmp_path):
    now = time.time()
    trip = {"at": now, "seconds": 600, "attempt": 7, "credited": "cactus", "ok": True,
            "chosen": "cactus", "chosen_by": "planner", "action": "gather",
            "candidates": [{"field": "rose", "score": 10, "why": "lower"},
                           {"field": "cactus", "score": 99, "why": "measured 10,685 pollen/s"}],
            "route_choice": {"chosen": "via_cannon", "why": "landed 10 of 10"},
            "routes": [{"kind": "flight", "route": "via_cannon", "outcome": "landed",
                        "seconds": 18}],
            "gather_seconds": 500, "pollen": 1234, "gather_ended": "bag full",
            "convert_note": "converted"}
    old = dict(trip, at=now - 5000, attempt=6)
    (tmp_path / "trips.jsonl").write_text(
        "not json\n" + json.dumps(old) + "\n" + json.dumps(trip) + "\n")
    inc = tmp_path / "incidents" / "20261102-101010-mob-sighting"
    inc.mkdir(parents=True)
    (inc / "149_t+10.0s.jpg").write_bytes(b"x")
    (inc / "reason.txt").write_text("mob-sighting")
    os.utime(inc / "reason.txt", (now - 60, now - 60))

    rows = whytrips.trips(tmp_path)
    assert [r["attempt"] for r in rows] == [7, 6]      # newest first, bad line skipped
    page = whytrips.trip_html(tmp_path, rows[0])
    assert page.index("cactus score 99") < page.index("rose score 10")
    for want in ("measured 10,685 pollen/s", "landed 10 of 10", "<b>landed</b>",
                 "bag full", "converted", "mob-sighting", "149_t%2B10.0s.jpg"):
        assert want in page
    assert "No frames" in whytrips.trip_html(tmp_path, rows[1])   # incident is after it


def test_empty_var_says_so(tmp_path):
    assert "No trips recorded yet" in whytrips.page_html(tmp_path)

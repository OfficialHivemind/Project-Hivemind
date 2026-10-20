"""brain/questvalue.one_plan (ROADMAP B20 step 5, shadow): the finished quests'
hand-ins and the places priced in ONE brain/value.plan."""
from __future__ import annotations

from hivemind.brain import questvalue as qv
from hivemind.brain import value

TABLE = {qv._key("Variety Fetcher 2"): ("black_bear", {"honey": 125_000_000}),
         qv._key("Scorpion Salad"): ("polar_bear", {"honey": 160_000})}
DONE = ["Collect 100,000,000 Pollen from the Pepper Patch. Complete!"]


def test_a_big_finished_quest_beats_a_place_and_an_unmeasured_walk_is_left_out():
    rows = qv.ranked([{"name": "Variety Fetcher 2", "requirements": DONE},
                      {"name": "Polar Bear: Scorpion Salad", "requirements": DONE},
                      {"name": "Unread", "requirements": []}], TABLE)
    assert [r.done for r in rows] == [True, True, False]       # no lines read: not done
    walks = {"black_bear": (0.9, 40.0), "polar_bear": (0.9, None)}
    clock = value.score("wealth_clock", bees=40, p=0.9, seconds=50, rho=8000)
    first, seq, _skipped = qv.one_plan([clock], rows, walks.get, 8000.0)
    assert first.name == "hand_in_black_bear" and first.v == 125e6
    assert "hand_in_polar_bear" not in [r.name for r in seq]   # no measured seconds
    line = qv.would(first, "wealth_clock")
    assert line.startswith("B20 would: hand in black bear") and "wealth clock" in line
    assert qv.would(first, "hand_in_black_bear") == ""
    assert qv.ONE_PLAN_LIVE is False


def test_a_small_hand_in_loses_to_gathering():
    rows = qv.ranked([{"name": "Polar Bear: Scorpion Salad", "requirements": DONE}],
                     {qv._key("Scorpion Salad"): ("polar_bear", {"honey": 10_000})})
    first, _seq, skipped = qv.one_plan([], rows, lambda g: (0.9, 60.0), 8000.0)
    assert first is None and [r.name for r in skipped] == ["hand_in_polar_bear"]

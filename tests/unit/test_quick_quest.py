"""A quest step one trip finishes goes first (brain/decide QUICK_QUEST_SHARE).

2026-09-28/29: "Collect 150,000 Pollen from the Strawberry Field" read 0/150,000
all night while Pine Tree's rate won every trip.
"""
from __future__ import annotations

from hivemind.brain.decide import QUICK_QUEST_SHARE, TRIP_SECONDS, Planner, Situation
from hivemind.brain.fieldnotes import FieldNotes, Note


class Needs:
    """The part of brain/questneeds the planner asks."""
    def __init__(self, fields):
        self._fields = dict(fields)

    def field_remaining(self, name):
        return self._fields.get(name, 0)

    def mobs_wanted(self):
        return {}

    def remaining(self, colour):
        return 0


def _planner(owed, walk_home=("strawberry", "pine_tree")):
    notes = FieldNotes()
    for name, rate in (("strawberry", 1500), ("pine_tree", 3000)):
        notes.notes[name] = Note(field=name, proven=True, visits=3, seconds=900.0,
                                 pollen=rate * 900, paid_seconds=900.0, paid_pollen=rate * 900)
    fields = {"strawberry": {"flowers": 400, "mobs": []},
              "pine_tree": {"flowers": 400, "mobs": []}}
    p = Planner(fields, notes, reachable={"strawberry", "pine_tree"},
                walk_home=set(walk_home))
    p.quest_needs = Needs({"strawberry": owed})
    return p


def test_a_quest_step_one_trip_finishes_goes_first():
    ranked = _planner(150_000).rank(Situation(pollen=0, capacity=3_000_000))
    assert ranked[0].field == "strawberry", [(s.field, s.score) for s in ranked]
    assert "one trip finishes it" in ranked[0].why
    # the owner's setting is not what put it there, and it is not said to be
    assert "quests.first" not in ranked[0].why
    # and run_farm watches that trip for the step being gathered
    assert ranked[0].quick_quest and not ranked[1].quick_quest


def test_not_where_the_trip_ends_in_a_rejoin():
    # the rejoin costs the Wealth Clock streak: the owner's to spend
    ranked = _planner(150_000, walk_home=("pine_tree",)).rank(
        Situation(pollen=0, capacity=3_000_000))
    assert ranked[0].field == "pine_tree"
    assert all("one trip finishes it" not in s.why for s in ranked)


def test_the_owners_setting_still_says_so():
    p = _planner(150_000)
    p.quest_first = True
    ranked = p.rank(Situation(pollen=0, capacity=3_000_000))
    assert ranked[0].field == "strawberry"
    assert "quests.first" in ranked[0].why and "one trip finishes it" not in ranked[0].why
    assert not ranked[0].quick_quest


def test_a_bigger_step_keeps_the_tilt_alone():
    big = int(1500 * TRIP_SECONDS * QUICK_QUEST_SHARE) + 1
    ranked = _planner(big).rank(Situation(pollen=0, capacity=3_000_000))
    assert ranked[0].field == "pine_tree"
    assert "one trip finishes it" not in ranked[1].why


def test_no_quest_no_change():
    ranked = _planner(0).rank(Situation(pollen=0, capacity=3_000_000))
    assert ranked[0].field == "pine_tree"


def test_the_voice_says_why():
    from hivemind.stream.voice import because_of
    why = ("measured 1,500 pollen/s over 900s here; a quest wants 150,000 more pollen from here "
           "specifically; a quest needs only 150,000 more pollen from here — about 2 min, one trip "
           "finishes it, so it goes first")
    said = because_of(why)
    assert said == "A quest needs only 150,000 more pollen from there, so one trip finishes it"


def test_with_quests_first_a_step_one_trip_finishes_goes_before_a_long_one():
    # MEASURED 2026-10-06 09:05: Sunflower owed 37,752 (the Polar Bear), the
    # Strawberry Field 12.3M (Star Journey 2), both put first by the setting --
    # here the faster field owes the long step and still goes second
    p = _planner(0)
    p.quest_needs = Needs({"strawberry": 150_000, "pine_tree": 12_000_000})
    p.quest_first = True
    ranked = p.rank(Situation(pollen=0, capacity=3_000_000))
    assert [s.field for s in ranked[:2]] == ["strawberry", "pine_tree"], \
        [(s.field, s.score, s.why) for s in ranked]
    assert ranked[0].one_trip and not ranked[1].one_trip
    assert "before the other quest fields" in ranked[0].why
    # the owner's setting put both first; the quick flag stays its own rule's
    assert not ranked[0].quick_quest


def test_a_step_one_trip_finishes_never_lifts_a_field_out_of_reach():
    p = _planner(0)
    p.quest_needs = Needs({"strawberry": 150_000, "pine_tree": 12_000_000})
    p.quest_first = True
    p.reachable = {"pine_tree"}
    ranked = p.rank(Situation(pollen=0, capacity=3_000_000))
    assert ranked[0].field == "pine_tree"

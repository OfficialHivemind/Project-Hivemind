"""Q1: a field given up on gets another trip for a quest when its route lands now
(brain/decide QUEST_RETRY_P_LAND, QUEST_ROUTE_RETRIES).

MEASURED 2026-10-12: the Polar Bear's "Collect 150,000 Pollen from the Strawberry
Field" sat at 142,592/150,000 from 16:31 to 19:59 while every trip scored
Strawberry 0 ("failed to arrive 4 trips in a row") and its flight landed 2 of 2.
"""
from __future__ import annotations

import time

from hivemind.brain.decide import (QUEST_RETRY_AFTER_S, QUEST_ROUTE_RETRIES, TRAVEL_FAILURES_TO_GIVE_UP,
                                   Planner, Situation)
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


def _planner(owed=7_408, p_land=0.75, failures=TRAVEL_FAILURES_TO_GIVE_UP):
    notes = FieldNotes()
    for name, rate in (("strawberry", 3_495), ("pine_tree", 26_601)):
        notes.notes[name] = Note(field=name, proven=True, visits=3, seconds=900.0,
                                 pollen=rate * 900, paid_seconds=900.0,
                                 paid_pollen=rate * 900)
    notes.notes["strawberry"].travel_failures = failures
    fields = {"strawberry": {"flowers": 400, "mobs": []},
              "pine_tree": {"flowers": 400, "mobs": []}}
    p = Planner(fields, notes, reachable={"strawberry", "pine_tree"},
                walk_home={"strawberry", "pine_tree"})
    p.quest_needs = Needs({"strawberry": owed})
    p.route_odds = lambda name: (p_land, "") if name == "strawberry" else (0.92, "")
    return p


def _rank(p):
    return p.rank(Situation(pollen=0, capacity=3_000_000))


def test_a_quest_field_whose_route_lands_now_gets_another_trip():
    ranked = _rank(_planner())
    top = ranked[0]
    assert top.field == "strawberry", [(s.field, s.score, s.why) for s in ranked]
    assert top.reachable and top.score > 0 and top.quick_quest
    assert "so it gets another trip" in top.why and "P 0.75" in top.why


def test_today_unchanged_without_a_quest_a_landing_route_or_the_odds():
    for p in (_planner(owed=0), _planner(p_land=0.49), _planner(p_land=0.33)):
        straw = next(s for s in _rank(p) if s.field == "strawberry")
        assert straw.score == 0.0 and not straw.reachable
        assert "failed to arrive" in straw.why
    p = _planner()
    p.route_odds = None                    # not wired (tests, a script): today's ban
    straw = next(s for s in _rank(p) if s.field == "strawberry")
    assert straw.score == 0.0 and "failed to arrive" in straw.why


def test_a_retry_that_got_nowhere_lets_the_ban_stand():
    p = _planner(failures=TRAVEL_FAILURES_TO_GIVE_UP + QUEST_ROUTE_RETRIES)
    p.notes.notes["strawberry"].failed_at = time.time() - 60.0
    straw = next(s for s in _rank(p) if s.field == "strawberry")
    assert straw.score == 0.0 and "failed to arrive" in straw.why


def test_an_old_miss_gets_one_more_trip_when_the_route_lands_now():
    # MEASURED 2026-10-18/19: Bamboo banned at 5 since 18 Oct 01:12, its flight
    # landing 8 of 10, two quests owing it -- 25 h of trips scored it 0
    p = _planner(failures=TRAVEL_FAILURES_TO_GIVE_UP + QUEST_ROUTE_RETRIES)
    p.notes.notes["strawberry"].failed_at = time.time() - QUEST_RETRY_AFTER_S - 60.0
    straw = next(s for s in _rank(p) if s.field == "strawberry")
    assert straw.reachable and straw.score > 0 and "gets another trip" in straw.why
    p = _planner(failures=9, p_land=0.33)                # a route that misses: still shut
    p.notes.notes["strawberry"].failed_at = time.time() - QUEST_RETRY_AFTER_S - 60.0
    straw = next(s for s in _rank(p) if s.field == "strawberry")
    assert straw.score == 0.0 and "failed to arrive" in straw.why


def test_even_odds_earn_the_retry():
    """2026-10-20: Bamboo and Strawberry sat at exactly 0.50, and a strict
    'over 0.5' kept their bans (and the quests behind them) shut for good."""
    straw = next(s for s in _rank(_planner(p_land=0.5)) if s.field == "strawberry")
    assert straw.reachable and straw.score > 0 and "so it gets another trip" in straw.why


def _recent(rate):
    from hivemind.brain import decide
    s = max(decide.RECENT_SECONDS_ENOUGH, 1000.0)
    return {"recent_trips": decide.RECENT_TRIPS_ENOUGH, "recent_seconds": s,
            "recent_pollen": rate * s}


def test_a_given_up_field_near_our_best_gets_a_trip_for_its_honey():
    """2026-10-20 22:12: Bamboo at 29,165/s recent, banned, no quest owing it."""
    p = _planner(owed=0)
    trips = {"strawberry": _recent(29_000), "pine_tree": _recent(25_500)}
    p._read_trips = lambda: None
    p._trips_for = lambda name: trips.get(name)
    straw = next(s for s in _rank(p) if s.field == "strawberry")
    assert straw.reachable and straw.score > 0, straw.why
    assert "for its honey" not in straw.why and "near our best" in straw.why


def test_a_given_up_field_well_below_our_best_stays_shut():
    p = _planner(owed=0)
    trips = {"strawberry": _recent(5_000), "pine_tree": _recent(25_500)}
    p._read_trips = lambda: None
    p._trips_for = lambda name: trips.get(name)
    straw = next(s for s in _rank(p) if s.field == "strawberry")
    assert not straw.reachable and "failed to arrive" in straw.why


def test_a_big_quest_debt_gets_a_daily_probe_under_even_odds():
    # MEASURED 2026-10-21: Pepper landed P 0.33 and 180M of its pollen held two
    # quests with no trip in 7 days (decide.QUEST_PROBE_*)
    from hivemind.brain.decide import QUEST_PROBE_AFTER_S, QUEST_PROBE_MIN_OWED
    p = _planner(owed=QUEST_PROBE_MIN_OWED, p_land=0.33)
    p.notes.notes["strawberry"].failed_at = time.time() - QUEST_PROBE_AFTER_S - 60.0
    straw = next(s for s in _rank(p) if s.field == "strawberry")
    assert straw.reachable and straw.score > 0 and "one probe trip" in straw.why
    # a miss inside the day, or a small debt: the ban stands
    for owed, ago in ((QUEST_PROBE_MIN_OWED, 3600.0), (QUEST_PROBE_MIN_OWED - 1, QUEST_PROBE_AFTER_S + 60)):
        p = _planner(owed=owed, p_land=0.33)
        p.notes.notes["strawberry"].failed_at = time.time() - ago
        straw = next(s for s in _rank(p) if s.field == "strawberry")
        assert straw.score == 0.0 and "failed to arrive" in straw.why

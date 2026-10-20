"""Q2: a quest's field, given up on, gets ONE trial trip when its route has not
been judged in its present shape (brain/decide QUEST_ROUTE_TRIAL,
Planner.route_window, fieldnotes Note.failed_at).

MEASURED 2026-10-12: the Brown Bear's "Collect 2,200,000 Pollen from the Coconut
Field" read 82,133/2,200,000 while Coconut stayed given up on from 10-06 17:50;
its walk's window started afresh 10-09 12:21 (run-811, the new walkspeed) and has
held no verdict since, so Q1's posterior (P 0.5) never let it back.
"""
from __future__ import annotations

import hivemind.brain.decide as decide
from hivemind.brain.decide import TRAVEL_FAILURES_TO_GIVE_UP, Planner, Situation
from hivemind.brain.fieldnotes import FieldNotes, Note

CHANGED = 1_791_520_902.0      # 2026-10-09, a run's fresh window


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


def _planner(owed=2_117_867, verdicts=0, since=CHANGED):
    notes = FieldNotes()
    for name, rate in (("coconut", 3_000), ("pine_tree", 26_601)):
        notes.notes[name] = Note(field=name, proven=True, visits=3, seconds=900.0,
                                 pollen=rate * 900, paid_seconds=900.0,
                                 paid_pollen=rate * 900)
    notes.notes["coconut"].travel_failures = TRAVEL_FAILURES_TO_GIVE_UP  # undated
    fields = {"coconut": {"flowers": 400, "mobs": []},
              "pine_tree": {"flowers": 400, "mobs": []}}
    p = Planner(fields, notes, reachable=set(fields), walk_home=set(fields))
    p.quest_needs = Needs({"coconut": owed})
    # JUST UNDER EVEN ODDS, so Q1's "lands now" retry (QUEST_RETRY_P_LAND, made
    # inclusive at 0.5 on 2026-10-20, 4c0683a) stays out and this file tests Q2's
    # trial alone. At exactly 0.5 the Q1 clause took these cases first: red on
    # main from 20 Oct until the Windows Claude's test run found it (2026-10-21).
    p.route_odds = lambda name: (0.45, "") if name == "coconut" else (0.92, "")
    p.route_window = lambda name: (verdicts, since) if name == "coconut" else (10, 0.0)
    return p, notes


def _coconut(p):
    ranked = p.rank(Situation(pollen=0, capacity=3_000_000))
    return next(s for s in ranked if s.field == "coconut")


def test_a_route_not_judged_since_it_changed_gets_one_trial():
    for since, words in ((CHANGED, "not been judged since it changed"),
                         (0.0, "never been judged")):
        got = _coconut(_planner(since=since)[0])
        assert got.reachable and got.score > 0, got.why
        assert words in got.why and "one trial trip" in got.why


def test_the_ban_stands_without_a_quest_an_empty_window_the_hook_or_the_switch(monkeypatch):
    def banned(p):
        got = _coconut(p)
        assert got.score == 0.0 and not got.reachable and "failed to arrive" in got.why
    banned(_planner(owed=0)[0])
    banned(_planner(verdicts=2)[0])        # judged since (1 of 2 is P 0.5): Q1's to rule
    p, _ = _planner()
    p.route_window = None                  # not wired (tests, a script): today's ban
    banned(p)
    monkeypatch.setattr(decide, "QUEST_ROUTE_TRIAL", False)
    banned(_planner()[0])


def test_a_trial_that_got_nowhere_waits_for_the_route_to_change_again(tmp_path):
    p, notes = _planner()
    notes.travel_failed("coconut", at=CHANGED + 3_600)     # the trial got nowhere
    got = _coconut(p)
    assert got.score == 0.0 and "failed to arrive 5 trips" in got.why
    p.route_window = lambda name: (0, CHANGED + 7_200) if name == "coconut" else (10, 0.0)
    assert "one trial trip" in _coconut(p).why             # re-transpiled since
    notes.save(tmp_path / "notes.json")
    back = FieldNotes()
    back.load(tmp_path / "notes.json")
    assert back.known("coconut").failed_at == CHANGED + 3_600
    notes.arrived("coconut")                               # a landing lifts the ban
    got = _coconut(p)
    assert got.score > 0 and "given up" not in got.why

"""Reliability 2026-10-19b: a mis-delivered trip to a field given up on uses its
quest retry (fieldnotes.missed_it give_up), and gumdrops are not thrown where the
feed names another field (run_farm throw_a_gumdrop).

MEASURED run-1085: the Bamboo retry landed in Spider at 12:11, and the next plan
sent the same retry again; 41 gumdrops went "in the bamboo" while the feed named
Spider and Mushroom.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import hivemind
from hivemind.brain.decide import (QUEST_RETRY_AFTER_S, QUEST_ROUTE_RETRIES,
                                   TRAVEL_FAILURES_TO_GIVE_UP, Planner, Situation)
from hivemind.brain.fieldnotes import FieldNotes, Note

ROOT = Path(hivemind.__file__).resolve().parents[2]


class Needs:
    def field_remaining(self, name):
        return 16_700_226 if name == "bamboo" else 0

    def mobs_wanted(self):
        return {}

    def remaining(self, colour):
        return 0


def _planner(failures):
    notes = FieldNotes()
    for name, rate in (("bamboo", 29_165), ("pineapple", 7_959)):
        notes.notes[name] = Note(field=name, proven=True, visits=3, seconds=900.0,
                                 pollen=rate * 900, paid_seconds=900.0, paid_pollen=rate * 900)
    notes.notes["bamboo"].travel_failures = failures
    notes.notes["bamboo"].failed_at = time.time() - QUEST_RETRY_AFTER_S - 60.0
    fields = {"bamboo": {"flowers": 400, "mobs": []}, "pineapple": {"flowers": 400, "mobs": []}}
    p = Planner(fields, notes, reachable={"bamboo", "pineapple"},
                walk_home={"bamboo", "pineapple"})
    p.quest_needs = Needs()
    p.route_odds = lambda name: (0.58, "")
    return p


def _bamboo(p):
    return next(s for s in p.rank(Situation(pollen=0, capacity=8_861_738))
                if s.field == "bamboo")


def test_a_mis_delivered_retry_uses_the_retry():
    p = _planner(TRAVEL_FAILURES_TO_GIVE_UP + QUEST_ROUTE_RETRIES)
    assert _bamboo(p).score > 0                      # the 6 h retry is due
    p.notes.missed_it("bamboo", give_up=TRAVEL_FAILURES_TO_GIVE_UP)
    b = _bamboo(p)
    assert b.score == 0.0 and not b.reachable, b.why
    assert p.notes.notes["bamboo"].missed == 1


def test_a_field_not_given_up_on_is_still_never_barred():
    p = _planner(1)
    p.notes.missed_it("bamboo", give_up=TRAVEL_FAILURES_TO_GIVE_UP)
    assert p.notes.notes["bamboo"].travel_failures == 1 and _bamboo(p).score > 0


def test_run_farm_wires_both():
    farm = (ROOT / "scripts" / "run_farm.py").read_text()
    assert "notes.missed_it(aimed, give_up=TRAVEL_FAILURES_TO_GIVE_UP)" in farm
    body = farm[farm.index("def throw_a_gumdrop"):]
    body = body[:body.index("hotbar_press(")]
    assert re.search(r"notes\.field_since\(began\) not in \(None, field\):\s*\n\s*return", body)


def _weak_quest_best():
    """run_farm's `weak_quest_best`, read from the source (run_farm is a script)."""
    farm = (ROOT / "scripts" / "run_farm.py").read_text()
    share = re.search(r"^QUEST_WEAK_SHARE = ([0-9.]+)$", farm, re.M).group(1)
    start = farm.index("def weak_quest_best(")
    src = farm[start:farm.index("\ndef ", start + 1)]
    ns = {"QUEST_WEAK_SHARE": float(share)}
    exec(src, ns)
    return ns["weak_quest_best"]


def test_a_weak_quest_field_gives_way_to_the_best_field_not_the_best_safe_one():
    # run-1025 16 Oct 03:17: Rose put first at 5,973/s, Pine Tree top at ~25k/s
    # (not "safe": it has mobs), Dandelion the only safe field at ~2,500/s
    from hivemind.brain.decide import FieldScore
    best_of = _weak_quest_best()
    alts = [FieldScore("rose", 9_000.0, rate=5_973.0, quest_first=True, safe=False),
            FieldScore("pine_tree", 25_153.0, rate=25_775.0, safe=False),
            FieldScore("dandelion", 2_508.0, rate=2_500.0, safe=True),
            FieldScore("bamboo", 0.0, rate=29_165.0, reachable=False, safe=False)]
    assert best_of(alts, "rose").field == "pine_tree"
    assert best_of(alts, "pine_tree") is None                      # not a quest pick
    alts[0] = FieldScore("rose", 9_000.0, rate=9_000.0, quest_first=True)
    assert best_of(alts, "rose") is None                           # not under the share

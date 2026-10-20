"""The value chooser (tokenbrain VALUE_CHOOSER, shadow): honey a second.

MEASURED 2026-10-21 (runs 1120-1167): detours take 1.9-3.4 s by px, 4-10%
of walks home reverse and end chasing for the trip, a reached far token is
taken ~30% of the time. A honey token far away costs more gathering than it
pays; an unnamed one near pays on a weak field. It only logs (`shadow`).
"""
from __future__ import annotations

import copy
import pathlib

import hivemind

from hivemind.brain import tokenbrain as tb
from hivemind.brain.tokenbrain import TokenBrain
from hivemind.vision.tracks import Track

ANCHOR = (960, 670)
ROOT = pathlib.Path(hivemind.__file__).resolve().parents[2]


def track(tid, dx, kind):
    return Track(id=tid, x=ANCHOR[0] + dx, y=ANCHOR[1], kind=kind, first_seen=0.0,
                 last_seen=0.0, matches=3, detector_confidence=0.9)


def cand(dx, kind):
    return next(c for c in TokenBrain().score([track(1, dx, kind)], ANCHOR, ANCHOR, 0.0)
                if not c.is_return)


def test_a_far_honey_token_is_skipped():
    c = cand(700, "honey")
    assert 0.25 < c.trace["x reach"] * 0.98 < 0.35           # reach ~0.3
    # with no trip-end risk at all: the detour alone costs more than it pays
    assert tb.value_per_second(c, 20_000.0, chase_value_left=0.0) < 0


def test_a_far_token_worth_a_lot_still_pays():
    c = cand(700, "honey")
    old = dict(tb.VALUE_HONEY)
    try:
        tb.VALUE_HONEY["honey"] = 10_000_000.0
        assert tb.value_per_second(c, 57_000.0) > 0
    finally:
        tb.VALUE_HONEY.clear()
        tb.VALUE_HONEY.update(old)


def test_a_near_unknown_token_is_chased_on_a_weak_field():
    assert tb.value_per_second(cand(250, "unknown"), 20_000.0) > 0


def test_the_worst_case_loss_skips_even_a_near_token_on_pine():
    # ~57k honey/s gathering and every detour second lost: nothing pays
    assert tb.value_per_second(cand(250, "unknown"), 57_000.0) < 0


def test_the_trip_end_risk_costs_more_far():
    assert tb.trip_end_risk(700) > tb.trip_end_risk(300) > tb.trip_end_risk(100)
    assert tb.detour_s(100) < tb.detour_s(450) < tb.detour_s(700)


def test_shadow_leaves_the_decision_and_the_commitment_alone():
    brain = TokenBrain()
    tracks = [track(1, 700, "honey"), track(2, 250, "unknown")]
    d = brain.decide(tracks, ANCHOR, ANCHOR, 0.0)
    before, committed = copy.deepcopy(d), brain.committed
    line = tb.shadow(d, 20_000.0)
    assert line.startswith("chase unknown at (1210, 670)")
    assert brain.committed == committed
    assert d.action == before.action and d.target == before.target
    assert [c.score for c in d.ranked] == [c.score for c in before.ranked]
    assert tb.shadow(d, 200_000.0).startswith("skip ")


def test_shadow_says_nothing_without_an_eligible_token():
    d = TokenBrain().decide([], ANCHOR, ANCHOR, 0.0)
    assert tb.shadow(d, 20_000.0) == ""


def test_run_farm_logs_the_value_chooser():
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert "token brain value would: " in src and "tokenbrain.shadow(" in src


def test_replay_brain_prints_the_verdict_and_sweeps_the_in_view_gate():
    src = (ROOT / "scripts" / "replay_brain.py").read_text(encoding="utf-8")
    assert "--value" in src and "tokenbrain.shadow(" in src
    assert "--in-view-s" in src and "in_view_s if in_view_s is not None" in src

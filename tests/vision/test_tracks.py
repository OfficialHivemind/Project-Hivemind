"""Tokens remembered between frames. See vision/tracks.py.

A popular macro's public docs describe a "short-lived record" per token --
how often it has been seen, how long it has existed, confirmed after two
matches. These tests hold ours to the same contract, plus the one rule theirs
does not need to state: it never invents a position it did not see.
"""
from __future__ import annotations

from types import SimpleNamespace as S

import pytest

from hivemind.vision import tracks
from hivemind.vision.tracks import Tracker


def sighting(x, y, kind="unknown", confidence=0.8):
    return S(x=x, y=y, kind=kind, confidence=confidence)


def test_a_token_seen_twice_nearby_is_one_track_and_becomes_confirmed():
    t = Tracker()
    t.observe([sighting(500, 400)], now=0.0)
    t.observe([sighting(520, 410)], now=0.3)      # the character walked a step

    live = t.alive(0.3)
    assert len(live) == 1
    assert live[0].matches == 2
    assert live[0].confirmed
    assert (live[0].x, live[0].y) == (520, 410), "the position follows the latest sighting"


def test_a_sighting_far_from_any_track_is_a_new_token():
    t = Tracker()
    t.observe([sighting(500, 400)], now=0.0)
    t.observe([sighting(900, 400)], now=0.3)      # 400 px away: a different token

    live = t.alive(0.3)
    assert len(live) == 2
    assert all(not x.confirmed for x in live)


def test_one_sighting_cannot_claim_two_tracks_nor_two_sightings_one_track():
    t = Tracker()
    t.observe([sighting(500, 400), sighting(560, 400)], now=0.0)   # two tokens, 60 px apart
    t.observe([sighting(505, 402), sighting(565, 401)], now=0.3)

    live = t.alive(0.3)
    assert len(live) == 2, [x.describe() for x in live]
    assert all(x.matches == 2 for x in live), [x.describe() for x in live]


def test_a_single_match_is_not_confirmed():
    """One match is a bee, a bubble or a glint; two is a thing."""
    t = Tracker()
    (only,) = t.observe([sighting(500, 400)], now=0.0)

    assert not only.confirmed
    assert only.match_confidence() == pytest.approx(0.5)
    assert t.confirmed(0.0) == []


def test_it_forgets_what_it_has_not_seen_for_a_while():
    t = Tracker(forget_after=2.0)
    t.observe([sighting(500, 400)], now=0.0)
    t.observe([sighting(500, 400)], now=0.1)          # confirmed

    assert len(t.alive(1.9)) == 1
    assert t.alive(2.2) == [], "a token unseen for longer than the limit is gone"


def test_a_camera_turn_clears_the_memory_rather_than_mismatching():
    t = Tracker()
    t.observe([sighting(500, 400)], now=0.0)
    t.observe([sighting(510, 400)], now=0.2)
    assert t.confirmed(0.2)

    t.turned()

    assert t.alive(0.2) == []
    assert t.turns == 1


def test_age_and_unseen_time_are_reported_not_guessed():
    t = Tracker()
    t.observe([sighting(500, 400)], now=10.0)
    t.observe([sighting(500, 400)], now=10.5)
    (only,) = t.alive(12.0)

    assert only.age(12.0) == pytest.approx(2.0)
    assert only.unseen_for(12.0) == pytest.approx(1.5)


def test_a_track_never_moves_without_being_seen():
    """The last seen position is kept and the gap is reported, never
    interpolated -- a position the tracker did not observe is a guess."""
    t = Tracker(forget_after=10.0)
    t.observe([sighting(500, 400)], now=0.0)
    t.observe([sighting(500, 400)], now=0.1)          # confirmed: a thing, not a glint
    t.observe([], now=1.0)
    t.observe([], now=2.0)
    (only,) = t.alive(2.0)

    assert (only.x, only.y) == (500, 400)
    assert only.unseen_for(2.0) == pytest.approx(1.9)


def test_the_kind_is_a_vote_and_unknown_never_outvotes_a_name():
    t = Tracker()
    t.observe([sighting(500, 400, kind="haste")], now=0.0)
    t.observe([sighting(502, 401, kind="unknown")], now=0.2)
    t.observe([sighting(504, 402, kind="unknown")], now=0.4)
    (only,) = t.alive(0.4)

    assert only.kind == "haste", only.seen_kinds


def test_the_detectors_best_confidence_is_kept():
    t = Tracker()
    t.observe([sighting(500, 400, confidence=0.55)], now=0.0)
    t.observe([sighting(500, 400, confidence=0.91)], now=0.2)
    t.observe([sighting(500, 400, confidence=0.60)], now=0.4)
    (only,) = t.alive(0.4)

    assert only.detector_confidence == pytest.approx(0.91)


def test_observe_returns_only_what_this_frame_touched():
    t = Tracker(forget_after=10.0)
    t.observe([sighting(500, 400)], now=0.0)
    touched = t.observe([sighting(900, 400)], now=0.5)   # the first token was not seen

    assert [x.x for x in touched] == [900]
    assert len(t.alive(0.5)) == 2, "the unseen one is remembered, not returned"


def test_describe_is_honest_about_counts():
    t = Tracker()
    t.observe([sighting(500, 400), sighting(900, 400)], now=0.0)
    t.observe([sighting(500, 400)], now=0.2)

    said = t.describe(0.2)
    assert "2 token(s) remembered" in said and "1 confirmed" in said


# --- carrying the memory with the ground -------------------------------------
#
# MEASURED 2026-09-22 (runs 237-239): one 0.35 s step slides the ground about
# 90 px on screen, which is the whole match gate, so a walking character
# un-matched every near token each look. The odometer that lived here, read
# off the matched tokens' shifts, saw only the far ones and reported +2..+28 px
# for those steps; it has moved to vision/flow, where the ground is measured
# directly, and the tracker is now TOLD how far the ground moved.

def test_the_ground_shift_carries_every_remembered_token_before_matching():
    t = Tracker()
    t.observe([sighting(500, 400), sighting(900, 400)], now=0.0)
    # the character walked right: the ground (and every token on it) slid
    # 120 px left, past the 90 px gate
    touched = t.observe([sighting(380, 400), sighting(780, 400)], now=0.3,
                        scene_shift=(-120.0, 0.0))

    assert sorted(tr.id for tr in touched) == [1, 2], "the same two tokens, not two new ones"
    assert all(tr.matches == 2 for tr in touched)
    assert t.shifted == 1


def test_without_a_shift_a_120px_slide_is_two_new_tokens():
    """The honest failure the shift exists to prevent -- kept so the gate's
    meaning is pinned down."""
    t = Tracker()
    t.observe([sighting(500, 400)], now=0.0)
    touched = t.observe([sighting(380, 400)], now=0.3)
    assert [tr.id for tr in touched] == [2]
    assert len(t.alive(0.3)) == 2


def test_an_unseen_track_is_carried_too_and_keeps_its_last_seen_time():
    t = Tracker(forget_after=10.0)
    t.observe([sighting(500, 400)], now=0.0)
    t.observe([], now=0.3, scene_shift=(-50.0, 10.0))
    tr = t.alive(0.3)[0]
    assert (tr.x, tr.y) == (450, 410)
    assert tr.last_seen == 0.0, "carrying is not seeing"
    assert tr.unseen_for(0.3) == pytest.approx(0.3)


def test_a_zero_shift_counts_as_no_shift():
    t = Tracker()
    t.observe([sighting(500, 400)], now=0.0)
    t.observe([sighting(500, 400)], now=0.3, scene_shift=(0.0, 0.0))
    assert t.shifted == 0


def test_a_camera_turn_clears_the_memory():
    t = Tracker()
    t.observe([sighting(500, 400)], now=0.0)
    t.turned()
    assert t.alive(0.0) == [] and t.turns == 1


def test_a_single_sighting_is_forgotten_long_before_a_confirmed_token():
    """MEASURED 2026-09-22: 103 tracks alive at t+5 s on a field recording,
    most of them seen once. One sighting is a glint; two is a thing."""
    t = Tracker()
    t.observe([sighting(500, 400), sighting(900, 400)], now=0.0)
    t.observe([sighting(500, 400)], now=0.2)           # only the first recurs
    assert len(t.alive(0.2)) == 2
    assert len(t.alive(1.5)) == 1, "the single sighting should be gone after a second"
    assert t.alive(1.5)[0].confirmed
    assert len(t.alive(4.5)) == 0, "and the confirmed one after the usual four"

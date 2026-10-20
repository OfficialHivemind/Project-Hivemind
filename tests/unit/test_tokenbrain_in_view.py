"""The farm's brain decides only on what its latest look saw (tokenbrain.IN_VIEW_S).

MEASURED 2026-10-01 (the replay in tokenbrain's IN_VIEW_S note): a track the
deciding look had not matched had a sighting the chase could start on in the
next frame 7% of the time, against 72% for one it had. So with `in_view_s`
given, a remembered track is gated -- with its reason -- and the brain picks
from what is on screen now; without it, nothing changes.
"""
from __future__ import annotations

from hivemind.brain import tokenbrain as tb
from hivemind.brain.tokenbrain import TokenBrain
from hivemind.vision.tracks import Tracker


class Seen:
    def __init__(self, x, y, kind="unknown", confidence=0.9):
        self.x, self.y, self.kind, self.confidence = x, y, kind, confidence


ANCHOR = (960, 670)


def two_looks():
    """A and B seen twice; then a look that sees only A."""
    tr = Tracker()
    tr.observe([Seen(600, 500), Seen(1300, 500)], 1.0)
    tr.observe([Seen(600, 500), Seen(1300, 500)], 2.0)
    tr.observe([Seen(600, 500)], 2.5)
    return tr


def by_place(ranked, x):
    return next(c for c in ranked if not c.is_return and c.x == x)


def test_a_track_the_latest_look_missed_is_gated_with_its_reason():
    tr = two_looks()
    brain = TokenBrain(in_view_s=tb.IN_VIEW_S)
    ranked = brain.score(tr.alive(2.5), ANCHOR, ANCHOR, 2.5)
    assert by_place(ranked, 600).gated == ""
    gone = by_place(ranked, 1300)
    assert gone.gated.startswith("not in the latest look (0.5s unseen)")
    assert gone.score == 0.0


def test_without_it_the_staleness_curve_still_judges():
    """Every other user of the brain (the replay tool, the tests) is unchanged."""
    tr = two_looks()
    ranked = TokenBrain().score(tr.alive(2.5), ANCHOR, ANCHOR, 2.5)
    assert by_place(ranked, 1300).gated == ""
    assert by_place(ranked, 1300).score > 0.0


# NEAR scores more than FAR (the distance curve: 340 px from the anchor
# against 655), and both are outside SELF_PX and far apart (no cluster).
NEAR, FAR = (700, 450), (1500, 300)


def test_the_decision_goes_to_what_is_on_screen():
    tr = Tracker()
    # NEAR is the better token, but the latest look lost it.
    tr.observe([Seen(*NEAR), Seen(*FAR)], 1.0)
    tr.observe([Seen(*NEAR), Seen(*FAR)], 2.0)
    tr.observe([Seen(*FAR)], 2.4)
    d = TokenBrain(in_view_s=tb.IN_VIEW_S).decide(tr.alive(2.4), ANCHOR, ANCHOR, 2.4)
    assert d.action == "chase"
    assert (d.target.x, d.target.y) == FAR
    old = TokenBrain().decide(tr.alive(2.4), ANCHOR, ANCHOR, 2.4)
    assert (old.target.x, old.target.y) == NEAR          # what it used to walk at


def test_a_committed_token_that_left_the_view_is_let_go():
    tr = Tracker()
    tr.observe([Seen(*NEAR), Seen(*FAR)], 1.0)
    tr.observe([Seen(*NEAR), Seen(*FAR)], 2.0)
    brain = TokenBrain(in_view_s=tb.IN_VIEW_S)
    first = brain.decide(tr.alive(2.0), ANCHOR, ANCHOR, 2.0)
    assert (first.target.x, first.target.y) == NEAR
    tr.observe([Seen(*FAR)], 3.0)
    then = brain.decide(tr.alive(3.0), ANCHOR, ANCHOR, 3.0)
    assert then.why.startswith("the committed token is gone or no longer eligible")
    assert (then.target.x, then.target.y) == FAR


def test_nothing_in_view_holds():
    tr = Tracker()
    tr.observe([Seen(*FAR)], 1.0)
    tr.observe([Seen(*FAR)], 2.0)
    assert TokenBrain(in_view_s=tb.IN_VIEW_S).decide(
        tr.alive(2.0), ANCHOR, ANCHOR, 2.0).action == "chase"
    tr.observe([], 2.5)
    d = TokenBrain(in_view_s=tb.IN_VIEW_S).decide(tr.alive(2.5), ANCHOR, ANCHOR, 2.5)
    assert d.action == "hold"

"""x reach: how often our own chase got to a token that far at that movespeed.

MEASURED 2026-10-14 (tokenbrain.REACH_BY_SPEED, scripts/token_payoff.py):
4,654 chases since run 820 reached 94% at ~310 px and 31% at ~710 px with no
speed buff, and 79% / 23% under Haste x5 and up.
"""
from __future__ import annotations

import math

import pytest

from hivemind.brain import tokenbrain as tb
from hivemind.brain.tokenbrain import TokenBrain
from hivemind.vision.tracks import Track

ANCHOR = (960, 670)
PRI = {"tabby_love": 1, "unknown": 100}


def pri(kind):
    return PRI.get(kind, 100)


def track(tid, dx, kind="unknown"):
    return Track(id=tid, x=ANCHOR[0] + dx, y=ANCHOR[1], kind=kind, first_seen=0.0,
                 last_seen=0.0, matches=3, detector_confidence=0.9)


def test_reach_falls_with_distance_and_with_speed(monkeypatch):
    assert tb.reach_multiplier(150) == 1.0
    assert tb.reach_multiplier(400) == tb.reach_multiplier(400, 1.0) < 1.0
    assert tb.reach_multiplier(700) < tb.reach_multiplier(400)
    assert tb.reach_multiplier(400, 1.6) < tb.reach_multiplier(400, 1.3) < tb.reach_multiplier(400, 1.0)
    assert tb.reach_multiplier(5_000, 2.0) == 0.0
    monkeypatch.setattr(tb, "REACH", "off")
    assert tb.reach_multiplier(700, 2.0) == 1.0


def test_a_far_coin_is_chased_at_walking_pace_and_held_under_strong_haste():
    """620 px: reached 56% at <1.25x, 36% at >=1.5x -- under the bar there."""
    slow = TokenBrain(pri).decide([track(1, 620)], ANCHOR, ANCHOR, 0.0, {"speed": 1.0})
    fast = TokenBrain(pri).decide([track(1, 620)], ANCHOR, ANCHOR, 0.0, {"speed": 1.6})
    assert slow.action == "chase", slow.describe()
    assert fast.action == "hold", fast.describe()
    assert "x reach" in fast.why


def test_the_owners_first_kinds_are_not_discounted():
    """The sample held honey tokens and unnamed coins only."""
    ranked = TokenBrain(pri).score([track(1, 700, "tabby_love")], ANCHOR, ANCHOR, 0.0, {"speed": 1.8})
    assert ranked[0].trace["x reach"] == 1.0


def test_the_trace_carries_every_factor_of_the_score():
    """`base` times every "x ..." entry is the score: what a "why this token"
    view shows, and a factor left out of the trace fails here."""
    tracks = [track(1, 300), track(2, 450), track(3, 650), track(4, -500, "tabby_love")]
    ranked = TokenBrain(pri).score(tracks, ANCHOR, ANCHOR, 0.0, {"speed": 1.4})
    tokens = [c for c in ranked if not c.is_return and not c.gated]
    assert len(tokens) == 4
    for c in tokens:
        product = c.trace["base"] * math.prod(v for k, v in c.trace.items() if k.startswith("x "))
        assert product == pytest.approx(c.score, rel=0.01), c.describe()
        assert c.trace["speed"] == 1.4

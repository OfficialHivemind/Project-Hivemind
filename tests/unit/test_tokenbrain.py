"""A score, not a script. See brain/tokenbrain.py.

The numbers are seeds where nobody measured one, ours where we measured one,
and an ordering where they are neither -- each test says which.
"""
from __future__ import annotations

import pytest

from hivemind.brain import tokenbrain as tb
from hivemind.brain.tokenbrain import TokenBrain
from hivemind.vision.tracks import Track


def track(tid, x, y, kind="unknown", matches=2, first=0.0, last=None):
    t = Track(id=tid, x=x, y=y, kind=kind, first_seen=first,
              last_seen=first if last is None else last, matches=matches,
              detector_confidence=0.8)
    return t


PRIORITY = {"tabby_love": 1, "scratch": 2, "haste": 10, "unknown": 100}
def pri(kind): return PRIORITY.get(kind, 100)

ANCHOR = (960, 670)
HERE = (960, 670)


# --- the pieces -----------------------------------------------------------------

def test_base_weight_follows_the_priority_ordering():
    """tokens.yaml ranks kinds; the weights keep that order and nothing more."""
    w = {k: tb.base_weight(k, pri) for k in ("tabby_love", "scratch", "haste", "unknown")}
    assert w["tabby_love"] > w["scratch"] > w["haste"] > w["unknown"]
    assert tb.base_weight("never_heard_of", pri) == tb.WEIGHT_BY_PRIORITY[100]


def test_the_distance_curve_has_the_documented_shape():
    """Ceiling inside NEAR, floor past CUTOFF, linear between."""
    assert tb.distance_multiplier(0) == tb.DISTANCE_CEILING
    assert tb.distance_multiplier(tb.NEAR_PX) == tb.DISTANCE_CEILING
    assert tb.distance_multiplier(tb.CUTOFF_PX) == tb.DISTANCE_FLOOR
    assert tb.distance_multiplier(5_000) == tb.DISTANCE_FLOOR
    mid = tb.distance_multiplier((tb.NEAR_PX + tb.CUTOFF_PX) / 2)
    assert tb.DISTANCE_FLOOR < mid < tb.DISTANCE_CEILING
    assert mid == pytest.approx((tb.DISTANCE_CEILING + tb.DISTANCE_FLOOR) / 2)


def test_the_cluster_bonus_is_seeded_and_capped():
    assert tb.cluster_multiplier(0) == 1.0
    assert tb.cluster_multiplier(1) == pytest.approx(1.2)
    assert tb.cluster_multiplier(50) == tb.CLUSTER_CAP


def test_staleness_decays_to_nothing():
    assert tb.staleness_multiplier(0.0) == 1.0
    assert tb.staleness_multiplier(tb.STALE_AFTER_S) == 1.0
    assert 0.0 < tb.staleness_multiplier((tb.STALE_AFTER_S + tb.GONE_AFTER_S) / 2) < 1.0
    assert tb.staleness_multiplier(tb.GONE_AFTER_S) == 0.0


def test_the_pull_home_rises_with_distance_and_is_nothing_at_the_anchor():
    assert tb.return_score(0) == 0.0
    assert tb.return_score(tb.RETURN_NEAR_PX) == 0.0
    near = tb.return_score(tb.RETURN_NEAR_PX + 1)
    far = tb.return_score(tb.RETURN_FAR_PX)
    assert 0 < near < far
    assert far == pytest.approx(tb.RETURN_BASE * tb.RETURN_MULT_FAR)


# --- eligibility -----------------------------------------------------------------

def test_a_token_seen_once_is_gated_not_scored_low():
    """Two vision matches confirm a token. A gate is not a score."""
    brain = TokenBrain(pri)
    ranked = brain.score([track(1, 1200, 600, "haste", matches=1)], ANCHOR, HERE, now=0.0)
    haste = next(c for c in ranked if c.track_id == 1)
    assert haste.gated and "two matches" in haste.gated
    assert haste.score == 0.0


def test_a_high_value_kind_may_be_chased_on_one_sighting():
    """The owner's own priorities are the High Value list."""
    brain = TokenBrain(pri)
    ranked = brain.score([track(1, 1200, 600, "tabby_love", matches=1)], ANCHOR, HERE, now=0.0)
    tabby = next(c for c in ranked if c.track_id == 1)
    assert not tabby.gated
    assert tabby.score > 0


def test_a_measured_expiry_gates_old_tokens_and_an_unknown_one_does_not():
    old = track(1, 1200, 600, "haste", matches=3, first=0.0, last=30.0)
    without = TokenBrain(pri).score([old], ANCHOR, HERE, now=30.0)
    with_expiry = TokenBrain(pri, expiry_s=20.0).score([old], ANCHOR, HERE, now=30.0)
    assert not next(c for c in without if c.track_id == 1).gated, \
        "a guessed expiry would gate real tokens; none is applied until measured"
    assert "lifetime" in next(c for c in with_expiry if c.track_id == 1).gated


# --- picking ----------------------------------------------------------------------

def test_a_better_kind_beats_a_nearer_ordinary_token():
    """Nearest-first picks easy pollen and walks past the token that matters."""
    brain = TokenBrain(pri)
    near_plain = track(1, 1100, 650, "unknown", matches=3)      # ~140 px
    far_tabby = track(2, 1500, 600, "tabby_love", matches=3)    # ~545 px
    d = brain.decide([near_plain, far_tabby], ANCHOR, HERE, now=0.0)
    assert d.action == "chase"
    assert d.target.track_id == 2, d.describe()


def test_a_cluster_is_worth_more_than_a_lone_token_of_the_same_kind():
    brain = TokenBrain(pri)
    lone = track(1, 1400, 650, "haste", matches=3)
    a = track(2, 700, 650, "haste", matches=3)
    b = track(3, 760, 640, "haste", matches=3)
    c = track(4, 720, 700, "haste", matches=3)
    ranked = brain.score([lone, a, b, c], ANCHOR, HERE, now=0.0)
    lone_c = next(x for x in ranked if x.track_id == 1)
    in_cluster = next(x for x in ranked if x.track_id == 2)
    assert in_cluster.score > lone_c.score
    assert in_cluster.trace["x cluster"] > 1.0


def test_nothing_over_the_bar_at_the_anchor_means_hold_not_wander():
    brain = TokenBrain(pri, threshold=1_000.0)     # nothing can clear this
    d = brain.decide([track(1, 1200, 600, "haste", matches=3)], ANCHOR, HERE, now=0.0)
    assert d.action == "hold", d.describe()
    assert brain.committed is None


def test_far_from_the_anchor_with_nothing_worthwhile_it_returns():
    brain = TokenBrain(pri, threshold=1_000.0)
    away = (1700, 650)                                # ~740 px from the anchor
    d = brain.decide([], ANCHOR, away, now=0.0)
    assert d.action == "return", d.describe()
    assert d.target.is_return


# --- commitment -------------------------------------------------------------------

def test_a_committed_target_is_kept_against_a_slightly_better_challenger():
    brain = TokenBrain(pri)
    first = track(1, 1150, 650, "haste", matches=3)
    d1 = brain.decide([first], ANCHOR, HERE, now=0.0)
    assert d1.action == "chase" and brain.committed == 1

    # a second haste appears a little closer: better, but not x1.5 better
    rival = track(2, 1120, 650, "haste", matches=3)
    d2 = brain.decide([first, rival], ANCHOR, HERE, now=0.3)
    assert d2.target.track_id == 1, d2.describe()
    assert brain.interrupts == 0


def test_a_clearly_better_challenger_interrupts_at_the_margin():
    """The ordinary-token margin seed: x1.5."""
    brain = TokenBrain(pri)
    plain = track(1, 1150, 650, "unknown", matches=3)
    brain.decide([plain], ANCHOR, HERE, now=0.0)
    tabby = track(2, 1150, 700, "tabby_love", matches=3)    # same distance, far higher weight
    d = brain.decide([plain, tabby], ANCHOR, HERE, now=0.3)
    assert d.target.track_id == 2, d.describe()
    assert brain.interrupts == 1
    assert "switched" in d.why


def test_a_committed_target_that_vanishes_releases_the_commitment():
    brain = TokenBrain(pri)
    brain.decide([track(1, 1150, 650, "haste", matches=3)], ANCHOR, HERE, now=0.0)
    d = brain.decide([], ANCHOR, HERE, now=0.5)
    assert brain.committed is None
    assert "gone" in d.why


def test_forget_clears_the_commitment():
    brain = TokenBrain(pri)
    brain.decide([track(1, 1150, 650, "haste", matches=3)], ANCHOR, HERE, now=0.0)
    brain.forget()
    assert brain.committed is None


def test_every_decision_carries_its_reasoning():
    """A trace of why a token scored highest -- a decision nobody can read is a decision nobody can tune."""
    brain = TokenBrain(pri)
    d = brain.decide([track(1, 1200, 600, "haste", matches=3),
                      track(2, 1300, 700, "unknown", matches=1)], ANCHOR, HERE, now=0.0)
    lines = [c.describe() for c in d.ranked]
    assert any("base" in l and "x distance" in l for l in lines), lines
    assert any("GATED" in l for l in lines), lines
    assert d.describe()


def test_a_token_on_the_characters_own_body_is_gated_not_chased():
    """MEASURED 2026-09-22 (runs 238-239): blue "tokens" 30-40 px from the
    anchor, chased three times running and still there each time -- the
    character's own shirt."""
    brain = TokenBrain(priority_of=pri)
    here = (960, 669)
    shirt = track(10, 941, 636, kind="fuzz_bombs", matches=3)
    far = track(11, 960 + 300, 669, kind="fuzz_bombs", matches=3)

    ranked = brain.score([shirt, far], here, here, now=1.0)
    by_id = {c.track_id: c for c in ranked if c.track_id is not None}
    assert "own body" in by_id[10].gated, by_id[10].gated
    assert by_id[10].score == 0.0
    assert not by_id[11].gated

    d = brain.decide([shirt], here, here, now=1.0)
    assert d.action == "hold", d.describe()


def test_a_hold_on_a_token_seen_once_or_missed_is_worth_a_second_look():
    """A coin edge-on is missed (a quarter turn in ~0.4 s, vision/coins); live,
    run-734 held 17 of 64 times on such a track (2026-10-07)."""
    brain = TokenBrain(priority_of=pri, in_view_s=tb.IN_VIEW_S)
    once = brain.decide([track(1, 600, 400, matches=1, first=1.0)], ANCHOR, HERE, now=1.0)
    assert once.action == "hold" and tb.worth_a_second_look(once)
    missed = brain.decide([track(2, 600, 400, matches=3, first=0.0, last=0.5)], ANCHOR, HERE, now=1.0)
    assert missed.action == "hold" and tb.worth_a_second_look(missed)
    body = brain.decide([track(3, 965, 660, matches=3, first=1.0)], ANCHOR, HERE, now=1.0)
    assert body.action == "hold" and not tb.worth_a_second_look(body)
    chase = brain.decide([track(4, 600, 400, matches=3, first=1.0)], ANCHOR, HERE, now=1.0)
    assert chase.action == "chase" and not tb.worth_a_second_look(chase)


def test_the_honey_token_ranks_below_an_unnamed_coin():
    """MEASURED 2026-10-07: a field honey token is +300..+7,000 honey, a tenth
    of a second of income; an unnamed coin is mostly an ability token."""
    pri_honey = lambda k: 101 if k == "honey" else PRIORITY.get(k, 100)
    assert tb.base_weight("honey", pri_honey) < tb.base_weight("unknown", pri_honey)
    brain = TokenBrain(priority_of=pri_honey)
    d = brain.decide([track(1, 960 + 300, 670, kind="honey"),
                      track(2, 960 - 420, 670, kind="unknown")], ANCHOR, HERE, now=0.0)
    assert d.action == "chase" and d.target.kind == "unknown"


# --- LIFETIME_GATE_LIVE: gone before we get there ------------------------------

LIFE = {"unknown": 4.0, "honey": 10.0}


def test_a_four_second_token_too_far_and_old_would_be_gated_look_only():
    # 7.5 s old, 400 px: 0.42 + 400/480 = 1.25 s walk, 8.75 > 2 x 4 s
    b = TokenBrain(pri, life_of=LIFE.get)
    d = b.decide([track(1, 960 + 400, 670, first=0.0, last=7.5)], ANCHOR, HERE, now=7.5)
    assert d.action == "chase"                       # look-only: still chased
    assert d.target.would_gate.startswith("gone before we get there")
    assert not d.target.gated


def test_a_track_past_its_token_life_but_inside_twice_it_is_kept():
    # MEASURED 2026-10-27 (TRACK_LIFE_FACTOR): a track outlives its token, and
    # at 1 x life the rule's skips were picked up like any other chase
    b = TokenBrain(pri, life_of=LIFE.get)
    c = b.score([track(1, 960 + 400, 670, first=0.0, last=3.5)], ANCHOR, HERE, now=3.5)[0]
    assert c.would_gate == ""


def test_a_far_honey_token_is_not_leashed():
    # the leash would have skipped 216 chases of 26-27 Oct, 23 HUD-confirmed
    b = TokenBrain(pri, life_of=LIFE.get)
    far = b.score([track(2, 960 + 600, 670, kind="honey", last=1.0)], ANCHOR, HERE, now=1.0)[0]
    assert far.would_gate == ""


def test_live_the_lifetime_rule_gates_and_a_high_value_kind_is_exempt(monkeypatch):
    monkeypatch.setattr(tb, "LIFETIME_GATE_LIVE", True)
    b = TokenBrain(pri, life_of=lambda k: 4.0)
    old = [track(1, 960 + 400, 670, first=0.0, last=7.5)]
    def token(ts):
        return next(c for c in b.score(ts, ANCHOR, HERE, now=7.5) if not c.is_return)
    assert token(old).gated.startswith("gone before")
    assert not token([track(2, 960 + 400, 670, kind="tabby_love", first=0.0, last=7.5)]).gated


def test_without_a_lifetime_table_nothing_would_be_gated():
    c = TokenBrain(pri).score([track(1, 960 + 700, 670, kind="honey", last=9.0)],
                              ANCHOR, HERE, now=9.0)[0]
    assert c.would_gate == ""


# --- COLOUR_LIVE: a colour token is worth only its colour's flowers ------------

def test_colour_factor_is_the_fields_share_of_that_colour_for_the_hive():
    # wiki FieldTable: Pepper 85% red, 15% white, no blue; Pine Tree 85% blue
    assert tb.colour_factor("blue_boost", "pepper", "blue") == 0.0
    assert tb.colour_factor("black_blue_burst", "pepper", "red") == 0.0
    assert tb.colour_factor("red_boost", "pepper", "blue") == pytest.approx(0.93, abs=0.01)
    assert tb.colour_factor("red_boost", "pepper", "") == pytest.approx(0.85)
    assert tb.colour_factor("blue_boost", "pine_tree", "blue") > 0.95
    assert tb.colour_factor("blue_boost", None, "blue") == 1.0         # field unknown
    assert tb.colour_factor("honey", "pepper", "blue") == 1.0          # no colour


def test_off_a_blue_boost_in_pepper_is_still_chased_and_the_shadow_says_so():
    b = TokenBrain(pri, hive="blue")
    b.field = "pepper"
    ts = [track(1, 960 + 300, 670, kind="blue_boost"), track(2, 960, 670 + 500, kind="honey")]
    d = b.decide(ts, ANCHOR, HERE, now=0.0)
    assert d.action == "chase" and d.target.kind == "blue_boost"
    assert d.target.trace["colour"] == 0.0 and "x colour" not in d.target.trace
    would = tb.colour_would(d, b.field)
    assert would.startswith("skip blue_boost#1") and "no blue flowers in pepper" in would
    assert "chase honey#2" in would
    b.field = "pine_tree"
    b.forget()
    assert tb.colour_would(b.decide(ts, ANCHOR, HERE, now=0.0), b.field) == ""


def test_live_a_zero_colour_kind_is_gated_and_a_quest_kind_is_exempt(monkeypatch):
    monkeypatch.setattr(tb, "COLOUR_LIVE", True)
    b = TokenBrain(lambda k: 1 if k == "black_blue_burst" else 10, hive="blue")
    b.field = "pepper"
    cs = b.score([track(1, 960 + 300, 670, kind="blue_boost"),
                  track(2, 960 - 300, 670, kind="black_blue_burst"),
                  track(3, 960, 670 + 300, kind="red_boost")], ANCHOR, HERE, now=0.0)
    by = {c.kind: c for c in cs}
    assert by["blue_boost"].gated.startswith("no blue flowers in pepper")
    assert not by["black_blue_burst"].gated                            # a quest wants it
    red = by["red_boost"]
    assert red.trace["x colour"] == pytest.approx(0.93, abs=0.01)
    assert red.score == pytest.approx(
        red.trace["base"] * red.trace["x confidence"] * red.trace["x distance"]
        * red.trace["x staleness"] * red.trace["x cluster"] * red.trace["x reach"]
        * red.trace["x colour"], rel=0.01)                 # the trace is rounded

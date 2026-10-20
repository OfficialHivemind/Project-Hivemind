"""Per-hive token weights, age urgency and balloon preempts (tokenbrain
WEIGHTS_LIVE, look-only), and the honey token's weight as an experiment arm
(brain/arms HONEY_WEIGHT, off with ARMS_LIVE)."""
from __future__ import annotations

import random
from pathlib import Path

import hivemind
from hivemind.brain import arms as A
from hivemind.brain import tokenbrain as tb
from hivemind.brain.tokenbrain import TokenBrain
from hivemind.vision import tokens
from hivemind.vision.tracks import Track

ANCHOR = (960, 670)
PRI = {"honey": 101, "unknown": 100, "inflate_balloon": 10, "blue_boost": 10}
LIFE = {"honey": 10.0, "blue_boost": 4.0}
BLUE = {"honey": 0.0}                     # tokens.yaml weight_by_hive, blue
PREEMPT = {"inflate_balloon": 220.0}


def pri(kind):
    return PRI.get(kind, 100)


def track(tid, dx, kind="unknown", dy=0, first=0.0):
    return Track(id=tid, x=ANCHOR[0] + dx, y=ANCHOR[1] + dy, kind=kind, first_seen=first,
                 last_seen=0.0, matches=3, detector_confidence=0.9)


def brain():
    return TokenBrain(pri, life_of=LIFE.get, weight_of=BLUE.get, preempt_of=PREEMPT.get)


def test_look_only_by_default_the_old_pick_stands_and_says_what_it_would_do():
    assert tb.WEIGHTS_LIVE is False
    d = brain().decide([track(1, 250, "honey"), track(2, 600)], ANCHOR, ANCHOR, 0.0)
    assert d.action == "chase" and d.target.kind == "honey", d.describe()
    assert d.would.startswith("chase unknown#2"), d.would
    honey = next(c for c in d.ranked if c.kind == "honey")
    assert honey.trace["would score"] == 0.0 and "x urgency" not in honey.trace


def test_live_a_blue_hive_does_not_walk_to_a_honey_token(monkeypatch):
    monkeypatch.setattr(tb, "WEIGHTS_LIVE", True)
    d = brain().decide([track(1, 250, "honey")], ANCHOR, ANCHOR, 0.0)
    assert d.action == "hold" and d.would == ""
    d = brain().decide([track(1, 250, "honey"), track(2, 600)], ANCHOR, ANCHOR, 0.0)
    assert d.target.kind == "unknown"


def test_the_trace_still_multiplies_out_to_the_score_when_live(monkeypatch):
    monkeypatch.setattr(tb, "WEIGHTS_LIVE", True)
    ranked = brain().score([track(1, 300, "blue_boost", first=-2.0)], ANCHOR, ANCHOR, 0.0)
    c = ranked[0]
    product = c.trace["base"]
    for k, v in c.trace.items():
        if k.startswith("x "):
            product *= v
    assert c.trace["x urgency"] > 1.0
    assert abs(product - c.score) < 0.01 * c.score


def test_urgency_rises_with_age_only_while_the_walk_gets_there_in_time():
    assert tb.urgency_multiplier(0.0, 10.0, 200) == 1.0
    assert tb.urgency_multiplier(5.0, 10.0, 200) == 1.5
    assert tb.urgency_multiplier(2.0, 4.0, 200) == 1.5
    assert tb.urgency_multiplier(3.5, 4.0, 200) == 1.0      # arrives past 1 x life: age unknown
    assert tb.urgency_multiplier(7.5, 4.0, 400) == 1.0      # gone before we get there (2 x life)
    assert tb.urgency_multiplier(9.0, None, 200) == 1.0     # no life in tokens.yaml


def test_live_the_older_of_two_equal_tokens_goes_first(monkeypatch):
    monkeypatch.setattr(tb, "WEIGHTS_LIVE", True)
    young, old = track(1, 300, "blue_boost", dy=-50), track(2, 300, "blue_boost", dy=50, first=-2.0)
    d = brain().decide([young, old], ANCHOR, ANCHOR, 0.0)
    assert d.target.track_id == 2, d.describe()


def test_live_a_near_balloon_token_preempts_even_a_committed_target(monkeypatch):
    monkeypatch.setattr(tb, "WEIGHTS_LIVE", True)
    b = brain()
    far = track(1, -350)
    assert b.decide([far], ANCHOR, ANCHOR, 0.0).target.track_id == 1
    d = b.decide([far, track(2, 200, "inflate_balloon")], ANCHOR, ANCHOR, 0.1)
    assert d.target.track_id == 2 and d.why.startswith("preempt"), d.describe()
    assert b.committed == 2 and b.interrupts == 1
    d = brain().decide([track(3, 500, "inflate_balloon"), track(4, -250)], ANCHOR, ANCHOR, 0.0)
    assert not d.why.startswith("preempt")                   # past its preempt_px


def test_look_only_a_preempt_is_said_not_done():
    b = brain()
    far = track(1, -350, "blue_boost")      # strong enough that the margin keeps it
    b.decide([far], ANCHOR, ANCHOR, 0.0)
    d = b.decide([far, track(2, 200, "inflate_balloon")], ANCHOR, ANCHOR, 0.1)
    assert d.target.track_id == 1
    assert d.would.startswith("chase inflate_balloon#2") and "preempt" in d.would


def test_an_arms_weight_beats_the_hive_weight_and_the_ordering():
    b = brain()
    assert b.base_for("honey") == tb.BELOW_UNKNOWN_WEIGHT     # look-only: the ordering
    assert b.base_for("honey", live=True) == 0.0              # the hive's
    b.weights["honey"] = 18.0
    assert b.base_for("honey") == b.base_for("honey", live=True) == 18.0
    # 18 chases only near: the arm's middle value
    assert b.decide([track(1, 300, "honey")], ANCHOR, ANCHOR, 0.0).action == "chase"
    assert TokenBrain(pri).decide([track(1, 550, "honey")], ANCHOR, ANCHOR, 0.0).action == "chase"
    b.forget()
    assert b.decide([track(2, 550, "honey")], ANCHOR, ANCHOR, 0.0).action == "hold"


def test_kinds_reads_the_hive_weight_and_preempt_from_tokens_yaml():
    path = Path(hivemind.__file__).resolve().parents[2] / "data/knowledge/tokens.yaml"
    blue, red = tokens.load_kinds(path, hive="blue"), tokens.load_kinds(path, hive="red")
    assert blue.weight("honey") == 0.0 and red.weight("honey") is None
    assert blue.weight("haste") is None
    assert blue.preempt_px("inflate_balloon") == 220.0 and blue.preempt_px("honey") is None
    blue.want(["honey"])                                     # a quest's top rank stands
    assert blue.weight("honey") is None


def test_the_honey_arm_files_the_weight_in_use_and_only_on_a_chasing_trip(tmp_path):
    a = A.Arms(tmp_path / "e.json", rng=random.Random(1))
    assert a.begin("pine_tree", 0.9, True, 36.0) == {A.CONVERT_AT: 0.9, A.CHASE: 1.0,
                                                     A.HONEY_WEIGHT: 36.0}
    assert a.learn({"honey": 30_000_000, "seconds": 600}) == [
        "convert at 0.9", "chase 1", "honey weight 36"]
    assert A.HONEY_WEIGHT not in a.begin("clover", 0.9, False, 36.0)
    assert "honey weight" in a.would("pine_tree", True)


def test_live_the_honey_arm_picks_from_its_values(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ARMS_LIVE", True)
    a = A.Arms(tmp_path / "e.json", rng=random.Random(2))
    seen = set()
    for _ in range(30):
        use = a.begin("pine_tree", 0.9, True, 36.0)
        if A.HONEY_WEIGHT in use:
            seen.add(use[A.HONEY_WEIGHT])
            assert use[A.CHASE] == 1.0
        a.learn({"honey": 20_000_000, "seconds": 600})
    assert seen <= set(A.VALUES[A.HONEY_WEIGHT]) and len(seen) > 1


def test_run_farm_wires_the_weights_and_the_honey_arm():
    src = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text(
        encoding="utf-8")
    assert "weight_of=token_kinds.weight" in src and "preempt_of=token_kinds.preempt_px" in src
    assert 'token brain weights would: {decision.would}' in src
    assert 'chase_here, token_brain.base_for("honey"))' in src
    assert 'token_brain.weights["honey"] = use[arms_mod.HONEY_WEIGHT]' in src


def test_the_shadow_does_not_name_a_chase_the_pull_home_would_beat():
    # away from the anchor the return outscores both tokens; with honey at 0 the
    # weights still leave the unknown under the pull home, so they agree: return
    here = (ANCHOR[0] + 125, ANCHOR[1])
    near = Track(id=1, x=here[0] - 150, y=here[1] - 50, kind="honey", first_seen=0.0,
                 last_seen=0.0, matches=3, detector_confidence=0.9)
    far = Track(id=2, x=here[0] - 400, y=here[1] - 134, kind="unknown", first_seen=0.0,
                last_seen=0.0, matches=3, detector_confidence=0.9)
    d = brain().decide([near, far], ANCHOR, here, 0.0)
    assert d.action == "return" and d.would == "", (d.describe(), d.would)

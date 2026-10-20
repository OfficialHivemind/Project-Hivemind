"""The token detector, against real frames -- and what it must never do again.

The real-frame tests run on the labelled frames of data/models/coin_labels.json
(var/incidents/*-token pickup windows and var/routes gather snapshots) and skip
cleanly where those frames are not on this machine; the incident windows are
large and are not committed. What the detector measured on frames it never
trained on is data/models/coins.json `held_out`; these pin the shipped model's
behaviour on the frames it did train on, so a broken model or a broken
pipeline cannot pass unnoticed.
"""
from __future__ import annotations

import json
import pathlib
import time

import cv2
import numpy as np
import pytest

from hivemind.vision import coins, tokens

ROOT = pathlib.Path(__file__).resolve().parents[2]
LABELS = ROOT / "data/models/coin_labels.json"

# THE OLD DETECTOR'S NINE "TOKEN CUBES", hand-labelled on this frame on
# 2026-09-21 and the ground truth of its tests ever since. Every one is a
# BEE -- the white level badge or chevron on a bee cube ("7", "^", "v", "6"),
# checked on the frame 2026-09-28. The frame's one coin is a honey crescent
# behind the fire at the top. Nothing here may be walked to.
BEE_BADGES_FRAME = ROOT / "var/incidents/234344-token/149_t+07.6s.jpg"
BEE_BADGES = [
    (704, 741), (922, 672), (878, 805), (1214, 741), (1419, 766),
    (1583, 636), (694, 493), (1068, 470), (966, 481)]
NEAR_PX = 45


def _labelled(partial: bool = False, limit: int | None = None):
    if not LABELS.exists():
        pytest.skip("no coin labels")
    frames = [f for f in json.loads(LABELS.read_text())["frames"]
              if bool(f.get("partial")) == partial]
    out = []
    for f in frames[:limit]:
        im = cv2.imread(str(ROOT / f["path"]))
        if im is not None:
            out.append((f, im))
    if not out:
        pytest.skip("the labelled frames are not on this machine")
    return out


def _inside(pt, box, grow=0.25):
    x0, y0, x1, y1 = box
    gx, gy = (x1 - x0) * grow, (y1 - y0) * grow
    return x0 - gx <= pt[0] <= x1 + gx and y0 - gy <= pt[1] <= y1 + gy


# ---------------------------------------------------------- on real frames ----
def test_none_of_the_old_detectors_bee_badges_is_chased():
    if not BEE_BADGES_FRAME.exists():
        pytest.skip("the 234344 incident frame is not on this machine")
    found = tokens.detect(cv2.imread(str(BEE_BADGES_FRAME)))
    chased = [s for s in found if s.confidence >= tokens.CHASE_CONFIDENCE]
    for bx, by in BEE_BADGES:
        near = [s for s in chased if abs(s.x - bx) <= NEAR_PX and abs(s.y - by) <= NEAR_PX]
        assert not near, f"the bee badge at ({bx}, {by}) was taken for a token: {near[0].why}"


def test_it_finds_most_labelled_coins_on_its_own_frames():
    """In-sample, so a floor for "the model works", not a claim of how well.
    MEASURED 2026-09-28 on the shipped model (trained on every frame): 55 of
    79 at CHASE_CONFIDENCE, 13 boxes on no coin over these 40 frames -- in
    line with its 0.654 recall held out (data/models/coins.json), so it is
    not overfit. The floors sit under that: a broken model or pipeline
    finds next to nothing, and fails them by a mile."""
    found = total = wrong = 0
    frames = _labelled(limit=40)
    for f, im in frames:
        seen = [s for s in tokens.detect(im) if s.confidence >= tokens.CHASE_CONFIDENCE]
        for c in f["coins"]:
            if c["sure"]:
                total += 1
                found += any(_inside((s.x, s.y), c["box"]) for s in seen)
        wrong += sum(1 for s in seen if not any(_inside((s.x, s.y), c["box"]) for c in f["coins"]))
    assert found >= 0.6 * total, f"{found} of {total} labelled coins"
    assert wrong <= 1.0 * len(frames), f"{wrong} boxes on no coin over {len(frames)} frames"


def test_the_reviewed_mistakes_in_other_fields_stay_mistakes():
    """The avatar, its skateboard, Pine Tree's shade, Mountain Top's red
    flowers: each was a box once, and a reviewed "not a coin" since."""
    kept = total = 0
    for f, im in _labelled(partial=True, limit=60):
        seen = [s for s in tokens.detect(im) if s.confidence >= tokens.CHASE_CONFIDENCE]
        for n in f.get("not_coins", ()):
            total += 1
            kept += any(_inside((s.x, s.y), n["box"], 0.0) for s in seen)
    assert total, "no reviewed not-coins in the partial frames"
    assert kept <= 0.1 * total, f"{kept} of {total} reviewed not-coins still chased"


def test_every_sighting_explains_itself_and_carries_the_coins_square():
    for f, im in _labelled(limit=5):
        for s in tokens.detect(im):
            assert s.why.startswith("coin p"), s.why
            left, top, w, h = s.box
            assert w == h and w > 0 and left <= s.x <= left + w and top <= s.y <= top + h


def test_it_is_fast_enough_to_run_in_the_loop():
    """The live view's overlay thread and the chaser both look every frame."""
    (f, im), = _labelled(limit=1)
    tokens.detect(im)                              # warm, and load the model
    started = time.perf_counter()
    for _ in range(3):
        tokens.detect(im)
    each = (time.perf_counter() - started) / 3
    assert each < 0.25, f"{each * 1000:.0f} ms a frame"


# ------------------------------------------------- without any real frame ----
def _canvas(colour=(90, 150, 70)):
    return np.full((1080, 1920, 3), colour, np.uint8)


def test_nothing_in_an_empty_frame():
    assert tokens.detect(_canvas()) == []


def test_an_empty_or_missing_frame_is_not_an_error():
    assert tokens.detect(None) == []
    assert tokens.detect(np.zeros((0, 0, 3), np.uint8)) == []


def test_candidates_on_one_coin_are_one_sighting(monkeypatch):
    monkeypatch.setattr(coins, "look", lambda f, *a, **k: [
        (900.0, 600.0, 80.0, 7.0, 3.0), (915.0, 610.0, 96.0, 6.0, 2.4)])
    found = tokens.detect(_canvas())
    assert len(found) == 1 and found[0].faces == 2


def test_below_the_report_cut_nothing_is_reported(monkeypatch):
    weak = float(np.log(0.5 / 0.5))                # p 0.5, under REPORT_P
    monkeypatch.setattr(coins, "look", lambda f, *a, **k: [(900.0, 600.0, 80.0, weak, 3.0)])
    assert tokens.detect(_canvas()) == []


def test_nearest_refuses_to_answer_below_the_threshold():
    weak = [tokens.Sighting(x=10, y=10, confidence=0.1)]
    assert tokens.nearest(weak, 1920, 1080) is None
    assert tokens.nearest(weak, 1920, 1080, min_confidence=0.0) is weak[0]


def test_nearest_of_nothing_is_nothing():
    assert tokens.nearest([], 1920, 1080) is None


# ---------------------------------------------------------- naming a token ---
def _sight(x, y, face, conf=0.9):
    return tokens.Sighting(x=x, y=y, confidence=conf, face_hsv=face)


def test_a_measured_kind_is_named_and_an_unmeasured_one_never_is():
    table = tokens.Kinds({
        "tabby_love": {"priority": 1, "face_hsv": None},         # wanted, not seen
        "navy": {"priority": 5, "face_hsv": [110, 200, 90]},
    })
    assert table.classify(_sight(0, 0, (111, 190, 100))) == "navy"
    assert table.classify(_sight(0, 0, (150, 200, 200))) == "unknown"
    assert table.classify(_sight(0, 0, None)) == "unknown"
    assert table.unmeasured() == ["tabby_love"] and table.measured() == ["navy"]
    assert "no colour at all: tabby_love" in table.describe()


def test_a_preferred_kind_beats_a_closer_ordinary_token():
    table = tokens.Kinds({"navy": {"priority": 1, "face_hsv": [110, 200, 90]}})
    near_plain = _sight(970, 680, (60, 30, 240))            # right under the character
    far_navy = _sight(1300, 500, (110, 200, 90))
    pick = tokens.nearest([near_plain, far_navy], 1920, 1080, prefer=table)
    assert pick is far_navy and pick.kind == "navy"


def test_without_a_table_it_is_plain_nearest():
    near_plain = _sight(970, 680, (60, 30, 240))
    far_navy = _sight(1300, 500, (110, 200, 90))
    assert tokens.nearest([near_plain, far_navy], 1920, 1080) is near_plain


def test_two_unknowns_rank_by_distance():
    table = tokens.Kinds({"tabby_love": {"priority": 1, "face_hsv": None}})
    a, b = _sight(970, 680, (60, 30, 240)), _sight(1300, 500, (110, 200, 90))
    assert tokens.nearest([a, b], 1920, 1080, prefer=table) is a


def test_hue_wraps_around_the_circle():
    table = tokens.Kinds({"red": {"priority": 2, "face_hsv": [2, 200, 200]}})
    assert table.classify(_sight(0, 0, (176, 200, 200))) == "red"


def test_the_real_table_has_a_colour_for_every_kind_and_confirms_none():
    """Every colour comes from the official wiki icon; an icon is not a
    screenshot, so nothing may claim in-game confirmation yet."""
    table = tokens.load_kinds(ROOT / "data/knowledge/tokens.yaml")
    assert len(table.measured()) >= 35
    assert table.unmeasured() == []
    assert table.confirmed() == [], "an icon colour is not an in-game measurement"
    assert table.priority("tabby_love") == 1
    assert table.priority("unknown") == tokens.UNKNOWN_PRIORITY
    assert "NONE confirmed on a live frame" in table.describe()


def test_three_orange_tokens_share_a_colour_and_are_split_by_their_dark_share():
    """MEASURED on the icons: Rage, Tabby Love and Scratch are all the same
    orange, and differ only in how much of the face is dark strokes --
    0.00, 0.14 and 0.64. Colour alone cannot name any of them."""
    table = tokens.load_kinds(ROOT / "data/knowledge/tokens.yaml")

    def named(dark):
        return table.classify(tokens.Sighting(x=0, y=0, confidence=0.9,
                                              face_hsv=(16, 208, 250), dark=dark))
    assert named(0.14) == "tabby_love"
    assert named(0.62) == "scratch"
    assert named(0.00) == "rage"


def test_the_owners_priority_really_wins_on_a_real_frame():
    """A Tabby-orange sighting is chased ahead of a closer one of any other
    kind. This is the owner's request made operational."""
    table = tokens.load_kinds(ROOT / "data/knowledge/tokens.yaml")
    near_honey = tokens.Sighting(x=970, y=680, confidence=0.9,
                                 face_hsv=(28, 240, 240), dark=0.03)
    far_tabby = tokens.Sighting(x=1400, y=420, confidence=0.9,
                                face_hsv=(16, 208, 250), dark=0.14)
    pick = tokens.nearest([near_honey, far_tabby], 1920, 1080, prefer=table)
    assert pick is far_tabby and pick.kind == "tabby_love"


def test_a_missing_table_is_empty_not_an_error(tmp_path):
    assert tokens.load_kinds(tmp_path / "nope.yaml").kinds == {}


# ---- a kind a quest still wants ranks first --------------------------------
# MEASURED 2026-09-23 from `var/quests.json`, read off the account's own quest
# menu: "Honey Bee's Honey Hunt -- Collect 2,000 Honey Tokens. 1,845/2,000".
# 155 tokens from a finished quest, and the token brain was chasing whatever
# was nearest: 18 honey tokens picked up in two and a half hours.

def _kinds():
    from hivemind.vision.tokens import Kinds
    return Kinds(kinds={
        "honey": {"priority": 10, "face_hsv": [28, 240, 240], "dark": 0.034},
        "haste": {"priority": 10, "face_hsv": [104, 16, 128], "dark": 0.0},
        "tabby_love": {"priority": 1, "face_hsv": [16, 208, 255], "dark": 0.138},
    })


def test_a_wanted_kind_takes_the_top_priority():
    from hivemind.vision.tokens import QUEST_PRIORITY
    k = _kinds()
    assert k.priority("honey") == 10
    known, unknown = k.want(["honey"])
    assert known == ("honey",) and unknown == ()
    assert k.priority("honey") == QUEST_PRIORITY
    assert k.priority("haste") == 10, "an unwanted kind must not move"


def test_the_top_priority_is_the_brain_s_best_weight():
    """It has to be the tier the brain already has, or wanting a token would
    mean nothing to the arithmetic that chases it."""
    from hivemind.vision.tokens import QUEST_PRIORITY
    from hivemind.brain.tokenbrain import WEIGHT_BY_PRIORITY
    assert QUEST_PRIORITY in WEIGHT_BY_PRIORITY
    assert WEIGHT_BY_PRIORITY[QUEST_PRIORITY] == max(WEIGHT_BY_PRIORITY.values())


def test_a_kind_the_table_does_not_know_is_reported_not_swallowed():
    k = _kinds()
    known, unknown = k.want(["honey", "moon_cheese"])
    assert known == ("honey",)
    assert unknown == ("moon_cheese",)
    assert k.priority("moon_cheese") != 1, "it must not be silently promoted"


def test_wanting_nothing_clears_the_list():
    k = _kinds()
    k.want(["honey"])
    k.want([])
    assert k.priority("honey") == 10


def test_the_table_on_disk_is_not_touched():
    """The file is the owner's standing ranking; a quest is one session's
    errand."""
    k = _kinds()
    k.want(["honey"])
    assert k.kinds["honey"]["priority"] == 10


def test_the_summary_says_when_a_quest_is_the_reason():
    """Without this the line reads "chasing tabby love then scratch first"
    from the table's standing ranking while the brain is walking for honey
    tokens, and the two statements sit a line apart in the log contradicting
    each other. MEASURED 2026-09-23 04:33, run-295's own startup."""
    k = _kinds()
    assert "a quest wants" not in k.describe()
    k.want(["honey"])
    text = k.describe()
    assert "a quest wants honey, so those come first" in text, text
    assert "chasing honey" in text, text

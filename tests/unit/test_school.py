"""The school: chases labelled by what the HUD did, and a classifier over them."""
from __future__ import annotations

import json
import pathlib

import cv2
import numpy as np
import pytest

from hivemind.brain import school as S
from hivemind.brain.school import School, Snapshot, judge
from hivemind.brain.tokenbrain import TokenBrain
from hivemind.vision.tracks import Track, Tracker


def snap(at=0.0, pollen=100_000, honey=1_000_000, haste=False, stacks=None, hstacks=None):
    return Snapshot(at=at, pollen=pollen, honey=honey, haste_present=haste,
                    haste_stacks=hstacks, stacks=dict(stacks or {}))


# ---- the verdict -----------------------------------------------------------------

def test_a_honey_lump_means_collected_whatever_the_kind_was_called():
    out, why = judge("fuzz_bombs", snap(), snap(at=3.0, honey=1_000_500), arrived=True,
                     pollen_rate=200.0, honey_rate=10.0)
    assert out == "collected" and "honey rose" in why


def test_the_honey_trickle_is_not_a_token():
    """MEASURED 2026-09-22 22:23: +5..+37 honey/sec in the field; the first
    three chases read 'honey rose by 273 / 345 / 97' -- the trickle."""
    out, _ = judge("fuzz_bombs", snap(), snap(at=3.0, honey=1_000_090), arrived=True,
                   pollen_rate=200.0, honey_rate=30.0)
    assert out == "unknown"
    out, why = judge("honey", snap(), snap(at=3.0, honey=1_000_090), arrived=True,
                     pollen_rate=200.0, honey_rate=30.0)
    assert out == "nothing" and "trickle" in why


def test_an_unwatched_honey_trickle_makes_a_honey_rise_prove_nothing():
    out, _ = judge("honey", snap(), snap(at=3.0, honey=1_000_500), arrived=True,
                   pollen_rate=200.0, honey_rate=None)
    assert out == "unknown"


def test_haste_appearing_or_stacking_means_collected():
    assert judge("haste", snap(), snap(at=2.0, haste=True), True, 200.0)[0] == "collected"
    assert judge("haste", snap(haste=True, hstacks=2), snap(at=2.0, haste=True, hstacks=3), True, 200.0)[0] == "collected"


def test_a_buffs_stack_digit_rising_means_collected():
    # stack_rate 0.0: the bar's own rise was watched and was nil (a rise
    # counts only beyond that background, STACK_LUMP_FACTOR)
    out, why = judge("focus", snap(stacks={2: 3}), snap(at=2.0, stacks={2: 4}), True, 200.0,
                     0.0, 0.0)
    assert out == "collected" and "x3 -> x4" in why


def test_a_pollen_lump_beyond_the_gathering_rate_means_collected():
    # 3 s of chase at 200/s gathers ~600; a lump of 5,000 is a token
    out, why = judge("baby_love", snap(pollen=100_000), snap(at=3.0, pollen=105_000), True, 200.0)
    assert out == "collected" and "pollen rose" in why


def test_gathering_alone_is_not_a_lump():
    out, _ = judge("baby_love", snap(pollen=100_000), snap(at=3.0, pollen=100_700), True, 200.0)
    assert out == "nothing"


def test_reaching_a_honey_coloured_thing_that_moved_no_honey_is_nothing():
    out, why = judge("honey", snap(), snap(at=3.0), True, 200.0)
    assert out == "nothing" and "honey figure" in why


def test_a_kind_whose_effect_cannot_be_seen_teaches_nothing():
    out, why = judge("triangulate", snap(), snap(at=3.0), True, 200.0)
    assert out == "unknown" and "no mark" in why


def test_a_chase_that_did_not_arrive_teaches_nothing():
    assert judge("honey", snap(), snap(at=3.0), False, 200.0)[0] == "unknown"


def test_an_unreadable_counter_makes_no_verdict():
    assert judge("honey", snap(honey=None), snap(at=3.0, honey=None), True, 200.0)[0] == "unknown"
    assert judge("baby_love", snap(), snap(at=3.0, pollen=100_100), True, None)[0] == "unknown"


# ---- the pollen rate --------------------------------------------------------------

def test_the_rate_needs_five_seconds_and_forgets_a_fall():
    sc = School.__new__(School)
    import collections
    sc._pollen = collections.deque(); sc._honey = collections.deque(); sc.clock = lambda: 0.0
    sc._stacks = collections.deque()
    sc.tick(1000, at=0.0)
    sc.tick(1400, at=2.0)
    assert sc.pollen_rate() is None
    sc.tick(2000, at=10.0)
    assert sc.pollen_rate() == pytest.approx(100.0)
    sc.tick(0, at=12.0)                   # a convert
    assert sc.pollen_rate() is None
    sc.tick(None, at=0.0, honey=1000); sc.tick(None, at=10.0, honey=1300)
    assert sc.honey_rate() == pytest.approx(30.0)


# ---- lessons on disk and the classifier ------------------------------------------

def _token_crop(rng):
    """A flat dark square with a white glyph: what a token cube face looks like."""
    c = np.full((S.CROP, S.CROP, 3), (70, 60, 40), np.uint8)
    c[:] = c + rng.integers(-15, 15, size=(1, 1, 3)).astype(np.int16).clip(-15, 15).astype(np.uint8)
    cv2.rectangle(c, (14, 14), (34, 34), (245, 245, 245), -1)
    cv2.rectangle(c, (8, 8), (40, 40), (10, 10, 10), 2)
    return c


def _bee_crop(rng):
    """A coloured cube with two white eyes on a green field."""
    c = np.full((S.CROP, S.CROP, 3), (60, 140, 70), np.uint8)
    colour = tuple(int(v) for v in rng.integers(80, 255, size=3))
    cv2.rectangle(c, (10, 12), (38, 40), colour, -1)
    cv2.circle(c, (18, 22), 3, (255, 255, 255), -1)
    cv2.circle(c, (30, 22), 3, (255, 255, 255), -1)
    cv2.rectangle(c, (10, 12), (38, 40), (20, 20, 20), 1)
    return c


def _teach(sc: School, frame_of, n: int, outcome_evidence):
    """Run n lessons through begin/finish with a HUD that behaves as told."""
    rng = np.random.default_rng(len(sc.lessons) + n)
    # the rates are watched: a flat honey figure and a steady pollen gather
    sc.tick(100_000, at=-10.0, honey=1000)
    sc.tick(102_000, at=0.0, honey=1000)
    for i in range(n):
        frame = np.zeros((200, 200, 3), np.uint8)
        frame[76:124, 76:124] = frame_of(rng)
        before = snap(at=float(i), honey=1000)
        lesson = sc.begin(frame, 100, 100, "honey", 0.8, before)
        after = snap(at=float(i) + 2.0, honey=1000 + (900 if outcome_evidence == "collected" else 0))
        sc.finish(lesson, after, arrived=True)


def test_lessons_are_written_down_and_the_school_stays_silent_until_it_has_enough(tmp_path):
    sc = School(tmp_path, min_lessons=5)
    _teach(sc, _token_crop, 3, "collected")
    assert sc.counts() == {"collected": 3, "nothing": 0}
    assert not sc.ready() and sc.score(_token_crop(np.random.default_rng(1))) is None
    lines = (tmp_path / "lessons.jsonl").read_text().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["outcome"] == "collected"
    assert len(list((tmp_path / "crops").glob("*.png"))) == 3
    assert "silent until 5" in sc.describe()


def test_with_enough_of_both_it_tells_a_token_from_a_bee(tmp_path):
    sc = School(tmp_path, min_lessons=5)
    _teach(sc, _token_crop, 6, "collected")
    _teach(sc, _bee_crop, 6, "nothing")
    assert sc.ready()
    rng = np.random.default_rng(99)
    assert sc.score(_token_crop(rng)) >= 0.8
    assert sc.score(_bee_crop(rng)) <= 0.2
    assert "classifying" in sc.describe()


def test_the_lessons_survive_a_restart(tmp_path):
    sc = School(tmp_path, min_lessons=5)
    _teach(sc, _token_crop, 6, "collected")
    _teach(sc, _bee_crop, 6, "nothing")
    again = School(tmp_path, min_lessons=5)
    assert again.counts() == {"collected": 6, "nothing": 6}
    assert again.score(_bee_crop(np.random.default_rng(3))) <= 0.2


def test_an_unknown_outcome_is_kept_for_a_human_but_teaches_nothing(tmp_path):
    sc = School(tmp_path, min_lessons=5)
    frame = np.zeros((200, 200, 3), np.uint8)
    lesson = sc.begin(frame, 100, 100, "triangulate", 0.7, snap())
    done = sc.finish(lesson, snap(at=2.0), arrived=True)
    assert done.outcome == "unknown"
    assert sc.counts() == {"collected": 0, "nothing": 0}
    assert (tmp_path / "lessons.jsonl").read_text().count("unknown") == 1


# ---- the hooks -------------------------------------------------------------------

def test_a_tracks_school_opinion_is_the_mean_of_its_sightings():
    class Sighting:
        def __init__(self, x, y, p): self.x, self.y, self.confidence, self.kind, self.school_p = x, y, 0.8, "honey", p
    t = Tracker()
    t.observe([Sighting(500, 400, 0.2)], now=0.0)
    t.observe([Sighting(502, 401, 0.6)], now=0.3)
    t.observe([Sighting(503, 401, None)], now=0.6)         # the school was silent this look
    (track,) = t.alive(0.6)
    assert track.school_p == pytest.approx(0.4) and track.school_n == 2


def test_the_brain_gates_what_the_school_calls_a_bee():
    brain = TokenBrain(priority_of=lambda k: 10)
    here = (960, 669)
    bee = Track(id=1, x=1300, y=500, kind="honey", first_seen=0.0, last_seen=1.0, matches=3, school_p=0.1)
    token = Track(id=2, x=600, y=500, kind="honey", first_seen=0.0, last_seen=1.0, matches=3, school_p=0.9)
    unsure = Track(id=3, x=1300, y=800, kind="honey", first_seen=0.0, last_seen=1.0, matches=3)
    ranked = {c.track_id: c for c in brain.score([bee, token, unsure], here, here, now=1.0) if c.track_id}
    assert "school says" in ranked[1].gated
    assert not ranked[2].gated and ranked[2].trace["school_p"] == 0.9
    assert not ranked[3].gated


def test_the_first_evenings_trickle_verdicts_teach_nothing(tmp_path):
    """Written before the trickle rule: 'honey rose by 273'. Kept, not learned."""
    (tmp_path / "lessons.jsonl").write_text(json.dumps({
        "id": "x", "at": 0.0, "kind": "fuzz_bombs", "confidence": 0.8, "x": 1, "y": 1,
        "outcome": "collected", "evidence": "honey rose by 273", "attempt": 246}) + "\n" + json.dumps({
        "id": "y", "at": 0.0, "kind": "honey", "confidence": 0.8, "x": 1, "y": 1,
        "outcome": "collected", "evidence": "honey rose 900 in 2.0s against 20 expected from the trickle",
        "attempt": 248}) + "\n")
    sc = School(tmp_path, min_lessons=1)
    assert sc.counts() == {"collected": 1, "nothing": 0}


def test_a_buff_appearing_counts_even_though_it_shifts_every_slot():
    """MEASURED 2026-09-22: icons are added to and removed from the bar and
    the ones to their right move, so a per-slot comparison misses the most
    common collection there is."""
    out, why = judge("focus", snap(stacks={0: 5, 1: 14}),
                     snap(at=2.0, stacks={0: 5, 1: 14, 2: 1}), True, 200.0, 0.0, 0.0)
    assert out == "collected" and ("altogether" in why or "appeared" in why)


def test_a_stack_falling_off_is_not_a_collection():
    out, _ = judge("focus", snap(stacks={0: 5, 1: 14}),
                   snap(at=2.0, stacks={0: 5, 1: 13}), True, 200.0, 0.0)
    assert out == "nothing"


def test_a_buff_kind_with_a_readable_bar_and_no_gain_is_nothing():
    out, why = judge("bomb_sync", snap(stacks={0: 5}), snap(at=2.0, stacks={0: 5}),
                     True, 200.0, 0.0)
    assert out == "nothing" and "buff bar" in why


# ---- where the gate belongs, measured off the school's own lessons ---------
# The school became ready at 03:27 on 2026-09-23 with 43 `collected` and 76
# `nothing` lessons. Scoring every crop back through a k=5 kNN quantises the
# answers to fifths, so the useful thresholds cluster:
#
#     gate   real tokens skipped   junk chases saved
#     0.20          2/43  ( 5%)         21/76  (28%)
#     0.30         13/43  (30%)         48/76  (63%)
#     0.50         26/43  (60%)         71/76  (93%)
#
# A chase costs at most four steps; a token is worth hundreds to thousands of
# honey. Skipping a real one is the dearer mistake, so the gate sits where the
# false negatives nearly vanish.

def test_the_gate_only_refuses_what_every_neighbour_calls_junk():
    from hivemind.brain import tokenbrain as TB
    from hivemind.brain.school import School
    k = School(pathlib.Path("/nonexistent")).k
    assert k == 5, "the quantisation this threshold was chosen against has changed"
    # With k=5 the possible scores are 0, 0.2, 0.4, 0.6, 0.8, 1.0. A gate in
    # (0.0, 0.2] refuses only a unanimous no; anything above 0.2 also refuses
    # crops one neighbour in five called a token, which measured as throwing
    # away three real tokens in ten.
    assert 0.0 < TB.SCHOOL_GATE_BELOW <= 1.0 / k, (
        f"SCHOOL_GATE_BELOW is {TB.SCHOOL_GATE_BELOW}, which refuses crops "
        f"that {k}-nearest-neighbour did not unanimously call junk")


def test_a_loud_honey_trickle_hides_a_token_so_no_lump_proves_nothing():
    """MEASURED 2026-10-07: a trickle of 500-900 honey a second, and 155 honey
    "nothing" lessons whose crops were coins (the school then gated honey at
    P 0.00)."""
    out, why = judge("honey", snap(), snap(at=1.5, honey=1_001_000), arrived=True,
                     pollen_rate=200.0, honey_rate=700.0)
    assert out == "unknown" and "hides a honey token" in why
    # a lump past the bar still shows, as a Honey Gift's 100 x level^2 does
    out, _ = judge("honey", snap(), snap(at=1.5, honey=1_012_000), arrived=True,
                   pollen_rate=200.0, honey_rate=700.0)
    assert out == "collected"


def test_a_honey_nothing_with_no_figures_was_judged_under_any_trickle_and_teaches_nothing(tmp_path):
    old = {"id": "x", "at": 0.0, "kind": "honey", "confidence": 1.0, "x": 1, "y": 1,
           "outcome": "nothing", "evidence": S.HONEY_NOTHING, "attempt": 723}
    new = dict(old, id="y", evidence=S.HONEY_NOTHING + " (90 expected in 3.0s)")
    (tmp_path / "lessons.jsonl").write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n")
    assert School(tmp_path, min_lessons=1).counts() == {"collected": 0, "nothing": 1}


def test_an_opencv_without_ml_stays_silent_rather_than_raising(tmp_path, monkeypatch):
    """Windows run 5: pip's opencv-python had no cv2.ml."""
    from hivemind.vision import fieldsense
    sc = School(tmp_path, min_lessons=5)
    _teach(sc, _token_crop, 6, "collected")
    _teach(sc, _bee_crop, 6, "nothing")
    monkeypatch.delattr(cv2, "ml")
    assert sc.score(_token_crop(np.random.default_rng(1))) is None
    sense = fieldsense.FieldSense(model=None, notes=None, live_dir=None)
    sense.train_async()
    sense.train_async()
    assert sense.problems == [fieldsense.NO_ML] and not sense.trained


def test_a_wide_crop_is_kept_for_the_coin_detector(tmp_path):
    import cv2
    from hivemind.brain.school import WIDE_CROP
    sc = School(tmp_path, min_lessons=5)
    frame = np.zeros((400, 400, 3), np.uint8)
    lesson = sc.begin(frame, 200, 200, "honey", 0.8, snap())
    wide = cv2.imread(str(tmp_path / "crops-wide" / f"{lesson.id}.jpg"))
    assert wide is not None and wide.shape[:2] == (WIDE_CROP, WIDE_CROP)


# ---- the verdict by sight (look-only) ---------------------------------------------

def test_by_sight_gone_is_collected_and_still_there_is_unknown():
    gone = {"verdict": "gone", "settle_s": 0.25, "seen": 3, "near_px": None, "underfoot": False}
    still = {"verdict": "still there", "settle_s": 0.25, "seen": 1, "near_px": 40.0,
             "underfoot": False}
    assert S.judge_by_sight(True, gone)[0] == "collected"
    assert S.judge_by_sight(True, still)[0] == "unknown"
    assert "40.0 px" in S.judge_by_sight(True, still)[1]
    assert S.judge_by_sight(False, gone)[0] == "unknown"
    assert S.judge_by_sight(True, None) == ("", "no look after arriving")


def test_by_sight_is_written_beside_the_hud_and_does_not_label_yet(tmp_path):
    assert S.SIGHT_LABELS is False
    sc = School(tmp_path, min_lessons=5)
    frame = np.zeros((200, 200, 3), np.uint8)
    lesson = sc.begin(frame, 100, 100, "honey", 0.9, snap())
    done = sc.finish(lesson, snap(at=2.0), arrived=True,
                     sight={"verdict": "gone", "settle_s": 0.25, "seen": 0})
    assert done.sight == "collected"
    assert done.outcome != "collected"            # the HUD's verdict stays the label
    row = json.loads((tmp_path / "lessons.jsonl").read_text().splitlines()[-1])
    assert row["sight"] == "collected" and row["outcome"] == done.outcome


def test_by_sight_labels_only_when_switched_on(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SIGHT_LABELS", True)
    sc = School(tmp_path, min_lessons=5)
    frame = np.zeros((200, 200, 3), np.uint8)
    lesson = sc.begin(frame, 100, 100, "triangulate", 0.9, snap())
    done = sc.finish(lesson, snap(at=2.0), arrived=True,
                     sight={"verdict": "gone", "settle_s": 0.25, "seen": 0})
    assert done.outcome == "collected" and done.evidence.startswith("by sight")


def test_a_lesson_keeps_the_pollen_rate_before_and_during_the_detour(tmp_path):
    # tokenbrain LOSS_FRACTION = 1 - during/before, from these two figures
    sc = School(tmp_path, min_lessons=5)
    sc.tick(100_000, at=-10.0)
    sc.tick(120_000, at=0.0)                                   # 2,000/s before
    lesson = sc.begin(np.zeros((200, 200, 3), np.uint8), 100, 100, "honey", 0.8,
                      snap(at=0.0, pollen=120_000))
    sc.finish(lesson, snap(at=2.0, pollen=122_000), arrived=True)   # 1,000/s during
    body = json.loads((tmp_path / "lessons.jsonl").read_text().splitlines()[-1])
    assert body["rate_before"] == 2_000.0 and body["rate_during"] == 1_000.0

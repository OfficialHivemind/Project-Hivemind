"""The player's own bee is not a token, and only time tells them apart.

THE BUG. `vision.tokens.nearest()` returns the closest sighting it is
confident about, and the closest sighting is nearly always the player's own
bee -- its two white eyes and the highlight on its body all pass the token
test. Over all 18 frames of `var/tokens_live`, the hive row with exactly one
real token in it, the bee sat 55-160 px from the point the code treats as the
character and the nearest real object was 385 px away; the bee won 14 of 18.
The chase then declared it had arrived without taking a step, because the bee
is always inside `chase.ARRIVED_PIXELS`.

A DEAD ZONE WAS TRIED AND REJECTED on measurement: on the hand-labelled field
frame two real tokens sit NEARER than the bee's own eyes.

WHAT WORKS is that the avatar is rigid in screen space and the world is not.
`test_it_reproduces_the_measurement_on_the_recorded_run` replays the 2,380
samples the rule was derived from, so the thresholds cannot drift away from
their evidence.
"""
from __future__ import annotations

import json
import math
import pathlib
from types import SimpleNamespace

import numpy as np
import pytest

from hivemind.vision import pinned as P

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "var/pinned/samples.json"


def spot(x, y):
    return SimpleNamespace(x=x, y=y)


def moving_looks(filter_, positions, times):
    """Feed the same positions through `times` looks of a moving view."""
    for _ in range(times):
        filter_.teach(0.9, [spot(*p) for p in positions])


# ---- the rule --------------------------------------------------------------
def test_a_mark_that_never_moves_while_the_view_does_is_pinned():
    f = P.Pinned()
    moving_looks(f, [(960, 560)], P.PIN_LOOKS + 2)
    assert f.is_pinned(960, 560)


def test_a_mark_that_moves_with_the_world_is_not_pinned():
    f = P.Pinned()
    for i in range(P.PIN_LOOKS * 3):
        f.teach(0.9, [spot(400 + i * 30, 500)])
    assert not f.is_pinned(400, 500)
    assert not f.is_pinned(400 + P.PIN_LOOKS * 3 * 30, 500)


def test_it_needs_more_than_a_couple_of_looks_before_it_will_say():
    f = P.Pinned()
    moving_looks(f, [(960, 560)], P.PIN_LOOKS - 1)
    assert not f.is_pinned(960, 560), "it decided on too little evidence"


def test_a_still_view_teaches_it_nothing():
    """A stationary camera makes the whole world look as rigid as the avatar,
    which is exactly how the first attempt at this rule failed: every frame of
    `var/tokens_live` was taken with the camera still and the real token was
    as static as the bee's eye."""
    f = P.Pinned()
    for _ in range(P.PIN_LOOKS * 4):
        f.teach(0.0, [spot(960, 560)])
    assert not f.is_pinned(960, 560)
    assert f.taught == 0


def test_a_spot_that_mostly_moves_is_not_pinned_by_the_odd_still_frame():
    f = P.Pinned()
    for i in range(P.PIN_LOOKS * 4):
        # stays put every fourth look only
        x = 960 if i % 4 == 0 else 400 + i * 40
        f.teach(0.9, [spot(x, 560)])
    assert not f.is_pinned(960, 560)


def test_keep_hands_back_only_what_is_in_the_world():
    f = P.Pinned()
    moving_looks(f, [(960, 560)], P.PIN_LOOKS + 2)
    kept = f.keep(0.9, [spot(960, 560), spot(1150, 334)])
    assert [(s.x, s.y) for s in kept] == [(1150, 334)]


def test_a_stale_spot_is_forgotten():
    f = P.Pinned(forget=5)
    moving_looks(f, [(960, 560)], P.PIN_LOOKS + 2)
    assert f.is_pinned(960, 560)
    for _ in range(8):
        f.teach(0.9, [spot(300, 300)])
    assert not f.is_pinned(960, 560), "it carried a stale opinion"


# ---- the frame difference --------------------------------------------------
def test_an_unchanged_frame_reads_zero():
    frame = np.zeros((400, 600, 3), np.uint8)
    assert P.view_change(frame, frame) == 0.0


def test_a_completely_different_frame_reads_one():
    a = np.zeros((400, 600, 3), np.uint8)
    b = np.full((400, 600, 3), 255, np.uint8)
    assert P.view_change(a, b) > 0.99


def test_a_missing_or_mismatched_frame_is_not_movement():
    frame = np.zeros((400, 600, 3), np.uint8)
    assert P.view_change(None, frame) == 0.0
    assert P.view_change(frame, None) == 0.0
    assert P.view_change(frame, np.zeros((10, 10, 3), np.uint8)) == 0.0


def test_the_difference_is_taken_at_a_quarter_scale():
    """MEASURED across 49 consecutive pairs of a whole route: the quarter-scale
    fraction tracks the full-scale one to within 0.004 from 0.016 to 0.725 and
    agrees on which side of the threshold in 49 of 49, at 3.8 ms against 32.9.
    """
    assert P.VIEW_SCALE == 4


# ---- against the run it was derived from -----------------------------------
def test_it_reproduces_the_measurement_on_the_recorded_run():
    """The whole justification, as a test.

    2,380 samples of a live farming run. The bee's own head is the strongest
    pinned spot; the real world is not pinned; and most marks near the
    character still survive, which is what a dead zone could not manage.
    """
    if not SAMPLES.exists():
        pytest.skip("var/pinned/samples.json is not in the repo")
    data = json.loads(SAMPLES.read_text())
    f = P.Pinned()
    ox, oy = 960, int(1080 * 0.62)
    kept_near = dropped_near = 0
    for sample in data["samples"]:
        sightings = [spot(g["x"], g["y"]) for g in sample["glyphs"]]
        kept = {(s.x, s.y) for s in f.keep(sample["moved"], sightings)}
        for s in sightings:
            if math.hypot(s.x - ox, s.y - oy) <= 200:
                if (s.x, s.y) in kept:
                    kept_near += 1
                else:
                    dropped_near += 1

    pins = f.spots
    assert pins, "it learned nothing from a whole farming run"
    head = pins[0]
    assert math.hypot(head.x - ox, head.y - oy) < 200, (
        f"the strongest pinned spot is at ({head.x:.0f}, {head.y:.0f}), which "
        f"is not on the character")
    assert head.fraction > 0.7, f"measured 78%, got {head.fraction:.0%}"
    assert head.looks > 100

    near = kept_near + dropped_near
    assert near > 1000, "not enough marks near the character to judge by"
    assert dropped_near / near < 0.35, (
        f"it dropped {dropped_near / near:.0%} of everything near the "
        f"character; a real token there must survive")


# ---- it must be taught the RAW marks, not the merged sightings -------------
def test_it_accepts_plain_x_y_pairs():
    """`tokens.detect(..., marks=[])` hands back raw (x, y) pairs, and those
    are what this filter was measured on."""
    f = P.Pinned()
    for _ in range(P.PIN_LOOKS + 2):
        f.teach(0.9, [(960, 560), (1150, 334)])
    assert f.is_pinned(960, 560)


def test_a_merged_position_that_flips_between_faces_is_not_pinned():
    """WHY THE RAW MARKS MATTER. `tokens._merge` reports one cube as one
    sighting and keeps the strongest face's position, and which face is
    strongest flips frame to frame -- so the reported position wanders by up
    to the merge radius while the cube has not moved. Taught merged positions,
    the filter learns nothing: the first live run to try it reported "352
    moving look(s), nothing pinned to the screen yet".
    """
    f = P.Pinned()
    for i in range(P.PIN_LOOKS * 4):
        flip = 560 if i % 2 == 0 else 583     # the cube's other face, 23 px up
        f.teach(0.9, [(960, flip)])
    assert not f.is_pinned(960, 560)
    assert not f.is_pinned(960, 583)


def test_the_raw_marks_of_the_same_cube_are_stable_and_do_pin():
    f = P.Pinned()
    for _ in range(P.PIN_LOOKS + 2):
        f.teach(0.9, [(960, 560), (960, 583)])
    assert f.is_pinned(960, 560) and f.is_pinned(960, 583)


def test_the_detector_hands_back_its_marks_on_request(monkeypatch):
    """The coin detector's marks are its sightings' centres (vision/coins
    finds one position per coin, so there is no face-flipping to avoid)."""
    from hivemind.vision import coins, tokens
    frame = np.full((1080, 1920, 3), (90, 150, 70), np.uint8)
    # two candidates on one coin and one elsewhere, as vision/coins.look hands them
    monkeypatch.setattr(coins, "look", lambda f, *a, **k: [
        (700.0, 600.0, 80.0, 7.0, 3.0), (712.0, 596.0, 90.0, 5.0, 2.5),
        (1300.0, 500.0, 60.0, 6.0, 2.2)])
    marks: list = []
    found = tokens.detect(frame, marks=marks)
    assert sorted(marks) == sorted((s.x, s.y) for s in found) == [(700, 600), (1300, 500)]
    assert [s.faces for s in found] == [2, 1]


def test_asking_for_the_marks_costs_nothing_when_nothing_is_there():
    from hivemind.vision import tokens
    marks: list = []
    assert tokens.detect(np.zeros((1080, 1920, 3), np.uint8), marks=marks) == []
    assert marks == []


def test_the_memory_is_bounded_and_the_real_pins_survive_it():
    """A moving world creates a fresh spot for every mark, none of which will
    ever pin, and the lookup is linear in the list. MEASURED over the
    2,380-sample run: unbounded it reached 1,772 spots at 1.67 ms a look;
    capped it holds 400 at 0.34 ms and finds the same pins."""
    f = P.Pinned(memory=20)
    for i in range(P.PIN_LOOKS * 6):
        world = [(100 + i * 17 + j * 40, 700) for j in range(12)]
        f.teach(0.9, [(960, 560)] + world)
    assert len(f._spots) <= 20
    assert f.is_pinned(960, 560), "the cap lost the one spot that mattered"


def test_it_stays_fast_over_a_long_run():
    import time
    f = P.Pinned()
    started = time.perf_counter()
    looks = 600
    for i in range(looks):
        world = [(100 + i * 13 + j * 37, 600 + (j % 5) * 30) for j in range(20)]
        f.keep(0.9, [(960, 560)] + world)
    each = (time.perf_counter() - started) / looks
    assert each < 0.005, f"{each * 1000:.1f} ms a look is too slow to run live"

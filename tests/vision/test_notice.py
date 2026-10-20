"""The live view's overlay: only real detections, and cheap enough to run.

THE OWNER ASKED FOR IT -- "i wanna see the Ai highlighting fetures and noticing
them" -- and then caught it missing the thing he most wanted to see: "on the
ais view i dont see it highlighting token". The token and health-bar detectors
were both built earlier the same day; this file was simply never updated, so
the overlay drew three HUD rectangles and nothing else.
"""
from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from hivemind.vision import nameplate, notice, tokens


def _canvas(colour=(90, 150, 70)):
    return np.full((1080, 1920, 3), colour, np.uint8)


def _one_token(confidence=0.8, x=700, y=600):
    """The detector's answer, stood in for: what is drawn is the point here,
    and what the detector finds on real frames is tests/vision/test_tokens.py."""
    hit = tokens.Sighting(x=x, y=y, area=6400, confidence=confidence,
                          box=(x - 40, y - 40, 80, 80), why="coin p 0.9990")
    return lambda frame, **kw: [hit]


class _detector:
    """`with _detector(fn):` swaps tokens.detect for the block."""
    def __init__(self, fn):
        self.fn = fn

    def __enter__(self):
        self.original, tokens.detect = tokens.detect, self.fn

    def __exit__(self, *exc):
        tokens.detect = self.original


def _put_bar(img, x, y, w=140, h=24):
    """A mob health bar as this client draws it: UI green, white text inside."""
    img[y:y + h, x:x + w] = (60, 230, 60)
    for gx in range(x + w // 3, x + w // 3 + w // 4, 10):
        img[y + 5:y + h - 5, gx:gx + 3] = (245, 245, 245)


def kinds_in(found):
    return {d["kind"] for d in found}


# ---- the HUD boxes were always there --------------------------------------
def test_the_hud_regions_are_always_pointed_at():
    found = notice.notice(_canvas())
    labels = " ".join(d["label"] for d in found)
    assert "pollen" in labels and "honey" in labels


def test_a_reading_decorates_its_box():
    found = notice.notice(_canvas(), {"honey": "16,329,246"})
    assert any("16,329,246" in d["label"] for d in found)


# ---- what was missing ------------------------------------------------------
def test_a_token_is_drawn():
    with _detector(_one_token()):
        found = notice.notice(_canvas())
    assert "token" in kinds_in(found)


def test_a_token_box_is_the_coins_square():
    """`Sighting` carried only a centre once, and the panel draws x/y/w/h."""
    with _detector(_one_token()):
        boxes = [d for d in notice.notice(_canvas()) if d["kind"] in ("token", "maybe")]
    assert boxes and all((d["x"], d["y"], d["w"], d["h"]) == (660, 560, 80, 80) for d in boxes)


def test_the_confidence_is_in_the_tag_on_the_chase_settings_scale():
    """gather.chase_confidence 70 and a pill reading "70%" are one number."""
    with _detector(_one_token(0.84)):
        boxes = [d for d in notice.notice(_canvas()) if d["kind"] == "token"]
    assert boxes and boxes[0]["tag"] == "token 84%"


def test_the_chasers_threshold_decides_ring_or_dot():
    with _detector(_one_token(0.6)):
        loose = notice.notice(_canvas(), chase_at=0.5)
        strict = notice.notice(_canvas(), chase_at=0.7)
    assert "token" in kinds_in(loose) and "maybe" not in kinds_in(loose)
    assert "maybe" in kinds_in(strict) and "token" not in kinds_in(strict)


def test_a_sighting_too_weak_to_chase_is_drawn_and_says_so():
    """"it walked past a token" and "it never saw a token" look identical
    unless the near-misses are drawn too."""
    weak = tokens.Sighting(x=700, y=600, area=200, confidence=0.2,
                           box=(690, 590, 20, 20))
    strong = tokens.Sighting(x=300, y=400, area=200, confidence=0.9,
                             box=(290, 390, 20, 20))
    original = tokens.detect
    tokens.detect = lambda frame, **kw: [weak, strong]
    try:
        found = notice._token_boxes(_canvas())
    finally:
        tokens.detect = original
    by_kind = {d["kind"]: d["label"] for d in found}
    assert "below the chase" in by_kind["maybe"]
    assert "below the chase" not in by_kind["token"]


def test_a_health_bar_is_drawn_as_a_mob():
    frame = _canvas()
    _put_bar(frame, 800, 400)
    found = notice.notice(frame)
    assert "mob" in kinds_in(found)
    assert any("health bar" in d["label"] for d in found)


def test_a_bloom_is_drawn_but_not_as_a_mob():
    plate = nameplate.Nameplate(x=800, y=400, w=140, h=24,
                                kind="bloom", text=0.1, pink=0.03)
    original = nameplate.find_all
    nameplate.find_all = lambda frame, **kw: [plate]
    try:
        found = notice._mob_boxes(_canvas())
    finally:
        nameplate.find_all = original
    assert kinds_in(found) == {"landmark"}


# ---- it must never break or slow the live view -----------------------------
def test_a_detector_that_throws_does_not_lose_the_overlay():
    original = tokens.detect
    tokens.detect = lambda frame, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        found = notice.notice(_canvas())
    finally:
        tokens.detect = original
    assert found, "the HUD boxes went with it"


def test_an_empty_or_missing_frame_is_not_an_error():
    assert notice.notice(None) == []
    assert notice.notice(np.zeros((0, 0, 3), np.uint8)) == []


def test_the_world_detectors_can_be_skipped():
    """MEASURED: the whole call is 30.3 ms and 25.8 of that is these two. The
    live view's budget at the configured 20 fps is 50 ms a frame, and neither
    a token nor a health bar can appear on the app home or a loading splash."""
    frame = _canvas()
    _put_bar(frame, 800, 400)
    full = notice.notice(frame)
    lean = notice.notice(frame, world=False)
    assert kinds_in(lean) == {"landmark"}
    assert len(lean) < len(full)


def test_it_is_fast_enough_for_the_live_view():
    frame = _canvas()
    notice.notice(frame)                      # warm the codepaths
    started = time.perf_counter()
    for _ in range(5):
        notice.notice(frame)
    each = (time.perf_counter() - started) / 5
    assert each < 0.05, f"{each * 1000:.0f} ms is most of a 20 fps frame"

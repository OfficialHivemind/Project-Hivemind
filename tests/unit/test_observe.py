"""Learning the map by watching someone play.

The signature is a coarse hue/saturation histogram, not an image hash. The
first version used a difference hash and MEASURED on the owner's real session
it turned 164 samples into 78 "places" -- one per sample, which is a trace and
not a map. See brain/observe.py for the numbers that replaced it.
"""
from __future__ import annotations

import json

import cv2
import numpy as np

from hivemind.brain.observe import (SAME_PLACE, PlayObserver, likeness,
                                    signature)


def place(hue: int, size=(180, 240)):
    """A scene dominated by one hue, as a field or a hive area would be."""
    img = np.zeros((size[0], size[1], 3), np.uint8)
    img[:, :] = (hue, 200, 180)
    noise = np.random.default_rng(hue).integers(0, 25, img.shape, dtype=np.uint8)
    return cv2.cvtColor(cv2.add(img, noise), cv2.COLOR_HSV2BGR)


def shifted(frame, amount=40):
    """The same place with the camera moved."""
    return np.roll(frame, amount, axis=1)


def test_the_same_place_from_a_moved_camera_still_matches():
    a = place(40)
    assert likeness(signature(a), signature(shifted(a))) >= SAME_PLACE


def test_different_places_do_not_match():
    assert likeness(signature(place(20)), signature(place(110))) < SAME_PLACE


def test_walking_around_one_place_does_not_invent_new_ones():
    """The failure that made the first version useless."""
    views = [place(40)] + [shifted(place(40), n) for n in (10, 25, 60, 90)]
    step = {"n": 0}

    def frames():
        frame = views[step["n"] % len(views)]
        step["n"] += 1
        return frame
    obs = PlayObserver(frames)
    for _ in range(20):
        obs.sample()
    assert len(obs.places) == 1, f"one place became {len(obs.places)}"


def test_a_single_odd_frame_does_not_mint_a_place():
    """Mid-jump, a cannon flash, a loading blink. Hysteresis covers these."""
    home, blip = place(40), place(150)
    order = [home, home, home, blip, home, home]
    step = {"n": 0}

    def frames():
        frame = order[min(step["n"], len(order) - 1)]
        step["n"] += 1
        return frame
    obs = PlayObserver(frames)
    for _ in range(len(order)):
        obs.sample()
    assert len(obs.places) == 1, "a one-frame blip became a place"


def test_a_real_move_is_recorded_once_it_persists():
    there = place(110)
    order = [place(40)] * 3 + [there] * 3
    step = {"n": 0}

    def frames():
        frame = order[min(step["n"], len(order) - 1)]
        step["n"] += 1
        return frame
    obs = PlayObserver(frames)
    for _ in range(len(order)):
        obs.sample()
    assert len(obs.places) == 2
    assert sum(obs.links.values()) >= 1, "the move between places was not linked"


def test_notes_are_taken_now_and_then_not_every_sample():
    """A note costs a second or two of model time; the answer does not change
    that fast."""
    clock = [0.0]
    asked = []
    obs = PlayObserver(lambda: place(40), clock=lambda: clock[0],
                       take_note=lambda f: (asked.append(1), "walking north")[1],
                       note_every=20.0)
    for tick in range(10):
        clock[0] = tick * 3.0
        obs.sample()
    assert 1 <= len(asked) <= 3, f"took {len(asked)} notes in 30s"
    assert any(p.notes for p in obs.places), "no note was kept"


def test_a_broken_capture_is_counted_not_fatal():
    def boom():
        raise RuntimeError("capture died")
    obs = PlayObserver(boom)
    assert obs.sample() is None
    assert obs.skipped == 1
    assert PlayObserver(lambda: None).sample() is None


def test_a_note_taker_that_breaks_does_not_stop_the_mapping():
    def boom(frame):
        raise RuntimeError("the model died")
    obs = PlayObserver(lambda: place(40), take_note=boom, note_every=0.0)
    obs.sample()                 # hysteresis: the first look only proposes
    assert obs.sample() is not None


def test_the_map_saves_as_readable_json(tmp_path):
    obs = PlayObserver(lambda: place(40))
    obs.sample()                 # proposes
    obs.sample()                 # confirms, and the place is created
    data = json.loads(obs.save(tmp_path / "map.json").read_text())
    assert data["places"][0]["visits"] == 1
    assert data["samples"] == 2


def test_the_observer_cannot_press_anything():
    """It watches a person play; it must not fight them for control."""
    import inspect
    from hivemind.brain import observe
    source = inspect.getsource(observe)
    for forbidden in ("vin.", "VirtualInput", ".tap(", ".press(", ".click("):
        assert forbidden not in source, (
            f"{forbidden!r} appears in the observer — it must send nothing")

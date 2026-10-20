"""Exploring: finding places, learning which pay, and remembering them.

The owner's diagnosis, which this exists to answer: it never seemed to know
where it was, even where it should know the map. It never did.
A place signature plus "did pollen rise here" is the first thing that lets the
bot answer "where am I" and "is this worth standing in".
"""
from __future__ import annotations

import random

import cv2
import numpy as np

from hivemind.brain.explore import Explorer


def place(hue: int, size=(180, 240)):
    img = np.zeros((size[0], size[1], 3), np.uint8)
    img[:, :] = (hue, 200, 180)
    noise = np.random.default_rng(hue).integers(0, 25, img.shape, dtype=np.uint8)
    return cv2.cvtColor(cv2.add(img, noise), cv2.COLOR_HSV2BGR)


class FakeInput:
    def __init__(self):
        self.pressed = []
        self.held_keys = set()

    def tap(self, key, ms=40):
        self.pressed.append(key)

    def release_all(self):
        self.held_keys.clear()

    class _Held:
        def __init__(self, inp, keys):
            self.inp, self.keys = inp, keys

        def __enter__(self):
            for k in self.keys:
                self.inp.pressed.append(k)
            return self.inp

        def __exit__(self, *exc):
            pass

    def held(self, *keys):
        return FakeInput._Held(self, keys)


class Reading:
    def __init__(self, value):
        self.value = value


def build(views, pollen_steps, **kwargs):
    seen = {"n": 0}
    pol = {"n": 0}

    def frames():
        frame = views[min(seen["n"], len(views) - 1)]
        seen["n"] += 1
        return frame

    def pollen():
        value = pollen_steps[min(pol["n"], len(pollen_steps) - 1)]
        pol["n"] += 1
        return Reading(value)

    vin = FakeInput()
    return Explorer(vin, frames, pollen, sleep=lambda s: None,
                    clock=lambda: 0.0, rng=random.Random(4), **kwargs), vin


def test_it_learns_which_place_pays():
    """The only test that matters: pollen rose while standing there."""
    field = place(40)
    explorer, vin = build([field] * 20, [0, 500, 500, 1200] * 10)
    explorer.explore(steps=3)
    assert explorer.paying(), "it never noticed pollen rising"
    assert explorer.paying()[0].pollen_gained > 0


def test_a_place_where_nothing_grows_is_not_reported_as_paying():
    explorer, vin = build([place(40)] * 20, [700] * 20)
    explorer.explore(steps=3)
    assert explorer.paying() == []


def test_an_unchanging_view_is_treated_as_a_wall():
    """Grinding into a wall for twenty seconds is what the probe search did."""
    same = place(40)
    explorer, vin = build([same] * 30, [0] * 30)
    explorer._last_sig = None
    explorer.step("w")              # first look establishes the view
    assert explorer.step("w") is False, "it walked into a wall and called it progress"
    assert explorer.walls >= 1


def test_it_never_presses_a_key_that_could_leave_the_game():
    explorer, vin = build([place(40), place(110)] * 20, [0, 100] * 20)
    explorer.explore(steps=8)
    for forbidden in ("e", "escape", "enter", "return", "r"):
        assert forbidden not in vin.pressed, (
            f"{forbidden!r} reached the keyboard while wandering")


def test_what_it_learned_survives_the_process(tmp_path):
    """It has to learn -- a map that dies with the process is not
    learning, it is an experience."""
    explorer, vin = build([place(40)] * 20, [0, 900] * 10)
    explorer.explore(steps=3)
    path = explorer.save(tmp_path / "map.json")

    fresh, _ = build([place(40)] * 5, [0] * 5)
    assert fresh.load(path) >= 1
    assert fresh.paying(), "it forgot which place paid"


def test_it_can_answer_where_am_i():
    """The question this bot has never been able to answer."""
    here, elsewhere = place(40), place(110)
    explorer, vin = build([here] * 20, [0, 800] * 10)
    explorer.explore(steps=3)
    assert explorer.recognise(here) is not None
    assert explorer.recognise(elsewhere) is None, "it recognised the wrong place"


def test_a_blind_capture_does_not_invent_a_place():
    explorer, vin = build([None] * 10, [0] * 10)
    explorer.explore(steps=3)
    assert explorer.spots == []


# ---------------------------------------------------------------------------
# Mapping while a person drives
# ---------------------------------------------------------------------------
def test_watching_a_person_maps_without_touching_the_keyboard():
    """The owner asked whether their walking would help. It is worth more than
    the bot's random wander -- but only if the bot stops fighting them for the
    controls."""
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return ticks["n"] * 0.5
    explorer, vin = build([place(40)] * 40, [0, 400] * 20)
    explorer.clock = clock
    explorer.watch(seconds=4.0)
    assert explorer.spots, "it mapped nothing while watching"
    assert vin.pressed == [], "it pressed keys while a person was driving"


def test_it_does_not_stand_still_to_measure_pollen():
    """MEASURED: the old loop slept a whole second per sample to compare
    pollen before and after, which was 97% of its time -- a signature costs
    1.07 ms and a HUD read 22.8 ms. A walking player passed things it never
    sampled. Pollen is now tracked across samples instead.
    """
    slept = []
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return ticks["n"] * 0.1
    explorer, vin = build([place(40)] * 60, [0, 100, 250, 400] * 15)
    explorer.clock = clock
    explorer.sleep = slept.append
    explorer.watch(seconds=2.0)
    assert slept, "it never yielded at all"
    assert max(slept) <= 0.25, (
        f"it slept {max(slept)}s in one go — that is standing still, not scanning")


def test_pollen_is_credited_to_the_place_it_was_gained_in():
    """Across samples, not by pausing: the gain belongs to where the player
    was standing when it happened."""
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return ticks["n"] * 0.1
    field = place(40)
    explorer, vin = build([field] * 30, [0, 0, 500, 900, 1500] + [1500] * 25)
    explorer.clock = clock
    explorer.sleep = lambda s: None
    explorer.watch(seconds=1.0)
    assert explorer.paying(), "a rising counter was not credited to anywhere"


def test_the_model_never_blocks_the_scan():
    """A description arriving late is fine; a mapper that stops to wait for
    one is not -- the first note took nine seconds in a live run."""
    import time as _time
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return ticks["n"] * 0.1

    def slow(frame):
        _time.sleep(0.4)
        return "somewhere"
    explorer, vin = build([place(40)] * 40, [0] * 40, describe=slow)
    explorer.clock = clock
    explorer.sleep = lambda s: None
    started = _time.monotonic()
    explorer.watch(seconds=1.0)
    assert _time.monotonic() - started < 0.35, (
        "the scan waited for the model")


def test_a_watched_walk_and_a_wander_share_one_map(tmp_path):
    """Their walking and the bot's exploring must accumulate, not compete."""
    explorer, vin = build([place(40)] * 30, [0, 600] * 15)
    explorer.explore(steps=2)
    path = explorer.save(tmp_path / "map.json")

    later, _ = build([place(110)] * 30, [0, 300] * 15)
    assert later.load(path) >= 1
    ticks = {"n": 0}
    later.clock = lambda: (ticks.__setitem__("n", ticks["n"] + 1)
                           or ticks["n"] * 0.5)
    later.watch(seconds=3.0)
    assert len(later.spots) >= 2, "the watched walk did not add to the map"

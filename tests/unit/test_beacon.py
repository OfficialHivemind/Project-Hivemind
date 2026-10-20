"""Walking toward the "!" over a giver (act/beacon), and the steered hold that
carries it (act/hiverow): keys follow the marker, every way out releases them."""
from __future__ import annotations

import contextlib

import cv2
import numpy as np

from hivemind.act import beacon, hiverow
from hivemind.vision.questmarker import Marker


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def mark(x, y=100, h=60, w=15):
    return Marker(x=x, y=y, w=w, h=h, outline=0.3, beside=0.0)


class Frame:
    """A stand-in frame: what the fake `find` sees in it, and a width."""

    def __init__(self, markers, width=1920):
        self.markers, self.shape = list(markers), (1080, width, 3)


def steer(clock, **kw):
    return beacon.Toward(find=lambda frame: frame.markers, clock=clock, **kw)


# --- the steer -----------------------------------------------------------------

def test_no_marker_on_screen_ends_it_at_once():
    t = steer(Clock())
    assert t(Frame([])) is None
    assert t.reason == "no quest marker on screen"
    assert t.describe() == "toward a quest marker: no quest marker on screen"


def test_it_walks_forward_and_slides_toward_the_marker():
    clock = Clock()
    t = steer(clock)
    assert t(Frame([mark(960 + 300)])) == ("w", "d")
    clock.now += 0.1
    assert t(Frame([mark(960 + 100, h=64)])) == ("w",)          # inside the deadband
    clock.now += 0.1
    assert t(Frame([mark(960 - 200, h=68)])) == ("w", "a")


def test_the_marker_nearest_the_middle_is_the_one_walked_to_and_it_is_followed():
    clock = Clock()
    t = steer(clock)
    assert t(Frame([mark(300), mark(1100), mark(1800)])) == ("w", "d")
    assert t.first.x == 1100
    clock.now += 0.1
    # another marker turns up nearer the middle; the walk keeps to its own
    assert t(Frame([mark(980, y=300), mark(1180, h=64)])) == ("w", "d")
    assert t.marker.x == 1180


def test_a_look_or_two_without_it_keeps_walking_then_it_is_lost():
    clock = Clock()
    t = steer(clock)
    t(Frame([mark(1300)]))
    for _ in range(4):                                  # 0.4 s unseen: a bee crossing it
        clock.now += 0.1
        assert t(Frame([])) == ("w", "d")
    clock.now += 0.1
    assert t(Frame([])) is None                         # 0.5 s: over the top of the screen
    assert "went out of sight (last at 1300, 100)" in t.reason


def test_a_marker_that_holds_still_means_something_is_in_the_way():
    clock = Clock()
    t = steer(clock)
    keys = []
    for i in range(11):                                 # 1.0 s of the same few pixels
        keys.append(t(Frame([mark(1000 + i % 2, y=100 + i % 3, h=60)])))
        clock.now += 0.1
    assert keys[:-1] == [("w",)] * 10 and keys[-1] is None
    assert "stopped moving" in t.reason and "in the way" in t.reason


def test_a_marker_that_grows_as_it_is_walked_to_does_not_stall():
    clock = Clock()
    t = steer(clock)
    for i in range(30):                                 # 3 s, nearer every look
        assert t(Frame([mark(1000, y=100 - i, h=60 + 3 * i)])) == ("w",)
        clock.now += 0.1
    assert t.reason == ""
    assert "first seen at (1000, 100) for 2.9s" in t.describe()


def test_a_pause_between_holds_starts_the_watching_afresh():
    """A panel read between two holds (or the owner's Pause) is a gap: the
    marker standing still across it is not a stall, nor is it lost."""
    clock = Clock()
    t = steer(clock)
    for _ in range(5):
        t(Frame([mark(1000, h=60)]))
        clock.now += 0.1
    clock.now += 2.0                                    # the read
    assert t(Frame([mark(1000, h=60)])) == ("w",)       # not a stall
    clock.now += 0.1
    assert t(Frame([])) == ("w",)                       # nor lost
    assert round(t.walked, 1) == 0.5                    # the gap is not walking


def test_a_half_width_frame_halves_the_deadband():
    t = steer(Clock())
    assert t(Frame([mark(480 + 80)], width=960)) == ("w", "d")      # 160 px at 1920


def test_a_frame_that_will_not_be_read_is_a_look_without_it():
    clock = Clock()
    t = beacon.Toward(find=lambda f: (_ for _ in ()).throw(RuntimeError("bad")), clock=clock)
    assert t(Frame([])) is None and t.reason == "no quest marker on screen"


# --- the steered hold (act/hiverow) ------------------------------------------------

class Keys:
    """A fake input with press, release and held, logging what changes when."""

    def __init__(self, clock, point=None):
        self.clock, self.down, self.log = clock, [], []
        if point is not None:
            self.hold_point = point

    def press(self, *keys):
        for k in keys:
            if k not in self.down:
                self.down.append(k)
        self.log.append((round(self.clock(), 2), "press", keys))
        return True

    def release(self, *keys):
        for k in keys:
            if k in self.down:
                self.down.remove(k)
        self.log.append((round(self.clock(), 2), "release", keys))

    @contextlib.contextmanager
    def held(self, *keys):
        self.press(*keys)
        try:
            yield self
        finally:
            self.release(*keys)


class Plan:
    """A steer that asks for the keys it was given, one look at a time."""

    def __init__(self, *plan):
        self.plan, self.frames, self.reason = list(plan), [], ""

    def __call__(self, frame):
        self.frames.append(frame)
        if not self.plan:
            self.reason = "the plan ran out"
            return None
        keys = self.plan.pop(0)
        if keys is None:
            self.reason = "told to stop"
        return keys


def row(vin, clock, at_hive, holds, **kw):
    notes = []
    frames = []

    def grab():
        frames.append(object())
        return frames[-1]

    out = hiverow.find_along_row(vin, grab, at_hive, walkspeed=28.0, clock=clock,
                                 sleep=clock.sleep, holds=holds, on_note=notes.append,
                                 overrun="hold", **kw)
    return out, notes, frames


def test_the_keys_follow_the_steer_and_come_up_when_it_ends():
    clock = Clock()
    vin = Keys(clock)
    plan = Plan(("w",), ("w", "d"), ("w", "d"), ("w",), None)
    out, notes, _ = row(vin, clock, lambda f: False, ((plan, "toward it", 5.0),))
    assert vin.log == [(0.0, "press", ("w",)), (0.1, "press", ("d",)),
                       (0.3, "release", ("d",)), (0.4, "release", ("w",))]
    assert vin.down == []
    assert not out.ok
    assert notes[0] == "held toward it for 0.4s without the hive prompt — told to stop"


def test_the_prompt_test_and_the_steer_see_the_same_frame():
    clock = Clock()
    seen = []
    plan = Plan(("w",), ("w",), ("w",), None)
    row(Keys(clock), clock, lambda f: seen.append(f) and False, ((plan, "toward it", 5.0),))
    # one grab before the holds (already on it?), then one per look, shared
    assert plan.frames == seen[1:]


def test_nothing_is_pressed_when_there_is_no_marker_and_the_next_hold_runs():
    clock = Clock()
    vin = Keys(clock)
    plan = Plan(None)
    out, notes, _ = row(vin, clock, lambda f: False,
                        ((plan, "toward it", 5.0), ("a", "left", 1.0)))
    assert vin.log[0][1:] == ("press", ("a",))           # the steer pressed nothing
    assert notes[0].startswith("held toward it for 0.0s") and notes[0].endswith("told to stop")
    assert notes[1] == "held left for 1s without the hive prompt"


def test_the_prompt_ends_the_steered_hold_and_the_overrun_walks_back_its_keys():
    clock = Clock()
    vin = Keys(clock)
    state = {"looks": 0}

    def at_hive(frame):
        # seen on the fourth look, gone after the slide, back on the way back
        state["looks"] += 1
        if "s" in vin.down:
            state["back"] = True
        return state["looks"] == 4 or bool(state.get("back"))

    plan = Plan(("w",), ("w", "d"), ("w", "d"), ("w", "d"))
    out, notes, _ = row(vin, clock, at_hive, ((plan, "toward the quest marker", 5.0),))
    assert out.ok and out.direction == "toward the quest marker"
    assert out.key == ("w", "d")
    assert ("s", "a") in [keys for _, what, keys in vin.log if what == "press"]
    assert vin.down == []
    # the look before the holds, then three more: seen at 0.2 s into the hold
    assert "appeared after 0.2s holding toward the quest marker" in notes[0]


def test_the_owner_taking_the_controls_ends_it_with_the_keys_up():
    clock = Clock()
    vin = Keys(clock, point=lambda: None)
    plan = Plan(("w", "d"), ("w", "d"), ("w", "d"))
    out, _, _ = row(vin, clock, lambda f: False, ((plan, "toward it", 5.0),))
    assert vin.down == []
    assert "the owner took the controls during the search" in out.notes


def test_the_steered_hold_is_bounded():
    clock = Clock()
    vin = Keys(clock)
    plan = Plan(*([("w",)] * 100))
    out, notes, _ = row(vin, clock, lambda f: False, ((plan, "toward it", 2.0),))
    assert vin.down == [] and 1.9 <= clock.now <= 2.2
    assert notes[0].endswith("the time ran out")


# --- the two together, on drawn frames ------------------------------------------

ORANGE, OUTLINE, SKY = (40, 150, 252), (40, 40, 40), (235, 200, 120)


def drawn(x, y=200, bar=44):
    img = np.zeros((1080, 1920, 3), np.uint8)
    img[:] = SKY
    cv2.rectangle(img, (x - 3, y - 3), (x + 17, y + bar + 2), OUTLINE, -1)
    cv2.rectangle(img, (x, y), (x + 14, y + bar - 1), ORANGE, -1)
    cv2.rectangle(img, (x - 1, y + bar + 2), (x + 16, y + bar + 20), OUTLINE, -1)
    cv2.rectangle(img, (x + 1, y + bar + 5), (x + 13, y + bar + 17), ORANGE, -1)
    return img


def test_a_marker_off_to_the_right_is_slid_to_the_middle_and_walked_to():
    """A world where d carries the marker left 40 px a look and w makes it
    climb; the prompt shows once it is near the top, centred."""
    clock = Clock()
    vin = Keys(clock)
    pos = {"x": 1500, "y": 400}

    def grab():
        if "d" in vin.down:
            pos["x"] -= 40
        if "a" in vin.down:
            pos["x"] += 40
        if "w" in vin.down:
            pos["y"] -= 20
        return drawn(pos["x"], pos["y"])

    def at_hive(frame):
        return pos["y"] <= 120 and abs(pos["x"] + 7 - 960) <= 120

    toward = beacon.Toward(clock=clock)
    out = hiverow.find_along_row(vin, grab, at_hive, walkspeed=28.0, clock=clock,
                                 sleep=clock.sleep, overrun="hold",
                                 holds=((toward, "toward the quest marker", 6.0),))
    assert out.ok, (toward.reason, pos)
    assert toward.first.x == 1507
    assert any("d" in keys for _, what, keys in vin.log if what == "press")
    assert vin.down == []

"""Knowing where we are, and admitting when we do not. See vision/whereami.py."""
from __future__ import annotations

import numpy as np
import pytest

from hivemind.vision.whereami import (STALE_AFTER, Fix, Locator, field_in,
                                      field_names)

KNOWN = {"pumpkin": "pumpkin", "pine tree": "pine_tree", "pepper": "pepper",
         "mountain top": "mountain_top", "blue flower": "blue_flower",
         "strawberry": "strawberry", "spider": "spider"}


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def tick(self, seconds):
        self.t += seconds


def frame_with_feed():
    """A frame carrying one pill of the measured colour, so `feed.rows` fires."""
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    img[1034:1054, 1565:1904] = (170, 110, 40)     # BGR of the measured blue
    return img


def blank_frame():
    return np.zeros((1080, 1920, 3), dtype=np.uint8)


# ---- reading the name ----------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("+590 Honey (from Pumpkin Patch)", "pumpkin"),
    ("+2 Pollen (from Pine Tree Forest)", "pine_tree"),
    ("+640 honey (from mountain top field)", "mountain_top"),
    ("+9 (from Pepper Patch)", "pepper"),
    ("+1 Neonberry (from Blue Flower Field)", "blue_flower"),
    ("+38 Pollen (from Spider Field)", "spider"),
])
def test_it_reads_the_field_the_game_named(text, expected):
    assert field_in(text, KNOWN) == expected


@pytest.mark.parametrize("text", [
    "+22,410 Honey (from Puffshroom)",
    "+125 bond (from rhino beetle)",
    "+1,418 Honey (from Spider)",          # the mob's kill, 2026-10-05 23:50
    "defeated mantis! (+5 battle points)",
    "ninja bee advanced to level 7!",
    "", "   ", "from",
])
def test_things_that_are_not_places_are_refused(text):
    """The feed credits Puffshrooms and beetles. They are not somewhere to stand."""
    assert field_in(text, KNOWN) is None


def test_the_suffix_bug_that_hid_pumpkin_stays_fixed():
    """REGRESSION. Stripping only " field" silently dropped every Patch and
    Forest, which is most of the fields the owner actually farms."""
    for text, expected in (("(from Pumpkin Patch)", "pumpkin"),
                           ("(from Pine Tree Forest)", "pine_tree"),
                           ("(from Pepper Patch)", "pepper")):
        assert field_in(text, KNOWN) == expected


def test_the_shipped_knowledge_base_supplies_the_names():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    names = field_names(root / "data/knowledge/world.yaml")
    assert len(names) == 17
    assert names["pumpkin"] == "pumpkin"


def test_a_missing_knowledge_file_is_not_fatal(tmp_path):
    assert field_names(tmp_path / "gone.yaml") == {}


# ---- the gate ------------------------------------------------------------
def test_nothing_is_read_when_there_is_no_feed():
    """THE GUARD. Shown an empty crop the model invented "claim hive" in 11 of
    24 frames, so a reader must never see one."""
    calls = []

    def reader(image):
        calls.append(image)
        return "+590 Honey (from Pumpkin Patch)"

    loc = Locator(reader, known=KNOWN)
    assert loc.look(blank_frame()) is None
    assert calls == [], "it read a frame with no feed in it"
    assert loc.skipped == 1 and loc.reads == 0


def test_a_frame_with_a_feed_is_read():
    loc = Locator(lambda img: "+590 Honey (from Pumpkin Patch)", known=KNOWN)
    fix = loc.look(frame_with_feed())
    assert fix is not None and fix.field == "pumpkin"
    assert loc.reads == 1


def test_look_of_none_is_safe():
    loc = Locator(lambda img: "", known=KNOWN)
    assert loc.look(None) is None


def test_a_reader_that_throws_does_not_take_the_bot_down():
    def angry(image):
        raise RuntimeError("the model fell over")

    loc = Locator(angry, known=KNOWN)
    assert loc.look(frame_with_feed()) is None


# ---- believing it --------------------------------------------------------
def test_where_is_none_before_anything_is_seen():
    loc = Locator(lambda img: "", known=KNOWN)
    assert loc.where() is None
    assert "do not know" in loc.describe()


def test_a_fix_goes_stale():
    """A fix older than a walk between fields may describe the last field."""
    clock = FakeClock()
    loc = Locator(lambda img: "+590 Honey (from Pumpkin Patch)",
                  known=KNOWN, clock=clock)
    loc.look(frame_with_feed())
    assert loc.where() is not None
    clock.tick(STALE_AFTER + 1)
    assert loc.where() is None, "it still believed a fix older than the walk"


def test_no_feed_does_not_erase_a_fresh_fix():
    """Silence means the game did not say, not that we moved."""
    loc = Locator(lambda img: "+590 Honey (from Pumpkin Patch)", known=KNOWN)
    loc.look(frame_with_feed())
    loc.look(blank_frame())
    assert loc.where().field == "pumpkin"


# ---- the question routes never asked -------------------------------------
def test_arrived_is_true_only_when_the_game_said_so():
    loc = Locator(lambda img: "+590 Honey (from Pumpkin Patch)", known=KNOWN)
    assert loc.arrived("pumpkin", frame_with_feed()) is True
    assert loc.arrived("strawberry") is False


def test_arrived_is_false_when_nothing_confirmed_it():
    """An unconfirmed arrival is not an arrival. Assuming otherwise is how the
    bot farmed the red cannon and talked to a bear."""
    loc = Locator(lambda img: "", known=KNOWN)
    assert loc.arrived("pumpkin", blank_frame()) is False


def test_arriving_somewhere_else_is_reported_as_not_arrived():
    loc = Locator(lambda img: "+1 Honey (from Strawberry Field)", known=KNOWN)
    assert loc.arrived("pumpkin", frame_with_feed()) is False
    assert loc.where().field == "strawberry"


def test_it_only_announces_when_the_field_changes():
    said = []
    texts = iter(["+1 Honey (from Pumpkin Patch)"] * 3
                 + ["+1 Honey (from Pepper Patch)"])
    loc = Locator(lambda img: next(texts), known=KNOWN, emit=said.append)
    for _ in range(4):
        loc.look(frame_with_feed())
    assert len(said) == 2, "it narrated every sample instead of every move"


def test_history_keeps_every_fix():
    texts = iter(["+1 (from Pumpkin Patch)", "+1 (from Pepper Patch)"])
    loc = Locator(lambda img: next(texts), known=KNOWN)
    loc.look(frame_with_feed())
    loc.look(frame_with_feed())
    assert [f.field for f in loc.history] == ["pumpkin", "pepper"]


def test_fix_describes_itself_in_words_a_person_reads():
    fix = Fix(field="mountain_top", at=100.0)
    assert "mountain top" in fix.describe()
    assert "12s ago" in fix.describe(now=112.0)


# ---- the tracker, and the regression that cost the owner their game ---------
class FakeTrackerClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def tick(self, seconds):
        self.t += seconds


def settle(tracker, tries=200):
    """Wait for the worker thread to finish, without a fixed sleep."""
    import time as _t
    for _ in range(tries):
        if not tracker.busy:
            return True
        _t.sleep(0.01)
    return False


def test_the_tracker_never_captures_anything():
    """REGRESSION, 2026-09-20. This class used to capture on its own thread,
    making a FOURTH screencopy client on the nested compositor. Sober exited
    48 s and 43 s into two farm runs; a control pressing nothing survived
    three minutes, and six samples over three minutes with this switched off
    were all alive. It now only ever reads frames handed to it."""
    from hivemind.vision.whereami import Tracker
    tracker = Tracker(Locator(lambda img: "", known=KNOWN))
    assert not hasattr(tracker, "frames"), \
        "the tracker has a capture source again — that is what killed the game"


def test_offering_a_frame_reads_it():
    from hivemind.vision.whereami import Tracker
    clock = FakeTrackerClock()
    seen = []
    loc = Locator(lambda img: "+1 Honey (from Pumpkin Patch)", known=KNOWN)
    tracker = Tracker(loc, on_fix=lambda fix, frame: seen.append(fix),
                      clock=clock)
    assert tracker.offer(frame_with_feed()) is True
    assert settle(tracker)
    assert [f.field for f in seen] == ["pumpkin"]


def test_it_throttles_so_the_live_view_is_not_slowed():
    """The hook fires 20 times a second; almost every call must do nothing."""
    from hivemind.vision.whereami import Tracker
    clock = FakeTrackerClock()
    tracker = Tracker(Locator(lambda img: "", known=KNOWN), every=3.0,
                      clock=clock)
    assert tracker.offer(frame_with_feed()) is True
    assert settle(tracker)
    taken = sum(tracker.offer(frame_with_feed()) for _ in range(60))
    assert taken == 0, "it read again before the interval was up"
    clock.tick(3.1)
    assert tracker.offer(frame_with_feed()) is True


def test_a_slow_read_does_not_queue_up_more():
    """A read costs ~1.7s; at 20 Hz that is 34 frames offered during one."""
    import threading
    from hivemind.vision.whereami import Tracker
    release = threading.Event()

    def slow(image):
        release.wait(2.0)
        return "+1 Honey (from Pumpkin Patch)"

    clock = FakeTrackerClock()
    tracker = Tracker(Locator(slow, known=KNOWN), every=0.5, clock=clock)
    assert tracker.offer(frame_with_feed()) is True
    for _ in range(40):
        clock.tick(1.0)
        assert tracker.offer(frame_with_feed()) is False, "it started a second read"
    release.set()
    assert settle(tracker)


def test_offering_nothing_is_harmless():
    from hivemind.vision.whereami import Tracker
    tracker = Tracker(Locator(lambda img: "", known=KNOWN))
    assert tracker.offer(None) is False


def test_stopping_means_it_stops_taking_frames():
    from hivemind.vision.whereami import Tracker
    clock = FakeTrackerClock()
    tracker = Tracker(Locator(lambda img: "", known=KNOWN), clock=clock)
    tracker.stop()
    clock.tick(100)
    assert tracker.offer(frame_with_feed()) is False


def test_a_reader_that_throws_does_not_kill_the_worker():
    from hivemind.vision.whereami import Tracker
    def angry(image):
        raise RuntimeError("model fell over")
    clock = FakeTrackerClock()
    tracker = Tracker(Locator(angry, known=KNOWN), every=0.1, clock=clock)
    tracker.offer(frame_with_feed())
    assert settle(tracker)
    assert tracker.busy is False
    clock.tick(1.0)
    assert tracker.offer(frame_with_feed()) is True

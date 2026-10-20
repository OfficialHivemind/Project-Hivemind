"""The collecting-tool clicker: it must click, jitter, and refuse."""
from __future__ import annotations

import random

from hivemind.act.clicker import Clicker, MIN_INTERVAL


class FakeInput:
    def __init__(self):
        self.clicks = 0

    def click(self, x=None, y=None):
        self.clicks += 1


def test_it_clicks_when_the_gate_allows():
    vin = FakeInput()
    clicker = Clicker(vin, can_click=lambda: True)
    for _ in range(5):
        clicker.tick()
    assert vin.clicks == 5
    assert clicker.refused == 0


def test_it_never_clicks_when_the_world_is_not_on_screen():
    """A click lands wherever the pointer is, and the Roblox menu carries
    Leave and Log Out as ordinary buttons."""
    vin = FakeInput()
    clicker = Clicker(vin, can_click=lambda: False)
    for _ in range(10):
        clicker.tick()
    assert vin.clicks == 0
    assert clicker.refused == 10


def test_a_gate_that_raises_is_treated_as_no():
    """A broken detector must not start clicking into an unknown screen."""
    def boom():
        raise RuntimeError("capture died")
    vin = FakeInput()
    clicker = Clicker(vin, can_click=boom)
    assert clicker.tick() is False
    assert vin.clicks == 0


def test_the_gate_is_asked_every_time_not_cached():
    """A menu can open at any moment."""
    vin = FakeInput()
    answers = iter([True, True, False, False, True])
    clicker = Clicker(vin, can_click=lambda: next(answers))
    for _ in range(5):
        clicker.tick()
    assert vin.clicks == 3
    assert clicker.refused == 2


def test_intervals_are_jittered_not_periodic():
    """BeeTuxMacro clicks every 0.3s forever — a delta function no human
    produces. These must have real spread."""
    clicker = Clicker(FakeInput(), can_click=lambda: True,
                      rng=random.Random(7))
    values = [clicker.interval() for _ in range(400)]
    assert len(set(values)) > 350, "intervals repeat — that is a metronome"
    spread = max(values) - min(values)
    assert spread > 0.15, f"almost no jitter: spread {spread:.3f}s"
    assert all(v >= MIN_INTERVAL for v in values), "an interval became a burst"
    average = sum(values) / len(values)
    assert 0.2 < average < 0.8, f"average interval drifted to {average:.2f}s"


def test_stop_is_safe_without_start():
    Clicker(FakeInput()).stop()


def test_the_default_gate_refuses():
    """Constructed with no gate, it must do nothing rather than click blind."""
    vin = FakeInput()
    clicker = Clicker(vin)
    assert clicker.tick() is False
    assert vin.clicks == 0


def test_every_swing_lands_on_the_floor_not_where_a_menu_left_the_pointer():
    """MEASURED 2026-10-03 03:01:51: after an item use the pointer sat on the
    inventory button, and every swing of the trip toggled the list."""
    from hivemind.act.clicker import SWING_POINT

    class Points:
        def __init__(self):
            self.at = []

        def click(self, x=None, y=None):
            self.at.append((x, y))

    vin = Points()
    c = Clicker(vin, can_click=lambda: True)
    for _ in range(3):
        c.tick()
    assert vin.at == [SWING_POINT] * 3
    # the floor between the item dialogs and the hotbar, clear of the menu bar
    x, y = SWING_POINT
    assert 623 < y < 980 and x > 330

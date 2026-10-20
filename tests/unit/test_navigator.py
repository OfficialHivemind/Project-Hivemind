"""The model steering: it may choose a direction, never press a dangerous key."""
from __future__ import annotations

import numpy as np

from hivemind.brain.navigator import MOVES, Navigator


class FakeInput:
    def __init__(self):
        self.pressed: list[str] = []
        self.held_keys: set[str] = set()

    def tap(self, key, ms=40):
        self.pressed.append(key)

    class _Held:
        def __init__(self, inp, keys):
            self.inp, self.keys = inp, keys

        def __enter__(self):
            for k in self.keys:
                self.inp.pressed.append(k)
                self.inp.held_keys.add(k)
            return self.inp

        def __exit__(self, *exc):
            self.inp.held_keys.clear()

    def held(self, *keys):
        return FakeInput._Held(self, keys)


class FakeModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.asked = 0

    def ask(self, png, question):
        self.asked += 1
        text = self.replies[min(self.asked - 1, len(self.replies) - 1)]
        return type("A", (), {"text": text})()


def frames():
    return np.zeros((64, 96, 3), np.uint8)


def build(*replies, arrived=None):
    vin = FakeInput()
    nav = Navigator(vin, frames, FakeModel(*replies),
                    arrived=arrived or (lambda: False),
                    sleep=lambda s: None, encode=lambda f: b"png")
    return nav, vin


def test_it_walks_the_direction_the_model_chooses():
    nav, vin = build("LEFT\nthe hive is off to the left")
    nav.go("get to the hive", max_steps=1)
    assert MOVES["LEFT"] in vin.pressed


def test_it_stops_when_the_measured_check_confirms_arrival():
    seen = {"n": 0}

    def arrived():
        seen["n"] += 1
        return seen["n"] > 2
    nav, vin = build("FORWARD\nkeep going", arrived=arrived)
    assert nav.go("get to the hive", max_steps=10) is True
    assert nav.steps == 2, "it kept deciding after arriving"


def test_the_model_saying_arrived_is_not_enough():
    """Its opinion is not a measurement.

    Believing it would have the farm loop press the interact key wherever it
    happens to be standing -- which is how one cycle opened a Polar Bear
    quest dialogue.
    """
    nav, vin = build("ARRIVED\nwe are at the hive")
    assert nav.go("get to the hive", max_steps=3) is False
    assert nav.model.asked == 3, "it stopped on the model's say-so"


def test_it_never_presses_a_key_that_could_leave_the_game():
    """Whatever the model answers, only movement reaches the keyboard."""
    nav, vin = build("ENTER\npress enter to confirm",
                     "ESCAPE\nopen the menu",
                     "E\ninteract with this",
                     "RESET\nrespawn")
    nav.go("do something dangerous", max_steps=4)
    for forbidden in ("enter", "return", "escape", "e", "r"):
        assert forbidden not in vin.pressed, (
            f"{forbidden!r} reached the keyboard from a model answer")


def test_an_unparseable_answer_looks_around_rather_than_guessing():
    nav, vin = build("I think you should probably consider your options")
    nav.go("get to the hive", max_steps=1)
    assert nav.unknowns == 1
    assert vin.pressed == ["period"], "it should turn to look, not walk"


def test_a_model_that_breaks_does_not_move_the_character():
    class Boom:
        def ask(self, png, question):
            raise RuntimeError("ollama died")
    vin = FakeInput()
    nav = Navigator(vin, frames, Boom(), sleep=lambda s: None,
                    encode=lambda f: b"png")
    nav.go("get to the hive", max_steps=2)
    assert not any(k in vin.pressed for k in MOVES.values())


def test_a_decision_buried_in_prose_is_still_found():
    nav, vin = build("Looking at the screen, you should go RIGHT to reach it")
    nav.go("get to the hive", max_steps=1)
    assert MOVES["RIGHT"] in vin.pressed


def test_it_cannot_spin_in_circles_forever():
    """THE failure of the first live run: 25 x TURN_LEFT, three full circles.

    Every answer was individually reasonable and none of them knew about the
    others. Eight taps is a full turn, so a ninth turn in a row is
    looking at something already seen -- the character has to move instead.
    """
    nav, vin = build("TURN_LEFT\nthe hive must be to the left")
    nav.go("get to the hive", max_steps=14)
    # the CONSECUTIVE run is what matters -- turning again after walking
    # somewhere new is looking at a different view, which is fine
    longest = streak = 0
    for key in vin.pressed:
        streak = streak + 1 if key == "comma" else 0
        longest = max(longest, streak)
    assert longest <= 8, f"turned {longest} times in a row without moving"
    assert MOVES["FORWARD"] in vin.pressed, "it never actually went anywhere"
    assert nav.forced_moves >= 1


def test_what_was_already_tried_is_put_in_the_question():
    """The model cannot avoid repeating itself if it is not told it did."""
    nav, vin = build("TURN_LEFT\nlooking around")
    asked = []

    original = nav.model.ask

    def spy(png, question):
        asked.append(question)
        return original(png, question)
    nav.model.ask = spy
    nav.go("get to the hive", max_steps=4)
    assert "YOUR LAST ACTIONS" in asked[-1]
    assert "has not worked" in asked[-1], (
        "a repeated action must be called out, not just listed")


def test_the_first_question_has_no_history_to_show():
    nav, vin = build("FORWARD\ngo")
    asked = []
    original = nav.model.ask
    nav.model.ask = lambda png, q: (asked.append(q), original(png, q))[1]
    nav.go("get to the hive", max_steps=1)
    assert "YOUR LAST ACTIONS" not in asked[0]

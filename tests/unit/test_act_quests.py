"""The quest reader must never improvise on an unknown panel.

Every test here is about one of the four rules in `act/quests.py`: no keys are
ever pressed, nothing is believed until the panel says what it is, the only
recovery is the button that was already clicked, and a menu left open is
reported rather than hidden.
"""
from __future__ import annotations

import pytest

import numpy as np

from hivemind.act.quests import QuestRead, changed_fraction, read_quests
from hivemind.vision import questmenu


@pytest.fixture(autouse=True)
def _buttons_show(monkeypatch):
    """These drawn frames carry no HUD icons; whether a button shows is
    test_roblox_overlay's subject (vision/questmenu.button_check, A18)."""
    monkeypatch.setattr(questmenu, "button_check", lambda frame, name, template=None: (True, 1.0, 0.0))


def blank(value=0):
    return np.full((1080, 1920, 3), value, np.uint8)


def panel(value=0, fraction=0.5):
    """A frame with `fraction` of its rows painted a different colour."""
    frame = blank(value)
    rows = int(1080 * fraction)
    frame[:rows, :, :] = 200
    return frame


class FakeInput:
    """Records clicks. Raises if anything tries to press a key."""

    def __init__(self):
        self.clicks = []

    def click(self, x=None, y=None):
        self.clicks.append((x, y))

    def __getattr__(self, name):          # tap, press, held, type_text...
        raise AssertionError(
            f"quests.py must not use {name!r}: pressing keys at a Roblox menu "
            f"is how a bot finds Log Out")


def player(frames):
    seen = list(frames)

    def next_frame():
        return seen.pop(0) if len(seen) > 1 else seen[0]
    return next_frame


# ---- the change detector --------------------------------------------------
def test_identical_frames_have_not_changed():
    assert changed_fraction(blank(), blank()) == 0.0


def test_a_panel_opening_is_a_large_change():
    assert changed_fraction(blank(), panel()) > 0.4


def test_frames_of_different_shapes_are_not_compared():
    assert changed_fraction(blank(), np.zeros((10, 10, 3), np.uint8)) == 0.0


def test_a_missing_frame_is_not_a_change():
    assert changed_fraction(None, blank()) == 0.0


# ---- opening --------------------------------------------------------------
def test_it_reads_the_quests_when_the_panel_says_it_is_the_quest_menu():
    vin = FakeInput()
    frames = player([blank(), panel(), blank(), blank()])
    text = "Quests\nBlack Bear's Quest\n- Collect 100 pollen\n"
    out = read_quests(vin, frames, lambda f: text, sleep=lambda s: None)
    assert out.ok is True
    assert out.menu_open is False
    assert len(out.quests) >= 1


def test_nothing_opening_is_reported_and_nothing_else_is_clicked():
    vin = FakeInput()
    frames = player([blank(), blank()])
    out = read_quests(vin, frames, lambda f: "quests", sleep=lambda s: None)
    assert out.ok is False
    assert "nothing opened" in out.reason
    # Exactly one click: the one that tried to open it. A blind second click
    # on a pointer that may not have landed is how this hits something else.
    assert len(vin.clicks) == 1


def test_an_unexpected_panel_is_backed_out_of_not_read():
    vin = FakeInput()
    frames = player([blank(), panel(), blank(), blank()])
    out = read_quests(vin, frames, lambda f: "Are you sure you want to leave?",
                      sleep=lambda s: None)
    assert out.ok is False
    assert out.quests == []
    assert "does not say it is the quest menu" in out.reason
    # It closed using the SAME button, never a close button it guessed at.
    assert set(vin.clicks) == {vin.clicks[0]}


def test_a_menu_that_will_not_close_is_reported_as_still_open():
    vin = FakeInput()
    # Every frame after the first still shows the panel.
    frames = player([blank(), panel(), panel(), panel(), panel()])
    out = read_quests(vin, frames, lambda f: "Quests\nA quest\n",
                      sleep=lambda s: None)
    assert out.ok is True
    assert out.menu_open is True
    assert "MENU STILL OPEN" in out.describe()


def test_it_clicks_the_measured_quest_button():
    from hivemind.vision import questmenu
    vin = FakeInput()
    frames = player([blank(), panel(), blank(), blank()])
    read_quests(vin, frames, lambda f: "quests", sleep=lambda s: None)
    assert vin.clicks[0] == questmenu.quest_button()


def test_a_transcription_failure_does_not_raise():
    vin = FakeInput()
    frames = player([blank(), panel(), blank(), blank()])

    def boom(frame):
        raise RuntimeError("model unavailable")

    out = read_quests(vin, frames, boom, sleep=lambda s: None)
    assert out.ok is False
    assert out.quests == []


def test_no_frame_at_all_is_reported_without_clicking():
    vin = FakeInput()

    def no_frame():
        return None

    out = read_quests(vin, no_frame, lambda f: "quests", sleep=lambda s: None)
    assert out.ok is False
    assert vin.clicks == []


def test_describe_is_honest_about_a_failure():
    assert "did not read" in QuestRead(reason="because").describe()

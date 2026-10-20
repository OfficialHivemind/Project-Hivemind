"""A menu routine must notice when it is no longer in a menu.

REGRESSION for 2026-09-20. The app was genuinely on its home screen, the join
WORKED, and `join_private_server` carried on scrolling and clicking for two
minutes because nothing asked whether the world had loaded. Those inputs went
into the game. The owner found their character on a ledge above the map while
the log still read "app home after 8s".
"""
from __future__ import annotations

import numpy as np

from hivemind.act.join import arrived, join_private_server
from hivemind.vision import screenstate as ss


class FakeUI:
    """A UI whose screen turns into the game world after N looks."""

    def __init__(self, becomes_game_after: int | None = None):
        self.becomes_game_after = becomes_game_after
        self.looks = 0
        self.scrolls = 0
        self.clicks = 0
        self.trace = []

    def frame(self):
        self.looks += 1
        return np.zeros((1080, 1920, 3), dtype=np.uint8)

    def scroll(self, *a, **kw):
        self.scrolls += 1

    def click(self, *a, **kw):
        self.clicks += 1

    def wait_for(self, *states, timeout=0):
        return ss.Screen.IN_GAME


def patch_classify(monkeypatch, ui, in_game_from: int):
    """classify() reports the world once the UI has been looked at enough."""
    def fake(frame):
        return (ss.Screen.IN_GAME if ui.looks >= in_game_from
                else ss.Screen.APP_HOME)
    monkeypatch.setattr("hivemind.act.join.ss.classify", fake)


def test_arrived_is_false_on_the_app_home(monkeypatch):
    ui = FakeUI()
    patch_classify(monkeypatch, ui, in_game_from=10_000)
    assert arrived(ui) is False


def test_arrived_is_true_in_the_world(monkeypatch):
    ui = FakeUI()
    patch_classify(monkeypatch, ui, in_game_from=0)
    assert arrived(ui) is True


def test_a_capture_failure_is_not_an_arrival(monkeypatch):
    class Broken(FakeUI):
        def frame(self):
            raise RuntimeError("capture died")
    assert arrived(Broken()) is False


def test_it_does_not_touch_anything_when_already_in_game(monkeypatch):
    """THE HEADLINE CASE. No scrolls, no clicks, straight out."""
    ui = FakeUI()
    patch_classify(monkeypatch, ui, in_game_from=0)
    result = join_private_server(ui, np.zeros((8, 8, 3), dtype=np.uint8))
    assert result.ok and "already in game" in result.reason
    assert ui.scrolls == 0, "it scrolled while standing in the world"
    assert ui.clicks == 0, "it clicked while standing in the world"


def test_it_stops_scrolling_the_moment_the_world_appears(monkeypatch):
    """The world can load mid-scroll. Every scroll after that lands in game."""
    ui = FakeUI()
    monkeypatch.setattr("hivemind.act.join.open_server_drawer",
                        lambda *a, **kw: True)
    monkeypatch.setattr("hivemind.act.join.wait_until_still", lambda *a, **kw: None)
    monkeypatch.setattr("hivemind.act.join.find_primary_button", lambda *a: None)
    patch_classify(monkeypatch, ui, in_game_from=4)

    result = join_private_server(ui, np.zeros((8, 8, 3), dtype=np.uint8))
    assert result.ok and "already in game" in result.reason
    assert ui.scrolls <= 4, (
        f"it kept scrolling after the world loaded ({ui.scrolls} scrolls)")
    assert ui.clicks == 0

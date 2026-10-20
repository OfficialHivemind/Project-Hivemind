"""The Roblox chat box left open (ROADMAP A12, act/quests close_chat): seen by
the chat icon's missing unread badge in the world, look-only, never Enter."""
from pathlib import Path

import cv2
import pytest

from hivemind.act import quests
from hivemind.stream import privacy

SCREENS = Path(__file__).resolve().parents[1] / "fixtures" / "screens"


def _frame(name):
    return cv2.imread(str(SCREENS / name))


def _badge_gone(frame):
    """in_game.png with its unread badge painted the top-bar pill's dark (no
    frame of the open chat exists: 0 of 358,353, stream/privacy)."""
    x, y, w, h = privacy.CHAT_BADGE
    frame[y:y + h, x:x + w] = (30, 30, 30)
    return frame


class Vin:
    def __init__(self):
        self.taps = []

    def tap(self, key):
        self.taps.append(key)


def test_the_badge_reads_closed_on_every_saved_screen():
    for name in ("in_game.png", "hive_make_honey.png", "field_earning.png",
                 "escape_menu.png", "reset_dialog.png", "loading_splash.png",
                 "loading_headless.png", "modal_join_error.png", "app_home.png"):
        assert quests.chat_open(_frame(name)) is False, name
    assert quests.chat_open(_badge_gone(_frame("in_game.png"))) is True
    # no HUD, no verdict: a loading screen has a dark pill and no badge
    assert quests.chat_open(None) is False


def test_look_only_presses_nothing_and_keeps_the_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(quests, "CHAT_DIR", tmp_path)
    monkeypatch.setattr(quests, "_chat_kept", [])
    vin, shown = Vin(), _badge_gone(_frame("in_game.png"))
    said = quests.close_chat(vin, lambda: shown, sleep=lambda s: None)
    assert vin.taps == [] and "chat would: " in said and "never Enter" in said
    assert len(list(tmp_path.glob("chat-*.jpg"))) == 1
    assert quests.close_chat(vin, lambda: _frame("in_game.png")) == ""


@pytest.mark.parametrize("after, taps", [("in_game.png", ["escape"]),
                                         ("escape_menu.png", ["escape", "escape"])])
def test_live_one_escape_and_a_second_only_on_the_menu(tmp_path, monkeypatch, after, taps):
    monkeypatch.setattr(quests, "CHAT_DIR", tmp_path)
    monkeypatch.setattr(quests, "CHAT_ESCAPE_LIVE", True)
    shown = [_badge_gone(_frame("in_game.png")), _frame(after)]
    vin = Vin()
    quests.close_chat(vin, lambda: shown.pop(0) if len(shown) > 1 else shown[0],
                      sleep=lambda s: None)
    assert vin.taps == taps and "enter" not in vin.taps

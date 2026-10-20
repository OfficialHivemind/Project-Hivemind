"""Re-attaching to the kept game looks more than once (audit 2026-10-13 #6).

MEASURED: run-960 11:49 and run-961 12:34 (3.7 min after a detach) judged the
kept game from one frame, "not in the world (no HUD)", and rejoined. Now about
5 s of looks, one Escape only for a menu a look has SEEN, then give up.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from hivemind.act import bootstrap
from hivemind.stream import privacy

SCREENS = Path(__file__).resolve().parents[1] / "fixtures" / "screens"


def drive(frames):
    """Run the looks over `frames` ('world', 'menu', 'other' or None)."""
    seq, pressed, slept = iter(frames), [], []
    seen, last, escaped = bootstrap.kept_game_in_world(
        lambda: next(seq), lambda f: f == "world", lambda f: f == "menu",
        lambda: pressed.append("escape"), sleep=slept.append)
    return seen, last, pressed, slept


def test_a_late_world_is_seen_without_a_key():
    seen, last, pressed, slept = drive([None, "other", "world"])
    assert seen and last == "world" and pressed == [] and slept == [1.0, 1.0]


def test_a_seen_menu_gets_one_escape_then_the_world():
    seen, _, pressed, _ = drive(["menu", "world"])
    assert seen and pressed == ["escape"]


def test_a_menu_that_stays_gets_one_escape_only_then_gives_up():
    seen, _, pressed, slept = drive(["menu"] * 6)
    assert not seen and pressed == ["escape"]
    assert sum(slept) == pytest.approx(5.0)


def test_no_escape_on_a_screen_that_is_not_seen_to_be_the_menu():
    seen, last, pressed, _ = drive(["other"] * 5 + [None])
    assert not seen and pressed == [] and last is None


@pytest.mark.parametrize("name, menu", [("escape_menu.png", True),
                                        ("reset_dialog.png", True),
                                        ("in_game.png", False),
                                        ("app_home.png", False),
                                        ("modal_join_error.png", False)])
def test_the_menu_is_seen_on_the_fixtures(name, menu):
    if not (SCREENS / name).exists():
        pytest.skip("the screen fixtures are in the live install only (owner's name on them)")
    assert privacy.menu_in_frame(cv2.imread(str(SCREENS / name))) is menu

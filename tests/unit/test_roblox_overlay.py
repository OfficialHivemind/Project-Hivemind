"""Roblox's own overlays over the HUD (ROADMAP A18, run-1005 18:15): a "Shop now"
promo toast lay over the HUD row, the rosette click opened the Robux Shop, and
every walk after pushed against it. On the run's own frames."""
from pathlib import Path

import cv2
import pytest

from hivemind.act import badges, quests
from hivemind.vision import questmenu

VAR = Path.home() / "Hivemind/var"
TOAST = VAR / "quest_reads" / "close-181529-before.jpg"       # toast over the HUD
SHOP = VAR / "badges" / "20261014-181516" / "page.jpg"          # the Robux Shop
WORLD = next(iter(sorted((VAR / "routes" / "attempt-1002").glob(
    "155002-*-00-start.jpg"))), VAR / "missing.jpg")           # the templates' source
if not all(p.exists() for p in (TOAST, SHOP, WORLD)):
    pytest.skip("run-1005's frames are not on this machine", allow_module_level=True)
FRAMES = {k: cv2.imread(str(p)) for k, p in
          (("toast", TOAST), ("shop", SHOP), ("world", WORLD))}
ROSETTE, TOAST_X, SHOP_X = (195, 128), (263, 88), (578, 272)


class Game:
    """What the screen shows, moved on by the clicks the run-1005 game took."""
    def __init__(self, state):
        self.state, self.clicks = state, []
        self.moves = {("toast", TOAST_X): "world", ("toast", ROSETTE): "shop",
                      ("shop", SHOP_X): "world"}

    def click(self, x, y):
        self.clicks.append((x, y))
        self.state = self.moves.get((self.state, (x, y)), self.state)

    def move_mouse(self, x, y):
        pass

    def frame(self):
        return FRAMES[self.state].copy()


class On:
    def bool(self, key):
        return True


def test_the_overlays_and_the_buttons_are_told_apart():
    assert questmenu.roblox_overlay(FRAMES["toast"]) == ("promo", TOAST_X)
    assert questmenu.roblox_overlay(FRAMES["shop"]) == ("shop", SHOP_X)
    assert questmenu.roblox_overlay(FRAMES["world"]) is None
    for name in ("quests", "badges", "settings"):          # the toast covers them
        assert questmenu.button_check(FRAMES["toast"], name)[0] is False
        assert questmenu.button_check(FRAMES["world"], name)[0] is True


def test_badge_look_closes_the_toast_first_and_never_clicks_shop_now(tmp_path):
    game = Game("toast")                                     # the rosette: no-op here
    got = badges.look(game, game.frame, lambda img: "",
                      sleep=lambda s: None, settings=On(), keep_dir=tmp_path)
    assert game.clicks == [TOAST_X, ROSETTE] and game.state == "world"
    assert "nothing opened" in got.reason


def test_a_shop_opened_instead_is_closed_by_its_own_x(tmp_path):
    game = Game("world")
    game.moves[("world", ROSETTE)] = "shop"                  # run-1005's click
    got = badges.look(game, game.frame, lambda img: "System",
                      sleep=lambda s: None, settings=On(), keep_dir=tmp_path)
    assert game.clicks == [ROSETTE, SHOP_X]                 # never the rosette again
    assert game.state == "world" and got.menu_open is False
    assert "Robux Shop opened" in got.reason


def test_a_route_never_sets_off_under_the_shop():
    game = Game("shop")
    said = quests.close_side_panel(game, game.frame, sleep=lambda s: None)
    assert game.clicks == [SHOP_X] and "closed Roblox's Robux Shop" in said
    stuck = Game("shop")
    stuck.moves.clear()                                      # the X does nothing
    said = quests.close_side_panel(stuck, stuck.frame, sleep=lambda s: None)
    assert stuck.clicks == [SHOP_X] and "did not close" in said

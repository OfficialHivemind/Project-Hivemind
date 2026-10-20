"""The Bee Swarm tile is found by its thumbnail, not assumed to be first.

MEASURED 2026-09-22: the Continue row is recent games newest first; with
another game played last, four attempts clicked that game and looked for a
private-server Join button it does not have.
"""
from __future__ import annotations

import pathlib

import cv2
import numpy as np
import pytest

from hivemind.act import join
from hivemind.vision import templates as T

ROOT = pathlib.Path(__file__).resolve().parents[2]
HOME = ROOT / "tests/fixtures/screens/app_home.png"
TILE = ROOT / "data/templates/ui/bss_tile.png"


@pytest.fixture
def home():
    frame = cv2.imread(str(HOME))
    if frame is None:
        pytest.skip("home fixture missing")
    return frame


@pytest.fixture
def tile():
    return T.load(TILE)


class UI:
    def __init__(self, frame):
        self._frame = frame
        self.clicks: list[tuple[int, int]] = []

    def focus(self): pass

    def frame(self): return self._frame

    def click(self, x, y, settle=0.0): self.clicks.append((int(x), int(y)))

    def scroll(self, *a, **kw): pass


def test_the_tile_is_found_where_it_is(home, tile):
    hit = join.find_bss_tile(home, tile)
    assert hit is not None and hit.score > 0.95
    assert abs(hit.centre[0] - join.BSS_TILE[0]) <= 4 and abs(hit.centre[1] - join.BSS_TILE[1]) <= 6


def test_a_bee_swarm_that_moved_to_the_second_slot_is_still_found(home, tile):
    """Another game played last: Bee Swarm slides one tile right."""
    moved = home.copy()
    x0, x1 = 128, 256
    band = home[862:990, x0:x1].copy()
    moved[862:990, x0:x1] = home[862:990, 274:402]          # Arsenal takes the first slot
    moved[862:990, 274:402] = band                         # Bee Swarm the second
    hit = join.find_bss_tile(moved, tile)
    assert hit is not None
    assert abs(hit.centre[0] - 338) <= 4, hit
    ui = UI(moved)
    said = []
    join.open_server_drawer(ui, servers_label=np.zeros((10, 40, 3), np.uint8),
                            max_scrolls=0, bss_tile=tile, stage=said.append)
    assert ui.clicks[0][0] == hit.centre[0], ui.clicks
    assert any("Bee Swarm's tile at" in t for t in said), said


def test_when_the_thumbnail_is_absent_nothing_is_clicked_and_it_says_so(home, tile, monkeypatch):
    """An unrecognised tile can be a shop item (22:47:28): no blind click on
    the first slot any more. (The search fallback, which clicks only the
    search box, has its own tests: test_join_search.)"""
    monkeypatch.setattr(join, "TILE_LOOK_SECONDS", 0.0)
    monkeypatch.setattr(join, "search_for_the_game", lambda ui, tile, note: None)
    blank = home.copy()
    blank[855:996, :] = (40, 40, 40)
    assert join.find_bss_tile(blank, tile) is None
    ui = UI(blank)
    said = []
    assert join.open_server_drawer(ui, servers_label=np.zeros((10, 40, 3), np.uint8),
                                   max_scrolls=0, bss_tile=tile, stage=said.append) is False
    assert ui.clicks == []
    assert any("not on the home" in t for t in said), said


def test_without_a_template_nothing_is_clicked(home):
    ui = UI(home)
    said = []
    assert join.open_server_drawer(ui, servers_label=np.zeros((10, 40, 3), np.uint8),
                                   max_scrolls=0, stage=said.append) is False
    assert ui.clicks == []
    assert any("no Bee Swarm tile template" in t for t in said), said


def test_a_home_with_bee_swarm_below_the_fold_is_scrolled_to(home, tile, monkeypatch):
    """2026-10-16 06:13: three Recommended rows pushed Continue off the
    screen; the home is scrolled down between looks and the tile then found."""
    monkeypatch.setattr(join, "TILE_LOOK_SECONDS", 0.0)
    blank = home.copy()
    blank[:, :] = (40, 40, 40)

    class Scrolling(UI):
        scrolls = 0

        def scroll(self, *a, **kw):
            self.scrolls += 1
            self._frame = home            # the Continue row comes into view

    ui = Scrolling(blank)
    said = []
    join.open_server_drawer(ui, servers_label=np.zeros((10, 40, 3), np.uint8),
                            max_scrolls=0, bss_tile=tile, stage=said.append)
    assert ui.scrolls >= 1 and ui.clicks, said        # scrolled, then clicked the tile
    assert any("Bee Swarm's tile at" in t for t in said), said


def test_a_tile_click_that_opened_nothing_is_clicked_again(home, tile):
    """2026-10-16 22:54-23:25: beside their game the first click only focused
    the window; the tile still in view is clicked again, at most TILE_RECLICKS."""
    ui = UI(home)                                   # the home never changes
    said = []
    join.open_server_drawer(ui, servers_label=np.zeros((10, 40, 3), np.uint8),
                            max_scrolls=0, bss_tile=tile, stage=said.append)
    assert len(ui.clicks) == 1 + join.TILE_RECLICKS, said
    assert sum("clicking it again" in t for t in said) == join.TILE_RECLICKS


def test_a_tile_click_that_worked_is_not_repeated(home, tile):
    class Opens(UI):
        def click(self, x, y, settle=0.0):
            super().click(x, y, settle)
            blank = home.copy()
            blank[:, :] = (40, 40, 40)
            self._frame = blank                     # the game page replaced the home

    ui = Opens(home)
    join.open_server_drawer(ui, servers_label=np.zeros((10, 40, 3), np.uint8),
                            max_scrolls=0, bss_tile=tile, stage=lambda t: None)
    assert len(ui.clicks) == 1

"""Memory Match: Natro's strategy, played on a board drawn here.

The board's constants are Natro's and not yet measured on this machine
(vision/memorymatch); these pin the player's logic -- a pair seen is claimed, a
paired tile is never clicked again, a click that turns nothing over stops the
game -- on a fake board that behaves the way the game's does.
"""
from __future__ import annotations

import random

import cv2
import numpy as np
import pytest

from hivemind.act import memorymatch as mm
from hivemind.vision import memorymatch as vm


def _fake_time():
    """A clock that a sleep moves on, so act/memorymatch's settle gap
    (SETTLE_S between two alike looks) passes without waiting for real."""
    now = [0.0]

    def sleep(s):
        now[0] += s
    return {"sleep": sleep, "clock": lambda: now[0]}


def _prizes(n, seed=3):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        p = np.zeros((vm.FACE, vm.FACE, 3), np.uint8)
        for _ in range(6):                           # a few bold shapes, like an icon
            colour = tuple(int(c) for c in rng.integers(40, 255, 3))
            centre = tuple(int(c) for c in rng.integers(8, vm.FACE - 8, 2))
            cv2.circle(p, centre, int(rng.integers(5, 14)), colour, -1)
        out.append(p)
    return out


class FakeBoard:
    """16 tiles, 8 pairs; a pair that differs turns back at the next click;
    the board closes when all are paired or `chances` turns are used."""

    def __init__(self, tiles=16, chances=12, seed=5, dead=False):
        self.board = vm.Board(tiles=tiles, centres=vm.centres(tiles))
        prizes = _prizes(tiles // 2, seed)
        layout = [i // 2 for i in range(tiles)]
        random.Random(seed).shuffle(layout)
        self.layout, self.prizes = layout, prizes
        self.up: set[int] = set()
        self.paired: set[int] = set()
        self.turn: list[int] = []
        self.chances, self.turns, self.clicks = chances, 0, []
        self.dead = dead

    def _tile_at(self, x, y):
        for i, (cx, cy) in enumerate(self.board.centres):
            if abs(cx - x) <= 20 and abs(cy - y) <= 20:
                return i
        return None

    def click(self, x, y):
        self.clicks.append((x, y))
        tile = self._tile_at(x, y)
        assert tile is not None, f"a click off the tiles at ({x}, {y})"
        assert tile not in self.paired, f"a paired tile clicked: {tile}"
        if self.dead:
            return
        if len(self.turn) == 2:                       # the last pair turns back
            a, b = self.turn
            if self.layout[a] != self.layout[b]:
                self.up -= {a, b}
            self.turn = []
        self.up.add(tile)
        self.turn.append(tile)
        if len(self.turn) == 2:
            self.turns += 1
            a, b = self.turn
            if self.layout[a] == self.layout[b]:
                self.paired |= {a, b}

    @property
    def open(self):
        return len(self.paired) < len(self.layout) and self.turns < self.chances

    def capture(self):
        frame = np.full((1080, 1920, 3), 90, np.uint8)
        for i, (cx, cy) in enumerate(self.board.centres):
            cv2.rectangle(frame, (cx - 35, cy - 35), (cx + 35, cy + 35), vm.HIDDEN_BGR, -1)
            if i in self.up:
                h = vm.FACE // 2
                frame[cy - h:cy + h, cx - h:cx + h] = self.prizes[self.layout[i]]
        return frame

    def read_board(self, frame):
        return self.board if self.open else None


def _play(fake, **kw):
    return mm.play(fake.capture, fake.click, fake.board, **_fake_time(),
                   read_board=fake.read_board, **kw)


# ---- the geometry and the looks ------------------------------------------------------
def test_natros_grid():
    assert vm.centres(16)[0] == (840, 420) and vm.centres(16)[-1] == (1080, 660)
    assert vm.centres(20)[0] == (800, 420) and len(vm.centres(20)) == 20


def test_a_brown_tile_is_hidden_and_a_prize_is_not():
    brown = np.full((vm.FACE, vm.FACE, 3), vm.HIDDEN_BGR, np.uint8)
    assert vm.is_hidden(brown)
    assert not vm.is_hidden(_prizes(1)[0])


def test_the_same_prize_a_little_shifted_matches_and_another_does_not():
    a, b = _prizes(2)
    shifted = np.roll(a, 2, axis=1)
    assert vm.same_prize(a, shifted)
    assert not vm.same_prize(a, b)


# ---- the play --------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(8))
def test_every_board_is_cleared_and_no_paired_tile_is_clicked(seed):
    fake = FakeBoard(seed=seed, chances=30)
    game = _play(fake, most_turns=30)
    assert fake.paired == set(range(16)), game.stopped
    assert game.pairs == 8
    assert game.turns <= 15, f"{game.turns} turns for 8 pairs"


def test_a_click_that_turns_nothing_over_stops_the_game():
    fake = FakeBoard(dead=True)
    game = _play(fake)
    assert "did not turn over" in game.stopped
    assert len(fake.clicks) == 1, "one click, then nothing else"


def test_the_game_ends_when_the_board_closes():
    fake = FakeBoard(chances=3)
    game = _play(fake)
    assert game.turns == 3 and game.stopped == "the board closed"

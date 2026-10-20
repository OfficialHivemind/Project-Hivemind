"""act/questscroll on a fake game made from a real open quest menu.

The fake is var/quest_reads/close-065946-open.jpg (a real frame) with its list
made two panels tall, moved `px` rows a notch under the wheel, and the
scrollbar's thumb drawn where that puts it -- or, with `camera`, a wheel the
camera takes instead, which changes the world beside the list.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pytest

from hivemind.act import questscroll as qs
from hivemind.act import quests
from hivemind.vision.inventory import SCROLL_AT
from hivemind.vision import questlist as ql

ROOT = pathlib.Path(__file__).resolve().parents[2]
KEPT = ROOT / "var" / "quest_reads"


def _frames():
    cv2 = pytest.importorskip("cv2")
    opened, world = KEPT / "close-065946-open.jpg", KEPT / "close-065946-before.jpg"
    if not (opened.exists() and world.exists()):
        pytest.skip("the kept open menu is not here")
    return cv2.imread(str(opened)), cv2.imread(str(world))


class Game:
    def __init__(self, px=100, camera=False, tall=True, opened=True):
        self.base, self.world = _frames()
        crop = ql.list_crop(self.base)
        self.list = np.vstack([crop, crop[::-1]]) if tall else crop
        self.view = crop.shape[0]
        self.offset, self.px, self.camera, self.zoom = 0, px, camera, 0
        self.turns, self.moves, self.open = [], [], opened
        self.stale, self.garble_after = False, None
        self.smudge_after = None

    def frame(self):
        if not self.open:
            return self.world.copy()
        f = self.base.copy()
        x0, y0, x1, y1 = ql.LIST_BOX
        f[y0:y1, x0:x1] = self.list[self.offset:self.offset + self.view]
        if self.garble_after is not None and len(self.turns) > self.garble_after:
            f[y0:y1, x0:x1] = np.random.default_rng(len(self.turns)).integers(
                0, 255, (y1 - y0, x1 - x0, 3), dtype=np.uint8)
        if self.smudge_after is not None and len(self.turns) > self.smudge_after:
            # something light over the band a page is placed by (a bee, a
            # sparkle): 80 x 60 px, the day's 0.86-0.89 at the true move
            f[y0 + 10:y0 + 70, x0 + 20:x0 + 100] = (235, 235, 235)
        track = ql.TRACK_BOTTOM - ql.TRACK_TOP + 1
        rows = int(track * self.view / self.list.shape[0])
        top = ql.TRACK_TOP + int(track * self.offset / self.list.shape[0])
        f[ql.TRACK_TOP:ql.TRACK_BOTTOM + 1, 309:320] = (120, 110, 80)
        f[top:top + rows, 309:320] = (197, 195, 179)
        if self.zoom:
            f[:, 400:] = (f[:, 400:] // 2 + 60).astype(np.uint8)
        return f

    # the input
    def move_mouse(self, x, y):
        self.moves.append((x, y))

    def scroll(self, n):
        self.turns.append(n)
        if self.camera:
            self.zoom += n
            return
        self.offset = max(0, min(self.list.shape[0] - self.view, self.offset + n * self.px))

    def click(self, x, y):
        self.open = not self.open


def _read(game, notes=None):
    notes = [] if notes is None else notes
    return qs.read_below(game, game.frame, lambda s: None, notes.append, game.frame()), notes


def test_the_whole_list_is_pictured_and_left_at_the_top():
    game = Game(px=100)
    out, notes = _read(game)
    assert game.moves[0] == SCROLL_AT
    assert out.px_per_notch == 100 and out.complete and out.back_at_top
    assert game.offset == 0
    assert game.turns[0] == 1 and game.turns[1] == int(qs.PAGE_ADVANCE * game.view / 100)
    canvas = ql.stitch(out.pages)
    assert canvas.shape == game.list.shape and (canvas == game.list).all()
    assert ql.thumb(out.last).at_top


def test_any_notch_size_is_measured_not_assumed():
    for px in (37, 64, 150):
        game = Game(px=px)
        out, _ = _read(game)
        assert out.px_per_notch == px and out.complete and game.offset == 0
        assert (ql.stitch(out.pages) == game.list).all()


def test_a_notch_the_camera_takes_is_taken_back_and_nothing_more_turns():
    game = Game(camera=True)
    out, _ = _read(game)
    assert game.turns == [1, -1] and game.zoom == 0
    assert len(out.pages) == 1 and "camera" in out.reason and out.back_at_top


def test_a_list_the_panel_shows_whole_is_not_scrolled():
    game = Game(tall=False)
    out, _ = _read(game)
    assert game.turns == [] and "whole list" in out.reason


def test_the_owners_take_over_turns_no_wheel():
    game = Game()
    game.stale = True
    out, _ = _read(game)
    assert game.turns == [] and out.reason == qs.HELD


def test_a_page_that_does_not_match_stops_it_and_it_still_goes_back_up():
    game = Game(px=100)
    game.garble_after = 1                 # after the probe notch: a picture that is not the list
    out, _ = _read(game)
    assert len(out.pages) == 2 and "guess" in out.reason
    assert game.turns[-1] == -qs.TOP_BURST


def test_the_closed_menu_turns_no_wheel():
    game = Game(opened=False)
    out, _ = _read(game)
    assert game.turns == [] and "no scrollbar" in out.reason


def test_every_piece_is_read_or_none_is_used():
    game = Game(px=100)
    out, _ = _read(game)
    calls = []
    texts, canvas, pieces = qs.transcribe(out, lambda img: calls.append(img.shape) or f"part {len(calls)}", 2, print)
    assert len(texts) == 2 and len(pieces) >= 2
    assert texts[0].splitlines() == [f"part {i + 1}" for i in range(len(pieces))]
    texts, _, _ = qs.transcribe(out, lambda img: "", 2, print)
    assert texts == []


class Settings:
    def __init__(self, scroll):
        self.scroll = scroll

    def bool(self, key):
        return {"quests.enabled": True, "quests.scroll": self.scroll}.get(key, False)


PAGE = ("Polar Bear: Candied Beetles\n"
        "Collect 150,000 Pollen from the Strawberry Field. 0/150,000\n"
        "Defeat 16 Rhino Beetles. Complete!")


def _quest_read(scroll):
    game = Game(px=100, opened=False)
    seen = {"in_round": 0}

    def piece(img):
        # the first piece of a read starts with the list's own first rows
        first = img.shape[0] >= 20 and (img[:20] == game.list[:20]).all()
        seen["in_round"] = 1 if first else seen["in_round"] + 1
        if first:
            return PAGE
        if seen["in_round"] == 2:
            return ("Limits of Language\nDiscover 25 Bee Types. Complete!\n"
                    "Craft 50 Ingredients with the Blender. 0/50")
        return "Defeat 50 Ants. 12/50"

    result = quests.read_quests(game, game.frame, lambda frame: PAGE, sleep=lambda s: None,
                                settings=Settings(scroll), transcribe_list=piece)
    return game, result


def test_the_quest_read_reads_the_whole_list_and_closes_the_menu():
    game, result = _quest_read(scroll=True)
    assert result.ok and not result.menu_open and not game.open
    names = [q.name for q in result.quests]
    assert "Limits of Language" in names, names
    limits = result.quests[names.index("Limits of Language")]
    assert any("Craft 50 Ingredients" in r for r in limits.requirements)
    assert PAGE in result.texts                     # the first page's reads stay
    assert game.offset == 0


def test_off_it_reads_the_first_page_only_and_turns_no_wheel():
    game, result = _quest_read(scroll=False)
    assert result.ok and game.turns == [] and len(result.quests) == 1


def test_a_page_a_bee_crosses_is_still_placed():
    # MEASURED 2026-10-06: 4 of 24 reads stopped at 0.86-0.89; the true move
    # matched 0.94-0.99 and nothing 10 px off it above 0.55 (qs.PAGE_MATCH)
    game = Game(px=100)
    game.smudge_after = 1
    out, _ = _read(game)
    assert out.complete, out.reason
    assert game.turns[-1] == -qs.TOP_BURST

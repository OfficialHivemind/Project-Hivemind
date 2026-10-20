"""The quest list's pixels (vision/questlist), on the kept open menus.

var/quest_reads/close-*-open.jpg are real frames of the open quest menu,
2026-09-27 to 30 (act/quests keeps them when a close is in doubt).
"""
from __future__ import annotations

import pathlib

import numpy as np
import pytest

from hivemind.vision import questlist as ql

ROOT = pathlib.Path(__file__).resolve().parents[2]
KEPT = ROOT / "var" / "quest_reads"
FRAME = KEPT / "close-065946-open.jpg"


def _read(path):
    cv2 = pytest.importorskip("cv2")
    if not path.exists():
        pytest.skip(f"{path.name} is not kept here")
    return cv2.imread(str(path))


# THE KEPT FRAMES THAT ARE THE QUEST MENU AT ITS TOP, named (looked at
# 2026-10-21, ROADMAP A20). The folder is a log the bot keeps adding to when
# a close is in doubt (inventory, the game's Shop, badges, nothing open, a
# scrolled menu all landed there) -- a glob over it went red again with each
# new one (close-020241, 21 Oct). So: this fixed list, not the folder.
QUEST_MENUS = ("close-004152-open.jpg", "close-025214-open.jpg", "close-032644-open.jpg",
               "close-065946-open.jpg", "close-073952-open.jpg", "close-081445-open.jpg",
               "close-115254-open.jpg", "close-151600-open.jpg")


def test_the_thumb_is_found_on_every_kept_open_menu():
    frames = [KEPT / n for n in QUEST_MENUS if (KEPT / n).exists()]
    if not frames:
        pytest.skip("no kept open menus")
    for path in frames:
        t = ql.thumb(_read(path))
        assert t is not None, path.name
        assert t.at_top and not t.fits, (path.name, t)
        assert 250 <= t.rows <= 400, (path.name, t)


def test_the_measured_thumb():
    t = ql.thumb(_read(FRAME))
    assert (t.top, t.bottom) == (176, 507)
    assert t.share == pytest.approx(0.42, abs=0.01)


def test_no_thumb_on_the_world():
    # the gold hive wall is as red as a thumb: only the scrollbar's own
    # border says it is there
    worlds = sorted(KEPT.glob("close-*-before.jpg"))
    if not worlds:
        pytest.skip("no kept frames of the world")
    for path in worlds:
        frame = _read(path)
        assert not ql.has_scrollbar(frame), path.name
        assert ql.thumb(frame) is None, path.name


def test_cuts_fall_between_bars_and_never_through_text():
    crop = ql.list_crop(_read(FRAME))
    cut = ql.cut_rows(crop)
    y0 = ql.LIST_BOX[1]
    # measured on this frame: the first quest's title text, its three step
    # bars, the gaps between them and the dark band before the next quest
    for top, bottom in ((188, 201), (220, 259), (270, 309), (320, 359)):
        assert not cut[top - y0:bottom - y0 + 1].any(), (top, bottom)
    for top, bottom in ((260, 269), (310, 319), (370, 379)):
        assert cut[top - y0:bottom - y0 + 1].all(), (top, bottom)


def test_pages_stitch_back_into_the_list_and_cut_on_allowed_rows():
    crop = ql.list_crop(_read(FRAME))
    whole = np.vstack([crop, crop])                      # a list two panels tall
    view = crop.shape[0]
    pages = [(whole[top:top + view], top)
             for top in (0, 310, 620, whole.shape[0] - view)]
    canvas = ql.stitch(pages)
    assert canvas.shape == whole.shape and (canvas == whole).all()
    pieces = ql.chunks(canvas, most=view)
    assert pieces is not None and sum(p.shape[0] for p in pieces) == whole.shape[0]
    allowed = ql.cut_rows(canvas)
    at = 0
    for piece in pieces[:-1]:
        at += piece.shape[0]
        assert allowed[at], at
        assert piece.shape[0] <= view


def test_a_stretch_with_nowhere_to_cut_is_not_cut():
    solid = np.zeros((1000, 306, 3), np.uint8)
    solid[:, 14:300] = (160, 210, 150)                    # one endless step bar
    solid[:, :7] = (210, 192, 163)                        # the margin beside it
    assert ql.chunks(solid, most=400) is None


def test_the_shift_is_measured_to_the_row_up_to_three_quarters_of_a_page():
    crop = ql.list_crop(_read(FRAME))
    whole = np.vstack([crop, crop[::-1]])                # nothing repeats exactly
    view = crop.shape[0]
    before = whole[:view]
    for moved in (1, 37, 100, 250, 400, 586, view - ql.SHIFT_BAND):
        after = whole[moved:moved + view]
        got, score = ql.vertical_shift(before, after)
        assert got == moved and score > 0.99, (moved, got, score)
    # at the list's end the wheel moves it less than asked, and that is seen
    got, score = ql.vertical_shift(before, whole[120:120 + view], most=600)
    assert got == 120 and score > 0.99


def test_a_list_that_did_not_move_measures_zero():
    crop = ql.list_crop(_read(FRAME))
    got, score = ql.vertical_shift(crop, crop.copy())
    assert got == 0 and score > 0.99

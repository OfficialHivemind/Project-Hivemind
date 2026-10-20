"""Closing a menu in front of a busy world (act/quests._close, the panel box).

run-534 06:59:46: at the hive during a convert the world moved a third of the
frame by itself, the whole-frame test could not tell the closed menu from the
open one, a second click reopened it, and the run stopped for a rejoin.
"""
from __future__ import annotations

import pathlib

import cv2
import numpy as np
import pytest

from hivemind.act import quests

ROOT = pathlib.Path(__file__).resolve().parents[2]
KEPT = ROOT / "var" / "quest_reads"


class FakeInput:
    def __init__(self):
        self.clicks = []

    def click(self, x=None, y=None):
        self.clicks.append((x, y))


class Result:
    menu_open = True


def world(seed):
    return np.random.default_rng(seed).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)


def moved(frame, share, seed):
    """`frame` with `share` of its pixels changed -- bees, bubbles, the camera."""
    rng = np.random.default_rng(seed)
    out = frame.copy()
    mask = rng.random(frame.shape[:2]) < share
    out[mask] = rng.integers(0, 255, (int(mask.sum()), 3), dtype=np.uint8)
    return out


def with_panel(frame):
    out = frame.copy()
    out[170:960, 0:320] = (60, 200, 90)          # the static quest panel
    return out


# THE WORLD MOVES ON FROM FRAME TO FRAME: each is the last one moved a little
# more, so frames further apart differ more (what the old whole-frame rule
# relies on), and the run-534 figures come back: the closed menu is further
# from the world than from the menu, and only the panel's box says it is shut.
def test_a_menu_closed_in_front_of_a_busy_world_is_seen_closed():
    before = world(1)
    busy = moved(before, 0.35, 2)
    opened = with_panel(busy)
    closed = moved(busy, 0.20, 3)                  # panel gone, the world moved on
    assert (quests.changed_fraction(before, closed) + quests.CLOSED_MARGIN
            >= quests.changed_fraction(opened, closed)), "the old rule alone misses it"
    vin, result = FakeInput(), Result()
    frames = iter([closed, closed, closed])
    quests._close(vin, lambda: next(frames), before, result, lambda s: None,
                  lambda t: None, 83, 128, opened=opened)
    assert not result.menu_open
    assert len(vin.clicks) == 1, "one click closed it; a second would reopen it"


def test_a_menu_still_open_in_front_of_a_busy_world_is_not_called_closed():
    before = world(4)
    busy = moved(before, 0.35, 5)
    opened = with_panel(busy)
    still = with_panel(moved(busy, 0.20, 6))       # the world moved on; the panel did not
    vin, result = FakeInput(), Result()
    frames = iter([still, still, still, still])
    quests._close(vin, lambda: next(frames), before, result, lambda s: None,
                  lambda t: None, 83, 128, opened=opened)
    assert result.menu_open


@pytest.mark.parametrize("stamp", ["065946", "115254"])
def test_the_kept_failures_have_a_box_that_tells_open_from_closed(stamp):
    paths = [KEPT / f"close-{stamp}-{n}.jpg" for n in ("before", "open", "after")]
    if not all(p.exists() for p in paths):
        pytest.skip("the kept close failures are not on this machine")
    before, opened, after = (cv2.imread(str(p)) for p in paths)
    box = quests._panel_box(before, opened)
    assert box is not None
    assert quests.changed_fraction(opened[box], before[box]) >= quests.PANEL_CLOSED_FROM_OPEN
    assert quests.changed_fraction(opened[box], after[box]) < quests.PANEL_CLOSED_FROM_OPEN

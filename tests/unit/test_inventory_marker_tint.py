"""Natro's item marker seen through the red damage vignette
(vision/inventory.item_rows, VIGNETTE_K): two real pages of the list.

2026-10-12 22:22, a Ladybug fight in the Mushroom Field: the list opened with
the Blue Clay Planter on it, the edge tinted BGR ~(175, 176, 207), and the
exact-colour test found no marker -- the planter was not placed. 22:18 the
same list over a calm world reads the marker's own (218, 221, 212)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

FIX = Path(__file__).resolve().parents[1] / "fixtures/inventory"
TINTED = FIX / "page-20261012-222209-00-vignette.png"
CALM = FIX / "page-20261012-221846-00.png"


def _rows(page):
    """act/inventory's own row tops (first marker of each item row)."""
    from hivemind.act import inventory
    return inventory.row_tops(page)


def test_the_marker_is_found_through_the_vignette():
    from hivemind.vision import inventory as inv
    page = cv2.imread(str(TINTED))
    # the exact colour is nowhere on its edge ...
    edge = page[:, :inv.ITEM_MARK_X].astype(int)
    assert not (np.abs(edge - (218, 221, 212)) <= 2).all(axis=2).any()
    # ... and the vignette path finds the list's rows exactly where an
    # untinted read of the same scroll position (20261012-221612 page 05)
    # found them
    rows = _rows(page)
    assert rows == [12, 77, 167, 257, 347, 437, 527, 617, 707]


def test_a_calm_page_is_read_by_the_exact_colour_as_before():
    from hivemind.vision import inventory as inv
    page = cv2.imread(str(CALM))
    assert inv.item_rows(page)[:5] == [67, 88, 109, 157, 178]
    assert _rows(page) == [67, 157, 247, 337, 427, 517, 607, 697, 787]


def test_the_vignette_colour_without_the_list_shape_is_refused():
    from hivemind.vision import inventory as inv
    page = cv2.imread(str(TINTED))
    # a long even strip of the tinted marker colour: the colour, no rows
    strip = np.empty_like(page)
    strip[:] = page[100, 0]
    assert inv._blocks(inv._vignetted(strip[:, :6].astype(np.int16),
                                      (218, 221, 212)))
    assert inv.item_rows(strip) == []
    # the tinted list with only two rows left on it (the rest the world)
    short = page.copy()
    short[200:] = page[880, 0]
    assert inv.item_rows(short) == []


def test_other_tints_are_still_not_the_marker():
    from hivemind.vision import inventory as inv
    calm = cv2.imread(str(CALM)).astype(np.float32)
    dimmed = (calm * 0.8).round().astype(np.uint8)          # red scaled too
    assert inv.item_rows(dimmed) == []
    blue = (calm * 0.8 + np.array([180, 0, 0], np.float32) * 0.2)
    assert inv.item_rows(blue.round().astype(np.uint8)) == []
    # and the red vignette over the calm page is found, rows unchanged
    red = (calm * 0.75 + np.array([0, 0, 187], np.float32) * 0.25)
    assert (_rows(red.round().astype(np.uint8))
            == [67, 157, 247, 337, 427, 517, 607, 697, 787])

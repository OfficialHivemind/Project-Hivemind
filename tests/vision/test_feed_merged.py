"""The newest feed pill, joined to the field's blue flowers behind it."""
from __future__ import annotations

import pathlib

import cv2

from hivemind.vision import feed

FRAME = pathlib.Path(__file__).resolve().parents[1] / "fixtures/feed/merged-pill.jpg"


def test_a_pill_merged_with_blue_flowers_is_still_a_row():
    """MEASURED 2026-10-03 03:01:53: "+580 Honey (from Rhino Beetle)" and the
    Pine Tree's blue flowers under it made one 340x49 blob, too tall and too
    sparse to pass, and the feed read only the ends of the faded lines."""
    frame = cv2.imread(str(FRAME))
    rows = feed.rows(frame)
    newest = [r for r in rows if r.w > 300]
    assert newest, [(r.x, r.y, r.w, r.h) for r in rows]
    assert 1025 <= newest[-1].y <= 1040 and newest[-1].h <= 30

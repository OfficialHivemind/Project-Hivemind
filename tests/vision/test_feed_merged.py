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


def test_blue_off_the_feed_column_is_no_row():
    """THE COLUMN (vision/feed): a pill starts at 1565 or ends at 1904; the
    same blue elsewhere (a bee, flowers) is the world's."""
    import numpy as np
    img = np.full((1080, 1920, 3), (60, 140, 60), np.uint8)
    blue = (200, 90, 30)                                   # BGR, hue ~104
    cv2.rectangle(img, (1565, 1033), (1904, 1053), blue, -1)
    cv2.putText(img, "+580 Honey (from Rhino Beetle)", (1575, 1048),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.rectangle(img, (1180, 800), (1340, 820), blue, -1)   # a bee's side
    cv2.rectangle(img, (1730, 950), (1919, 965), blue, -1)   # flowers off the edge
    assert [(r.x, r.y) for r in feed.rows(img)] == [(1565, 1033)]

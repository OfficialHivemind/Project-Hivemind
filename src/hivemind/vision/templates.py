"""Finding a known picture inside a frame.

Used for UI landmarks -- the word "Servers" on a game page, a button, a dialog
title. The alternative would be OCR, which costs 30-80 ms and misreads styled
text; a template match costs well under a millisecond and either finds the thing
or honestly says it did not.

Matching is TM_CCOEFF_NORMED, which subtracts the mean of both patches before
correlating. That makes it insensitive to uniform brightness changes, so a
landmark still matches when Roblox renders the page a shade lighter or the
capture lands mid-fade.

Why this matters more than it sounds: the Servers row on a game page sits at a
y that depends on how far the page has scrolled and on how much variable content
("People Also Join") sits above it. Clicking a remembered coordinate is exactly
the brittleness that breaks every scripted UI automation on the first redesign.
Finding the label and clicking relative to *it* survives both.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Match:
    x: int; y: int; w: int; h: int
    score: float

    @property
    def centre(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


def load(path: str | Path) -> np.ndarray:
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(path)
    return img


def find(frame: np.ndarray, template: np.ndarray,
         threshold: float = 0.75,
         region: tuple[int, int, int, int] | None = None) -> Match | None:
    """Best match for `template`, or None if nothing scores above `threshold`.

    `region` (x, y, w, h) restricts the search, which both speeds it up and
    removes whole classes of false positive -- a word that appears twice on a
    page can be disambiguated by where it is allowed to be.
    """
    ox, oy = 0, 0
    haystack = frame[:, :, :3]
    if region is not None:
        ox, oy, rw, rh = region
        haystack = haystack[oy:oy + rh, ox:ox + rw]
    th, tw = template.shape[:2]
    if haystack.shape[0] < th or haystack.shape[1] < tw:
        return None
    res = cv2.matchTemplate(haystack, template[:, :, :3], cv2.TM_CCOEFF_NORMED)
    _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
    if maxv < threshold:
        return None
    return Match(int(maxl[0]) + ox, int(maxl[1]) + oy, tw, th, float(maxv))


def find_all(frame: np.ndarray, template: np.ndarray,
             threshold: float = 0.75, min_gap: int = 8) -> list[Match]:
    """Every match above threshold, strongest first, suppressing near-duplicates.

    A single drawn word produces a cluster of high scores at neighbouring
    offsets, so without suppression one label reads as dozens of hits.
    """
    th, tw = template.shape[:2]
    if frame.shape[0] < th or frame.shape[1] < tw:
        return []
    res = cv2.matchTemplate(frame[:, :, :3], template[:, :, :3],
                            cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    cands = sorted(((float(res[y, x]), int(x), int(y)) for y, x in zip(ys, xs)),
                   reverse=True)
    out: list[Match] = []
    for score, x, y in cands:
        if any(abs(x - m.x) < min_gap and abs(y - m.y) < min_gap for m in out):
            continue
        out.append(Match(x, y, tw, th, score))
    return out

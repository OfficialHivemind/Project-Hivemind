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

TRANSPARENT PIXELS DO NOT VOTE. A template whose PNG has an alpha channel is
matched with that alpha as the mask, so a piece of GUI cut out of the world
around it (a round button, a tile's outline) scores on its own pixels only,
whatever the world behind it shows. MEASURED 2026-10-27 on 611 saved frames
the cut was not made from (var/hotbar stack/press frames, September route
frames, the golden frames): the Roblox button (data/templates/ui/
anchor_roblox.png) scored p1 0.494 without its alpha, 0.996 with it. A
template with no alpha, or an all-opaque one, matches exactly as before.
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
    """BGR, or BGRA when the PNG has transparent pixels (its alpha is the mask)."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4 and img[:, :, 3].min() == 255:
        return np.ascontiguousarray(img[:, :, :3])
    return img


def match(haystack: np.ndarray, template: np.ndarray) -> np.ndarray:
    """TM_CCOEFF_NORMED of `template` over `haystack`, its alpha (if any) as
    the mask. A masked match divides by the patch's spread, so a flat patch
    gives inf/nan: that is no evidence, scored 0."""
    mask = None
    if template.ndim == 3 and template.shape[2] == 4:
        mask = np.ascontiguousarray(cv2.merge([template[:, :, 3]] * 3))
    res = cv2.matchTemplate(np.ascontiguousarray(haystack[:, :, :3]),
                            np.ascontiguousarray(template[:, :, :3]),
                            cv2.TM_CCOEFF_NORMED, mask=mask)
    if mask is not None:
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
    return res


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
    res = match(haystack, template)
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
    res = match(frame, template)
    ys, xs = np.where(res >= threshold)
    cands = sorted(((float(res[y, x]), int(x), int(y)) for y, x in zip(ys, xs)),
                   reverse=True)
    out: list[Match] = []
    for score, x, y in cands:
        if any(abs(x - m.x) < min_gap and abs(y - m.y) < min_gap for m in out):
            continue
        out.append(Match(x, y, tw, th, score))
    return out

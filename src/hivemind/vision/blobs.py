"""Blob extraction.

connectedComponentsWithStats rather than findContours: it returns centroids and
areas in a single pass, which is all we need, and it is faster.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Blob:
    x: int; y: int; w: int; h: int      # bounding box
    area: int
    cx: float; cy: float                # centroid

    @property
    def aspect(self) -> float:
        return self.w / self.h if self.h else 0.0


def find(mask: np.ndarray, min_area: int = 40, max_area: int = 20000,
         min_aspect: float = 0.4, max_aspect: float = 2.5) -> list[Blob]:
    n, _lbl, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out: list[Blob] = []
    for i in range(1, n):                        # 0 is background
        x, y, w, h, area = stats[i]
        if not (min_area <= area <= max_area):
            continue
        b = Blob(int(x), int(y), int(w), int(h), int(area),
                 float(cents[i][0]), float(cents[i][1]))
        if min_aspect <= b.aspect <= max_aspect:
            out.append(b)
    return sorted(out, key=lambda b: -b.area)

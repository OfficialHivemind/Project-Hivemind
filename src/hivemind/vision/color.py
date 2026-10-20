"""HSV colour bands.

Bee Swarm tokens are engine-rendered sprites with an emissive, unshaded material
-- they do not respond to scene lighting the way a real object would. That makes
them close to the ideal case for plain HSV thresholding and a poor argument for
a neural net: classical CV is 10-20x faster here and usually more accurate.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Band:
    """An inclusive HSV range. OpenCV hue is 0-179, not 0-359."""
    name: str
    lo: tuple[int, int, int]
    hi: tuple[int, int, int]

    def mask(self, bgr: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        return cv2.inRange(hsv, np.array(self.lo, np.uint8), np.array(self.hi, np.uint8))


def clean(mask: np.ndarray, open_k: int = 3, close_k: int = 5) -> np.ndarray:
    """Open to kill 1-2px speckle, close to fill the token interior."""
    k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k))
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k_open)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_close)

"""What colour the flowers are, where the character is standing.

WHY THIS MATTERS: the owner wants a blue hive. A blue
bee gets +50% pollen from a blue flower, and the Bubble Wand collects double
from one. Both of those are claims about FLOWERS, not about fields -- and the
difference is not academic. Treating "the Pineapple Patch is a blue field" as
"every flower in it is blue" is what made a 3,500,000-honey sidegrade look
like a 1.43x upgrade, until the owner asked whether the Bubble Wand was worse
than the Golden Rake and the ground was actually counted.

It was 42.5% blue. The tool was worth 1.02x.

The quests make the same demand from the other direction. Read off their own
screen tonight: "Collect 820,020 Blue Pollen" and "Collect 1,500,000 Red
Pollen". Neither can be planned for without knowing which fields actually
carry which colour, and the wiki's one-word colour label cannot answer it.

WHAT THIS MEASURES, AND WHAT IT DOES NOT. It measures the share of GROUND
PIXELS that are flat petal colours, which is a proxy for the share of flowers
and not the same thing: a big flower covers more pixels than a small one, and
the camera sees nearer flowers larger. It is used for choosing between fields,
where a proxy is enough, and it is never reported as a flower count.

The bands are deliberately tight. Petals in this game are flat, bright, unlit
colour on flat green grass -- the same property that makes the reward feed and
the notification banner readable -- so requiring high saturation AND high
value keeps grass, shadow and the sky out without needing a model.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# The ground plane, and why it is cropped this way. Above row 430 is mostly
# sky, scenery and the HUD; below 980 is the hotbar and the buff tray. Neither
# contains flowers, and both contain flat bright colour that would be counted
# as petals. MEASURED against the 1920x1080 frames this client produces.
GROUND = (430, 980)

# Petal colours. Blue and red are hue bands; white is the absence of hue at
# high brightness, which is why it is defined on saturation instead.
BANDS = {
    "blue": (((100, 120, 120), (130, 255, 255)),),
    "red": (((0, 120, 110), (8, 255, 255)),
            ((172, 120, 110), (179, 255, 255))),   # red wraps the hue circle
    "white": (((0, 0, 190), (179, 45, 255)),),
}

# Below this many petal pixels the frame is not showing a flower bed -- it is
# a wall, the sky, a menu or the inside of a cannon -- and a share computed
# from it would be noise presented as a measurement.
MIN_PETAL_PIXELS = 20_000


@dataclass(frozen=True)
class Flowers:
    """Shares of each petal colour in one frame. They sum to 1, or it is empty."""
    blue: float = 0.0
    red: float = 0.0
    white: float = 0.0
    pixels: int = 0

    @property
    def ok(self) -> bool:
        """Did this frame show enough flowers to say anything at all?"""
        return self.pixels >= MIN_PETAL_PIXELS

    def share(self, colour: str) -> float:
        return float(getattr(self, colour, 0.0))

    @property
    def dominant(self) -> str | None:
        if not self.ok:
            return None
        return max(("blue", "red", "white"), key=self.share)

    def describe(self) -> str:
        if not self.ok:
            return "no flower bed in view"
        return (f"{self.blue:.0%} blue, {self.white:.0%} white, "
                f"{self.red:.0%} red")


def measure(frame) -> Flowers:
    """Count petal pixels in one frame. Never raises, never guesses."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return Flowers()
    top, bottom = GROUND
    ground = frame[top:bottom, :, :3]
    if ground.size == 0:
        return Flowers()
    hsv = cv2.cvtColor(ground, cv2.COLOR_BGR2HSV)
    counts: dict[str, int] = {}
    for name, bands in BANDS.items():
        total = 0
        for lo, hi in bands:
            mask = cv2.inRange(hsv, np.array(lo, np.uint8),
                               np.array(hi, np.uint8))
            total += int(mask.sum() // 255)
        counts[name] = total
    pixels = sum(counts.values())
    if pixels <= 0:
        return Flowers(pixels=0)
    return Flowers(blue=counts["blue"] / pixels,
                   red=counts["red"] / pixels,
                   white=counts["white"] / pixels,
                   pixels=pixels)

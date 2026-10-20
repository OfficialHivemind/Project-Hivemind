"""Telling the player's own bee from a token, by whether it moves.

THE BUG THIS EXISTS FOR. `vision.tokens.nearest()` returns the closest
sighting it is confident about, and the closest sighting is nearly always the
player's own bee -- its two white eyes and the highlight on its body all pass
the token test. Over all 18 frames of `var/tokens_live`, the hive row with
exactly one real token in it, the bee sat 55-160 px from the point the code
treats as the character and the nearest real object was 385 px away. The bee
won 14 of those 18. The owner watched the result twice: it had not seen
the haste or Baby Love tokens, only walked into them by accident; and all it
did was turn once and jump once when it got nothing.

WHY NOT A DEAD ZONE. Measured and rejected. On the hand-labelled field frame
`var/incidents/234344-token/149_t+07.6s.jpg` the nine real tokens sit at 38,
159, 188, 226, 264, 266, 319, 469 and 624 px from that same point -- two of
them NEARER than the bee's own eyes. Any radius that removes the eyes removes
real tokens with them.

WHAT DOES SEPARATE THEM IS TIME. The avatar is rigid in screen space; the
world is not. So a mark that does not move while the view does is part of the
character or the interface, and a mark that moves with the world is in the
world.

MEASURED 2026-09-21 against 2,380 samples of a live farming run
(`var/pinned/samples.json`, collected by `scripts/collect_pinned.py` from the
live-view JPEG, so nothing extra touched the game). Taking only the 483
consecutive pairs where at least 30% of the frame changed -- which is a camera
turn or a walk, not a token spinning -- and asking of each glyph position how
often it was still within 4 px of where it had just been:

    (960, 560), 109 px from the character   seen 237   stayed put  76.8%
    (960, 540), 129 px from the character   seen 124   stayed put  68.5%
    a band at y=160, 510 px out             seen  30+  stayed put  43-63%
    every other position near the character            median      4.8%
    every other position further out                   median     10.0%

The first two are the bee's own head and eye. The y=160 band is interface
leaking into the world crop. Everything genuinely in the world moved. A gap
between 43% and 10% with nothing in it is what makes this a measurement rather
than a threshold.

WHAT IT COSTS. One frame difference per look and a short list of remembered
spots. It learns only from looks where the view really changed, so a character
standing still teaches it nothing -- which is correct, because a stationary
camera makes the whole world look as rigid as the avatar.
"""
from __future__ import annotations

import numpy as np

# "The same place": the tolerance the measurement above was taken at.
PIN_TOLERANCE = 4

# HOW MUCH OF THE FRAME MUST CHANGE for a look to teach anything. The
# separation is cleanest here: at 15% the avatar stayed put 78.9% against a
# median of 15.4% elsewhere, and at 30% it is 76.8% against 4.8%. Below this a
# spinning token or a pollen popup is enough to call the view "moved", and
# then standing still teaches the filter that the whole world is rigid.
VIEW_CHANGED = 0.30

# A pixel has changed when it moves by more than this. JPEG noise and the
# game's idle animation sit well below it. Shared with act.quests, which uses
# the same measure to decide whether a menu opened.
PIXEL_DELTA = 28

# HOW MANY TEACHING LOOKS BEFORE AN OPINION. A CHOICE, not a measurement: the
# bee's own eye was seen in 237 of them and a token near the character in far
# fewer, so anything from a handful upwards works. Eight is about three
# seconds of walking at the chase's look rate, which is short enough to help
# the first detour of a trip and long enough not to fire on a coincidence.
PIN_LOOKS = 8

# Stayed put in this share of the teaching looks. The measured band is 43-77%
# for the avatar and the interface against 10% and below for everything in the
# world, so this sits in the middle of an empty gap.
PIN_FRACTION = 0.5

# A spot nothing has confirmed for this many teaching looks is forgotten, so
# the filter cannot carry a stale opinion across a scene change.
PIN_FORGET = 60

# HOW MANY SPOTS TO REMEMBER AT ONCE, which is a cost bound and nothing else.
# Every mark in a moving world creates a fresh spot that will never pin, and
# the lookup is linear in the list: MEASURED over the 2,380-sample run the
# list reached 1,772 spots and a look cost 1.67 ms, so an all-night session
# would grow it without limit. When the list is over the cap the spots with
# the FEWEST looks are dropped, which cannot lose a real pin -- a pinned spot
# is by definition one of the most-seen.
PIN_MEMORY = 400


# The difference is taken at a QUARTER SCALE, and that is measured rather
# than assumed. At full 1920x1080 it costs 32.9 ms, which is most of a frame
# at the configured 20 fps and would more than double the live view's cost.
# MEASURED across 49 consecutive pairs spanning a whole route, walking
# included (`var/incidents/234206-refused`): the quarter-scale fraction tracks
# the full-scale one to within 0.004 everywhere from 0.016 to 0.725, and the
# two agree on which side of VIEW_CHANGED they fall on in 49 of 49. It costs
# 3.8 ms. So the 2,380-sample calibration transfers unchanged.
VIEW_SCALE = 4

# A VETOED SPOT (Pinned.veto) covers this far either way: the gear a chase
# caught staying put bobs 20-60 px (act/chase STUCK_PX). At most VETO_MEMORY
# of them, newest kept.
VETO_RADIUS = 40
VETO_MEMORY = 8


def view_change(before, after) -> float:
    """How much of the frame moved between two looks, 0..1.

    The same measure the 2,380-sample run was labelled with, so the
    VIEW_CHANGED threshold transfers exactly. See VIEW_SCALE.
    """
    if before is None or after is None:
        return 0.0
    a, b = before[:, :, :3], after[:, :, :3]
    if a.shape != b.shape or a.size == 0:
        return 0.0
    import cv2
    height, width = a.shape[:2]
    size = (max(1, width // VIEW_SCALE), max(1, height // VIEW_SCALE))
    a = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    b = cv2.resize(b, size, interpolation=cv2.INTER_AREA)
    return float((np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
                  > PIXEL_DELTA).mean())


class _Spot:
    """One screen position, and how often it has failed to move."""

    __slots__ = ("x", "y", "looks", "stayed", "last_look")

    def __init__(self, x: float, y: float, look: int):
        self.x, self.y = float(x), float(y)
        self.looks = 0
        self.stayed = 0
        self.last_look = look

    @property
    def fraction(self) -> float:
        return self.stayed / self.looks if self.looks else 0.0

    @property
    def pinned(self) -> bool:
        return self.looks >= PIN_LOOKS and self.fraction >= PIN_FRACTION


class Pinned:
    """Sightings that do not move while the view does. Not in the world."""

    def __init__(self, *, tolerance: int = PIN_TOLERANCE,
                 changed: float = VIEW_CHANGED, looks: int = PIN_LOOKS,
                 fraction: float = PIN_FRACTION, forget: int = PIN_FORGET,
                 memory: int = PIN_MEMORY):
        self.tolerance = int(tolerance)
        self.changed = float(changed)
        self.min_looks = int(looks)
        self.min_fraction = float(fraction)
        self.forget = int(forget)
        self.memory = max(8, int(memory))
        self._spots: list[_Spot] = []
        self._vetoed: list[tuple[float, float]] = []
        self._previous: list[tuple[float, float]] = []
        self.looks = 0
        self.taught = 0
        self.dropped = 0

    # ---- learning -----------------------------------------------------------
    @staticmethod
    def _points(sightings) -> list[tuple[float, float]]:
        """Accepts sightings or plain (x, y) pairs.

        Pairs are what `tokens.detect(..., marks=[])` hands back, and they are
        the RAW glyph positions -- the ones this filter was measured on. A
        merged sighting's position flips between the faces of one cube, so it
        wanders while the object is still.
        """
        out = []
        for item in sightings or ():
            if hasattr(item, "x"):
                out.append((float(item.x), float(item.y)))
            else:
                x, y = item[0], item[1]
                out.append((float(x), float(y)))
        return out

    def teach(self, moved: float, sightings) -> None:
        """Record one look. `moved` is `view_change` for this frame."""
        here = self._points(sightings)
        if moved < self.changed:
            # The view barely changed, so nothing here is evidence either way.
            # The positions are still remembered, because the NEXT look may be
            # a moving one and it needs something to compare against.
            self._previous = here
            return
        self.looks += 1
        self.taught += 1
        for x, y in here:
            spot = self._nearest(x, y)
            if spot is None:
                spot = _Spot(x, y, self.looks)
                self._spots.append(spot)
            spot.looks += 1
            spot.last_look = self.looks
            if any(abs(x - px) <= self.tolerance and abs(y - py) <= self.tolerance
                   for px, py in self._previous):
                spot.stayed += 1
        self._previous = here
        self._forget()

    def _forget(self) -> None:
        keep = [s for s in self._spots
                if self.looks - s.last_look <= self.forget]
        if len(keep) > self.memory:
            # Most-seen first, so every pinned spot survives. See PIN_MEMORY.
            keep.sort(key=lambda s: (-s.looks, self.looks - s.last_look))
            keep = keep[:self.memory]
        self.dropped += len(self._spots) - len(keep)
        self._spots = keep

    def _nearest(self, x: float, y: float) -> _Spot | None:
        for spot in self._spots:
            if (abs(spot.x - x) <= self.tolerance
                    and abs(spot.y - y) <= self.tolerance):
                return spot
        return None

    # ---- using --------------------------------------------------------------
    def veto(self, x: float, y: float) -> None:
        """A spot a chase PROVED is not in the world (act/chase STUCK_PX: it
        stayed put on screen while the ground moved under a step), skipped
        for the rest of the session, within VETO_RADIUS -- the thing bobs
        further than this filter's own `tolerance`."""
        if any(abs(x - vx) <= VETO_RADIUS and abs(y - vy) <= VETO_RADIUS
               for vx, vy in self._vetoed):
            return
        self._vetoed.append((float(x), float(y)))
        del self._vetoed[:-VETO_MEMORY]

    def is_pinned(self, x: float, y: float) -> bool:
        if any(abs(x - vx) <= VETO_RADIUS and abs(y - vy) <= VETO_RADIUS
               for vx, vy in self._vetoed):
            return True
        spot = self._nearest(x, y)
        return spot is not None and (
            spot.looks >= self.min_looks
            and spot.fraction >= self.min_fraction)

    def keep(self, moved: float, sightings) -> list:
        """Learn from this look, then hand back only what is in the world.

        Takes sightings or plain (x, y) pairs, like `teach`, and hands back
        the same kind of thing it was given.
        """
        self.teach(moved, sightings)
        points = self._points(sightings)
        return [item for item, (x, y) in zip(sightings, points)
                if not self.is_pinned(x, y)]

    @property
    def spots(self) -> list:
        """The positions currently considered pinned, strongest first."""
        return sorted((s for s in self._spots if s.pinned),
                      key=lambda s: -s.fraction)

    def describe(self) -> str:
        pins = self.spots
        if not self.taught:
            return ("nothing learned yet — it only learns from looks where the "
                    "view really moved")
        if not pins:
            return (f"{self.taught} moving look(s), nothing pinned to the "
                    f"screen yet")
        worst = ", ".join(f"({s.x:.0f}, {s.y:.0f}) {s.fraction:.0%}"
                          for s in pins[:3])
        return (f"{len(pins)} spot(s) pinned to the screen after "
                f"{self.taught} moving look(s): {worst}")

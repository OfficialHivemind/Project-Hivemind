"""Walk toward the "!" over a quest giver: a steer for act/hiverow's holds.

WHY. The Panda Bear's route ends with his marker on screen and his prompt out
of range: at (1056, 96), (1032, 100) and (1020, 96) on the three visits whose
looks were kept (var/bears/panda_bear-look1-*, vision/questmarker) -- straight
ahead to within 100 px -- and the search that follows walks blind: forward and
left took it into the Bamboo Field, up against the blue wall, on 2026-10-01 at
15:37 (panda_bear-hunt1-*-153743.jpg), and the holds after that searched the
field. Where the marker is says which way he is, so the walk can go that way
first.

HOW. The camera keeps its heading while the character walks -- every recorded
route steers by it (act/bearvisit puts it back before a search for that
reason) -- so W walks the camera's heading and A and D slide across it,
carrying the marker the other way on screen. The marker nearest the middle at
the first look is the one walked to and is followed from look to look; W is
held throughout, and with it the slide key that brings the marker back to the
middle while it is more than DEADBAND_PX off it. The walk ends:

  - when the prompt shows (hiverow's test, on the same frame);
  - when the marker has been out of sight for LOST_AFTER_S -- close under a
    giver on a platform it goes over the top of the screen;
  - when it has stopped moving for STALL_AFTER_S -- walking toward it makes
    it grow and climb, so a marker that holds still means something is in
    the way;
  - at the hold's own bound.

WHAT IT PRESSES: w, a and d, held. Nothing else; the prompt is read by the
caller, never pressed here.
"""
from __future__ import annotations

import time

from ..vision import questmarker

FRAME_WIDTH = 1920
# Off the middle by more than this (px of a 1920-wide frame), slide toward it.
DEADBAND_PX = 120
# Out of sight this long and the walk is over (a bee or a bubble crossing it
# hides it for a look or two).
LOST_AFTER_S = 0.5
# Holding still this long, within STALL_PX in x, y and height: in the way.
# Walking at 28 studs/s toward a marker 60 px tall 60 studs off nearly
# doubles it in a second, so a few pixels is not a walk that is getting there.
STALL_AFTER_S = 1.0
STALL_PX = 4
# A marker further than this from the last one is somebody else's.
TRACK_PX = 300
# A pause between looks longer than this (the owner's Pause, a panel read
# between two holds) starts the watching afresh.
GAP_S = 0.5
# Ten looks of 0.1 s add up to 0.9999999 s; a second is a second.
EPSILON_S = 1e-6


class Toward:
    """The steer: called with each frame, returns the keys to hold until the
    next look, or None with `reason` saying why the walk is over."""

    def __init__(self, find=questmarker.find, *, clock=time.monotonic,
                 deadband: float = DEADBAND_PX, lost_after: float = LOST_AFTER_S,
                 stall_after: float = STALL_AFTER_S, stall_px: float = STALL_PX,
                 track_px: float = TRACK_PX, gap: float = GAP_S):
        self.find, self.clock = find, clock
        self.deadband, self.lost_after = float(deadband), float(lost_after)
        self.stall_after, self.stall_px = float(stall_after), float(stall_px)
        self.track_px, self.gap = float(track_px), float(gap)
        self.reason = ""
        self.first = None          # the marker the walk set off toward
        self.marker = None         # the last one seen
        self.looks = self.seen = 0
        self.walked = 0.0          # seconds of looking, gaps left out
        self._keys: tuple = ("w",)
        self._trail: list = []     # (time, x, y, h) of the marker
        self._last_seen = None
        self._last_look = None

    def __call__(self, frame):
        now = self.clock()
        if self._last_look is not None:
            step = now - self._last_look
            if step > self.gap:
                self._trail.clear()
                self._last_seen = now
            else:
                self.walked += step
        self._last_look = now
        self.looks += 1
        try:
            markers = list(self.find(frame)) if frame is not None else []
        except Exception:
            markers = []
        width = int(getattr(frame, "shape", (0, FRAME_WIDTH))[1] or FRAME_WIDTH)
        scale = width / float(FRAME_WIDTH)
        if self.marker is None:
            if not markers:
                self.reason = "no quest marker on screen"
                return None
            seen = min(markers, key=lambda m: abs(m.x - width / 2.0))
            self.first = seen
        else:
            near = [m for m in markers
                    if abs(m.x - self.marker.x) <= self.track_px * scale]
            seen = min(near, key=lambda m: abs(m.x - self.marker.x)) if near else None
        if seen is None:
            if now - self._last_seen >= self.lost_after - EPSILON_S:
                self.reason = (f"the marker went out of sight (last at "
                               f"{self.marker.x}, {self.marker.y})")
                return None
            return self._keys
        self.seen += 1
        self.marker, self._last_seen = seen, now
        self._trail.append((now, seen.x, seen.y, seen.h))
        del self._trail[:-64]
        old = [i for i, p in enumerate(self._trail)
               if now - p[0] >= self.stall_after - EPSILON_S]
        if old:
            tol = self.stall_px * scale
            if all(abs(p[1] - seen.x) <= tol and abs(p[2] - seen.y) <= tol
                   and abs(p[3] - seen.h) <= tol for p in self._trail[old[-1]:]):
                self.reason = (f"the marker stopped moving at ({seen.x}, {seen.y}) "
                               f"for {self.stall_after:.1f}s — something is in the way")
                return None
        off = seen.x - width / 2.0
        dead = self.deadband * scale
        self._keys = ("w", "d") if off > dead else ("w", "a") if off < -dead else ("w",)
        return self._keys

    def describe(self) -> str:
        if self.first is None:
            return f"toward a quest marker: {self.reason or 'not tried'}"
        return (f"toward the quest marker first seen at ({self.first.x}, "
                f"{self.first.y}) for {self.walked:.1f}s"
                + (f" — {self.reason}" if self.reason else ""))

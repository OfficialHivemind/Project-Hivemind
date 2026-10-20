"""Watching the owner play, and turning it into a map.

HIS IDEA, and it is a good one: "what if u put a mode in where it learns how i
play, not following what i do exactly but almost sorta maps it out like fake
nodes ect".

WHY IT BEATS WHAT THE BOT HAS NOW. Every route it owns is a transpiled
BeeTuxMacro recording: a list of timed key holds with no idea what is on
screen. They work until something moves -- a haste token, a ledge, a wall --
and then they walk confidently into the trophy store. A human's path is
different in kind: it is a route that demonstrably worked, and the owner can
produce a new one just by playing.

NOT A KEYSTROKE RECORDING. Replaying someone's exact inputs has the same
fragility as the macros, for the same reason. What is worth keeping is the
SHAPE: which places exist, what each looks like, and which places lead to
which. That is what he means by "fake nodes" -- not a copy of the walk, a map
of it.

HOW A PLACE IS RECOGNISED. Each sample gets a difference hash of the frame,
which is cheap, robust to brightness, and stable for the same view. Two
samples whose hashes are close are the same place. A place seen from a
different camera angle hashes differently, so a node accumulates several
signatures rather than one -- which is correct, because "the hive from the
north" and "the hive from the east" really are different views of one place.

IT SENDS NOTHING. There is no keyboard or pointer in this module, by
construction rather than by policy: nothing here can press a key, so a
recording session cannot fight the person making it. The bot watches and
writes things down.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# HOW A PLACE IS SIGNED, AND WHY IT IS NOT AN IMAGE HASH.
#
# The first version used an 8x8 difference hash of the frame. MEASURED on the
# owner's first real session: 164 samples produced 78 "places" -- essentially
# one per sample, which is a trace and not a map. The signatures had no
# structure to cluster on either: across the whole session the median
# pairwise distance was 30 bits of 64 and the minimum was 10, so no threshold
# separates "same place" from "different place". A difference hash describes a
# PICTURE, and two pictures of one field taken half a second apart while
# walking are genuinely different pictures.
#
# A coarse hue/saturation histogram describes the PLACE instead. MEASURED
# across real frames with known ground truth -- 40 from the Pine Tree field,
# 12 at the hive, 8 around the shop and cannon:
#
#     within one place    median correlation +0.99 / +0.94 / +0.87, min +0.53
#     field vs hive       median +0.01, max +0.17
#     field vs shop       median +0.03, max +0.20
#
# Every within-place pair scores above 0.53 and every across-place pair below
# 0.20, so anything in between separates them. 0.45 sits in that gap.
#
# The hive and the shop overlap (max +0.99) and that is correct rather than a
# failure: the shop is IN the hive area, and a coarse map should say so.
HIST_BINS = (12, 4)          # hue x saturation
HIST_SIZE = (160, 90)        # the scene, not its detail
# SUPERSEDED AS A PLACE TEST. MEASURED 2026-09-20 over 82 game-labelled frames
# across 12 fields (3,321 pairs): worst same-field correlation +0.108, best
# different-field +0.972. No threshold separates them, this one included. The
# constant is kept because `brain/explore` still imports it, and because a
# number with its refutation beside it is worth more than a deleted one.
# Where am I is now answered by vision/whereami from the game's own text.
SAME_PLACE = 0.45

# How often to look. A person crosses the map in tens of seconds, so a couple
# of samples a second captures the shape without filling the disk.
SAMPLE_HZ = 2.0

# How often to ask the model what the player is doing. Seconds.
NOTE_EVERY_SECONDS = 20.0


def signature(frame: np.ndarray) -> np.ndarray:
    """A coarse colour signature of the scene. See SAME_PLACE."""
    import cv2
    small = cv2.resize(frame[:, :, :3], HIST_SIZE, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, list(HIST_BINS), [0, 180, 0, 256])
    return cv2.normalize(hist, hist).flatten().astype("float32")


def likeness(a: np.ndarray, b: np.ndarray) -> float:
    """+1 identical, 0 unrelated. Correlation over the two histograms."""
    import cv2
    return float(cv2.compareHist(a, b, cv2.HISTCMP_CORREL))


@dataclass
class Place:
    """One node of the map: a place the player was, and what it looked like."""
    name: str
    signatures: list = field(default_factory=list)
    visits: int = 0
    pollen_seen: list[int] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def score(self, sig) -> float:
        """Best likeness to any view of this place we already hold."""
        return max((likeness(sig, known) for known in self.signatures),
                   default=-1.0)

    def matches(self, sig, threshold: float = SAME_PLACE) -> bool:
        return self.score(sig) >= threshold

    def absorb(self, sig) -> None:
        # Keep a second view only when it is a genuinely different angle on
        # the same place, so a node does not accumulate a hundred near
        # duplicates over a long session.
        if self.score(sig) < 0.85 and len(self.signatures) < 8:
            self.signatures.append(sig)
        self.visits += 1


class PlayObserver:
    """Samples the screen while a person plays, and builds places and links.

    `frames()` returns the current frame. `read_hud` and `read_panel` are
    optional and only enrich what is recorded -- the map works without them.
    """

    def __init__(self, frames, read_hud=None, read_panel=None,
                 sample_hz: float = SAMPLE_HZ, clock=time.monotonic,
                 sleep=time.sleep, take_note=None,
                 note_every: float = NOTE_EVERY_SECONDS):
        self.frames = frames
        self.read_hud = read_hud
        self.read_panel = read_panel
        self.interval = 1.0 / max(0.2, float(sample_hz))
        self.clock = clock
        self.sleep = sleep
        self.places: list[Place] = []
        self.links: dict[tuple[str, str], int] = {}
        self.samples = 0
        self.skipped = 0
        self._current: Place | None = None
        self._pending = None
        self._last_note = -1e9
        # "make sure the ai is taking notes on everything i do, not coppying
        # exactly ... so it maps everything out and learns from my gameplay".
        # A note is the model's own sentence about what the player is doing,
        # taken now and then rather than every sample, because it costs a
        # second or two and the answer does not change that fast.
        self.take_note = take_note
        self.note_every = float(note_every)

    # ---- building ---------------------------------------------------------
    def place_for(self, sig, create: bool = True):
        """The place this view belongs to, best match first."""
        best, best_score = None, SAME_PLACE
        for place in self.places:
            score = place.score(sig)
            if score >= best_score:
                best, best_score = place, score
        if best is not None or not create:
            return best
        place = Place(name=f"place_{len(self.places) + 1}")
        place.signatures.append(sig)
        self.places.append(place)
        return place

    def sample(self) -> Place | None:
        """Take one look. Returns the place it decided we are in."""
        try:
            frame = self.frames()
        except Exception:
            self.skipped += 1
            return None
        if frame is None or getattr(frame, "size", 0) == 0:
            self.skipped += 1
            return None
        try:
            sig = signature(frame)
        except Exception:
            self.skipped += 1
            return None

        # HYSTERESIS. A single odd frame -- mid-jump, a cannon flash, a
        # loading blink -- must not mint a place. A new signature has to turn
        # up twice in a row before it becomes one; the run that produced 78
        # places from 164 samples is what this exists to prevent.
        place = self.place_for(sig, create=False)
        if place is None:
            if (self._pending is not None
                    and likeness(sig, self._pending) >= SAME_PLACE):
                place = self.place_for(sig, create=True)
                self._pending = None
            else:
                self._pending = sig
                self.samples += 1
                return self._current
        else:
            self._pending = None
        place.absorb(sig)
        self.samples += 1

        if self.read_hud is not None:
            try:
                reading = self.read_hud()
                value = getattr(reading, "value", None)
                if value is not None:
                    place.pollen_seen.append(int(value))
            except Exception:
                pass
        if self.read_panel is not None and len(place.labels) < 3:
            try:
                text = self.read_panel(frame)
                if text and text not in place.labels:
                    place.labels.append(text)
            except Exception:
                pass

        if (self.take_note is not None
                and self.clock() - self._last_note >= self.note_every):
            self._last_note = self.clock()
            try:
                note = self.take_note(frame)
                if note:
                    place.notes.append(" ".join(str(note).split())[:200])
            except Exception:
                pass

        if self._current is not None and self._current is not place:
            key = (self._current.name, place.name)
            self.links[key] = self.links.get(key, 0) + 1
        self._current = place
        return place

    def watch(self, seconds: float, on_place=None) -> None:
        """Sample for a while. Sends nothing, ever."""
        until = self.clock() + seconds
        last: Place | None = None
        while self.clock() < until:
            place = self.sample()
            if place is not None and place is not last and on_place is not None:
                on_place(place)
            last = place
            self.sleep(self.interval)

    # ---- output -----------------------------------------------------------
    def as_map(self) -> dict:
        return {
            "places": [
                {"name": p.name, "visits": p.visits,
                 "views": len(p.signatures),
                 "labels": p.labels, "notes": p.notes,
                 "pollen_range": ([min(p.pollen_seen), max(p.pollen_seen)]
                                  if p.pollen_seen else None)}
                for p in self.places
            ],
            "links": [{"from": a, "to": b, "times": n}
                      for (a, b), n in sorted(self.links.items())],
            "samples": self.samples,
            "skipped": self.skipped,
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_map(), indent=2))
        return path

    def describe(self) -> str:
        return (f"{len(self.places)} places, {len(self.links)} links, "
                f"{self.samples} samples"
                + (f", {self.skipped} frames missed" if self.skipped else ""))

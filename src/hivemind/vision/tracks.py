"""Remembering tokens between frames, so a token has an age and a history.

WHY A DETECTION IS NOT ENOUGH. `vision/tokens.detect` answers "what token-
shaped things are in THIS frame". Chasing on that alone means: a bee that
looks like a token for one frame gets walked to; a real token hidden by a
bubble for one frame is forgotten; a token that has sat there for twenty
seconds and is about to expire looks exactly like one that just spawned; and
nothing can say "that is the same token I saw a moment ago" -- which is what
committing to a target needs.

WHAT A POPULAR MACRO DOES, from its public documentation (read in full,
2026-09-22; docs, not binaries): it keeps "a short-lived record that tells it
how often it's been seen and how long it's existed", refreshed "independently
of movement", so a token covered "for one frame" is not lost; a token is
CONFIRMED after "two vision matches" and default rules require confirmation
before a high-value token can override a pick; TOKEN AGE feeds an urgency
curve near expiry and a stale-token decay when it stops being seen; and
MATCH CONFIDENCE scales the score by how often the vision has matched it --
"zero matches receive large penalty; two+ matches receive full confidence".
That is a tracker, and this is ours.

HOW A SIGHTING IS MATCHED TO A TRACK. Nearest existing track within
`MATCH_PX` of the sighting's screen position, else a new track. Screen
position, not world position: the camera moves, so a static token's screen
position moves too. Between two looks a fraction of a second apart while the
character stands still the move is small compared with the gap between
tokens (measured spacing between distinct tokens is well over 100 px). While
the character WALKS it is not: MEASURED 2026-09-22 (runs 237-239), one 0.35 s
step slides the ground about 90 px, which is the whole match gate, so the
near tokens un-matched and only the far ones kept their tracks. The caller
therefore passes `scene_shift` -- how far the ground moved on screen since
the last look, read by `vision.flow` -- and every remembered position is
carried along with the ground before matching. When the camera TURNS the
whole field slides by hundreds of pixels in a way no shift describes, so the
caller says `turned()` and the memory is cleared rather than mis-matched.
Honest forgetting beats confident mislabelling.

WHAT IT NEVER DOES. It never invents a position it did not see: a track that
has not been matched this frame keeps its LAST seen position and says how
long ago. It never promotes a track on its own; `confirmed` is a count and the
threshold is the caller's to apply.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# A sighting within this many screen pixels of a track's last position is the
# same token. Between frames at the tracker's cadence a walking character
# shifts a static token by tens of pixels; distinct tokens sit well over a
# hundred apart. Generous enough to survive a few frames of walking, tight
# enough not to merge neighbours.
MATCH_PX = 90.0
# Another macro: two vision matches confirm a token. Ours is the same number for
# the same reason -- one match is a bee, a bubble or a glint; two is a thing.
CONFIRMED_AT = 2
# A track not seen for this long is dropped. Tokens in Bee Swarm expire, and a
# thing unseen for several seconds while the camera has not turned is far
# more likely gone than hidden. (Another macro's "sprinkler wait before rescan"
# clears stale detections at 12 s; this is stricter because we do not yet
# distinguish "hidden behind a bubble" from "collected".)
FORGET_AFTER = 4.0
# A track matched ONCE and not seen again is a glint, a bee or a flower's
# edge, and it is forgotten much sooner: MEASURED 2026-09-22 21:10 replaying
# var/incidents/234344-token, the memory carried 103 tracks at t+5 s with
# the four-second rule alone, most of them single sightings that never
# recurred. Another macro's own stale-token decay makes the same distinction
# ("zero matches receive large penalty").
FORGET_UNCONFIRMED_AFTER = 1.0
# Another macro's confidence curve: "zero matches receive large penalty; two+
# matches receive full confidence". One match sits between.
CONFIDENCE_BY_MATCHES = {0: 0.0, 1: 0.5}


@dataclass
class Track:
    """One token, remembered."""
    id: int
    x: int
    y: int
    kind: str = "unknown"
    first_seen: float = 0.0
    last_seen: float = 0.0
    matches: int = 0
    # the detector's best confidence for this token across its matches
    detector_confidence: float = 0.0
    seen_kinds: dict = field(default_factory=dict)
    # HOW MUCH IT MOVES AGAINST THE GROUND. When the caller tells `observe`
    # how far the ground slid, every track is carried with it before
    # matching, so a token lying on the ground lands where it was predicted
    # and a bee, a floating damage number or a passing player does not. The
    # summed residual, in px, over the seconds between looks in which it was
    # measured -- `own_motion()` gives px per second. Only counted on looks
    # that had a ground shift: without one the character's own walking is in
    # the residual and the figure would mean nothing.
    motion_px: float = 0.0
    motion_seconds: float = 0.0
    # WHAT THE SCHOOL THINKS: P(token) for this thing's appearance, averaged
    # over the sightings that carried one (brain/school). None until the
    # school has spoken at all.
    school_p: float | None = None
    school_n: int = 0

    def own_motion(self) -> float | None:
        """Px per second this thing moved against the ground, or None when no
        look has measured it."""
        if self.motion_seconds <= 0:
            return None
        return self.motion_px / self.motion_seconds

    def age(self, now: float) -> float:
        """Seconds since first seen. Another macro's TOKEN AGE."""
        return max(0.0, now - self.first_seen)

    def unseen_for(self, now: float) -> float:
        return max(0.0, now - self.last_seen)

    @property
    def confirmed(self) -> bool:
        return self.matches >= CONFIRMED_AT

    def match_confidence(self) -> float:
        """How sure the tracker is this is a real token, from match count."""
        return CONFIDENCE_BY_MATCHES.get(self.matches, 1.0)

    def describe(self, now: float | None = None) -> str:
        when = "" if now is None else (f", {self.age(now):.1f}s old, last seen "
                                       f"{self.unseen_for(now):.1f}s ago")
        moving = self.own_motion()
        motion = "" if moving is None else f", moves {moving:.0f} px/s against the ground"
        return (f"#{self.id} {self.kind} at ({self.x}, {self.y}) x{self.matches}"
                f"{' confirmed' if self.confirmed else ''}{when}{motion}")


class Tracker:
    """Turns per-frame sightings into tokens with a history."""

    def __init__(self, match_px: float = MATCH_PX, forget_after: float = FORGET_AFTER,
                 forget_unconfirmed_after: float = FORGET_UNCONFIRMED_AFTER):
        self.match_px = float(match_px)
        self.forget_after = float(forget_after)
        self.forget_unconfirmed_after = min(float(forget_unconfirmed_after), self.forget_after)
        self.tracks: dict[int, Track] = {}
        self._next_id = 1
        self.turns = 0            # how many times the memory was cleared for a turn
        self.shifted = 0          # how many looks carried the tracks with the ground

    # ---- feeding it ----------------------------------------------------------
    def observe(self, sightings, now: float,
                scene_shift: tuple[float, float] | None = None,
                scene_transform=None) -> list[Track]:
        """Match this frame's sightings to tracks. Returns the tracks matched
        or created THIS frame, so the caller can tell fresh from remembered.

        `scene_shift` is how far the ground moved on screen since the last
        look, (dx, dy) with +x right and +y down, as `vision.flow` reads it.
        Every remembered position is moved by it first, so a token that slid
        90 px because the character walked is still the same token. Without
        it the tracks stay where they were last seen.

        Each sighting matches at most one track and each track at most one
        sighting, nearest first, so two sightings cannot both claim a track and
        a track cannot split. Anything unmatched becomes a new track.
        """
        measured = scene_shift is not None or scene_transform is not None
        if scene_transform is not None and self.tracks:
            # A 3x3 homography of the GROUND between the last look and this
            # one (from the flow's point pairs): the ground is a plane, so it
            # carries every point lying on it exactly, near and far alike,
            # where one median shift carries the far ones right and drags
            # the near ones short (perspective).
            import numpy as np
            pts = np.array([[[float(t.x), float(t.y)] for t in self.tracks.values()]],
                           dtype=np.float64)
            import cv2
            moved = cv2.perspectiveTransform(pts, np.asarray(scene_transform, dtype=np.float64))[0]
            for t, (nx, ny) in zip(self.tracks.values(), moved):
                if np.isfinite(nx) and np.isfinite(ny):
                    t.x, t.y = int(round(nx)), int(round(ny))
            self.shifted += 1
        elif scene_shift is not None:
            sdx, sdy = scene_shift
            if sdx or sdy:
                for t in self.tracks.values():
                    t.x = int(round(t.x + sdx))
                    t.y = int(round(t.y + sdy))
                self.shifted += 1
        pending = [(s, int(getattr(s, "x", 0)), int(getattr(s, "y", 0))) for s in sightings]
        free = dict(self.tracks)
        pairs = []
        for s, sx, sy in pending:
            for tid, t in free.items():
                d = math.hypot(sx - t.x, sy - t.y)
                if d <= self.match_px:
                    pairs.append((d, sx, sy, s, tid))
        pairs.sort(key=lambda p: p[0])
        touched: list[Track] = []
        used_tracks: set[int] = set()
        used_sightings: set[int] = set()
        for d, sx, sy, s, tid in pairs:
            if tid in used_tracks or id(s) in used_sightings:
                continue
            t = self.tracks[tid]
            if measured and now > t.last_seen:
                t.motion_px += d                      # against the carried prediction
                t.motion_seconds += now - t.last_seen
            t.x, t.y = sx, sy
            t.last_seen = now
            t.matches += 1
            t.detector_confidence = max(t.detector_confidence,
                                        float(getattr(s, "confidence", 0.0) or 0.0))
            self._note_kind(t, getattr(s, "kind", "unknown"))
            self._note_school(t, getattr(s, "school_p", None))
            used_tracks.add(tid)
            used_sightings.add(id(s))
            touched.append(t)
        for s, sx, sy in pending:
            if id(s) in used_sightings:
                continue
            t = Track(id=self._next_id, x=sx, y=sy,
                      kind=str(getattr(s, "kind", "unknown") or "unknown"),
                      first_seen=now, last_seen=now, matches=1,
                      detector_confidence=float(getattr(s, "confidence", 0.0) or 0.0))
            t.seen_kinds[t.kind] = 1
            self._note_school(t, getattr(s, "school_p", None))
            self.tracks[t.id] = t
            self._next_id += 1
            touched.append(t)
        self._forget(now)
        return touched

    def turned(self) -> None:
        """The camera turned: every screen position is now meaningless.

        Forgetting is the honest response. Trying to re-match tracks across a
        45-degree swing would pair tokens with their neighbours and call the
        result a history.
        """
        self.tracks.clear()
        self.turns += 1

    # ---- reading it ----------------------------------------------------------
    def alive(self, now: float) -> list[Track]:
        self._forget(now)
        return sorted(self.tracks.values(), key=lambda t: t.id)

    def confirmed(self, now: float) -> list[Track]:
        return [t for t in self.alive(now) if t.confirmed]

    def get(self, track_id: int) -> Track | None:
        return self.tracks.get(track_id)

    def describe(self, now: float) -> str:
        live = self.alive(now)
        return (f"{len(live)} token(s) remembered, {sum(1 for t in live if t.confirmed)} "
                f"confirmed, memory cleared {self.turns}x for camera turns")

    # ---- housekeeping -------------------------------------------------------
    def _forget(self, now: float) -> None:
        gone = [tid for tid, t in self.tracks.items()
                if now - t.last_seen > (self.forget_after if t.confirmed
                                        else self.forget_unconfirmed_after)]
        for tid in gone:
            del self.tracks[tid]

    @staticmethod
    def _note_school(t: Track, p) -> None:
        if p is None:
            return
        p = float(p)
        t.school_p = p if t.school_p is None else (t.school_p * t.school_n + p) / (t.school_n + 1)
        t.school_n += 1

    @staticmethod
    def _note_kind(t: Track, kind) -> None:
        """A track's kind is whatever it has been named MOST often.

        The detector names a token from one face's colour, and a lit cube at
        an angle reads slightly differently frame to frame; a vote across
        matches is steadier than the latest guess, and an "unknown" never
        outvotes a real name.
        """
        k = str(kind or "unknown")
        t.seen_kinds[k] = t.seen_kinds.get(k, 0) + 1
        named = {n: c for n, c in t.seen_kinds.items() if n != "unknown"}
        if named:
            t.kind = max(named.items(), key=lambda kv: kv[1])[0]
        elif t.kind == "unknown":
            t.kind = "unknown"

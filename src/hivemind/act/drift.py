"""Walking back into the flowers when the pattern has walked out of the field.

A gather pattern is a loop of blind timed holds, and its legs never cancel
exactly: a knock, a slope, a bush, a leg cut short by a mob. So the loop
drifts, and a drift that crosses the field's edge gathers nothing while the
feed stays silent. MEASURED (research `fieldseg` case_drift): on the seven
drift trips with frames at the exit, the character left the aimed field and
the feed named the next field 19-85 s later; attempt 351 left Strawberry,
the feed named Sunflower 36 s later, and the first thing to react was the
pollen-stall line at +287 s (docs/GAPS.md).

Natro Macro closes this loop between every two passes
(`nm_fieldDriftCompensation`, submacros/natro_macro.ahk): it finds its own
sprinkler on screen and holds the keys towards it -- left of centre the left
key, above it the forward key -- until the sprinkler is back in the middle,
polling every 20 ms and giving up after 300 polls (6 s). This bot has no
sprinkler finder, so it steers by the flowers themselves
(vision/fieldsense `flower_bed`): the way to walk is towards the centroid of
the flower-bed cells around the character, in the same screen frame as a
token chase (`act/chase.keys_towards`), one short hold at a time, looking
again after each.

MEASURED whether this direction points into the field (scratchpad
fieldsense/edge_dir.py, 183 ring-buffer windows of gathering, 13,047 pairs of
frames 0.5 s apart, the character's own movement read off the ground's optical
flow): moving towards the centroid the bed share rose 0.054 on average (61% of
the time), moving away it fell 0.031 (38%); on a thin bed (under 0.30) it
rose 72% of the time towards, 54% away and 64% in a random direction; on the
drift trips' windows +0.071 against -0.030. BUT NOT WHERE THE STEER STARTS.
From a bed under the edge (0.08, 508 pairs) a step towards was back over it
five frames later 68% of the time -- and a random direction 68%, sideways
77%, away 55% (scratchpad fieldsense3/edge_replay3.py); back over the stop
level (0.105) 56% towards, 60% random. So at the edge the direction is no
better than chance, and this is shipped LOOKING ONLY (run_farm
`stay_in_field`, `gather.stay_in_field` off): each time it would walk, the
run log says which way and a picture is kept, and `would_steer` is what
answers then.

When it does walk, every step looks again, the walk stops just past the edge
(the trainer's `back_at`) rather than deep in the flowers, and it walks at
most MAX_SECONDS -- the token chase's own ceiling on a detour, not Natro's
6 s: this walk is not undone afterwards, and 17 steps is about 168 studs at
walkspeed 28. It presses nothing but movement keys and runs only between two
passes, never inside one.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import chase, motion

# One step: the token chase's own, measured to correct a wrong heading
# quickly while the look (about 5 ms here) is a small part of it.
STEP_SECONDS = chase.STEP_SECONDS
# At most the token chase's hard ceiling on one detour (chase.MAX_STEPS, 10
# steps: 3.5 s, about 98 studs at walkspeed 28). Natro gives the same job
# 300 polls of 20 ms (6 s), but steers at its own sprinkler, which it can
# find; this steers by a direction measured no better than chance at the
# edge (see above), and leaves the character where the walk ended.
MAX_SECONDS = chase.MAX_STEPS * chase.STEP_SECONDS


@dataclass
class Steer:
    """What one walk back did. `walked` is the only claim that moved anything."""
    before: float = 0.0             # the bed share it started from
    after: float | None = None      # and the last one it saw
    steps: int = 0
    seconds: float = 0.0
    keys: list = field(default_factory=list)
    reason: str = ""
    walkspeed: float = 28.0
    # LOOKING ONLY (`would_steer`): the keys the first step would have held,
    # "" when it would not have walked either.
    would: str = ""
    # The flower bed is back (`back_at` or more) at the last look: a fresh
    # look that already showed it, or a walk that ended there. False is what
    # brain/farm's stuck rule reads as "still off the flowers".
    back: bool = False
    # STEERED BY THE DRIFT (`steer_by_drift`): the ground px still owed to
    # the last look with a good bed, before and after the walk.
    owed: tuple | None = None
    owed_after: tuple | None = None

    @property
    def walked(self) -> bool:
        return self.steps > 0

    @property
    def studs(self) -> float:
        """Time times speed: an estimate, as the chase's is."""
        return self.seconds * self.walkspeed

    def describe(self) -> str:
        if self.would:
            return (f"would steer back towards the flowers ({self.would}), "
                    f"flower bed {self.before:.0%}: {self.reason}")
        if not self.walked:
            return f"not steering back into the flowers: {self.reason}"
        held = " ".join(dict.fromkeys(self.keys))
        after = f"{self.after:.0%}" if self.after is not None else "unread"
        if self.owed is not None:
            left = self.owed_after or self.owed
            return (f"steered back along the drift — {self.steps} step(s) ({held}) "
                    f"towards the last good flower bed, {self.owed[0]:+.0f}, "
                    f"{self.owed[1]:+.0f} px of ground owed -> {left[0]:+.0f}, "
                    f"{left[1]:+.0f}; flower bed {self.before:.0%} -> {after}: "
                    f"{self.reason}")
        return (f"steered back towards the flowers — {self.steps} step(s) "
                f"({held}), flower bed {self.before:.0%} -> {after}: {self.reason}")


def steer_back(frames, bed_of, *, vin, back_at: float, stopped=None,
               sleep=time.sleep, walkspeed: float = 28.0,
               max_seconds: float = MAX_SECONDS,
               step_seconds: float = STEP_SECONDS) -> Steer:
    """Walk towards the flower bed until it is `back_at` or more of the
    ground around the character, the flowers are all round, or `max_seconds`.

    `frames()` returns the current frame and `bed_of(frame)` its
    vision/fieldsense Bed; both are asked before every step, which is what
    makes this a closed loop. A frame too dark or washed out to read stops
    it: it never walks on a guess."""
    stopped = stopped or (lambda: False)
    out = Steer(walkspeed=walkspeed)
    bed = _first_look(frames, bed_of, back_at, out)
    if bed is None:
        return out
    try:
        while out.seconds + step_seconds <= max_seconds + 1e-9:
            if stopped():
                out.reason = out.reason or "stopped"
                break
            keys = chase.keys_towards(*bed.towards)
            if not keys:
                out.reason = ("no flowers in view to walk towards" if bed.share == 0
                              else "the flowers are all round, no way is better")
                break
            with vin.held(*keys):
                sleep(step_seconds)
            out.steps += 1
            out.seconds += step_seconds
            out.keys.append(keys)
            frame = frames()
            if frame is None:
                out.reason = "the next look had no frame"
                break
            bed = bed_of(frame)
            if not bed.informative:
                out.reason = "the next look was too dark or washed out"
                break
            out.after = bed.share
            if bed.share >= back_at:
                out.back = True
                out.reason = (f"back in the flowers ({bed.share:.0%}, "
                              f"at least {back_at:.1%})")
                break
        else:
            out.reason = f"walked the {max_seconds:.1f}s it may"
    finally:
        try:
            vin.release_all()        # belt to `held()`'s braces
        except Exception:
            pass
    return out


def would_steer(frames, bed_of, *, back_at: float,
                walkspeed: float = 28.0) -> Steer:
    """What `steer_back` would do first, PRESSING NOTHING: the same fresh
    look and the same keys its first step would hold, in `Steer.would`
    ("" when it would not walk either, with the reason). For the owner's
    switch off, so the first live runs show what it would have done."""
    out = Steer(walkspeed=walkspeed)
    bed = _first_look(frames, bed_of, back_at, out)
    if bed is None:
        return out
    out.would = chase.keys_towards(*bed.towards)
    if not out.would:
        out.reason = ("no flowers in view to walk towards" if bed.share == 0
                      else "the flowers are all round, no way is better")
    return out


def _first_look(frames, bed_of, back_at: float, out: Steer):
    """The look before the first step: its Bed, or None with `out.reason`
    saying why there is nothing to walk on."""
    frame = frames()
    if frame is None:
        out.reason = "no frame to look at"
        return None
    bed = bed_of(frame)
    if not bed.informative:
        out.reason = "the frame is too dark or washed out to read"
        return None
    out.before = out.after = bed.share
    if bed.share >= back_at:
        out.back = True
        out.reason = f"a fresh look already shows {bed.share:.0%} flower bed"
        return None
    return bed


# ---- steering back by the drift, when no flowers are in view ---------------
# MEASURED 2026-10-15 04:33-04:44 (var/night/run-1013.log, ROADMAP A21): a
# Blue Flower gather walked off the flowers onto the red cannon's platform;
# for 11 min every look said "no flowers in view to walk towards" -- the bed
# steer has nothing to aim at -- and the pollen stayed flat. The ground's
# flow had measured the walk off ((-1322, +1031) px net over the gather).
# NOT THE WHOLE GATHER'S SUM: walked back from the gather's start, that sum
# missed 0 of 3 (run_farm WALK_BACK_THE_DRIFT, 2026-10-10, ~1,600-2,300 px
# out). So this walks back only what the ground moved SINCE THE LAST LOOK
# WITH A GOOD BED (run_farm `stay_in_field` keeps it), a far shorter sum,
# looks after every step and stops as soon as the bed is back, or the debt is
# paid, or the steps run out.
# A bound, not a measurement: the token chase's ceiling on a detour.
DRIFT_STEPS = chase.MAX_STEPS
# Two steps in a row the flow could not measure, or that moved nothing, end
# it: walking on an unmeasured debt is the 0-of-3 above (act/chase BLIND_STEPS).
DRIFT_BLIND_STEPS = chase.BLIND_STEPS


def good_bed(looks, back_at: float) -> bool:
    """Did any informative look show the bed at `back_at` or more?"""
    return any(getattr(lk, "informative", False) and lk.bed.share >= back_at
               for lk in looks)


def steer_by_drift(frames, bed_of, *, vin, owed, back_at: float, odometer,
                   stopped=None, sleep=time.sleep, walkspeed: float = 28.0,
                   max_steps: int = DRIFT_STEPS,
                   step_seconds: float = STEP_SECONDS) -> Steer:
    """Walk the ground `owed` (dx, dy) px back, screen x right and y down:
    the ground moved that far since the last good bed, so the character moved
    the other way and walks `keys_towards(dx, dy)` to undo it. Every step is
    measured (`motion.hold_measuring` on `odometer`), its ground motion paid
    off the debt, and the bed looked at after it."""
    stopped = stopped or (lambda: False)
    out = Steer(walkspeed=walkspeed)
    bed = _first_look(frames, bed_of, back_at, out)
    if bed is None:
        return out
    dx, dy = float(owed[0]), float(owed[1])
    out.owed = (dx, dy)
    blind = 0
    try:
        while True:
            if out.steps >= max_steps:
                out.reason = f"walked the {max_steps} steps it may"
                break
            if stopped():
                out.reason = "stopped"
                break
            keys = chase.keys_towards(dx, dy)
            if not keys:
                out.reason = "the drift is walked back and still no flower bed"
                break
            hold = motion.hold_measuring(vin, keys, step_seconds, sleep, frames,
                                         odometer)
            out.steps += 1
            out.seconds += step_seconds
            out.keys.append(keys)
            if hold is None or hold[0] == 0 or motion.stuck(hold):
                blind += 1
                if blind >= DRIFT_BLIND_STEPS:
                    out.reason = (f"{blind} steps in a row the flow could not "
                                  f"measure or that moved nothing")
                    break
            else:
                blind = 0
                dx, dy = dx + hold[1], dy + hold[2]
            out.owed_after = (dx, dy)
            frame = frames()
            if frame is None:
                out.reason = "the next look had no frame"
                break
            bed = bed_of(frame)
            if not bed.informative:
                out.reason = "the next look was too dark or washed out"
                break
            out.after = bed.share
            if bed.share >= back_at:
                out.back = True
                out.reason = (f"back in the flowers ({bed.share:.0%}, "
                              f"at least {back_at:.1%})")
                break
    finally:
        try:
            vin.release_all()
        except Exception:
            pass
    return out


# ---- a look round, for when no flowers are in view at all -------------------
# `steer_back` walks towards the flower bed it can see, and stops with "no
# flowers in view to walk towards" when there is none -- which is exactly where
# a gather that drifted off its field leaves the character facing: MEASURED
# 2026-09-27 (attempts 504-508), Bamboo's walk home missed the 3 times its last
# looks said that, and landed the 3 times the gather ended in the flowers. So
# before a walk home, the camera goes round in LOOKS turns of LOOK_TAPS (a
# quarter each, eight taps to a full turn), the flower bed is read after
# each, and the character is left facing whichever heading showed the most.
LOOKS = 4
LOOK_TAPS = 2
LOOK_SETTLE_SECONDS = 0.35
# A22c: under this share at every heading read, the look round found no
# flowers at all (run 1013 04:44 stood on the red cannon, 0% all round).
NOWHERE_SHARE = 0.01


@dataclass
class LookRound:
    """What one look round saw: the flower-bed share at each heading, as taps
    from where it began (None where the look could not be read), and the taps
    it ended turned by."""
    shares: dict = field(default_factory=dict)
    turned: int = 0

    @property
    def best(self) -> tuple[int, float] | None:
        seen = [(taps, share) for taps, share in self.shares.items() if share]
        return max(seen, key=lambda pair: pair[1]) if seen else None

    @property
    def nowhere(self) -> bool:
        """Some heading was read, and none showed NOWHERE_SHARE of flowers:
        the start is unknown, so a route timed from inside a field cannot
        land from it (A22c)."""
        read = [s for s in self.shares.values() if s is not None]
        return bool(read) and max(read) < NOWHERE_SHARE

    def describe(self) -> str:
        looks = ", ".join(f"{taps * 45}°: {'-' if s is None else f'{s:.0%}'}"
                          for taps, s in sorted(self.shares.items()))
        best = self.best
        return (f"looked round for the flowers ({looks})"
                + (f" — facing the most, {best[1]:.0%} at {best[0] * 45}°" if best
                   else " — none in any direction"))


def look_round(frames, bed_of, *, turn, looks: int = LOOKS, taps: int = LOOK_TAPS,
               settle: float = LOOK_SETTLE_SECONDS, sleep=time.sleep) -> LookRound:
    """Turn the camera round in `looks` turns of `taps` (one full turn when
    looks x taps is eight), reading `bed_of(frames())` after each, and end
    facing the heading that showed the most flower bed -- or where it began
    when none did. `turn(n)` taps the camera n times (negative left) and tells
    the compass. Presses nothing but the camera keys."""
    out = LookRound()
    for look in range(looks):
        if look:
            turn(taps)
            out.turned += taps
            sleep(settle)
        frame = frames()
        bed = bed_of(frame) if frame is not None else None
        share = bed.share if bed is not None and bed.informative else None
        out.shares[(look * taps) % 8] = share
    # back round to the best heading (or the start), the short way
    best = out.best
    want = best[0] if best else 0
    delta = ((want - out.turned) % 8 + 4) % 8 - 4
    if delta:
        turn(delta)
    out.turned += delta
    return out

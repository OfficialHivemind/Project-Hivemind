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

import math
import time
from dataclasses import dataclass, field

from . import chase, motion
from .routes import pass_drift

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


# ---- the sprinkler anchor: back to the sprinkler between passes (LOOK ONLY) --
# What other macros do between two passes (see the module docstring): find
# their own sprinkler and walk until it is back under the character. This bot
# can now find its Golden Gushers (vision/sprinkler, measured in
# docs/pending/ai-sprinkler.md), so this says which keys that walk would hold
# -- and holds none: SPRINKLER_ANCHOR_LIVE is False until the logged "would"
# lines have been checked against the frames they were read from.
SPRINKLER_ANCHOR_LIVE = False
# AND AT THE END OF EVERY GATHER, before the walk home (run_farm
# `end_at_the_sprinkler`, brain/farm `end_of_gather`): back to the sprinkler,
# so the walk home starts where the field's route expects -- the spot the
# sprinkler was placed on, the pattern's start. LOOK-ONLY on its own switch.
SPRINKLER_RETURN_LIVE = False
# Within this many px of the character (full 1920x1080 frame, the gather's
# zoomed-out view) the sprinkler counts as under it. MEASURED 2026-10-27
# (docs/pending/sprinkleranchor.md, 8,193 gather-pattern frames of runs
# 896-1259 through vision/sprinkler.find): on the pattern's first frame, the
# character standing on the sprinkler just placed, the foot read within 170 px
# 76% of the time (median 130, dy median -114: the post's foot is behind the
# character, so the box ends at its back); on every later frame of the pass,
# 10%. The chase's 110 px would have said "walk" on 72% of the on-the-
# sprinkler looks.
ANCHOR_BOX_PIXELS = 170
# At most the token chase's ceiling on one detour, as `steer_back`.
ANCHOR_STEPS = chase.MAX_STEPS

# ---- OURS, NOT ANOTHER PLAYER'S ------------------------------------------------
# The finder sees every Golden Gusher, and on a server with other players
# theirs stand in the same fields (MEASURED: var/routes/attempt-1173/232805-
# natro_pattern_pine_tree_as_natro-05-walk-a32.jpg and attempt-1163/164324-...
# show another player's nametag beside the Gushers that Pine Tree's frames of
# runs 1163-1178 kept boxing far left). Ours is where WE placed it: under the
# character at the placing, moved across the screen since then only by our
# own walk. `walked` is that walk as (studs right, studs forward), camera-
# relative, from the route runner's own ledger (act/routes RouteRunner.walked).
# ASSUMED, not measured past a gather's first pass: the token chases walk back
# to where they began (chase CARRY), so they are left out; and the camera
# holds its heading through a gather (camsweep gives back every tap) -- a turn
# kept after a walk would rotate where ours stands. The live "would" lines
# with their kept frames are what checks this.
#
# WHERE OURS STANDS AFTER A WALK: a ground plane seen from behind the
# character -- x shrinks with depth, and walking forward leaves it nearer the
# camera, lower on the screen. FITTED 2026-10-27 (docs/pending/ownsprinkler.md,
# every box on the first-pass pattern frames of the Gusher gathers, runs
# 896-1248, fit on the train/val runs, scored on the test runs): its nearest
# box lands within 250 px of this point on 78% of the test frames, against 63%
# for a flat px-per-stud scale and 7.5% for "it stays where it was placed".
OWN_DEPTH_STUDS = 50.0        # the character's depth from the camera
OWN_FOCAL_PX = 2100.0
OWN_HORIZON_PX = -1000.0      # screen dy of the horizon from chase.ANCHOR
# ...placed under the character, its foot reads behind its back: MEASURED
# median dy -114, dx -2 on the placing frame (docs/pending/sprinkleranchor.md).
# The stack of three can stand in front too (14% of the placing frame's boxes
# within 300 px read below the character's feet, p95 dy +148), so the placed
# spot runs from there to the feet (dy 0).
OWN_PLACED_DY = -114.0
# A WALL ONLY CUTS A WALK SHORT, so ours is anywhere between the placing spot
# and the whole walk, side and forward each (ASSUMED: exact for one leg, near
# for several -- a leg the wall cut and an opposite one walked in full end
# past the sum). That box of the ground, sampled every OWN_SAMPLE_STUDS (a
# Natro tile, the patterns' own unit) up to OWN_MAX_SAMPLES a side.
# ponytail: past 160 studs a side the samples thin out and a drifted post
# between two of them can be missed -- a look that walks nowhere, not a wrong one.
OWN_SAMPLE_STUDS = 4.0
OWN_MAX_SAMPLES = 40
# How far from that ground box a box may read and still be ours. MEASURED
# (ownsprinkler.md, 2,098 boxes on 1,724 first-pass frames): the stack of three
# spreads up to ~260 px on one placing frame; 361 of the placing frames' 399
# boxes are kept. By eye, all 53 picks it takes away from today's anchor: 0
# ours; 12 not a sprinkler (bee, token, bear face), 18 Gushers in the Pine Tree
# spot another player used (runs 1163-1173), 2 more far from ours (one is the
# 810 px post of sprinkleranchor.md), 21 Gushers 330-840 px from where ours
# was just placed with no owner in view.
OWN_RADIUS_PX = 300.0
# A box cut by the screen's side edge has its foot somewhere past that edge.
OWN_EDGE_PX = 2


def placed_at(right: float, forward: float) -> tuple[float, float]:
    """Where on screen (dx, dy px from chase.ANCHOR) a sprinkler placed under
    the character stands after the character walked `right`, `forward` studs."""
    z = max(OWN_DEPTH_STUDS - forward, 1.0)
    return (OWN_FOCAL_PX * -right / z,
            OWN_HORIZON_PX * (1.0 - OWN_DEPTH_STUDS / z) + OWN_PLACED_DY)


def ours(seen, shape, walked, *, radius: float = OWN_RADIUS_PX) -> list:
    """The sightings in `seen` that can be OUR sprinkler, the nearest to where
    ours can be first: the rest are another player's (or not a sprinkler).
    `shape` is the frame's; `walked` (studs right, forward) since the placing."""
    h, w = shape[:2]
    right, forward = walked
    n = min(OWN_MAX_SAMPLES, max(1, math.ceil(abs(right) / OWN_SAMPLE_STUDS)))
    m = min(OWN_MAX_SAMPLES, max(1, math.ceil(abs(forward) / OWN_SAMPLE_STUDS)))
    spots = [(qx, qy + lift) for i in range(n + 1) for j in range(m + 1)
             for qx, qy in [placed_at(right * i / n, forward * j / m)]
             for lift in (0.0, -OWN_PLACED_DY)]
    keep = []
    for s in seen:
        fx = s.x + s.w / 2 - w * chase.ANCHOR[0]
        fy = s.y + s.h - h * chase.ANCHOR[1]
        cut_left, cut_right = s.x <= OWN_EDGE_PX, s.x + s.w >= w - OWN_EDGE_PX
        if cut_left or cut_right:
            # side only, and nothing for a spot further out than the cut box
            off = min(0.0 if (cut_left and qx < fx) or (cut_right and qx > fx)
                      else abs(fx - qx) for qx, _ in spots)
        else:
            off = min(math.hypot(fx - qx, fy - qy) for qx, qy in spots)
        if off <= radius:
            keep.append((off, s))
    return [s for _, s in sorted(keep, key=lambda t: t[0])]


@dataclass
class Anchor:
    """One look for the sprinkler: the best sighting, where its foot stands
    from the character, and the keys a walk back would hold ("" = none)."""
    seen: object = None             # vision/sprinkler.Sighting or None
    offset: tuple | None = None     # (dx, dy) px, screen x right, y down
    would: str = ""
    reason: str = ""
    others: list = field(default_factory=list)   # sightings that are not ours

    def describe(self, what: str = "sprinkler anchor") -> str:
        return f"{what} would: {self.reason}"


def sprinkler_anchor(frame, find, *, box: float = ANCHOR_BOX_PIXELS,
                     walked=None) -> Anchor:
    """Where the sprinkler is from the character and which way back, PRESSING
    NOTHING. `find(frame)` is vision/sprinkler.find: sightings best first.
    The FOOT of the post (bottom centre of its box) is aimed at, not its
    middle: a tall post close by has its middle well above where it stands.
    With `walked` (studs right, forward since the placing), only OUR
    sprinkler counts (`ours`); without it, the best sighting, as before."""
    out = Anchor()
    if frame is None:
        out.reason = "nothing (no frame to look at)"
        return out
    seen = find(frame)
    if not seen:
        out.reason = "nothing (no sprinkler in view)"
        return out
    h, w = frame.shape[:2]
    not_ours = ""
    if walked is not None:
        mine = ours(seen, frame.shape, walked)
        out.others = [s for s in seen if s not in mine]
        if out.others:
            o = out.others[0]
            not_ours = (f"; {len(out.others)} not ours, e.g. "
                        f"{o.x + o.w / 2 - w * chase.ANCHOR[0]:+.0f}, "
                        f"{o.y + o.h - h * chase.ANCHOR[1]:+.0f} px")
        if not mine:
            out.reason = (f"nothing (no sprinkler where ours can be after walking "
                          f"{walked[0]:+.0f} right, {walked[1]:+.0f} forward{not_ours})")
            return out
        seen = mine
    s = out.seen = seen[0]
    dx = s.x + s.w / 2 - w * chase.ANCHOR[0]
    dy = s.y + s.h - h * chase.ANCHOR[1]
    out.offset = (dx, dy)
    where = (f"sprinkler {dx:+.0f}, {dy:+.0f} px from the character, "
             f"score {s.score:.2f}{not_ours}")
    if (dx * dx + dy * dy) ** 0.5 <= box:
        out.reason = f"stay ({where}, within {box:.0f} px)"
        return out
    out.would = chase.keys_towards(dx, dy)
    out.reason = (f"hold {out.would} ({where})" if out.would
                  else f"stay ({where}, inside the deadzone)")
    return out


@dataclass
class AnchorWalk:
    """What one walk back to the sprinkler did: the first look, the steps."""
    first: Anchor | None = None
    steps: int = 0
    keys: list = field(default_factory=list)
    arrived: bool = False
    reason: str = ""

    @property
    def walked(self) -> bool:
        return self.steps > 0

    def describe(self, what: str = "sprinkler anchor") -> str:
        if not self.walked:
            return f"{what}: not walking -- {self.reason}"
        held = " ".join(dict.fromkeys(self.keys))
        return f"{what}: {self.steps} step(s) ({held}) back to the sprinkler -- {self.reason}"


def steps_walked(keys, walkspeed: float = 28.0,
                 step_seconds: float = STEP_SECONDS) -> tuple[float, float]:
    """(studs right, studs forward) of chase steps walked, `keys` one entry a
    step (a Steer's or an AnchorWalk's `keys`), as planned: what `ours` needs
    of any walk the route runner did not walk itself."""
    return pass_drift([{"op": "walk", "keys": k, "studs": walkspeed * step_seconds}
                       for k in keys])


def walk_to_sprinkler(frames, find, *, vin, stopped=None, sleep=time.sleep,
                      box: float = ANCHOR_BOX_PIXELS, max_steps: int = ANCHOR_STEPS,
                      step_seconds: float = STEP_SECONDS, walked=None,
                      walkspeed: float = 28.0) -> AnchorWalk:
    """Walk back until the sprinkler is within `box` px of the character:
    a look (`sprinkler_anchor` on `frames()`), one chase step towards the
    post's foot, a look again. It never walks on a guess: no sprinkler at
    the first look is no walk, and one lost after a step ends it (walked
    onto, the post is hidden behind the character: MEASURED, the foot reads
    -114 px above the character when standing on it). With `walked` (studs
    since the placing) it walks only to OUR sprinkler, each step added to that
    walk at `walkspeed`. Only for the switches SPRINKLER_ANCHOR_LIVE /
    SPRINKLER_RETURN_LIVE."""
    stopped = stopped or (lambda: False)
    out = AnchorWalk()
    try:
        while True:
            look = sprinkler_anchor(frames(), find, box=box, walked=walked)
            if out.first is None:
                out.first = look
            if look.offset is None:
                out.reason = (look.reason if not out.steps else
                              "lost from view after the last step (under the character?)")
                break
            if not look.would:
                out.arrived = True
                out.reason = look.reason
                break
            if out.steps >= max_steps:
                out.reason = f"walked the {max_steps} steps it may, {look.reason}"
                break
            if stopped():
                out.reason = "stopped"
                break
            with vin.held(*look.would):
                sleep(step_seconds)
            out.steps += 1
            out.keys.append(look.would)
            if walked is not None:
                r, f = steps_walked([look.would], walkspeed, step_seconds)
                walked = (walked[0] + r, walked[1] + f)
    finally:
        try:
            vin.release_all()
        except Exception:
            pass
    return out


# ---- the sprinkler search: a camera look round when it is out of view -------
# The anchor above can only act on a sprinkler it sees, and it is in view on
# 22% of gather looks (1,840 / 8,193, docs/pending/sprinkleranchor.md). So
# where the anchor would act -- between passes, at the end of the gather --
# a look that sees nothing turns the camera and looks again, then turns back.
# LOOK-ONLY: SPRINKLER_SEARCH_LIVE is False until its kept frames are graded;
# off, it says which headings it would look at and what that costs.
SPRINKLER_SEARCH_LIVE = False
# WHAT A TURN FINDS. MEASURED 2026-10-27 (docs/pending/sprinklersearch.md):
# the home routes that turn the camera in place at the gather's end (runs
# 896-1259, 47 trips whose sprinkler the game took: Strawberry and Sunflower
# 2 taps left, Dandelion 2 right, Pumpkin 4 left after a short step), by eye:
# out of view at the start look on 35; ONE tap found it on 3 of 35 (9%), a
# second tap no more; up to FOUR taps one way found it on 5 of the 17 Pumpkin
# trips (29%), 4 of them at the third tap (135 degrees). Those frames are
# zoomed in; the gather's zoomed-out view sees more ground (ASSUMED: finds at
# least as often). Between passes, the cheap look either side; at the end of
# the gather, once a trip, the whole way round (it ends where it began).
SEARCH_PASS_HEADINGS = (1, -1)
SEARCH_END_HEADINGS = (1, 2, 3, 4, 5, 6, 7)
# Seconds a tap costs. From the code: run_farm's `turn_camera` is a 40 ms
# tap (platform/input) and a 0.25 s wait, ~0.29 s; vision/sprinkler.find is
# ~1 ms a frame. So +-1 is 4 taps (1.2 s) and the whole way round 8 (2.3 s)
# when nothing is found. NO EXTRA SETTLE before a look (SEARCH_SETTLE_SECONDS):
# the finds above were on frames the route runner keeps 0.1 s after its tap
# (act/routes CAMERA_GAP; MEASURED 0.279 s from one tap's frame to the next,
# median of 97), and `turn_camera` already waits 0.25 s. The flower look
# round's 0.35 s settle would add 0.7 s to +-1 and 2.5 s to the whole way.
SEARCH_TAP_SECONDS = 0.29
SEARCH_SETTLE_SECONDS = 0.0
# A gather pass is 17.2 s (median, var/trips.jsonl, 1,337 trips of runs
# 896-1259), so a +-1 search on every pass that lost the sprinkler would cost
# ~5% of gather time (78% x 1.2 s / 17.2 s). At most one search in this many
# passes: ~1.8%. ponytail: a cost bound, not measured to pay; the live A/B
# (pattern_blocks) is what tunes it.
SEARCH_PASS_EVERY = 3


def search_taps(headings) -> int:
    """Taps a search through `headings` turns when it finds nothing: to each
    heading the short way, then back to where it began."""
    taps, at = 0, 0
    for h in list(headings) + [0]:
        taps += abs(((h - at) % 8 + 4) % 8 - 4)
        at = h
    return taps


@dataclass
class Search:
    """One search: the taps each look was turned by from the start (`looked`),
    the heading it was found at (None = not found) and its Anchor there."""
    headings: tuple = ()
    looked: list = field(default_factory=list)
    found_at: int | None = None
    anchor: Anchor | None = None
    turned: int = 0                 # net taps it left the camera turned by
    taps: int = 0                   # every tap sent
    frames: dict = field(default_factory=dict)   # heading -> the frame it saw it in

    def describe(self, what: str = "sprinkler search") -> str:
        cost = f"{search_taps(self.headings)} taps, ~{search_taps(self.headings) * SEARCH_TAP_SECONDS:.1f}s"
        where = ", ".join(f"{h * 45:+d}°" for h in self.headings)
        if not self.looked:
            return f"{what} would: look at {where} ({cost}) -- not in view here"
        if self.found_at is None:
            return f"{what}: not found at {where} ({self.taps} taps)"
        return (f"{what}: found at {self.found_at * 45:+d}° after {self.taps} taps -- "
                f"{self.anchor.reason}")


def search_sprinkler(frames, find, *, turn, headings=SEARCH_PASS_HEADINGS,
                     stay: bool = False, settle: float = SEARCH_SETTLE_SECONDS,
                     stopped=None, sleep=time.sleep) -> Search:
    """Turn the camera to each of `headings` (taps from where it began, 45
    degrees a tap, the short way), looking (`sprinkler_anchor`) after each,
    until the sprinkler is seen. Then back to where it began -- or, `stay`,
    left facing it for a walk (the caller turns back `out.turned` after: WASD
    is camera-relative, and the walk home needs the heading it began with,
    act/camsweep). Whatever stops it part way, the heading is given back
    unless it was found with `stay`. `turn(n)` is run_farm's counted
    `turn_camera`. Presses nothing but the camera keys."""
    stopped = stopped or (lambda: False)
    out = Search(headings=tuple(headings))
    try:
        for h in out.headings:
            if stopped():
                break
            delta = ((h - out.turned) % 8 + 4) % 8 - 4
            if delta:
                turn(delta)
                out.turned += delta
                out.taps += abs(delta)
            sleep(settle)
            frame = frames()
            look = sprinkler_anchor(frame, find)
            out.looked.append(h)
            if look.offset is not None:
                out.found_at, out.anchor = h, look
                out.frames[h] = frame
                break
    finally:
        if out.turned and not (stay and out.found_at is not None):
            back = ((-out.turned) % 8 + 4) % 8 - 4
            turn(back)
            out.taps += abs(back)
            out.turned = 0
    return out

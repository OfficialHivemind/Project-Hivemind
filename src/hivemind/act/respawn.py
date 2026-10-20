"""Coming home from an errand the way Natro Macro does: by respawning.

THE PROBLEM. Every quest giver, dispenser and machine has a recorded route
FROM the hive and, for all but two, no route back. So a visit ended with
"did not walk back ... the next trip's route guard walks to the hive first,
and the rejoin is behind that" -- and the rejoin is what actually happened:
75 seconds of loading, and it leaves the server, which the owner says resets
the Wealth Clock streak he wants kept ("rejoining is slow and also it resets
wealth clock"). MEASURED 2026-09-23 18:17: the Bucko Bee recon ended at the
Blue HQ, the next trip's guard ran a walk home meant for the Spider Field
from there, and the attempt ended in a rejoin having gathered nothing.

WHAT NATRO DOES. natro_macro.ahk (GPLv3, read 2026-09-23) calls `nm_Reset()`
after every collectible and quest giver -- thirty-odd call sites -- and then
`nm_gotoRamp()` for the next thing. A respawn puts the character at the
spawn point facing the hive row -- spawn heading -- which is exactly where
every Natro route out starts; MEASURED here too: a respawn restores the
camera (DESIGN 8a, two post-reset views 0.991 similar), and where it lands
is the paragraph below.

WHY THIS IS NOT THE RESET THIS PROJECT BANNED. The ban was earned: a reset
is a death and death empties the backpack ("when i die i loose all pollen
and go back to hive"), so a reset on the WAY HOME threw the whole haul away.
An errand is the one moment that cost is nothing, because errands run only
after a convert has emptied the bag (brain/farm.errand_is_safe). This module
is the check that makes that true at the moment of pressing, rather than
assumed from the sequence: it reads the pollen counter and refuses unless
the bag is empty, or near enough that a stray token picked up on the walk
over is all that would be lost.

WHERE IT LANDS. At the SPAWN POINT, not on the pad. MEASURED 2026-09-23
19:49:52 (`var/respawn/194952-no-prompt.jpg`): after the respawn the
character stands on the grey slabs in front of the hive row, the owner's pad
straight ahead a few tiles away, and `act/hive.hive_bearing` reads 85,197
honeycomb pixels -- the homing module's own figure for "one step off a pad"
is 82,941. Natro's comment on its return paths says why the pad is straight
ahead: the default SpawnLocation "aligns with Hive 3", and this account owns
slot 3. That is exactly where every Natro route out begins, because every
`gtf-*` opens with `nm_gotoRamp()` AFTER `nm_Reset()`, and the next trip
does start from there without the route guard objecting (19:49:52 ->
"staying up to 906s this trip", no "going back first"). So the pad's prompt
is NOT the thing to wait for after a respawn; the hive row in view is.

WHAT IT PRESSES. Nothing itself. The keys are the runner's guarded `reset`
(act/routes._reset): Escape, R, and Return ONLY once the respawn confirmation
is seen on screen (vision/screenstate.reset_dialog_present), because the
menu underneath carries Leave and Log Out.
"""
from __future__ import annotations

from dataclasses import dataclass

# HOW FULL A BAG MAY BE AND STILL BE RESPAWNED AWAY. A share of the
# backpack, because the bag's size is what makes a number small: 1% of a
# 1,113,750 backpack is about 11,000 pollen, which is what walking past a few
# tokens on the way to a bear picks up (the Bucko Bee recon read 1,958 on
# arrival) and about ten seconds of gathering. A rejoin costs 75 seconds and
# the Wealth Clock streak. This is a chosen ratio, not a measurement, and it
# is deliberately small: the rule stays "do not throw pollen away", with an
# exception the size of a rounding error.
MAX_BAG_SHARE = 0.01
# What the bar reads when the digits cannot be -- the same figure the convert
# dwell trusts (brain/farm.BAR_EMPTY, measured against known-empty frames).
BAR_EMPTY = 0.02


@dataclass
class Verdict:
    ok: bool
    reason: str


def bag_is_empty_enough(reading, *, share: float = MAX_BAG_SHARE,
                        bar_empty: float = BAR_EMPTY) -> Verdict:
    """May this bag be respawned away? Decided from the HUD, never assumed.

    `reading` is a HUD pollen reading with `.value` (the counter, or None
    when illegible), `.capacity` and `.bar_fill` (0-1, or None). Legible
    digits decide; the bar decides only when the digits cannot; and no
    reading at all is a refusal, because "cannot tell" must never become
    "empty".
    """
    value = getattr(reading, "value", None)
    capacity = getattr(reading, "capacity", None)
    bar = getattr(reading, "bar_fill", None)
    if value is not None:
        if value <= 0:
            return Verdict(True, "the counter reads 0")
        if capacity:
            limit = int(float(capacity) * share)
            if value <= limit:
                return Verdict(True, f"the counter reads {value:,}, under "
                                     f"{share:.0%} of the {int(capacity):,} bag")
            return Verdict(False, f"the counter reads {value:,} — more than "
                                  f"{share:.0%} of the bag, and a respawn would "
                                  f"lose it")
        return Verdict(False, f"the counter reads {value:,} and the bag's size "
                              f"is unknown, so how much that is cannot be said")
    if bar is not None:
        if bar <= bar_empty:
            return Verdict(True, f"the digits are illegible but the bar reads "
                                 f"{bar:.0%}, which is empty")
        return Verdict(False, f"the digits are illegible and the bar reads "
                              f"{bar:.0%} — not empty")
    return Verdict(False, "no pollen reading at all — refusing rather than "
                          "guessing the bag is empty")


def bag_reads_zero(reading) -> bool:
    """Does the counter say, in legible digits, that the bag holds nothing?

    STRICTER THAN `bag_is_empty_enough`, ON PURPOSE. That one lets an errand
    respawn away up to `MAX_BAG_SHARE` of the bag, or trust the bar when the
    digits are illegible, because an errand runs straight after a convert.
    This is for the respawn after a missed route OUT (run_farm `at_my_hive`,
    DESIGN 8de), which is not that moment, so there is no share and no bar:
    only a counter that reads 0. The errand rule's cost is why, MEASURED in
    the errand respawns' own verdicts ("the counter reads 1,998, under 1% of
    the 1,113,750 bag") in runs 320, 321, 323, 333 and 339: 1,122 to 2,893
    pollen thrown away each time.

    `reading` is a HUD pollen reading (`brain.farm.Reading`), whose `value`
    is None whenever the digits did not parse. None is never zero.
    """
    value = getattr(reading, "value", None)
    return value is not None and value <= 0


# THE HIVE ROW IN VIEW, by the homing module's measured scale: fields read
# 0-15,000 honeycomb pixels, the hive at the horizon 22,000-54,000, one step
# off a pad 82,941, the spawn point 85,197. `act/homing.NEAR_YELLOW`.
try:
    from .homing import NEAR_YELLOW as ROW_IN_VIEW_YELLOW
except Exception:                                   # pragma: no cover
    ROW_IN_VIEW_YELLOW = 50_000


# CLOSER TO THE HIVE THAN THE SPAWN POINT EVER READS IS ON THE PAD. MEASURED
# 2026-09-29 over var/respawn and the run logs (run-510..531): the respawns that
# stood on our own pad with an empty bag read 113,522-134,452 honeycomb px (11),
# the spawn point 73,926-83,816 (8). The empty-bag banner fades in after the
# respawn, so a "spawn" this close is looked at a little longer for it
# (run_farm PAD_HINT_WAIT_S) before the walk forward -- which, from the pad,
# walks off it.
ON_PAD_YELLOW = 100_000


@dataclass
class Landing:
    ok: bool
    where: str
    reason: str


def landed(prompt_showing: bool, yellow: int,
           near: int = ROW_IN_VIEW_YELLOW) -> Landing:
    """Did the respawn put us back at the hive? Decided from what is on
    screen, in the order the evidence deserves.

    The pad's own prompt is the strongest -- it means we happen to be ON the
    pad. The honeycomb wall filling the view means the spawn point in front
    of the row, which is where a respawn lands and where Natro's routes
    start; that is the normal case. Neither means the respawn did not land
    where it should, and the caller says so with the frame kept.
    """
    if prompt_showing:
        return Landing(True, "pad", "the pad's own prompt is showing")
    if int(yellow) >= int(near):
        return Landing(True, "spawn",
                       f"the hive row fills the view ({int(yellow):,} honeycomb "
                       f"px; the row reads {int(near):,}+ from the spawn point)")
    return Landing(False, "unknown",
                   f"neither the pad's prompt nor the hive row is in view "
                   f"({int(yellow):,} honeycomb px, under {int(near):,})")


# HOW MANY RESPAWNS A WALK OUT MAY TAKE TO GET THE STANDARD VIEW (run_farm
# RESPAWN_VIEWS / RESPAWN_VIEW_MAX_SHIFT), and the view is looked at after
# EVERY one of them. Until 2026-10-19 only the first was looked at: an off
# view was respawned once more and whatever that one left was walked from.
# MEASURED over var/respawn and var/night (docs/pending/leg3-respawn.md): 231
# of 1,053 such second respawns were still off -- 72 px at 21:09:13 on 19 Oct
# became 212 px at 21:09:22, and natro_out_polar_bear ended in the Mushroom
# Field ("only 6% of the ground under us is the yellow path"). Of the 20 leg-3
# path failures on record, the 4 that set off from an off view all set off
# from such an unchecked second respawn (109, 212, 338 and 157 px); the other
# 16 started 0.2-1.2 px off. Each respawn is off about 1 time in 4 whatever
# the one before it was (1,645 frames since 14 Oct: 24% after an off one, 28%
# after a good one), so three leave about 1 walk in 60 without the view, and
# that one is not walked (`view_verdict`). A camera tap is 45 degrees, far
# too coarse to fix a few degrees, so the respawn is the only correction.
VIEW_RESPAWNS = 3


def view_verdict(off: float | None, respawns: int, *, max_shift: float,
                 tries: int = VIEW_RESPAWNS) -> str:
    """After respawn number `respawns` (1 = the first): "ok" (the standard
    view, or it could not be measured -- as before), "again" (off: respawn
    once more) or "refuse" (still off after `tries`: no walk out sets off from it)."""
    if off is None or off <= max_shift:
        return "ok"
    return "again" if respawns < tries else "refuse"

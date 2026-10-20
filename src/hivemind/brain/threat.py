"""Noticing a mob and not standing next to it.

The owner's own diagnosis of why the bot keeps dying, and it is the right one:
walking a small radius, the character keeps getting caught by the Mantis, and a
death loses all the pollen and sends it back to the hive.

Two things in that. The SMALL RADIUS is why the mob connects -- the
gathering patterns loop inside a few dozen studs, so a character that has been
noticed stays inside reach the whole time. LOSING ALL POLLEN is why it matters
more than anything else in the loop: a death does not cost a few seconds, it
costs everything gathered since the last convert.

WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT

It does one thing: when a mob's health bar appears on screen during a walk, it
asks the walk to STOP EARLY. That is all. The route then carries on with its
next step, which takes the character somewhere else -- which is precisely the
counter the wiki describes, since a lunge is aimed at where the player was
when it began.

It does not chase, flee in a chosen direction, fight, or reset. It presses no
key at all. Every key that gets pressed as a result was already going to be
pressed by the gathering pattern; the only change is that one hold ends sooner
than its recorded time. That keeps the blast radius of a wrong detection to
"walked slightly less far than planned", which is survivable, whereas a policy
that pressed keys on a false positive would not be.

WHY IT IS THIS TIMID. `vision/nameplate.find` has a measured false-positive
rate of zero across every real frame this project has captured, but its RECALL
on this build is unknown -- there is no frame of a real mob from our own
client, because nothing has ever recorded one. Acting boldly on a detector
whose recall nobody has measured would be guessing.

So this also does the thing that fixes that: a sighting writes out the
incident window, which is seven and a half seconds of frames ending at the
sighting. That is how real positives get collected, and once there are some,
how often this fires and how often it should have can finally be compared.
Since DESIGN 8di only a sighting with a bar in it is saved, at most once a
minute (run_farm MOB_SIGHTING_SAVE_SECONDS). The disc windows already on
disk are why: 363 of them in attempts 300-344, and 1 with a bar in its last
5 s (DISC_NEEDS_BAR_SECONDS).
"""
from __future__ import annotations

import time

from ..vision import hurt, nameplate

# The HUD band is flat UI colour and carries no mobs. Skipping it is free.
# Rows above this are HUD. Was 170, which cropped the Rhino Beetle's own bar
# at y=186 -- the mob standing on the character had its plate in the one strip
# nothing looked at. The nameplate reader now owns its own row limits
# (vision/nameplate.WORLD_TOP = 100) and this only tightens them.
SKIP_TOP = 100

# A MOB NEAR DEATH: its bar almost all red, too little green for `find_all`.
# `nameplate.hurt_bars` (green left end, red right end, a name above) sees it.
# MEASURED 2026-10-22, the last 6 frames of 200 mob-sighting windows: find_all
# kept a bar on 170 of 1,200, hurt_bars 14 more (e.g. 20261015-234204-mob-
# sighting/149_t+10.8s, a Rhino Beetle at "HP: 1"), all 14 mobs' bars by eye;
# 0 on 1,200 random route frames. Look-only (AGENTS rule 4): a bar counted
# cuts a walk short, so off it only says what it would count.
HURT_BARS_LIVE = False

# How long after reacting before another sighting counts. Without it a mob
# that stays on screen would cut short every slice of every walk, which would
# stop the bot gathering at all -- a denial of service by one insect.
COOLDOWN_SECONDS = 8.0

# THE DISC COUNTS ONLY BESIDE A BAR. `hurt.find` takes the largest red region
# around the screen centre. That matches the attack disc, and also the red
# and pink ability domes over the character, big red pollen numbers and the
# strawberry field itself. MEASURED:
# * 2026-09-23 loss audit, attempts 300-336: 1.15 discs a gather minute in
#   spider against 1.10 in dandelion, which has no mobs (world.yaml
#   `mobs: []`). Trips that gathered saw 1.17 a minute, trips whose counter did
#   not rise 0.20. Bars stay flat (0.040 vs 0.043 a minute), so the disc
#   follows gathering, not mobs.
# * 2026-09-24 01:35, the staged `nameplate.find` over the saved window of
#   every mob-sighting in attempts 300-344 (scratchpad drive8di/measure.py,
#   every 2nd frame of the last 5 s): 363 reactions were a disc with no bar,
#   and 1 of them had a hostile bar anywhere in its last 5 s (064343, bar 2.0 s
#   before). Each reaction stood about 0.84 s in its settle wait (audit
#   regression), about 40 s/h.
# * Frames: var/incidents/225356-mob-sighting/149 (strawberry field, "Ladybug:
#   40s", no mob) and 225629-mob-sighting/149 (a red dome over the player).
# So a disc is a threat only while a hostile bar has been seen within this
# many seconds. A bar alone still reacts at once, as before.
DISC_NEEDS_BAR_SECONDS = 5.0

# ON THE WAY OUT, ONLY A BAR NEAR THE CHARACTER. MEASURED 2026-09-24 over
# run-276..345 (scratchpad drive8di/outbound.py): 17 natro_out_* walks had a
# leg cut short by a mob, and in 11 of them no bar was within this radius of
# the screen centre. natro_out_spider was cut by a bar at (184, 227),
# (208, 225) and (216, 223), 809-837 px away (run-299.log:63, run-304.log:63,
# run-309.log:63; the saved frame 073230-mob-sighting/149 shows a "Ladybug
# (Lvl 1)" in the Mushroom Field). The feed's first field after all three was
# mushroom; after the two uncut walks (run-317, run-322) it was spider. Whether
# the cut caused the miss is not measured. A route's reaction only
# pauses the character: `_walk` waits for `settle`, up to 9 s, and then walks
# the same remainder from the same spot (act/routes RESUME_ATTEMPTS).
# Inside a field nothing changes. The two fatal bars in the audit's death
# review were 256 px (Aphid, 154220) and 378 px (King Beetle, 034353) away,
# and gather patterns are not natro_out_* routes anyway.
# ONLY WITH THE BAG EMPTY. The audit's case for this was "on the way out the
# bag has just been converted", and that is not always so. MEASURED:
# run-344 (00:26:49 tonight) went out on natro_out_strawberry with the counter
# illegible and the bar at 89%, under the 90% it converts at. Runs 295-297
# went out at 91-95% by the bar, and runs 276, 277 and 287-289 at 56-85% by
# the counter.
# So a far bar is dropped only while `bag_is_empty()` says so. run_farm asks
# act/respawn.bag_is_empty_enough (the errands' 1% rule) of DeathWatch's
# last reading. When the bag cannot be read, the bar counts as before.
# AND THE ERRANDS' OWN COPIES of those routes (run_farm builds "to_the_blender",
# "to_the_mts", "to_the_guild_counter", "to_the_pro_shop", "commando_via" from
# natro_out_* steps): MEASURED 2026-10-13 20:39 and 23:24, two Blender walks
# with near-empty bags were cut by bars 873 and 620 px off centre, both well
# past the radius, and both ended off the route (the Instant Converter, the
# Strawberry Field) -- the far-bar rule never looked at them by name.
# "survey_walk": a shop survey rides a natro_out_ route under that name
# (run_farm survey_by_walk). MEASURED 2026-10-21 05:28: a far bar at (579, 180)
# cut the Ace survey's Blender walk short and it ended by the Strawberry Field --
# the miss 086b569 fixed for the Blender walk itself on 10-13.
OUTBOUND_PREFIX = ("natro_out_", "to_the_", "commando_via", "survey_walk")
OUTBOUND_BAR_RADIUS_PX = 400.0

# How often an ignored disc or far bar goes to the log, per kind. Same as the
# reaction cooldown, so the log gets no more lines than the reactions used to
# write.
IGNORED_NOTE_SECONDS = COOLDOWN_SECONDS


# A BEE'S CARD LEFT OPEN IS NOT A MOB. MEASURED 2026-10-06 05:05 (run-673): a
# Commander Bee card stood open over the pad, its green Energy bar read as
# "mob health bar 124x25 at (965, 503)", and every walk out was cut short for it.
# The card's box from its red X (vision/hivecell.new_type_card_close, MEASURED
# at (827, 292) with the card's bars down to about (1105, 630)).
CARD_BOX = (-40, -30, 300, 380)


def _off_a_bee_card(bars, frame):
    """The bars that are not on an open bee card."""
    from ..vision import hivecell
    try:
        at = hivecell.new_type_card_close(frame)
    except Exception:
        at = None
    if at is None:
        return bars
    x0, y0, x1, y1 = (at[0] + CARD_BOX[0], at[1] + CARD_BOX[1],
                      at[0] + CARD_BOX[2], at[1] + CARD_BOX[3])
    return [b for b in bars
            if not (x0 <= b.centre[0] <= x1 and y0 <= b.centre[1] <= y1)]


class ThreatWatch:
    """A `RouteRunner.watch` hook: True asks the current hold to stop.

    `frames()` returns the current frame. `on_sighting(plates, note)` is
    called once per cooldown window and is where an incident save, a log line
    or a supervisor look belongs -- none of which are this class's business.
    `route_name()` names the route being walked ("" when none), and
    `bag_is_empty()` says whether the bag is known to hold (next to) nothing.
    On a natro_out_* route with an empty bag only bars near the character
    count; without either hook every bar counts. `on_ignored(note)`
    hears about a disc or a far bar that was not counted, at most once per
    IGNORED_NOTE_SECONDS for each kind.
    """

    def __init__(self, frames, on_sighting=None, cooldown: float = COOLDOWN_SECONDS,
                 clock=time.monotonic, skip_top: int = SKIP_TOP,
                 route_name=None, bag_is_empty=None, on_ignored=None,
                 engaged=None):
        self.frames = frames
        self.on_sighting = on_sighting or (lambda plates, note: None)
        self.cooldown = float(cooldown)
        self.clock = clock
        self.skip_top = int(skip_top)
        self.route_name = route_name or (lambda: "")
        self.bag_is_empty = bag_is_empty or (lambda: False)
        self.on_ignored = on_ignored or (lambda note: None)
        # WHILE A BUG RUN FIGHTS, THE BAR IS THE TARGET (act/bugrun, DESIGN
        # 8do). `engaged()` True makes `__call__` stand down: the fight stands
        # still on purpose so the mob comes to the bees, and its loot walk is
        # Natro's sweep over the drops -- cutting either short at the very
        # bar it came for would undo the run. `look()` is untouched, so
        # anything that asks what is on screen still gets the truth, and the
        # death, dialogue and world checks in run_farm's `watching` are not
        # this class's and still end a hold.
        self.engaged = engaged or (lambda: False)
        self.engaged_skips = 0
        self.sightings = 0
        self.reactions = 0
        self.last_seen_at: float | None = None
        # When `look` last kept a hostile bar. The disc counts only within
        # DISC_NEEDS_BAR_SECONDS of it.
        self.bar_seen_at: float | None = None
        # Looks that dropped something, for `describe`: a disc with no bar
        # nearby in time, and a far bar on the way out.
        self.discs_ignored = 0
        self.far_bars_ignored = 0
        self._last_reaction = -1e9
        self._last_ignored_note = {"disc": -1e9, "far": -1e9, "bloom": -1e9,
                                  "hurt": -1e9}
        self.hurt_bars_would = 0
        self.blooms_seen = 0

    def look(self):
        """Every threat on screen right now. Never raises.

        THREE EYES. `nameplate.find_all` sees a mob's health bar;
        `nameplate.hurt_bars`, asked only when that finds none, sees a nearly
        dead mob's mostly red bar (counted only when HURT_BARS_LIVE);
        `hurt.find` sees a large red region around the character. The red
        region is the attack disc only some of the time; mostly it is the
        bees' own gathering (see DISC_NEEDS_BAR_SECONDS). So it is counted
        only within that many seconds of a hostile bar. On a natro_out_* route with an empty bag, bars more
        than OUTBOUND_BAR_RADIUS_PX from the centre are dropped before either
        rule.
        `settled()` in run_farm calls this too, so its settle waits follow the
        same rules.
        """
        try:
            frame = self.frames()
        except Exception:
            return []
        if frame is None:
            return []
        seen = []
        try:
            plates = list(nameplate.find_all(frame, top=self.skip_top))
        except Exception:
            plates = []
        bars = [p for p in plates if p.hostile]
        if not bars:
            # ponytail: a second colour pass, only on a look with no bar
            try:
                worn = [p for p in nameplate.hurt_bars(frame) if p.y >= self.skip_top
                        and not any(abs(p.x - q.x) < q.w and abs(p.y - q.y) < q.h
                                    for q in plates)]
            except Exception:
                worn = []
            if worn and HURT_BARS_LIVE:
                bars = worn
            elif worn:
                self.hurt_bars_would += 1
                self._note_ignored("hurt", "would: count hurt bar " + "; ".join(
                    p.describe() for p in worn) + " — look-only (HURT_BARS_LIVE off)")
        # BLOOMS, LOOK-ONLY (Q8 step 3): their bar was found and dropped; now a
        # sighting is counted and said, so how often each field grows them can
        # be measured before anything walks after their petals.
        blooms = [p for p in plates if p.kind == "bloom"]
        if blooms:
            self.blooms_seen += 1
            self._note_ignored("bloom", "BLOOM seen: " + "; ".join(
                p.describe() for p in blooms) + " — look-only, not chased (Q8)")
        if bars:
            bars = _off_a_bee_card(bars, frame)
        if bars:
            bars = self._near_enough(bars, frame)
        if bars:
            self.bar_seen_at = self.clock()
            seen.extend(bars)
        try:
            disc = hurt.find(frame)
        except Exception:
            disc = None
        if disc is not None:
            if (self.bar_seen_at is not None
                    and self.clock() - self.bar_seen_at <= DISC_NEEDS_BAR_SECONDS):
                seen.append(disc)
            else:
                self.discs_ignored += 1
                self._note_ignored(
                    "disc", f"not counting {disc.describe()}: no mob health "
                    f"bar in the last {DISC_NEEDS_BAR_SECONDS:.0f} s, and a "
                    f"disc alone is mostly the bees' own gathering (DESIGN "
                    f"8di) — walking on")
        return seen

    def _near_enough(self, bars, frame):
        """`bars` without the far ones, on a walk out with an empty bag.

        The distance is from each bar's centre to the frame's centre, which
        is (960, 540) on this client's 1920x1080 capture. The bag is asked
        only once a bar is on screen on a natro_out_* route.
        """
        try:
            route = str(self.route_name() or "")
        except Exception:
            route = ""
        if not route.startswith(OUTBOUND_PREFIX):
            return bars
        try:
            if self.bag_is_empty() is not True:
                return bars
        except Exception:
            return bars
        try:
            cx, cy = frame.shape[1] / 2.0, frame.shape[0] / 2.0
        except Exception:
            return bars
        kept, far = [], []
        for bar in bars:
            try:
                bx, by = bar.centre
                gap = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5
            except Exception:
                kept.append(bar)       # cannot measure it: keep it
                continue
            if gap > OUTBOUND_BAR_RADIUS_PX:
                far.append((bar, gap))
            else:
                kept.append(bar)
        if far:
            self.far_bars_ignored += 1
            self._note_ignored(
                "far", "not counting "
                + "; ".join(f"{b.describe()}, {gap:.0f} px from the centre"
                            for b, gap in far)
                + f": over {OUTBOUND_BAR_RADIUS_PX:.0f} px on {route}, the "
                  f"walk out, with the bag read empty (DESIGN 8di) — walking "
                  f"on")
        return kept

    def _note_ignored(self, kind: str, note: str) -> None:
        now = self.clock()
        if now - self._last_ignored_note[kind] < IGNORED_NOTE_SECONDS:
            return
        self._last_ignored_note[kind] = now
        try:
            self.on_ignored(note)
        except Exception:
            pass          # reporting must never break the watch

    def __call__(self) -> bool:
        try:
            engaged = self.engaged() is True
        except Exception:
            engaged = False          # a broken hook must not blind the watch
        if engaged:
            self.engaged_skips += 1
            return False
        plates = self.look()
        if not plates:
            return False
        self.sightings += 1
        self.last_seen_at = self.clock()
        if self.clock() - self._last_reaction < self.cooldown:
            return False
        self._last_reaction = self.clock()
        self.reactions += 1
        note = ("a threat is on screen: "
                + "; ".join(p.describe() for p in plates)
                + " — cutting this walk short rather than finishing the loop "
                  "beside it")
        try:
            self.on_sighting(plates, note)
        except Exception:
            pass          # reporting must never break the reaction
        return True

    def describe(self) -> str:
        return (f"{self.sightings} frames with a mob bar, "
                f"{self.reactions} walks cut short, "
                f"{self.discs_ignored} looks at a disc with no bar near it in "
                f"time, {self.far_bars_ignored} looks at a far bar on a walk "
                f"out (not counted, DESIGN 8di), {self.engaged_skips} watch "
                f"ticks stood down during a bug run (DESIGN 8do)")

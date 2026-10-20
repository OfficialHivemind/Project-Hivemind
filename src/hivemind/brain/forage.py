"""Farming without a map, without a heading, and without a calibration.

WHY THIS EXISTS, AND WHAT IT REPLACES

The first farm loop drove BeeTuxMacro's recorded routes. Those are blind timed
holds, and MEASURED over a night of live runs they need two things the bot
cannot establish:

  * the right POSITION. A reset puts the character at the hive, which is close.
  * the right CAMERA HEADING. Every movement key in Roblox is relative to the
    camera, and the camera's rotation survives a reset. The very same route
    fired the cannon perfectly on one run and walked into the sand beside hive
    slot 5 on the next -- same code, same reset, only the heading differed.

Eight headings were then tried explicitly, running the first leg from each and
asking the vision model whether the character had reached the cannon. NONE of
them did. The recorded routes assume a starting state that cannot be recovered
from inside the game, and no amount of care with the replay fixes that.

THE IDEA HERE IS SMALLER AND HARDER TO BREAK

The bot does not need to know where it is. It needs to be somewhere pollen
rises. Both of those are directly observable on the HUD:

    pollen rising   -> standing in a field, whatever it is called
    honey rising    -> converting at the hive, wherever that is

So the loop navigates by consequence rather than by coordinates:

    1. RESET                 a guaranteed teleport to the hive. No route, no
                             heading, no drift. This is the anchor the whole
                             design rests on, and it is the one movement in
                             the game that cannot go wrong.
    2. SEARCH                walk out, gather briefly, watch the counter.
                             Pollen rising means this spot works; flat means
                             turn and try elsewhere.
    3. GATHER                stay while it keeps paying, up to the backpack.
    4. RESET                 back at the hive, again exactly.
    5. CONVERT               stand still and watch honey rise.

Every transition is gated on a MEASURED change, so the loop cannot convince
itself it arrived somewhere it did not. A search that never finds pollen is
reported as a search that never found pollen -- not as a cycle.

WHAT IT COSTS

A reset kills the character, so bees take a moment to recover, and walking out
blind is less efficient than a direct route would be. That is the trade: a
slower cycle that actually completes, against a faster one that arrives in the
wrong place. Once the ground plane is calibrated and routes can be verified on
arrival, the fast path can come back -- and this stays as the fallback, because
a bot that can always get home is a bot that can always recover.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

# --- what counts as evidence ----------------------------------------------
# MEASURED at the hive: a blocked direction gives ~1-2 px of flow per frame
# against 8-23 px in the open, so "did we move" is a wide-margin test. Pollen
# is the stricter signal and the one that matters: a field pays thousands per
# minute, and anything under this is noise from a stray token or a bee.
POLLEN_WORTH_STAYING = 200          # per probe, see SEARCH_PROBE_SECONDS
SEARCH_PROBE_SECONDS = 20.0         # long enough for a real field to show

# HOW FAR TO STRIKE OUT, and why the first attempt found nothing.
#
# MEASURED: ten probes at 2.5 s of walking apiece -- about 70 studs at
# WALKSPEED 28 -- returned exactly 0 pollen every time. That is not bad luck:
# 70 studs only circles the hive platform, which is decking and sand. The
# transpiled routes put the nearest fields 300-600 studs out, so the search has
# to cover that kind of distance before a probe means anything.
#
# So it spirals: walk, probe, turn, then walk FURTHER next time. A fixed radius
# can only ever search one ring.
SEARCH_WALK_SECONDS = 8.0           # ~225 studs at WALKSPEED 28
SEARCH_WALK_GROWTH = 1.25           # each lap reaches further out
SEARCH_WALK_MAX = 22.0              # ~600 studs, past the furthest known field
SEARCH_TURN_TAPS = 2                # 90 degrees, at the measured 45 per tap
MAX_SEARCH_PROBES = 12              # a turn and a half of spiral

# Walking into the hive wall produces ~1-2 px of flow per frame against 8-23 in
# the open (measured three times, three sessions). Below this the character did
# not go anywhere, so the probe would be measuring the same barren spot again
# -- turn immediately instead of spending twenty seconds proving it.
BLOCKED_FLOW_PX = 2.5

# THE CAMERA CLIPS INTO SCENERY, and when it does the world renders BLACK.
#
# MEASURED: after the cannon landing, the world area of the frame went from
# luma 135 to 0.0 while the HUD stayed perfectly readable. Zooming out with
# `o` recovered it (luma 104.8). A black world has no trackable features, so
# optical flow reads 0.0 px in every direction -- which is indistinguishable
# from being walled in unless something looks at the brightness. The search
# spent twelve probes concluding the world had no fields in it while the
# character was simply looking at the inside of a rock.
BLIND_LUMA = 12.0                   # world area below this is not rendering

# ...AND A BRIGHT SCREEN CAN BE JUST AS UNREADABLE.
#
# MEASURED: wedged inside the white fence beside the hive, with a flower field
# visible past it, optical flow read 0.0 px in all four directions -- not
# because the character could not move, but because the visible scene was a
# flat white wall and a flat green floor with no corners to track at all. The
# search concluded "every direction blocked" twelve times while the pollen
# counter was quietly climbing to 1,084.
#
# ABSENCE OF FEATURES IS NOT ABSENCE OF MOTION. Below this many tracked points
# the measurement means nothing and must be reported as unknown, never as zero.
MIN_TRACKED_TO_TRUST = 12

# JUMP WHILE WALKING. Bee Swarm is full of low fences and ledges, and the
# recorded routes contain 54 jumps for exactly this reason -- a character that
# only walks gets caught on scenery that a single hop clears. MEASURED: the
# search spent twelve probes wedged inside the white fence beside the hive,
# with a flower field visible on the other side of it.
JUMP_EVERY_SECONDS = 2.0

# After this many probes that neither moved nor paid, the character is stuck
# somewhere a nudge will not fix. Reset: it is a teleport home and costs ten
# seconds, against a search that would otherwise grind for minutes.
STUCK_PROBES_BEFORE_RESET = 3

# AN OUTBOUND ROUTE, used for the part of the journey that demonstrably works.
#
# MEASURED: `from_hive_to_red_cannon` reliably puts the character on top of the
# red cannon, ~320 studs from the hive, with flower fields visible beside it.
# The full `..._to_pine_tree_with_red_cannon` continues by firing the cannon,
# and THAT is the unreliable part -- the ride worked once and never again.
#
# So the loop takes the half that works and forages from where it lands. The
# hive itself is enclosed by fences, which is why searching from the spawn
# point found nothing in twelve probes across four separate runs; 320 studs out
# is past the enclosure and beside actual flowers.
# MEASURED LIVE, 2026-09-20, and the owner spotted it before the numbers did:
# "yk its just going to ticket shop and runnign around in circles right".
#
# `from_hive_to_red_cannon` is only the FIRST LEG. It walks 324 studs to the
# cannon and stops there -- the end-of-run frame shows the character standing
# at a shop counter with "[E] Open Shop" on screen, which is the ticket shop
# beside the cannon, not a field. Gathering there collected 0 pollen in 120 s
# WITH a hive claimed and bees out, which is exactly right: there are no
# flowers at a shop.
#
# `from_hive_to_pine_tree_with_red_cannon` is the whole journey. It CALLS the
# route above and then does the part that matters: aim the camera, `interact`
# to board the cannon, jump twice, wait out the 8 s flight, and walk 22.5
# studs into the field. Pine is also the field the owner's own config names
# (FIELD="pine").
OUTBOUND_ROUTE = "from_hive_to_pine_tree_with_red_cannon"
BLIND_BAND = (200, 900)             # rows to sample, skipping the HUD strips
UNBLIND_ZOOMS = 3                   # `o` presses; 3 recovered it when measured
# How long to hold each key when asking which way is open.
#
# MEASURED: at 0.4 s the answer was 0.0 px for all four keys IMMEDIATELY after
# a walk that had just measured 18 px/frame in one of them. A Roblox character
# accelerates, so four-tenths of a second is mostly the acceleration and the
# tracker sees almost no displacement. Every working measurement in this
# project used 0.7 s or more, so the probe does too.
PROBE_DIRECTION_SECONDS = 1.0

# Walking straight back the way we came wastes a probe.
_OPPOSITE = {"w": "s", "s": "w", "a": "d", "d": "a"}

GATHER_SECONDS = 420.0              # BeeTuxMacro's FARM_SECONDS default
GATHER_STALL_SECONDS = 60.0         # flat this long means the spot is spent
FULL_AT = 0.90                      # pollen above the cap is discarded

CONVERT_SECONDS = 100.0             # BeeTuxMacro's CONVERT_TIME
CONVERT_STALL_SECONDS = 35.0        # honey flat this long means not converting

POLL_SECONDS = 3.0


class Phase(str, Enum):
    RESETTING = "resetting"
    SEARCHING = "searching"
    GATHERING = "gathering"
    RETURNING = "returning"
    CONVERTING = "converting"


@dataclass
class Cycle:
    """One trip out and back, in measured numbers only."""
    number: int
    pollen_gathered: int = 0
    honey_made: int = 0
    search_probes: int = 0
    found_field: bool = False
    seconds: float = 0.0
    note: str = ""

    def describe(self) -> str:
        if not self.found_field:
            return (f"cycle {self.number}: no field found in "
                    f"{self.search_probes} probes ({self.seconds:.0f}s)"
                    + (f" — {self.note}" if self.note else ""))
        return (f"cycle {self.number}: +{self.pollen_gathered:,} pollen, "
                f"+{self.honey_made:,} honey, found after "
                f"{self.search_probes} probe(s), {self.seconds:.0f}s"
                + (f" — {self.note}" if self.note else ""))


@dataclass
class Session:
    """The whole run. Every figure here came off the HUD."""
    cycles: list[Cycle] = field(default_factory=list)
    started_at: float = 0.0
    seconds: float = 0.0
    stopped_because: str = ""
    unreadable_reads: int = 0

    @property
    def honey_made(self) -> int:
        return sum(c.honey_made for c in self.cycles)

    @property
    def complete_cycles(self) -> int:
        """Cycles that found a field AND made honey. The only ones that count."""
        return sum(1 for c in self.cycles
                   if c.found_field and c.honey_made > 0)

    def describe(self) -> str:
        minutes = self.seconds / 60.0
        rate = self.honey_made / (self.seconds / 3600.0) if self.seconds else 0
        return (f"{len(self.cycles)} cycles ({self.complete_cycles} complete) "
                f"in {minutes:.1f} min — +{self.honey_made:,} honey "
                f"({rate:,.0f}/hr) — {self.unreadable_reads} unreadable reads"
                + (f" — stopped: {self.stopped_because}"
                   if self.stopped_because else ""))


def _median(values) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return 0.0
    middle = n // 2
    return (ordered[middle] if n % 2
            else (ordered[middle - 1] + ordered[middle]) / 2.0)


def _median_norm(delta) -> float:
    """Median length of a set of (dx, dy) vectors."""
    return _median([(float(dx) ** 2 + float(dy) ** 2) ** 0.5
                    for dx, dy in delta])


class _Stop(Exception):
    """Raised at a safe boundary when a stop is requested."""


class Forager:
    """The map-free farm loop.

    Dependencies are injected so the whole thing runs in a test with no game:

        routes   a RouteRunner, used ONLY for the reset and the gather pattern
        hud      anything with .pollen() / .honey() -> Reading
        vin      the input client
    """

    def __init__(self, routes, hud, *, vin=None, stop=None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 emit: Callable[[Any], None] | None = None,
                 pattern: str = "farm_better_snake",
                 gather_seconds: float = GATHER_SECONDS,
                 probe_seconds: float = SEARCH_PROBE_SECONDS,
                 walk_seconds: float = SEARCH_WALK_SECONDS,
                 max_probes: int = MAX_SEARCH_PROBES,
                 worth_staying: int = POLLEN_WORTH_STAYING,
                 full_at: float = FULL_AT,
                 convert_seconds: float = CONVERT_SECONDS,
                 poll_seconds: float = POLL_SECONDS,
                 outbound_route: str | None = OUTBOUND_ROUTE,
                 at_home=None,
                 frames: Callable[[], Any] | None = None,
                 tracker_factory: Callable[[], Any] | None = None,
                 debug_shot: Callable[[str], None] | None = None):
        self.routes = routes
        self.hud = hud
        # `at_home()` says whether the character is standing at its own hive
        # right now. When it can answer, `go_home` costs nothing instead of
        # costing a death.
        self.at_home = at_home
        self.vin = vin if vin is not None else getattr(routes, "vin", None)
        if self.vin is None:
            raise ValueError("the forager needs an input client")
        self.stop = stop
        self.clock = clock
        self.sleep = sleep
        self.emit = emit or (lambda _event: None)
        self.pattern = pattern
        self.gather_seconds = gather_seconds
        self.probe_seconds = probe_seconds
        self.walk_seconds = walk_seconds
        self.max_probes = max_probes
        self.worth_staying = worth_staying
        self.full_at = full_at
        self.convert_seconds = convert_seconds
        self.poll_seconds = poll_seconds
        self.outbound_route = outbound_route
        # Optional, but strongly wanted: with these the search can tell a walk
        # from a walk into a wall, and skip a twenty-second probe it already
        # knows the answer to.
        self.frames = frames
        self.tracker_factory = tracker_factory
        self.phase = Phase.RESETTING
        self.unreadable = 0
        self._last_key: str | None = None
        # Optional: called with a tag whenever something surprising happens,
        # so a live run can be inspected afterwards instead of guessed about.
        self.debug_shot = debug_shot or (lambda _tag: None)

    # ---- plumbing ---------------------------------------------------------
    def _say(self, text: str) -> None:
        self.emit(_Note(text))

    def _check_stop(self) -> None:
        if self.stop is not None and self.stop.is_set():
            raise _Stop()

    def _rest(self, seconds: float) -> None:
        """Sleep in slices so a stop is noticed promptly."""
        end = self.clock() + seconds
        while self.clock() < end:
            self._check_stop()
            self.sleep(min(self.poll_seconds, max(0.0, end - self.clock())))

    def _pollen(self) -> tuple[int, int] | None:
        """(carried, capacity), or None when the HUD could not be read.

        Reading.value is the carried amount and Reading.capacity is separate;
        both are None unless the read succeeded. There is deliberately no
        fallback -- an unreadable counter must not become a zero, because a
        zero reads as "the backpack is empty" and would send the bot home.
        """
        reading = self.hud.pollen()
        if not getattr(reading, "ok", False) or reading.value is None:
            self.unreadable += 1
            return None
        return int(reading.value), int(reading.capacity or 0)

    def _honey(self) -> int | None:
        reading = self.hud.honey()
        if not getattr(reading, "ok", False) or reading.value is None:
            self.unreadable += 1
            return None
        return int(reading.value)

    # ---- the anchor -------------------------------------------------------
    def go_home(self, allow_loss: bool = False) -> bool:
        """Reset to the hive -- WHICH COSTS THE ENTIRE BACKPACK.

        It is exact: a teleport, no heading, no route, no accumulated drift,
        and that is why this loop leaned on it. The price was not understood
        when it was written.

        MEASURED, and the owner named it while watching: "when i die i loose
        all pollen and go back to hive". A reset is a death. Everything
        gathered since the last convert is destroyed, and the bees go home to
        rest for about 30 seconds on top of that. A run that reset on its
        first move duly threw away 115,831 pollen before it had walked
        anywhere.

        So this now REFUSES when the backpack has anything in it, and says
        why. An empty backpack has nothing to lose, which is the only case
        where the exactness is free. `allow_loss=True` is for a caller that
        has genuinely decided the position is worth more than the haul --
        nothing does today.
        """
        # ALREADY THERE? Then there is nothing to do, and a reset here is
        # pure cost: it is a death, it empties the backpack, it sends the
        # bees home for thirty seconds, and it can fail.
        #
        # MEASURED: a run claimed a hive -- which leaves the character
        # standing ON the hive -- and then immediately tried to reset back to
        # it. The reset was refused because the respawn dialog never appeared,
        # and the cycle ended two seconds in having done nothing at all.
        if self.at_home is not None:
            try:
                if self.at_home():
                    self._say("already at the hive; no reset needed")
                    return True
            except Exception:
                pass          # cannot tell -> fall through and decide below

        if not allow_loss:
            reading = self.hud.pollen()
            carrying = getattr(reading, "value", None)
            # AN UNREADABLE COUNTER IS NOT AN EMPTY BAG: a seven-digit bag
            # reads None (vision/digits), and `if carrying:` let it through.
            if carrying is None:
                self._say("NOT resetting: the pollen counter cannot be read, "
                          "and a reset is a death that would destroy whatever "
                          "is in the backpack.")
                return False
            if carrying:
                self._say(
                    f"NOT resetting: the backpack holds {carrying:,} pollen "
                    f"and a reset is a death, which would destroy all of it.")
                return False
        self.phase = Phase.RESETTING
        self._say("resetting to the hive")
        from ..act.routes import RouteResult
        result = RouteResult("reset")
        self.routes._run_step({"op": "reset"}, result, 0)
        if not result.ok or result.skipped:
            self._say(f"reset refused: {result.reason or result.skipped}")
            return False
        return True

    # ---- finding somewhere that pays --------------------------------------
    def find_a_field(self, cycle: Cycle) -> bool:
        """Walk and probe until the pollen counter actually rises.

        No map is consulted and no arrival is claimed. The only evidence that
        this is a field is that the number went up while standing in it.
        """
        self.phase = Phase.SEARCHING

        # Get clear of the hive enclosure first, by the one route that has
        # been shown to work. Searching from the spawn point found nothing in
        # twelve probes on four separate runs, because the hive is fenced.
        if self.outbound_route:
            result = self.routes.run(self.outbound_route)
            ok = getattr(result, "ok", True)
            self._say(f"took {self.outbound_route} out of the hive"
                      + ("" if ok else f" — but it reported: {result.reason}"))
            self._last_key = None

        distance = self.walk_seconds
        stuck = 0
        for probe in range(1, self.max_probes + 1):
            self._check_stop()
            cycle.search_probes = probe

            if self.blind() and not self.unblind():
                self._say("still cannot see; resetting to the hive")
                self.go_home()
                self.phase = Phase.SEARCHING
                stuck = 0

            moved = self._walk_out(distance)
            if moved is not None and moved < BLOCKED_FLOW_PX:
                stuck += 1
                if stuck >= STUCK_PROBES_BEFORE_RESET:
                    self._say(f"stuck for {stuck} probes — resetting to the "
                              "hive and striking out again")
                    self.go_home()
                    self.phase = Phase.SEARCHING
                    self._last_key = None
                    stuck = 0
                    distance = self.walk_seconds
                    continue
                # Blocked. Probing here would spend twenty seconds proving the
                # character never left the last spot.
                self._say(f"probe {probe}: every direction blocked "
                          f"({moved:.1f} px) — turning the camera")
                self.debug_shot(f"blocked_probe{probe}")
                self.vin.camera_right(SEARCH_TURN_TAPS)
                self.sleep(0.4)
                self._last_key = None
                distance = min(distance * SEARCH_WALK_GROWTH, SEARCH_WALK_MAX)
                continue

            stuck = 0
            before = self._pollen()
            self._say(f"probe {probe}: walked {distance:.0f}s out, gathering "
                      f"{self.probe_seconds:.0f}s to see if anything grows here")
            self._gather_for(self.probe_seconds)
            after = self._pollen()

            if before is None or after is None:
                self._say("could not read the backpack during the probe")
                continue
            gained = after[0] - before[0]
            self.debug_shot(f"probe{probe}_gained{gained}")
            if gained >= self.worth_staying:
                self._say(f"probe {probe} paid {gained:,} pollen — staying")
                cycle.pollen_gathered += gained
                return True
            self._say(f"probe {probe} paid {gained:,} — going further out")
            distance = min(distance * SEARCH_WALK_GROWTH, SEARCH_WALK_MAX)
        return False

    def _flow_while(self, key: str, seconds: float,
                    jump: bool = False) -> float | None:
        """Hold a key and report how much the scene moved, in px per frame.

        None when there is nothing to measure with, which the caller treats as
        "assume it worked" -- refusing to move on a missing measurement would
        strand the bot at the hive forever.
        """
        if self.tracker_factory is None or self.frames is None:
            with self.vin.held(key):
                self._rest(seconds)
            return None

        tracker = self.tracker_factory()
        tracker.update(self.frames())
        seen: list[float] = []
        best_tracked = 0
        next_jump = self.clock() + JUMP_EVERY_SECONDS
        try:
            self.vin.press(key)
            end = self.clock() + seconds
            while True:
                self._check_stop()
                if jump and self.clock() >= next_jump:
                    self.vin.tap("space")      # clear fences and ledges
                    next_jump = self.clock() + JUMP_EVERY_SECONDS
                sample = tracker.update(self.frames())
                pairs = getattr(sample, "pairs", None) if sample else None
                if pairs is not None and len(pairs):
                    best_tracked = max(best_tracked, len(pairs))
                    seen.append(_median_norm(pairs[:, 1, :] - pairs[:, 0, :]))
                if self.clock() >= end:
                    break
                self.sleep(0.05)
        finally:
            self.vin.release(key)
        if not seen or best_tracked < MIN_TRACKED_TO_TRUST:
            # Too little texture on screen to say anything. UNKNOWN, not zero:
            # see MIN_TRACKED_TO_TRUST.
            return None
        return _median(seen)

    def _pick_direction(self, avoid: str | None = None
                        ) -> tuple[str, float | None]:
        """Which key actually moves the character right now?

        MEASURED, and the reason this exists: standing at the hive, `d` gave
        10.69 px per frame while `w`, `a` and `s` gave 0.35, 0.09 and 0.09.
        The character was wedged in a corner where only ONE direction was
        open. A search that only ever presses `w` reports "blocked" twelve
        times in a row and concludes the world has no fields in it.

        Turning the camera does not fix that on its own -- it changes what `w`
        means, but the character can still be against geometry. Asking all four
        keys costs about a second and a half and cannot be wrong, because the
        answer is the observation.
        """
        # Try what worked last time first. A direction that was open a moment
        # ago usually still is, and skipping the sweep saves four seconds on
        # every probe -- which over a night is most of an hour.
        if self._last_key and self._last_key != avoid:
            flow = self._flow_while(self._last_key, PROBE_DIRECTION_SECONDS)
            if flow is None:
                return self._last_key, None
            if flow >= BLOCKED_FLOW_PX:
                return self._last_key, flow

        best, best_flow = "", -1.0
        for key in ("w", "d", "a", "s"):
            if key == avoid:
                continue
            flow = self._flow_while(key, PROBE_DIRECTION_SECONDS)
            if flow is None:
                # Nothing to measure with. UNKNOWN, not blocked -- returning a
                # zero here would read as "every direction is a wall" and the
                # search would never take a step.
                return key, None
            if flow > best_flow:
                best, best_flow = key, flow
        return best or "w", max(best_flow, 0.0)

    def _world_luma(self) -> float | None:
        """Mean brightness of the world area, ignoring the HUD strips."""
        if self.frames is None:
            return None
        frame = self.frames()
        if frame is None:
            return None
        top, bottom = BLIND_BAND
        band = frame[top:bottom, :, :3]
        try:
            return float(band.mean())
        except (AttributeError, TypeError):
            return None

    def blind(self) -> bool:
        """Is the camera inside something? See BLIND_LUMA."""
        luma = self._world_luma()
        return luma is not None and luma < BLIND_LUMA

    def unblind(self) -> bool:
        """Back the camera out of whatever it is inside. True if it worked.

        Zooming out is what recovered it when measured; a jump is the cheap
        second try, because the usual cause is standing half-inside geometry.
        """
        self._say("the world is not rendering — the camera is inside "
                  "something; zooming out")
        for _ in range(UNBLIND_ZOOMS):
            self.vin.tap("o")
            self.sleep(0.15)
        self.sleep(0.6)
        if not self.blind():
            return True
        self.vin.tap("space")
        self.sleep(1.0)
        return not self.blind()

    def _walk_out(self, seconds: float) -> float | None:
        """Strike out in whichever direction is actually open."""
        key, flow = self._pick_direction(avoid=_OPPOSITE.get(self._last_key))
        if flow is not None and flow < BLOCKED_FLOW_PX:
            return flow                  # everything is blocked; caller turns
        self._last_key = key
        where = f"{flow:.1f} px/frame" if flow is not None else "unmeasured"
        self._say(f"walking {seconds:.0f}s along '{key}' ({where})")
        return self._flow_while(key, seconds, jump=True)

    def _gather_for(self, seconds: float) -> None:
        end = self.clock() + seconds
        while self.clock() < end:
            self._check_stop()
            self.routes.run(self.pattern)

    # ---- staying while it pays --------------------------------------------
    def gather(self, cycle: Cycle) -> None:
        self.phase = Phase.GATHERING
        start = self.clock()
        opened = self._pollen()
        best = opened[0] if opened else 0
        last_rise = self.clock()

        while self.clock() - start < self.gather_seconds:
            self._check_stop()
            self.routes.run(self.pattern)
            now = self._pollen()
            if now is None:
                continue
            current, capacity = now
            if current > best:
                best, last_rise = current, self.clock()
            if capacity and current >= capacity * self.full_at:
                cycle.note = f"backpack full at {current:,}/{capacity:,}"
                self._say(cycle.note)
                break
            if self.clock() - last_rise > GATHER_STALL_SECONDS:
                cycle.note = "the spot stopped paying"
                self._say(cycle.note)
                break

        closed = self._pollen()
        if opened and closed:
            cycle.pollen_gathered += max(0, closed[0] - opened[0])

    # ---- turning it into honey --------------------------------------------
    def convert(self, cycle: Cycle) -> None:
        """Stand at the hive and watch honey rise. Proof, not a timer."""
        self.phase = Phase.CONVERTING
        # E ONLY WHERE SOMETHING SAYS THIS IS THE HIVE: it is also the key
        # that opens shops and dialogues (brain/farm `confirm_hive`).
        try:
            home = bool(self.at_home()) if self.at_home is not None else False
        except Exception:
            home = False
        if not home:
            cycle.note = "not converting: nothing confirms this is the hive"
            self._say(cycle.note)
            return
        before = self._honey()
        self._say("converting at the hive")
        self.vin.tap("e")

        start = self.clock()
        last_rise = self.clock()
        best = before or 0
        while self.clock() - start < self.convert_seconds:
            self._check_stop()
            self._rest(self.poll_seconds)
            now = self._honey()
            if now is None:
                continue
            if now > best:
                best, last_rise = now, self.clock()
            pollen = self._pollen()
            if pollen and pollen[0] == 0 and before is not None and best > before:
                break                    # emptied the backpack: done
            if self.clock() - last_rise > CONVERT_STALL_SECONDS:
                break
        after = self._honey()
        if before is not None and after is not None:
            cycle.honey_made = max(0, after - before)
            self._say(f"made {cycle.honey_made:,} honey")

    # ---- the loop ---------------------------------------------------------
    def run(self, cycles: int | None = None) -> Session:
        session = Session(started_at=self.clock())
        try:
            number = 0
            while cycles is None or number < cycles:
                number += 1
                cycle = Cycle(number=number)
                began = self.clock()
                try:
                    if not self.go_home():
                        # the `finally` below records the cycle; appending
                        # here too logged every failed reset twice
                        cycle.note = "could not reset"
                        # Said HERE: the `break` skips everything below.
                        session.stopped_because = (
                            "could not reset to the hive, so the position is "
                            "unknown and walking on would be guessing")
                        break
                    if self.find_a_field(cycle):
                        cycle.found_field = True
                        self.gather(cycle)
                        self.phase = Phase.RETURNING
                        # A REFUSED RESET IS NOT A WAY HOME, and nothing
                        # walks instead: stop here with the bag kept.
                        if not self.go_home():
                            cycle.note = "could not get home to convert"
                            session.stopped_because = (
                                "could not get home to convert, and a reset "
                                "would have destroyed the bag")
                            break
                        self.convert(cycle)
                    else:
                        cycle.note = "no field found"
                finally:
                    cycle.seconds = self.clock() - began
                    session.cycles.append(cycle)
                    self._say(cycle.describe())
            if not session.stopped_because:
                session.stopped_because = (
                    f"finished the {cycles} cycles asked for" if cycles else "")
        except _Stop:
            session.stopped_because = "stop requested"
        finally:
            self.vin.release_all()
            session.seconds = self.clock() - session.started_at
            session.unreadable_reads = self.unreadable
        return session


@dataclass
class _Note:
    """A plain narration line, shaped like the telemetry Thought event."""
    text: str

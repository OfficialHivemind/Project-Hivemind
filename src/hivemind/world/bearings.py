"""Where the bot is, which way it is facing, and how sure it is of either.

THE OWNER'S DIAGNOSIS, 2026-09-21, watching a live run: can it stop and find
its way to the field? All it did was turn once and jump once when it got
nothing, which cannot help if it is in the wrong area to begin with.

They were describing a bot with no sense of place at all. The log agreed. It ran
a route to the Pine Tree, pressed E to board a cannon it was not standing at,
waited eight seconds for a flight that did not happen, and then "farmed" the
hive pads for five and a half minutes -- 27 pattern passes, 0 pollen -- while
the top-centre panel read "Make Honey" the entire time and the vision model
said "the player is inside a hive". Nothing was listening to either.

THIS IS THE THING THAT LISTENS. One object, fed every observation the rest of
the bot already makes, answering three questions:

    where()          the best current belief about place, with its source
    heading_taps     how far the camera has been turned from spawn heading
    shift_lock       whether shift lock is on, which inverts what A and D do

HIDDEN STATE, AND WHY IT HAD TO BE TRACKED. Every recorded route is CAMERA-
RELATIVE: `w` means "the way the camera points". The camera is turned by taps
of comma and period, 45 degrees each (MEASURED by closure, act/orient.py: the
view repeats after 8 taps). Three things tap it and none of them told anyone:

    the hive sweep        0 to 7 taps, whichever way the most red was
    the box search        2 taps per leg, 6 legs -- ends 180 degrees off
    the TURN recovery     1 tap, every time the pollen counter stalls

So after one stalled gather the next route ran 45 degrees wrong, and after one
failed box search the route home ran backwards. Shift lock is the same shape
of problem: routes toggle it in matched pairs, an aborted route leaves it odd,
and with it on the strafe keys strafe while with it off they turn. This module
counts both, and `nav/journey` squares both up before any recorded route runs.

WHAT EACH SIGNAL IS ALLOWED TO CLAIM. This is the part worth being strict
about, because a place belief that overclaims is how the bot farmed the hive.

  panel      The game's own prompt. "Make Honey" means ON our pad, right now,
             certainly. MEASURED to vanish the moment the character steps off,
             so an ABSENT panel is itself evidence: not at any landmark. A
             panel fix therefore has a short half-life -- it is only true
             while the panel is still there.
  feed       "+590 Honey (from Pumpkin Patch)": the game naming the field.
             Certain when it fires; fires on pickup only, so it goes stale.
  pollen     The counter rising means we are in SOME field that pays. It does
             not say which. Weak alone, strong as corroboration.
  heard      A sentence from the vision model. MEASURED 44% on which field
             (DESIGN 8b), so it is the weakest source here and only ever
             breaks a tie. It is kept because "inside a hive" was exactly
             right at 18:38:48 and nothing acted on it.
  sight      Which field the frame LOOKS like (vision/fieldsense, DESIGN 8dz),
             asked before the vision model at the end of a walk out, and
             believed at the held-out precision of looks like it -- 76 of 81
             walk-end looks right on nights the classifier had not seen. A
             fallback only: it is never preferred to the panel or the feed,
             and it says "what looks like" the field.
  spawn      A rejoin lands in the hive area with spawn heading, shift lock
             off. MEASURED: both joins on 2026-09-20 claimed a pad within two
             hops of arriving. Position and heading are both known at spawn,
             which is why a rejoin is the reset of last resort.

Built on `world/beliefs.BeliefStore`, which has carried the design's promise
of decaying, source-tagged beliefs since the first week and until today had
nothing feeding it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from ..vision import landmarks as lm
from ..vision.flow import BLOCKED_FLOW_PX

# A MOTION REPORT SAYS NOTHING ABOUT "NOW" FOR LONG. The route runner reports
# the flow at its watch rate while a key is held (act/routes, several times a
# second) and says nothing when the hold ends, so a leg that finished against
# something -- waiting at the red cannon -- left the character "pushing against
# something" for as long as nothing walked a route again: 894 s through a bug
# run and a whole gather in run-531 (2026-09-28 21:08-21:25), gathering all the
# while, and the stream's voice made a joke of the wall. Older than this, a
# report is no claim about now.
MOTION_FRESH_S = 2.0
from . import beliefs

# The camera turns 45 degrees per tap: 8 taps is one full turn, MEASURED by
# closure in act/orient.py. Right (period) is +1, left (comma) is -1.
TAPS_PER_FULL_TURN = 8

# How long each kind of fix is worth believing, in seconds. These are added to
# the belief store's table so `observe` picks them up by name.
HALF_LIVES = {
    "place:panel": 6.0,      # true only while the panel is still showing
    "place:feed": 45.0,      # a pickup every ~9 s while farming; stale after a walk
    "place:spawn": 90.0,     # spawn is the hive area until we walk away from it
    "place:heard": 20.0,     # the vision model, weakest of all
    # A look is one frame, true where it was taken: `moved()` ends it, and
    # otherwise it fades like a sentence from the vision model it replaces.
    "place:sight": 20.0,
    "not_at_landmark": 6.0,  # the panel was looked for and was not there
    "in_field": 30.0,        # the pollen counter rose
}
beliefs.HALF_LIVES.update(HALF_LIVES)

# How long a reported threat stays in the picture without being seen again.
THREAT_SECONDS = 6.0

# Below this a belief is not worth acting on. Half of the initial confidence
# of the strongest sources -- one half-life old.
FLOOR = 0.45
# A belief in somewhere else this sure is taken as "not there" (`at`), which
# is what the journey and the farm loop act on. It is also the least a look
# by sight must be right, on unseen nights, before it may name a field here
# (scripts/train_fieldsense.py `sight`, DESIGN 8dz).
SURE_ELSEWHERE = 0.8

# Words the vision model uses that this module is willing to read a place
# from. Deliberately few, and each maps to a coarse claim only.
HEARD_HIVE = ("inside a hive", "hive pad", "on a hive", "at the hive",
              "the hive area", "make honey", "claim hive", "hexagonal")
HEARD_FIELD = ("flowers around", "in a field", "on a field", "flower field",
               "surrounded by flowers", "gathering pollen")


@dataclass(frozen=True)
class Place:
    """One belief about where the character is."""
    name: str                 # "hive", "pumpkin", "red_cannon", or "a field"
    kind: str                 # hive | field | transport | shop | dispenser | npc
    source: str               # panel | feed | pollen | heard | spawn
    confidence: float
    age: float
    mine: bool | None = None  # hive only: our pad, a free pad, or unknown

    def describe(self) -> str:
        if self.name == "hive":
            where = ("on our own hive pad" if self.mine else
                     "on a free hive pad" if self.mine is False else
                     "in the hive area")
        elif self.kind == "field" and self.source == "sight":
            where = f"in what looks like the {self.name.replace('_', ' ')} field"
        elif self.kind == "field":
            where = (f"in the {self.name.replace('_', ' ')} field"
                     if self.name != "a field" else "in a field")
        else:
            where = f"at the {self.name.replace('_', ' ')}"
        return f"{where} ({self.confidence:.0%} sure, {self.source}, {self.age:.0f}s ago)"


class Bearings:
    """The bot's sense of place and heading. Fed observations, asked questions."""

    def __init__(self, table: lm.Table | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 emit: Callable | None = None):
        self.table = table or lm.Table({})
        self.clock = clock
        self.emit = emit
        self.store = beliefs.BeliefStore()
        self.heading_taps: int = 0            # 0 is spawn heading
        self.shift_lock: bool | None = None   # None until a spawn says
        self.turns = 0                          # total taps counted, for the log
        self.spawns = 0                         # spawned() calls; act/camera watches it
        self.routes_run = 0
        self.pad_offset: tuple[int, int] | None = None   # (steps forward, taps) at claim
        self._last_pollen: tuple[int, float] | None = None
        # Motion, from the route runner: since when movement keys have been
        # held with the world standing still. "Pushing against something" is
        # that, lasting.
        self._blocked_since: float | None = None
        self._motion_at: float | None = None     # the last saw_motion report
        self._last_moved_at: float | None = None
        self.blocked_episodes = 0
        # The last threat the watch reported, and when. Short-lived: a mob
        # that was on screen five seconds ago may be gone or may be biting.
        self._threat: tuple[str, float] | None = None
        self.threats_seen = 0
        self._last_said = ""
        # `on_panel(place)`: told each time the panel names a place, which is
        # a label for whatever the camera shows (vision/fieldsense.Labeller).
        self.on_panel = None

    # ---- observations -------------------------------------------------------
    def saw_panel(self, text: str | None) -> lm.Landmark | None:
        """The top-centre panel, or its absence.

        "" means we looked and there was no panel -- a real observation, and
        it says we are NOT standing at any landmark. None means we could not
        look (no frame, model down), which says nothing.
        """
        if text is None:
            return None
        now = self.clock()
        mark = self.table.match(text)
        if mark is None:
            if text.strip() == "" or not self.table.is_prompt(text):
                # No panel, or panel text that is not about a place. Either
                # way we are not standing at a recorded landmark.
                self.store.invalidate("place:panel")
                self.store.observe("not_at_landmark", True, source="panel",
                                   confidence=0.95, at=now)
                self._changed()
            return None
        self.store.invalidate("not_at_landmark")
        if self.on_panel is not None:
            try:
                self.on_panel(mark.place)
            except Exception:
                pass          # a dataset collector must never break the compass
        kind = "hive" if mark.place == "hive" else mark.kind
        self.store.observe("place:panel", (mark.place, kind, mark.mine),
                           source="panel", confidence=0.98, at=now)
        if mark.place == "hive":
            # Standing on a pad means we are not out in a field, whatever the
            # last pickup said.
            self.store.invalidate("in_field")
        self._changed()
        return mark

    def saw_feed(self, fix) -> None:
        """A `vision.whereami.Fix`: the game named the field on a pickup."""
        field = getattr(fix, "field", None)
        if not field:
            return
        at = getattr(fix, "at", None)
        now = self.clock()
        # The fix carries its own timestamp on the same clock the tracker
        # uses; if it does not match ours, believe it as of now.
        when = at if isinstance(at, (int, float)) and at <= now else now
        self.store.observe("place:feed", (str(field), "field", None),
                           source="feed", confidence=0.95, at=when)
        self.store.observe("in_field", True, source="feed",
                           confidence=0.95, at=when)
        self.store.invalidate("place:panel")
        self.store.invalidate("place:spawn")
        self._changed()

    def saw_pollen(self, reading) -> bool | None:
        """A HUD pollen reading. A rise means we are in a field that pays.

        Returns True on a rise, False on no rise, None when unreadable. A rise
        is the only thing recorded: a flat counter is exactly what the hive
        and a wall both look like, so it proves nothing on its own.
        """
        if reading is None or not getattr(reading, "ok", False):
            return None
        value = getattr(reading, "value", None)
        if value is None:
            return None
        now = self.clock()
        rose = None
        if self._last_pollen is not None:
            last, _ = self._last_pollen
            rose = value > last
            if rose:
                self.store.observe("in_field", True, source="pollen",
                                   confidence=0.85, at=now)
                self.store.invalidate("place:spawn")
                self._changed()
        self._last_pollen = (int(value), now)
        return rose

    def heard(self, sentence: str | None) -> None:
        """A sentence from the vision model. Weak, and only ever coarse."""
        if not sentence:
            return
        low = " ".join(str(sentence).lower().split())
        now = self.clock()
        if any(w in low for w in HEARD_HIVE):
            self.store.observe("place:heard", ("hive", "hive", None),
                               source="heard", confidence=0.45, at=now)
            self._changed()
        elif any(w in low for w in HEARD_FIELD):
            self.store.observe("place:heard", ("a field", "field", None),
                               source="heard", confidence=0.40, at=now)
            self.store.observe("in_field", True, source="heard",
                               confidence=0.40, at=now)
            self._changed()

    def saw_sight(self, field: str, sure: float) -> None:
        """vision/fieldsense's look said this is `field`, and looks like it
        were right `sure` of the time on unseen nights. A fallback belief:
        see `_best`."""
        if not field:
            return
        self.store.observe("place:sight", (str(field), "field", None),
                           source="sight", confidence=float(sure),
                           at=self.clock())
        self._changed()

    def saw_motion(self, keys: str, flow_px: float) -> bool | None:
        """Movement keys are held and the world slid `flow_px`. True = moving.

        Called at the route runner's watch rate while a key is down. Below
        BLOCKED_FLOW_PX (MEASURED, vision/flow) nothing is moving, and if that
        goes on the character is pressed against something. Only a claim about
        RIGHT NOW: it does not move the place belief, because a wall is not a
        place.
        """
        now = self.clock()
        self._motion_at = now
        if not keys:
            self._blocked_since = None
            return None
        if flow_px >= BLOCKED_FLOW_PX:
            self._blocked_since = None
            self._last_moved_at = now
            return True
        if self._blocked_since is None:
            self._blocked_since = now
            self.blocked_episodes += 1
        return False

    def saw_threat(self, what: str) -> None:
        """brain/threat saw a mob bar or the attack disc. Remembered briefly."""
        if not what:
            return
        self._threat = (" ".join(str(what).split())[:120], self.clock())
        self.threats_seen += 1
        self._changed()

    def threat(self, within: float = THREAT_SECONDS) -> str | None:
        """What was threatening us within the last few seconds, or None."""
        if self._threat is None:
            return None
        what, at = self._threat
        return what if self.clock() - at <= within else None

    @property
    def blocked_seconds(self) -> float:
        """How long the held keys have been moving nothing, right now -- 0
        once no report has come for MOTION_FRESH_S (the keys are up)."""
        if self._blocked_since is None:
            return 0.0
        now = self.clock()
        if self._motion_at is None or now - self._motion_at > MOTION_FRESH_S:
            return 0.0
        return max(0.0, now - self._blocked_since)

    def spawned(self) -> None:
        """A join or rejoin landed. Position AND heading are known again.

        MEASURED: spawn is the hive area (both joins on 2026-09-20 claimed a
        pad within two hops), the camera faces the honeycomb wall (act/orient),
        and Roblox starts with shift lock off.
        """
        now = self.clock()
        for key in ("place:panel", "place:feed", "place:heard", "place:sight",
                    "not_at_landmark", "in_field"):
            self.store.invalidate(key)
        self.store.observe("place:spawn", ("hive", "hive", None),
                           source="spawn", confidence=0.9, at=now)
        self.spawns += 1
        self.heading_taps = 0
        self.shift_lock = False
        self._last_pollen = None
        self.pad_offset = None
        self._blocked_since = None
        self._threat = None
        self._changed()

    def claimed(self, steps_forward: int, at_taps: int) -> None:
        """The hive sweep found our pad: this many steps out, facing this way.

        Recorded so the geometry the routes assume -- "start at your own pad,
        facing spawn heading" -- is at least written down when it does not
        hold. It is a fact about this session, not a fix on the map.

        THE TAPS ARE ALSO APPLIED TO THE HEADING, and they were not. This
        stored them in `pad_offset` and stopped, so after a SUCCESSFUL claim
        the compass still believed the camera was at spawn heading -- and
        `journey.square_up` then had nothing to undo and left the route to run
        however far round the sweep had turned it. The `else` branch in the
        caller already called `turned()` when the claim FAILED, which is the
        wrong way round.
        
        It happens not to have bitten this account yet: `sweep_and_claim` taps
        a full turn first, so its total is 8 + (the bearing it picked),
        and every live run so far picked 0 ("strongest bearing at 0° (0 px)" in
        runs 45, 46, 47, 49 and 50). 8 taps modulo a full turn is zero, so the
        belief was accidentally right. The first time the red probe finds
        anything, it stops being right, silently.
        """
        self.pad_offset = (int(steps_forward), int(at_taps) % TAPS_PER_FULL_TURN)
        self.turned(int(at_taps))
        self.saw_panel("make honey")

    def turned(self, taps: int) -> None:
        """The camera was tapped: right is positive, left negative."""
        if not taps:
            return
        self.heading_taps = (self.heading_taps + int(taps)) % TAPS_PER_FULL_TURN
        self.turns += abs(int(taps))

    def toggled_shift_lock(self) -> None:
        if self.shift_lock is not None:
            self.shift_lock = not self.shift_lock

    def moved(self, what: str = "") -> None:
        """A route or a walk ran, so every position fix is now suspect.

        Landmark fixes are killed outright -- the character is no longer where
        the panel last said. A feed fix is left to decay: a walk within a
        field does not leave it.
        """
        self.routes_run += 1
        self.store.invalidate("place:panel")
        self.store.invalidate("place:spawn")
        self.store.invalidate("not_at_landmark")
        self.store.invalidate("place:heard")
        self.store.invalidate("place:sight")

    # ---- questions ----------------------------------------------------------
    def _best(self) -> Place | None:
        now = self.clock()
        best: Place | None = None
        named = False
        for key in ("place:panel", "place:feed", "place:spawn", "place:heard",
                    "place:sight"):
            belief = self.store.raw(key)
            if belief is None:
                continue
            conf = belief.confidence(now)
            if conf < FLOOR:
                continue
            if key in ("place:panel", "place:feed"):
                named = True
            elif key == "place:sight" and named:
                continue      # the game has said where; a look does not argue
            name, kind, mine = belief.value
            place = Place(name=name, kind=kind, source=belief.source,
                          confidence=conf, age=belief.age(now), mine=mine)
            if best is None or place.confidence > best.confidence:
                best = place
        if best is None:
            # No named place, but the counter is rising: we are in a field.
            conf = self.store.confidence("in_field", now)
            if conf >= FLOOR:
                b = self.store.raw("in_field")
                return Place(name="a field", kind="field", source=b.source,
                             confidence=conf, age=b.age(now))
        return best

    def where(self) -> Place | None:
        """The best current belief, or None when there is not one worth holding."""
        return self._best()

    def at(self, place: str) -> bool | None:
        """Are we at `place`? True, False, or None for "no idea".

        False is only ever said on evidence: a fresh fix somewhere else, or the
        panel having been looked for and not found (for landmarks).
        """
        now = self.clock()
        best = self._best()
        if best is not None and best.name == place:
            return True
        is_landmark = place in self.table.places()
        if is_landmark and self.store.confidence("not_at_landmark", now) >= FLOOR:
            return False
        if best is not None and best.confidence >= SURE_ELSEWHERE and best.name != place:
            if not (best.name == "a field" and place not in self.table.places()):
                return False
        return None

    def on_my_pad(self) -> bool | None:
        """Standing on the pad we own, per the panel, right now."""
        now = self.clock()
        b = self.store.raw("place:panel")
        if b is not None and b.confidence(now) >= FLOOR:
            name, _, mine = b.value
            return bool(name == "hive" and mine)
        if self.store.confidence("not_at_landmark", now) >= FLOOR:
            return False
        return None

    def in_field(self) -> str | bool | None:
        """Which field we are in, True for "some field", False for "not in one".

        False comes from standing at a landmark. None is "cannot tell", and it
        is the honest answer for most of a walk between places.
        """
        now = self.clock()
        feed = self.store.raw("place:feed")
        if feed is not None and feed.confidence(now) >= FLOOR:
            return feed.value[0]
        panel = self.store.raw("place:panel")
        if panel is not None and panel.confidence(now) >= FLOOR:
            return False
        if self.store.confidence("in_field", now) >= FLOOR:
            return True
        spawn = self.store.raw("place:spawn")
        if spawn is not None and spawn.confidence(now) >= 0.8:
            return False
        return None

    # ---- heading ------------------------------------------------------------
    def taps_to_square(self) -> int:
        """Signed taps to return to spawn heading: negative is left (comma)."""
        h = self.heading_taps % TAPS_PER_FULL_TURN
        if h == 0:
            return 0
        return -h if h <= TAPS_PER_FULL_TURN // 2 else TAPS_PER_FULL_TURN - h

    @property
    def heading_degrees(self) -> float:
        return (self.heading_taps * 360.0 / TAPS_PER_FULL_TURN) % 360.0

    # ---- reporting ----------------------------------------------------------
    def describe(self) -> str:
        place = self.where()
        where = place.describe() if place else "nowhere I can confirm"
        facing = ("spawn heading" if self.heading_taps % TAPS_PER_FULL_TURN == 0
                  else f"{self.heading_degrees:.0f}° right of spawn heading")
        lock = ("on" if self.shift_lock else "off" if self.shift_lock is False
                else "unknown")
        text = f"I am {where} · facing {facing} · shift lock {lock}"
        if self.blocked_seconds >= 1.0:
            text += f" · pushing against something for {self.blocked_seconds:.0f}s"
        threat = self.threat()
        if threat:
            text += f" · THREAT: {threat}"
        return text

    def _changed(self) -> None:
        if self.emit is None:
            return
        text = self.describe()
        if text == self._last_said:
            return
        self._last_said = text
        try:
            from ..telemetry.events import Belief, Thought
            place = self.where()
            self.emit(Thought(topic="where", text=text))
            self.emit(Belief(name="where",
                             value=place.describe() if place else "unknown",
                             source=place.source if place else "",
                             confidence=place.confidence if place else 0.0))
        except Exception:
            pass

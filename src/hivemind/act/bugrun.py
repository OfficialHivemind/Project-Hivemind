"""Killing the field mobs on purpose: Natro Macro's bug run, with eyes.

THE OWNER, 2026-09-25, asked for the bot to fight mobs. Until today the bot only ever ran
from them -- `brain/threat` cuts a walk short at a mob's health bar -- and let
the bees fight whatever came near while it gathered (DESIGN 8ce). That is how
every fight step the account has held got done: the quest menu read "Defeat 16
Ladybugs. Complete!", "Defeat 16 Rhino Beetles. Complete!", "Defeat 10
Spiders. 9/10", "Defeat 10 Mantises. 8/10", "Defeat 15 Scorpions. 14/15" and
"Defeat 5 Werewolves. 4/5" (var/night/run-3*.log), so these bees kill all six
kinds. None of it was sought out.

WHAT NATRO DOES (nm_Bugrun, submacros/natro_macro.ahk:13899-15160 at the
pinned commit). Per mob kind a respawn timer; when one is due it resets,
walks the field's gotoField path, looks for a health bar (`nm_HealthDetection`
is a pixel search for the bar's green 0x1fe744 and red 0x6b131a), holds the
tool and waits while bars are on screen -- turning the camera two taps left
half way through a quiet spell -- until one whole inner loop sees no bar,
then walks a loot pattern over the drops and writes the kill time down.

WHAT THIS KEEPS, from `data/knowledge/mobs.yaml`, which cites every line:
the per-field look loop, the wait loop (rounds, looks, spacing, the turn),
the Werewolf's and the Scorpions' dodge square, the loot walks, the timers.

WHAT THIS CHANGES, each for a measured or cited reason:

  * THE EYE IS `vision/nameplate`, not a pixel colour. It was rebuilt on this
    client's frames (DESIGN 8g): 18 of 18 hits checked by eye were real, 0
    false positives on the fixture screens. MEASURED 2026-09-25 at 13 ms a
    look on a 1920x1080 frame (120 saved frames, nice 19), so Natro's sleeps
    between looks, not the looking, set the pace.
  * THE PLAYER'S OWN HEALTH IS READ (`vision/hurt.own_health`) and the fight
    is left at `combat.retreat_health`. Natro has no such exit: its only
    death check is `youDied`.
  * NO PAGEUP/PAGEDOWN AND NO ZOOM. Natro tilts the camera four taps for the
    fight and zooms out on every look. DESIGN 8ap measured the tilt changing
    nothing and warned that a death mid-way leaves the camera tilted; and
    every threshold this bot homes by (the hive wall's pixel count, the
    respawn view templates) was measured at its own zoom, which a zoom-out
    would change for the rest of the session.
  * THE TURN IS UNDONE ONCE. Natro sends `RotLeft 2` every time a quiet spell
    reaches `turn_at`, in any round, and `RotRight 2` once at the end; this
    turns once per fight and undoes exactly what it turned.
  * THE TOOL IS NOT HELD. Natro holds `Click "Down"` (natro_macro.ahk:13966)
    and that swings the collector, which gathers pollen and hurts nothing:
    the wiki's Mob page lists what can attack a mob -- bees, flames, frogs,
    the Rogue Vicious and Wild Windy Bees, abilities, passives, coconuts and
    Beesmas coal -- and the player's tool is not on it. The pollen it adds
    (2,193/s with the tool against 780/s with bees alone, measured in Pine
    Tree, brain/farm) would only be thrown away: the way home is the
    respawn every errand takes (run_farm `respawn_home`).
  * ONLY THE FEED COUNTS A KILL. Natro sets `success:=1` on its last round
    whether or not the bar went; here that is `left == "cap"`, booked as a
    visit. And a bar that left the detector is not a kill either: MEASURED
    on the Rose frames of var/incidents/233202 (scratchpad bugrun4/
    trace_233202.out), `vision/nameplate` saw a scorpion's bar at 0.0-0.1 s
    and never again, while "Scorpion (Lvl 5) HP: 53" was drawn at 1.8 s (its
    run-down green 117x55, under the detector's aspect 2.5) and "Scorpion
    (Lvl 6) HP: 65" filled the screen at 4.0 s (122 px tall, over its 70),
    and the character's own bar fell 0.86 -> 0.33 in between. So only a
    "Defeated <Name>!" line in the reward feed books a kill; bars that went
    book a visit (`gone`). The timer is booked either way, which is Natro's
    rule too: it writes LastBugrun* after every attempt.
  * A MOB THAT HITS IS STILL THERE. A fall in the character's own health
    (`Hits`) counts as a bar seen, in the look and in the wait, so a mob too
    close for the detector keeps the fight going. And after a "gone" the
    feed has not confirmed, the loot walk watches for the same falls: a hit
    before any leg ends it (`HIT_AGAIN`), before the first leg too, so no
    loot walk starts while our health is falling.
  * THE CAP IS NATRO'S OWN LONGEST WAIT. Natro's rounds end at the first bar
    it sees, so with a bar in view its fight lasts as long as its looks take
    and its loot walk finishes the job; its LONGEST wait in a field is a quiet
    spell one look short of "gone" in every round, `rounds x (looks - 1) x
    sleep` plus any per-round pause and dodge move (`Profile.cap_seconds`).
    That is the bound used, in seconds: 9 s at Strawberry, 57 s at Spider.
  * THE LOOK GOES AROUND. Natro zooms out on every look and this bot does
    not (above), so its view is narrower, and MEASURED 2026-09-26 over the
    saved runs (scratchpad bugrun/arrive_bars.py, arrive_to_bar.py): the last
    frame of a walk out showed a mob bar on 2 of 127 Pine Tree walks, 3 of
    81 Strawberry and 2 of 23 Spider, and while gathering the first bar came
    within 3 s of arriving on 25% of Spider trips, within 10 s on 42%. So
    after Natro's own look loop the camera turns Natro's quiet-spell turn
    (`RotLeft 2`, 90 degrees) three times and looks at each heading for the
    field's own quiet spell, facing where a bar showed for the fight and
    turning back before the loot walk (`SWEEP_TAPS`).
  * TWO EMPTY LOOKS BOOK A VISIT, AS NATRO'S TWO TRIES DO. Natro's `while
    (not success)` resets and walks the field again when its look loop found
    nothing, up to twice (`if(A_Index>=3) break`, natro_macro.ahk:13940).
    Here a visit is a whole errand, so the second try is the next convert's:
    the first empty look is written down (`empty_visits`) without starting
    the timer, the second starts it (`EMPTY_VISITS_TO_BOOK`).
  * THE RETREAT LINE MUST HOLD. The own-health reader flashes: MEASURED over
    65 saved windows with the bar drawn (scratchpad bugrun2/hp_flash2.out,
    7,463 reads), 14 dips to 0.0 that came back within 0.0-0.3 s, while
    the two deaths in them (034403, 063652) stayed down 0.8-1.3 s, until the
    respawn. So a read at the line counts only once the reads have stayed
    there `HP_CONFIRM_SECONDS`.
  * THE FEED CAN END THE WAIT. When the reward feed has named every mob the
    field holds ("Defeated Ladybug!" twice at Strawberry) the fight is won,
    whatever the bars do, and the loot walk starts (`left == "killed"`).
  * NO LOOT WALK AFTER AN EMPTY LOOK. Natro loots whether or not it found
    anything; the wiki (Mob) says a defeated mob "drop[s] a ring of tokens
    around it", so with no bar seen there is nothing on the ground to walk.
  * THE DODGE SQUARE IS WALKED IN NATRO'S FRAME. The look around leaves the
    camera turned for the fight, and the movement keys are camera-relative,
    so each dodge key is turned back by the quarter turns still applied
    (`turned_keys`): the square, and the loot walk's opening legs that Natro
    picks by it, land where Natro lays them out, and the camera stays on the
    bar. Which way a tap turns is Roblox's camera script (Core-Scripts
    BaseCamera.lua): "," adds a negative yaw input and the view is turned by
    CFrame.Angles(0, -input, 0), a turn to the LEFT, which is also Natro's
    name for it (`RotLeft`, ","). Turning the camera back for each hold and
    forth after would do the same at 0.25 s a tap (run_farm `turn_camera`):
    1-3 s a round for a bar found 90-270 degrees round, out of a longest
    wait of 49 s over 25 rounds at the Pumpkin Patch.
  * NO RUN AFTER ITS TIME. A run whose way out used up `combat.bug_run_seconds`
    does not look, and one that finds a bar with no time left does not stand
    (`left == "late"`), so no timer is started on a mob it never fought. The
    deadline is checked before the arrival, before every heading of the look
    and before every look.

WHAT IT DELIBERATELY DOES NOT DO: bosses (King Beetle, Tunnel Bear, Stump
Snail, Coconut Crab, Commando Chick, Mondo Chick) -- their HP persistence is
unmeasured (data/world/timers.yaml marks every one `verified: false`) and
Natro fights each with a bespoke routine; press any key but movement and the
two camera keys; or walk a fight with a loaded bag (run_farm checks
`act/respawn.bag_is_empty_enough` before it leaves the pad).
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..vision import hurt, nameplate

# Natro's `Walk(n)` is n TILES, and lib/Walk.ahk says "4 studs in a tile" --
# the same rule scripts/transpile_natro.py uses (STUDS_PER_TILE).
STUDS_PER_TILE = 4.0

# THE SWITCHES, read here in the library so the GUI's controls are wired to
# something real (tests/unit/test_settings.py looks for these names).
MASTER_SWITCH = "combat.bug_runs"
LOOT_SWITCH = "combat.bug_loot"
RETREAT_SETTING = "combat.retreat_health"
RUN_SECONDS_SETTING = "combat.bug_run_seconds"
WORTH_SWITCH = "combat.bug_worth_it"
MOB_SWITCHES = {
    "ladybug": "combat.bug_ladybug",
    "rhino_beetle": "combat.bug_rhino_beetle",
    "spider": "combat.bug_spider",
    "mantis": "combat.bug_mantis",
    "scorpion": "combat.bug_scorpion",
    "werewolf": "combat.bug_werewolf",
}

# "Defeated Rhino Beetle! (+1 Battle Point)" -- the reward feed's kill line.
# MEASURED in the saved feed reads (var/incidents/*-token/reason.txt, the text
# the vision model transcribed off the feed): "Defeated Rhino Beetle! (+1
# Battle Point) +130 Bond (from Rhino Beetle) Defeated Mantis! (+5 Battle
# Points)" (000311), and "Defeated Rhino Beetle! +1 Battle Point" (234908),
# where the brackets were dropped and the "!" kept. DESIGN 8a's feed sample
# read "defeated mantis! (+5 battle points)", lower case, so case is ignored.
DEFEATED = re.compile(r"defeated\s+([a-z][a-z' ]*?)\s*!", re.IGNORECASE)

# HOW LONG ONE KILL LINE STAYS ON THE FEED, so a line read twice is one kill.
# MEASURED 2026-09-25 on the frames of var/incidents/000311-token,
# 000314-token and 000320-token (the feed corner, scratchpad
# bugrun2/feed_life.jpg): "Defeated Rhino Beetle!" appears 2.3 s into
# 000311's window (about 00:03:05.6), is drawn in every frame of 000314's,
# fades from about 00:03:12 and is gone by about 00:03:14 -- 8-9 s on screen,
# timed off stamps one second apart. The feed is read every 3 s
# (whereami.Tracker.DEFAULT_EVERY) and saw each kill line in exactly two reads
# (000311/000314, 234357/234400, 234906/234908, never a third); and 235420,
# two seconds after 235418 had the line, did not -- a read can drop a line
# that is still drawn, so "absent once" is not "gone". The 9 s, plus a second
# for the stamps.
FEED_LINE_SECONDS = 10.0

# How many runs the log keeps, for the morning's reading and the GUI. The
# file is rewritten on every booking, so it stays small.
RUNS_KEPT = 60

# THE LOOK AROUND (module docstring). Natro's quiet-spell turn is `RotLeft 2`
# (natro_macro.ahk:13976, 14097, 14207 ...), two 45-degree camera taps
# (nav/journey QUARTER_TURN_TAPS); four headings of it are the full circle.
SWEEP_TAPS = 2
SWEEP_HEADINGS = 4

# HOW LONG THE OWN-HEALTH READ MUST STAY AT THE RETREAT LINE before it counts.
# MEASURED (scratchpad bugrun2/hp_flash2.out): the reader's false dips lasted
# 0.0-0.3 s from their first low read to their last, and 0.2-0.4 s from the
# good read before to the good read after; the real falls in the same windows
# (034403 and 063652, both deaths) stayed low 0.8-1.3 s, until the respawn.
# Half a second is past every flash and a few looks at any field's spacing.
HP_CONFIRM_SECONDS = 0.5

# HOW FAR THE OWN-HEALTH READ MUST FALL BETWEEN TWO READS TO BE A HIT.
# MEASURED 2026-09-26 over the same 65 windows (scratchpad bugrun4/
# hp_falls.out, 6,917 pairs of consecutive drawn reads above 0): the read
# moves in steps of 1/117 (the track is 117 columns, hurt.HP_TRACK); it fell
# 1 step 250 times, 2 steps 4 times and 3 steps once, and every other fall
# was 7 steps or more (48 of them, 47 of 10+: the scorpions' 22, 0.19 a hit,
# in 233202). Nothing fell 4-6 steps. 0.04 is just under 5 steps.
HP_HIT_DROP = 0.04

# THE WORDS A LOOT WALK STOPS WITH ON OUR OWN HEALTH, as names the caller can
# test for, the way act/routes has CANNON_MISS and UNWALKED: every such stop
# starts with OWN_HEALTH (`left_on_health`), at the retreat line (RETREATED)
# or on a hit after bars the feed did not confirm gone (HIT_AGAIN).
OWN_HEALTH = "own health"
RETREATED = "held at the retreat line"
HIT_AGAIN = "a mob the detector lost is still hitting us"

# WHICH KEY WALKS WHICH WAY ONCE THE VIEW HAS TURNED A QUARTER LEFT (module
# docstring, THE DODGE SQUARE): the old forward is the new right, and so on.
QUARTER_TAPS = 2
_QUARTER_LEFT = {"w": "d", "d": "s", "s": "a", "a": "w"}

# Natro's two tries at a field whose look loop found nothing (module
# docstring): the second empty look starts the respawn timer.
EMPTY_VISITS_TO_BOOK = 2

# A RESPAWN HOME AFTER AN ERRAND, for planning a run's length. MEASURED in
# DESIGN 8ds (audit-farm): a median 9 s over 65 respawns, to the next trip's
# "staying up to" line.
RESPAWN_SECONDS = 9.0

# THE HONEY A TICKET IS WORTH, for ranking the loot. The Ticket Shop sells
# ticket n for 100,000 + 1000 n^1.2 honey (wiki Ticket_Shop, rev 2026-08-10,
# formula datamined 2026-03-18; salvage/materials_research.json "currency:
# Tickets"), so the cheapest a ticket ever costs in honey is 100,000.
TICKET_HONEY = 100_000


@dataclass(frozen=True)
class Mob:
    """One mob kind, as its wiki page describes it."""
    slug: str
    name: str
    respawn_seconds: float
    battle_points: int = 0
    honey: int = 0
    ticket_chance: float = 0.0
    damage: int = 0
    fields: dict = field(default_factory=dict)   # field -> {count, levels, hp}
    # Fields it defends without being fought there: the Werewolf "defends
    # three fields instead of one" (wiki) and Natro fights it in one of them.
    also_defends: tuple = ()

    def count_in(self, where: str) -> int:
        row = self.fields.get(where) or {}
        try:
            return max(0, int(row.get("count", 0) or 0))
        except (TypeError, ValueError, AttributeError):
            return 0

    def booked_in(self, where: str) -> tuple:
        """The fields whose timer a kill of this mob in `where` starts: that
        field when it lives there, the fields it is fought in when it only
        defends `where` (one Werewolf for three fields), else none."""
        if self.count_in(where) > 0:
            return (where,)
        if where in self.also_defends:
            return tuple(f for f in self.fields if self.count_in(f) > 0)
        return ()


@dataclass(frozen=True)
class Profile:
    """Natro's fight in one field. See data/knowledge/mobs.yaml `fields:`."""
    field: str
    source: str = ""
    books: tuple = ()
    arrive: tuple = ()
    fight_turn: int = 0
    look_tries: int = 20
    look_every: float = 0.15
    # FULL CIRCLES OF THE LOOK AROUND (SWEEP_HEADINGS each). One is Natro's
    # reach; a field whose mob comes late gets more. See mobs.yaml `sweeps`.
    sweeps: int = 1
    rounds: int = 10
    looks: int = 10
    every: float = 0.10
    turn_at: int = 0
    round_pause: float = 0.0
    dodge_tiles: float = 0.0
    dodge_keys: tuple = ()
    loot: tuple = ()
    loot_after_dodge: dict = field(default_factory=dict)

    def dodge_seconds(self, walkspeed: float) -> float:
        if not self.dodge_keys or self.dodge_tiles <= 0:
            return 0.0
        return self.dodge_tiles * STUDS_PER_TILE / max(1.0, float(walkspeed))

    def cap_seconds(self, walkspeed: float = 28.0) -> float:
        """Natro's longest wait here: a quiet spell one look short of "gone"
        in every one of its rounds, plus each round's pause and dodge move."""
        per_round = (max(0, self.looks - 1) * self.every + self.round_pause
                     + self.dodge_seconds(walkspeed))
        return self.rounds * per_round

    def look_seconds(self) -> float:
        """How long the first look loop can take: Natro's `loop 20 {...;
        Sleep 150}`."""
        return max(1, self.look_tries) * self.look_every

    def sweep_looks(self) -> int:
        """Looks at each heading of the look around: the field's own quiet
        spell before Natro turns (`turn_at`), or its whole inner loop where
        Natro never turns (Clover, the Pumpkin Patch, the Rose Field)."""
        return max(1, int(self.turn_at or self.looks))

    def sweep_seconds(self) -> float:
        """The look around at most: three more headings, each a turn of
        SWEEP_TAPS taps (run_farm's `turn_camera` waits 0.25 s a tap) and its
        looks, and the turn back."""
        headings = SWEEP_HEADINGS * max(1, int(self.sweeps)) - 1
        turns = headings * SWEEP_TAPS * 2 * 0.25
        return headings * self.sweep_looks() * self.every + turns

    def arrive_seconds(self, walkspeed: float = 28.0) -> float:
        total = 0.0
        for step in self.arrive:
            step = step or {}
            try:
                if "pause_s" in step:
                    total += float(step.get("pause_s") or 0.0)
                elif "walk" in step:
                    total += (float(step["walk"][1]) * STUDS_PER_TILE
                              / max(1.0, float(walkspeed)))
            except (TypeError, ValueError, IndexError, KeyError):
                continue
        return total

    def loot_seconds(self, walkspeed: float = 28.0) -> float:
        """Natro's loot walk at `walkspeed`, the longest of its dodge-square
        openings included."""
        studs = sum(tiles for _keys, tiles in self.loot) * STUDS_PER_TILE
        if self.loot_after_dodge:
            studs += max(sum(t for _k, t in legs)
                         for legs in self.loot_after_dodge.values()) * STUDS_PER_TILE
        return studs / max(1.0, float(walkspeed))

    def plan_seconds(self, travel_seconds: float, walkspeed: float = 28.0,
                     loot: bool = True) -> float:
        """A run's planned bound here: the walk out at walkspeed with nothing
        in the way, Natro's arrival, the look and the look around, Natro's
        longest wait, the loot walk and the median respawn home
        (RESPAWN_SECONDS). The fight and the loot are held to it by the
        run's deadline; the way out and the respawn home are not cut, so a
        run whose walk was slowed can take longer."""
        return (float(travel_seconds) + self.arrive_seconds(walkspeed)
                + self.look_seconds() + self.sweep_seconds()
                + self.cap_seconds(walkspeed)
                + (self.loot_seconds(walkspeed) if loot else 0.0)
                + RESPAWN_SECONDS)


@dataclass
class Book:
    """Every mob and every field fight the knowledge base describes."""
    mobs: dict = field(default_factory=dict)       # slug -> Mob
    profiles: dict = field(default_factory=dict)   # field -> Profile

    def mobs_in(self, where: str) -> tuple:
        """The mob kinds that live in `where`, in the table's order."""
        return tuple(slug for slug, mob in self.mobs.items()
                     if mob.count_in(where) > 0)

    def slug_for(self, name: str) -> str:
        """"Rhino Beetle" or "rhino beetle" -> "rhino_beetle"; "" if unknown.

        Singular only -- the feed says "Defeated Mantis!" -- and only the
        names the book holds, which questneeds.mob_slug (plurals, any
        name) does not check."""
        low = " ".join(str(name or "").lower().split())
        for slug, mob in self.mobs.items():
            if low == mob.name.lower() or low == slug.replace("_", " "):
                return slug
        return ""


def _legs(raw) -> tuple:
    """[keys, tiles] and {repeat: N, legs: [...]} opened out into (keys, tiles)."""
    out = []
    for item in raw or ():
        if isinstance(item, dict):
            try:
                times = int(item.get("repeat", 1) or 1)
            except (TypeError, ValueError):
                continue
            inner = _legs(item.get("legs"))
            for _ in range(max(0, times)):
                out.extend(inner)
            continue
        try:
            keys, tiles = str(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if keys and tiles > 0:
            out.append((keys, tiles))
    return tuple(out)


def load(path) -> Book:
    """Read data/knowledge/mobs.yaml. A broken file is an empty book, so the
    bug runs simply have nothing to do rather than failing the session."""
    import yaml
    try:
        body = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return Book()
    if not isinstance(body, dict):
        return Book()
    book = Book()
    for slug, row in (body.get("mobs") or {}).items():
        row = row or {}
        try:
            book.mobs[str(slug)] = Mob(
                slug=str(slug), name=str(row.get("name") or slug),
                respawn_seconds=float(row.get("respawn_seconds")),
                battle_points=int(row.get("battle_points", 0) or 0),
                honey=int(row.get("honey", 0) or 0),
                ticket_chance=float(row.get("ticket_chance", 0.0) or 0.0),
                damage=int(row.get("damage", 0) or 0),
                fields=dict(row.get("fields") or {}),
                also_defends=tuple(str(f) for f in
                                   (row.get("also_defends") or ())))
        except (TypeError, ValueError, AttributeError):
            continue              # no respawn time means no timer: skipped
    for where, row in (body.get("fields") or {}).items():
        row = row or {}
        try:
            look = row.get("look") or {}
            wait = row.get("wait") or {}
            dodge = row.get("dodge") or {}
            after = {}
            for key, legs in (row.get("loot_after_dodge") or {}).items():
                after[int(key) % 4] = _legs(legs)
            book.profiles[str(where)] = Profile(
                field=str(where), source=str(row.get("source", "")),
                books=tuple(str(m) for m in (row.get("books") or ())
                            if str(m) in book.mobs),
                arrive=tuple(row.get("arrive") or ()),
                fight_turn=int(row.get("fight_turn", 0) or 0),
                look_tries=int(look.get("tries", 20)),
                look_every=float(look.get("every_s", 0.15)),
                sweeps=int(look.get("sweeps", 1) or 1),
                rounds=int(wait.get("rounds", 10)),
                looks=int(wait.get("looks", 10)),
                every=float(wait.get("every_s", 0.10)),
                turn_at=int(wait.get("turn_at", 0) or 0),
                round_pause=float(wait.get("round_pause_s", 0.0) or 0.0),
                dodge_tiles=float(dodge.get("tiles", 0.0) or 0.0),
                dodge_keys=tuple(str(k) for k in (dodge.get("keys") or ())),
                loot=_legs(row.get("loot")),
                loot_after_dodge=after)
        except (TypeError, ValueError, AttributeError):
            continue
    return book


# ---- the owner's switches ---------------------------------------------------
def enabled(settings) -> bool:
    """`combat.bug_runs`. Unreadable settings say yes, as `wanted_place`
    does for the errands: the owner asked for this, and a run not happening
    is the quieter failure."""
    try:
        return bool(settings.bool(MASTER_SWITCH))
    except Exception:
        return True


def wanted(settings, mob: str, quest: int = 0) -> bool:
    """Is a run for this mob kind allowed?

    NATRO'S RULE: its switch, OR a quest that wants it. Natro's test is
    `(BugrunSpiderCheck || QuestSpider || RileyAll)` (natro_macro.ahk:13931,
    and the same shape for every mob), so a per-mob switch that is off means
    "not for its own sake", and a quest step for that mob still sends the
    run. Only the master switch stops both. A mob with no switch (an Aphid)
    is never in the set."""
    if not enabled(settings):
        return False
    key = MOB_SWITCHES.get(str(mob))
    if key is None:
        return False
    if int(quest or 0) > 0:
        return True
    try:
        return bool(settings.bool(key))
    except Exception:
        return True


def loot_wanted(settings) -> bool:
    try:
        return bool(settings.bool(LOOT_SWITCH))
    except Exception:
        return True


def run_seconds(settings) -> float:
    """`combat.bug_run_seconds`: the planned bound on one run from leaving
    the pad (`Profile.plan_seconds`); the fight and the loot stop at it, the
    way out and the respawn home are not cut. The schema's default when
    unreadable."""
    try:
        value = float(settings.int(RUN_SECONDS_SETTING))
    except Exception:
        from ..world.settings import defaults
        value = float(defaults().get(RUN_SECONDS_SETTING, 0) or 0)
    return max(0.0, value)


def retreat_at(settings) -> float:
    """`combat.retreat_health` as a share of the health bar, 0..1. The
    schema's own default (35) when the settings cannot be read."""
    try:
        return max(0.0, min(1.0, settings.int(RETREAT_SETTING) / 100.0))
    except Exception:
        from ..world.settings import defaults
        return max(0.0, min(1.0, float(defaults().get(RETREAT_SETTING, 0)) / 100.0))


def worth_it(settings) -> bool:
    """`combat.bug_worth_it`: is a run no quest wants priced against the
    gathering it replaces (`pays`)? The schema's default when unreadable."""
    try:
        return bool(settings.bool(WORTH_SWITCH))
    except Exception:
        from ..world.settings import defaults
        return bool(defaults().get(WORTH_SWITCH, True))


# WHAT A KILL HAS PAID THIS ACCOUNT, MEASURED (the owner's list, item 11: learn
# real drop rates from its own kill log). The wiki prices a mob by its drop
# table; the reward feed says what reached the account ("+580 Honey (from Rhino
# Beetle)"), loot that was missed included -- the figure a run is worth.
# run_farm logs each feed-named kill (var/mob_kills.jsonl) beside each drop line
# (var/mob_drops.jsonl); a drop belongs to the nearest kill of its mob from
# KILL_DROPS_BEFORE_S before it to KILL_DROPS_S after (the feed is read every
# few seconds, so a drop line can be read in the same look as the kill or the
# one before). The counts are blended with the wiki's figures as the prior
# (brain/mobtable.blend): the wiki until kills come in, the measured rate once
# they outnumber mobtable.PRIOR_KILLS.
KILL_DROPS_S = 20.0
KILL_DROPS_BEFORE_S = 5.0
# Tesseract's readings of "Honey" in the feed (DROPPED: "Honëx" for Honey)
HONEY_READS = frozenset({"honey", "honex", "honëx", "honéx"})
TICKET_READS = frozenset({"ticket", "tickets"})


def measured_loot(kills_path, drops_path) -> dict:
    """{mob slug: (honey per kill, kills, kills with a ticket)} from the two
    logs; a mob with no kill logged is absent. A ticket is counted per KILL
    (did one drop), the unit of the wiki's chance -- so a misread "+410
    Tickets (from Werewolf)" cannot swamp it."""
    import json

    def rows(path):
        try:
            with open(path) as fh:
                return [r for r in (json.loads(line) for line in fh if line.strip())
                        if isinstance(r, dict)]
        except (OSError, ValueError):
            return []
    kills: dict = {}
    for r in rows(kills_path):
        kills.setdefault(str(r.get("mob")), []).append(float(r.get("at") or 0.0))
    honey: dict = {mob: [0.0] * len(times) for mob, times in kills.items()}
    ticket: dict = {mob: set() for mob in kills}
    for d in rows(drops_path):
        mob = str(d.get("mob"))
        item = str(d.get("item") or "").lower()
        if mob not in kills or item not in HONEY_READS | TICKET_READS:
            continue
        at = float(d.get("at") or 0.0)
        near = [(abs(at - t), i) for i, t in enumerate(kills[mob])
                if t - KILL_DROPS_BEFORE_S <= at <= t + KILL_DROPS_S]
        if not near:
            continue
        if item in TICKET_READS:
            ticket[mob].add(min(near)[1])
        else:
            honey[mob][min(near)[1]] += float(d.get("amount") or 0)
    return {mob: (sum(paid) / len(paid), len(paid), len(ticket[mob]))
            for mob, paid in honey.items() if paid}


def pays(choice, honey_per_hour) -> tuple:
    """(worth it, why) for a run no quest wants: the drops on offer
    (`Choice.loot`, tickets at TICKET_HONEY) against the honey the loop's
    last measured rate would gather in the run's planned bound
    (`Choice.plan_s`). Battle points, bond and treats are not priced. An
    unknown rate says yes -- nothing has measured the gathering yet -- and
    the run's own log line prices it afterwards."""
    try:
        rate = float(honey_per_hour or 0.0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate <= 0.0 or choice.plan_s <= 0.0:
        return True, "no measured honey rate to price it against"
    cost = choice.plan_s * rate / 3600.0
    if choice.loot >= cost:
        return True, (f"drops worth about {choice.loot:,.0f} honey against "
                      f"{cost:,.0f} of gathering in {choice.plan_s:.0f}s")
    return False, (f"not worth the gathering it replaces: drops worth about "
                   f"{choice.loot:,.0f} honey (measured, wiki prior) against {cost:,.0f} honey "
                   f"of gathering in its {choice.plan_s:.0f}s at "
                   f"{rate:,.0f}/h ({WORTH_SWITCH})")


# ---- the respawn timers, kept where the next process can read them ----------
class KillLog:
    """When each mob in each field was last killed or visited, on disk.

    Per FIELD as well as per mob, where Natro keeps one timer per mob kind
    (LastBugrunLadybugs covers all three ladybug fields): its runs chain the
    fields in one go, and these start one field at a time from the pad, so a
    strawberry kill says nothing about the mushroom ladybug.

    A VISIT BOOKS THE TIMER TOO -- Natro writes LastBugrun* after every
    attempt, found or not (natro_macro.ahk:13997, 14326, 14449, 14694,
    14839, 14953, 15135), and its attempt is up to two looks (module
    docstring). So a fight that saw a bar books the timer at once, and a
    look that found nothing books it on the second in a row
    (`EMPTY_VISITS_TO_BOOK`), which is what stops one empty field being
    visited every convert.

    Written from the main loop and from the reward-feed reader's thread, so
    every change holds a lock.
    """

    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()
        self.body = {"schema": 1, "fields": {}, "runs": []}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            self.body["fields"] = dict(raw.get("fields") or {})
            self.body["runs"] = list(raw.get("runs") or [])[-RUNS_KEPT:]

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.body, indent=1))
            tmp.replace(self.path)
        except OSError:
            pass

    def _row(self, where: str, mob: str) -> dict:
        fields = self.body.setdefault("fields", {})
        return fields.setdefault(str(where), {}).setdefault(str(mob), {})

    def row(self, where: str, mob: str) -> dict:
        """A copy of one field's record for one mob kind ({} if never).
        Under the lock: the feed reader's thread adds rows while the main
        loop reads them."""
        with self._lock:
            return dict((self.body.get("fields", {}).get(str(where)) or {})
                        .get(str(mob)) or {})

    def last(self, where: str, mob: str) -> float:
        """The later of the last kill and the last visit, 0 if never."""
        row = self.row(where, mob)          # a copy, taken under the lock
        try:
            return max(float(row.get("last_kill", 0.0) or 0.0),
                       float(row.get("last_try", 0.0) or 0.0))
        except (TypeError, ValueError):
            return 0.0

    def killed(self, where: str, mobs, at: float | None = None,
               how: str = "", feed: bool = False) -> None:
        """Book a kill. `feed` marks one the reward feed named, which since
        2026-09-26 is the only kind the bug runs book (module docstring);
        records written before then also hold kills booked on bars going."""
        at = float(at if at is not None else self.clock())
        with self._lock:
            for mob in mobs:
                row = self._row(where, mob)
                row["last_kill"] = max(at, float(row.get("last_kill", 0.0) or 0.0))
                row["kills"] = int(row.get("kills", 0) or 0) + 1
                row.pop("empty_visits", None)
                if feed:
                    row["feed_kills"] = int(row.get("feed_kills", 0) or 0) + 1
                if how:
                    row["how"] = str(how)[:80]
            self._save()

    def tried(self, where: str, mobs, at: float | None = None,
              why: str = "", empty: bool = False) -> bool:
        """Book a visit without a seen kill. `empty` is a look that found no
        bar at all: it starts the timer only on the EMPTY_VISITS_TO_BOOK-th
        in a row. True when the timer was started."""
        at = float(at if at is not None else self.clock())
        booked = True
        with self._lock:
            for mob in mobs:
                row = self._row(where, mob)
                row["tries"] = int(row.get("tries", 0) or 0) + 1
                if why:
                    row["why"] = str(why)[:80]
                if empty:
                    row["empty_visits"] = int(row.get("empty_visits", 0) or 0) + 1
                    if row["empty_visits"] < EMPTY_VISITS_TO_BOOK:
                        booked = False
                        continue
                row.pop("empty_visits", None)
                row["last_try"] = at
            self._save()
        return booked

    def note_run(self, run: dict) -> None:
        with self._lock:
            runs = self.body.setdefault("runs", [])
            runs.append(dict(run))
            del runs[:-RUNS_KEPT]
            self._save()

    def runs(self) -> list:
        """A copy of the run records, under the lock (see `row`)."""
        with self._lock:
            return [dict(r) for r in self.body.get("runs") or () if isinstance(r, dict)]

    def describe(self) -> str:
        kills = feed = tries = 0
        with self._lock:                    # see `row`
            for mobs in self.body.get("fields", {}).values():
                for row in (mobs or {}).values():
                    kills += int((row or {}).get("kills", 0) or 0)
                    feed += int((row or {}).get("feed_kills", 0) or 0)
                    tries += int((row or {}).get("tries", 0) or 0)
            runs = len(self.body.get("runs") or [])
        return (f"{kills} kill(s) booked ({feed} named by the reward feed), "
                f"{tries} visit(s) without a kill the feed named, "
                f"{runs} run(s) on record in {self.path.name}")


def due_mobs(book: Book, log: KillLog, settings, where: str,
             now: float | None = None, quest=None) -> tuple:
    """The mobs living in `where` that a run may go for (`wanted`: switched
    on, or a quest wants them) and whose respawn time has passed."""
    now = float(now if now is not None else time.time())
    quest = dict(quest or {})
    out = []
    for slug in book.mobs_in(where):
        mob = book.mobs[slug]
        if not wanted(settings, slug, int(quest.get(slug, 0) or 0)):
            continue
        if now - log.last(where, slug) >= mob.respawn_seconds:
            out.append(slug)
    return tuple(out)


# WHAT A RUN TO A FIELD HAS FOUND, MEASURED (ROADMAP M1). `choose` priced a
# run at the wiki's count of mobs in the field, as if every run met them all.
# MEASURED 2026-10-26 over the 60 runs in var/bugrun.json (13-23 Oct, every one
# for a quest): Rose Field Scorpions 19 kills in 18 runs, Pineapple 21 in 13,
# Pine Tree Mantises 17 in 11, Strawberry Ladybugs 13 in 7, Spider 3 in 3 --
# but the Pumpkin Patch's Werewolf 1 kill in 6 runs (5.5M honey of gathering a
# kill, against 0.4-1.2M everywhere else; 4 empty looks on 22 Oct 12:53-15:32)
# and Bamboo's Rhino Beetles 0 in 2. The Werewolf dies while the bot gathers
# instead: 103 of its kills were named in Pine Tree, 7 in the Pumpkin Patch
# (var/mob_kills.jsonl, 3-26 Oct). So the kills a run is expected to bring are
# the wiki's count blended with the field's own runs, the count worth
# RUN_PRIOR runs: (RUN_PRIOR x count + kills) / (RUN_PRIOR + runs), never over
# the count. A run counts once it reached the fight (`feed_kills` written);
# a failed walk out or an owner stop says nothing about the mobs.
RUN_PRIOR = 3


def run_yield(log: KillLog, where: str, mobs, expected: float) -> tuple:
    """(share of `expected` kills a run to `where` brings, runs, kills): the
    feed-named kills of `mobs` over the field's recorded runs, blended with
    the wiki's `expected` (RUN_PRIOR). (1.0, 0, 0) with no run on record."""
    mobs = set(mobs)
    runs = kills = 0
    for r in log.runs():
        if r.get("field") != where or "feed_kills" not in r \
                or not mobs & set(r.get("mobs") or ()):
            continue
        runs += 1
        kills += sum(1 for m in r.get("feed_kills") or () if m in mobs)
    if expected <= 0 or runs == 0:
        return 1.0, runs, kills
    got = (RUN_PRIOR * expected + kills) / (RUN_PRIOR + runs)
    return min(1.0, got / expected), runs, kills


@dataclass
class Choice:
    field: str
    mobs: tuple
    quest: int = 0             # how many of these a quest still wants
    points: int = 0            # battle points on offer (wiki)
    honey: int = 0             # the wiki's honey on offer
    loot: float = 0.0          # honey plus tickets at TICKET_HONEY (wiki)
    plan_s: float = 0.0        # the run's planned bound (Profile.plan_seconds)
    why: str = ""


def choose(book: Book, log: KillLog, settings, now: float | None = None, *,
           quest=None, bees: int = 0, required=None, usable=None,
           only_quest: bool = False, plan=None,
           cap_seconds: float = 0.0, measured=None) -> tuple:
    """(the field worth a run now, or None; why each other field was not).

    THE ORDER. A mob a quest still wants beats everything -- the Panda Bear's
    "The REAL Final Showdown" wants ten of five of these kinds and five
    Werewolves for a Gold Egg (salvage/account_research.json) -- and after
    that, among the quest's fields, the quest's kills a run is expected to
    bring (`run_yield`: the wiki's count, blended with the field's own runs)
    per second of it, then the drops per second of the run: the honey and ticket rate a kill
    paid (`measured`, blended with the wiki's figures as the prior,
    brain/mobtable.blend) for every due mob in the field, over the run's planned
    bound (`plan`). Battle points break a tie.

    `quest` is questneeds.Needs.mobs_wanted(); `bees` the bee count
    (account.yaml, or what the fields have proved); `required` each field's
    `bees_required` (data/knowledge/world.yaml); `usable(field) -> (ok, why)`
    is the caller's say on routes and this session's failures; `plan(field)`
    the run's planned bound in seconds, and `cap_seconds` the owner's
    `combat.bug_run_seconds` -- a field whose bound is over it is skipped
    and says so, so the setting is what decides which fields are too far.
    `measured` is `measured_loot`'s table, (honey a kill, kills, ticket
    kills) per mob; a mob absent from it is priced by the wiki alone.
    """
    from ..brain import mobtable
    measured = dict(measured or {})

    def per_kill(m):
        row = tuple(measured.get(m) or ())
        paid, n, tix = (row + (0.0, 0, 0)[len(row):])[:3]
        wiki = book.mobs[m]
        honey, src = mobtable.blend(wiki.honey, float(paid) * int(n), int(n))
        rate, _ = mobtable.blend(wiki.ticket_chance, int(tix), int(n))
        return honey + rate * TICKET_HONEY, src
    now = float(now if now is not None else time.time())
    quest = dict(quest or {})
    required = dict(required or {})
    skipped = []
    ranked = []
    for where in book.profiles:
        due = due_mobs(book, log, settings, where, now, quest=quest)
        if not due:
            continue
        need = sum(int(quest.get(m, 0) or 0) for m in due)
        if only_quest and need <= 0:
            continue
        pretty = where.replace("_", " ")
        gate = int(required.get(where, 0) or 0)
        if gate and bees < gate:
            skipped.append(f"{pretty}: needs {gate} bees, {bees} known")
            continue
        if usable is not None:
            try:
                ok, why = usable(where)
            except Exception as exc:
                ok, why = False, f"could not check it ({exc})"
            if not ok:
                skipped.append(f"{pretty}: {why}")
                continue
        plan_s = 0.0
        if plan is not None:
            try:
                plan_s = float(plan(where) or 0.0)
            except Exception:
                plan_s = 0.0
        if cap_seconds and plan_s > cap_seconds:
            skipped.append(f"{pretty}: a run there can take {plan_s:.0f}s, over "
                           f"the {cap_seconds:.0f}s a run may (combat.bug_run_seconds)")
            continue
        points = sum(book.mobs[m].battle_points * book.mobs[m].count_in(where)
                     for m in due)
        honey = sum(book.mobs[m].honey * book.mobs[m].count_in(where) for m in due)
        share, runs, run_kills = run_yield(
            log, where, due, sum(book.mobs[m].count_in(where) for m in due))
        loot = share * sum(per_kill(m)[0] * book.mobs[m].count_in(where) for m in due)
        rate = loot / plan_s if plan_s > 0 else loot
        owed = share * sum(book.mobs[m].count_in(where) for m in due
                           if int(quest.get(m, 0) or 0) > 0)
        owed_rate = owed / plan_s if plan_s > 0 else owed
        names = ", ".join(book.mobs[m].name for m in due)
        priced = "; ".join(f"{book.mobs[m].name} {per_kill(m)[0]:,.0f} a kill "
                           f"({per_kill(m)[1]})" for m in due)
        why = (f"{names} due in {pretty}"
               + (f", and a quest still wants {need}" if need > 0 else "")
               + f" — drops worth about {loot:,.0f} honey ({priced}; "
                 f"tickets at {TICKET_HONEY:,}"
               + (f"; runs here found {run_kills} kill(s) in {runs}, so "
                  f"{share:.0%} of the wiki's count" if runs else "")
               + f"), {points} battle point(s)"
               + (f", a run of at most {plan_s:.0f}s" if plan_s else ""))
        ranked.append(((need > 0, owed_rate, rate, points), Choice(
            field=where, mobs=due, quest=need, points=points, honey=honey,
            loot=loot, plan_s=plan_s, why=why)))
    if not ranked:
        return None, skipped
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked[0][1], skipped


# ---- the fight ----------------------------------------------------------------
def turned_keys(keys: str, taps: int) -> str | None:
    """The keys that walk the way `keys` walked before the camera turned
    `taps` (left negative), or None when `taps` is not whole quarter turns.

    `turned_keys("w", -2)` is "d": with the view a quarter turn left, the old
    forward is to the right (module docstring, THE DODGE SQUARE)."""
    taps = int(taps or 0)
    if taps % QUARTER_TAPS:
        return None
    lefts = (-taps // QUARTER_TAPS) % 4
    out = str(keys)
    for _ in range(lefts):
        out = "".join(_QUARTER_LEFT.get(k, k) for k in out)
    return out


def left_on_health(why) -> bool:
    """Did a loot walk stop on our own health (`loot`'s OWN_HEALTH words, at
    the retreat line or on a hit), which the caller answers as it does the
    fight's retreat: a respawn at once?"""
    return str(why or "").startswith(OWN_HEALTH)


class LowHealth:
    """The retreat line, counted only once it has held HP_CONFIRM_SECONDS.

    `saw(hp)` is fed every own-health read: None (no bar drawn, which is
    full health, or a frame it cannot read) and any read over the line end
    the spell; a spell that has lasted the confirm time says leave."""

    def __init__(self, line: float, clock=time.monotonic,
                 hold: float = HP_CONFIRM_SECONDS):
        self.line = float(line)
        self.clock = clock
        self.hold = float(hold)
        self.since: float | None = None
        self.flashes = 0            # spells that ended before they counted

    def saw(self, hp) -> bool:
        if hp is None or float(hp) > self.line:
            if self.since is not None:
                self.flashes += 1
            self.since = None
            return False
        now = self.clock()
        if self.since is None:
            self.since = now
        return now - self.since >= self.hold


class Hits:
    """A fall in the character's own health between two reads: something is
    hitting it, whether or not its bar is in view (HP_HIT_DROP).

    `saw(hp)` is fed every own-health read and says True on a hit. A 0.0 is
    left out: the reader's flashes read 0.0 (LowHealth), and a real death is
    the death watch's. So is a None once a bar has been read -- MEASURED
    (scratchpad bugrun4/hp_none.out) the reader drops to None for 1-8 reads
    (0.5 s at most) around hits and comes back at the level before, or below
    it across a hit, which the next drawn read then counts. A None before
    any drawn read is full health, the game drawing no bar
    (hurt.own_health), so the bar's first appearance below full is a hit
    too: in 11 of the 15 windows where it appeared it read 0.73-0.90 (and
    0.0, a flash, in the other 4)."""

    def __init__(self, drop: float = HP_HIT_DROP):
        self.drop = float(drop)
        self.last: float | None = None
        self.count = 0

    def saw(self, hp) -> bool:
        if hp is None:
            if self.last is None:
                self.last = 1.0
            return False
        hp = float(hp)
        if hp <= 0.0:
            return False
        hit = self.last is not None and hp <= self.last - self.drop
        self.last = hp
        self.count += int(hit)
        return hit


@dataclass
class Fight:
    """What one fight saw. `left` is why it ended:

        killed     the reward feed named every mob the field holds
        gone       a bar was seen and then no bar and no hit for a whole
                   inner loop -- the bars left the detector, which is not a
                   kill until the feed names it (module docstring)
        cap        Natro's longest wait (or the run's own deadline) passed
                   with a bar still coming back
        health     the character's own bar held at the retreat line
        not_found  no bar and no hit in the look loop or the look around
        late       the run's own deadline had passed before it could stand
        stop       the owner, the session or a death asked it to stop
    """
    field: str
    found: bool = False
    left: str = ""
    seconds: float = 0.0
    looks: int = 0
    # How many headings the look for a first bar had (1 + the look around:
    # SWEEP_HEADINGS a sweep, and a field's `sweeps`), for the line it ends on.
    headings: int = 0
    bar_looks: int = 0
    most_bars: int = 0
    # The largest share of a mob bar read as lost (nameplate `tail`): a bar
    # that went after falling is a kill more surely than one that walked off.
    most_depleted: float = 0.0
    rounds: int = 0
    hp_first: float | None = None
    hp_min: float | None = None
    hp_last: float | None = None
    hp_reads: int = 0
    hp_flashes: int = 0
    # Falls in our own health (`Hits`), each counted as a bar seen, and the
    # level the hit watch held at the end (`Hits.last`: the last drawn read
    # above 0, 1.0 for a bar never drawn), which the loot walk's own watch
    # starts from after a "gone" the feed has not confirmed.
    hits: int = 0
    first_hit_after: float | None = None
    hp_level: float | None = None
    # Camera taps the fight left turned for the loot walk, which the caller
    # undoes after it (Natro's Mushroom arrival turn and Rose fight turn); the
    # look around's and the mid-fight turns are undone here.
    keep_turned: int = 0
    # Taps of the look around the first bar showed at: 0 is Natro's own
    # look loop, facing the way the route left the character.
    found_at_taps: int | None = None
    first_bar_after: float | None = None
    last_bar_after: float | None = None
    capped_by_deadline: bool = False
    moves: list = field(default_factory=list)

    @property
    def gone(self) -> bool:
        return self.left == "gone"

    def describe(self) -> str:
        where = self.field.replace("_", " ")
        hp = ""
        if self.hp_min is not None:
            hp = f"; own health low {self.hp_min:.0%}, last {self.hp_last:.0%}"
        if self.hp_flashes:
            hp += f" ({self.hp_flashes} read(s) at the line that did not hold)"
        if self.left == "not_found":
            return (f"{where}: no mob health bar and no hit on us in "
                    f"{self.looks} look(s) over "
                    f"{self.headings or SWEEP_HEADINGS} heading(s), "
                    f"{self.seconds:.1f}s{hp}")
        verdict = {
            "killed": "the reward feed named every mob here as defeated",
            "gone": ("the bars left the detector and no hit came for a whole "
                     "inner loop (not a kill unless the feed names it)"),
            "cap": ("the run's own deadline came with a bar still showing"
                    if self.capped_by_deadline else
                    "Natro's longest wait here ran out with a bar still coming back"),
            "health": "left at the retreat line on our own health",
            "late": "the run's own time was up before it could stand",
            "stop": "stopped",
        }.get(self.left, self.left)
        seen = (f"a bar {self.first_bar_after:.1f}s in"
                + (f" ({abs(self.found_at_taps) * 45} degrees round)"
                   if self.found_at_taps else "")
                + f", last {self.last_bar_after:.1f}s in"
                if self.first_bar_after is not None else "no bar")
        if self.hits:
            seen += (f", {self.hits} hit(s) on us, the first "
                     f"{self.first_hit_after:.1f}s in")
        depleted = (f", a bar down to {1 - self.most_depleted:.0%}"
                    if self.most_depleted > 0.05 else "")
        return (f"{where}: {verdict} — {seen}, {self.bar_looks} of "
                f"{self.looks} looks with a bar, up to {self.most_bars} at "
                f"once{depleted}, {self.rounds} round(s), "
                f"{self.seconds:.1f}s{hp}")


def fight(profile: Profile, *, frames, find=None, health=None, turn=None,
          hold=None, snap=None, sleep=time.sleep, clock=time.monotonic,
          stopped=lambda: False, retreat: float = 0.35,
          walkspeed: float = 28.0, deadline: float | None = None,
          all_killed=lambda: False, sweep: bool = True,
          dead=lambda: False, on_note=lambda text: None) -> Fight:
    """Stand in the field and let the bees kill what comes, Natro's way.

    `frames()` is a capture; `find(frame)` the hostile bars (nameplate.find);
    `health(frame)` the character's own bar, 0..1 or None when the game is
    not drawing it (hurt.own_health); `turn(taps)` turns the camera, left
    negative, and tells the compass; `hold(keys, studs)` walks one timed
    hold; `snap(label)` keeps the frame for whoever reads the run later;
    `deadline` (on `clock`) is the run's own end, which shortens Natro's
    wait when the walk out took long and, once passed, ends the run before
    it stands (`late`); `all_killed()` is True once the reward feed has
    named every mob the field holds; `dead()` is True once a death has been
    seen, after which no turn is undone: the respawn has already put the
    camera at spawn heading and told the compass (run_farm `on_death`).

    Presses nothing but the camera keys and the arrival and dodge holds.
    """
    find = find or nameplate.find
    health = health or hurt.own_health
    snap = snap or (lambda label: None)
    out = Fight(field=profile.field)
    began = clock()
    low = LowHealth(retreat, clock=clock)
    hits = Hits()

    def look():
        try:
            frame = frames()
        except Exception:
            frame = None
        out.looks += 1
        bars = []
        hp = None
        if frame is not None:
            try:
                bars = list(find(frame))
            except Exception:
                bars = []
            try:
                read = health(frame)
                hp = None if read is None else float(getattr(read, "fraction", read))
            except Exception:
                hp = None
        if bars:
            out.bar_looks += 1
            out.most_bars = max(out.most_bars, len(bars))
            try:
                out.most_depleted = max(out.most_depleted, max(
                    float(getattr(b, "tail", 0.0) or 0.0) for b in bars))
            except (TypeError, ValueError):
                pass
            at = clock() - began
            if out.first_bar_after is None:
                out.first_bar_after = at
            out.last_bar_after = at
        if hp is not None:
            out.hp_reads += 1
            if out.hp_first is None:
                out.hp_first = hp
            out.hp_min = hp if out.hp_min is None else min(out.hp_min, hp)
            out.hp_last = hp
        hit = hits.saw(hp)
        if hit:
            out.hits += 1
            if out.first_hit_after is None:
                out.first_hit_after = clock() - began
        leave = low.saw(hp)
        out.hp_flashes = low.flashes
        return bars, leave, hit

    def late() -> bool:
        return deadline is not None and clock() >= float(deadline)

    def turn_by(taps: int) -> int:
        try:
            gone = bool(dead())
        except Exception:
            gone = False
        if not taps or turn is None or gone:
            return 0
        try:
            turn(int(taps))
            return int(taps)
        except Exception:
            return 0

    def done(why: str) -> Fight:
        out.left = why
        out.seconds = clock() - began
        out.hp_level = hits.last
        try:
            snap(f"bugrun-{profile.field}-{why}")
        except Exception:
            pass
        return out

    # Turns undone before this returns: the look around's, kept for the fight
    # so the bar it found stays in view, the mid-fight quiet-spell turn, and
    # a dodge hold's turn back to Natro's frame if the hold did not return.
    undo = {"sweep": 0, "mid": 0, "dodge": 0}
    try:
        if late():
            return done("late")
        # ARRIVING, Natro's way: its loot legs are laid out in the frame
        # these steps leave (Strawberry's pause, Mushroom's turn, Rose's two
        # walks).
        for step in profile.arrive:
            step = step or {}
            if stopped():
                return done("stop")
            if "pause_s" in step:
                sleep(float(step.get("pause_s") or 0.0))
            elif "turn" in step:
                out.keep_turned += turn_by(int(step.get("turn") or 0))
            elif "walk" in step and hold is not None:
                try:
                    keys, tiles = str(step["walk"][0]), float(step["walk"][1])
                except (TypeError, ValueError, IndexError, KeyError):
                    continue
                hold(keys, tiles * STUDS_PER_TILE)
                out.moves.append((keys, tiles * STUDS_PER_TILE))

        # LOOKING for a first bar: Natro's `loop 20 { ...; Sleep 150 }`,
        # then the look around (module docstring), one heading at a time.
        headings = [(0, max(1, profile.look_tries), profile.look_every)]
        if sweep and turn is not None:
            headings += [(-SWEEP_TAPS, profile.sweep_looks(), profile.every)
                         for _ in range(SWEEP_HEADINGS * max(1, int(profile.sweeps)) - 1)]
        out.headings = len(headings)
        for taps, tries, every in headings:
            if late():
                return done("late")
            if taps:
                undo["sweep"] += turn_by(taps)
            for _ in range(tries):
                if stopped():
                    return done("stop")
                if late():
                    return done("late")
                bars, leave, hit = look()
                if leave:
                    return done("health")
                if bars or hit:
                    out.found = True
                    out.found_at_taps = undo["sweep"]
                    break
                sleep(every)
            if out.found:
                break
        if not out.found:
            return done("not_found")
        try:
            snap(f"bugrun-{profile.field}-found")
        except Exception:
            pass
        cap = profile.cap_seconds(walkspeed)
        if deadline is not None:
            left_s = max(0.0, float(deadline) - clock())
            if left_s <= 0.0:
                return done("late")
            if left_s < cap:
                cap = left_s
                out.capped_by_deadline = True
        pretty = profile.field.replace("_", " ")
        on_note((f"a mob health bar in {pretty} {out.first_bar_after:.1f}s in"
                 if out.first_bar_after is not None else
                 f"no bar in view in {pretty}, but our own health fell "
                 f"{out.first_hit_after:.1f}s in: something is hitting us")
                + (f", {abs(undo['sweep']) * 45} degrees round" if undo["sweep"] else "")
                + f" — standing for the bees, up to {cap:.0f}s ("
                + ("what is left of the run's own time"
                   if out.capped_by_deadline else
                   f"Natro's longest wait here, {profile.source}") + ")")
        if profile.fight_turn:
            out.keep_turned += turn_by(profile.fight_turn)

        # WAITING: rounds of looks, each round ending at the first bar it
        # sees, the fight ending when one whole round sees none.
        wait_began = clock()
        while True:
            out.rounds += 1
            if profile.dodge_keys and hold is not None:
                keys = profile.dodge_keys[(out.rounds - 1) % len(profile.dodge_keys)]
                studs = profile.dodge_tiles * STUDS_PER_TILE
                # IN NATRO'S FRAME (module docstring): the key turned back by
                # the look around's and the quiet-spell turns, so the camera
                # stays on the bar. `moves` keeps Natro's key.
                extra = undo["sweep"] + undo["mid"]
                walk = turned_keys(keys, extra)
                if walk is not None:
                    hold(walk, studs)
                else:
                    # Not whole quarter turns (SWEEP_TAPS changed): turn back
                    # for the hold and forth after, whatever it costs.
                    undo["dodge"] = turn_by(-extra)
                    try:
                        hold(keys, studs)
                    finally:
                        if undo["dodge"]:
                            undo["dodge"] += turn_by(-undo["dodge"])
                out.moves.append((keys, studs))
            absent = 0
            saw = False
            while absent < max(1, profile.looks):
                if stopped():
                    return done("stop")
                if all_killed():
                    return done("killed")
                if clock() - wait_began >= cap:
                    return done("cap")
                bars, leave, hit = look()
                if leave:
                    return done("health")
                # A HIT IS A BAR (module docstring): a mob too close for the
                # detector is still here, so the quiet spell starts again.
                if bars or hit:
                    saw = True
                    break
                absent += 1
                if (profile.turn_at and absent == profile.turn_at
                        and not undo["mid"]):
                    undo["mid"] = turn_by(-SWEEP_TAPS)
                if absent < profile.looks:
                    sleep(profile.every)
            if not saw:
                return done("killed" if all_killed() else "gone")
            # Natro starts its next round at detection speed; the same pace
            # here would spin at ~70 looks a second (13 ms a look), so the
            # looks keep the field's own spacing.
            #
            # AND ITS ROUND COUNT IS NOT A CLOCK HERE. Natro ends after N
            # rounds, each as long as one of its looks takes, so with a bar
            # in view its fight lasts N looks and its loot walk finishes the
            # job. Counting rounds at this bot's look speed would stand for a
            # few seconds at a spider; the bound is the time Natro can stand
            # (`cap`), and a bar that goes ends it sooner.
            sleep(profile.every + profile.round_pause)
    finally:
        back = -(undo["sweep"] + undo["mid"] + undo["dodge"])
        # THE SHORT WAY ROUND: eight 45-degree taps are a whole turn, so the
        # same heading is never more than four away. Two circles of the look
        # around (a field's `sweeps`) would otherwise turn back 14 taps.
        back = (back + 4) % 8 - 4
        if back:
            turn_by(back)


def loot_steps(profile: Profile, last_round: int = 0) -> list:
    """Natro's loot walk for this field as route steps (walk ops in studs).

    After a dodge square it starts with the two legs Natro picks from the
    last round's index mod 4 (`loot_after_dodge`)."""
    legs = []
    if profile.dodge_keys and last_round > 0:
        legs.extend(profile.loot_after_dodge.get(int(last_round) % 4, ()))
    legs.extend(profile.loot)
    return [{"op": "walk", "keys": keys, "studs": round(tiles * STUDS_PER_TILE, 2)}
            for keys, tiles in legs]


def loot(profile: Profile, last_round: int = 0, *, hold, frames=None,
         health=None, stopped=lambda: False, retreat: float = 0.35,
         deadline: float | None = None, clock=time.monotonic,
         watch_hits: bool = False, hp_before=None) -> tuple:
    """Walk Natro's loot legs one at a time; (walked it all, why it stopped).

    Leg by leg rather than as one route because the route runner's watch
    reads deaths and dialogues but not the character's own health, and a
    fight that ran out (`cap`) leaves a mob on the field that the walk passes
    through. The health bar is read before every leg -- the longest is 18
    tiles, 72 studs, 2.6 s at walkspeed 28 -- and the walk ends once the
    reads hold at the retreat line (`LowHealth`), as the fight does, or when
    the run's own `deadline` has passed.

    `watch_hits` is for a fight that ended "gone" with the feed not naming
    its mobs: the walk also ends on a hit (`Hits`, from `hp_before`, the
    fight's `hp_level`), before the first leg as before any other -- on
    233202's frames the scorpions' bars left the detector at 0.1 s and their
    first hit came at 2.0 s. Both health stops start with OWN_HEALTH
    (`left_on_health`), which the caller answers as it does the fight's
    retreat: a respawn at once.
    """
    health = health or hurt.own_health
    low = LowHealth(retreat, clock=clock)
    hits = None
    if watch_hits:
        hits = Hits()
        hits.saw(hp_before)
    for step in loot_steps(profile, last_round):
        if stopped():
            return False, "stopped"
        if deadline is not None and clock() >= float(deadline):
            return False, "the run's own time (combat.bug_run_seconds) ran out"
        if frames is not None:
            try:
                read = health(frames())
                hp = None if read is None else float(getattr(read, "fraction", read))
            except Exception:
                hp = None
            if low.saw(hp):
                return False, f"{OWN_HEALTH} {float(hp):.0%}, {RETREATED}"
            was = hits.last if hits is not None else None
            if hits is not None and hits.saw(hp):
                return False, (f"{OWN_HEALTH} fell {float(was):.0%} -> "
                               f"{float(hp):.0%} after bars the feed has not "
                               f"confirmed gone: {HIT_AGAIN}")
        hold(step["keys"], step["studs"])
    return True, ""


# ---- the reward feed -----------------------------------------------------------
# A DROP, AS THE GAME SAYS IT: "+1 Honeysuckle (from Ladybug)", "+170 Bond
# (from Ladybug)" -- MEASURED on var/routes/attempt-595/171027-bugrun-
# strawberry-gone.jpg (2026-10-02 17:10, two Ladybugs). A "(from ...)" that
# names a field is a field's credit, not a drop: only mobs in the book count.
# AS TESSERACT READS IT, NOT AS IT IS DRAWN. MEASURED 2026-10-03 on the feed
# of var/loot_misses/20261003-030153-*.jpg: "+580 Honey (from Rhino Beetle)"
# reads "1580 Honey (from Rhino Beetle)" -- the plus as a 1 -- and "Honëx"
# for Honey; vision/feed already takes "rom" for "from" (whereami.FROM). A
# leading 1 glued to the number is that plus and is dropped (a real "+1,155"
# reads "11,155": the 1,155 is kept), an item may hold any letter, and the
# pattern found no drop at all in a week of runs without these.
# AN ITEM OF MORE THAN ONE WORD: its words joined by a space, a quote or a
# hyphen -- written once inside a negated class, where the space barred
# itself, so "+1 Royal Jelly (from Sprout)" matched nothing (2026-10-03 06:57)
# and no two-word drop was ever logged.
DROPPED = re.compile(r"(?:\+\s?|(?<![\w,])1(?=\d))?([\d,]+)\s+"
                     r"([^\W\d_](?:[^\W\d_]|[ '-](?=[^\W\d_])){1,30}?)\s*"
                     r"\(\s*f?rom\s+([A-Za-z][A-Za-z' ]{2,30}?)\s*\)", re.IGNORECASE)


class FeedDrops:
    """New "+N <Item> (from <Mob>)" lines, counted once however often a read
    sees them -- FeedKills' own rule, per (item, amount, mob) line -- so what
    each kill drops is MEASURED, not taken from the wiki's tiers."""

    def __init__(self, book: Book, clock=time.monotonic,
                 line_seconds: float = FEED_LINE_SECONDS, extras: dict | None = None):
        self.book = book
        self.clock = clock
        self.line_seconds = float(line_seconds)
        self._lines: dict = {}          # (item, amount, mob) -> [first seen, most copies]
        # sources that are no mob but drop all the same: {"sprout": "sprout"}
        # ("+1 Royal Jelly (from Sprout)", a Magic Bean's, 2026-10-03 06:57)
        self.extras = dict(extras or {})

    def seen(self, text: str) -> list:
        """[(mob slug, item, amount)] for the drop lines new in this read."""
        now = self.clock()
        counts: dict = {}
        for m in DROPPED.finditer(str(text or "")):
            source = " ".join(m.group(3).lower().split())
            slug = self.book.slug_for(source) or self.extras.get(source)
            if not slug:
                continue
            try:
                amount = int(m.group(1).replace(",", ""))
            except ValueError:
                continue
            item = " ".join(m.group(2).lower().split())
            key = (item, amount, slug)
            counts[key] = counts.get(key, 0) + 1
        new = []
        # an expired line is a new line anyway; dropping it keeps the memo
        # to the lines on screen (every amount was a new key, kept forever)
        for key in [k for k, memo in self._lines.items()
                    if now - memo[0] > self.line_seconds]:
            del self._lines[key]
        for key, n in counts.items():
            memo = self._lines.get(key)
            if memo is None or now - memo[0] > self.line_seconds:
                extra = n
                self._lines[key] = [now, n]
            else:
                extra = n - memo[1]
                memo[1] = max(memo[1], n)
            item, amount, slug = key
            new.extend([(slug, item, amount)] * max(0, extra))
        return new


class FeedKills:
    """New "Defeated <Name>!" lines, counted once however often a read sees them.

    The feed is read every few seconds (vision/whereami.Tracker) and a kill
    line stays on it for about nine (FEED_LINE_SECONDS), so the same line is
    usually read twice. For each mob name this keeps when its line was first
    seen and the most copies any read has shown since: within the line's
    lifetime only copies beyond that most are new kills (two ladybugs dying
    together are two lines and count twice), and a read that drops the line
    and the next that shows it again still count it once. Past the lifetime
    every copy is a new kill. A kill whose line appears while an earlier one
    of the same name is still drawn is missed -- the undercount is the safe
    direction, because a kill booked that did not happen skips a live mob.
    """

    def __init__(self, book: Book, clock=time.monotonic,
                 line_seconds: float = FEED_LINE_SECONDS):
        self.book = book
        self.clock = clock
        self.line_seconds = float(line_seconds)
        self._lines: dict = {}          # name -> [first seen at, most copies]
        self.other: dict = {}           # names that are not in the book
        self.counted = 0

    def seen(self, text: str) -> list:
        now = self.clock()
        counts: dict = {}
        for m in DEFEATED.finditer(str(text or "")):
            name = " ".join(m.group(1).lower().split())
            counts[name] = counts.get(name, 0) + 1
        new = []
        for name, n in counts.items():
            memo = self._lines.get(name)
            if memo is None or now - memo[0] > self.line_seconds:
                extra = n
                self._lines[name] = [now, n]
            else:
                extra = n - memo[1]
                memo[1] = max(memo[1], n)
            if extra <= 0:
                continue
            slug = self.book.slug_for(name)
            if slug:
                new.extend([slug] * extra)
                self.counted += extra
            else:
                self.other[name] = self.other.get(name, 0) + extra
        return new


# ---- loot by sight -----------------------------------------------------------
# THE OWNER, 2026-10-02: after a kill the bot did not walk to the dropped
# tokens to collect them, as if it could not see them. It could see
# them -- vision/coins finds tokens, act/chase walks to one -- but the loot
# was Natro's fixed legs (`loot`), walked blind from where the fight was
# assumed to be. A mob drops where it dies. So first the coins in view are
# chased one after another, nearest first, until none is seen twice in a row,
# LOOT_SIGHT_CHASES have run, or LOOT_SIGHT_SECONDS have passed; Natro's legs
# then sweep what was out of view.
LOOT_SIGHT_SETTING = "combat.loot_by_sight"
LOOT_SIGHT_SECONDS = 12.0
LOOT_SIGHT_CHASES = 6
LOOT_SIGHT_EMPTY_LOOKS = 2


@dataclass
class SightLoot:
    chases: int = 0
    walked: int = 0
    arrived: int = 0
    seconds: float = 0.0
    reason: str = ""
    notes: list = field(default_factory=list)

    def describe(self) -> str:
        if not self.chases:
            return f"no loot chased by sight: {self.reason}"
        return (f"chased {self.walked} token(s) by sight, walked onto {self.arrived}, "
                f"in {self.seconds:.0f}s ({self.reason})")


def loot_by_sight_wanted(settings) -> bool:
    try:
        return bool(settings.bool(LOOT_SIGHT_SETTING))
    except Exception:
        return True


def loot_by_sight(chase_one, *, stopped=lambda: False, clock=time.monotonic,
                  deadline: float | None = None,
                  seconds: float = LOOT_SIGHT_SECONDS,
                  chases: int = LOOT_SIGHT_CHASES) -> SightLoot:
    """Chase the coins in view after a kill. `chase_one()` is one act/chase
    detour (it looks, walks to the nearest coin it trusts and back) and
    returns its ChaseResult; this decides when to stop."""
    out = SightLoot()
    began = clock()
    end = began + float(seconds)
    if deadline is not None:
        end = min(end, float(deadline))
    empty = 0
    while True:
        if stopped():
            out.reason = "stopped"
            break
        if clock() >= end:
            out.reason = "its time was up"
            break
        if out.chases >= chases:
            out.reason = f"{chases} chases"
            break
        try:
            got = chase_one()
        except Exception as exc:
            out.reason = f"a chase failed ({exc})"
            break
        out.chases += 1
        if getattr(got, "walked", False):
            out.walked += 1
            out.arrived += int(bool(getattr(got, "arrived", False)))
            empty = 0
            try:
                out.notes.append(got.describe())
            except Exception:
                pass
        else:
            empty += 1
            if empty >= LOOT_SIGHT_EMPTY_LOOKS:
                out.reason = "no token in view twice in a row"
                break
    out.seconds = clock() - began
    return out

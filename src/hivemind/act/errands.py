"""Going somewhere recorded, and using what is there — or refusing to.

WHAT THIS UNLOCKS. `data/world/paths.yaml` already contains routes from the
hive to the Wealth Clock, the three Field Boosters and three Dispensers. Every
one of those is free income or a direct buff to the gathering rate, and the
settings have had switches for all three groups since the beginning with
nothing behind them. The routes were expected to be the hard part; they are
not, because they already exist.

THE PART THAT IS NOT FREE IS THE KEYPRESS. `e` is the interact key for
everything in this game: it converts pollen at a hive, opens shops, and starts
NPC conversations. This project has already opened a Polar Bear quest dialogue
by pressing it where it believed the hive was, and has a standing rule against
pressing keys at screens it cannot read. So an errand here is two separate
claims, and the second is never assumed from the first:

    1. the route ran            -- which a timed walk can always say
    2. the right thing is in front of us -- which only the panel can say

`expect` is the words the game's own top-centre panel must contain before
anything is pressed. If the panel says something else, or says nothing, the
errand reports what it saw and presses NOTHING. That failure is useful: run
with `press=False` and this becomes a recon tool that walks to a place and
writes down what the panel there actually says, which is how `expect` gets
filled in honestly rather than guessed.

WHAT IT DELIBERATELY DOES NOT DO. It does not retry, it does not hunt for the
thing nearby, and it does not press twice. A dispenser that is on cooldown
looks exactly like a dispenser whose panel we misread, and the safe response to
both is to walk away and say so.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# The interact key, cited from BeeTuxMacro and shared with act/hive so there is
# one definition of "the key that does things".
INTERACT_KEY = "e"

# How long to let the panel settle after arriving, and after pressing.
SETTLE_SECONDS = 1.0

# WHY NOTHING WAS PRESSED when the owner's Pause or Take Over held the E back
# (`run_errand`): the panel had confirmed the place, so the route arrived and
# the place did nothing wrong. Callers tell it apart by this exact reason.
HELD_BACK = ("the E was held back by the owner's Pause or Take Over — nothing "
             "was pressed")

# HOW MANY TIMES THE PANEL IS READ AFTER A PRESS, a SETTLE_SECONDS apart,
# stopping at the first that shows the machine's timer. One read was all it
# had, and MEASURED over the saved run logs (attempts 346-402) it showed the
# timer on 4 of the 10 dispenser presses -- "(3:59:59)" twice at the
# blueberry, "(59:59)" twice at the treat -- and nothing to go on for the
# other six, each of which was then booked as a full period (audit errands
# F8). Three is the audit's number; every read is kept (`read_back`) and
# logged, so the next live run says when the timer appears.
AFTER_PRESS_READS = 3


@dataclass
class Errand:
    """One place worth visiting, and how to know we are actually there."""
    name: str                       # router node, e.g. "wealth_clock"
    expect: tuple = ()              # words the panel must contain, lowercased
    gives: str = ""                 # what it is for, for the log
    every_hours: float = 0.0        # 0 means "whenever asked"
    # THE BEE GATE in front of the place, from `errands.yaml` (0: none known),
    # and anything else known to keep this account out, in words (see `gate`).
    bees_required: int = 0
    blocked: str = ""
    # A FIELD BOOSTER'S FIELDS and the pollen share each gets (1.0 is +100%),
    # and the fields among them that need more bees before they can be picked.
    # Empty for everything that is not a booster. See `booster_worth`.
    boosts: dict = field(default_factory=dict)
    boost_needs_bees: dict = field(default_factory=dict)
    # THE PLACE'S OWN WORDS FOR "NOTHING TO GIVE YOU", lowercased: the route
    # arrived and the machine is full up, so nothing is pressed and it is a
    # visit, not a miss (`run_errand`). From `errands.yaml` `full`.
    full: tuple = ()

    def is_full(self, text: str) -> bool:
        low = " ".join((text or "").lower().split())
        return any(word in low for word in self.full)

    def matches(self, text: str) -> bool:
        """Does the panel say what this errand expects? Empty expect = never.

        An errand with nothing to match on cannot be confirmed, and is treated
        as unconfirmable rather than as always-true. That is what keeps a
        half-filled table from pressing keys at random scenery.
        """
        if not self.expect:
            return False
        low = " ".join((text or "").lower().split())
        return any(word in low for word in self.expect)


@dataclass
class ErrandResult:
    """What happened. `used` is the only claim that means a key was pressed."""
    name: str = ""
    walked: bool = False
    saw: str = ""
    used: bool = False
    reason: str = ""
    readings: list = field(default_factory=list)
    # THE MACHINE'S OWN TIMER, when its panel showed one. `cooling` is the
    # seconds left on arrival -- nothing is pressed then -- and `next_in` is
    # the timer read back after a press, which is both the confirmation the
    # press did something and the next deadline. See `countdown_seconds`.
    cooling: float | None = None
    # The panel said the machine has nothing to give (`Errand.full`).
    full: bool = False
    next_in: float | None = None
    # When the arrival read, the press and the read-back happened, so the
    # caller can turn a countdown into a deadline without guessing the gaps.
    saw_at: float = 0.0
    pressed_at: float = 0.0
    after_at: float = 0.0
    # Every read taken after the press, in order (AFTER_PRESS_READS).
    read_back: list = field(default_factory=list)

    def describe(self) -> str:
        if self.used and self.next_in is not None:
            return (f"{self.name}: used it — the panel then showed its timer, "
                    f"{_clock(self.next_in)} until the next one")
        if self.used:
            # WHAT THE READ-BACK SAID, not only what was pressed at: a press
            # with no timer after it is a use nobody has confirmed, and the
            # log could not tell a panel that went blank from one that stayed
            # the same (audit errands F8).
            after = [r for r in self.read_back if r] or ["nothing"]
            return (f"{self.name}: used it (panel read {self.saw!r}) — no timer "
                    f"read back; after the press it read "
                    f"{' / '.join(repr(r) for r in after)}, and {self.reason}")
        if self.full:
            return f"{self.name}: arrived and full — {self.reason}"
        if self.cooling is not None:
            return (f"{self.name}: cooling down, {_clock(self.cooling)} left "
                    f"on its own timer — nothing pressed")
        if not self.walked:
            return f"{self.name}: did not get there — {self.reason}"
        if self.saw:
            return f"{self.name}: arrived, panel read {self.saw!r} — {self.reason}"
        return f"{self.name}: arrived, no panel — {self.reason}"


# Words that name a place but never appear in its node name, so a panel can
# still be recognised. Kept short and explicit: a fuzzy match here would be a
# licence to press E at anything.
ALSO_CALLED = {
    "wealth_clock": ("wealth", "clock"),
    "blueberry_dispenser": ("blueberry", "blueberries"),
    "strawberry_dispenser": ("strawberry", "strawberries"),
    "treat_dispenser": ("treat", "treats"),
    "coconut_dispenser": ("coconut", "coconuts"),
    "glue_dispenser": ("glue",),
    "royal_jelly_dispenser": ("royal jelly", "jelly"),
    "honey_dispenser": ("honey dispenser",),
    "blender": ("blender",),
    # THE THREE FIELD BOOSTERS, in the wiki's own names (Blue_Field_Booster,
    # Red_Field_Booster, Field_Booster). The mountain one is just "Field
    # Booster", which is also the tail of the other two -- `_named_in` lets
    # the longer name win, so a blue booster's panel never passes for it.
    "blue_field_booster": ("blue field booster",),
    "red_field_booster": ("red field booster",),
    "white_field_booster": ("field booster",),
    # THE FREE ANT PASS DISPENSER, by the one word its neighbours would not
    # say (wiki Free_Ant_Pass_Dispenser). Two other prompts stand within a
    # few studs and neither panel has been read: the ticket Ant Pass
    # Dispenser to its right (wiki Ant_Pass_Dispenser; "spend"/"ticket" are
    # in NEVER_PRESS too), and the Ant Challenge's entrance, 12 studs
    # diagonally and 4 forward, where E spends a pass and starts the
    # challenge (natro_macro.ahk:12006-12020, nm_Ant). "Ant pass" alone --
    # "Use an Ant Pass", say -- could be the entrance, so it is not enough
    # (the routes branch kept the place read-only for this, DESIGN 8dr). A
    # free dispenser whose panel does not say "free" is read and never
    # pressed, and the log says what it did say.
    "ant_pass": ("free ant pass",),
    # THE STICKER STACK, read only: its menu stacks a sticker or spends 25
    # tickets (wiki Sticker_Stack), so it is not in FREE_TO_USE.
    "sticker_stack": ("sticker stack",),
    # X4/X3 (LOOK_ONLY below), the wiki's names; neither panel read yet.
    "honeystorm": ("honeystorm",),
    "sticker_printer": ("sticker printer",),
}

# Panels that must NEVER become an `expect`, whatever place they were read at.
# `Open Shop` is one keypress from spending the owner's honey, which is the
# only action in this game that cannot be undone. MEASURED 2026-09-23 04:10:
# the recon walked `natro_out_honey_dispenser`, four steps off the pad, and
# the panel there said `Open Shop` -- so a route named after a dispenser can
# land at a shop counter, and copying what it read into `expect` would have
# pointed the errand engine at a till.
#
# AND "spend": the Royal Jelly Dispenser's panel reads "Spend 6 Tickets to Use
# the Royal Jelly Dispenser" (var/live_run13.log:27), which names its place --
# so it passed `expect_from_panel` for royal_jelly_dispenser and E would have
# spent the owner's tickets unattended. No route reaches it today (Natro's is
# cannon-only); this keeps it that way whatever route is added.
#
# AND "ticket", for any other press that pays in tickets. The Ant Pass
# Dispenser sells a pass for 10 tickets beside the free one (wiki
# Ant_Pass_Dispenser), and Natro buys one with a single E (natro_macro.ahk:
# 12062-12067); the same panel reading (var/vlm_cache/69/69a74e3b...d281.txt
# is the Royal Jelly one) says "Tickets". Tickets are the owner's currency.
NEVER_PRESS = ("open shop", "claim hive", "buy", "purchase", "sell", "spend",
               "ticket")

# THE PLACES WHERE ONE PRESS OF E IS FREE, and the only ones `use` may press
# at. A veto list says what must not be pressed; this says what may, so a
# place added to the route table later is walked to and READ, never used,
# until it is written in here with its evidence. Each is a single press with
# nothing spent, in Natro's own collect code and on the wiki page named:
#
#   wealth_clock          nm_Clock (natro_macro.ahk:11718), wiki Wealth_Clock
#   honey/treat/blueberry/strawberry/coconut/glue dispensers
#                         nm_HoneyDis, nm_TreatDis, nm_BlueberryDis,
#                         nm_StrawberryDis, nm_CoconutDis, nm_GlueDis
#                         (12150-12339), wiki <Name>_Dispenser
#   ant_pass              nm_Ant's first press (11974-11980), wiki
#                         Free_Ant_Pass_Dispenser ("free ... every 2 hours")
#   the three boosters    nm_toBooster (13599), wiki Blue_Field_Booster,
#                         Red_Field_Booster, Field_Booster
#
# NOT HERE, ON PURPOSE: the Royal Jelly Dispenser (6 tickets a press, wiki
# Royal_Jelly_Dispenser; the free one is in the Star Hall with no route), the
# Blender (its menu crafts, which spends ingredients), the Wind Shrine (a
# donation) and the Memory Matches (25,000 honey a game and up, wiki
# Memory_Match). Those may be read; nothing is pressed at them unattended.
#
# AND NOT THE BEESMAS MACHINES YET. They spend nothing (DESIGN 8dc), but what
# they give lands on the ground in front of them: Natro walks a loot pattern
# after every press (nm_Wreath 12386-12399, nm_Stockings 12466-12489,
# nm_Samovar 12669-12682) and this bot respawns home instead, so a press
# would start the machine's cooldown and leave its payout on the floor. They
# are read with `economy.beesmas` on; pressing waits for the loot walk.
FREE_TO_USE = frozenset({
    "wealth_clock", "honey_dispenser", "treat_dispenser",
    "blueberry_dispenser", "strawberry_dispenser", "coconut_dispenser",
    "glue_dispenser", "ant_pass",
    "blue_field_booster", "red_field_booster", "white_field_booster",
    # THE TWO BEESMAS MACHINES WHOSE LOOT PASS IS PLAIN WALKING (LOOT_WALKS);
    # the Stockings' pass jumps on Natro's timing and waits for it.
    "honey_wreath", "samovar",
})

# THE PASS OVER A BEESMAS MACHINE'S PAYOUT, Natro's own after its press
# (natro_macro.ahk nm_Wreath 12369: Sleep 4000, then the rows; nm_Samovar
# 12648: Sleep 5000, then the rows), in Natro's walk units of 4 studs and its
# keys as the machine's route leaves the camera. run_farm walks it straight
# after a press that took, before the respawn home.
def _rows(first: str, step: str, back: str, n: int = 3) -> tuple:
    out = ()
    for _ in range(n):
        out += ({"op": "walk", "keys": first, "studs": 24.0},
                {"op": "walk", "keys": step, "studs": 5.0},
                {"op": "walk", "keys": back, "studs": 24.0},
                {"op": "walk", "keys": step, "studs": 5.0})
    return out


LOOT_WALKS = {
    "honey_wreath": ((
        {"op": "pause", "seconds": 4.0},
        {"op": "walk", "keys": "s", "studs": 4.0},
        {"op": "walk", "keys": "sa", "studs": 18.0},
        {"op": "walk", "keys": "a", "studs": 4.0})
        + _rows("w", "d", "s")
        + ({"op": "walk", "keys": "w", "studs": 24.0},)),
    "samovar": ((
        {"op": "pause", "seconds": 5.0},
        {"op": "walk", "keys": "wd", "studs": 16.0},
        {"op": "walk", "keys": "d", "studs": 4.0})
        + _rows("s", "a", "w")
        + ({"op": "walk", "keys": "s", "studs": 24.0},)),
}


def free_to_use(place: str) -> bool:
    """May E be pressed at this place at all? See FREE_TO_USE."""
    return str(place) in FREE_TO_USE


# X4 THE HONEYSTORM AND X3 THE STICKER PRINTER: PRICED, LOOK-ONLY. Their
# routes are Natro's (natro_out_honeystorm, natro_out_sticker_printer in
# data/world/natro_paths.yaml) and have never been walked by this bot, neither
# panel has been read, and the printer's egg menu has no measured frame. So
# neither is in FREE_TO_USE nor in run_farm's PLACE_ROUTES (no recon walks
# there either): with its setting on, run_farm logs once per reason what the
# errand would do and what brain/value prices it at (`would`), and nothing
# moves. Each goes live after a watched walk shows the route landing and the
# panel's words (docs/pending/errandsx.md).
HONEYSTORM_LIVE = False
STICKER_PRINTER_LIVE = False
# SECONDS AT THE PLACE, on top of the walk there. The storm lasts 20 s
# (wiki Honeystorm) and pays only in the field the character stands in, so the
# errand would stand in the field in front of the pad for all of it. The
# printer's E, menu, egg pick and confirm: ASSUMED 10 s, never timed.
STAY_SECONDS = {"honeystorm": 20.0, "sticker_printer": 10.0}
LOOK_ONLY = {
    "honeystorm": ("HONEYSTORM_LIVE",
                   "walk natro_out_honeystorm to the pad by the Clover Field, press E "
                   "only at a panel naming the Honeystorm, then gather the field in "
                   "front of it for the storm's 20 s"),
    "sticker_printer": ("STICKER_PRINTER_LIVE",
                        "walk natro_out_sticker_printer to the printer by the Mountain "
                        "Top Field, press E only at a panel naming the Sticker Printer, "
                        "pick the BASIC egg in its menu (never another egg) and confirm"),
}


def would(place: str, *, q: float | None, v: float | None, seconds: float,
          rate: float) -> str:
    """X3/X4's look-only line: what the errand would do and its price, and
    whether the planner (brain/value.plan) would skip it: a Q at or under 0
    loses to gathering for its seconds."""
    flag, plan = LOOK_ONLY[place]
    pretty = place.replace("_", " ")
    if q is None or v is None:
        price = "unpriced"
    else:
        price = (f"worth ~{v / 1e6:,.2f}M, costs ~{rate * seconds / 1e6:,.2f}M of "
                 f"gathering for its ~{seconds:.0f}s (Q {q / 1e6:+,.2f}M): the planner "
                 + ("would skip it" if q <= 0 else "would go"))
    return f"{pretty} would: {plan}; {price}; look-only (act/errands {flag} is False)"


# WHICH SETTING SWITCHES WHICH PLACE OFF.
#
# The economy switches have sat in `world/settings.NOT_WIRED` since the
# beginning under the note that the routes land close enough to call arrived
# and not close enough for a prompt -- which was a verdict on BeeTuxMacro's
# routes, not on the places (see DESIGN 8bg). With Natro's routes, the panel
# recon and `expect_from_panel`, they are real controls, so they are read
# here, in the library, rather than in whichever script happens to need them.
#
# A place with no switch is governed by nothing and runs; the switches exist
# to let the owner say no, not to enumerate everything.
PLACE_SETTINGS = {
    "wealth_clock": "economy.wealth_clock",
    "blender": "economy.blender",
    "wind_shrine": "economy.wind_shrine",
    "blueberry_dispenser": "economy.dispensers",
    "strawberry_dispenser": "economy.dispensers",
    "treat_dispenser": "economy.dispensers",
    "coconut_dispenser": "economy.dispensers",
    "glue_dispenser": "economy.dispensers",
    "royal_jelly_dispenser": "economy.dispensers",
    "honey_dispenser": "economy.dispensers",
    # The FREE Ant Pass Dispenser is a dispenser (wiki Free_Ant_Pass_Dispenser).
    "ant_pass": "economy.dispensers",
    "blue_field_booster": "economy.boosters",
    "red_field_booster": "economy.boosters",
    "white_field_booster": "economy.boosters",
    # THE EVENT MACHINES exist only during Beesmas. Natro decides that from a
    # file on GitHub (natro_macro.ahk:3033-3036, nm_BeesmasHandler); this bot
    # does not depend on the network, so the owner says so with a switch.
    "samovar": "economy.beesmas",
    "stockings": "economy.beesmas",
    "honey_wreath": "economy.beesmas",
    "beesmas_feast": "economy.beesmas",
    "gingerbread_house": "economy.beesmas",
    "snow_machine": "economy.beesmas",
    "candles": "economy.beesmas",
    "lid_art": "economy.beesmas",
    # X4/X3, look-only (LOOK_ONLY), off by default
    "honeystorm": "economy.honeystorm",
    "sticker_printer": "economy.sticker_printer",
}


def wanted_place(settings, place: str) -> bool:
    """Has the owner left this place switched on?

    Unreadable settings say yes, because a place not being visited is a
    quieter failure than a control that silently cancels it -- the same rule
    `bearvisit.wanted_givers` follows for the quest givers.
    """
    key = PLACE_SETTINGS.get(str(place))
    if key is None:
        return True
    try:
        return bool(settings.bool(key))
    except Exception:
        return True


# A MACHINE'S TIMER, as the game prints it on the prompt: "(57:22)" is
# minutes and seconds, "(1:02:03)" hours, minutes and seconds. MEASURED
# 2026-09-23 on the Wealth Clock, twice, 17 s apart: "(57:36)" then
# "(57:22)", so it is a live countdown and not a label.
COUNTDOWN = re.compile(r"\((?:(\d{1,2}):)?(\d{1,2}):(\d{2})\)|\((\d{1,2})s\)")
# UNDER A MINUTE THE TIMER IS PRINTED IN SECONDS. MEASURED 2026-09-24
# 06:47:39 (attempt 356): the Wealth Clock's panel read "Use the Wealth Clock
# (26s)". Unrecognised, that looked like a clock with no timer, E was pressed
# 26 s early, and the visit was written down as a use. Both forms parse now.
# Past a day it is not a machine's cooldown this bot knows of, and a misread
# is likelier than a timer that long.
COUNTDOWN_MAX_SECONDS = 24 * 3600.0


# The longest timer worth standing at the machine for, and how long past it to
# keep reading before giving up. See `run_errand`.
SHORT_WAIT_SECONDS = 300.0         # see run_farm.ERRAND_EARLY_SECONDS
SHORT_WAIT_SLACK_SECONDS = 10.0
# How far past the first reading's deadline the panel's own timer may carry
# the wait (see `run_errand`): the clock ran ~10 s behind ours, measured once.
SHORT_WAIT_OVERRUN_SECONDS = 60.0


def countdown_seconds(text) -> float | None:
    """Seconds left on the timer printed in a panel, or None when it has none.

    None is also the answer for a timer that does not parse as one -- a
    seconds field of 60 or more, or a day or longer -- because a wrong
    deadline is worse than no deadline: the scheduler would stay away from a
    machine that is ready.
    """
    m = COUNTDOWN.search(str(text or ""))
    if not m:
        return None
    if m.group(4) is not None:              # "(26s)"
        return float(int(m.group(4)))
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2))
    seconds = int(m.group(3))
    if seconds >= 60 or (m.group(1) and minutes >= 60):
        return None
    total = float(hours * 3600 + minutes * 60 + seconds)
    if total >= COUNTDOWN_MAX_SECONDS:
        return None
    return total


# B16: A TIMER LONGER THAN THE MACHINE'S OWN PERIOD x1.5 IS A MISREAD, NOT A
# TIMER. MEASURED over var/night/run-*.log (to run-1091): every read-back after
# a press sat at the wiki period less a second or two -- 44:57-44:59 on the
# three field boosters (wiki 45 min), 59:59/1:00:00 on the clock, honey and
# treat dispensers (1 h), 1:59:xx on the ant pass (2 h), 3:59:xx on the
# blueberry (4 h) -- and every arrival read was under it. So a longer one
# ("(5:59:59)" for "(59:59)") is cut to this, never trusted whole: a wrong
# deadline keeps the bot away from a ready machine (`countdown_seconds`).
PERIOD_CAP = 1.5


def capped(seconds, every_hours: float) -> float | None:
    """`seconds` read off a panel, at most PERIOD_CAP x the machine's period
    (`every_hours`, 0 = none known, so only COUNTDOWN_MAX_SECONDS holds)."""
    if seconds is None:
        return None
    if every_hours and every_hours > 0:
        return min(float(seconds), every_hours * 3600.0 * PERIOD_CAP)
    return float(seconds)


def prompt_clock(seconds: float) -> str:
    """57:22 or 3:59:59 -- the timer the way the prompt prints it."""
    seconds = max(0, int(round(float(seconds))))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def booked_line(name: str, left: float, due: float, every_hours: float) -> str:
    """B16's log line: "wealth clock: the prompt says ready in 57:22 -- booked
    for 21:29, not the wiki's 1h"."""
    pretty = str(name).replace("_", " ")
    wiki = (f"the wiki's {every_hours:g}h" if every_hours >= 1 else
            f"the wiki's {every_hours * 60:g} min" if every_hours > 0 else
            "no wiki period")
    return (f"{pretty}: the prompt says ready in {prompt_clock(left)} — booked "
            f"for {time.strftime('%H:%M', time.localtime(due))}, not {wiki}")


def _clock(seconds: float) -> str:
    """57m 22s, for a log line."""
    seconds = max(0, int(round(float(seconds))))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s"


def expect_from_panel(place: str, panel: str) -> tuple:
    """The words to require before pressing E here, or () for "do not press".

    A PANEL READ AT A ROUTE'S END IS AN OBSERVATION, NOT A CONFIRMATION that
    the route reached the place it is named after. `var/place_panels.json`
    records what was seen; this decides whether what was seen is evidence of
    being in the right place, and it is deliberately strict:

      * the panel has to NAME the place, and not another one (`_named_in`:
        one of its names in ALSO_CALLED that no longer name on the panel
        contains, or else all its node words but GENERIC_NAME_WORDS, whole
        words);
      * and it must not be one of NEVER_PRESS, whatever else it says.

    Anything else returns (), which `Errand.matches` treats as
    unconfirmable, so the engine walks there, looks, and presses nothing.
    """
    words = " ".join(str(panel or "").lower().split())
    # A COOLDOWN TIMER IS NOT PART OF THE PLACE'S NAME. MEASURED 2026-09-23
    # 21:06:51 (`var/places/wealth_clock-210651.jpg`): the clock's panel read
    # "Use the Wealth Clock (57:22)" while it was cooling down. Recorded
    # whole, that string would never match the prompt once the timer was
    # gone, and the errand would wait for a panel that never comes.
    words = COUNTDOWN.sub("", words).strip()     # both timer forms; see COUNTDOWN
    if not words:
        return ()
    if any(bad in words for bad in NEVER_PRESS):
        return ()
    if not _named_in(place, words):
        return ()
    return (words,)


def names_place(place: str, panel: str) -> bool:
    """Does this panel NAME `place` (`_named_in`), whatever else it says?

    Not a licence to press: `expect_from_panel` is, and it also refuses
    NEVER_PRESS. This is the other question, whether a route ARRIVED --
    "Spend 6 Tickets to Use the Royal Jelly Dispenser" is the Royal Jelly
    Dispenser, and a route that ends there got there."""
    words = COUNTDOWN.sub("", " ".join(str(panel or "").lower().split())).strip()
    return bool(words) and _named_in(place, words)


# Words in node names that do not tell one place from another (see
# expect_from_panel): every dispenser is a dispenser, and "field" is in every
# booster's name. NOT "hq": no panel read has ever printed it, so with it
# required a place named *_hq can never be confirmed -- right for the
# headquarters, which are shops ("Open Shop", NEVER_PRESS). The three routes
# that carried the name are Natro's gtb paths and go to the field boosters
# (natro_macro.ahk:310, "go to (field) booster"); they are *_field_booster
# now. Without it, "red" alone named red_hq, and "Fire the Red Cannon" passed
# for it.
GENERIC_NAME_WORDS = frozenset({"dispenser", "field"})


def _says(words: str, name: str) -> bool:
    """Does the panel say `name` as whole words? "red" is in "powered"."""
    return bool(name) and re.search(
        r"\b" + re.escape(name) + r"\b", words) is not None


def _named_in(place: str, words: str) -> bool:
    """Does this panel NAME this place, and not some other one?

    THE WORD THAT SAYS WHICH ONE, NOT THE WORD THEY ALL SHARE. Any word of
    the node name used to do, so for the honey dispenser "honey" passed --
    and its route walks the hive row, where our own pad reads "Make Honey"
    -- and "dispenser" passed every other dispenser's panel: a strawberry
    route stopping at the blueberry machine would have had E pressed there
    and its timer booked under the wrong name. Now:

      * a place with names in ALSO_CALLED is known by those alone (they are
        chosen to be specific: "honey dispenser", "blue field booster");
      * any other place by ALL of its node words that are not
        GENERIC_NAME_WORDS ("blue" and "booster" for blue_field_booster);
      * whole words only ("blue" is not in "blueberry", "red" not in
        "powered");
      * and when another place's ALSO_CALLED name is also on the panel and
        CONTAINS the one that matched -- "field booster" inside "blue field
        booster" -- the panel is that other place's. The Mountain Top
        booster is called just "Field Booster" (wiki Field_Booster), the
        tail of the other two names.
    """
    also = ALSO_CALLED.get(place, ())
    if not also:
        names = [n for n in str(place).lower().split("_")
                 if n and n not in GENERIC_NAME_WORDS]
        return bool(names) and all(_says(words, n) for n in names)
    hits = [n for n in also if _says(words, n)]
    others = [p for other, phrases in ALSO_CALLED.items() if other != place
              for p in phrases if _says(words, p)]
    return any(not any(h != p and h in p for p in others) for h in hits)


# A BORROWED ROUTE IS JUDGED BY ITS OWN PLACE, NOT THE GIVER'S. run_farm's
# GIVER_ROUTE_OVERRIDE sends the Honey Bee's hand-in down natro_out_sticker_stack
# (she moved; the stack's walk lands beside her -- UNDONE 2026-10-13, she never
# moved and the override is empty: see run_farm), and the talk scored that walk
# on whether E was pressed at HER -- so every hunt that missed her charged the
# Sticker Stack's walk with a miss. MEASURED 2026-10-13 (runs 949, 950, 954, the
# Honey Bee hand-ins): all three scored "elsewhere", and the record fell to 2 of
# its last 5, one more from the quarantine that would rest the stack's visits
# and the Honey Bee's hand-in with it. Two of the three LANDED: the final leg's
# frame shows "Add a Sticker to the Sticker Stack" with its E
# (var/routes/attempt-949/060627-*-55-walk-w12.jpg, attempt-950/071005-*-55-*)
# and the hunt's first stop read that panel ("the search stopped at a panel
# reading 'Add a Sticker to the Sticker Stack'", 06:06:59, 07:10:40). The third
# was a real miss -- a mob cut the walk (08:22:52 "MOB: ... cutting this walk
# short"), the feed put it in the Strawberry field and leg 55 stands by the
# Ticket Shop (attempt-954/082327-*-55-*) -- and no panel named the stack. So a
# borrowed walk landed when E was pressed or a panel on the way named its own
# place. PINNED "on": it scores, it presses no key, so an hour split would
# only leave half the day scored wrong ("ab" = hours 0-3, 8-11, 16-19).
# ponytail: reads the hunt's own words (its "walked past '...'" text); a
# structured list of the panels it passed if that wording ever changes.
BORROWED_ROUTE_VERDICT = "on"


def borrowed_verdict_on(hour: int | None = None) -> bool:
    h = time.localtime().tm_hour if hour is None else hour
    if BORROWED_ROUTE_VERDICT == "ab":
        return (h // 4) % 2 == 0
    return BORROWED_ROUTE_VERDICT == "on"


def route_place(route: str) -> str:
    """natro_out_sticker_stack(_via_red_cannon) -> sticker_stack."""
    name = str(route or "")
    if name.startswith("natro_out_"):
        name = name[len("natro_out_"):]
    if name.endswith("_via_red_cannon"):
        name = name[:-len("_via_red_cannon")]
    return name


def borrowed_route_landed(route: str, pressed: bool, said: str) -> bool:
    """Did a borrowed walk reach ITS OWN place? `said` is what the talk read
    and walked past (bearvisit's `hunted` and `reason`)."""
    return bool(pressed) or names_place(route_place(route), said)


def run_errand(errand: Errand, *, walk, frames, read_text, vin=None,
               press: bool = False, sleep=time.sleep,
               settle: float = SETTLE_SECONDS, on_note=None,
               hunt=None, stopped=None, max_wait: float = SHORT_WAIT_SECONDS,
               wait_verdict=None) -> ErrandResult:
    """Walk to `errand`, read the panel, and use it only if the panel agrees.

    `walk()` runs the recorded route and returns truthy on success. `press` is
    False by default on purpose: the safe default for a place nobody has
    looked at is to look at it. `stopped()` ends a wait at the machine's
    timer (up to SHORT_WAIT_SECONDS), pressing nothing (run_farm's stop
    flag, DESIGN 8ds). `max_wait` lowers that ceiling (run_farm prices the
    wait); `wait_verdict(left)` is its shadow, a "would walk away" line logged
    before an unchanged wait.
    """
    note = on_note or (lambda text: None)
    result = ErrandResult(name=errand.name)

    try:
        arrived = bool(walk())
    except Exception as exc:
        result.reason = f"the route failed: {exc}"
        return result
    result.walked = arrived
    if not arrived:
        result.reason = "the route did not complete"
        return result

    sleep(settle)
    text = _panel(frames, read_text, note)
    # A ROUTE THAT STOPS SHORT GETS THE SAME SEARCH THE RECON GETS. MEASURED
    # 2026-09-24 01:10:47: `natro_out_blueberry_dispenser`, whose recon had
    # just read "Use the Blueberry Dispenser" after a search, ended this time
    # in the Blue Flower Field with nothing on the panel. `hunt()` walks and
    # watches and presses nothing; what it stops at is read below and must
    # still match `expect` before anything is pressed. This module's rule
    # against hunting was about pressing near a guess, and nothing here does.
    # AND ONE THAT ENDS AT THE NEIGHBOUR. MEASURED 2026-10-11 12:37:
    # natro_out_ant_pass read "Use the Honey Dispenser" (the machine beside
    # it) twice in an hour, and nothing was pressed or searched; the search
    # walks on past a panel naming another place when its `accept` says so.
    if hunt is not None and (not text or not (errand.matches(text)
                                              or errand.is_full(text))):
        try:
            said = str(hunt() or "")
        except Exception as exc:
            said = f"the search itself failed ({exc})"
        if said:
            note(f"{errand.name}: {said}")
        sleep(settle)
        text = _panel(frames, read_text, note)
    result.saw_at = time.time()
    result.saw = " ".join((text or "").split())[:120]
    result.readings.append(result.saw)

    if not text:
        result.reason = ("nothing on the top-centre panel, so there is no "
                         "evidence anything is in front of us")
        return result

    # A FULL MACHINE IS ARRIVED AT, NOT MISSED. MEASURED 2026-09-28 13:22:29
    # (attempt 520): the Free Ant Pass Dispenser read "You Already Have 10 or
    # More Ant Passes", was booked as a route that did not arrive, and the
    # place rested for 527 minutes -- and the Ant Challenge, which rides on
    # its visit, with it. Its period is when to look again.
    if errand.is_full(text):
        result.full = True
        result.cooling = errand.every_hours * 3600.0 if errand.every_hours else None
        result.reason = (f"its own panel says there is nothing to give "
                         f"({result.saw!r}) — pressing nothing")
        return result

    if not errand.matches(text):
        result.reason = (f"the panel does not say this is the {errand.name} "
                         f"— pressing nothing")
        return result

    # A PANEL WITH A TIMER ON IT IS A MACHINE THAT IS NOT READY. The words
    # match -- "Use the Wealth Clock (57:22)" names the clock -- so without
    # this the press went ahead, `used` came back True, and the caller
    # recorded a use that never happened and stayed away for a full period
    # from a machine that was due in whatever the timer said. The timer is
    # the deadline; it is reported, and nothing is pressed.
    left = capped(countdown_seconds(text), errand.every_hours)
    # A SHORT TIMER IS WAITED OUT, NOT WALKED AWAY FROM. The caller may set
    # out a little early (run_farm.ERRAND_EARLY_SECONDS) so as not to lose a
    # whole trip to a clock that is a minute from ready. Waiting presses
    # nothing: the panel is read every few seconds, and the press below
    # still needs the words to match and the timer to be gone.
    if left is not None and wait_verdict is not None and left <= SHORT_WAIT_SECONDS:
        said = wait_verdict(left)
        if said:
            note(said)
    if left is not None and left <= min(max_wait, SHORT_WAIT_SECONDS):
        note(f"{errand.name}: its timer shows {_clock(left)} — waiting here for it")
        waited_until = time.time() + left + SHORT_WAIT_SLACK_SECONDS
        # THE GAME'S TIMER IS THE CLOCK, NOT OURS. MEASURED 2026-09-27
        # (attempt 484): the Wealth Clock's panel read "3m 09s" at 01:50:39,
        # which is ready at 01:53:48 by our clock -- and at 01:53:58, the end
        # of the slack, it still read "0m 01s", so the errand walked away one
        # second early and the clock waited for the next convert's walk. So
        # each reading moves the deadline to what the panel itself says, plus
        # the slack, never past SHORT_WAIT_OVERRUN_SECONDS beyond the first.
        hard_stop = waited_until + SHORT_WAIT_OVERRUN_SECONDS
        while left is not None and time.time() < waited_until:
            # A STOP ENDS THE WAIT, and `left` stays set, so the branch below
            # reports the timer and nothing is pressed.
            if stopped is not None and stopped():
                note(f"{errand.name}: stop requested — not waiting for its timer")
                break
            sleep(min(3.0, max(0.5, left)))
            again = _panel(frames, read_text, note)
            if again and errand.matches(again):
                text = again
                result.saw = " ".join(text.split())[:120]
                result.readings.append(result.saw)
                left = capped(countdown_seconds(text), errand.every_hours)
                if left is not None:
                    waited_until = min(hard_stop, max(
                        waited_until, time.time() + left + SHORT_WAIT_SLACK_SECONDS))
            # A blank read (a receipt passing over the panel) proves nothing
            # either way; the loop simply reads again.
        result.saw_at = time.time()
    if left is not None:
        result.cooling = left
        result.reason = (f"the panel shows its timer ({_clock(left)} left) — "
                         f"not ready, so nothing was pressed")
        note(f"{errand.name}: {result.reason}")
        return result

    # THE LIVE PANEL IS HELD TO NEVER_PRESS TOO, not only the recorded one it
    # matched: `matches` asks whether the expected words are in it, not
    # whether anything else is, and a panel that also says "buy" or "claim
    # hive" is not one to press at whatever else it names -- the same rule
    # act/routes' `_interact_when` applies to a press in the middle of a route.
    # "Spend 6 Tickets to Use the Royal Jelly Dispenser" (the panel by the
    # Clover Field, var/vlm_cache/69/69a74e3b...d281.txt) contains "use the
    # royal jelly dispenser", so a recorded phrase alone would have let it by.
    live = " ".join((text or "").lower().split())
    refused = next((bad for bad in NEVER_PRESS if bad in live), "")
    if refused:
        result.reason = (f"the panel also says {refused!r}, which is not "
                         f"something this bot presses — pressing nothing")
        note(f"{errand.name}: {result.reason}")
        return result

    if not press or vin is None:
        result.reason = ("panel confirms it, but this run is looking only "
                         "(press=False)")
        note(f"{errand.name}: panel confirms — {result.saw!r}")
        return result

    if vin.tap(INTERACT_KEY) is False:
        # HELD BACK BY THE OWNER'S PAUSE OR TAKE OVER (brain/controls
        # STALE_AFTER_A_WAIT): the panel above is from before it. Not a use,
        # so no cooldown is recorded against a machine nobody pressed.
        result.reason = HELD_BACK
        note(f"{errand.name}: {result.reason}")
        return result
    result.pressed_at = time.time()
    result.used = True
    after = ""
    # The timer appearing where there was none is the best evidence this
    # game offers that the press did something -- and it is the next
    # deadline, read rather than assumed. Read until it shows, up to
    # AFTER_PRESS_READS times; nothing more is pressed whatever they say.
    for _ in range(AFTER_PRESS_READS):
        sleep(settle)
        after = _panel(frames, read_text, note) or ""
        result.after_at = time.time()
        result.read_back.append(" ".join(after.split())[:120])
        result.readings.append(result.read_back[-1])
        result.next_in = capped(countdown_seconds(after), errand.every_hours)
        if result.next_in is not None:
            break
    # The panel changing is evidence the press did something; not changing is
    # NOT evidence it did nothing, because plenty of things in this game give
    # you an item without altering the prompt. So this is reported, not judged.
    result.reason = ("the panel changed after pressing"
                     if after.strip() != text.strip()
                     else "the panel read the same after pressing")
    return result


def _panel(frames, read_text, note) -> str | None:
    try:
        frame = frames()
    except Exception as exc:
        note(f"capture failed ({exc})")
        return None
    if frame is None:
        return None
    try:
        return read_text(frame)
    except Exception as exc:
        note(f"could not read the panel ({exc})")
        return None


def load(path) -> dict:
    """Read `data/knowledge/errands.yaml` into Errands, keyed by router node.

    An entry with no `expect` loads fine and simply cannot be confirmed, which
    is the intended state for a place nobody has looked at yet.
    """
    import yaml
    from pathlib import Path

    try:
        body = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}
    out = {}
    for name, row in (body.get("errands") or {}).items():
        row = row or {}
        out[name] = Errand(
            name=name,
            expect=tuple(str(w).lower() for w in (row.get("expect") or ())),
            gives=str(row.get("gives", "")),
            every_hours=float(row.get("every_hours", 0.0) or 0.0),
            bees_required=int(row.get("bees_required", 0) or 0),
            blocked=" ".join(str(row.get("blocked", "") or "").split()),
            boosts={str(k): float(v) for k, v in (row.get("boosts") or {}).items()},
            boost_needs_bees={str(k): int(v) for k, v in
                              (row.get("boost_needs_bees") or {}).items()},
            full=tuple(str(w).lower() for w in (row.get("full") or ())))
    return out


def gate(errand, bees) -> str:
    """What is known to keep this account out of the place, "" for nothing.

    Two things, both from `errands.yaml`: the bees a hive needs
    (`bees_required`, held against `bees`) -- a bee gate, or the only branch
    of Natro's path the route keeps -- and a `blocked` sentence for anything
    else, a badge, a step the route cannot do. A gated place is not walked
    to: a player past a bee gate without the bees is sent straight back to
    spawn (wiki, the gate pages), so the walk buys nothing.

    `bees` is the account's count (the caller's: the owner's screenshot in
    account.yaml, or what gathering has proved, whichever is more) or None
    when nothing says. AN UNKNOWN COUNT GATES a bee-gated place: nothing says
    the hive is past the gate, and a walk there on a hope is the guess the
    owner ruled out (the routes branch's rule, DESIGN 8dr).
    """
    blocked = str(getattr(errand, "blocked", "") or "")
    if blocked:
        return blocked
    need = int(getattr(errand, "bees_required", 0) or 0)
    if need and bees is None:
        return (f"it needs a hive of {need} bees and the hive's bee count is "
                f"not known")
    if need and int(bees) < need:
        return f"it needs a hive of {need} bees and the hive has {int(bees)}"
    return ""


ODDS_MIN_READS = 20      # read presses before their shares replace 1 in the pool


def booster_worth(errand, field_name: str, bees, *, boosted_seconds: float,
                  detour_seconds: float,
                  fill_seconds: float | None = None,
                  odds: dict | None = None,
                  elsewhere: dict | None = None) -> tuple[bool, str]:
    """Is pressing this booster before a trip to `field_name` worth the walk?

    A FIELD BOOSTER BOOSTS ONE FIELD OF ITS SET AT RANDOM (wiki
    Blue_Field_Booster, Red_Field_Booster, Field_Booster: "a random blue
    field", "a random red field", "a random field that is either colorless
    or ... mixed"), for 15 minutes (wiki Field_Boost). Which one, the game
    says only after the press (run_farm `read_the_boost`), so the press is
    worth it on the odds:

        P(this field) x its boost x the boosted seconds it will gather
                >= the seconds the detour costs

    THE ODDS ARE MEASURED when there are enough of them: `odds` is {field:
    presses read} (brain/boostwindow.read_counts, var/boosts.jsonl), and from
    ODDS_MIN_READS reads on, a field's share of them is its chance -- else it
    is 1 in the pool. MEASURED 2026-10-02 over 70 read Blue Field Booster
    presses: Blue Flower 30, Pine Tree 21, Bamboo 19, Stump never (the wiki's
    pool has it only while the Stump Snail is dead).

    A BOOST ELSEWHERE IS NOT WASTED when the trip follows it (the playbook's
    `gather_where_the_boost_landed`): `elsewhere` is {field: how much more a
    followed boost there gathers than this field unboosted, 0.48 for 48%}
    (boostwindow.follow_gain), and each such field adds its own chance times
    that gain.

    The field's own pollen rate is on both sides -- the gain is at its rate
    ("increases pollen gained from its field", wiki Field_Boost) and so is
    the gathering the detour delays -- so it cancels, and nothing in the
    comparison is a rate this bot has not measured. `boosted_seconds` (the
    trip's stay inside the boost's 15 minutes) and `detour_seconds` are the
    caller's, from measurements.

    A BOOSTED BAG FILLS SOONER. With `fill_seconds` (the seconds a full bag
    takes at the field's measured rate) the boosted gathering is at most
    fill_seconds / (1 + boost), when the trip ends on a full bag; whatever a
    second trip back inside the same 15 minutes would add is left out, so
    this is the lower bound.

    The pool is every field the booster can pick that no bee gate keeps it
    from (`boost_needs_bees`, e.g. the Pepper Patch at 35); a field whose
    eligibility is unknown stays in the pool, which lowers the odds rather
    than raising them.
    """
    boosts = dict(getattr(errand, "boosts", {}) or {})
    name = str(getattr(errand, "name", "booster")).replace("_", " ")
    boost = float(boosts.get(field_name, 0.0) or 0.0)
    if boost <= 0:
        return False, f"the {name} does not boost {field_name.replace('_', ' ')}"
    needs = dict(getattr(errand, "boost_needs_bees", {}) or {})
    pool = [f for f in boosts
            if bees is None or int(needs.get(f, 0) or 0) <= int(bees)]
    if field_name not in pool:
        return False, (f"the {name} cannot pick {field_name.replace('_', ' ')} "
                       f"below {needs.get(field_name)} bees")
    reads = {f: int(n) for f, n in (odds or {}).items() if f in pool and int(n) > 0}
    total = sum(reads.values())
    measured = total >= ODDS_MIN_READS

    def chance(f: str) -> float:
        return reads.get(f, 0) / total if measured else 1.0 / len(pool)

    def gathered(gain_factor: float) -> float:
        # A BOOSTED BAG FILLS SOONER: no more than a full bag's seconds
        seconds = max(0.0, float(boosted_seconds))
        if fill_seconds is not None and float(fill_seconds) > 0:
            seconds = min(seconds, float(fill_seconds) / (1.0 + gain_factor))
        return seconds

    seconds = gathered(boost)
    full = (", when the boosted bag is full"
            if seconds < max(0.0, float(boosted_seconds)) else "")
    gain = chance(field_name) * boost * seconds
    followed = {f: float(k) for f, k in (elsewhere or {}).items()
                if f != field_name and f in pool and float(k) > 0 and chance(f) > 0}
    gain_else = sum(chance(f) * k * gathered(k) for f, k in followed.items())
    name_of = field_name.replace("_", " ")
    why = ((f"{name_of} on {reads.get(field_name, 0)} of {total} read presses"
            if measured else f"1 in {len(pool)} that it picks {name_of}")
           + f", +{boost:.0%} for about {seconds:.0f}s of the trip{full}")
    if gain_else > 0:
        why += (f"; following it to "
                f"{' or '.join(f.replace('_', ' ') for f in followed)} adds "
                f"{gain_else:.0f}s")
    gain += gain_else
    why += f": worth {gain:.0f}s of gathering against a {detour_seconds:.0f}s detour"
    return gain >= float(detour_seconds), why


def for_groups(groups, errands: dict, mapping: dict | None = None) -> list:
    """The errands named by these group keys.

    IT DOES NOT READ THE SETTINGS, AND THAT IS DELIBERATE. The three economy
    switches this would serve are still listed in `world/settings.NOT_WIRED`,
    and a first version of this function read them -- which made
    `tests/unit/test_settings.py` demand they be marked as built. (Their names
    are deliberately not written out anywhere in this package: that test scans
    the source for them, and a mention in a comment is enough to trip it.)

    They are not built. MEASURED 2026-09-21: the bot walked the recorded routes
    to the Wealth Clock, the Blue Field Booster and the Royal Jelly Dispenser,
    and at all three the top-centre panel was EMPTY. The routes come from
    BeeTuxMacro and land somewhere close enough to call "arrived" and not close
    enough for the game to offer a prompt. Everything on this side is finished
    and tested; the routes are what is missing.

    Turning on a switch that then does nothing is precisely the thing the owner
    ruled out -- nothing fake for looks; everything must work and be useful --
    so the switches stay off until a route lands. The
    switch-to-errand mapping lives in `errands.yaml` under `groups`; load it
    and pass it as `mapping` the day a route does land.
    """
    mapping = mapping or {}
    asked = []
    for key in groups:
        for name in mapping.get(key, ()):
            if name in errands:
                asked.append(errands[name])
    return asked

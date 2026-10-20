"""The owner's gear goals: what each costs, how far off it is, and what to do next.

THEIR REQUEST: "get me the porcelain staff and backpack and honey mask/all ace
equipment". `data/knowledge/goals.yaml` says what those are and
what they cost, with the wiki page behind every number; this reads it against
what the account has and answers, per goal:

  * how much honey is still missing, counting the goals above it in THEIR order
    first, because buying the Dipper spends the honey the backpack was going to
    come from;
  * how long that is at the honey rate THIS BOT MEASURED -- the rise of the
    balance between its own confirmed converts ("honey settled at N" in
    `var/trips.jsonl`), not a figure from a guide;
  * which materials are missing, and which of the bot's own activities pays
    each one (a quest giver it hands in at, a dispenser it uses, a drop its
    bees pick up) -- or that nothing it does can. "Does" is checked against
    what the bot has actually learned, not just the file: a giver counts once
    its prompt is in var/bear_panels.json, a dispenser once var/place_panels
    .json holds a panel naming it, and neither when the owner switched it off.

WHY THE RATE IS THE BALANCE AND NOT `Totals.honey_per_hour`. The ledger's rate
leaves out honey banked by a cycle that gathered nothing, because that pollen
was gathered on an earlier trip. MEASURED over the session of 2026-09-24 22:03
to 2026-09-25 07:32 (89 trips): 41.9M of the 56.6M banked was such a carry-in
-- the walk home refuses to press E, the rejoin keeps the bag and the next
cycle banks it -- so the ledger's rate read 1,957,015/h while the confirmed
balance went from 22,801,552 to 97,636,800 in 9.41 h, 7,956,853/h. An ETA
built on the first would be four times too long. The balance's own rises are
what the goal actually waits on, and a fall (the owner spending) is left out,
the same rule `scripts/night_report.py` uses for "earned".

WHAT IT DOES NOT DO. It buys nothing itself. The owner lets the bot spend
honey and tickets, never Robux (2026-10-02), and scripts/run_farm buys what it
has a purchase flow for -- brain/buyer.bot_buys: the next Hive Slot, the
Ticket Tent's eggs. A ready goal says which, in the log (and on Telegram): the
bot's to buy at its next visit, or the owner's. NO CARD ASKS "did you buy it"
(the owner, 2026-10-26: too many questions): the honey drop when they buy it
(brain/owned) and the shop's window
(brain/sight, whose daily look checks every ready goal) tell the bot.

AND IT NEVER TURNS "UNKNOWN" INTO ZERO. A material count nobody has told it
and the inventory read (act/inventory, DESIGN 8ea) has not seen is unknown, a
goal whose materials are unknown is never called ready, and the ETA of a goal
is blank when no rate has been measured.

WHAT IS OWNED IS RECHECKED (DESIGN 8ea). "i got porcelain dipper and some
stuff so it would be saving for nothing": owned is `goals.owned` (their word,
CONFIRMED) together with var/owned.json, where `brain/owned` writes what the
honey balance says they bought (INFERRED, with the evidence, and a card asking
them). Both drop the goal from the queue, so the next goal and every ETA are
recomputed from it; the two are shown differently wherever a row is drawn.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..platform.session import ROLE

# A row's state, from done to furthest off.
OWNED = "owned"
READY = "ready to buy"          # the honey and every material are known to be there
HONEY_READY = "honey ready"     # the honey is there; a material is short or unknown
SAVING = "saving"               # honey short, and a rate to say how long for
BLOCKED = "blocked"             # the shop's gate is not passed
UNKNOWN = "unknown"             # no honey reading, so nothing can be said

# What a material source is, NOW. goals.yaml's `bot:` says what KIND of thing
# it is; for a giver or a dispenser marked `does`, `source_now` checks the
# bot's own records before believing it (see the module docstring).
DOES = "does"                   # the bot does this unattended today
UNREAD = "unread"               # the bot has a way there but has not read its prompt
OFF = "off"                     # the owner switched it off in Settings
CANNOT = "cannot"               # nothing the bot has reaches it
TAGS = {UNREAD: "prompt not read yet", OFF: "switched off in Settings",
        CANNOT: "not the bot", "gated": "locked for now",
        "yours": "yours to buy"}

# The Decision Inbox card's two answers. `gui/window` writes the goal into the
# `goals.owned` setting on BOUGHT; NOT_YET changes nothing but stops the card
# coming back until it is re-armed (`Watch._judge`).
BOUGHT = "I bought it"
NOT_YET = "Not yet"
QUESTION_PREFIX = "goal:"
# The card's own state, as a Belief under the card's id: RAISED when it is
# first sent, WITHDRAWN when it is re-armed, which `gui/window` answers by
# taking the card out of the inbox. A Belief because the socket replays the
# newest of each (ipc/bus.REPLAYABLE) and a Question it does not, so a window
# that reconnects hears the card's latest state and not a stale withdrawal.
RAISED = "raised"
WITHDRAWN = "withdrawn"

# THE SHORTEST STRETCH OF CONVERTING A HONEY RATE IS TAKEN OVER: an hour and a
# half, pooled from the newest sittings back until it is covered. MEASURED on
# var/trips.jsonl, every window of the sitting of 2026-09-24 22:03 to
# 2026-09-25 07:32 (48 confirmed converts, 7,956,853/h over the whole 9.4 h)
# against the whole: a 20-minute window -- one trip, the floor this used to
# have -- was within 48% of it in nine windows out of ten and 83% off at
# worst; a 1-hour window within 32% (40% at worst); a 1.5-hour window within
# 22% (27% at worst), and longer bought little (3 h: 17%, 22%). An ETA is a
# plan the owner acts on, so it waits for the 1.5 hours.
RATE_MIN_SECONDS = 1.5 * 3600.0
# the longest gap between two confirmed converts still counted as farming
RATE_STEP_MAX_S = 30 * 60.0
# how far back the rate looks, from the newest row
RATE_WINDOW_S = 12 * 3600.0

# HOW MANY HEARTBEAT READINGS IN A ROW must agree before a card is raised, or
# taken down (`Watch._judge`: WITHDRAWN). Two, for the reason run_farm's
# ZERO_REREAD_SECONDS reads a bag twice: one misread frame must not do
# something the owner then has to undo. A seven-figure honey counter mid-roll
# is exactly where the digit reader has misread before (DESIGN 8aq), and a card
# that appears and vanishes is noise.
ASK_AFTER_READINGS = 2

# The line brain/farm writes when a convert is CONFIRMED -- two identical
# readable honey values above the starting one.
SETTLED = re.compile(r"honey settled at ([\d,]+)")


def _pretty(name: str) -> str:
    return str(name or "").replace("_", " ")


def _slug(text: str) -> str:
    return "_".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def hours_text(hours: float | None) -> str:
    if hours is None:
        return ""
    if hours <= 0:                     # nothing short: not "1 min"
        return "now"
    if hours < 1:
        return f"{max(1, round(hours * 60))} min"
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24:.1f} days"


# ---- the knowledge ---------------------------------------------------------
# Parsed once per change of the file: the bot plans on every 20-second
# heartbeat and the GUI on every honey reading, and the file changes by hand.
_LOADED: dict = {}


def load(path: str | Path | None = None) -> dict:
    """data/knowledge/goals.yaml, or {} when it cannot be read. Shared: do not
    change what it returns."""
    import yaml
    if path is None:
        from ..datapaths import data
        path = data("knowledge", "goals.yaml")
    path = Path(path)
    try:
        stamp = path.stat().st_mtime_ns
        hit = _LOADED.get(str(path))
        if hit is not None and hit[0] == stamp:
            return hit[1]
        body = yaml.safe_load(path.read_text()) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    body = body if isinstance(body, dict) else {}
    _LOADED[str(path)] = (stamp, body)
    return body


def _names(text) -> list[str]:
    return [p.strip() for p in re.split(r"[,;\n]+", str(text or "")) if p.strip()]


def goal_key(name: str, data: dict) -> str | None:
    """A goal's key from whatever the owner typed: a key, a label or an alias."""
    wanted = _slug(name)
    for key, body in (data.get("goals") or {}).items():
        body = body or {}
        spellings = [key, body.get("label", "")] + list(body.get("aliases") or [])
        if wanted in {_slug(s) for s in spellings}:
            return key
    return None


def order_from(text, data: dict) -> tuple[list[str], list[str]]:
    """(goal keys in the owner's order, names that matched nothing).

    Empty text means the file's `default_order`. A goal left out of a
    non-empty list is dropped, which is how they say they do not want it.
    """
    names = _names(text)
    if not names:
        return [k for k in (data.get("default_order") or [])
                if k in (data.get("goals") or {})], []
    keys, unknown = [], []
    for name in names:
        key = goal_key(name, data)
        if key is None:
            unknown.append(name)
        elif key not in keys:
            keys.append(key)
    return keys, unknown


def with_gear(data: dict, text) -> dict:
    """`data` with every piece of gear their `goals.order` names that goals.yaml
    does not, as a goal: the Gear plan page (gui/panels/gearplan) offers all
    of brain/owned.prices() -- the tools of progression.yaml, the bags, hats,
    guards, belts, boots, gliders, sprinklers and Star Amulets of
    gear_prices.yaml -- with the price and materials those files give (a
    material count nobody read stays unknown, so it is never "ready" on a
    guess). Not the hive-slot ladder: their list's `hive_slot` entries are the
    next slot (`with_next_slot`)."""
    from . import owned as owned_mod
    table = owned_mod.prices()
    goals = dict(data.get("goals") or {})
    for name in _names(text):
        if goal_key(name, data):
            continue
        key = owned_mod.item_key(name, table)
        item = table.get(key)
        if item is None or key in goals or item.slot == "hive":
            continue
        goals[key] = {
            "label": item.label, "honey": item.honey, "slot": item.slot,
            "shop": item.shop, "aliases": list(item.aliases),
            "materials": {material_key(m, data) or m: n for m, n in item.materials},
            "source": "data/knowledge/gear_prices.yaml or progression.yaml tools.known"}
    return dict(data, goals=goals)


def with_owned(text, key: str, data: dict | None = None) -> str:
    """`goals.owned` with `key` added, unless it is already there under any
    spelling. What the Decision Inbox's "I bought it" writes."""
    data = load() if data is None else data
    names = _names(text)
    if any(goal_key(n, data) == key for n in names):
        return ", ".join(names)
    # The label, not the key: it is a text box they read and edit.
    label = ((data.get("goals") or {}).get(key) or {}).get("label") or key
    return ", ".join(names + [str(label)])


def material_key(name: str, data: dict) -> str | None:
    wanted = _slug(name)
    table = {**(data.get("materials") or {}), **(data.get("currencies") or {})}
    for key, body in table.items():
        spellings = {_slug(key), _slug((body or {}).get("label", ""))}
        # "treat" and "treats", "gold egg" and "gold eggs": the owner types
        # whichever, and neither is ambiguous between two materials.
        spellings |= {s[:-1] for s in spellings if s.endswith("s")}
        spellings |= {s + "s" for s in list(spellings)}
        if wanted in spellings:
            return key
    return None


def counts_from(text, data: dict) -> tuple[dict, list[str]]:
    """`goals.have`, "treats=1200, oil 4, gold eggs: 1", as {material: count}.

    Returns the pieces it could not read too, so the panel can say so rather
    than silently ignoring a typo.
    """
    out, bad = {}, []
    # A comma inside a number ("treats=1,200") is not a separator.
    parts = re.split(r"[;\n]+|,(?!\d{3}\b)", str(text or ""))
    for part in (p.strip() for p in parts if p.strip()):
        found = re.match(r"^\s*(.+?)\s*[=:]?\s*([\d][\d,]*)\s*$", part)
        key = material_key(found.group(1), data) if found else None
        if key is None:
            bad.append(part)
            continue
        out[key] = int(found.group(2).replace(",", ""))
    return out, bad


def held_materials(typed: dict, account: dict, data: dict | None = None,
                   read: tuple | None = None) -> dict:
    """{material: (count, where the count came from)}.

    What the owner typed wins. Then the bot's own read of the inventory
    menu (`read`, from `brain/owned.inventory`: {material: count} and when),
    then their screenshot of 2026-09-20 in account.yaml for anything else it
    names -- each labelled with its date, because an old count is still a
    count and hiding it would be worse than dating it. A material none of
    them names stays unknown.
    """
    out = {}
    inventory = (account or {}).get("inventory") or {}
    dated = str(inventory.get("source", "") or "the account file")
    for key, value in inventory.items():
        if isinstance(value, int) and not isinstance(value, bool):
            name = (material_key(str(key), data) if data else None) or str(key)
            out[name] = (int(value), dated)
    counts, where = read if read else ({}, "")
    for key, value in (counts or {}).items():
        name = (material_key(str(key), data) if data else None) or str(key)
        out[name] = (int(value), where or "the inventory read")
    for key, value in (typed or {}).items():
        out[key] = (int(value), "you typed it in Settings > Goals")
    return out


# ---- what the bot can actually do today ------------------------------------
@dataclass
class Can:
    """The bot's own records of which givers and places it can use.

    `givers`: quest givers whose prompt it has read (var/bear_panels.json), so
    the hand-in can press there. `routed`: the givers it walks to at all
    (act/bearvisit.GIVERS). `places`: places with a recorded panel that names
    them (var/place_panels.json through `act/errands.expect_from_panel`, the
    test `_next_usable` applies before it uses one) and that are in
    `act/errands.FREE_TO_USE`. `off`: what the owner has
    switched off in Settings.
    """
    givers: set = field(default_factory=set)
    routed: set = field(default_factory=set)
    places: set = field(default_factory=set)
    off: set = field(default_factory=set)


def _read_json(path: Path) -> dict:
    try:
        body = json.loads(Path(path).read_text())
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


def can_from_files(var_root: str | Path, settings=None) -> Can:
    """`Can` from the bot's own files. Read-only: `bearvisit.Learned.load`
    would rewrite the file it reads, so the JSON is read here directly."""
    from ..act.bearvisit import GIVERS, prompt_shaped, wanted_givers
    from ..act.errands import (PLACE_SETTINGS, expect_from_panel, free_to_use,
                               wanted_place)
    var_root = Path(var_root)
    bears = _read_json(var_root / "bear_panels.json")
    places = _read_json(var_root / "place_panels.json")
    can = Can(routed=set(GIVERS))
    can.givers = {str(k) for k, v in bears.items()
                  if str(k) in GIVERS and prompt_shaped(str(v))}
    # AND ONLY WHERE E MAY BE PRESSED AT ALL (act/errands.FREE_TO_USE):
    # `_next_usable` skips any other place, so a named Blender panel is a
    # place read, not one used.
    can.places = {str(k) for k, v in places.items()
                  if prompt_shaped(str(v)) and expect_from_panel(str(k), str(v))
                  and free_to_use(str(k))}
    if settings is not None:
        try:
            if not bool(settings.bool("quests.enabled")):
                can.off |= set(GIVERS)
        except Exception:
            pass
        can.off |= set(GIVERS) - set(wanted_givers(settings, GIVERS))
        can.off |= {k for k in set(PLACE_SETTINGS) | set(places)
                    if not wanted_place(settings, k)}
    return can


def source_now(src: dict, can: Can | None) -> tuple[str, str]:
    """(what this source is now, why) -- see DOES and the rest.

    Only a giver's or a dispenser's `does` is checked: a drop happens while
    the bees gather whatever the bot does, and `gated`, `cannot` and `yours`
    are facts about the game and the rules, not about what it has learned.
    Without `can` the file's word stands.
    """
    bot = str(src.get("bot") or "")
    if bot != DOES or can is None:
        return bot, ""
    giver, place = src.get("giver"), src.get("place")
    if src.get("kind") == "shop":
        place = None     # a shop is no errand panel: its `does` is run_farm's buy flow (glue's Gumdrop Shop)
    if giver:
        giver = str(giver)
        if giver not in can.routed:
            return CANNOT, "no recorded route the bot walks to it"
        if giver in can.off:
            return OFF, "switched off in Settings"
        if giver not in can.givers:
            return UNREAD, ("its prompt has never been read, so nothing can be "
                            "handed in there yet")
    elif place:
        place = str(place)
        if place in can.off:
            return OFF, "switched off in Settings"
        if place not in can.places:
            return UNREAD, ("no panel naming it has been read at the end of "
                            "its route yet, so it is never pressed")
    return DOES, ""


# ---- the honey -------------------------------------------------------------
# The trip fields the plan reads; Watch keeps no others (see _ledger_rows).
TRIP_FIELDS = ("at", "convert_note")


def balance_readings(rows) -> list[tuple[float, int]]:
    """(when, honey) for every confirmed convert in the ledger, oldest first."""
    out = []
    for row in rows or ():
        found = SETTLED.search(str(row.get("convert_note") or ""))
        if found:
            try:
                out.append((float(row.get("at") or 0.0),
                            int(found.group(1).replace(",", ""))))
            except ValueError:
                continue
    return out


def latest_balance(rows) -> tuple[int, float] | None:
    got = balance_readings(rows)
    return (got[-1][1], got[-1][0]) if got else None


@dataclass
class Rate:
    """How fast the balance rose, between this bot's own confirmed converts."""
    per_hour: float
    hours: float
    readings: int
    since: float
    until: float
    spent: int = 0
    sittings: int = 1

    def describe(self) -> str:
        when = time.strftime("%d %b %H:%M", time.localtime(self.until))
        return (f"{self.per_hour:,.0f} honey/h, the balance's rise over "
                f"{self.hours:.1f} h of this bot's converts"
                + (f" in its last {self.sittings} sittings"
                   if self.sittings > 1 else "") + f", to {when}")


def balance_rate(rows, min_seconds: float = RATE_MIN_SECONDS) -> Rate | None:
    """The rate at which the confirmed balance rose, newest sittings first.

    A sitting is `brain.ledger.sessions` -- split on a quiet gap -- so the
    hours the bot was not running are never counted. The newest sitting is
    taken whole; when it spans less than `min_seconds` of converts the one
    before it is added, and so on. None until `min_seconds` is covered.
    A fall (the owner spending) is left out and reported as `spent`.
    """
    from .ledger import sessions
    rise = spent = readings = sittings = 0
    seconds = 0.0
    since = until = None
    # THE NEWEST RATE_WINDOW_S ONLY: the hive grows, so a 2-day sitting reads its
    # older, slower hours in (21 Oct: 151.5M/h over the sitting, the HUD's newest
    # 13.9 h 238M/h)
    newest = max((float(r.get("at") or 0.0) for r in rows or ()), default=0.0)
    for sitting in reversed(sessions(list(rows or ()))):
        got = [g for g in balance_readings(sitting) if g[0] >= newest - RATE_WINDOW_S]
        if len(got) < 2:
            continue
        # TIME ONLY WHERE IT EARNED. MEASURED 2026-10-21 (research): this said
        # 134.6M/h against the HUD's 238M/h, because a sitting runs to a 3 h
        # quiet gap (ledger.sessions), so 10.6 h of 20 min-2 h breaks counted as
        # farming, and a fall (a purchase) dropped its rise but kept its time.
        # An interval longer than RATE_STEP_MAX_S, or one that fell, is skipped.
        for (a, before), (b, after) in zip(got, got[1:]):
            if after < before:
                spent += before - after
            elif b - a <= RATE_STEP_MAX_S:
                rise += after - before
                seconds += b - a
        readings += len(got)
        sittings += 1
        since = got[0][0]
        until = got[-1][0] if until is None else until
        if seconds >= min_seconds:
            break
    if seconds < min_seconds or rise <= 0:
        return None
    return Rate(per_hour=rise * 3600.0 / seconds, hours=seconds / 3600.0,
                readings=readings, since=since, until=until, spent=spent,
                sittings=sittings)


# ---- the plan --------------------------------------------------------------
@dataclass
class Need:
    material: str
    label: str
    need: int
    have: int | None = None
    have_from: str = ""
    sources: list = field(default_factory=list)   # dicts, each with `now`
    eta_h: float | None = None         # hours to cover `short` at its measured rate

    @property
    def short(self) -> int | None:
        return None if self.have is None else max(0, self.need - self.have)

    @property
    def met(self) -> bool:
        return self.have is not None and self.have >= self.need

    def describe(self) -> str:
        have = "?" if self.have is None else f"{self.have:,}"
        return f"{self.label} {have}/{self.need:,}"

    def where(self, limit: int = 3) -> str:
        """The bot's own ways of getting it, then anything else, briefly."""
        def who(s):
            name = (s.get("giver") or s.get("place")
                    or {"drop": "drops while gathering",
                        "blender": "the Blender"}.get(s.get("kind"),
                                                      s.get("kind", "")))
            if s.get("giver"):
                name = f"{name} quests"
            return _pretty(name)
        does = [who(s) for s in self.sources if s.get("now") == DOES][:limit]
        rest = [f"{who(s)} ({TAGS.get(s.get('now'), s.get('now', ''))})"
                for s in self.sources if s.get("now") != DOES]
        rest = rest[:max(1, limit - len(does))]
        out = ("the bot gets it from " + ", ".join(does)) if does else ""
        if rest:
            out += ("; also " if out else "") + ", ".join(rest)
        return out

    def brief(self, limit: int = 3) -> str:
        """`where` as short tags for a checklist: what the bot does itself
        first, e.g. "Drops · Black Bear quests · Stinger Shop (yours)"."""
        def who(s):
            name = (s.get("giver") or s.get("place")
                    or {"drop": "drops", "blender": "Blender"}.get(s.get("kind"),
                                                              s.get("kind", "")))
            name = _pretty(name)
            name = name[:1].upper() + name[1:]
            return f"{name} quests" if s.get("giver") else name
        does = [who(s) for s in self.sources if s.get("now") == DOES]
        rest = [who(s) + (" (yours)" if s.get("now") == "yours" else "")
                for s in self.sources if s.get("now") != DOES]
        return " · ".join(list(dict.fromkeys(does + rest))[:limit])


@dataclass
class Row:
    key: str
    label: str
    shop: str = ""
    shop_label: str = ""
    cost: int = 0
    needs: list = field(default_factory=list)
    owned: bool = False
    gate: str = ""
    gate_ok: bool | None = None
    state: str = UNKNOWN
    honey: int | None = None
    short: int | None = None           # honey, this goal alone
    queue_short: int | None = None     # honey, this goal after the ones above it
    eta_hours: float | None = None
    next_step: str = ""
    source: str = ""
    held_quests: list = field(default_factory=list)
    # HOW IT CAME TO BE OWNED (brain/owned): "confirmed" is their word, in
    # Settings or on a card; "inferred" is the balance's evidence, which a
    # card is asking them about. `owned_why` says which and from what.
    owned_how: str = ""
    owned_why: str = ""
    waits: str = ""                    # why the bot holds off buying it (slot_waits)
    # "from the Blue progression" (brain/progression): not their goal, the
    # research's next one after theirs. `quiet`: no Decision Inbox card for it.
    origin: str = ""
    quiet: bool = False
    # WHAT WAS CHECKED OF IT BY SIGHT (brain/sight.ask_note, ROADMAP G13):
    # its card says so, not just "did you buy it"
    checked: str = ""
    # THE SLOWEST INPUT, not the honey (2026-10-22 replay, runs 1138-1174:
    # the Diamond Mask's honey was 16 h away and its moon charms ~35 days):
    # (hours, what) over the honey and every short input with a rate
    # (`slowest`); `rate_unknown` names the short inputs with none.
    eta_slowest: tuple | None = None
    rate_unknown: list = field(default_factory=list)

    def slowest_text(self) -> str:
        """"slowest: moon charm ~35.0 days (honey 16.0 h)", or ""."""
        if self.eta_slowest is None:
            return ("rate unknown: " + ", ".join(self.rate_unknown)) if self.rate_unknown else ""
        hours, what = self.eta_slowest
        out = (f"slowest: {what}, none gained since its reads began" if hours == float("inf")
               else f"slowest: {what} ~{hours_text(hours)}")
        if what != "honey" and self.eta_hours:
            out += f" (honey {hours_text(self.eta_hours)})"
        if self.rate_unknown:
            out += "; rate unknown: " + ", ".join(self.rate_unknown)
        return out

    @property
    def state_text(self) -> str:
        """The state as the owner reads it: an inferred goal says so."""
        if self.owned and self.owned_how == "inferred":
            return "owned? (inferred)"
        return self.state

    @property
    def missing(self) -> list:
        return [n for n in self.needs if not n.met]

    @property
    def card_due(self) -> bool:
        """Whether this goal gets a Decision Inbox card: ready to buy, or its
        honey there with every missing count one the bot has not been told.
        A count they typed that is short is a known "not yet" -- 1,200 treats
        against the Honey Mask's 9,999 -- and a card would invite a purchase
        the shop refuses."""
        if self.waits or self.quiet:
            return False
        return self.state == READY or (
            self.state == HONEY_READY
            and all(n.have is None for n in self.missing))


@dataclass
class Plan:
    rows: list = field(default_factory=list)
    honey: int | None = None
    honey_from: str = ""
    honey_at: float | None = None
    rate: Rate | None = None
    unknown_names: list = field(default_factory=list)
    unread_counts: list = field(default_factory=list)
    at: float = 0.0
    progress: object = None            # brain/progression.Progress, or None

    def row(self, key: str) -> Row | None:
        return next((r for r in self.rows if r.key == key), None)

    def ready(self) -> list:
        """The goals they can buy now: honey and every material known there."""
        return [r for r in self.rows if r.state == READY]

    def first_open(self) -> Row | None:
        return next((r for r in self.rows if not r.owned), None)

    def owned_text(self) -> str:
        """"Porcelain Dipper, Honeycomb Belt? (inferred)" -- the owned goals,
        the inferred ones marked, for a line of the stream or the log."""
        return ", ".join(r.label + ("? (inferred)" if r.owned_how == "inferred"
                                    else "") for r in self.rows if r.owned)

    def honey_line(self) -> str:
        if self.honey is None:
            return "honey: not read"
        when = (time.strftime("%d %b %H:%M", time.localtime(self.honey_at))
                if self.honey_at else "")
        return (f"honey {self.honey:,}"
                + (f" ({self.honey_from}{', ' + when if when else ''})"
                   if self.honey_from else ""))

    def headline(self) -> str:
        """One line for the run log and the report's short version."""
        row = self.first_open()
        if row is None:
            return ("goals: every gear goal is owned"
                    if self.rows else "goals: none set")
        if row.state == READY:
            return (f"goals: the {row.label} is ready to buy at the "
                    f"{row.shop_label} for {row.cost:,} honey — "
                    + (f"it waits: {row.waits}" if row.waits else
                       "the bot buys it at its next visit" if _bot_buys(row)
                       else "yours to buy")
                    + f"; {self.honey_line()}")
        slow = row.slowest_text()
        slow = f"{slow}; " if slow else ""
        if row.state == HONEY_READY:
            return (f"goals: the honey for the {row.label} is there "
                    f"({row.cost:,}); {slow}still needed: "
                    + ", ".join(n.describe() for n in row.missing)
                    + f"; {self.honey_line()}")
        if row.state == BLOCKED:
            return f"goals: next is the {row.label} — {row.next_step}"
        if row.short is None:
            return f"goals: next is the {row.label} ({row.cost:,} honey); {self.honey_line()}"
        return (f"goals: next is the {row.label} — {slow}{row.short:,} honey short"
                + (f", about {hours_text(row.eta_hours)} of farming at "
                   f"{self.rate.per_hour:,.0f}/h" if row.eta_hours is not None
                   and self.rate else ", no rate measured yet")
                + ("; also needs " + ", ".join(n.describe() for n in row.missing)
                   if row.missing else "")
                + f"; {self.honey_line()}")

    def describe(self) -> str:
        lines = [self.headline()]
        for row in self.rows:
            lines.append(f"  - {row.label}: {row.state}"
                         + (f" — {row.next_step}" if row.next_step else ""))
        if self.unknown_names:
            lines.append("  (not a goal this file knows: "
                         + ", ".join(self.unknown_names) + ")")
        return "\n".join(lines)


def _gate(shop: dict, bees: int | None) -> tuple[bool | None, str]:
    need = shop.get("gate_bees")
    if need is not None:
        if bees is None:
            return None, f"{shop.get('gate', '')} — bee count not known"
        if int(bees) >= int(need):
            return True, f"{shop.get('gate', '')} — you have {bees}"
        return False, f"{shop.get('gate', '')} — you have {bees}"
    evidence = " ".join(str(shop.get("gate_evidence", "")).split())
    return None, (shop.get("gate", "") + (f" — {evidence.split('.')[0].lower()}"
                                          if evidence else ""))


def _quests_of(src: dict) -> list[str]:
    quest = src.get("quest")
    if isinstance(quest, (list, tuple)):
        return [str(q) for q in quest if q]
    return [str(quest)] if quest else []


def build(data: dict, *, honey: int | None = None, honey_from: str = "",
          honey_at: float | None = None, rate: Rate | None = None,
          order=None, owned=(), held: dict | None = None,
          bees: int | None = None, quest_text: str = "",
          tickets: tuple | None = None, can: Can | None = None,
          rates: dict | None = None, clock=time.time) -> Plan:
    """Every goal in `order`, measured against what is known of the account.

    `held` is `held_materials(...)`; `tickets` is (count, where from), for the
    ticket-priced sources; `can` is what the bot's records say it can use
    (`can_from_files`); `rates` is {material: gained per hour}
    (`material_rates`). `owned` is goal keys, or {key: (how, why)} from
    `brain/owned` (CONFIRMED or INFERRED). Pure: everything it knows comes
    in as arguments.
    """
    goals = data.get("goals") or {}
    shops = data.get("shops") or {}
    materials = data.get("materials") or {}
    held = held or {}
    owned = (dict(owned) if isinstance(owned, dict)
             else {str(k): ("confirmed", "") for k in (owned or ())})
    order = list(order if order is not None else (data.get("default_order") or []))
    plan = Plan(honey=honey, honey_from=honey_from, honey_at=honey_at,
                rate=rate, at=clock())
    queue = 0
    # THE MATERIALS ARE QUEUED LIKE THE HONEY. With 50 oil and 50 enzymes held
    # and the Honey Mask (50 oil, 25 enzymes) above the Honeycomb Belt (25 oil,
    # 50 enzymes), each alone is covered and the two together are 25 of each
    # short; counted in full for both, both were "ready to buy", and after they
    # bought the Mask the Belt could not be. So a goal gets what the open goals
    # above it leave: {material: what they need between them}.
    taken: dict = {}
    quest_low = str(quest_text or "").lower()
    for key in order:
        body = goals.get(key)
        if not body:
            plan.unknown_names.append(key)
            continue
        shop = shops.get(body.get("shop")) or {}
        row = Row(key=key, label=str(body.get("label") or _pretty(key)),
                  shop=str(body.get("shop") or ""),
                  shop_label=str(shop.get("label") or _pretty(body.get("shop"))),
                  cost=int(body.get("honey") or 0), owned=key in owned,
                  honey=honey, source=str(body.get("source") or ""),
                  origin=str(body.get("origin") or ""))
        row.gate_ok, row.gate = _gate(shop, bees)
        for name, need in (body.get("materials") or {}).items():
            mat = materials.get(name) or {}
            count, where = held.get(name, (None, ""))
            if count is not None and not row.owned and taken.get(name):
                where = (f"{where}; you hold {count:,}, and the goals above "
                         f"it take {taken[name]:,}")
                count = max(0, count - taken[name])
            sources, held_now = [], []
            for src in mat.get("sources") or ():
                now, why = source_now(src, can)
                sources.append(dict(src, now=now, now_why=why))
                for quest in _quests_of(src):
                    if quest.lower() in quest_low:
                        held_now.append(
                            f"\"{quest}\" ({_pretty(src.get('giver'))}) is in "
                            f"the quest menu now and pays {mat.get('label', name)}"
                            f": {' '.join(str(src.get('gives', '')).split())}")
            row.needs.append(Need(material=name,
                                  label=str(mat.get("label") or _pretty(name)),
                                  need=int(need), have=count, have_from=where,
                                  sources=sources))
            if not row.needs[-1].met:
                row.held_quests += [q for q in held_now if q not in row.held_quests]
        if not row.owned:
            for need in row.needs:
                taken[need.material] = taken.get(need.material, 0) + need.need
        if row.owned:
            row.owned_how, row.owned_why = owned[key]
            row.state = OWNED
            row.next_step = ("owned" if row.owned_how != "inferred" else
                             f"owned, inferred: {row.owned_why} — decided on "
                             f"its own; \"Not right? Undo\" takes it back")
            plan.rows.append(row)
            continue
        queue += row.cost
        if honey is not None:
            row.short = max(0, row.cost - int(honey))
            row.queue_short = max(0, queue - int(honey))
            if rate is not None and rate.per_hour > 0:
                row.eta_hours = row.queue_short / rate.per_hour
        _judge_row(row, rate, tickets)
        if rates is not None:
            slowest(row, rates, tickets)
        plan.rows.append(row)
    return plan


def say_slowest(plan: Plan) -> None:
    """Each open row's `next_step` ends with its slowest input. Called once
    every `slowest` has run (from_files: after `with_blender`, which re-runs
    the Blender goal's), so the step and the headline name the same inputs."""
    for row in plan.rows:
        if row.state != READY and row.slowest_text():
            row.next_step += "; " + row.slowest_text()


# ---- the slowest input (2026-10-22) ----------------------------------------
# MATERIAL RATES FROM THE INVENTORY'S OWN READS: act/inventory.write keeps the
# last READS_KEPT reads' counts in var/inventory.json "reads". A rate is what
# was GAINED between reads (a fall is a spend -- the Blender, a planter -- not
# a negative rate) over the hours they span; fewer than 2 reads or under
# RATE_MIN_HOURS is "rate unknown". NOTHING GAINED is a rate of 0 (an ETA of
# never, which frees the goal's honey) only over RATE_ZERO_MIN_READS reads
# spanning RATE_ZERO_MIN_HOURS (review 2026-10-22: one quiet hour flipped it).
READS_KEPT = 60
RATE_MIN_HOURS = 1.0
RATE_ZERO_MIN_READS = 3
RATE_ZERO_MIN_HOURS = 6.0


def material_rates(reads) -> dict:
    """{slug: gained per hour} from [[at, {slug: count}], ...]."""
    seen: dict = {}
    for entry in sorted((e for e in reads or () if isinstance(e, (list, tuple)) and len(e) == 2
                         and isinstance(e[1], dict)), key=lambda e: float(e[0])):
        for slug, n in entry[1].items():
            if isinstance(n, int):
                seen.setdefault(slug, []).append((float(entry[0]), n))
    out = {}
    for slug, pts in seen.items():
        span = (pts[-1][0] - pts[0][0]) / 3600
        if len(pts) < 2 or span < RATE_MIN_HOURS:
            continue
        gained = sum(max(0, b[1] - a[1]) for a, b in zip(pts, pts[1:]))
        if gained or (len(pts) >= RATE_ZERO_MIN_READS and span >= RATE_ZERO_MIN_HOURS):
            out[slug] = gained / span
    return out


def _eta(short: int, rate) -> float | None:
    if rate is None:
        return None
    return short / rate if rate > 0 else float("inf")


def slowest(row: Row, rates: dict, tickets=None, extra=()) -> None:
    """`row.eta_slowest` and `row.rate_unknown` over its honey, its short
    materials and `extra` ((slug, label, short): the Blender's other inputs,
    `with_blender`). A material priced in tickets may come by the tickets
    instead, whichever is sooner.
    ponytail: the ticket route counts every ticket for this one material --
    the Diamond Eggs and the Magic Beans share them; and a Blender-made
    material is bounded by the slower of its two ways (an upper bound)."""
    etas, unknown = [], []
    if row.queue_short and row.eta_hours is not None:
        etas.append((row.eta_hours, "honey"))
    for need in row.missing:
        if need.short is None:
            unknown.append(need.label)
            continue
        need.eta_h = _eta(need.short, rates.get(need.material))
        priced = [x for x in need.sources if x.get("currency") == "tickets" and x.get("price")]
        if priced and tickets and tickets[0] is not None:
            cost = max(0, need.short * int(priced[0]["price"]) - int(tickets[0]))
            by_tickets = _eta(cost, rates.get("tickets")) if cost else 0.0
            if by_tickets is not None:
                need.eta_h = by_tickets if need.eta_h is None else min(need.eta_h, by_tickets)
        if need.eta_h is None:
            unknown.append(need.label)
        else:
            etas.append((need.eta_h, need.label))
    for slug, label, short in extra:
        eta = _eta(int(short), rates.get(slug))
        if eta is None:
            unknown.append(label)
        else:
            etas.append((eta, label))
    row.eta_slowest = max(etas, key=lambda e: e[0]) if etas else None
    row.rate_unknown = list(dict.fromkeys(unknown))


def with_blender(plan: Plan, crafting, rates: dict, tickets=None) -> None:
    """The Blender's other inputs (act/blender.Crafting `lacking`) into its
    goal's slowest input: the moon charms behind the Diamond Mask's Glitter."""
    lacking = dict(getattr(crafting, "lacking", None) or {})
    row = next((r for r in plan.rows if not r.owned
                and r.label == getattr(crafting, "goal", None)), None)
    if row is None or not lacking:
        return
    slowest(row, rates, tickets, extra=[(slug, slug.replace("_", " "), n)
                                        for slug, n in lacking.items()])


# THE KEEP RULE, SHADOW (GOALS_KEEP_LIVE False: logged as "goals would: ...",
# today's keeping unchanged). MEASURED runs 1138-1174: billions were kept for the
# Diamond Mask (its price and the Blender's jelly) while its moon charms
# were ~35 days away, so the honey earned nothing for weeks and the jelly
# rolls waited on "the Blender's first". A goal's price is kept only while its
# slowest input is under KEEP_HOURS away; the Blender's jelly only while its
# crafts' other inputs are held.
GOALS_KEEP_LIVE = False
KEEP_HOURS = 24.0


def keep_within(plan: Plan, crafting=None, jelly_honey: int = 0,
                hours: float = KEEP_HOURS) -> tuple[int, str]:
    """(honey the rule would keep, why) for the first open goal; `jelly_honey`
    is what today's buyer keeps for the Blender's jelly."""
    row = plan.first_open() if plan is not None else None
    if row is None:
        return 0, "no open goal"
    slow = row.eta_slowest
    near = slow is None or slow[0] <= hours
    keep = int(row.cost or 0) if near else 0
    # AN INPUT WITH NO RATE IS NOT "NEAR": the price stays kept, as today,
    # and the line says it is for want of a rate, not for the honey
    why = (f"slowest {slow[1]} in {hours_text(slow[0]) if slow[0] != float('inf') else 'never at its rate'}"
           if slow and not (near and row.rate_unknown) else
           "kept: rate unknown for " + ", ".join(row.rate_unknown) if row.rate_unknown else
           "no rate for its inputs, so kept as today")
    if jelly_honey:
        crafts_ready = crafting is not None and not getattr(crafting, "lacking", None) \
            and not getattr(crafting, "cannot", None)
        if crafts_ready:
            keep += int(jelly_honey)
        else:
            why += "; the Blender's jelly not kept (its crafts wait on " + ", ".join(
                [s.replace("_", " ") for s in (getattr(crafting, "lacking", None) or {})]
                + list(getattr(crafting, "cannot", None) or ())) + ")"
    return keep, f"keep {keep:,} for the {row.label} ({why})"


def _judge_row(row: Row, rate: Rate | None, tickets) -> None:
    """The state and the plain-English next step."""
    missing = row.missing
    where = f"at the {row.shop_label}" if row.shop_label else "at its shop"
    if row.gate_ok is False:
        row.state = BLOCKED
        row.next_step = f"{row.gate}, so the shop cannot be reached yet"
        return
    if row.short is None:
        row.state = UNKNOWN
        row.next_step = (f"{row.cost:,} honey {where}; the honey counter has not "
                         f"been read")
        return
    parts = []
    # AFFORDABLE MEANS AFFORDABLE IN THEIR ORDER. With 97.6M on 2026-09-25 the
    # Honeycomb Belt (75M, fourth) was affordable on its own while the Dipper
    # (150M, first) was not, and a card saying "the Belt is ready" is an
    # invitation to spend the Dipper's honey. So a goal is only ready once the
    # goals above it are paid for too; its own price being covered is said in
    # the text instead.
    if row.queue_short == 0 and not missing:
        row.state = READY
        if _bot_buys(row):
            row.next_step = (f"ready: the bot buys it {where} for {row.cost:,} honey "
                             f"at its next visit, once the shop's own screen shows "
                             f"that price — answer \"{BOUGHT}\" if you buy it first")
        else:
            row.next_step = (f"ready: buy it yourself {where} for {row.cost:,} honey "
                             f"(check the price on the shop's own screen) — the bot "
                             f"has no purchase flow for it, and answering "
                             f"\"{BOUGHT}\" moves the plan on")
        return
    eta = (f", about {hours_text(row.eta_hours)} of farming at the measured "
           f"{rate.per_hour:,.0f}/h" if row.eta_hours is not None and rate
           else ", and no honey rate measured yet")
    if row.queue_short == 0:
        row.state = HONEY_READY
        parts.append(f"the honey is there ({row.cost:,} {where})")
    elif row.short == 0:
        row.state = SAVING
        parts.append(f"the honey for this one alone is there ({row.cost:,}), but "
                     f"the goals above it come first in your order: "
                     f"{row.queue_short:,} short counting them" + eta)
    else:
        row.state = SAVING
        ahead = (row.queue_short or 0) - row.short
        parts.append(f"{row.short:,} honey short"
                     + (f" ({row.queue_short:,} counting the goals above it)"
                        if ahead > 0 else "") + eta)
    for need in missing:
        if need.have is None:
            text = f"{need.label} ?/{need.need:,}"
        else:
            text = (f"{need.label} {need.have:,}/{need.need:,} "
                    f"({need.have_from})")
        how = need.where()
        if how:
            text += f" — {how}"
        priced = [s for s in need.sources if s.get("currency") == "tickets"
                  and s.get("price")]
        if priced and tickets and tickets[0] is not None:
            price = int(priced[0]["price"])
            text += (f"; {tickets[0]:,} tickets ({tickets[1]}) would buy "
                     f"{tickets[0] // price} at the {_pretty(priced[0].get('place'))}")
        parts.append(text)
    parts.extend(row.held_quests)
    if any(n.have is None for n in missing):
        parts.append("? is a count nobody has seen yet — the bot's inventory "
                     "read fills it once a session, or type yours into "
                     "Settings > Goals")
    row.next_step = "; ".join(parts)


def rank_givers(plan: Plan) -> dict:
    """{giver: rank} for the quest givers the bot DOES hand in at (`source_now`)
    whose quests pay a material an open goal still needs. Rank is the goal's
    position among the open goals, so the next goal's materials come first."""
    givers = {}
    open_rows = [r for r in plan.rows if not r.owned]
    for rank, row in enumerate(open_rows):
        for need in row.missing:
            for src in need.sources:
                if src.get("now") == DOES and src.get("giver"):
                    givers.setdefault(str(src["giver"]), rank)
    return givers


def _bot_buys(row) -> bool:
    """Whether scripts/run_farm buys this goal itself (brain/buyer.bot_buys)."""
    from .buyer import bot_buys
    return bot_buys(str(getattr(row, "shop", "") or ""), str(getattr(row, "key", "") or ""))


def prefer(names, ranks: dict) -> tuple:
    """`names` reordered so the ranked ones come first, lowest rank first; the
    rest keep their order behind them (the sort is stable)."""
    names = list(names)
    big = len(names) + 1
    return tuple(sorted(names, key=lambda n: ranks.get(n, big)))


def question(row: Row, plan: Plan):
    """What a goal that has become affordable says: its `question` is the
    log line's title (`Watch._judge`). No longer sent as a card (2026-10-26)."""
    from ..telemetry.events import Option, Question
    if row.state == READY:
        title = (f"Ready to buy the {row.label} at the {row.shop_label} for "
                 f"{row.cost:,} honey")
    else:
        title = (f"The honey for the {row.label} is there ({row.cost:,} at the "
                 f"{row.shop_label}) — check the materials")
    context = (f"{plan.honey_line()}. "
               + (("Materials: " + ", ".join(n.describe() for n in row.needs)
                   + ". ") if row.needs else "No materials needed. ")
               + (f"{row.gate[:1].upper()}{row.gate[1:]}. " if row.gate else "")
               + ("The bot buys this one itself at its next visit, with honey "
                  f"and never Robux; answer \"{BOUGHT}\" only if you buy it first."
                  if _bot_buys(row) else
                  "The bot has no purchase flow for this one. Buy it yourself, "
                  f"and answer \"{BOUGHT}\" so the plan moves on to the next goal.")
               + (f" {row.checked}" if row.checked else ""))
    return Question(
        id=f"{QUESTION_PREFIX}{row.key}", question=title, context=context,
        default=NOT_YET,
        options=[Option(label=BOUGHT, score=float(row.cost), unit="honey",
                        why="writes it into Settings > Goals > owned, so the "
                            "plan moves on to the next goal"),
                 Option(label=NOT_YET, score=0.0, unit="honey",
                        why="nothing changes; the card comes back only after "
                            "the honey dips below the price and climbs back")])


# ---- the whole thing from the files ----------------------------------------
# THE NEXT HIVE SLOT, a goal priced from the hive itself. `default_order`
# names it `hive_slot`; `with_next_slot` replaces that with `hive_slot_<n>`,
# n the bee count after it, at data/knowledge/hive_slots.yaml's price -- one
# key per slot, so the one the balance says they bought (brain/owned) does not
# hide the next. A hive of 50, or no count, has none.
NEXT_SLOT = "hive_slot"
# THE CELLS A HIVE HAS BEFORE ANY SLOT IS BOUGHT: data/knowledge/hive_slots.yaml
# ("A hive starts with 25 slots", the wiki's Hive Slot page read 2026-10-01;
# its price table starts at the 26th). ASSUMED for a new account until one is
# seen: a new account's count comes from the bee menu (var/bees.json).
FREE_SLOTS = 25


def slots_bought(var_root, slots: dict | None = None) -> int:
    """The highest hive slot the bot's own purchases bought (var/purchases.json:
    an ok "Hive Slot" row at the price hive_slots.yaml gives that slot), or 0."""
    if slots is None:
        import yaml
        from ..datapaths import data as data_path
        try:
            body = yaml.safe_load(data_path("knowledge", "hive_slots.yaml").read_text()) or {}
            slots = {int(k): int(v) for k, v in (body.get("honey_for_bees") or {}).items()}
        except (OSError, ValueError, TypeError):
            return 0
    try:
        rows = json.loads((Path(var_root) / "purchases.json").read_text())
    except (OSError, ValueError):
        return 0
    by_price = {price: n for n, price in (slots or {}).items()}
    got = [by_price.get(int(r.get("price") or 0), 0) for r in rows
           if isinstance(r, dict) and r.get("ok") and r.get("item") == "Hive Slot"]
    return max(got, default=0)


# THE EGG A NEW SLOT IS BOUGHT FOR AND FILLED WITH: the Basic Egg, the blue
# guide's (blue_hive_plan.yaml `serves: [basic_egg, hive_slot]`), bought with
# honey at the Basic Egg Shop. Tickets stay for the Honey Mask's Gold Eggs, and
# run_farm hatches no other egg into a new slot by itself.
SLOT_EGG = ("basic_egg", "Basic Egg")
# THE EGGS A NEW SLOT TAKES: the Basic Egg only. THE OWNER, 2026-10-10:
# no egg but the Basic (and an event bee's own egg, `egg_may_hatch`)
# is spent -- the rest are saved for crafting and special use, and a Star Egg
# (a gifted bee of a type not yet gifted) waits until every other type is
# gifted. So Star and Silver Eggs are never hatched.
SLOT_EGGS = (SLOT_EGG,)
# THE ALT HATCHES ANY EGG (HIVEMIND_ROLE=alt). THE OWNER, 2026-10-13: the alt
# may spend on anything that costs no Robux --
# Mythic, Diamond, Star and Gold included; the rule above is the main's. So a
# new slot on the alt takes the best egg held: a Mythic first (1 in 6 a
# Tadpole, a Tad alt's only no-Robux path: brain-research-2.md section 2),
# then by items.yaml's egg odds (Diamond 95% legendary, Gold 79% epic, Silver
# 65% rare), the Basic last.
# ponytail: the Star Egg's place (after the Diamond) is a judgement -- its odds
# are not in items.yaml; move it once they are.
ALT_SLOT_EGGS = (("mythic_egg", "Mythic Egg"), ("diamond_egg", "Diamond Egg"),
                 ("star_egg", "Star Egg"), ("gold_egg", "Gold Egg"),
                 ("silver_egg", "Silver Egg"), SLOT_EGG)
if ROLE == "alt":
    SLOT_EGGS = ALT_SLOT_EGGS


# DIAMOND EGGS ARE SAVED FOR RECIPES (settings `eggs.save_diamond`, default
# on). THE OWNER, 2026-10-14: an option to save Diamond Eggs for recipes.
# The Diamond Mask
# takes 5 (goals.yaml diamond_mask); the bot never crafts or buys gear, so the
# only use it could make of one is a hatch -- and while this is on, no role
# hatches one (the alt included; its own settings file turns it off). Off, the
# rules before it stand: the main still saves them (egg_may_hatch), the alt
# hatches any egg.
DIAMOND_EGG = ("diamond_egg", "Diamond Egg")


def diamond_saved(settings=None) -> bool:
    """Whether `eggs.save_diamond` is on (a settings object that cannot answer:
    on -- an egg kept is never lost). AND WHILE THE BOT BUYS THEM
    (`economy.tickets.diamond_eggs`, brain/buyer.ticket_purchases): bought
    for the Diamond Mask, never hatched, fed or slotted, whatever else is set."""
    try:
        if settings is None:
            from ..world.settings import Settings
            settings = Settings()
        return (bool(settings.get("eggs.save_diamond", True))
                or bool(settings.get("economy.tickets.diamond_eggs", False)))
    except Exception:
        return True


MYTHIC_EGG = ("mythic_egg", "Mythic Egg")


def mythic_hatched(settings=None) -> bool:
    """Whether `eggs.hatch_mythic` is on (default off: the owner's 2026-10-10
    rule saves them). RESEARCH 2026-10-21 (wiki Egg page): nothing uses a
    Mythic Egg -- no recipe, no gifting path -- and every mythic beats a
    Basic Bee, 2 in 6 a core blue bee (Buoyant, Tadpole); a saved one makes
    no honey. The owner, 2026-10-21, left the choice to research."""
    try:
        if settings is None:
            from ..world.settings import Settings
            settings = Settings()
        return bool(settings.get("eggs.hatch_mythic", False))
    except Exception:
        return False


def egg_may_hatch(label: str, settings=None) -> bool:
    """The owner's rule (2026-10-10): a Basic Egg, or an event bee's own egg
    ("Festive Bee Egg" -- a "<Bee> Bee Egg"), may be hatched; a Silver, Gold,
    Diamond, Star or Mythic Egg never. On the alt, any egg (ALT_SLOT_EGGS).
    A Diamond Egg never while `eggs.save_diamond` is on, on any role."""
    words = " ".join(str(label or "").lower().split())
    if words == DIAMOND_EGG[1].lower() and diamond_saved(settings):
        return False
    if ROLE == "alt":
        return words.endswith(" egg")
    if words == MYTHIC_EGG[1].lower():
        return mythic_hatched(settings)
    return words == "basic egg" or words.endswith(" bee egg")


def slot_egg_held(counts: dict, settings=None):
    """The (slug, label) of the best SLOT_EGGS egg held, or None -- never a
    Diamond Egg while `eggs.save_diamond` is on."""
    saved = diamond_saved(settings)
    if mythic_hatched(settings) and int((counts or {}).get(MYTHIC_EGG[0], 0) or 0) > 0:
        return MYTHIC_EGG            # a mythic first, where the setting is on
    return next((egg for egg in SLOT_EGGS
                 if int((counts or {}).get(egg[0], 0) or 0) > 0
                 and not (saved and egg[0] == DIAMOND_EGG[0])), None)


def slot_waits(var_root, bees: int, settings=None) -> str:
    """Why the next hive slot waits although its honey is there, or "". A SLOT
    WITH NO EGG FOR IT IS HONEY STANDING EMPTY: the 35th was bought with the
    Festive Bee Egg in hand (2026-10-03 06:01), and once it hatched the 36th
    was next at 283,309,237 with no egg. So a slot is bought only when every
    slot bought has its bee, both reads are up to date (act/inventory
    mark_dirty: an egg bought or hatched since) and the inventory read counted
    a SLOT_EGG (run_farm.mts_buy_due holds to this)."""
    if slots_bought(var_root) > bees:
        return f"slot {bees + 1} is bought and still waits for its bee"
    from ..act.inventory import dirty
    for name in ("inventory.json", "bees.json"):
        why = dirty(Path(var_root) / name)
        # ONLY AN EGG CHANGES WHAT THIS DECIDES (the bees counted, the eggs
        # held). MEASURED 2026-10-07 10:21-11:00: the slot's honey was there
        # and every convert found a read "not read again since 30 Pineapple
        # fed" or "1 Royal Jelly rolled" -- each window's feed or roll staled
        # the read the last one had just renewed
        if why and "egg" in why.lower():
            return f"var/{name} has not been read again since {why}"
    from .owned import inventory
    counts, _where = inventory(var_root)
    if slot_egg_held(counts, settings) is None:
        return f"no {SLOT_EGG[1]} is held to fill slot {bees + 1}, so it would stand empty"
    return ""


def with_next_slot(data: dict, bees: int | None, slots: dict | None = None) -> dict:
    """`data` with the next hive slot as a goal, where `default_order` asks
    for it; `data` itself when there is no count or no slot left."""
    order = list(data.get("default_order") or [])
    # A SLOT ENTRY MAY STOP AT A HIVE SIZE: "hive_slot<=42" asks for the next
    # slot only while it is slot 42 or lower, so gear can come between slots
    # (the guides' order, data/knowledge/goals.yaml). The first entry that
    # still applies stands for the next slot; the rest go.
    def _bound(k) -> int | None:
        k = str(k)
        if k == NEXT_SLOT:
            return 10 ** 9
        if k.startswith(NEXT_SLOT + "<="):
            try:
                return int(k.split("<=", 1)[1])
            except ValueError:
                return None
        return None
    if not any(_bound(k) is not None for k in order):
        return data
    if slots is None:
        import yaml
        from ..datapaths import data as data_path
        try:
            body = yaml.safe_load(data_path("knowledge", "hive_slots.yaml").read_text()) or {}
            slots = {int(k): int(v) for k, v in (body.get("honey_for_bees") or {}).items()}
        except (OSError, ValueError, TypeError):
            slots = {}
    nxt = int(bees) + 1 if bees else None
    honey = slots.get(nxt) if nxt else None
    out = dict(data)
    out["goals"] = dict(data.get("goals") or {})
    if not honey:
        out["default_order"] = [k for k in order if _bound(k) is None]
        return out
    key = f"{NEXT_SLOT}_{nxt}"
    out["goals"][key] = {
        "label": f"Hive Slot (bee {nxt})", "slot": "hive", "shop": "mountain_top_shop",
        "honey": honey, "materials": {}, "aliases": ["hive slot", "slot", "next slot"],
        "what": (f"the hive's slot {nxt}: room for one more bee, hatched from an egg "
                 f"(a Basic Egg for honey, or a Silver or Gold Egg for 50 or 100 "
                 f"tickets at the Ticket Tent). The blue guide's Stage 1 ends at 48 "
                 f"bees; 35 opens the 35-bee zone."),
        "source": "https://bee-swarm-simulator.fandom.com/wiki/Hive_Slot (data/knowledge/hive_slots.yaml)"}
    placed, new_order = False, []
    for k in order:
        bound = _bound(k)
        if bound is None:
            new_order.append(k)
        elif not placed and nxt <= bound:
            new_order.append(key)
            placed = True
    out["default_order"] = new_order
    return out


def with_progression(data: dict, order: list, prog) -> tuple:
    """(data, order) with up to progression.PLAN_EXTRA of the progression's
    next goals after theirs. Only gear, amulets and planters with a honey price;
    a goal goals.yaml already has is theirs to order or drop (`goals.order`: one
    left out is one they do not want), so it is never added back; hive slots
    are their list's `hive_slot` entries. No `shop`: the bot buys none of these
    (brain/buyer.bot_buys)."""
    from .progression import PLAN_EXTRA, plan_entry
    goals = dict(data.get("goals") or {})
    order, added = list(order), 0
    for nxt in prog.next if prog else []:
        if added >= PLAN_EXTRA:
            break
        if (nxt.goal.get("kind") not in ("gear", "amulet", "planter") or not nxt.honey
                or nxt.id in goals or nxt.id in order):
            continue
        goals[nxt.id] = plan_entry(nxt, prog.hive, prog.account)
        order.append(nxt.id)
        added += 1
    return dict(data, goals=goals), order


def from_files(*, var_root: str | Path | None = None, settings=None,
               honey: int | None = None, honey_from: str = "",
               honey_at: float | None = None, data: dict | None = None,
               rows: list | None = None, clock=time.time,
               first: list | None = None) -> Plan:
    """The plan from the same files the bot reasons with. Reads, never writes.

    `first`: goal keys ahead of their order; None means the session goals'
    items while their horizon lasts (brain/session_goals, ROADMAP G9).

    The honey is the caller's live reading when it has one -- the bot's HUD,
    the GUI's last `honey` metric, the report's live frame -- and otherwise
    the newest confirmed convert in the ledger, said to be that.
    """
    from . import knowledge
    from . import plan as plan_mod
    from .ledger import Ledger
    if var_root is None:
        from ..datapaths import VAR_ROOT
        var_root = VAR_ROOT
    var_root = Path(var_root)
    data = load() if data is None else data
    # THE HIVE'S COUNT: the bee menu's own header when the bot has read it
    # (act/beemenu), else account.yaml's.
    bees = knowledge.standing().bees
    try:
        from ..act import beemenu
        read = beemenu.count_for_gates(var_root / "bees.json")
        if read:
            bees = max(int(bees or 0), int(read))
    except Exception:
        pass
    # A SLOT BOUGHT IS NOT A BEE: the count stays 34 until an egg hatches in
    # the 35th cell, and the next-slot goal must not offer the slot already
    # bought (MEASURED 2026-10-03 06:02, still "ready to buy" a minute after
    # the bot bought it). The goals' next slot counts the slots bought;
    # `bees` stays the bees, for the gates.
    if settings is None:
        from ..world.settings import Settings
        settings = Settings()
    # THEIR ORDER IS READ LIKE THE DEFAULT ONE (the Gear plan page, 2026-10-20):
    # any priced gear in it is a goal (`with_gear`), and a `hive_slot` /
    # `hive_slot<=N` entry stands for the next slot, as in goals.yaml.
    typed = _names(settings.get("goals.order") or "")
    # THE PLAN'S TARGET FIRST (brain/plan: 'Get one item', the alt plans)
    typed = plan_mod.prepend(settings, typed, data)
    data = plan_mod.with_targets(settings, data)
    if typed:
        # THE PRO TESTER'S ORDER (brain/protips), when they took it: its goals
        # are not goals.yaml's, so the ones their list names are merged first
        try:
            from . import protips
            from .progression import hive_from
            picked = dict(protips.suggested_order(hive_from(settings), data))
            names = {_slug(n) for n in typed}
            data = dict(data, goals={**{k: e for k, e in picked.items() if k in names},
                                     **(data.get("goals") or {})})
        except Exception:              # a broken suggestion never ends a plan
            pass
        data = with_gear(dict(data, default_order=typed), ", ".join(typed))
    data = with_next_slot(data, max(int(bees or 0), slots_bought(var_root)) or bees)
    if rows is None:
        rows = Ledger(var_root / "trips.jsonl").trips()
    if honey is None:
        last = latest_balance(rows)
        if last is not None:
            honey, honey_at = last
            honey_from = "the last confirmed convert in var/trips.jsonl"
    order, unknown = order_from(", ".join(data.get("default_order") or []) if typed else "",
                                data)
    # SESSION GOALS FIRST (G9): then their goals.order, then the progression.
    if first is None:
        from .session_goals import first_keys
        first = first_keys(data, var_root)
    order = list(dict.fromkeys(list(first) + order))
    # THE PROGRESSION'S NEXT GOALS, AFTER THEIRS (2026-10-14): their list first,
    # then the research's next ones for the hive colour they set, so the bot
    # always has a sensible next target (brain/progression, with_progression).
    try:
        from . import progression
        prog = progression.progress(var_root, settings)
        data, order = with_progression(data, order, prog)
    except Exception:                  # a broken research file never ends a plan
        prog = None
    typed, unread = counts_from(settings.get("goals.have") or "", data)
    # WHAT IS OWNED: their word, and what the balance says they bought
    # (brain/owned, DESIGN 8ea). A name they typed that is not a goal (their
    # "Riley Guard, Bucko Guard") is gear all the same, and brain/owned
    # knows it; the plan only needs the goals.
    from . import owned as owned_mod
    owned = {k: (o.how, o.why) for k, o in owned_mod.owned(
        settings.get("goals.owned") or "", var_root).items()
        if k in (data.get("goals") or {})}
    account = knowledge.account() or {}
    read = owned_mod.inventory(var_root)
    held = held_materials(typed, account, data, read=read)
    try:
        rates = material_rates(json.loads((var_root / "inventory.json").read_text(
            encoding="utf-8")).get("reads"))
    except (OSError, ValueError, AttributeError):
        rates = {}
    tickets = held.get("tickets")
    try:
        quest_text = (var_root / "quests.json").read_text()
    except OSError:
        quest_text = ""
    plan = build(data, honey=honey, honey_from=honey_from, honey_at=honey_at,
                 rate=balance_rate(rows), order=order,
                 owned=owned, held=held,
                 bees=bees, quest_text=quest_text,
                 tickets=tickets, can=can_from_files(var_root, settings),
                 rates=rates, clock=clock)
    if read[0]:
        try:
            from .buyer import crafting_from_files
            with_blender(plan, crafting_from_files(plan, read[0]), rates, tickets)
        except Exception:              # a recipe file never ends a plan
            pass
    say_slowest(plan)
    plan.unknown_names += unknown
    plan.unread_counts = unread
    plan.progress = prog
    # ONE CARD FOR THE PROGRESSION AT A TIME: the first of its goals open.
    extra = [r for r in plan.rows if r.origin and not r.owned]
    for row in extra[1:]:
        row.quiet = True
    # WHAT THE SHOP WINDOWS SHOWED of each open goal (brain/sight, G13): an
    # item seen owned is already owned above (brain/owned.SEEN); the rest
    # carry what was checked, and when, into their card.
    try:
        from . import sight
        table = owned_mod.prices()
        for row in plan.rows:
            if not row.owned and row.key in table and table[row.key].infer:
                row.checked = sight.ask_note(var_root, [row.key], table)
    except Exception:
        pass
    for row in plan.rows:
        if row.key.startswith(NEXT_SLOT + "_") and not row.owned:
            row.waits = slot_waits(var_root, int(bees or 0), settings)
            if row.waits and row.state == READY:
                row.next_step = f"ready, but it waits: {row.waits}"
    return plan


def hud_honey(reading) -> int | None:
    """What `Watch.tick` is given from a HUD honey Reading (brain/farm): its
    value when it is OK and its digits are grouped as the HUD groups them
    (brain/owned.GROUPED, where the misreads are measured), else None: no
    reading, so a misread neither counts towards a goal card nor makes a
    level, and the purchase watch does not bridge the gap
    (owned.Purchases.observe)."""
    from .owned import GROUPED
    if not getattr(reading, "ok", False) or reading.value is None:
        return None
    if not GROUPED.fullmatch(str(getattr(reading, "text", "") or "")):
        return None
    return int(reading.value)


class Watch:
    """The bot's end: plans on every reading, raises cards, orders givers.

    `emit` sends a telemetry event (the Decision Inbox card); `say` writes a
    log line. Both may be set after construction. Every entry point swallows
    its own errors -- a goal list must never end a farming run.

    NO CARD IS SENT ANY MORE (the owner, 2026-10-26: too many questions):
    a ready goal is said in the log,
    and a card an older version put up is taken down. What follows is the
    history of the cards, kept because var/goals.json still holds them.

    THE CARD WAS SENT AGAIN WHILE IT WAS UNANSWERED. The socket does not replay
    questions to a GUI that connects later (ipc/bus.REPLAYABLE), and the bot
    restarts with every attempt, so a card sent once is a card the owner
    never sees if the window was closed at that moment. It is re-sent on
    every judged reading (the inbox shows one card per id, so repeats cost
    nothing) until an answer comes back through `answer`, and `var/goals.json`
    carries that across restarts.

    AND IT IS TAKEN DOWN when it is re-armed. The window outlives the bot's
    restarts and a card stays until they answer it, so "Ready to buy the
    Dipper" sat there after the honey fell back below the price while the
    Goals tab said "saving". A WITHDRAWN belief under the card's id removes it;
    a re-sent card whose title has changed (the honey was there, now the
    materials are too) replaces the old one.

    EVERY READING IS ALSO A CHECK OF WHAT THEY OWN (DESIGN 8ea). The same
    readings go to `brain/owned.Purchases`, which reads a fall of the balance
    as a purchase and decides what it bought; the first reading of a process reads the
    saved record once for the falls it already holds. A goal that becomes
    owned is dropped from the plan in the same tick, and the log says so.
    """

    def __init__(self, var_root: str | Path, emit=None, say=None,
                 settings_factory=None, clock=time.time,
                 state_path: str | Path | None = None):
        import threading
        self.var_root = Path(var_root)
        self.state_path = (Path(state_path) if state_path
                           else self.var_root / "goals.json")
        self.emit = emit or (lambda event: None)
        self.say = say or (lambda text: None)
        self.settings_factory = settings_factory
        self.clock = clock
        self.honey: int | None = None
        self.honey_at: float | None = None
        self.plan: Plan | None = None
        # The heartbeat thread, the main loop and the socket's reader all
        # come through here.
        self._lock = threading.RLock()
        self._streak: dict = {}
        self._said_order: tuple | None = None
        self._rows_key = None
        self._rows: list = []
        self.asked: dict = self._load()
        # What was owned at the last plan, {key: how}; None until the first.
        self._owned_seen: dict | None = None
        self._buyer = None
        # WHAT TO BUY (brain/buyer), said again only when it changes in
        # substance -- what, ready or not, and why not -- not each tick
        self._said_shopping = None
        self._said_checked: set = set()
        # the card ids taken down this process (the cards older versions sent)
        self._cleared: set = set()

    # ---- state ------------------------------------------------------------
    def _load(self) -> dict:
        try:
            body = json.loads(self.state_path.read_text())
            asked = body.get("asked") if isinstance(body, dict) else None
            return dict(asked) if isinstance(asked, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            from ..files import atomic_write
            atomic_write(self.state_path, json.dumps({"asked": self.asked},
                                                     indent=1))
        except OSError:
            pass

    def _settings(self):
        if self.settings_factory is not None:
            return self.settings_factory()
        from ..world.settings import Settings
        return Settings()              # fresh: the owner edits these live

    def _ledger_rows(self) -> list:
        """The trips, re-read only when the file has changed."""
        from .ledger import Ledger
        path = self.var_root / "trips.jsonl"
        try:
            stat = path.stat()
            key = (stat.st_mtime, stat.st_size)
        except OSError:
            return []
        if key != self._rows_key:
            # ONLY WHAT THE PLAN READS (balance_readings, ledger.sessions):
            # the whole parsed trips.jsonl was ~56 MB resident, ~135 MB at
            # each re-read.
            self._rows = [{k: row.get(k) for k in TRIP_FIELDS}
                          for row in Ledger(path).trips()]
            self._rows_key = key
        return self._rows

    # ---- the tick ---------------------------------------------------------
    def purchases(self):
        """brain/owned's watch on the balance, built on first use."""
        if self._buyer is None:
            from .owned import Purchases
            self._buyer = Purchases(
                self.var_root, emit=lambda event: self.emit(event),
                say=lambda text: self.say(text), clock=self.clock,
                typed=lambda: self._settings().get("goals.owned") or "")
        return self._buyer

    def _plan(self) -> Plan:
        return from_files(var_root=self.var_root, settings=self._settings(),
                          honey=self.honey, honey_at=self.honey_at,
                          honey_from="the HUD" if self.honey is not None else "",
                          rows=self._ledger_rows(), clock=self.clock)

    def tick(self, honey: int | None = None, say: bool = False,
             capacity: int | None = None, read: bool = False) -> Plan | None:
        """Plan again. A fresh `honey` reading also judges the cards, and is
        a check of what they own; `capacity` is a session-start capacity.
        `read` says this tick is a HUD reading even when `honey` is None (an
        unreadable or misgrouped one, `hud_honey`): brain/owned's "two in a
        row" does not reach across it."""
        try:
            with self._lock:
                if honey is not None:
                    self.honey, self.honey_at = int(honey), self.clock()
                plan = self._plan()
                if (honey is not None or capacity is not None or read) and \
                        self._recheck(plan, honey, capacity, read):
                    plan = self._plan()          # an owned goal leaves now
                self.plan = plan
                self._narrate_owned(plan)
                if honey is not None:
                    self._judge(plan)
                    self._owned_cards(plan)
                    self._progression_cards(plan)
            if say:
                self.say(plan.headline())
                self._say_shopping(plan)
            return plan
        except Exception as exc:              # a goal list must never end a run
            if say:
                self.say(f"goals: could not plan ({exc})")
            return None

    def _say_shopping(self, plan: Plan) -> None:
        """The buyer's list (brain/buyer), when it has changed."""
        try:
            from . import buyer
            shopping = buyer.from_files(plan, self.var_root, honey=self.honey,
                                        settings=self._settings())
            key = tuple((p.key, p.ready, p.can_buy, p.blocked.split(":")[0])
                        for p in shopping.purchases)
            if key == self._said_shopping:
                return
            self._said_shopping = key
            for line in shopping.lines():
                self.say(line)
        except Exception as exc:              # never ends a run
            self.say(f"buying: could not plan ({exc})")

    def _recheck(self, plan: Plan, honey, capacity, read=False) -> bool:
        """brain/owned on this reading. True when what is owned changed.
        Its own errors are its own: the plan goes on without it."""
        try:
            buyer = self.purchases()
            changed = False
            for line in buyer.backfill(plan, plan.rate):     # once, ever
                self.say(line)
                changed = True
            if capacity is not None:
                changed |= buyer.observe_capacity(capacity, self.clock())
            if honey is not None or read:
                changed |= buyer.observe(honey, self.honey_at, plan, plan.rate)
            return changed
        except Exception as exc:
            self.say(f"owned: could not check the purchases ({exc})")
            return False

    def _owned_cards(self, plan: Plan) -> None:
        try:
            self.purchases().cards(plan)
        except Exception as exc:
            self.say(f"owned: could not send its cards ({exc})")

    def _narrate_owned(self, plan: Plan) -> None:
        """Say when a goal leaves the plan as owned, or comes back."""
        now = {r.key: r for r in plan.rows if r.owned}
        seen, self._owned_seen = self._owned_seen, {k: r.owned_how
                                                    for k, r in now.items()}
        nxt = plan.first_open()
        after = (f"; next is the {nxt.label}" if nxt else
                 "; every goal on the list is owned")
        if seen is None:
            if now:
                self.say("goals: already owned, so not saved for — "
                         + "; ".join(f"{r.label} ({r.owned_why or r.owned_how})"
                                     for r in now.values()) + after)
            return
        for key, row in now.items():
            if key not in seen:
                self.say(f"goals: the {row.label} is dropped from the plan as "
                         f"owned ({row.owned_how}: {row.owned_why}){after}")
            elif seen[key] != row.owned_how:
                self.say(f"goals: the {row.label} is now {row.owned_how} "
                         f"owned ({row.owned_why})")
        for key in set(seen) - set(now):
            row = plan.row(key)
            if row is not None:
                self.say(f"goals: the {row.label} is back on the plan — it is "
                         f"not owned any more (a \"No\" on its card, or taken "
                         f"out of Settings > Goals); {row.state}")

    def _card_state(self, key: str, value: str) -> None:
        from ..telemetry.events import Belief
        self.emit(Belief(name=f"{QUESTION_PREFIX}{key}", value=value,
                         source="goals"))

    def _judge(self, plan: Plan) -> None:
        changed = False
        for row in plan.rows:
            ready = row.card_due
            streak = self._streak.get(row.key, 0)
            streak = (max(0, streak) + 1) if ready else (min(0, streak) - 1)
            self._streak[row.key] = streak
            asked = self.asked.get(row.key)
            if ready and streak >= ASK_AFTER_READINGS:
                if asked is None:
                    # SAID, NOT ASKED (the owner, 2026-10-26): no card. The
                    # entry stays unanswered, so brain/sight's daily shop look
                    # checks the item (open_items) until it is owned.
                    self.asked[row.key] = {"at": self.clock(), "honey": plan.honey,
                                           "state": row.state}
                    changed = True
                    self.say(f"goals: {question(row, plan).question} — "
                             + ("the bot buys it at its next visit, with honey"
                                if _bot_buys(row) else
                                "yours to buy (the bot has no purchase flow for it); "
                                "when you buy it, the honey drop or its shop window "
                                "tells the bot, nothing to answer"))
                elif not asked.get("answered") and row.key not in self._cleared:
                    # a card an older version put up comes down, once a process
                    self._cleared.add(row.key)
                    self._card_state(row.key, WITHDRAWN)
            elif (not ready and streak <= -ASK_AFTER_READINGS
                    and asked is not None):
                # RE-ARMED. The honey fell below the price (bought, or spent
                # on something else), a count they typed came up short, or the
                # goal was marked owned; the next time it becomes affordable
                # is news again. A card still in the inbox is taken down (see
                # the class note).
                del self.asked[row.key]
                changed = True
                self._card_state(row.key, WITHDRAWN)
        if changed:
            self._save()

    def _progression_cards(self, plan: Plan) -> None:
        """brain/progression's slots no reader sees ("Which boots do you
        wear?"): DECIDED, NOT ASKED (the owner, 2026-10-26). The plan already
        assumes none of the slot's items (the card's own default, "None of
        these yet"), and nothing is bought on a progression goal
        (brain/buyer.bot_buys), so it is said once, ever (var/goals.json),
        and the shop look checks the items (brain/sight.open_items reads
        these cards) -- never sent to the window."""
        from ..telemetry.events import Belief
        from .progression import QUESTION_PREFIX as ASK
        cards = getattr(plan.progress, "questions", None) or []
        # CHECKED, NOT ASKED (G13): once a process, each slot a shop window answered
        for line in getattr(plan.progress, "checked", None) or []:
            if line not in self._said_checked:
                self._said_checked.add(line)
                self.say(line)
        for card in cards:
            if card.id not in self.asked:
                self.asked[card.id] = {"at": self.clock()}
                self._save()
                items = [o.label for o in card.options if o.label != card.default]
                self.say(f"progression: decided: no shop window showed your "
                         f"{card.id.rsplit(':', 1)[-1]} yet, so the plan assumes none of the "
                         f"{', the '.join(items)} yet (nothing is bought on it); the "
                         f"bot looks at their shop windows on its next visits. "
                         f"Have one? Add it in Settings > Goals > Gear you already own")
            elif card.id not in self._cleared:
                # a card an older version put up comes down, once a process
                self._cleared.add(card.id)
                self.emit(Belief(name=card.id, value=WITHDRAWN, source="goals"))
        # SETTLED SOME OTHER WAY (they typed their boots into Settings): taken down
        for key in [k for k, v in self.asked.items() if k.startswith(ASK)
                    and not v.get("answered") and k not in {c.id for c in cards}]:
            del self.asked[key]
            self._save()
            self.emit(Belief(name=key, value=WITHDRAWN, source="goals"))
            # ...BY A SHOP'S WINDOW (G13): say what was seen, not just that it went
            try:
                from .progression import load, slot_checked
                prog = plan.progress
                line = slot_checked(prog.account, load(prog.hive), key.rsplit(":", 1)[-1])
                if line and line not in self._said_checked:
                    self._said_checked.add(line)
                    self.say(line)
            except Exception:
                pass

    def answer(self, event) -> None:
        """An `Answer` from the GUI. One for a goal card stops it being sent
        again; the GUI itself writes "I bought it" into `goals.owned`. One
        for an owned or fall card (brain/owned) is recorded in var/owned.json
        -- the window records it too, and the second write changes nothing."""
        try:
            qid = str(getattr(event, "id", "") or "")
            if getattr(event, "kind", "") != "answer":
                return
            from . import owned as owned_mod
            if qid.startswith(owned_mod.CARD_PREFIXES):
                choice = str(getattr(event, "choice", "") or "")
                with self._lock:
                    owned_mod.record_answer(self.var_root, qid, choice,
                                            clock=self.clock)
                self.say(f"owned: the owner answered {choice!r} on the "
                         f"{qid} card")
                return
            from .progression import QUESTION_PREFIX as ASK
            if not qid.startswith((QUESTION_PREFIX, ASK)):
                return
            # a progression card is kept under its whole id (brain/progression
            # reads "None of these yet" back from var/goals.json)
            key = qid if qid.startswith(ASK) else qid[len(QUESTION_PREFIX):]
            choice = str(getattr(event, "choice", "") or "")
            with self._lock:
                row = self.asked.setdefault(key, {"at": self.clock()})
                row["answered"] = choice
                row["answered_at"] = self.clock()
                self._save()
            self.say(f"goals: the owner answered {choice!r} on the "
                     f"{_pretty(key)} card")
        except Exception:
            pass

    # ---- ordering the quest givers ----------------------------------------
    def prefer_givers(self, names) -> tuple:
        """Quest givers, the ones paying a missing goal material first."""
        try:
            plan = self.plan or self.tick()
            if plan is None:
                return tuple(names)
            ranks = rank_givers(plan)
            out = prefer(names, ranks)
            self._narrate_order(tuple(names), out, ranks, plan)
            return out
        except Exception:
            return tuple(names)

    def _narrate_order(self, was: tuple, now: tuple, ranks: dict,
                       plan: Plan) -> None:
        if now == was or self._said_order == now:
            return
        self._said_order = now
        why = []
        for name in (n for n in now if n in ranks):
            mats = sorted({need.label for row in plan.rows if not row.owned
                           for need in row.missing for s in need.sources
                           if s.get("now") == DOES and s.get("giver") == name})
            if mats:
                why.append(f"{_pretty(name)} ({', '.join(mats)})")
        self.say("goals: the quest givers whose quests pay what the next "
                 "goals still need go first — " + "; ".join(why))

"""Planters: when to place one in the field being farmed, and when to harvest it.

WHY. The owner, 2026-10-06, asked for planters too. A planter grows in a field
and, harvested, gives nectar -- a buff by the
field's kind: Pine Tree's Comforting is x1.1-1.5 blue pollen and up to x2 the
convert rate at the hive -- pollen and items; and the bees sip from one in the
field they gather, which grows it (wiki Planter, read 2026-10-07). Up to three
may be out, one in a field and one of each kind.

HOW (wiki Planter, read 2026-10-07):
placed from the inventory while standing in a field -- its icon clicked and
the "Use ...?" answered Yes, as `act/inventory.use_item` does any item --
where the trip's gather starts, so the next trip to that field arrives beside
it; harvested by E on its prompt ("Harvest ... Planter"), Yes if the game
asks, its loot falling round it. Harvested only when grown, which gives all it
can: its growth time alone, shorter in its own fields (the sipping only
brings it sooner).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# EVERY PLANTER (N1-N3, wiki pages of each, read 2026-10-26 by the wiki's
# api.php wikitext): {key: (its title in the inventory, hours to grow alone,
# where it grows faster -- a flower colour, or the fields it names --, how much
# faster, its nectar bonus -- one number for every nectar, or by nectar TYPE)}.
# Two growth rules, as the wiki words them:
#   COLOUR: "+25% in fields with blue flowers" (Blue/Red Clay), "up to +50% in
#   fields with blue flowers" (Hydroponic, Heat-Treated, Petal): growth x (1 +
#   bonus x the field's share of that colour, FIELD_COLOURS). ASSUMED weighting
#   ("up to" says it scales); Natro's table (natro_macro.ahk <Field>Planters)
#   is the same formula: its Blue Clay rows are 1 + 0.25 x blue share within
#   0.003 (Stump too: the wiki's 0.85 blue of biases summing 1.125 is 0.756),
#   save Cactus (0.009 off); every colour row within 0.035. NOT the
#   old flat +25% on a field list here (Sunflower, Dandelion, Pineapple...):
#   MEASURED 2026-10-20/21 the Blue Clay took 6.44 h in Sunflower and 6.02 h in
#   Pineapple (var/planters.json harvests), not that list's 4.8 h.
#   FIELDS: "+25% in the Strawberry Field, Pineapple Patch, and Coconut Field"
#   (Candy), Pepper/Stump/Coconut/Mountain Top (Planter of Plenty, +50%). Two
#   say it by grow TIME: "-25% grow time in the Starting Zone" (Tacky: 8 h ->
#   6 h, x4/3) and "+30% Or 7 Hours in the 5 Bee Zone" (Pesticide: 10 h -> 7 h,
#   x10/7) -- their `faster` is the speed that gives those hours.
#   Natro uses x1.5/1.5/1.6 for Candy/Tacky/Pesticide there: UNVERIFIED either
#   way; the wiki's numbers kept (none of the three held, 2026-10-26).
# THE ORDER IS THE ORDER THEY GO OUT IN (next_step, errand_target): the
# reusable first, the single-use last -- Natro's <Field>Planters lists end with
# the Paper and the Ticket. "Only one of each type of planter can be planted at
# any time ... up to 3 planters active" (wiki Planters, read 2026-10-12).
# The Sticker Planter is left out: 100 Robux (wiki), never bought here.
PLANTERS = {
    # Blue HQ: 10M honey, 5 Magic Beans, 15 Blue Extract, 20 Soft Wax
    "blue_clay_planter": ("Blue Clay Planter", 6.0, "blue", 0.25,
                          {"comforting": 1.2, "refreshing": 1.2}),
    # Plastic Planter: Dapper Bear's Shop, 750,000 honey + 3 Magic Beans + 1
    # Soft Wax, reusable, ~2 h, no bonus (wiki Plastic_Planter, read 2026-10-12)
    # -- the third planter (brain/buyer SIDE_PURCHASES).
    "plastic_planter": ("Plastic Planter", 2.0, (), 0.0, 1.0),
    # Dapper Bear: 5M honey, 5 Magic Beans, 3 Jelly Beans, 5 Soft Wax
    "candy_planter": ("Candy Planter", 4.0, ("strawberry", "pineapple", "coconut"), 0.25,
                      {"motivating": 1.2}),
    # Red HQ: 10M honey, 5 Magic Beans, 15 Red Extract, 20 Soft Wax
    "red_clay_planter": ("Red Clay Planter", 6.0, "red", 0.25,
                         {"invigorating": 1.2, "satisfying": 1.2}),
    # Dapper Bear: 50M honey, 10 Magic Beans, 1 Purple Potion, 5 Hard + 20 Soft Wax
    "tacky_planter": ("Tacky Planter", 8.0,
                      ("sunflower", "dandelion", "mushroom", "blue_flower", "clover"), 1 / 3,
                      {"satisfying": 1.25, "comforting": 1.25}),
    # Dapper Bear: 750M honey, 25 Magic Beans, 25 Neonberries, 15 Glue, ...
    "pesticide_planter": ("Pesticide Planter", 10.0, ("strawberry", "spider", "bamboo"), 3 / 7,
                          {"satisfying": 1.3, "motivating": 1.3}),
    # Red HQ / Blue HQ: 750B honey, 75 Magic Beans, 750 extracts, ... 1 Turpentine
    "heat_treated_planter": ("Heat-Treated Planter", 12.0, "red", 0.5,
                             {"invigorating": 1.4, "motivating": 1.4}),
    "hydroponic_planter": ("Hydroponic Planter", 12.0, "blue", 0.5,
                           {"refreshing": 1.4, "comforting": 1.4}),
    # Petal Shop: 5T honey, ...
    "petal_planter": ("Petal Planter", 14.0, "white", 0.5,
                      {"comforting": 1.5, "satisfying": 1.5}),
    # Dapper Bear: 100T honey, ... "+50% of all Nectar Types"
    "planter_of_plenty": ("The Planter Of Plenty", 16.0,
                          ("pepper", "stump", "coconut", "mountain_top"), 0.5, 1.5),
    # Paper Planter: Pro Shop, 25,000 honey + 1 Sunflower Seed, single use,
    # 1 h in any field, x0.75 nectar (bee-swarm-simulator.fandom.com/wiki/
    # Paper_Planter, read 2026-10-10). The owner, 2026-10-10: nectar and
    # planters give a lot. MEASURED 2026-10-12/13: 1 h of time IN GAME (51.3%
    # -> 88.2% in 22.2 min, Stump) -- a shut game stops it (game_opened, below).
    "paper_planter": ("Paper Planter", 1.0, (), 0.0, 0.75),
    # Ticket Planter: x2 every nectar, ~2 h, single use, sold nowhere (Dapper
    # Bear's first talk, quests, the Samovar: wiki Ticket_Planter, read
    # 2026-10-12) -- it spends no tickets and drops some. MEASURED: "Ticket
    # Planter 1/100" in the bag (var/inventory/20261012-200035/page-04.png).
    "ticket_planter": ("Ticket Planter", 2.0, (), 0.0, 2.0),
    # Festive Planter: Beesmas only, single use, ~4 h, x3 nectar (wiki)
    "festive_planter": ("Festive Planter", 4.0, (), 0.0, 3.0),
}
# ONE USE EACH: holding more of them says nothing of the one out
SINGLE_USE = frozenset({"paper_planter", "ticket_planter", "festive_planter"})
PLACE_RETRY_S = 3600.0       # a placing that failed is tried again after this
# EACH FIELD'S FLOWERS, (white, red, blue): the wiki's FieldTable on each field's
# page (read 2026-10-26), made to sum to 1 -- Cactus and Mountain Top list
# "biases" (0.05/0.333/0.333; "Yes, the biases for red and blue are 0.333").
_FIELD_BIASES = {
    "sunflower": (0.7, 0.15, 0.15), "dandelion": (0.85, 0.05, 0.1),
    "mushroom": (0.3, 0.7, 0.0), "blue_flower": (0.3, 0.0, 0.7),
    "clover": (0.333, 0.333, 0.333), "strawberry": (0.25, 0.75, 0.0),
    "spider": (1.0, 0.0, 0.0), "bamboo": (0.25, 0.0, 0.75),
    "pineapple": (0.9, 0.05, 0.05), "stump": (0.2, 0.075, 0.85),
    "cactus": (0.05, 0.333, 0.333), "pumpkin": (0.6, 0.2, 0.2),
    "pine_tree": (0.15, 0.0, 0.85), "rose": (0.15, 0.85, 0.0),
    "mountain_top": (0.0, 0.333, 0.333), "coconut": (0.85, 0.08, 0.04),
    "pepper": (0.15, 0.85, 0.0),
}
FIELD_COLOURS = {f: dict(zip(("white", "red", "blue"), (c / sum(b) for c in b)))
                 for f, b in _FIELD_BIASES.items()}
# A NECTAR ALREADY FULL ENOUGH takes no planter: projected (read + the planters
# out for it) at or over this. Natro harvests early past 110 projected, and
# plants by its minimums below 100.
NECTAR_FULL = 100.0


# THE PLANTER ERRAND (Natro's Planters+ stage 1, the research's #1): a nectar
# under its minimum gets a planter, the largest weighted shortfall first. Natro's
# default minimums; the weights by priority rank, the order the blue
# hive guide's (blue pollen first, then blue convert, then honey, red last).
NECTAR_MIN = {"comforting": 70.0, "motivating": 80.0, "refreshing": 80.0,
              "satisfying": 80.0, "invigorating": 40.0}
NECTAR_ORDER = ("comforting", "motivating", "refreshing", "satisfying", "invigorating")
# Each nectar's fields, the blue ones first (where the hive gathers)
NECTAR_FIELDS = {
    "comforting": ("pine_tree", "bamboo", "dandelion"),
    "motivating": ("mushroom", "stump", "spider", "rose"),
    "refreshing": ("blue_flower", "strawberry", "coconut"),
    "satisfying": ("pineapple", "pumpkin", "sunflower"),
    "invigorating": ("clover", "mountain_top", "cactus", "pepper"),
}


# HARVESTED EARLY WHEN ITS NECTAR WOULD OVERFILL (backlog 1d): the
# growth at which it is harvested, by the nectar read now and projected --
# (current >= 99: at once), (projected >= 120: 55%), (current >= 90 and projected
# >= 110: 75%); else when fully grown. Past 100% (24 h) nectar is not kept.
OVERFILL = ((99.0, None, 0.0), (None, 120.0, 0.55), (90.0, 110.0, 0.75))


def harvest_at(state: dict, key: str, levels: dict | None = None) -> tuple:
    """(when it is due, early): when the planter `key` out should be harvested --
    fully grown, or sooner when its nectar would overfill (OVERFILL)."""
    body = (state.get("out") or {}).get(key) or {}
    field = body.get("field")
    at = float(body.get("at") or 0.0)
    full = at + planter_grow_s(state, key)
    nectar = NECTAR.get(field)
    now_level = (levels or {}).get(nectar) if nectar else None
    projected = nectar_projected(state, nectar, levels or {}) if nectar else None
    if now_level is None or projected is None:
        return full, False
    for cur_min, proj_min, growth in OVERFILL:
        if ((cur_min is None or now_level >= cur_min)
                and (proj_min is None or projected >= proj_min)):
            return at + growth * planter_grow_s(state, key), growth < 1.0
    return full, False


# NATRO'S "AUTO" HARVEST TIMING (backlog 1d2, research "Planters+ ... Harvest
# timing, 'auto' mode"): harvest at time-to-cap (the nectar bonus's own rate,
# so the planter's nectar does not run past NECTAR_FULL) or full growth,
# whichever is sooner. Kept separate from `harvest_at` rather than folded in:
# `harvest_at`'s docstring promises OVERFILL's three rungs exactly (and the
# unit tests pin that), and the two timings disagree in the middle of the
# range (OVERFILL only cuts a harvest short past its 90/110 or 120 rungs;
# "auto" starts trimming as soon as time-to-cap beats full growth).
#
# AUTO_MIN_GROWTH: the research's "auto" formula has no floor against cutting
# a planter short for a sliver of nectar in the ordinary (non-overfill) case
# -- its own floor (min(timeToCap, 0.5 h) when nb x gb < 1.2) is an hours
# figure, not a growth fraction, and does not generalize across planters.
# ASSUMPTION: borrow OVERFILL's own middle rung (0.55, its "projected >= 120"
# growth) as the floor's spirit here too, since OVERFILL's 0.0 rung is
# reserved for its own "current >= 99" emergency and stays an exception below.
AUTO_MIN_GROWTH = 0.55


def auto_harvest_at(state: dict, key: str, levels: dict | None = None) -> tuple:
    """(when it is due, early): Natro's "auto" timing for the planter `key`
    out -- time-to-cap or full growth, whichever is sooner (AUTO_MIN_GROWTH
    is the floor; OVERFILL's own at-once rung, current nectar >= 99, still
    overrides it, same as `harvest_at`)."""
    body = (state.get("out") or {}).get(key) or {}
    field = body.get("field")
    at = float(body.get("at") or 0.0)
    grow = planter_grow_s(state, key)
    full = at + grow
    nectar = NECTAR.get(field)
    now_level = (levels or {}).get(nectar) if (nectar and field) else None
    if now_level is None:
        return full, False
    if now_level >= 99.0:
        return at, True
    added_full = nectar_added(key, field)
    growth_to_cap = ((NECTAR_FULL - now_level) / added_full) if added_full > 0.0 else 1.0
    growth = max(AUTO_MIN_GROWTH, min(1.0, growth_to_cap))
    return at + growth * grow, growth < 1.0


# BATCHING HARVESTS INTO ONE TRIP (backlog 1e2, research "'Every X h' ... is
# moved earlier to match the soonest existing harvest, so harvests happen in
# one trip"): a planter not yet due is still worth walking to now if pulling
# its harvest forward costs it little growth. BATCH_WINDOW_S bounds how far
# ahead "due soon" looks; BATCH_MAX_GROWTH_LOST bounds the loss itself, since
# a short planter (Paper, 1 h) loses a much bigger share of its growth in 20
# min than a 6 h Blue Clay does -- the research's "every X h" mode has no such
# bound (it just moves to the soonest), so this gate is this module's own.
BATCH_WINDOW_S = 1200.0        # 20 min, a module default (the caller may pass another)
BATCH_MAX_GROWTH_LOST = 0.10   # pulling a harvest forward costs at most this much growth


def due_at(state: dict, key: str, levels: dict | None = None) -> tuple:
    """(due, early): the EARLIER of the overfill rule (`harvest_at`) and
    Natro's time-to-cap (`auto_harvest_at`), so the errand that walks out and
    the step at the planter (`next_step`) always agree (backlog 1d2)."""
    a, b = harvest_at(state, key, levels), auto_harvest_at(state, key, levels)
    return min(a, b, key=lambda r: r[0])


def batch_harvest_due(state: dict, levels: dict, now: float,
                       window_s: float = BATCH_WINDOW_S) -> list:
    """The planter keys worth harvesting on one trip `now`, soonest first:
    everything already due (harvest_at), plus anything due within `window_s`
    whose growth lost by harvesting now instead of at its due time is at most
    BATCH_MAX_GROWTH_LOST of its grow time."""
    out = state.get("out") or {}
    due = []
    for key in out:
        if key not in PLANTERS:
            continue
        when, _early = due_at(state, key, levels)
        if when <= now:
            due.append((when, key))
            continue
        if when > now + window_s:
            continue
        grow = planter_grow_s(state, key)
        lost = (when - now) / grow if grow else 0.0
        if lost <= BATCH_MAX_GROWTH_LOST:
            due.append((when, key))
    due.sort()
    return [key for _when, key in due]


# FIELD DEGRADATION (wiki Planter; backlog 4): a harvest wears its
# field by 1 h + growth x the planter's grow hours, to DEGRADE_CAP_H, wearing off
# an hour an hour; a planter placed there grows that many hours longer, and the
# errand prefers a fresher field by 1 / (1 + hours / DEGRADE_PENALTY_H).
DEGRADE_CAP_H = 48.0
DEGRADE_PENALTY_H = 12.0


def degradation_h(state: dict, field, now: float) -> float:
    row = (state.get("degradation") or {}).get(field) or {}
    since = float(row["at"]) if row.get("at") is not None else now
    hours = float(row.get("hours") or 0.0) - (now - since) / 3600.0
    return max(0.0, hours)


def planter_grow_s(state: dict, key: str) -> float:
    """The grow time of the planter `key` out: what it was placed with (its
    field's degradation added then), else the table's."""
    body = (state.get("out") or {}).get(key) or {}
    return float(body.get("grow") or 0.0) or grow_s(key, body.get("field"))


def _score(key: str, field: str, state: dict | None = None, now: float = 0.0) -> float:
    row = table_row(key, field)
    score = row[0] * row[1] if row is not None else 1.0
    if state is not None:
        score /= 1.0 + degradation_h(state, field, now) / DEGRADE_PENALTY_H
    return score


def switched_off(settings) -> str:
    """Why no planter may be placed, harvested or bought now -- '' when they
    may. `economy.planters` is the owner's switch for all of it (run_farm's
    planter_errand, tend_the_planter and paper_planters_due ask here);
    `economy.use_items` gated the planters before that switch was read, and
    still does. A settings object that cannot answer leaves them on."""
    for key in ("economy.planters", "economy.use_items"):
        try:
            if not bool(settings.bool(key)):
                return f"{key} is off"
        except Exception:
            pass
    return ""


# A22d: ONE PLANTER IN PINE TREE WHILE UNDER TWO WHIRLIGIGS ARE HELD. A
# Whirligig rescues a missed walk home (no rejoin, the Wealth Clock streak
# kept); none are sold, and planters drop them -- Pine Tree Forest's most often
# (BSS wiki). brain/stash RESCUE_KEEP keeps 2, the same bar.
WHIRLIGIG_WANT = 2
# the most single-use planters a bag plausibly holds; a "held" above it is a misread
HELD_PLAUSIBLE = 999
WHIRLIGIG_FIELD = "pine_tree"


def placeable(state: dict, owned, now: float) -> list:
    """The planter keys that may go out now, in PLANTERS order: owned (titles),
    not out, not lost, not given up, no failed placing in PLACE_RETRY_S."""
    out = state.get("out") or {}
    return [k for k, (label, *_r) in PLANTERS.items()
            if label in set(owned or ()) and k not in out
            and k not in (state.get("lost") or {}) and not given_up(state, k)
            and now - float((state.get("failed") or {}).get(k, -1e18)) >= PLACE_RETRY_S]


def errand_target(state: dict, owned, levels: dict, reachable, now: float,
                  whirligigs: int | None = None):
    """(field, why) for a planter errand now, or None: a planter out that has
    grown (harvest first), else -- `whirligigs` given and under WHIRLIGIG_WANT,
    no planter out in Pine Tree -- one held planter to Pine Tree, else a held
    planter for the nectar furthest under its minimum (projected) -- or, every
    nectar at its minimum, the lowest one under NECTAR_FULL -- in its best
    reachable field."""
    out = state.get("out") or {}
    grown = sorted((due_at(state, k, levels)[0], b.get("field"), k)
                   for k, b in out.items() if k in PLANTERS)
    for due, field, key in grown:
        if now >= due and field in reachable:
            early = due_at(state, key, levels)[1]
            return field, (f"the {PLANTERS[key][0]} in {field.replace('_', ' ')} "
                           + ("is harvested early: its nectar would overfill" if early
                              else "has grown"))
    held = placeable(state, owned, now)
    if not held:
        return None
    if (whirligigs is not None and whirligigs < WHIRLIGIG_WANT
            and WHIRLIGIG_FIELD in reachable
            and all(b.get("field") != WHIRLIGIG_FIELD for b in out.values())):
        return WHIRLIGIG_FIELD, (f"planting the {PLANTERS[held[0]][0]} in Pine Tree: Whirligigs "
                                 f"{whirligigs}, the rescue item that saves a rejoin")
    if not any(v is not None for v in (levels or {}).values()):
        return None
    planted = {NECTAR.get(b.get("field")) for b in out.values()}
    best, lowest = None, None
    for rank, nectar in enumerate(NECTAR_ORDER):
        if nectar in planted:
            continue
        projected = nectar_projected(state, nectar, levels)
        if projected is None or projected >= NECTAR_FULL:
            continue
        # THE FIELD WHERE THE PLANTER DOES BEST (Natro's nectar x growth bonus),
        # the blue order breaking ties
        options = [f for f in NECTAR_FIELDS[nectar] if f in reachable]
        field = max(options, key=lambda f: (_score(held[0], f, state, now), -options.index(f)),
                    default=None)
        if not field:
            continue
        why = (f"{nectar} nectar reads {levels.get(nectar):.0f}% (projected "
               f"{projected:.0f}%, its minimum {NECTAR_MIN[nectar]:.0f}%)")
        if projected < NECTAR_MIN[nectar]:
            need = (NECTAR_MIN[nectar] - projected) * max(0.5, 1.35 - 0.12 * rank)
            if best is None or need > best[0]:
                best = (need, field, why)
        # NATRO'S STAGE 2 (natro_macro.ahk 20959, "fill from lowest to highest
        # nectar percent"): every nectar at its minimum, a held planter still
        # goes out -- to the lowest -- rather than idle in the bag
        elif lowest is None or projected < lowest[0]:
            lowest = (projected, field, why + " -- every nectar is at its minimum; the lowest")
    pick = best or lowest
    return (pick[1], pick[2]) if pick else None


# NECTAR A GROWN PLANTER GIVES. "The amount of nectar and items it drops
# depends on the current growth of the planter" (wiki Planter, read
# 2026-10-26): ASSUMED from that, a grown one gives the same wherever it grew,
# so a faster field gives it sooner, not less -- Natro's estimator (its grow
# seconds x bonus / 864) had a slow field give MORE, while its own picking
# (nectar x growth) agrees with this. Here: its own hours alone x its nectar
# bonus (100% = 24 h, wiki Nectar), x NECTAR_SCALE -- MEASURED once: the Blue
# Clay grown in Pine Tree left Comforting at 21.1% two minutes after its harvest
# (tests/fixtures/nectar/comforting-21.jpg, 2026-10-11 00:14; vision/nectar
# reads it so), against 6 h x 1.2 = 30% -- ASSUMED from 0% before it (no read
# before that harvest in var/trips.jsonl). ponytail: one harvest; refit from the
# bar read before and after a few more (docs/pending/planners.md).
NECTAR_SCALE = 0.7


def nectar_added(key: str, field: str) -> float:
    """Percent of nectar one grown planter `key` in `field` adds."""
    row = table_row(key, field)
    return row[0] * PLANTERS[key][1] * 100.0 / 24.0 * NECTAR_SCALE


def nectar_projected(state: dict, nectar: str, levels: dict) -> float | None:
    """`levels[nectar]` (vision/nectar) plus what the planters out for that
    nectar will add; None when the level was not read."""
    now = levels.get(nectar)
    if now is None:
        return None
    return float(now) + sum(nectar_added(k, b.get("field"))
                            for k, b in (state.get("out") or {}).items()
                            if k in PLANTERS and NECTAR.get(b.get("field")) == nectar)
# THE NECTAR A FIELD GIVES (docs/pending/blue_progression_research.md, from the
# wiki): a harvested planter gives its field's nectar, so two planters out in
# fields of one nectar fill one buff twice and leave another empty.
NECTAR = {
    "dandelion": "comforting", "bamboo": "comforting", "pine_tree": "comforting",
    "mushroom": "motivating", "spider": "motivating", "stump": "motivating",
    "rose": "motivating",
    "blue_flower": "refreshing", "strawberry": "refreshing", "coconut": "refreshing",
    "sunflower": "satisfying", "pineapple": "satisfying", "pumpkin": "satisfying",
    "clover": "invigorating", "cactus": "invigorating", "mountain_top": "invigorating",
    "pepper": "invigorating",
}
# A grown planter whose prompt is not showing where the gather starts is
# walked to by its nameplate (vision/nameplate kind "planter": the UI-green bar
# with its name and growth inside, 14 of 15 on saved frames) -- MEASURED
# 2026-10-09/10: the owner's Blue Clay in Pine Tree was missed from the start
# spot 3 trips running and written off. Only when that walk too finds no
# prompt MISSES_TO_GIVE_UP trips running is it written off as lost.
MISSES_TO_GIVE_UP = 3
SEEK_ZOOM_OUT = 4           # "o" taps before the look round, undone after
SEEK_TURNS = 8               # 45 degrees a camera tap: one look per tap, a full circle
SEEK_PUSHES = 14             # short pushes toward the bar, a prompt read after each
SEEK_PUSH_S = 0.35           # at base speed (scaled by the caller)
SEEK_FACE_PX = 360           # further off the middle than this: a camera tap toward it first
SEEK_CENTRE_PX = 120         # the bar this far off the middle steers with A or D
SEEK_LOST_PUSHES = 3         # blind pushes after the bar is lost, then the seek stops (run_farm)
SEEK_STUCK_PX = 4            # a bar no further than this from the last push's: stuck (run_farm)


# THE LOOT A HARVEST DROPS ROUND THE PLANTER, walked over FIRST (tokens left
# too long vanish): a square spiral that ends where it began (w d s s a a w w d
# s nets zero), so the planter goes back on its own spot. Natro walks a loot
# pattern after every harvest; the loot by sight follows it.
LOOT_LEGS = ("w", "d", "s", "s", "a", "a", "w", "w", "d", "s")
LOOT_PUSH_S = 0.45
LOOT_SIGHT_SECONDS = 6.0     # the loot by sight after a harvest, each quarter (a kill gets 12)
LOOT_SIGHT_CHASES = 10       # a harvest drops more than a kill (bugrun.LOOT_SIGHT_CHASES 6)
LOOT_QUARTERS = 4            # facing each way in turn ...
LOOT_TURN_TAPS = 2           # ... 90 degrees a quarter: 4 x 2 taps is the full circle


def seek_keys(bar_x, width: int, centre_px: int = SEEK_CENTRE_PX) -> str:
    """The keys of one push toward a planter's bar at `bar_x` (None: not seen,
    straight on): W, with A or D while the bar is off the middle."""
    if bar_x is None:
        return "w"
    off = int(bar_x) - width // 2
    return "w" + ("a" if off < -centre_px else "d" if off > centre_px else "")


def face_the_bar(bar_x, width: int, turn, look, taps: int = 2,
                 face_px: int = SEEK_FACE_PX, stopped=lambda: False):
    """The camera turned toward a planter's bar at `bar_x`: `turn(step)` taps
    45 degrees (+1 right), `look()` is the bar's x after it (None: not seen).
    A tap at most `taps` times while the bar sits further off the middle than
    `face_px`. A TAP THAT LOSES THE BAR IS UNDONE and the pushes steer toward
    where it was last seen; they used to take it as dead ahead (the middle).
    MEASURED 2026-10-13 (var/planters/seek-20261013-*): 4 of the day's 8 face
    taps lost the bar, and in none was it ahead -- Bamboo 07:01 (070101-turn0:
    the Paper Planter beside the character, x 325 and 201 px wide; face-1 x
    530; face-2 none; then 14 pushes at the middle, never seen again), Pine
    Tree 02:28 (022824-turn3 x 377; face2 none; 14 blind pushes), 12:48 and
    13:07 (124843-face0, 130714-face0: the planter still far left, its bar
    unread beside a Mantis's green one). A near bar moves little for a tap
    (325 -> 530) and a far one a lot (054159: 159 -> 666).
    (the bar's x, the taps left turned)."""
    turned = 0
    for _ in range(taps):
        off = int(bar_x) - width // 2
        if abs(off) < face_px or stopped():
            break
        step = 1 if off > 0 else -1
        turn(step)
        turned += step
        seen = look()
        if seen is None:
            turn(-step)
            turned -= step
            break
        bar_x = seen
    return bar_x, turned


def reverse_keys(keys: str) -> str:
    """The push that undoes `keys`: W for S, A for D."""
    swap = {"w": "s", "s": "w", "a": "d", "d": "a"}
    return "".join(swap.get(k, k) for k in keys)


def load(path) -> dict:
    try:
        body = json.loads(Path(path).read_text())
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, path)


def table_row(key: str, field) -> tuple | None:
    """(nectar bonus, growth bonus, hours to grow) of the planter `key` in
    `field` -- the numbers the errand and brain/nectarplan pick by (PLANTERS'
    two growth rules, its nectar bonus by the field's nectar); None for an
    unknown planter."""
    if key not in PLANTERS:
        return None
    _label, hours, where, faster, nectar = PLANTERS[key]
    if isinstance(where, str):
        growth = 1.0 + faster * (FIELD_COLOURS.get(field) or {}).get(where, 0.0)
    else:
        growth = 1.0 + (faster if field in where else 0.0)
    bonus = nectar.get(NECTAR.get(field), 1.0) if isinstance(nectar, dict) else nectar
    return bonus, growth, hours / growth


def grow_s(key: str, field: str) -> float:
    return table_row(key, field)[2] * 3600.0


def next_step(state: dict, field: str, owned, now: float, levels: dict | None = None):
    """("harvest", key) when a planter out in `field` has grown; ("place",
    key) when one owned (`owned`: the labels of var/purchases.json's ok rows
    and of the planters the last inventory read counted) is neither out nor
    lost and no planter is in `field`; else None."""
    out = state.get("out") or {}
    for key, body in out.items():
        if key in PLANTERS and body.get("field") == field \
                and now >= due_at(state, key, levels)[0]:
            return "harvest", key
    if any(body.get("field") == field for body in out.values()):
        return None
    # A NECTAR ALREADY GROWING: not a second planter for it (the owner,
    # 2026-10-10: nectar and planters give a lot -- more kinds, not more of one)
    nectar = NECTAR.get(field)
    if nectar and any(NECTAR.get(body.get("field")) == nectar for body in out.values()):
        return None
    # A NECTAR ALREADY FULL takes no more (vision/nectar read, NECTAR_FULL)
    projected = nectar_projected(state, nectar, levels or {}) if nectar else None
    if projected is not None and projected >= NECTAR_FULL:
        return None
    for key, (label, *_rest) in PLANTERS.items():
        failed_at = (state.get("failed") or {}).get(key)
        if (label in set(owned or ()) and key not in out and key not in (state.get("lost") or {})
                and not given_up(state, key)
                and (failed_at is None or now - float(failed_at) >= PLACE_RETRY_S)):
            return "place", key
    return None


# THE TICKET PLANTER'S NAME, read loosely: tesseract made "Planter" into
# "Diantar" (2026-10-13 05:41:02, Mushroom). A word ending "ant[ae]r" after
# "ticket" -- never a price ("Spend 1 Ticket", "Ticket Eggs").
TICKET_PLANTER = re.compile(r"(?i)ticket\s+[a-z|!1]{0,3}ant[ae]r\b")


def harvest_prompt(said) -> bool:
    """Does the prompt read harvest a planter ("Harvest the Blue Clay Planter"),
    read loosely. MEASURED 2026-10-10 23:56 (var/planters/seek-20261010-235626-
    push5/6): the prompt is two lines and the read had only the first --
    'harvestp ïr êtglrue clay', 'harvesl r iêlrue clay i' -- so "planter" is not
    asked for: "harves" alone, letters only (no other prompt says it)."""
    letters = re.sub(r"[^a-z]", "", str(said or "").lower())
    return "harves" in letters


# A PLANTER GROWS ONLY WHILE THE GAME IS PLAYED ("A deployed planter will
# naturally grow over time only when you are playing the game", wiki Planters,
# read 2026-10-13). MEASURED 2026-10-12/13, the Paper in Stump placed 22:23:42:
# its bar read 51.3% at 23:35:57 and 88.2% at 23:58:07 -- 36.9% in 22.2 min,
# the wiki's 1 h exactly -- because the game was shut 22:37:00 (run-921 "stop
# requested") to 23:18:45 (run-936's join): 13.3 + 17.2 min in game = 51%.
# The 1 h was right; the wall clock was not. So the time the game was shut
# moves every planter out on by as long (`game_opened`), and a planter whose
# prompt still says it is growing is not harvested, its due time read from its
# bar (`still_growing`, `regrown`).
GROWING_RETRY = 0.15         # no growth read off its bar: looked at again after this share of its grow time


def game_closed(state: dict, now: float) -> dict:
    """The game shut at `now` (not kept for the next run): its planters stop."""
    return dict(state, closed_at=now)


def game_opened(state: dict, now: float) -> dict:
    """A fresh join at `now`: every planter out is moved on by the time the
    game was shut (`game_closed`), and the mark cleared."""
    out = {k: v for k, v in state.items() if k != "closed_at"}
    closed = state.get("closed_at")
    if closed is None or now <= float(closed):
        return out
    gap = now - float(closed)
    out["out"] = {k: (dict(b, at=float(b["at"]) + gap) if b.get("at") is not None else b)
                  for k, b in (state.get("out") or {}).items()}
    return out


def still_growing(said) -> bool:
    """Does the harvest prompt say the planter is not grown yet ("Harvest the
    Paper Planter (It's still growing)"; read "(lt's still. growing)" live,
    2026-10-13 01:22:48)?"""
    return "growing" in re.sub(r"[^a-z]", "", str(said or "").lower())


def bar_growth(text, label) -> float | None:
    """The growth, 0-1, its own bar reads ("Paper Planter (51.3%)"), else None."""
    low = " ".join(str(text or "").lower().split())
    if not label or str(label).lower() not in low:
        return None
    return _percent(low)


def _percent(text) -> float | None:
    """"(51.3%" in `text` as 0.513, else None."""
    m = re.search(r"\(\s*(\d{1,3}(?:[.,]\d)?)\s*%", str(text or ""))
    return min(1.0, float(m.group(1).replace(",", ".")) / 100.0) if m else None


# ITS GROWTH OFF ITS OWN BAR, wherever that is on screen (vision/nameplate
# .find_planter_bars), not only in the banner bands above the character
# (act/shoplook.PLANTER_BANNER_BANDS). MEASURED 2026-10-13: at 20:20:06 the
# Blue Clay in Spider read "still growing" and no growth -- booked 54 min on
# (GROWING_RETRY) -- and at 21:29 its bar read 81.4% at x 0-370, y 544-592
# (var/planters/seek-20261013-212933-turn0.jpg), far from those bands. Its
# white letters read black on white as act/stumpsnail.read_hp does, at each
# READ_SCALES, kept only when the two agree on the number and one names it.
# MEASURED on the 114 bars find_planter_bars gives on var/planters and 12,300
# route and incident frames: 28 read, none wrong ("100.0" x25, "81.4" x3) --
# 26 of the 28 bars 25 px tall or more (the two not: one cut by the screen's
# edge, one behind the spider web) and 2 of the 86 smaller ones. A one-scale
# read was tried and dropped: it read "1.3" for 51.3% and "499.6", "200.0",
# "109.0" off small bars. A near bar -- standing at it -- is what reads.
READ_SCALES = (4, 3)
READ_INK = (170, 70)           # its letters: value at least, saturation at most
READ_ASPECT = 9.0              # the whole bar from its left edge: 7.2-7.4 x its height
# The letters of the four planters held so far only: the 28 reads above were
# measured with this whitelist; a new planter's letters join it when its bar
# is measured (an "o" beside "0" is a new way to misread "100.0").
READ_CHARS = "".join(sorted({c for label in ("Blue Clay Planter", "Plastic Planter",
                                             "Paper Planter", "Ticket Planter") for c in label}
                            | set("0123456789.%() ")))


def read_growth(frame, label, run=None, boxes=None) -> float | None:
    """The growth, 0-1, the bar titled `label` reads anywhere on screen, or
    None (READ_*). `boxes` (x, y, w, h) instead of find_planter_bars'."""
    import subprocess
    import cv2
    import numpy as np
    from ..vision import nameplate
    from ..vision.beemenu import LANGUAGE, TESSERACT
    if frame is None or getattr(frame, "size", 0) == 0 or not label:
        return None
    name = re.sub(r"[^a-z]", "", str(label).lower())
    for x, y, _w, h in (nameplate.find_planter_bars(frame) if boxes is None else boxes):
        crop = frame[y:y + h, max(0, x - 4):min(frame.shape[1], x + int(READ_ASPECT * h)), :3]
        texts = []
        for scale in READ_SCALES:
            hsv = cv2.cvtColor(cv2.resize(crop, None, fx=scale, fy=scale,
                                          interpolation=cv2.INTER_CUBIC), cv2.COLOR_BGR2HSV)
            ink = (hsv[:, :, 2] >= READ_INK[0]) & (hsv[:, :, 1] <= READ_INK[1])
            page = cv2.copyMakeBorder(np.where(ink, 0, 255).astype(np.uint8), 20, 20, 20, 20,
                                      cv2.BORDER_CONSTANT, value=255)
            ok, png = cv2.imencode(".png", page)
            try:
                out = (run or subprocess.run)(
                    [TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "7",
                     "-c", f"tessedit_char_whitelist={READ_CHARS}"],
                    input=png.tobytes(), capture_output=True, timeout=8.0) if ok else None
            except (OSError, subprocess.SubprocessError):
                out = None
            raw = getattr(out, "stdout", b"") or b""
            texts.append(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw))
        reads = {_percent(t) for t in texts}
        if (len(reads) == 1 and None not in reads
                and any(name in re.sub(r"[^a-z]", "", t.lower()) for t in texts)):
            return reads.pop()
    return None


def regrown(state: dict, key: str, now: float, growth: float | None = None) -> dict:
    """The planter `key` seen still growing at `now`: booked so it is due when
    its bar says it will be full (`growth` read off it), else GROWING_RETRY of
    its grow time from now. Seen, so not a miss."""
    out = dict(state)
    body = dict((state.get("out") or {}).get(key) or {})
    if not body:
        return out
    grow = planter_grow_s(state, key)
    left = (1.0 - growth) if growth is not None else GROWING_RETRY
    body["at"] = now + left * grow - grow
    body["misses"] = 0
    out["out"] = dict(state.get("out") or {}, **{key: body})
    return out


def placed(state: dict, key: str, field: str, now: float, held: int | None = None) -> dict:
    """`key` out in `field` from `now`; `held`: the bag's count of it just
    before (a single-use one's next read must count fewer, `reconcile`)."""
    out = dict(state)
    grow = grow_s(key, field) + degradation_h(state, field, now) * 3600.0
    body = {"field": field, "at": now, "misses": 0, "grow": grow}
    if held is not None:
        body["held"] = int(held)
    out["out"] = dict(state.get("out") or {}, **{key: body})
    for book in ("failed", "fails", "lost", "pending"):   # placed: not failing, not lost
        out[book] = {k: v for k, v in (state.get(book) or {}).items() if k != key}
    return out


def unverified(state: dict, key: str, field: str, now: float, held: int | None = None) -> dict:
    """"Place ...?" answered Yes and closed, but no sign of the planter after
    (`placement_seen`): held, not out -- a failed placing, tried again after
    PLACE_RETRY_S -- with the try kept as "pending", so the next inventory read
    (`reconcile`) books it out after all if the bag no longer has it.
    MEASURED 2026-10-12: the Ticket in Bamboo 22:24:53 and the Blue Clay in
    Pine Tree 16:43:18 both "answered Yes ... and the question closed", and
    both were still in the bag at the next read (23:25 "ticket_planter 1";
    20:00 "Blue Clay Planter 1/1")."""
    out = failed(state, key, now)
    try_ = {"field": field, "at": now}
    if held is not None:
        try_["held"] = int(held)
    out["pending"] = dict(state.get("pending") or {}, **{key: try_})
    return out


def placement_seen(said) -> bool:
    """Is the prompt read just after a placing the planter's own? The
    character stands on it, so its prompt shows: MEASURED 2026-10-12 22:23:44,
    2 s after the Paper went into Stump (92 -> 91), the panel read "Harvest the
    Paper Planter (It's still growing)" (var/vlm_cache/ed/ede06ab9...); after
    the Ticket at 22:24:53, which stayed in the bag, no prompt was read at all."""
    return harvest_prompt(said)


def banner_names(text, label) -> bool:
    """Does the planter's own bar read "<label> (n%)" -- the other proof of a
    placing, when the camera faces away from its prompt (act/shoplook
    .white_banner_text)?"""
    low = " ".join(str(text or "").lower().split())
    return bool(label) and str(label).lower() in low and "(" in low


# THE BAR IS SMALL. MEASURED 2026-10-21 on var/planters/place-*-unseen.jpg: of 11
# placings filed "no planter's prompt showed" since 13 Oct, 9 show the planter's
# own bar ("Blue Clay Planter (0.0%)", y 190-470 of 1080) that the 120 px bands
# (shoplook.PLANTER_BANNER_BANDS) read as noise; thin strips, 4x smooth, white
# over 180, and a fuzzy name ("Rlue Clav Planter", "Blus Clay Planuter") read
# all 9 -- and nothing on three walk frames with no planter. ~10 s at worst,
# only after the bands missed.
BAR_STRIPS = tuple((560, y, 1360, y + 45) for y in range(150, 560, 20))
BAR_MATCH = 0.8


def bar_names_fuzzy(text, label, cut: float = BAR_MATCH) -> bool:
    """`label` in `text` letters only, allowing OCR slips: the best window's
    similarity at least `cut`."""
    import difflib
    a = re.sub(r"[^a-z]", "", str(text or "").lower())
    b = re.sub(r"[^a-z]", "", str(label or "").lower())
    if not a or not b:
        return False
    return max(difflib.SequenceMatcher(None, a[i:i + len(b) + 2], b).ratio()
               for i in range(max(1, len(a) - len(b) + 3))) >= cut


# A PLANTER THAT KEEPS FAILING TO GO DOWN IS LEFT IN THE BAG (Natro: 10 failed
# placings lower its planter limit, backlog 1f): this many in a row and it is not
# tried again until a placing of it works (`placed` clears the count).
PLACE_FAILS_TO_STOP = 10


def failed(state: dict, key: str, now: float) -> dict:
    fails = dict(state.get("fails") or {})
    fails[key] = int(fails.get(key, 0) or 0) + 1
    return dict(state, failed=dict(state.get("failed") or {}, **{key: now}), fails=fails)


def given_up(state: dict, key: str) -> bool:
    return int((state.get("fails") or {}).get(key, 0) or 0) >= PLACE_FAILS_TO_STOP


def harvested(state: dict, key: str, now: float) -> dict:
    out = dict(state)
    body = (state.get("out") or {}).get(key) or {}
    field = body.get("field")
    if field:
        grow = planter_grow_s(state, key)
        placed_at = float(body["at"]) if body.get("at") is not None else now
        growth = min(1.0, max(0.0, (now - placed_at) / grow)) if grow else 1.0
        hours = min(DEGRADE_CAP_H, degradation_h(state, field, now)
                    + 1.0 + growth * grow_s(key, field) / 3600.0)
        out["degradation"] = dict(state.get("degradation") or {},
                                  **{field: {"hours": round(hours, 3), "at": now}})
    out["out"] = {k: v for k, v in (state.get("out") or {}).items() if k != key}
    out["lost"] = {k: v for k, v in (state.get("lost") or {}).items() if k != key}
    out["harvests"] = (list(state.get("harvests") or [])
                       + [{"key": key, "field": body.get("field"), "placed": body.get("at"),
                           "at": now}])[-50:]
    return out


def missed(state: dict, key: str, now: float) -> dict:
    """A due trip without its prompt; the MISSES_TO_GIVE_UPth writes it off."""
    out = dict(state)
    body = dict((state.get("out") or {}).get(key) or {})
    body["misses"] = int(body.get("misses") or 0) + 1
    if body["misses"] >= MISSES_TO_GIVE_UP:
        out["out"] = {k: v for k, v in (state.get("out") or {}).items() if k != key}
        out["lost"] = dict(state.get("lost") or {}, **{key: dict(body, lost_at=now)})
    else:
        out["out"] = dict(state.get("out") or {}, **{key: body})
    return out


def reconcile(state: dict, held: dict, read_at: float) -> dict:
    """`state` squared with an inventory read made at `read_at` (`held`: {key:
    count}), for what was recorded before the read:
    - a reusable planter the read counted in the bag is neither out nor lost.
      A planter out is not in the list -- MEASURED 2026-10-11 22:43 to 10-12
      02:18, ten "no row titled 'Blue Clay Planter'" while it stood in Rose --
      and 2026-10-12 the 16:43 place in Pine Tree answered Yes, yet the 20:00
      read listed "Blue Clay Planter 1/1" (var/inventory/20261012-200035/
      page-04.png): recorded out till 03:37, it sat in the bag.
    - a single-use one out whose count did not fall below its count at the
      placing (its "held") is not out: MEASURED 2026-10-12, the Ticket "placed"
      in Bamboo 22:24:53 with 1 held, and the 23:25 read "ticket_planter 1";
      the Paper placed in Stump 22:23:42 with 92 held really went (read 91).
    - a "pending" try (`unverified`) is settled: the bag still has it -- the
      try failed, dropped; it is gone (a reusable not listed, a single-use
      below its "held") -- it went out after all, booked out from the try.
      # ponytail: an absent row is taken as out; a misread title books a
      # phantom, which three missed harvests write off (MISSES_TO_GIVE_UP)."""
    out = dict(state)

    def still_held(k, body, lost=False) -> bool:
        n = int(held.get(k) or 0)
        if k not in SINGLE_USE:
            return n > 0
        was = (body or {}).get("held")
        # A MISREAD "held" IS NO COUNT. MEASURED 2026-10-21 (var/planters.json):
        # the Paper lost on ~14 Oct was booked with held 72100 -- the bag held 64
        # -- so `n >= was` never passed, it stayed lost, and no second planter
        # went out for a week. Above HELD_PLAUSIBLE it is taken as uncounted.
        if was is not None and int(was) > HELD_PLAUSIBLE:
            was = None
        if was is None:
            # A LOST ONE booked before its count was kept: any left in the bag
            # may go out -- were it really out, the game refuses a second of
            # its kind and `unverified` holds it again
            return lost and n > 0
        return n >= int(was)

    for book, stamp in (("out", "at"), ("lost", "lost_at")):
        rows = state.get(book) or {}
        back = {k for k, body in rows.items()
                if k in PLANTERS and still_held(k, body, book == "lost")
                and float((body or {}).get(stamp) or 0.0) < read_at}
        if back:
            out[book] = {k: v for k, v in rows.items() if k not in back}
    for k, try_ in (state.get("pending") or {}).items():
        if k not in PLANTERS or float((try_ or {}).get("at") or 0.0) >= read_at:
            continue
        if still_held(k, try_) or (k in SINGLE_USE and (try_ or {}).get("held") is None):
            out["pending"] = {j: v for j, v in (out.get("pending") or {}).items() if j != k}
        else:
            out = placed(out, k, try_["field"], float(try_["at"]), try_.get("held"))
    return out


if __name__ == "__main__":
    H = 3600.0

    # auto_harvest_at: no nectar read -> full growth, not early
    st = placed({}, "blue_clay_planter", "pine_tree", 0.0)
    grow = planter_grow_s(st, "blue_clay_planter")
    assert auto_harvest_at(st, "blue_clay_planter", {}) == (grow, False)

    # time-to-cap beats full growth -- comforting reads 80%, the Blue Clay in
    # Pine Tree adds 1.2 x 6 h x 100/24 x 0.7 = 21% fully grown -> growth to
    # cap (100-80)/21 = 0.95, inside [AUTO_MIN_GROWTH, 1] so it wins over 1.0
    added_full = nectar_added("blue_clay_planter", "pine_tree")
    expect_growth = (100.0 - 80.0) / added_full
    assert AUTO_MIN_GROWTH < expect_growth < 1.0
    due, early = auto_harvest_at(st, "blue_clay_planter", {"comforting": 80.0})
    assert abs(due - expect_growth * grow) < 1e-6 and early

    # AUTO_MIN_GROWTH floor -- nectar reads 95% (below the >=99 override),
    # time-to-cap would be (100-95)/24.8 = 0.20, floored to AUTO_MIN_GROWTH
    # instead of cutting the planter short further
    due, early = auto_harvest_at(st, "blue_clay_planter", {"comforting": 95.0})
    assert abs(due - AUTO_MIN_GROWTH * grow) < 1e-6 and early

    # OVERFILL's own at-once rung still overrides the floor
    due, early = auto_harvest_at(st, "blue_clay_planter", {"comforting": 99.0})
    assert due == 0.0 and early

    # fully-grown nectar read stays at full growth (time-to-cap >= full)
    due, early = auto_harvest_at(st, "blue_clay_planter", {"comforting": 10.0})
    assert due == grow and not early

    # batch_harvest_due: "at"/"grow" set directly (bypassing the field table)
    # so the three gates -- already due, due soon with little lost, due soon
    # but too much lost -- are each exercised on their own. No nectar levels
    # are given, so harvest_at falls back to full growth for both (full, False).
    def body(field, at, grow):
        return {"field": field, "at": at, "grow": grow}
    state2 = {"out": {"paper_planter": body("pumpkin", 0.0, 200.0),        # due at 200
                      "blue_clay_planter": body("pine_tree", 0.0, 1000.0)}}  # due at 1000

    # both already due: soonest first
    assert batch_harvest_due(state2, {}, 1000.0, window_s=0.0) == \
        ["paper_planter", "blue_clay_planter"]

    # blue_clay not due yet, but only 10s (1%) of its 1000s grow would be
    # lost pulling it forward -- within BATCH_MAX_GROWTH_LOST, batched
    assert batch_harvest_due(state2, {}, 990.0, window_s=20.0) == \
        ["paper_planter", "blue_clay_planter"]

    # blue_clay 800s off: inside the (default, 20 min) window, but that is
    # 80% of its growth -- too much, left for its own trip
    assert batch_harvest_due(state2, {}, 200.0, window_s=BATCH_WINDOW_S) == ["paper_planter"]

    print("planter.py: all checks passed")

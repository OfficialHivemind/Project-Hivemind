"""N4, KEEPING THE NECTARS UP: which field a trip should prefer while a nectar
is low, and which Nectar Vial would be used.

WHY. The owner, 2026-10-10: nectar is "super super important"; a viewer
(koj1l, Discord #suggestions, 2026-10-18) asked for auto nectar vials.

WHAT THE BOT SEES (MEASURED). vision/nectar reads the five nectar icons off the
buff bar; var/trips.jsonl carries the levels every trip ran under -- Comforting
5-29% on 2026-10-19, the only nectar this account has held, so the other four
icons' colours are Natro's, not yet seen here. The inventory read has never
counted a Nectar Vial (var/inventory.json, 2026-10-19: none held).

THE FIELD NUDGE (`field_for`, nectar.keep_up). Gathering alone gives no nectar;
"bees standing in the field sip the planter: they ... grant nectar, and add
growth" (wiki Planter, data/knowledge/economy.yaml). So the nudge only sends a
trip to a field where OUR planter grows the low nectar, and only when that field
scores within NUDGE_SHARE of the planned one -- the honey given up is capped.
How much nectar a trip there adds is NOT MEASURED: the badge says so.

THE VIAL (`vial_to_use`). A vial gives 4 h of its nectar [assumed: wiki Nectar
Condenser via search, robloxden], one ~17% of the 24 h bar. act/inventory.use_item
is a tested use path, but no vial has ever been on the page and a Comforting
Vial is a Diamond Mask material (goals.yaml), so it is LOOK-ONLY (VIAL_LIVE):
the log says which vial it would use and why. Only spare vials (brain/stash:
none a goal keeps) are ever named.

THE CONDENSER is not here: it stands past the Windy Bee Gate (35 bees
[assumed, wiki]) and this hive has 34 (account.yaml) -- see economy.yaml.
"""
from __future__ import annotations

from ..act.planter import NECTAR, NECTAR_MIN, NECTAR_ORDER

# The nectar field may score this share of the planned field's score and
# still be chosen. ponytail: a flat share, not a priced trade -- price it once
# reflect.nectar_effect has trips under each nectar to compare.
NUDGE_SHARE = 0.85
VIAL_LIVE = False                    # look-only: no vial ever read (module doc)
VIAL_HOURS = 4.0                     # [assumed] wiki Nectar Condenser
VIAL_PCT = 100.0 * VIAL_HOURS / 24.0
VIAL_KEYS = {n: f"{n}_vial" for n in NECTAR_ORDER}   # consumables.yaml keys


def low(levels: dict) -> list[str]:
    """The nectars READ under their minimum (planter.NECTAR_MIN), furthest
    under first; an unread one (None) is never low."""
    under = [(levels[n] - NECTAR_MIN[n], n) for n in NECTAR_ORDER
             if levels.get(n) is not None and levels[n] < NECTAR_MIN[n]]
    return [n for _, n in sorted(under)]


def field_for(levels: dict, planters_out: dict, alternatives, planned):
    """(field, why) for a trip to the field where our planter grows a low
    nectar, when it scores within NUDGE_SHARE of `planned`; else None."""
    scores = {a.field: a.score for a in alternatives if getattr(a, "reachable", True)}
    base = scores.get(planned)
    if not base or base <= 0:
        return None
    # A QUEST'S FIELD STAYS: quests.first and a one-trip quest step outrank nectar
    mine = next((a for a in alternatives if a.field == planned), None)
    if getattr(mine, "quest_first", False) or getattr(mine, "quick_quest", False):
        return None
    grown = {b.get("field") for b in (planters_out or {}).values()}
    for nectar in low(levels):
        if NECTAR.get(planned) == nectar and planned in grown:
            return None                  # the planned trip already feeds it
        for field in sorted(f for f in grown if NECTAR.get(f) == nectar and f != planned):
            score = scores.get(field)
            if score and score >= NUDGE_SHARE * base:
                return field, (f"{nectar} nectar reads {levels[nectar]:.0f}% (under its "
                               f"{NECTAR_MIN[nectar]:.0f}%) and our planter grows in "
                               f"{field.replace('_', ' ')}: the bees sip it there, for "
                               f"{100 * (1 - score / base):.0f}% less than "
                               f"{planned.replace('_', ' ')}'s score")
    return None


def vial_to_use(levels: dict, spare: dict):
    """(nectar, vial key, why) for the lowest low nectar with a spare vial,
    when one vial does not overfill it; `spare` is {vial key: spare count}."""
    for nectar in low(levels):
        key = VIAL_KEYS[nectar]
        if (spare.get(key) or 0) > 0 and levels[nectar] + VIAL_PCT <= 100.0:
            return nectar, key, (f"{nectar} nectar reads {levels[nectar]:.0f}% (under its "
                                 f"{NECTAR_MIN[nectar]:.0f}%); a vial adds ~{VIAL_PCT:.0f}% "
                                 f"({VIAL_HOURS:.0f} h) and {spare[key]} are spare")
    return None

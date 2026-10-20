"""PRO TESTER, ROUND 1 (19 Oct 2026): an expert's answers, relayed by the
owner, as the bot's rules. Each is an EXPERT PRIOR, not a measurement: where
the bot measures the same thing (a field's pollen/s, a boost's gain) the
measurement wins, and every rule here says so where it applies. The rules and
their source lines are data/knowledge/playbook.yaml (`confidence: expert`,
ids `pro_*`); the code that follows each is named there in `followed_by`.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

SOURCE = "pro tester round 1, 19 Oct 2026"

# 1. "pine tree is always best." A tie-breaker (brain/decide Planner.rank):
# Pine Tree goes first when it scores within PINE_TREE_CLOSE of the leader, or
# the leader is not measured at all -- never past a field MEASURED clearly
# better, a quest-first field, or a field a quest names.
PINE_TREE = "pine_tree"
PINE_TREE_CLOSE = 0.90

# 2. "convert at 95% or higher": world/settings gather.convert_at's default.
CONVERT_AT = 95

# 5. + 6. WHO IS VISITED FIRST (run_farm rebuild_queue): Mother Bear, then
# Black Bear (5), then the givers whose rewards are worth chasing (6: Spirit's
# 3 Spirit Petals, Science Bear's translators). The Polar Bear is third until
# every main questline but Spirit's is done, then first. The Panda Bear is
# "important but no need to rush": unranked, so he keeps his place in the walk
# order. Unranked givers keep their order behind these (a stable sort).
GIVER_RANK = {"mother_bear": 1, "black_bear": 2, "polar_bear": 3,
              "spirit_bear": 4, "science_bear": 4}
# THE BOT DOES NOT READ WHICH QUESTLINES ARE FINISHED. Until it does, unknown
# is "not done": the Polar Bear stays third, and his quests' fields lose the
# "first of the quest fields" place (questneeds.PRIORITY_GIVERS) they had.
MAIN_LINES_DONE = False

# 7. "don't auto goo quests until you have gummy bee or gummy mask/boots".
GUMMY_BEE = "gummy"                        # var/bees.json `bees` key
GUMMY_GEAR = ("gummy_mask", "gummy_boots")  # brain/owned keys

# 8. "field boosters are mostly for pollen in weaker fields (0 bee/starter
# zone)": a field whose world.yaml `bees_required` is 0.

# 9. "only use materials for crafting in early stages; at hive level 16 start
# boosting with them." A material is consumables.yaml `role: material`.
MATERIAL_BOOST_HIVE_LEVEL = 16

# 10. "loaded dice ..., then glitter, a super smoothie or purple potion. Use
# the glitter 5 minutes after the loaded dice". LOOK-ONLY: the bot never uses
# a Loaded Dice, a Super Smoothie or a Purple Potion.
COMBO_GLITTER_AFTER_S = 5 * 60.0

# 4. "when macroing, sprinkler in the center of the movement pattern". LOOK-
# ONLY: placing it there is a walk no tested route makes yet.
SPRINKLER_AT_PATTERN_CENTRE_LIVE = False


def pine_tree_first(ranked: list, quest_names=lambda field: False) -> list:
    """`ranked` (best first) with Pine Tree moved to the front when rule 1
    says so; `quest_names(field)` is True for a field a quest names."""
    pine = next((s for s in ranked if s.field == PINE_TREE), None)
    if pine is None or pine is ranked[0] or not pine.reachable or pine.score <= 0:
        return ranked
    lead = ranked[0]
    if lead.quest_first or quest_names(lead.field):
        return ranked
    if lead.rate is not None and pine.score < PINE_TREE_CLOSE * lead.score:
        return ranked                       # measured clearly better: it wins
    pine.why += (f"; {SOURCE}: Pine Tree is the best field, so it goes ahead of "
                 f"{lead.pretty} ({lead.score:,.0f}, "
                 + ("never measured" if lead.rate is None else
                    f"within {1 - PINE_TREE_CLOSE:.0%}") + ")")
    return [pine] + [s for s in ranked if s is not pine]


def giver_order(names, mains_done: bool = MAIN_LINES_DONE) -> tuple:
    """`names` (quest givers) in rule 5/6's order; unranked ones keep theirs."""
    ranks = dict(GIVER_RANK, polar_bear=0) if mains_done else GIVER_RANK
    big = max(ranks.values()) + 1
    return tuple(sorted(names, key=lambda n: ranks.get(n, big)))


def gummy_owned(var_root, owned_keys=()) -> str:
    """The Gummy thing the account owns ("Gummy Bee", "Gummy Mask", ...), or ''
    -- unknown is not owned. `owned_keys`: brain/owned.owned(...)'s keys."""
    try:
        bees = json.loads((Path(var_root) / "bees.json").read_text()).get("bees") or {}
        if int(bees.get(GUMMY_BEE) or 0) > 0:
            return "Gummy Bee"
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    have = next((k for k in GUMMY_GEAR if k in set(owned_keys or ())), "")
    return have.replace("_", " ").title()


# WHERE A GOO QUEST'S GOO COMES FROM (ROADMAP Q7, settings quests.goo_source).
GOO_FROM_GUMDROPS, GOO_FROM_GUMMY, GOO_FROM_BOTH = "gumdrops", "gummy bee ability", "both"


def gumdrops_for_goo(source, owned: str) -> tuple[bool, str]:
    """(throw gumdrops?, a line to say or ''), for a goo quest step.
    `owned` is gummy_owned's answer. 'gummy bee ability' throws none only when
    the Gummy Bee itself is owned (the mask and boots make no goo of their
    own); without it the step would stall, so gumdrops are thrown and the line
    says why. Anything unknown reads as 'gumdrops', the old behaviour."""
    if source == GOO_FROM_GUMMY:
        if owned == "Gummy Bee":
            return False, ("gumdrops: none thrown for the goo quest — the goo comes "
                           "from the Gummy Bee's ability (Goo for goo quests from)")
        return True, ("gumdrops: 'gummy bee ability' is chosen but no Gummy Bee is "
                      "known to be owned, so gumdrops are thrown for the goo quest")
    return True, ""


def starter_field(body) -> bool:
    """A 0-bee (starter zone) field, by its world.yaml row."""
    return int((body or {}).get("bees_required", -1)) == 0


def material_boost_ok(role: str | None, hive_level) -> tuple[bool, str]:
    """(may a boost spend it, why) for an item of consumables.yaml `role`."""
    if role != "material":
        return True, ""
    if hive_level is None:
        return False, (f"{SOURCE}: materials are for crafting until hive level "
                       f"{MATERIAL_BOOST_HIVE_LEVEL}, and the hive level is not known")
    if float(hive_level) < MATERIAL_BOOST_HIVE_LEVEL:
        return False, (f"{SOURCE}: materials are for crafting until hive level "
                       f"{MATERIAL_BOOST_HIVE_LEVEL} (hive level {hive_level})")
    return True, ""


def hive_level(account: dict | None):
    """account.yaml's `hive.level` (the owner's word or a read), or None."""
    try:
        level = ((account or {}).get("hive") or {}).get("level")
        return float(level) if level is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def big_combo(field, held: dict) -> str:
    """Rule 10's plan for `field` as a sentence, from `held` {item: count or
    None}: what it would do, or what it lacks."""
    if not field:
        return ""
    name = str(field).replace("_", " ")
    drink = next((k for k in ("super_smoothie", "purple_potion") if held.get(k)), None)
    lacks = [k.replace("_", " ") for k in ("loaded_dice", "glitter") if not held.get(k)]
    if not drink:
        lacks.append("super smoothie or purple potion")
    if lacks:
        return f"big boost combo on {name}: not now, no {', '.join(lacks)} counted"
    return (f"big boost combo: Loaded Dice now on {name}, Glitter at "
            f"+{COMBO_GLITTER_AFTER_S / 60:.0f}:00, then the {drink.replace('_', ' ')}, "
            f"so the field boost runs as long as the drink ({SOURCE})")


def pattern_centre(steps) -> tuple[float, float]:
    """(right, forward) studs from a pattern's start to the centre of the box
    its path covers, in the start's camera frame. `steps`: the route runner's
    ops (`walk` with keys and studs, `camera` left/right = 45 degrees)."""
    unit = {"w": (0.0, 1.0), "s": (0.0, -1.0), "a": (-1.0, 0.0), "d": (1.0, 0.0)}
    x = y = 0.0
    heading = 0.0                     # radians, positive = turned right
    xs, ys = [0.0], [0.0]
    for s in steps or ():
        if s.get("op") == "camera":
            heading += math.radians(45.0) * (1 if s.get("direction") == "right" else -1)
            continue
        if s.get("op") != "walk":
            continue
        vx = sum(unit.get(k, (0.0, 0.0))[0] for k in str(s.get("keys", "")))
        vy = sum(unit.get(k, (0.0, 0.0))[1] for k in str(s.get("keys", "")))
        norm = math.hypot(vx, vy)
        if not norm:
            continue
        d = float(s.get("studs") or 0.0) / norm
        c, si = math.cos(heading), math.sin(heading)
        x += d * (vx * c + vy * si)
        y += d * (vy * c - vx * si)
        xs.append(x)
        ys.append(y)
    return ((max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0)


# ======================================================================
# PRO TESTER, ROUND 2 (answers 11-20, relayed by the owner 2026-10-20,
# var/pro_answers/round2-*.txt). The same footing as round 1: expert priors,
# playbook.yaml `pro_*` with `followed_by`; the measurement wins where there is
# one. docs/pending/pro-round2.md is the table.
# ======================================================================
SOURCE2 = "pro tester round 2, 20 Oct 2026"

# 11. "petal belt, crimson guard, coconut clogs, coconut canister, petal wand,
# supreme saturator, tidepopper/ dark scythe." A SUGGESTED order the Goals tab
# can offer (data/knowledge/goals.yaml `suggested_orders.pro_tester`), never
# the owner's own: `goals.order` and `default_order` are untouched.
SUGGESTED_ORDER = "pro_tester"


def _entry_from_progression(key: str, colour: str) -> dict | None:
    """A goals.yaml-shaped entry for `key` from progression/<colour>.yaml (its
    colour first, then the others): the wiki-sourced price and recipe there."""
    from . import progression
    for hive in [colour] + [h for h in progression.HIVES if h != colour]:
        for _i, goal in progression._goals(progression.load(hive)):
            if goal.get("id") == key:
                cost = goal.get("cost") or {}
                return {"label": goal.get("label") or key, "slot": goal.get("slot", ""),
                        "honey": progression._honey(goal),
                        "materials": dict(cost.get("items") or {}),
                        "what": str(goal.get("why") or ""),
                        "origin": f"suggested by the {SOURCE2}",
                        "source": f"data/knowledge/progression/{hive}.yaml "
                                  f"({', '.join(goal.get('source') or [])})"}
    return None


def suggested_order(colour: str = "blue", data: dict | None = None,
                    name: str = SUGGESTED_ORDER) -> list:
    """[(key, goals.yaml-shaped entry)] of goals.yaml `suggested_orders[name]`
    for a `colour` hive. An entry may be {blue: ..., red: ...}: the colour's
    pick (the Tide Popper for blue, the Dark Scythe for red; white takes the
    entry's `white`, else its first). The entry is goals.yaml's own goal where
    it has one, else the progression file's; a key neither has is left out."""
    from . import goals as goals_mod
    data = goals_mod.load() if data is None else data
    goals = data.get("goals") or {}
    out = []
    for item in (data.get("suggested_orders") or {}).get(name) or []:
        if isinstance(item, dict):
            item = item.get(colour) or next(iter(item.values()), None)
        if not item:
            continue
        entry = goals.get(item) or _entry_from_progression(str(item), colour)
        if entry is not None:
            out.append((str(item), entry))
    return out


def with_suggested(data: dict, colour: str = "blue", name: str = SUGGESTED_ORDER) -> tuple:
    """(data, order) for brain/goals.build(data, order=order): the suggested
    goals added to `data["goals"]` (one goals.yaml has is kept as it is) and
    their keys in the suggested order. Pure on `data`: a copy is returned."""
    picked = suggested_order(colour, data, name)
    goals = dict(data.get("goals") or {})
    for key, entry in picked:
        goals.setdefault(key, entry)
    return dict(data, goals=goals), [k for k, _e in picked]


# 12. "buy hive slots until the hive slot is more than the gear you are trying
# to get." The setting economy.slot_rule: "current" (the default: today's
# buying, the slot whenever its honey and its egg are there) or "pro" (this).
# The OWNER decides -- brain/roi's payback can rank a late slot (slot 40) far behind the
# Diamond Mask, so the two disagree.
SLOT_RULE_SETTING = "economy.slot_rule"


def slot_rule(slot_price: int, rows, rule: str = "current") -> tuple[bool, str]:
    """(may the next hive slot be bought now, why not). `rows`: brain/goals
    Plan.rows; the gear saved for is the first open row that is not a slot."""
    if rule != "pro":
        return True, ""
    gear = next((r for r in rows or () if not getattr(r, "owned", False)
                 and not str(getattr(r, "key", "")).startswith("hive_slot")), None)
    cost = int(getattr(gear, "cost", 0) or 0) if gear is not None else 0
    if gear is None or not cost or slot_price <= cost:
        return True, ""
    return False, (f"{SOURCE2}: the slot ({slot_price:,}) costs more than the "
                   f"{gear.label} saved for ({cost:,}) (economy.slot_rule is pro)")


# 13. "keep it if its a new gifted type that you dont have yet." Today a roll
# stops on ANY gifted bee; the pro keeps only a gifted type the hive has not
# got gifted (var/bees.json `gifted`). Rolling on past a gifted duplicate
# spends jelly the owner never saw spent: LOOK-ONLY.
JELLY_ROLL_PAST_GIFTED_DUPLICATE_LIVE = False


def keep_jelly_roll(bee: str | None, gifted_card: bool, gifted_types) -> tuple[bool, str]:
    """(keep the roll, why) by rule 13 alone -- the wanted bee and a Mythic
    are kept by the bot's own rules before this is asked."""
    if not bee or not gifted_card:
        return False, ""
    if bee in set(gifted_types or ()):
        return False, (f"{SOURCE2}: the gifted {bee.replace('_', ' ')} is not a new "
                       f"gifted type (the hive has one), so roll on")
    return True, f"{SOURCE2}: a new gifted type, the {bee.replace('_', ' ')} -- keep it"


# 14. "with treats feed event bees first and also star treats on event bees
# first." An event bee = bee_types.yaml `rarity: event`. LOOK-ONLY: the quest
# feed drops on any bee (run_farm feed_for_the_quest); finding a named bee by
# its card for a feed is a scan no live feed has made.
FEED_EVENT_BEES_LIVE = False


def feed_target(have: dict, types: dict) -> str | None:
    """The event bee a treat goes to first: one the hive holds, the most held
    first (ties by name); None when it holds none."""
    events = [(-int(n or 0), b) for b, n in (have or {}).items()
              if int(n or 0) > 0 and ((types or {}).get(b) or {}).get("rarity") == "event"]
    return min(events)[1] if events else None


# 15. "vicious, king beetle, tunnel bear, commando chick is not really worth
# the time it takes to kill." The bosses stay opt-in features; where the bot
# prices a fight against gathering (act/commando's Q to the next milestone),
# a MEASURED loss with nothing unpriced in it now skips the fight. An
# unpriced fight (no visit timed, a Star Jelly or Mythic Egg ahead) goes as
# today: the owner asked for them.
def boss_worth(q, unpriced=()) -> tuple[bool, str]:
    """(go, why not) for a boss fight priced `q` honey a visit (value.q)."""
    if q is None or unpriced or q >= 0:
        return True, ""
    # no figure in the words: the log says a skip once, and Q moves every trip
    return False, (f"{SOURCE2}: not worth the time -- a visit is measured to make "
                   f"less than gathering, and nothing unpriced is in its drops")


# 16. "dont kill mondo every hour only some hours." The bot never fights the
# Mondo Chick (world/timers keeps every trip off Mountain Top :00-:15); its
# loot pickup after someone else's kill (act/mondo, look-only) now goes only
# in an hour a quest step wants the chick. No "every Nth hour": the pro gave
# no number and none is invented.
def mondo_this_hour(quest_wants: int | None) -> tuple[bool, str]:
    if quest_wants:
        return True, ""
    return False, (f"{SOURCE2}: not every hour -- no quest step wants the Mondo Chick")


# 17. Robo Bear Challenge and 18. Ant Challenge: playbook only (pro_robo_bear_*,
# pro_ant_challenge_dodge) -- the bot has no Robo Bear feature and no ant or
# lawnmower detector; nothing is claimed in code.

# 19. + 20. "everything in the game evolves around efficiency, not just having
# the best equipment ... its all about keeping your buffs alive and having a
# good hive comp". A PRIOR on brain/roi's ranking, which prices GEAR only
# (gains.yaml): nectars, the balloon blessing and the buffs a hive comp keeps
# up are not in it, so it undervalues them. No percentage is put on them --
# none was given, and none is invented; the boost AI's and the nectar plan's
# own measurements are where they get a number.
EFFICIENCY_NOTE = (f"Not ranked here ({SOURCE2}): nectars, the balloon blessing and "
                   f"the buffs a hive comp keeps alive (Melody, Baby Love, bear morphs) "
                   f"-- an efficient hive beats better gear '9 times out of 10'; this "
                   f"ranking prices gear only, so it undervalues them.")

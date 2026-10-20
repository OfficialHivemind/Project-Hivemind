"""N4, KEEPING THE NECTARS UP: which field a trip should prefer while a nectar
is low, and which Nectar Vial would be used.

WHY. The owner, 2026-10-10: nectar matters a great deal; a viewer
(Discord #suggestions, 2026-10-18) asked for auto nectar vials.

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

from itertools import combinations

from ..act import planter
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


# ---------------------------------------------------------------------------
# N1-N3: THE 24 H PLANTER PLAN. Which held planter goes in which field for each
# of the 3 slots, looking a day ahead, re-run on every planter errand (after
# each harvest). The errand alone picks one nectar at a time -- the furthest
# under its minimum -- and the first held planter in table order; MEASURED
# (var/planters.json harvests, 18-22 Oct) that sent the Blue Clay (x1.2
# Comforting/Refreshing) to Stump, Sunflower, Pineapple, Mushroom and Pepper
# while the x0.75 Paper took Pine Tree. Here every placement now (each
# combination of held planters x their best field per nectar) is played out
# for PLAN_HOURS on the nectar the buff bar reads, the slots refilled
# greedily as each harvest frees one, and the best day wins.
#
# THE MODEL (each part marked):
# - nectar a harvest adds: act/planter.nectar_added, on the level READ off the
#   buff bar (vision/nectar), capped at 100 (24 h). The bar drains 100% a day
#   "even if the player is not in the game" (wiki Nectar, read 2026-10-26).
# - grow time: act/planter.table_row + the field's degradation (planter.placed);
#   a planter grows only in game, so the plan's hours are hours of play.
# - HARVEST_LAG_S: MEASURED 2026-10-12..22 (var/planters.json, 41 harvests):
#   a harvest lands a median ~9 min after the planter's grow time (the errand
#   runs every 15 min, PLANTER_ERRAND_EVERY_S, and waits on a trip) -- a 1 h
#   Paper idles ~13% of its slot, a 5 h Blue Clay ~3%.
# - what a level is worth: the wiki's datamined buff, "min + (max - min) x
#   (t/86400)^0.7" (wiki Nectar, read 2026-10-26): ANY nectar held gives the
#   buff's min at once, the rest grows as the 0.7 power of the hours. MIN_SHARE:
#   the min's share of the whole buff, Comforting's x1.1-1.5 blue pollen (0.1
#   of 0.5 above x1) -- ASSUMED for every nectar. Each nectar weighted by its
#   rank (planter.errand_target's own weights: blue pollen first, red last).
# - one planter per nectar at a time, one per field (planter.next_step's rules).
# ponytail: sipping bees (more nectar and growth where the hive gathers) are
# not in it -- NOT MEASURED; reflect.nectar_effect can price it later.
#
# FIELD WEAR (act/planter.degradation_h: a harvest wears its field by 1 h + the
# planter's grow hours, to 48 h -- wiki Planter, read 2026-10-27 -- wearing off
# an hour an hour and a planter there growing that many hours longer, ASSUMED,
# the wiki says only "the longer they'll naturally grow"). The day is
# played out on that model, so a worn field already costs its hours. On top,
# an option's rate charges each hour of wear (1 + WEAR_PENALTY) times, so the
# slots refill toward fresh fields. MEASURED 2026-10-27 (tools/planter_plan_sim,
# 3 days, the five starts): 0.5-0.7 is flat, every start equal or better --
# value/day +0.0/+1.2/+1.3/+0.5/+0.0%, the wear a planter grew through
# 0.0/0.2/0.7/1.2/0.3 -> 0.0/0.0/0.0/0.2/0.3 h a day; 1.0 lost 0.2% mid-game.
# Our own logs (docs/pending/plantdeg.md) fit the 1 h-an-hour recovery (Spider
# Blue Clay 13 Oct: 81.4% at 4.8 h in game, the table's 6 h, 7.4 h after a 7 h
# wear) but have NO clean read of a planter growing INTO a worn field, so the
# wear's size stays the wiki's -- the penalty hedges an under-count.
WEAR_PENALTY = 0.6
PLAN_LIVE = False                    # look-only: logs "planter plan would: ..."
PLAN_HOURS = 24.0
PLAN_STEP_S = 900.0                  # the sim's clock = the errand's 15 min
HARVEST_LAG_S = 540.0                # MEASURED (above)
MIN_SHARE = 0.2                      # ASSUMED (above)
MAX_OUT = 3                          # "up to 3 planters active" (wiki Planters)
PLAN_OPTIONS = 20                    # (planter, nectar) options a plan tries, at most
WEIGHTS = {n: max(0.5, 1.35 - 0.12 * rank) for rank, n in enumerate(NECTAR_ORDER)}


def day_value(levels: dict) -> float:
    """What these nectar levels are worth for one step of the day (0-100 a
    nectar, by its weight)."""
    return sum(100.0 * WEIGHTS[n] * ((MIN_SHARE if lv > 0 else 0.0)
                                     + (1 - MIN_SHARE) * (min(lv, 100.0) / 100.0) ** 0.7)
               for n, lv in levels.items())


def _options(st: dict, keys, levels: dict, reachable, now: float) -> list:
    """(rate, key, field, nectar): each placeable planter's best free field per
    nectar not already growing, best first -- the value its harvest adds per
    hour of slot it holds."""
    out = st.get("out") or {}
    used = {b.get("field") for b in out.values()}
    growing = {NECTAR.get(b.get("field")) for b in out.values()}
    best = {}
    for key in keys:
        if key in out:
            continue
        for field in sorted(reachable):
            nectar = NECTAR.get(field)
            if field in used or nectar is None or nectar in growing:
                continue
            lv = levels[nectar]
            if lv >= 100.0:
                continue
            gain = (day_value({nectar: min(100.0, lv + planter.nectar_added(key, field))})
                    - day_value({nectar: lv}))
            hours = (planter.grow_s(key, field) + HARVEST_LAG_S
                     + planter.degradation_h(st, field, now) * 3600.0 * (1 + WEAR_PENALTY)) / 3600.0
            row = (gain / hours, key, field, nectar)
            if row > best.get((key, nectar), (-1.0,)):
                best[(key, nectar)] = row
    return sorted(best.values(), reverse=True)


def simulate(state: dict, counts: dict, levels: dict, reachable, now: float,
             first=(), choose=None, hours: float = PLAN_HOURS):
    """(score, tracks): `hours` played out from `state` (act/planter's) with
    `levels` (None read as 0), `first` [(key, field)] placed now, then every
    free slot filled by `choose(st, counts, levels, t)` -> (key, field) or None
    (default: the best `_options` rate). `counts`: the placeable keys and how
    many (a reusable 1, a single-use its bag count). tracks: [(key, field,
    placed at, harvested at or None)]."""
    st = {k: v for k, v in state.items() if k in ("out", "degradation")}
    left = dict(counts)
    lv = {n: float(levels.get(n) or 0.0) for n in NECTAR_ORDER}
    tracks = [[k, b.get("field"), b.get("at"), None] for k, b in (st.get("out") or {}).items()]
    first = list(first)
    score, t = 0.0, now
    decay = 100.0 * PLAN_STEP_S / (24 * 3600.0)
    for _ in range(int(hours * 3600 / PLAN_STEP_S)):
        for key, body in list((st.get("out") or {}).items()):
            if t >= float(body.get("at") or now) + planter.planter_grow_s(st, key) + HARVEST_LAG_S:
                n = NECTAR.get(body.get("field"))
                if n:
                    lv[n] = min(100.0, lv[n] + planter.nectar_added(key, body.get("field")))
                st = planter.harvested(st, key, t)
                if key not in planter.SINGLE_USE:
                    left[key] = left.get(key, 0) + 1     # a reusable comes back
                for tr in tracks:
                    if tr[0] == key and tr[3] is None:
                        tr[3] = t
        while len(st.get("out") or {}) < MAX_OUT:
            if first:
                pick = first.pop(0)
            elif choose is not None:
                pick = choose(st, left, lv, t)
            else:
                opts = _options(st, [k for k, c in left.items() if c > 0], lv, reachable, t)
                pick = opts[0][1:3] if opts else None
            if pick is None:
                break
            key, field = pick
            st = planter.placed(st, key, field, t)
            left[key] = left.get(key, 0) - 1
            tracks.append([key, field, t, None])
        score += day_value(lv)
        lv = {n: max(0.0, v - decay) for n, v in lv.items()}
        t += PLAN_STEP_S
    return score, [tuple(tr) for tr in tracks]


def plan(state: dict, owned, held: dict, levels: dict, reachable, now: float) -> dict | None:
    """The 24 h planter plan, or None when no nectar was read: {"place":
    [(key, field)] to put out now; "tracks": the day as played out; "score",
    and "greedy" (the same day filling each slot by the best rate alone);
    "why": one line; "blocked": why no more goes out}. `owned`: planter
    titles; `held`: {key: bag count} (the inventory read)."""
    if not any(v is not None for v in (levels or {}).values()):
        return None
    keys = planter.placeable(state, owned, now)
    counts = {k: (max(1, int(held.get(k) or 0)) if k in planter.SINGLE_USE else 1) for k in keys}
    free = MAX_OUT - len(state.get("out") or {})
    lv = {n: float(levels.get(n) or 0.0) for n in NECTAR_ORDER}
    # ponytail: at most PLAN_OPTIONS options, each planter's best nectars --
    # 7 planters held made 35 options and 3.7 s of CPU a plan (MEASURED
    # 2026-10-26). Never cut by rate alone: a best-rate cut kept only the
    # Paper's and dropped the Blue Clay on Comforting (-23% on the Ticket day,
    # tools/planter_plan_sim); up to 4 planters held, nothing is cut.
    cap = max(1, PLAN_OPTIONS // max(1, len(keys)))
    opts, per = [], {}
    for o in (_options(state, keys, lv, reachable, now) if free > 0 else []):
        per[o[1]] = per.get(o[1], 0) + 1
        if per[o[1]] <= cap:
            opts.append(o)
    greedy, _ = simulate(state, counts, lv, reachable, now)
    best = (float("-inf"), [])
    # EVERY PLACEMENT NOW: up to `free` options, no planter, field or nectar twice
    for size in range(min(free, len(keys)), 0, -1):
        for combo in combinations(opts, size):
            if any(len({c[i] for c in combo}) < size for i in (1, 2, 3)):
                continue
            first = [(k, f) for _r, k, f, _n in combo]
            score, _ = simulate(state, counts, lv, reachable, now, first=first)
            if score > best[0] + 1e-9:
                best = (score, first)
        if best[1]:
            break
    score, tracks = simulate(state, counts, lv, reachable, now, first=best[1])
    blocked = [f"the {planter.PLANTERS[k][0]} is lost in "
               f"{str(b.get('field')).replace('_', ' ')} (one of each may be out)"
               for k, b in (state.get("lost") or {}).items() if k in planter.PLANTERS]
    if free <= 0:
        blocked.append(f"{MAX_OUT} planters are out")
    elif not keys:
        blocked.append("no planter is held")
    elif not opts:
        blocked.append("every nectar is full or growing, or has no field with a route")
    why = ", ".join(f"the {planter.PLANTERS[k][0]} in {f.replace('_', ' ')} "
                    f"({NECTAR[f]} {lv[NECTAR[f]]:.0f}%)" for k, f in best[1])
    return {"place": best[1], "tracks": tracks, "score": score, "greedy": greedy,
            "why": why, "blocked": blocked,
            "unplaced": unplaced(state, best[1], lv, reachable, now) if keys and free > 0 else []}


def unplaced(state: dict, place, levels: dict, reachable, now: float) -> list[str]:
    """'no planter placed in <field> because ...' for each nectar with no
    planter out and none going out now (`place`), naming its least-worn
    reachable field and that field's wear when it has some. plan asks only
    when a planter was held and a slot free; else its "blocked" says why."""
    taken = ({NECTAR.get(b.get("field")) for b in (state.get("out") or {}).values()}
             | {NECTAR.get(f) for _k, f in place})
    lines = []
    for nectar in NECTAR_ORDER:
        if nectar in taken:
            continue
        fields = planter.NECTAR_FIELDS[nectar]
        near = [f for f in fields if f in reachable]
        if not near:
            lines.append(f"no planter placed for {nectar} because none of its fields ("
                         + ", ".join(f.replace("_", " ") for f in fields) + ") has a route out")
            continue
        field = min(near, key=lambda f: (planter.degradation_h(state, f, now), near.index(f)))
        level = float(levels.get(nectar) or 0.0)
        if level >= planter.NECTAR_FULL:
            why = f"{nectar} is full ({level:.0f}%)"
        elif place:
            why = f"{nectar} reads {level:.0f}% and the held planters do more on other nectars"
        else:
            why = f"{nectar} reads {level:.0f}% and no held planter can go there"
        wear = planter.degradation_h(state, field, now)
        if wear >= 0.05:
            why += f"; the field is worn {wear:.1f} h, so a planter there grows {wear:.1f} h longer"
        lines.append(f"no planter placed in {field.replace('_', ' ')} because {why}")
    return lines

"""The opportunity calendar: timed game events priced against plain gathering
(backlog item 8, docs/pending/brain-research.md "8. Opportunity calendar...").

WHY. Natro runs these on a fixed priority order (Night -> Mondo -> Planter ->
Bugrun -> Collect -> QuestRotate -> Boost -> GoGather, brain-research.md
section 1). The research's point, and brain/value.py's: choose by what each
is WORTH against rho (the honey/s gathering pays right now), the same Q
arithmetic as every other errand, not a fixed order.

WHAT THIS DOES NOT DO. It does not click anything -- `opportunities()` is a
pure function of `now` and `state`, and nothing here reads the screen or
writes a file. It does not invent a price: most of these events have no honey
figure anywhere in the research or data/knowledge, and an unpriced
Opportunity's `value_honey` stays None, same rule as value.py's payouts.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import mobtable, value

# ---------------------------------------------------------------- Mondo ----
# data/knowledge/playbook.yaml id mondo_chick_hour: "Keep off Mountain Top in
# the first quarter of each hour, when the Mondo Chick comes." brain-research.md
# section 1: "Mondo has priority from minute 0 to 14 of each UTC hour, if 960 s
# have passed since the last Mondo buff." Epoch seconds are already UTC, so
# `now % 3600` gives the minute-of-hour with no timezone handling needed.
MONDO_WINDOW_END_MINUTE = 14
MONDO_MIN_GAP_SECONDS = 960.0
# No honey figure for a Mondo kill anywhere in the research or
# data/knowledge/world.yaml -- stays unpriced.

# ------------------------------------------------------------ bug respawns --
# data/knowledge/mobs.yaml `respawn_seconds`, `honey` and `ticket_chance` of
# the six field mobs (`kind: field_mob`), each read off the wiki (cited there
# per-mob), through brain/mobtable (ROADMAP K7) rather than a second copy here.
# werewolf is 3630 s (Natro's figure, measured 3639-3734 s between kills), not
# the 3600 s the research report rounds to. Honey and tickets a kill are the
# MEASURED rates blended with the wiki's (mobtable.kill_honey / ticket_rate):
# the wiki's ticket chances are about 10x what reached the account
# (Spider 8 of 283 kills, Mantis 4 of 527; docs/pending/mobs-k7.md).
_FIELD_MOBS = {slug: row for slug, row in mobtable.table().items()
               if row.get("kind") == "field_mob"}
RESPAWN_SECONDS = {m: row["respawn_seconds"] for m, row in _FIELD_MOBS.items()}
MOB_HONEY = {m: mobtable.kill_honey(m)[0] for m in _FIELD_MOBS}
MOB_TICKET_CHANCE = {m: mobtable.ticket_rate(m)[0] for m in _FIELD_MOBS}
# Which fields each mob defends (mobs.yaml `fields:`, plus werewolf's
# `also_defends`), by day. Shared with goalvalue.field_quest_value so the two
# modules don't keep two copies of the same wiki numbers.
FIELD_MOBS = {}
for _m, _row in _FIELD_MOBS.items():
    for _f in mobtable.fields_of(_row):
        FIELD_MOBS[_f] = FIELD_MOBS.get(_f, ()) + (_m,)
# SECONDS IS 0: the bees fight whatever comes near while the character
# gathers (brain/decide.py `_quest_value`, "the bees fight while it
# gathers"; measured kill counts in mobs.yaml's header comment). A wanted
# mob's kill costs no extra trip time, so it is free money once it is up.

# ------------------------------------------------------------ Memory Match --
# data/knowledge/playbook.yaml id memory_match_on_its_timers; brain-research.md
# section 1: "Memory Match cooldowns are 2 h normal, 4 h mega and winter, 8 h
# extreme and night."
MEMORY_MATCH_COOLDOWN_S = {"normal": 2 * 3600.0, "mega": 4 * 3600.0,
                           "winter": 4 * 3600.0, "extreme": 8 * 3600.0,
                           "night": 8 * 3600.0}
# Its prizes (Treats, Royal Jelly, Micro-Converters, Cloud Vials, "the better
# pairs") are never priced anywhere in the research or data/knowledge --
# stays unpriced.

# -------------------------------------------------------------- Vicious Bee --
# brain-research.md section 1: "Vicious Bee hunting only runs at night and is
# skipped if one was killed within 22 h." Nothing in the research or
# data/knowledge/playbook.yaml (id night_vicious_bee) gives the CLOCK HOURS
# that count as night -- "telling night from day" is still listed there as
# `taught: needs_a_look`. This module does not invent a boundary; the caller
# says so itself, in `state["is_night"]`.
VICIOUS_COOLDOWN_S = 22.0 * 3600.0
# Its drop (Stingers) has no honey price in the research or data/knowledge --
# stays unpriced.

# ---------------------------------------------------------------- boosters --
# data/knowledge/errands.yaml `every_hours: 0.75` for each of the blue, red and
# white field boosters (wiki: "a cooldown of 45 minutes"). brain-research.md
# section 3: "uses are spaced at least 15 min apart" -- a stack lasts 15 min
# (wiki Field_Booster) so pressing again inside that window restacks instead
# of wasting the press.
BOOSTER_COOLDOWN_S = 2700.0
BOOSTER_SPACING_S = 900.0
BOOSTER_KINDS = ("blue_field_booster", "red_field_booster", "white_field_booster")
# MEASURED SECONDS: brain-research-3.md's own table only timed the blue one
# (206 runs, 93% landed, median 40 s); used here for red/white too since it is
# the same errand shape and nothing separately timed them.
BOOSTER_ERRAND_SECONDS = 40.0
# What a boost is worth depends on which field it lands on and that field's
# OWN rate right now (brain-research.md: "69% of the read ones the boost
# landed on a field the bot was not going to") -- too context-dependent for a
# flat number here. Stays unpriced; `brain/boostwindow.py` is where a landed
# boost gets priced against the field it actually hit.

# --------------------------------------------------------- Honey Bee quest --
# docs/pending/brain-research-2.md "Honey Bee": "Reward: 2x convert rate for
# 30 min, plus a Star Jelly on every 10th quest up to the 100th."
HONEY_BEE_CONVERT_BOOST_S = 30.0 * 60.0
# A rate MULTIPLIER, not a flat honey amount -- its value depends on how much
# honey is converted during the window, which this module does not know.
# Stays unpriced.


@dataclass
class Opportunity:
    """One timed event, priced where the research or data/knowledge prices
    it, `why` always saying which. `value_honey` is None for anything this
    project has no honey figure for -- never 0, so an unpriced event never
    reads as worthless."""
    name: str
    starts_at: float
    ends_at: float
    value_honey: float | None
    seconds: float | None
    why: str


def _mondo(now: float, state: dict) -> Opportunity | None:
    hour_start = now - (now % 3600.0)
    minute = (now % 3600.0) / 60.0
    if minute > MONDO_WINDOW_END_MINUTE:
        return None             # outside the window: due now, not "coming up"
    window_end = hour_start + (MONDO_WINDOW_END_MINUTE + 1) * 60.0
    last_buff = state.get("mondo_last_buff_at")
    if last_buff is not None and now - float(last_buff) < MONDO_MIN_GAP_SECONDS:
        return None
    return Opportunity("mondo_chick", hour_start, window_end, None, None,
                       "minutes 0-14 of the UTC hour (playbook mondo_chick_hour); "
                       "no honey figure for the kill is in the research or data")


def _bug_respawns(now: float, state: dict) -> list:
    out = []
    for key, last_kill in (state.get("bug_last_kill") or {}).items():
        field, _, mob = str(key).partition(":")
        respawn = RESPAWN_SECONDS.get(mob)
        if respawn is None or last_kill is None:
            continue           # an unknown mob or no reading: no claim, not a guess
        ready = float(last_kill) + respawn
        if now < ready:
            continue           # not respawned yet
        honey = MOB_HONEY[mob] + MOB_TICKET_CHANCE[mob] * value.PRICES["ticket"]
        out.append(Opportunity(
            f"{field}:{mob}", ready, ready + respawn, honey, 0.0,
            f"mobs.yaml: {mob} respawns {respawn}s, pays {MOB_HONEY[mob]:,.0f} honey "
            f"+ {MOB_TICKET_CHANCE[mob]:.1%} chance of a ticket (measured, wiki "
            f"prior); the bees fight "
            f"it while the character gathers in {field}, so it costs no extra time"))
    return out


def _memory_match(now: float, state: dict) -> list:
    out = []
    for kind, cooldown in MEMORY_MATCH_COOLDOWN_S.items():
        last = (state.get("memory_match_last_play") or {}).get(kind)
        if last is None:
            continue           # never recorded: no claim
        ready = float(last) + cooldown
        if now < ready:
            continue
        out.append(Opportunity(
            f"memory_match_{kind}", ready, ready + cooldown, None, None,
            f"playbook memory_match_on_its_timers: {kind} cooldown "
            f"{cooldown / 3600:.0f}h; its prizes have no honey price in the research"))
    return out


def _vicious(now: float, state: dict) -> Opportunity | None:
    if not state.get("is_night"):
        # Not night, or the caller does not know -- this module has no clock
        # boundary of its own to fall back on (data/knowledge/playbook.yaml
        # night_vicious_bee: "telling night from day" is still unread).
        return None
    last_kill = state.get("vicious_last_kill")
    ready = (float(last_kill) + VICIOUS_COOLDOWN_S) if last_kill is not None else now
    if now < ready:
        return None
    return Opportunity("vicious_bee", ready, ready + VICIOUS_COOLDOWN_S, None, None,
                       "night, and 22h since the last kill (brain-research.md); "
                       "its Stinger drop has no honey price in the research")


def _boosters(now: float, state: dict) -> list:
    out = []
    last_any = state.get("booster_last_press_any")
    for kind in BOOSTER_KINDS:
        last = (state.get("booster_last_press") or {}).get(kind)
        if last is None:
            continue
        ready = float(last) + BOOSTER_COOLDOWN_S
        if last_any is not None:
            ready = max(ready, float(last_any) + BOOSTER_SPACING_S)
        if now < ready:
            continue
        out.append(Opportunity(
            kind, ready, ready + BOOSTER_COOLDOWN_S, None, BOOSTER_ERRAND_SECONDS,
            "errands.yaml every_hours 0.75 (45 min cooldown), spaced >=15 min "
            "apart from the last booster of any kind (brain-research.md); what it "
            "boosts is random (brain-research.md 69% miss-landed), so unpriced here"))
    return out


def _honey_bee_convert(now: float, state: dict) -> Opportunity | None:
    turnin = state.get("honey_bee_turnin_at")
    if turnin is None:
        return None
    ends = float(turnin) + HONEY_BEE_CONVERT_BOOST_S
    if now >= ends:
        return None
    return Opportunity("honey_bee_2x_convert", float(turnin), ends, None, None,
                       "brain-research-2.md Honey Bee: 2x convert rate for 30 min; "
                       "a rate multiplier, not a flat honey figure, so unpriced here")


def opportunities(now: float, state: dict) -> list:
    """Every timed event due now, from `state`:

    state["mondo_last_buff_at"]        epoch of the last Mondo buff (optional)
    state["bug_last_kill"]             {"field:mob": epoch}, e.g. {"rose:scorpion": 1760...}
    state["memory_match_last_play"]    {"normal"|"mega"|"winter"|"extreme"|"night": epoch}
    state["is_night"], state["vicious_last_kill"]   bool, epoch|None
    state["booster_last_press"]        {"blue_field_booster"|"red_..."|"white_...": epoch}
    state["booster_last_press_any"]    epoch of the most recent booster press of any kind
    state["honey_bee_turnin_at"]       epoch the Honey Bee quest reward was granted

    A key this project has never recorded is left out, not guessed at --
    same discipline as `goals.py`'s UNKNOWN (never silently "ready now")."""
    out = []
    mondo = _mondo(now, state)
    if mondo is not None:
        out.append(mondo)
    out.extend(_bug_respawns(now, state))
    out.extend(_memory_match(now, state))
    vicious = _vicious(now, state)
    if vicious is not None:
        out.append(vicious)
    out.extend(_boosters(now, state))
    honey_bee = _honey_bee_convert(now, state)
    if honey_bee is not None:
        out.append(honey_bee)
    return out


def best_now(opps: list, rho: float) -> list:
    """Those worth doing over gathering, by value.q's own arithmetic: p=1
    (no landing odds for a calendar event), seconds its own cost, no
    cooldown/trip term. Unpriced opportunities (`value_honey` is None) or
    ones with no seconds figure can never beat anything and are left out,
    same as an unpriced errand in value.order()."""
    out = []
    for o in opps:
        if o.value_honey is None or o.seconds is None:
            continue
        q = value.q(o.value_honey, 1.0, o.seconds, rho)
        if q is not None and q > 0:
            out.append(o)
    return out


if __name__ == "__main__":
    # Mondo: minute 5 of the hour is in the window, minute 20 is not.
    hour = 1_760_000_400.0        # a round hour, epoch
    assert _mondo(hour + 5 * 60, {}) is not None
    assert _mondo(hour + 20 * 60, {}) is None
    assert _mondo(hour + 5 * 60, {"mondo_last_buff_at": hour + 4 * 60}) is None

    # A scorpion killed 1,300s ago (respawn 1,230s) is up, priced from
    # mobs.yaml, and costs no extra seconds.
    now = 2_000_000.0
    state = {"bug_last_kill": {"rose:scorpion": now - 1300}}
    bugs = _bug_respawns(now, state)
    assert len(bugs) == 1 and bugs[0].name == "rose:scorpion"
    # measured, wiki prior: 155 kills paid 2,656 honey and 2 tickets (mobs.yaml)
    assert bugs[0].value_honey == MOB_HONEY["scorpion"] + MOB_TICKET_CHANCE["scorpion"] * 100_000.0
    assert 1000 < MOB_HONEY["scorpion"] < 2656 and 0.03 < MOB_TICKET_CHANCE["scorpion"] < 0.05
    assert bugs[0].seconds == 0.0
    # Not yet respawned: nothing.
    assert _bug_respawns(now, {"bug_last_kill": {"rose:scorpion": now - 100}}) == []
    # An unrecorded mob: no claim, not a guess.
    assert _bug_respawns(now, {"bug_last_kill": {"rose:unknown_bug": now - 9999}}) == []

    # Memory Match: unpriced even when due.
    mm = _memory_match(now, {"memory_match_last_play": {"normal": now - 7300}})
    assert len(mm) == 1 and mm[0].value_honey is None

    # Vicious: no opportunity without the caller saying it is night.
    assert _vicious(now, {"vicious_last_kill": now - 100000}) is None
    assert _vicious(now, {"is_night": True, "vicious_last_kill": now - 100000}) is not None
    assert _vicious(now, {"is_night": True, "vicious_last_kill": now - 100}) is None

    # Boosters: spacing from the last press of ANY kind pushes the ready time out.
    b = _boosters(now, {"booster_last_press": {"blue_field_booster": now - 3000},
                        "booster_last_press_any": now - 200})
    assert b == []       # cooldown is over but the 15-min spacing is not
    b = _boosters(now, {"booster_last_press": {"blue_field_booster": now - 3000},
                        "booster_last_press_any": now - 3000})
    assert len(b) == 1 and b[0].seconds == BOOSTER_ERRAND_SECONDS

    # best_now: the priced, free (seconds=0) scorpion opportunity always
    # beats any gathering rate; the unpriced Mondo and Memory Match never do.
    all_opps = opportunities(now, {"bug_last_kill": {"rose:scorpion": now - 1300},
                                   "memory_match_last_play": {"normal": now - 7300}})
    won = best_now(all_opps, rho=50_000.0)
    assert [o.name for o in won] == ["rose:scorpion"]

    print("ok:", len(all_opps), "opportunities,", len(won), "beat gathering")

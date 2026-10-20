"""What to buy next, and why: the purchases a strong player would make now.

THE OWNER, 2026-10-02: "i want you to teach the bot how to buy things and to
know what to buy". This is the KNOWING half. It reads what the bot already
reasons with, invents nothing, and returns a short ordered list, each line a
thing, where it is sold, what it costs, why it is next, and whether the bot can
buy it now -- or exactly what stands in the way:

  * the gear goals in the owner's own order (brain/goals: prices, shops,
    materials held) -- the first one not owned is what the honey is kept for;
  * Royal Jelly for the hive (brain/hivejudge: what jelly goes on, ~266 rolls a
    Diamond) bought with honey, never with tickets, and only from the honey
    ABOVE what the next goal still needs (the owner's "buy roysal jellys with
    honey", and his goal order, both kept);
  * Royal Jelly for the Blender FIRST (act/blender.crafting: what the next
    goal's short materials take), bought from the honey above the goal's own
    price -- THE OWNER, 2026-10-13: "bot must learn one day, its used for
    crafting too";
  * the playbook's buying rules (data/knowledge/playbook.yaml): no Diamond or
    Mythic Eggs, none of the known traps.

THE DOING HALF is per shop and needs each shop's window seen once
(act/shoplook): `BUYS_AT` lists what scripts/run_farm completes a purchase of,
and anything else says it is the owner's to buy -- the truth, not a plan
pretending to be one.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..platform.session import ROLE

# WHAT THE BOT BUYS ITSELF. THE OWNER, 2026-10-02: "the bot is allowed to do
# the game purchases so long as they dont cost robux meaning it can spend my
# honey tickets and other recourses without my permission". scripts/run_farm
# completes a purchase only where it has the flow for one: every purchase
# planned at the Ticket Tent (TENT_PURCHASES; the Festive Bee Egg bought
# 2026-10-02 23:30) and the next Hive Slot at the Mountain Top Shop
# (run_farm.mts_buy_due; its window first read 2026-10-03 05:14). {shop: the
# goal keys bought there, by prefix -- None for every purchase planned there}.
# And the Bubble Mask at the Blue HQ (run_farm.blue_hq_buy_due, 2026-10-06: the
# owner, "i want bubble mask then diamond mask"). And the Plastic Planter at
# Dapper Bear's shop (run_farm.dapper_buy_due, once a survey finds its way in).
BUYS_AT: dict = {"ticket_tent": None, "mountain_top_shop": ("hive_slot",),
                 "blue_hq": ("bubble_mask", "blue_clay_planter"),
                 "dapper_bear_shop": ("plastic_planter",)}

# BESIDE THE GOALS, each bought once: the planters (the owner, 2026-10-06:
# "the best planter ... it should prolly do them too"). They wait on Magic
# Beans, which must not hold the goals back -- the buyer plans only the first
# open goal. The Blue Clay Planter is the guides' blue planter within reach
# (wiki Blue_Clay_Planter: reusable, ~6 h, +25% growth in blue fields, x1.2
# Comforting and Refreshing nectar, +25% blue pollen; sold at the Blue HQ);
# the Hydroponic after it costs 750B.
SIDE_FROM_KEPT_SHARE = 0.05    # a side purchase this cheap beside the goal may come out of it
SIDE_PURCHASES = (
    {"key": "blue_clay_planter", "label": "Blue Clay Planter", "shop": "blue_hq",
     "shop_label": "Blue HQ", "honey": 10_000_000,
     "materials": {"magic_bean": 5, "blue_extract": 15, "soft_wax": 20},
     "why": "the guides' blue planter, for nectar and pollen in the field it farms"},
    # THE THIRD PLANTER (2026-10-12): one of each kind and three at most may be
    # out (wiki Planters), and the Blue Clay and the single-use Paper are two.
    # The Plastic is the cheapest reusable one (wiki Plastic_Planter and
    # Dapper_Bear's_Shop, read 2026-10-12: 750,000 honey, 3 Magic Beans, 1
    # Soft Wax; ~2 h, no bonus); the Candy after it takes 5M, 5 beans and 30
    # Gumdrops for +20% Motivating alone. Listed here, its beans are kept from
    # the sprouts (run_farm the_stash).
    {"key": "plastic_planter", "label": "Plastic Planter", "shop": "dapper_bear_shop",
     "shop_label": "Dapper Bear's Shop", "honey": 750_000,
     "materials": {"magic_bean": 3, "soft_wax": 1},
     "why": "a third planter out at once, for nectar"},
)


# A SHOP THE BOT BUYS AT ONLY ONCE A SURVEY HAS READ ITS "Open Shop"
# (run_farm plan_buy_due: surveyed_legs), {shop: the survey's var/shoplook.json
# look key, run_farm DAPPER_SHOP_SURVEY}. MEASURED run-1174 (22 Oct
# 00:31-01:00): "Plastic Planter ... buying it" on every buying line while
# run_farm said "the way to its counter has not read "Open Shop" yet". The
# same test as surveyed_legs: that exact key, a "legN-" read saying "Open
# Shop" (the stump look and the bear talk do not count).
NEEDS_SURVEY = {"dapper_bear_shop": "dapper_shop_stairs_onto"}
NO_SURVEY = "the way to its counter has not read \"Open Shop\" yet"


def unsurveyed(var_root) -> set:
    """The NEEDS_SURVEY shops no look in var/shoplook.json has read "Open
    Shop" at; every one of them when the file cannot be read."""
    try:
        looks = json.loads((Path(var_root) / "shoplook.json").read_text(
            encoding="utf-8")).get("looks") or []
    except (OSError, ValueError, AttributeError):
        return set(NEEDS_SURVEY)
    seen = {shop for shop, survey in NEEDS_SURVEY.items() for e in looks
            if isinstance(e, dict) and e.get("shop") == survey and e.get("ok")
            and any(re.match(r"leg\d+-", str(r)) and "open shop" in str(r).lower()
                    for r in e.get("reads") or ())}
    return set(NEEDS_SURVEY) - seen


def bot_buys(shop: str, key: str = "") -> bool:
    """Whether scripts/run_farm completes the purchase of `key` at `shop`."""
    if shop not in BUYS_AT:
        return False
    keys = BUYS_AT[shop]
    return keys is None or any(str(key).startswith(k) for k in keys)

# ROYAL JELLY, priced at the Royal Jelly Shop's cap (items.yaml: 250,000 rising
# 10,000 a purchase to 1,000,000). How many the account has bought -- where
# the price stands -- is read off the shop's own panel when it buys; a plan
# made at the cap can only be too cautious.
JELLY_SHOP = "royal_jelly_shop"
JELLY_PRICE_PLANNED = 1_000_000
JELLY_LOT = 10                     # the shop sells in lots of 1, 10, 100
JELLY_MAX_PER_VISIT = 100
# NO WAY TO BUY IT YET. MEASURED 2026-10-03..07 (var/shoplook.json): six walks
# toward the shop (royal_jelly_shop_survey .. royal_jelly_dispenser_counter)
# and none read its "Open Shop"; no frame of its window exists, so there is
# no buy flow (act/shoplook.buy needs the window's words) and BUYS_AT does
# not list it. Said plainly on every Royal Jelly line until there is.
JELLY_NO_FLOW = ("the bot has no way to the Royal Jelly Shop's counter yet (no survey "
                 "has read its \"Open Shop\") and no buy flow — yours to buy")

# THE TICKET TENT'S PURCHASES, in order: (the item as the window names it,
# its price in tickets, why). scripts/run_farm buys them (act/shoplook.buy)
# once each, only after the tent's catalogue has shown the item at that
# price; var/purchases.json keeps every try.
TENT_SHOP = "ticket_tent"
TENT_PURCHASES = (
    # The guide's "necessary by default" event bee (guides/blue_hive_guide.md:
    # "Classes exclude bees that are deemed necessary by default {Festive /
    # Bear / Diamond / Puppy}"), for the next hive cell. The hive has the
    # Bear; the Puppy pays only past level 16 without Reindeer Antlers (the
    # same guide). 500 tickets (wiki Ticket_Tent); 507 held 2026-10-02 22:02.
    ("Festive Bee Egg", 500, "the guide's necessary Festive Bee, for the next hive cell"),
)
# THE ALT'S TICKET TENT (HIVEMIND_ROLE=alt), for a Tad alt (alt plan, stage 1).
# THE OWNER, 2026-10-13: the alt may spend its tickets on anything useful, eggs
# included, never Robux. MEASURED in the tent's catalogue (the main's
# var/shoplook.json, read 2026-10-03 06:10): "Gold Egg | 100 Tickets", "Mythic
# Egg | 2500 Tickets". A Gold Egg (79% epic, 20% legendary: items.yaml) fills
# the next slot better than the 10M-honey Basic Egg; a Mythic Egg is 1 in 6 a
# Tadpole. The main's Festive Bee Egg is left off: tent_buy_due stops at the
# first item not bought, and the cheap one goes first.
# ponytail: each item is bought ONCE (run_farm tent_buy_due skips one bought
# ok); a second Mythic Egg needs a count per item there.
if ROLE == "alt":
    TENT_PURCHASES = (
        ("Gold Egg", 100, "79% an epic bee, 20% a legendary, for the alt's next hive cell"),
        ("Mythic Egg", 2500, "1 in 6 a Tadpole Bee, the Tad alt's bee"),
    )

# GUMDROPS FOR THE BLENDER'S GLUE. THE OWNER, 2026-10-14 07:55: tickets may be
# spent on Gumdrops or Glue for the Honeycomb Belt ("your allowed to spend
# whatever u want"); never Robux (act/shoplook.buy refuses it). No shop sells
# Glue for tickets or honey -- only Robux packs, long gone (wiki Glue, rev
# 2026-07-12) -- so it is the Blender's "50 Gumdrops + 10 Royal Jelly" (wiki
# Blender, rev 2026-02-19), and the Gumdrop Shop sells 3 for 1 ticket, 30 for
# 10, 300 for 100 (wiki Gumdrop_Shop, rev 2026-07-12): 16.7 tickets a Glue.
# scripts/run_farm buys its 300 (GUMDROP_BUY, the goo quests' flow: "300
# Gumdrops | 100 Tickets" bought ok 2026-10-07 07:47 and 10-09 12:20, var/
# purchases.json) when the Blender's crafts for the next goal lack them and
# goals.yaml gives that material a Gumdrop Shop source the bot does.
GUMDROP_SHOP = "gumdrop_shop"
GLUE_GUMDROPS = 50


def gumdrops_for_the_blender(plan, crafting) -> tuple:
    """(gumdrops the Blender's crafts for the next goal lack, why) when one of
    that goal's missing materials has a Gumdrop Shop source the bot does
    (goals.yaml glue), else (0, "")."""
    from . import goals as goals_mod
    lacking = int((getattr(crafting, "lacking", None) or {}).get("gumdrops") or 0)
    if not lacking:
        return 0, ""
    row = next((r for r in getattr(plan, "rows", None) or ()
                if r.label == crafting.goal and not r.owned), None)
    if row is None or not any(s.get("place") == GUMDROP_SHOP and s.get("now") == goals_mod.DOES
                              for n in row.missing for s in n.sources):
        return 0, ""
    takes = int(crafting.takes.get("gumdrops", 0))
    return lacking, (f"for the Blender: {crafting.what()} for the {crafting.goal} take "
                     f"{takes:,} Gumdrops, {takes - lacking:,} held")


def gumdrops_kept(have: int, takes: int, keep: int) -> int:
    """The gumdrops a goo quest may not throw: `keep`, or while the Blender's
    crafts take some (`takes`, act/blender.Crafting) every whole Glue's 50
    held, up to what they take -- what tickets bought for the Glue is not
    thrown in a field, and the odd few still are."""
    return max(keep, min(int(have), int(takes)) // GLUE_GUMDROPS * GLUE_GUMDROPS)


# THE TICKET OPTIONS (Settings > Spending). THE OWNER, 2026-10-21: "make
# options for what it can spend [tickets] on and leave it all off as default
# but for me i want it on". Each is its own switch, off unless turned on, and
# none spends the tickets kept back (`economy.tickets.keep`).
#   Diamond Eggs: 400 tickets at the Ticket Tent (wiki Ticket_Tent, api.php
#   rev 448216, read 2026-10-21; the tent's catalogue read "Diamond Egg | AOO
#   Tickets" 2026-10-03 06:10, var/shoplook.json -- its 400 misread), bought
#   only while an open goal (the Diamond Mask's 5) is short of them, through
#   the tent's tested buy (run_farm tent_buy_due). NEVER's diamond_egg is the
#   playbook's no-HATCH rule: one bought for the mask is never hatched
#   (goals.diamond_saved holds while this is on).
#   Magic Beans: 20 tickets each at the Magic Bean Shop (wiki Magic_Bean, rev
#   449529, read 2026-10-21), for a planter on the list short of them.
#   LOOK-ONLY: no walk there has read its "Open Shop" (var/shoplook.json,
#   magic_bean_shop_counter_3, 2026-10-07), so its line says what it would buy.
DIAMOND_EGG_KEY, DIAMOND_EGG_LABEL = "diamond_egg", "Diamond Egg"
DIAMOND_EGG_TICKETS = 400
MAGIC_BEAN_TICKETS = 20
BEAN_SHOP = "magic_bean_shop"
BEAN_LOOK_ONLY = ("look-only: no walk has read the Magic Bean Shop's \"Open Shop\" "
                  "yet, so the bot only says what it would buy")


def ticket_purchases(plan, tickets: int | None, held: dict | None, settings,
                     bought=(), crafting=None) -> list:
    """The ticket spends switched on in Settings > Spending, each a Purchase:
    the Diamond Eggs the first open goal taking them is short of, and the
    Magic Beans the next planter on the list -- else the Blender's crafts for
    the next goal (`crafting`, act/blender.Crafting) -- are short of. None
    while the tickets or the bag are not counted."""
    if tickets is None or held is None or settings is None:
        return []
    keep = max(0, settings.int("economy.tickets.keep"))
    spare = max(0, int(tickets) - keep)
    out = []
    if settings.bool("economy.tickets.diamond_eggs"):
        row = next((r for r in getattr(plan, "rows", None) or () if not r.owned
                    and any(n.material == DIAMOND_EGG_KEY for n in r.needs)), None)
        need = next((n.need for n in (row.needs if row else ()) if n.material == DIAMOND_EGG_KEY), 0)
        short = max(0, need - int(held.get(DIAMOND_EGG_KEY) or 0))
        if short:
            count = min(short, spare // DIAMOND_EGG_TICKETS)
            out.append(Purchase(
                key=DIAMOND_EGG_KEY, label=DIAMOND_EGG_LABEL, shop=TENT_SHOP,
                shop_label="Ticket Tent", tickets=max(1, count) * DIAMOND_EGG_TICKETS,
                count=max(1, count), ready=bool(count), can_buy=bool(count),
                why=(f"for the {row.label} ({int(held.get(DIAMOND_EGG_KEY) or 0)}/{need} "
                     f"held), never hatched"),
                blocked=("" if count else
                         f"{DIAMOND_EGG_TICKETS + keep - int(tickets):,} tickets short "
                         f"({int(tickets):,} held, {keep:,} kept back)")))
    if settings.bool("economy.tickets.magic_beans"):
        side = next((x for x in SIDE_PURCHASES if x["label"] not in set(bought or ())
                     and x["materials"].get("magic_bean", 0) > int(held.get("magic_bean") or 0)),
                    None)
        lacking = int((getattr(crafting, "lacking", None) or {}).get("magic_bean") or 0)
        short, for_what = 0, ""
        if side is not None:
            short = side["materials"]["magic_bean"] - int(held.get("magic_bean") or 0)
            for_what = f"the {side['label']}"
        elif lacking:
            short, for_what = lacking, f"the Blender's crafts for the {crafting.goal}"
        if short:
            count = min(short, spare // MAGIC_BEAN_TICKETS)
            out.append(Purchase(
                key="magic_bean", label="Magic Bean", shop=BEAN_SHOP,
                shop_label="Magic Bean Shop", tickets=max(1, count) * MAGIC_BEAN_TICKETS,
                count=max(1, count), ready=bool(count), can_buy=False,
                why=f"for {for_what} ({short} short)",
                blocked=(f"{BEAN_LOOK_ONLY}: {count} for {count * MAGIC_BEAN_TICKETS:,} tickets"
                         if count else
                         f"{MAGIC_BEAN_TICKETS + keep - int(tickets):,} tickets short "
                         f"({int(tickets):,} held, {keep:,} kept back)")))
    return out


# NEVER BOUGHT, whatever else says so (the playbook: `no_diamond_or_mythic_eggs`,
# `buying_traps`).
NEVER = frozenset({"diamond_egg", "mythic_egg", "ticket_shop_tickets_past_500",
                   "royal_jelly_for_tickets", "blender_speed_up",
                   "ant_pass_for_tickets", "treats_for_levelling"})
# BUT THE ALT MAY BUY EGGS (HIVEMIND_ROLE=alt; the owner, 2026-10-13: "spend and
# do whatever that doesnt cost robux"). The traps stay for it too. Robux is
# refused for every role in act/shoplook.buy (ROBUX_WORDS), which no role
# touches.
if ROLE == "alt":
    NEVER = NEVER - {"diamond_egg", "mythic_egg"}


@dataclass
class Purchase:
    key: str
    label: str
    shop: str = ""
    shop_label: str = ""
    honey: int = 0
    tickets: int = 0
    count: int = 1
    why: str = ""
    ready: bool = False          # everything it costs is in hand
    can_buy: bool = False        # ready AND the bot can complete it at its shop
    blocked: str = ""            # what stands in the way, "" when nothing

    def describe(self) -> str:
        cost = (f"{self.honey:,} honey" if self.honey else "") + (
            f"{' + ' if self.honey else ''}{self.tickets:,} tickets" if self.tickets else "")
        what = f"{self.count} {self.label}" if self.count > 1 else self.label
        where = f" at the {self.shop_label}" if self.shop_label else ""
        state = ("buying it" if self.can_buy else
                 f"ready, but {self.blocked}" if self.ready else
                 f"not yet: {self.blocked}")
        return f"{what}{where} for {cost or 'nothing known'} — {self.why}; {state}"


@dataclass
class Shopping:
    purchases: list = field(default_factory=list)
    honey: int | None = None
    kept_for: str = ""           # the goal whose honey is kept back
    kept: int = 0
    would: str = ""              # goals.keep_within's shadow line

    def first(self) -> Purchase | None:
        return self.purchases[0] if self.purchases else None

    def lines(self) -> list[str]:
        out = []
        if self.honey is not None and self.kept_for:
            out.append(f"buying: honey {self.honey:,}; {self.kept:,} of it kept "
                       f"for the {self.kept_for}")
        out += [f"buying {i}: {p.describe()}" for i, p in enumerate(self.purchases, 1)]
        if self.would:
            out.append(self.would)
        return out


def _shop_blocked(shop: str, key: str = "") -> str:
    return ("" if bot_buys(shop, key) else JELLY_NO_FLOW if shop == JELLY_SHOP else
            "the bot has no purchase flow for it at this shop — yours to buy")


def _lots(jelly: int) -> int:
    """`jelly` rounded up to the shop's lots."""
    return -(-max(0, int(jelly)) // JELLY_LOT) * JELLY_LOT


def plan_purchases(plan, *, judgement=None, honey: int | None = None,
                   tickets: int | None = None, bought=(), held: dict | None = None,
                   crafting=None, settings=None, unreached=()) -> Shopping:
    """The purchases, in order. `plan` is brain/goals' Plan (the owner's goal
    order, prices, materials); `judgement` brain/hivejudge's Judgement (what
    jelly is for); `honey` the live balance, else the plan's; `crafting`
    act/blender's Crafting (the jelly the next goal's materials take)."""
    from . import goals as goals_mod
    out = Shopping(honey=honey if honey is not None else getattr(plan, "honey", None))
    first = plan.first_open() if plan is not None else None
    if first is not None and first.key not in NEVER:
        missing = [n for n in first.missing]
        short_honey = (max(0, first.cost - out.honey) if out.honey is not None
                       and first.cost else None)
        ready = first.state == goals_mod.READY
        if first.state == goals_mod.BLOCKED:
            blocked = f"its shop's gate: {first.gate}"
        elif short_honey:
            blocked = f"{short_honey:,} honey short"
        elif missing:
            blocked = "materials short: " + ", ".join(n.describe() for n in missing)
        else:
            blocked = getattr(first, "waits", "") or _shop_blocked(first.shop, first.key)
        p = Purchase(key=first.key, label=first.label, shop=first.shop,
                     shop_label=first.shop_label, honey=int(first.cost or 0),
                     why="the next of the owner's gear goals",
                     ready=ready, blocked=blocked)
        p.can_buy = (ready and bot_buys(first.shop, first.key)
                     and not getattr(first, "waits", ""))
        if p.can_buy:
            p.blocked = ""
        out.purchases.append(p)
        # THE NEXT GOAL'S HONEY IS KEPT: jelly comes out of what is above it
        out.kept_for, out.kept = first.label, int(first.cost or 0)
    # ROYAL JELLY FOR THE BLENDER, before anything else is bought: the jelly
    # the next goal's crafts take, less what is held. Paid from the honey
    # above the goal's own price, so that price stays reachable; and the
    # rest of the gap is KEPT with the goal's honey (it is what the goal
    # really costs), so nothing after it -- the rolls' jelly first -- spends it.
    gap = 0
    if crafting is not None and getattr(crafting, "jelly", 0) and held is not None:
        gap = _lots(crafting.jelly - int(held.get("royal_jelly") or 0))
    if gap:
        made = crafting.what() + (f" for the {crafting.goal}" if crafting.goal else "")
        why = (f"for the Blender: {made} take {crafting.jelly:,} Royal Jelly, "
               f"{int(held.get('royal_jelly') or 0):,} held, so {gap:,} to buy "
               f"({gap * JELLY_PRICE_PLANNED:,} honey at the cap, {JELLY_MAX_PER_VISIT} a visit)")
        waits = [f"{n:,} {s.replace('_', ' ')}" for s, n in crafting.lacking.items()]
        waits += list(crafting.cannot)
        if waits:
            why += "; the Blender also waits on " + ", ".join(waits)
        spare = None if out.honey is None else out.honey - out.kept
        count = (0 if spare is None else
                 int(min(JELLY_MAX_PER_VISIT, gap, max(0, spare // (JELLY_PRICE_PLANNED * JELLY_LOT)) * JELLY_LOT)))
        p = Purchase(key="royal_jelly", label="Royal Jelly", shop=JELLY_SHOP,
                     shop_label="Royal Jelly Shop", count=count or JELLY_LOT,
                     honey=(count or JELLY_LOT) * JELLY_PRICE_PLANNED, why=why,
                     ready=bool(count),
                     blocked=(_shop_blocked(JELLY_SHOP, "royal_jelly") if count else
                              "the honey is not read" if spare is None else
                              f"{JELLY_PRICE_PLANNED * JELLY_LOT - spare:,} honey above what the "
                              f"{out.kept_for or 'next goal'} keeps"))
        p.can_buy = p.ready and bot_buys(JELLY_SHOP, "royal_jelly")
        if p.can_buy:
            p.blocked = ""
        out.purchases.append(p)
        out.kept += gap * JELLY_PRICE_PLANNED
    # THE KEEP RULE, SHADOW (goals.keep_within, GOALS_KEEP_LIVE False): what
    # it would keep beside today's `kept`, which still decides
    if first is not None and out.kept:
        would, why = goals_mod.keep_within(plan, crafting, gap * JELLY_PRICE_PLANNED)
        out.would = (f"goals would: {why}; free {out.kept - would:,} of the "
                     f"{out.kept:,} kept today" if would < out.kept else
                     f"goals would: {why}, as today")
    # THE SIDE PURCHASES, from the honey above what the goal keeps, once
    # every material is counted held (`held`: the last inventory read; none
    # are said before the inventory has been counted)
    for side in (SIDE_PURCHASES if held is not None else ()):
        if side["label"] in set(bought or ()):
            continue
        short = [f"{n - int((held or {}).get(m) or 0):,} {m.replace('_', ' ')}"
                 for m, n in side["materials"].items() if int((held or {}).get(m) or 0) < n]
        spare = None if out.honey is None else out.honey - out.kept
        # ONE CHEAP NEXT TO THE GOAL comes out of what it keeps: the 10M
        # planter against the 894,566,712 slot is minutes of farming
        cheap = side["honey"] <= SIDE_FROM_KEPT_SHARE * out.kept and (out.honey or 0) >= side["honey"]
        ready = not short and spare is not None and (spare >= side["honey"] or cheap)
        far = side["shop"] in set(unreached)
        out.purchases.append(Purchase(
            key=side["key"], label=side["label"], shop=side["shop"],
            shop_label=side["shop_label"], honey=side["honey"], why=side["why"],
            ready=ready, can_buy=ready and not far and bot_buys(side["shop"], side["key"]),
            blocked=(NO_SURVEY if ready and far else "" if ready else
                     "materials short: " + ", ".join(short) if short else
                     "the honey is not read" if spare is None else
                     f"{side['honey'] - spare:,} honey above what the "
                     f"{out.kept_for or 'next goal'} keeps")))
    # ROYAL JELLY FROM THE SURPLUS, for the cells the guide does not want
    if judgement is not None and getattr(judgement, "jelly_on", None) and out.honey is not None:
        surplus = out.honey - out.kept
        lots = max(0, surplus // (JELLY_PRICE_PLANNED * JELLY_LOT))
        count = int(min(JELLY_MAX_PER_VISIT, lots * JELLY_LOT))
        wants = " or ".join(str(b).replace("_", " ").title()
                            for b in (getattr(judgement, "jelly_hits_for", None) or []))
        rolls = getattr(judgement, "jelly_rolls", None)
        cells = ", ".join(str(b).replace("_", " ").title()
                          for b in judgement.jelly_on)
        why = (f"to roll the {cells} — bees the guide does not want — for a "
               f"{wants or 'wanted bee'}"
               + (f" (about {rolls:,.0f} rolls each)" if rolls else ""))
        if gap:
            # THE BLENDER'S JELLY COMES FIRST: what is bought before its gap
            # is closed would only be kept for it (run_farm jelly_keep)
            p = Purchase(key="royal_jelly", label="Royal Jelly", shop=JELLY_SHOP,
                         shop_label="Royal Jelly Shop",
                         honey=JELLY_PRICE_PLANNED * JELLY_LOT, count=JELLY_LOT,
                         why=why, ready=False,
                         blocked=f"the Blender's {gap:,} Royal Jelly come first")
        elif count:
            p = Purchase(key="royal_jelly", label="Royal Jelly", shop=JELLY_SHOP,
                         shop_label="Royal Jelly Shop", honey=count * JELLY_PRICE_PLANNED,
                         count=count, why=why, ready=True,
                         blocked=_shop_blocked(JELLY_SHOP, "royal_jelly"))
        else:
            need = (out.kept + JELLY_PRICE_PLANNED * JELLY_LOT) - out.honey
            p = Purchase(key="royal_jelly", label="Royal Jelly", shop=JELLY_SHOP,
                         shop_label="Royal Jelly Shop",
                         honey=JELLY_PRICE_PLANNED * JELLY_LOT, count=JELLY_LOT,
                         why=why, ready=False,
                         blocked=(f"{need:,} honey above what the {out.kept_for} "
                                  f"keeps" if out.kept_for else f"{need:,} honey short"))
        p.can_buy = p.ready and bot_buys(JELLY_SHOP, "royal_jelly")
        if p.can_buy:
            p.blocked = ""
        out.purchases.append(p)
    # THE TICKET TENT'S, with tickets (`tickets`: the last inventory read;
    # none are said before the tickets have been counted)
    for item, price, why in (TENT_PURCHASES if tickets is not None else ()):
        if item in set(bought or ()):
            continue
        ready = tickets is not None and tickets >= price
        out.purchases.append(Purchase(
            key=item.lower().replace(" ", "_"), label=item, shop=TENT_SHOP,
            shop_label="Ticket Tent", tickets=price, why=why, ready=ready,
            can_buy=ready,
            blocked=("" if ready else
                     f"{price - (tickets or 0):,} tickets short" if tickets is not None
                     else "the tickets are not counted yet")))
    # AND WHAT SETTINGS > SPENDING SWITCHED ON (`ticket_purchases`)
    out.purchases += ticket_purchases(plan, tickets, held, settings, bought, crafting)
    return out


def from_files(plan, var_root, *, honey: int | None = None, settings=None) -> Shopping:
    """`plan_purchases` with the hive judged from the last bee read
    (var/bees.json, act/beemenu) and the knowledge files -- the same
    judgement run_farm narrates after a read."""
    import yaml

    from ..datapaths import data
    from . import hivejudge
    judgement = None
    try:
        body = json.loads((Path(var_root) / "bees.json").read_text())
    except (OSError, ValueError):
        body = {}
    if isinstance(body, dict) and body.get("bees") and body.get("verified"):
        try:
            know = Path(data("knowledge"))
            load = lambda name: yaml.safe_load((know / name).read_text()) or {}  # noqa: E731
            types = (load("bee_types.yaml").get("types") or {})
            judgement = hivejudge.judge(
                {k: int(v) for k, v in body["bees"].items()}, body.get("total"),
                types=types, plan=load("blue_hive_plan.yaml"), items=load("items.yaml"),
                verified=True, rows_known=True)
            from .goals import diamond_saved
            judgement.diamond_saved = diamond_saved()
        except Exception:
            judgement = None
    tickets, held = None, None
    try:
        items = json.loads((Path(var_root) / "inventory.json").read_text())["items"]
        held = {k: int(v["count"]) for k, v in items.items()
                if isinstance(v, dict) and v.get("count") is not None}
        tickets = held.get("tickets")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        tickets, held = None, None
    try:
        rows = json.loads((Path(var_root) / "purchases.json").read_text())
        bought = {r.get("item") for r in rows if isinstance(r, dict) and r.get("ok")}
    except (OSError, ValueError, TypeError):
        bought = set()
    return plan_purchases(plan, judgement=judgement, honey=honey, tickets=tickets,
                          bought=bought, held=held, settings=settings,
                          unreached=unsurveyed(var_root),
                          crafting=crafting_from_files(plan, held) if held is not None else None)


def crafting_from_files(plan, held: dict):
    """act/blender.crafting for `plan`'s goals with the consumables' own
    labels -- the same recipe reading the Blender errand makes (run_farm
    blend_due); None when it cannot be read."""
    try:
        import yaml

        from ..act import blender, feed
        from ..datapaths import data
        items = (yaml.safe_load(data("knowledge", "consumables.yaml").read_text())
                 or {}).get("items") or {}
        labels = {slug: str((v or {}).get("label") or slug) for slug, v in items.items()}
        return blender.crafting(getattr(plan, "rows", None) or (), held or {}, labels,
                                feed.item_of)
    except Exception:
        return None

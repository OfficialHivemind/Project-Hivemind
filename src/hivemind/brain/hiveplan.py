"""The hive plan's sharper edge: specific Royal Jelly, Star Jelly, Star Treat
and blueberry targets, from brain-research-2.md's second research pass.

`brain/hivejudge.py` already turns a bee-menu read into the GENERAL case --
the guide's stage comp, and "jelly goes on whatever the guide does not want"
(blue_hive_plan.yaml `jelly_targets: [diamond]`). This module is the
SPECIFIC list the owner asked pass 2 to work out on top of that (P6,
docs/pending/brain-backlog.md:64-65): Star Jelly on Ninja slots, blueberries
into one ungifted rare blue bee, Star Treats held -- and the Royal Jelly
targets, which since 2026-10-21 are the guide's own (`jelly_targets`).

PURE. Every function here takes a bee-menu-style dict ({bee type: count}, and
a `gifted` dict of the same shape where the caller has it -- act/beemenu's
`gifted_star` per row) and returns advice: strings and numbers, never an
action. The owner's rules hold absolutely: this never spends a ticket, a
Royal Jelly, a Star Treat or a blueberry itself, and Royal Jelly is bought
with honey the owner spends himself (never this bot, never Robux) -- see
blue_hive_plan.yaml's own `jelly_honey` note in hivejudge.py, "the owner's
way, honey being what the hive makes".
"""
from __future__ import annotations

# ROYAL JELLY TARGETS FOLLOW THE GUIDE (blue_hive_plan.yaml `jelly_targets`,
# "push to add as many Diamonds as possible"). CORRECTED 2026-10-21: this was
# research pass 2's "Babies to 4, Stubborn, Commander" -- none of them blue,
# Baby a 1-in-267 legendary -- where the owner said YES that day to "use Royal
# Jelly to swap the Basic, Crimson and Cobalt bees for blue ones". What a roll
# KEEPS is brain/hivejudge.keep_roll; which bee it goes on, hivejudge.judge.
GUIDE_REASON = "the guide's jelly_targets (blue_hive_plan.yaml): as many Diamonds as possible"


def jelly_targets(hive_bees: dict, plan: dict) -> list:
    """[(bee_type, reason)] the guide wants Royal Jelly to land, in its own
    order (`plan` is blue_hive_plan.yaml). `hive_bees` is unused: the guide
    wants more Diamonds however many are held."""
    return [(str(b), GUIDE_REASON) for b in (plan or {}).get("jelly_targets") or ()]


# brain-research-2.md §2, "Star Jelly": "Use it on a Ninja slot and keep the
# result if the type is new." "Given the gifted types you already have, about
# 81% of rolls would be a new gifted type." -- measured for THIS account's
# gifted set (Baby, Bear, Bubble, Hasty, Looker, Music, per the research pass
# read of var/bees.json at 00:46 2026-10-11); a different gifted roster would
# need the chance recomputed (hivejudge.jelly_chance does that generically).
STAR_JELLY_NEW_GIFTED_CHANCE = 0.81
# brain-research-2.md §2, "Good outcomes for blue":
STAR_JELLY_GOOD_BLUE_OUTCOMES = {
    "bucko": "x1.20 blue field capacity",
    "bumble": "x1.1 capacity",
    "cool": "x1.1 blue pollen",
    "stubborn": "+15% token lifespan when gifted",
    "diamond": "x1.2 convert rate",
}
# blue_hive_plan.yaml Stage 1 (guide:334): "the 3 Ninjas are listed as
# removable fill bees (Bubbles beat Ninjas for fill)" -- why Ninja is the
# slot to spend a Star Jelly roll on rather than any other.
NINJA_FILL_NOTE = "removable fill bee -- Bubbles beat Ninjas for fill (blue_hive_plan.yaml guide:334)"


def star_jelly_slots(hive_bees: dict) -> dict:
    """Where to spend a Star Jelly: on a Ninja slot, if one is held -- advice
    only, it names a slot, it never rolls one."""
    hive_bees = hive_bees or {}
    ninjas = int(hive_bees.get("ninja", 0))
    if ninjas <= 0:
        return {"slots": 0, "advice": "no Ninja bee held -- nothing to spend a Star Jelly on yet"}
    return {
        "slots": ninjas,
        "advice": f"spend a Star Jelly on a Ninja slot ({ninjas} held, {NINJA_FILL_NOTE}); "
                  f"keep the roll only if the type it lands is new to the hive",
        "new_gifted_chance": STAR_JELLY_NEW_GIFTED_CHANCE,
        "good_outcomes": dict(STAR_JELLY_GOOD_BLUE_OUTCOMES),
    }


# brain-research-2.md §2, "Blueberries": "Blue bees get double bond from them
# (50). Each berry has a gift chance: 1 in 8,000 for a rare, 1 in 10,000 for
# an epic, 1 in 12,000 for a legendary. The account's 3,816 berries fed to one
# ungifted rare blue bee (Bumble or Cool) is about a 38% chance of gifting it."
BLUEBERRY_RARE_GIFT_CHANCE = 1.0 / 8_000
BLUEBERRY_RARE_BLUE_TARGETS = ("bumble", "cool")

# brain-research-2.md §2, "Until a mythic arrives, Star Treats are best
# saved, or spent on bees only Star Treats can gift: event bees such as
# Festive (x1.25 convert rate at hive) and Tabby (+50% crit power)."
STAR_TREAT_MYTHICS = ("buoyant", "fuzzy", "tadpole", "precise", "spicy", "vector")
STAR_TREAT_EVENT_TARGETS = {
    "festive": "x1.25 convert rate at hive",
    "tabby": "+50% crit power",
}
# brain-research-2.md "Corrections the first pass missed" #3: "It costs 1,000
# tickets at the Ticket Tent." Also tickets are kept for Diamond Eggs for the
# Diamond Mask (owner rule) -- this module only ever advises holding both.
STAR_TREAT_TICKET_PRICE = 1_000


def treat_plan(hive_bees: dict, *, gifted: dict | None = None,
                blueberries_held: int | None = None) -> list:
    """Advice for Star Treats and blueberries, as a list of
    {item, action, reason} dicts -- never a spend, per the owner's rule that
    tickets are kept for Star Treats and Diamond Eggs, and he buys Royal
    Jelly himself."""
    hive_bees, gifted = hive_bees or {}, gifted or {}
    out = []
    has_mythic_gifted = any(gifted.get(bee) for bee in STAR_TREAT_MYTHICS)
    if not has_mythic_gifted:
        out.append({
            "item": "star_treat", "action": "hold",
            "reason": "no mythic gifted yet -- saved for the first Buoyant/Tadpole, "
                      "or for an event bee only Star Treats can gift",
        })
    for bee, reason in STAR_TREAT_EVENT_TARGETS.items():
        if not gifted.get(bee):
            out.append({
                "item": "star_treat", "action": f"ok to spend on {bee} once one is held",
                "reason": f"{reason} -- an event bee, so only a Star Treat can gift it",
            })
    out.append({
        "item": "star_treat", "action": "never buy with tickets",
        "reason": f"costs {STAR_TREAT_TICKET_PRICE:,} tickets at the Ticket Tent -- "
                  f"tickets are kept for Star Treats and Diamond Eggs (owner rule), not spent faster",
    })
    target = next((bee for bee in BLUEBERRY_RARE_BLUE_TARGETS
                   if hive_bees.get(bee) and not gifted.get(bee)), None)
    if target:
        advice = {
            "item": "blueberry", "action": f"feed every held blueberry into the ungifted {target}",
            "reason": "1 in 8,000 gift chance per berry on a rare blue bee (brain-research-2.md §2)",
        }
        if blueberries_held:
            chance = 1 - (1 - BLUEBERRY_RARE_GIFT_CHANCE) ** int(blueberries_held)
            advice["chance_with_held"] = round(chance, 4)
        out.append(advice)
    return out


if __name__ == "__main__":
    bees = {"baby": 1, "bubble": 8, "diamond": 12, "ninja": 3, "bumble": 2, "bear": 1}
    assert [t for t, _r in jelly_targets(bees, {"jelly_targets": ["diamond"]})] == ["diamond"]
    assert jelly_targets(bees, {}) == []

    slots = star_jelly_slots(bees)
    assert slots["slots"] == 3
    assert "Ninja" in slots["advice"]
    assert slots["new_gifted_chance"] == STAR_JELLY_NEW_GIFTED_CHANCE
    assert star_jelly_slots({"ninja": 0})["slots"] == 0

    gifted = {"baby": True, "bear": True, "bubble": True, "hasty": True,
              "looker": True, "music": True}
    plan = treat_plan(bees, gifted=gifted, blueberries_held=3816)
    items = {row["item"] for row in plan}
    assert items == {"star_treat", "blueberry"}
    assert any(row["action"] == "hold" for row in plan if row["item"] == "star_treat")
    blue_row = next(row for row in plan if row["item"] == "blueberry")
    assert blue_row["action"].endswith("bumble") or blue_row["action"].endswith("cool")
    assert 0.37 < blue_row["chance_with_held"] < 0.39   # about 38%, as measured

    # a hive with no ungifted rare blue bee and a mythic already gifted: the
    # "hold" line and the blueberry line both drop out
    gifted_with_mythic = dict(gifted, buoyant=True, bumble=True, cool=True)
    quiet = treat_plan({"bumble": 1, "cool": 1}, gifted=gifted_with_mythic, blueberries_held=100)
    assert all(row["item"] != "blueberry" for row in quiet)
    assert all(row["action"] != "hold" for row in quiet)

    print("hiveplan: self-check OK")

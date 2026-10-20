"""The Blender, planned rather than driven: what it can make right now, and
what to make next -- pure, no screen, no click.

THE OWNER, 2026-10-11 (docs/pending/brain-research-2.md, pass 2, P8):
"Commando Chick (a Mythic Egg at the 50th capture) and automating the
Blender, which unlocks Science Bear, then Bucko, and the Blue Extracts the
mask needs." `act/blender.py` is the vision-driven half -- it reads the
Blender's window and clicks Make/Confirm. This module is the planning half:
given an inventory count and what is wanted, which recipe to run next, with
no game state at all. `act/blender.recipe()` parses a goals.yaml source's
prose through OCR-matched item names; RECIPES below is the same data, already
resolved to plain material keys, so this module can be tested and used
without act/feed's `item_of` or a labels table.

WHY SCIENCE BEAR MATTERS HERE: its quest 19, "Meticulously Crafted", needs 10
Blender crafts of ANYTHING before quest 21's Translator unlocks Bucko's
quests -- and once Bucko is gifted, his quests are the one way to Blue
Extract that is not a slow field drop (goals.yaml:432, 473-477). Blue Extract
is also the material the Diamond Mask needs 250 of, 50 berries and 10 Royal
Jelly a batch (brain-research-2.md §6, "Diamond Mask gate"). So until Science
Bear's 10 crafts are done, ANY craftable recipe is worth running -- after
that, the choice narrows to whatever a goal is actually short of.

THE OWNER RULES THIS MODULE NEVER CROSSES: no Robux, ever. Only Basic eggs
and event-bee eggs are hatched -- Star, Silver, Gold, Diamond and Mythic eggs
are SAVED. Tickets are kept for Star Treats and Diamond Eggs for the Diamond
Mask. The owner buys Royal Jelly himself, with honey. Nothing here spends
anything: `next_craft` and `commando_progress` only say what COULD be made
or what a capture count means -- the Blender window itself is only ever
opened by `act/blender.py`, and only a Mythic Egg landing from a capture is
ever SAVED here, never hatched.
"""
from __future__ import annotations

# Every Blender recipe this module currently cares about, as plain material
# keys (consumables.yaml's own slugs where one exists: blue_extract,
# sunflower_seed, strawberry, pineapple, moon_charm, royal_jelly, magic_bean,
# gumdrops -- "gumdrop" and "honeysuckle" are the Blender's own singular
# words and are not yet rows of their own file). Each recipe is quoted from
# goals.yaml's `kind: blender` sources, themselves quoting the wiki's Blender
# page (rev 2026-02-19; Blueberry_Dispenser rev 2026-02-26 for Blue Extract).
RECIPES = {
    "blue_extract": {"blueberry": 50, "royal_jelly": 10},     # goals.yaml:478-481
    "oil": {"sunflower_seed": 50, "royal_jelly": 10},         # goals.yaml:365-368
    "enzymes": {"pineapple": 50, "royal_jelly": 10},          # goals.yaml:386-389
    "glue": {"gumdrops": 50, "royal_jelly": 10},               # goals.yaml:407-410
    "glitter": {"moon_charm": 25, "magic_bean": 1},            # goals.yaml:434-437
    "soft_wax": {"honeysuckle": 5, "oil": 1, "enzymes": 1, "royal_jelly": 10},  # goals.yaml:445-448
    "moon_charm": {"royal_jelly": 1, "pineapple": 5, "gumdrops": 5},            # goals.yaml:456-459
    "red_extract": {"strawberry": 50, "royal_jelly": 10},     # goals.yaml:500-503
}

# goals.yaml:432: Science Bear quest 19 "Meticulously Crafted" needs 10
# Blender crafts (any recipe) before quest 21's Translator unlocks Bucko.
SCIENCE_BEAR_CRAFTS_NEEDED = 10
# goals.yaml:473-477: once Bucko is gifted (after the Translator), his
# quests give at least one Blue Extract each -- the blocked route this
# module is counting crafts toward opening.
SCIENCE_BEAR_UNLOCKS = "bucko quests (at least 1 Blue Extract each)"


def craftable(inventory: dict, recipe: dict) -> int:
    """How many times `recipe` ({material: n needed}) can be made from
    `inventory` ({material: held}). 0 when any ingredient is short or the
    recipe is empty."""
    if not recipe:
        return 0
    counts = [inventory.get(mat, 0) // n for mat, n in recipe.items() if n > 0]
    return min(counts) if counts else 0


def next_craft(inventory: dict, goals: dict, *, science_bear_crafts_done: int = 0) -> dict | None:
    """The next Blender craft worth running, from what `inventory` can
    actually make right now -- pure planning, nothing is crafted.

    `goals`: {material: how many more are still wanted}, e.g.
    {"blue_extract": 250} for the Diamond Mask.

    While Science Bear's 10 crafts are not done, ANY craftable recipe counts
    (goals.yaml:432) -- the cheapest one (fewest ingredients spent) is
    chosen, since they all pay the same toward the quest. After that, the
    recipe is the craftable one whose output `goals` is shortest of.

    None when nothing in `inventory` can make anything.
    """
    options = {name: craftable(inventory, recipe) for name, recipe in RECIPES.items()}
    options = {name: n for name, n in options.items() if n > 0}
    if not options:
        return None
    if science_bear_crafts_done < SCIENCE_BEAR_CRAFTS_NEEDED:
        name = min(options, key=lambda n: sum(RECIPES[n].values()))
        return {
            "craft": name, "recipe": dict(RECIPES[name]), "times_possible": options[name],
            "reason": f"counts toward Science Bear's quest 19 "
                      f"({science_bear_crafts_done}/{SCIENCE_BEAR_CRAFTS_NEEDED} Blender crafts so far, "
                      f"goals.yaml:432) -- unlocks {SCIENCE_BEAR_UNLOCKS}",
        }
    wanted = {name: goals.get(name, 0) for name in options if goals.get(name, 0) > 0}
    if not wanted:
        return None
    name = max(wanted, key=wanted.get)
    return {
        "craft": name, "recipe": dict(RECIPES[name]), "times_possible": options[name],
        "reason": f"goal is still short {wanted[name]} {name}",
    }


# brain-research-2.md §6, "Commando Chick": "It respawns every 30 min and
# keeps its damage between visits. Milestones: 15th capture Star Jelly, 25th
# 100 tickets, 50th Mythic Egg, 100th Star Treat." tickets.yaml:55 confirms
# the per-capture and 25th-capture ticket rows from its own, earlier read
# ("1 per capture, and 100 on the 25th"). The whole list, 2026-10-12, from the
# wiki's Commando_Chick (rev 448352) "Milestone rewards"; act/commando.EXTRA
# holds the same goods capture by capture, priced.
COMMANDO_MILESTONES = {
    5: "Glue",
    10: "Gold Egg -- SAVE, do not hatch (owner rule: only Basic and event-bee eggs are hatched)",
    15: "Star Jelly",
    20: "3 Blue Extract",
    25: "100 tickets",
    30: "10 Stingers",
    40: "10 Ant Passes and 10 Stingers",
    50: "Mythic Egg -- SAVE, do not hatch (owner rule: only Basic and event-bee eggs are hatched)",
    100: "Star Treat",
    200: "Commander Bee Egg -- SAVE, do not hatch (owner rule: only Basic and event-bee eggs are hatched)",
}
COMMANDO_MYTHIC_AT = 50
COMMANDO_TICKET_PER_CAPTURE = 1
COMMANDO_TICKET_BONUS_AT_25 = 100


def commando_progress(captures: int) -> dict:
    """What a Commando Chick capture count means: tickets earned so far, the
    milestone just reached (if `captures` lands on one), the next one ahead,
    and whether a Mythic Egg from the 50th capture is sitting there to be
    SAVED (never hatched -- the owner's standing rule)."""
    captures = max(0, int(captures or 0))
    tickets = captures * COMMANDO_TICKET_PER_CAPTURE
    if captures >= 25:
        tickets += COMMANDO_TICKET_BONUS_AT_25
    ahead = sorted(m for m in COMMANDO_MILESTONES if m > captures)
    return {
        "captures": captures,
        "tickets_so_far": tickets,
        "reached_now": COMMANDO_MILESTONES.get(captures),
        "next_milestone": ahead[0] if ahead else None,
        "next_reward": COMMANDO_MILESTONES[ahead[0]] if ahead else None,
        "mythic_egg_due": captures >= COMMANDO_MYTHIC_AT,
    }


if __name__ == "__main__":
    inv = {"blueberry": 120, "royal_jelly": 25, "sunflower_seed": 10, "pineapple": 0}
    assert craftable(inv, RECIPES["blue_extract"]) == 2     # floor(120/50), floor(25/10) -> 2
    assert craftable(inv, RECIPES["oil"]) == 0               # only 10 sunflower seeds, needs 50
    assert craftable({}, RECIPES["blue_extract"]) == 0
    assert craftable(inv, {}) == 0

    # Science Bear's crafts not done yet: the cheapest craftable recipe wins,
    # even though blue_extract is what the goal actually wants.
    pick = next_craft(inv, {"blue_extract": 250}, science_bear_crafts_done=3)
    assert pick["craft"] == "blue_extract"   # the only one craftable here anyway
    assert "Science Bear" in pick["reason"]

    # once an unrelated recipe is also craftable and the crafts are still
    # short, the cheapest (fewest total ingredients) one is chosen
    inv2 = {"blueberry": 500, "royal_jelly": 100, "moon_charm": 25, "magic_bean": 1}
    pick2 = next_craft(inv2, {"blue_extract": 250}, science_bear_crafts_done=0)
    assert pick2["craft"] == "glitter"        # 25+1=26 ingredients vs blue_extract's 50+10=60
    assert sum(RECIPES["glitter"].values()) < sum(RECIPES["blue_extract"].values())

    # Science Bear's 10 are done: now it is goal-driven
    pick3 = next_craft(inv2, {"blue_extract": 250, "glitter": 1}, science_bear_crafts_done=10)
    assert pick3["craft"] == "blue_extract"
    assert "short 250" in pick3["reason"]

    assert next_craft({}, {"blue_extract": 1}, science_bear_crafts_done=10) is None

    before = commando_progress(49)
    assert before["mythic_egg_due"] is False
    assert before["next_milestone"] == 50

    at = commando_progress(50)
    assert at["mythic_egg_due"] is True
    assert "Mythic Egg" in at["reached_now"] and "SAVE" in at["reached_now"]
    assert at["tickets_so_far"] == 50 + 100   # 1 per capture + the 25th-capture bonus

    assert commando_progress(0)["tickets_so_far"] == 0
    assert commando_progress(24)["tickets_so_far"] == 24   # bonus not yet earned

    print("blenderplan: self-check OK")

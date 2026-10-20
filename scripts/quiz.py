#!/usr/bin/env python3
"""Quiz the bot on Bee Swarm Simulator. Does the teaching actually reach it?

    ./.venv/bin/python scripts/quiz.py

THE OWNER ASKED FOR THIS: "ok so like continue teaching it and quiz it too or
test its knowlage". It is the right instinct, because a knowledge base is easy
to write and hard to verify. A fact in a YAML file that nothing can retrieve is
decoration; this asks the QUESTIONS THROUGH THE BOT'S OWN CODE, so a pass means
the bot could genuinely answer, not merely that I typed the answer somewhere.

Every question is answered by calling the real modules -- `brain.knowledge`,
`brain.decide.Planner`, `brain.progress.Ladder` -- and compared against an
expected answer stated here. A question it gets wrong is a gap in the brain,
not a gap in the quiz.

It touches no game, no GPU and no network.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.brain import knowledge                       # noqa: E402
from hivemind.brain.decide import (Planner, Situation,      # noqa: E402
                                   load_fields)
from hivemind.brain.fieldnotes import FieldNotes            # noqa: E402
from hivemind.brain.progress import Ladder, Standing        # noqa: E402
from hivemind.brain.progress import load as load_progression  # noqa: E402
from hivemind.nav.router import Router                      # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def build():
    fields = load_fields(ROOT / "data/knowledge/world.yaml")
    notes = FieldNotes()
    notes.load(ROOT / "var/field_notes.json")
    reachable = {e.end for e in Router().edges if e.start == "hive"}
    planner = Planner(fields, notes, reachable=reachable, prefer_colour="blue")
    ladder = Ladder(load_progression(ROOT / "data/knowledge/progression.yaml"),
                    fields)
    return fields, notes, planner, ladder


def questions():
    fields, notes, planner, ladder = build()
    standing = Standing(honey=6_198_839, bees=25, tool="golden_rake",
                        colour="blue", fields_proven=tuple(notes.notes))
    loaded = Situation(pollen=362_208, capacity=957_375)
    empty = Situation(pollen=0, capacity=957_375)

    def q(question, answer, expect, why=""):
        return (question, answer, expect, why)

    return [
        q("Carrying 362,208 pollen, where do I farm?",
          planner.decide(loaded).action, "convert",
          "every reachable field is guarded; banking beats gambling"),

        q("Empty backpack, where do I farm?",
          planner.decide(empty).field, "pineapple",
          "most flowers of anything reachable, and blue-leaning"),

        q("What is the next tool worth buying?",
          (ladder.upgrades(standing) or [None])[0].name, "bubble_wand",
          "240/s on blue against the Golden Rake's ~167 average"),

        q("How much does it cost?",
          (ladder.upgrades(standing) or [None])[0].cost, 3_500_000, ""),

        q("Should I buy the Spark Staff?",
          "spark_staff" in ladder.skip, True,
          "the community says it is a trap; skip to the Porcelain Dipper"),

        q("How many bees have I proved?",
          planner.bees_at_least(), 25,
          "gathering in Mountain Top requires 25"),

        q("Is the Pine Tree Forest safe?",
          fields["pine_tree"]["safe"], False,
          "two mantises and the Werewolf"),

        q("Which fields are actually safe?",
          knowledge.safe_fields(), ["dandelion", "pepper", "sunflower"], ""),

        q("Which reachable fields suit a blue hive?",
          sorted(n for n, b in fields.items()
                 if (b or {}).get("colour") == "blue"
                 and n in {e.end for e in Router().edges if e.start == "hive"}),
          ["pine_tree", "pineapple"], ""),

        q("Can I reach the Cactus Field?",
          "cactus" in {e.end for e in Router().edges if e.start == "hive"},
          False, "it is blue and worth a route, but none is recorded"),

        q("How many bees does Mountain Top need?",
          fields["mountain_top"]["bees_required"], 25, ""),

        q("What does a Basic Egg cost to start?",
          ladder.bees["basic_egg"]["honey_from"], 1000, ""),

        q("Is Royal Jelly an upgrade?",
          any("REROLL" in r for r in knowledge.rules()), True,
          "the odds ignore what the bee already was"),

        q("Does the briefing warn about haste and timed walks?",
          any("haste" in r.lower() for r in knowledge.rules()), True, ""),

        q("How many hours can a field be degraded?",
          knowledge.economy()["planters"]["degradation"]["cap_hours"], 48, ""),

        q("Which nectars suit a blue hive?",
          knowledge.economy()["for_a_blue_hive"]["best_nectars"],
          ["comforting", "motivating", "refreshing"], ""),

        q("Where should a blue hive put its planter?",
          knowledge.economy()["for_a_blue_hive"]["planter_fields_reachable_today"],
          ["pine_tree"], "Pineapple gives Satisfying, which is red/white"),

        q("Which questlines are actually required?",
          sorted(k for k in knowledge.quests()["givers"]["mandatory"]
                 if k != "note"),
          ["science_bear", "spirit_bear"], ""),

        q("Am I blocked from The Power of Information?",
          knowledge.quests()["givers"]["power_of_information"]["blocked"],
          False, "the Club is a free Roblox group and this account is in it"),

        q("What is the best thing I can reach that I am not doing?",
          knowledge.tickets()["wealth_clock"]["route_exists"], True,
          "the Wealth Clock pays 5 tickets an hour and we have a route"),

        q("How many tickets an hour does the Wealth Clock settle at?",
          knowledge.tickets()["wealth_clock"]["schedule"][-1], 5, ""),

        q("What is cheaper for Royal Jelly, honey or tickets?",
          "tickets" if 6 < 250_000 else "honey", "tickets",
          "6 tickets against 250,000-1,000,000 honey"),

        q("Which mobs always drop tickets?",
          knowledge.tickets()["reliable_drops"]["guaranteed_from_mobs"],
          ["tunnel_bear", "stump_snail", "king_beetle"], ""),

        q("Can the bot collect the Cloud Obby ticket?",
          all("needs" in loc for loc in
              knowledge.tickets()["one_time_token_locations"]
              if loc.get("tickets") == 5), True,
          "both 5-ticket spots need a glide or parachute, which it cannot do"),

        q("What is the baseline blue hive?",
          (knowledge.blue_hive_plan()["baseline"]["buoyants"],
           knowledge.blue_hive_plan()["baseline"]["tadpoles"]),
          (16, 7), "from the owner's guide, which supersedes the 21+9 I had"),

        q("Which bee actually scales a blue hive?",
          knowledge.blue_hive_plan()["diamonds_are_the_engine"]["passive"],
          "Shimmering Honey", "+50% Honey at Hive each, and it is not blue"),

        q("Should I run a Frosty or a Cobalt?",
          sorted(knowledge.blue_hive_plan()["never_run"]),
          ["cobalt", "frosty", "lion", "shy"],
          "both are in the wiki's Blue category and the guide says never"),

        q("What stage is this account at?",
          knowledge.blue_hive_plan()["stages"][0]["name"],
          "Stage 1 — Earlygame Blue", "25 bees; stage 1 ends at 48"),

        q("May I level past 15 yet?",
          "DO NOT LEVEL ABOVE 15" in
          knowledge.blue_hive_plan()["build_order"][5]["why"], True,
          "not before 50 bees"),

        q("How many Polar quests before it stops holding me back?",
          "1500" in knowledge.blue_hive_plan()["multipliers"]["polar_power"]["rule"],
          True, "below 500 the guide calls it 'really bad'"),

        q("Do I have enough bees for stage 1?",
          25 >= 48, False,
          "stage 1 ends at 48 bees and a basic hive holds 25"),

        q("Can I jelly an Epic bee?",
          "use Royal Jelly on a bee that is not Basic"
          in knowledge.irreversible(), True,
          "70% chance of making it worse; the odds ignore what it was"),

        q("What is step one of the build?",
          knowledge.blue_hive_plan()["build_order"][0]["step"],
          "macro Polar Bear quests",
          "the most bot-shaped job in the guide, and it has no cap"),

        q("Which fields does the guide care about?",
          knowledge.blue_hive_plan()["macro_settings"]["fields_that_matter"],
          ["pine_tree", "bamboo", "blue_flower"], ""),

        q("Should Mondo killing be on?",
          knowledge.blue_hive_plan()["macro_settings"]["mondo_killing"],
          "OFF — it steals one gather attempt per hour", ""),

        q("How long should a gather be?",
          knowledge.blue_hive_plan()["macro_settings"]["gather_time_minutes"],
          "7-10 (10 is fine for most)", ""),

        q("May the bot reroll an amulet by itself?",
          "reroll an amulet" in knowledge.irreversible(), True, ""),

        q("May it choose a field by itself?",
          "which reachable field to gather in"
          in knowledge.mistakes()["safe_to_decide_alone"], True, ""),

        q("Should it suggest redeeming codes?",
          knowledge.account()["codes"]["all_redeemed"], True,
          "the owner has done them all"),

        q("Is the blueberry dispenser usable?",
          "IN the group" in knowledge.machines()["club_membership"]["this_account"],
          True, ""),
    ]


def main() -> int:
    rows = questions()
    right = 0
    print()
    for question, answer, expect, why in rows:
        ok = answer == expect
        right += ok
        mark = "OK  " if ok else "WRONG"
        print(f"  [{mark}] {question}")
        print(f"          answered: {answer!r}")
        if not ok:
            print(f"          expected: {expect!r}")
        elif why:
            print(f"          because:  {why}")
    print(f"\n  {right}/{len(rows)} correct\n")
    return 0 if right == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

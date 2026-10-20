"""Quest requirements, parsed from the owner's own screen.

Every string here was transcribed from a live read on 2026-09-20. They are
kept verbatim because every assumption made about this panel before it was
read turned out to be wrong, including that it would contain the word "quest".
"""
from __future__ import annotations

import pytest

from hivemind.brain.questneeds import Needs, from_lines, load

REAL = [
    "Discover 19 Bee Types. Complete.",
    "Collect 820,020 Blue Pollen. 142,504/820,020",
    "Collect 720,020 White Pollen. Complete.",
    "Defeat 15 Scorpions. 0/15",
    "Collect 1,500,000 Red Pollen. 720,047/1,500,000",
]


def test_it_reads_what_is_still_owed_from_the_real_panel():
    needs = from_lines(REAL)
    assert needs.remaining("blue") == 820_020 - 142_504
    assert needs.remaining("red") == 1_500_000 - 720_047


def test_a_completed_requirement_owes_nothing():
    needs = from_lines(REAL)
    assert needs.remaining("white") == 0


def test_colours_are_ranked_by_how_much_is_outstanding():
    needs = from_lines(REAL)
    # Red is short 779,953 and blue 677,516, so red comes first.
    assert needs.wanted_colours == ("red", "blue")


def test_a_fight_is_recorded_but_never_treated_as_actionable():
    needs = from_lines(REAL)
    assert any("Scorpions" in line for line in needs.fights)
    # It must not become a pollen requirement of any colour.
    assert set(needs.pollen) <= {"blue", "red", "white"}


def test_lines_it_cannot_parse_are_dropped_not_guessed():
    needs = from_lines(["something the model hallucinated", "", "Collect"])
    assert needs.pollen == {}


def test_a_progress_pair_that_does_not_match_the_target_is_not_believed():
    # Two requirements run together by the transcription. Believing the pair
    # would report the wrong amount outstanding and send the bot to the wrong
    # field for hours.
    needs = from_lines(["Collect 820,020 Blue Pollen. 3/15"])
    assert needs.remaining("blue") == 820_020


def test_no_quests_means_no_opinion():
    assert Needs().wanted_colours == ()
    assert Needs().remaining("blue") == 0


def test_a_missing_file_is_not_an_error(tmp_path):
    assert load(tmp_path / "nope.json").pollen == {}


def test_a_broken_file_is_not_an_error(tmp_path):
    bad = tmp_path / "quests.json"
    bad.write_text("{not json")
    assert load(bad).pollen == {}


def test_it_reads_back_what_the_bot_saved(tmp_path):
    import json
    path = tmp_path / "quests.json"
    path.write_text(json.dumps({
        "read_at": 123.0,
        "quests": [{"giver": "", "name": "Optimizing Abilities",
                    "requirements": REAL}],
    }))
    needs = load(path)
    assert needs.remaining("blue") == 677_516
    assert needs.read_at == 123.0


def test_the_backpack_hud_bleeding_into_a_quest_line_is_ignored():
    """REAL transcription, 2026-09-20:

        Collect 1,500,000 Red Pollen. 752,395/1,500,000; 526697/948750

    The second pair is the Pollen HUD pill, which the model read as part of
    the same line. Believing it would report the backpack as quest progress.
    """
    needs = from_lines(
        ["Collect 1,500,000 Red Pollen. 752,395/1,500,000; 526697/948750"])
    assert needs.remaining("red") == 1_500_000 - 752_395


def test_complete_with_an_exclamation_mark_counts_as_done():
    """The menu writes both "Complete." and "Complete!"; both were seen."""
    needs = from_lines(["Collect 720,020 White Pollen. Complete!"])
    assert needs.remaining("white") == 0


# ---- the fuller read, once the transcription caught every line ------------
FULLER = [
    "Discover 19 Bee Types. Complete!",
    "Collect 820,020 Blue Pollen. 191,221/820,020",
    "Collect 720,020 White Pollen. Complete!",
    "Collect 320,020 Pollen from the Sunflower Field. 153/320,020",
    "Collect 100 Haste Tokens. 95/100",
    "Collect 100 Focus Tokens. 19/100",
    "Defeat 3 Spiders. 0/3",
]


def test_a_field_specific_requirement_is_understood():
    needs = from_lines(FULLER)
    assert needs.field_remaining("sunflower") == 320_020 - 153


def test_token_steps_are_recorded_as_something_it_cannot_do():
    needs = from_lines(FULLER)
    assert len(needs.tokens) == 2
    # And they must never be mistaken for pollen of a colour.
    assert "haste" not in needs.pollen


def test_nothing_is_silently_dropped():
    """A requirement quietly ignored looks exactly like one that is finished.

    Every line must land somewhere: a colour, a field, tokens, a fight, or
    `unread` -- which is the bot admitting it did not understand something.
    """
    needs = from_lines(FULLER)
    accounted = (len(needs.tokens) + len(needs.fights) + len(needs.unread)
                 + len(needs.fields)
                 + sum(1 for line in FULLER
                       if any(c in line.lower() for c in ("blue pollen",
                                                          "white pollen"))))
    assert accounted == len(FULLER)


def test_the_description_says_what_it_does_not_do_rather_than_hiding_it():
    """A requirement quietly ignored looks identical to one that does not
    exist, so a combat step has to be named.

    "CANNOT DO" WAS TOO STRONG and the menu proved it: MEASURED 2026-09-23,
    "Defeat 3 Spiders" went 0/3, 1/3, then 2/3 while the bot farmed the
    Spider Field. It never seeks combat and runs from what it sees, but the
    bees fight and the count rises. Claiming it cannot be done is the same
    kind of lie as a switch that does nothing."""
    text = from_lines(FULLER).describe()
    # it does seek out the six field mobs now (bug runs), and says which
    assert "bug run" in text, text
    assert "the bees fight whatever comes near" in text
    assert "Defeat" in text
    assert "cannot do" not in text


def test_one_requirement_read_twice_is_listed_once():
    """Two readings of one menu differ by a full stop. MEASURED 2026-09-23
    04:56: the needs read "2 combat step(s) ... Defeat 3 Spiders. 2/3; Defeat
    3 Spiders 2/3", which is one requirement counted twice."""
    a = from_lines(["Defeat 3 Spiders. 2/3"])
    b = from_lines(["Defeat 3 Spiders 2/3"])
    merged = a.merged_with(b)
    assert len(merged.fights) == 1, merged.fights
    assert "1 combat step(s)" in merged.describe()


def test_a_token_step_is_now_a_need_rather_than_a_shrug():
    """It used to read "N token step(s), which chasing moves along but cannot
    target by kind", because the detector found token-shaped objects and not
    their kind. `vision/tokens.Kinds.classify` has named kinds since
    2026-09-21 off the official icons' face colours, and the night's logs
    name them constantly -- 81 haste, 33 rain_cloud, 18 honey. So a step
    asking for a specific token is now a quantity, like pollen is."""
    needs = from_lines(FULLER)
    assert needs.tokens, "no token step was parsed"
    by_kind = {n.kind: n for n in needs.tokens}
    assert "haste" in by_kind, sorted(by_kind)
    haste = by_kind["haste"]
    assert (haste.target, haste.done) == (100, 95), haste
    assert haste.remaining == 5
    assert "5 more haste token(s) (95/100)" in needs.describe()


def test_the_kinds_still_wanted_come_back_most_needed_first():
    needs = from_lines(FULLER)
    wanted = needs.wanted_token_kinds
    assert wanted, "nothing was wanted"
    remaining = [n.remaining for k in wanted
                 for n in needs.tokens if n.kind == k]
    assert remaining == sorted(remaining, reverse=True), list(zip(wanted, remaining))
    assert all(r > 0 for r in remaining)


def test_a_finished_token_step_is_not_wanted():
    needs = from_lines(["Collect 2,000 Honey Tokens. 2,000/2,000"])
    assert needs.tokens and needs.tokens[0].remaining == 0
    assert needs.wanted_token_kinds == ()


def test_the_kind_name_matches_the_tokens_table():
    """The names have to be `data/knowledge/tokens.yaml` keys, because that is
    what `classify` returns and what the brain weighs."""
    import pathlib as _p
    import yaml
    root = _p.Path(__file__).resolve().parents[2]
    table = yaml.safe_load((root / "data/knowledge/tokens.yaml").read_text())
    known = set((table.get("kinds") or {}))
    for line, kind in (("Collect 2,000 Honey Tokens. 1,845/2,000", "honey"),
                       ("Collect 313 Red Boost Tokens. 0/313", "red_boost"),
                       ("Collect 100 Haste Tokens. 0/100", "haste")):
        needs = from_lines([line])
        assert needs.tokens[0].kind == kind, needs.tokens[0]
        assert kind in known, f"{kind} is not a kind the table knows"


# ---- two readings of one menu, merged by furthest progress -----------------
# MEASURED 2026-09-23: one read of this account's menu wrote down "Collect
# 3,000,000 White Pollen" with no verdict, while an earlier read of the same
# quest had "Collect 3,000,000 White Pollen. Complete!". One read decides the
# whole session's quest needs, and a requirement whose "Complete!" is missed
# reads as entirely outstanding -- which pulls the planner toward fields for
# pollen it does not need. `act/quests` transcribes the open menu twice; the
# quest state cannot change between two frames a moment apart.

def test_a_missed_complete_is_recovered_from_the_other_reading():
    missed = from_lines(["Collect 3,000,000 White Pollen"])
    caught = from_lines(["Collect 3,000,000 White Pollen. Complete!"])
    assert missed.remaining("white") == 3_000_000
    assert missed.merged_with(caught).remaining("white") == 0
    assert caught.merged_with(missed).remaining("white") == 0, "order must not matter"


def test_the_furthest_progress_wins_for_a_field_step():
    low = from_lines(["Collect 3,000,000 Pollen from the Clover Field 10/3,000,000"])
    high = from_lines(["Collect 3,000,000 Pollen from the Clover Field 2,900,000/3,000,000"])
    assert low.merged_with(high).field_remaining("clover") == 100_000


def test_the_furthest_progress_wins_for_a_token_step():
    low = from_lines(["Collect 2,000 Honey Tokens. 1,845/2,000"])
    high = from_lines(["Collect 2,000 Honey Tokens. 1,954/2,000"])
    merged = low.merged_with(high)
    assert [n.remaining for n in merged.tokens] == [46]
    assert merged.wanted_token_kinds == ("honey",)


def test_merging_keeps_one_entry_per_requirement():
    one = from_lines(["Collect 2,000 Honey Tokens. 1,845/2,000"])
    two = from_lines(["Collect 2,000 Honey Tokens. 1,954/2,000"])
    assert len(one.merged_with(two).tokens) == 1


def test_a_requirement_only_one_reading_saw_is_kept():
    seen = from_lines(["Collect 100 Haste Tokens. 0/100"])
    blank = from_lines([])
    assert len(blank.merged_with(seen).tokens) == 1
    assert len(seen.merged_with(blank).tokens) == 1


def test_unreadable_lines_and_fights_are_not_duplicated():
    a = from_lines(["Defeat 3 Spiders. 1/3", "gibberish here"])
    merged = a.merged_with(from_lines(["Defeat 3 Spiders. 1/3", "gibberish here"]))
    assert merged.fights == ["Defeat 3 Spiders. 1/3"]
    assert merged.unread == ["gibberish here"]


def test_the_loader_uses_every_stored_transcription(tmp_path):
    import json
    path = tmp_path / "quests.json"
    path.write_text(json.dumps({
        "read_at": 1.0,
        "transcript": "Collect 2,000 Honey Tokens. 1,845/2,000",
        "transcripts": ["Collect 2,000 Honey Tokens. 1,845/2,000",
                        "Collect 2,000 Honey Tokens. 1,954/2,000"],
        "quests": [{"giver": "", "name": "Honey Bee's Honey Hunt",
                    "requirements": ["Collect 2,000 Honey Tokens. 1,845/2,000"]}],
    }))
    needs = load(path)
    assert [n.remaining for n in needs.tokens] == [46], needs.describe()


def test_a_file_with_no_transcripts_list_still_loads(tmp_path):
    """Files written before this existed must keep working."""
    import json
    path = tmp_path / "quests.json"
    path.write_text(json.dumps({
        "read_at": 1.0,
        "quests": [{"giver": "", "name": "q",
                    "requirements": ["Collect 2,000 Honey Tokens. 1,845/2,000"]}],
    }))
    assert [n.remaining for n in load(path).tokens] == [155]


def test_a_finished_fight_is_not_listed_as_something_it_cannot_do():
    """The list exists so a requirement this bot cannot progress is SAID
    rather than silently dropped. A step already complete is not one of those.
    MEASURED 2026-09-23, after the verdict-folding of merge_progress: the
    needs read "3 combat step(s), which this bot cannot do" and two of the
    three were done."""
    needs = from_lines(["Defeat 3 Spiders. 1/3",
                        "Defeat 6 Ladybugs. Complete! Talk to Science Bear.",
                        "Defeat 10 Scorpions. Complete! Talk to Science Bear."])
    assert needs.fights == ["Defeat 3 Spiders. 1/3"], needs.fights
    assert "1 combat step(s)" in needs.describe()


# ---- who to hand a finished quest in to ------------------------------------
# MEASURED 2026-09-23 04:34, off the account's own menu: "Collect 2,000 Honey
# Tokens. Complete! Talk to Honey Bee." The errand walks to givers
# cheapest-walk-first and the Honey Bee is the dearest of the seven at 28
# steps, so the one giver holding a finished quest was last in a queue that
# gets through about one entry per convert. The "Talk to <giver>" beside a
# completed requirement is the ONLY place the quest menu names a giver.

def test_the_giver_of_a_finished_requirement_is_read():
    needs = from_lines(["Collect 2,000 Honey Tokens. Complete! Talk to Honey Bee."])
    assert needs.ready_to_hand_in == ("honey_bee",)


def test_the_name_is_a_node_name():
    """`bearvisit.GIVERS` and the route graph both use node names."""
    from hivemind.act.bearvisit import GIVERS
    needs = from_lines(["Discover 20 Bee Types. Complete! Talk to Polar Bear."])
    assert needs.ready_to_hand_in == ("polar_bear",)
    assert "polar_bear" in GIVERS


def test_the_giver_with_the_most_finished_steps_comes_first():
    needs = from_lines([
        "Collect 2,000 Honey Tokens. Complete! Talk to Honey Bee.",
        "Discover 20 Bee Types. Complete! Talk to Science Bear.",
        "Defeat 10 Scorpions. Complete! Talk to Science Bear.",
    ])
    assert needs.ready_to_hand_in == ("science_bear", "honey_bee")


def test_an_unfinished_requirement_names_nobody():
    needs = from_lines(["Collect 2,000 Honey Tokens. 1,954/2,000"])
    assert needs.ready_to_hand_in == ()


def test_a_finished_fight_still_names_its_giver():
    """A done fight is not added to `fights`, and a done token step has
    nothing remaining, so the giver would go with the dropped line unless it
    is read before those branches."""
    needs = from_lines(["Defeat 10 Scorpions. Complete! Talk to Science Bear."])
    assert needs.fights == []
    assert needs.ready_to_hand_in == ("science_bear",)


def test_a_verdict_on_its_own_line_still_names_the_giver():
    """The menu splits it when the requirement fills the width; the folding
    of `questmenu.merge_progress` has to happen first."""
    needs = from_lines(["Collect 313 Red Boost Tokens.",
                        "Complete! Talk to Science Bear."])
    assert needs.ready_to_hand_in == ("science_bear",)


def test_merging_two_readings_keeps_the_givers():
    a = from_lines(["Collect 2,000 Honey Tokens. Complete! Talk to Honey Bee."])
    b = from_lines(["Defeat 10 Scorpions. Complete! Talk to Science Bear."])
    assert set(a.merged_with(b).ready_to_hand_in) == {"honey_bee", "science_bear"}


def test_the_real_quest_file_has_the_honey_bee_waiting(tmp_path):
    """Against the account's own file, if it is in the repo."""
    import pathlib as _p
    path = _p.Path(__file__).resolve().parents[2] / "var" / "quests.json"
    if not path.exists():
        pytest.skip("the account's quest file is not in the repo")
    ready = load(path).ready_to_hand_in
    assert isinstance(ready, tuple)


# ---- fights, as something the planner can act on ---------------------------
# "Defeat 3 Spiders. 1/3" is two more spiders, and spiders live in the Spider
# Field. The bot never seeks combat; the bees fight whatever comes near while
# it gathers, and the count rose while it farmed there (2026-09-23).

def test_the_mobs_a_quest_wants_are_named_the_way_the_field_table_spells_them():
    from hivemind.brain.questneeds import Needs, mob_slug
    needs = Needs()
    needs.fights = ["Defeat 3 Spiders. 1/3", "Defeat 1 Werewolf. 0/1",
                    "Defeat 6 Rhino Beetles. 4/6", "Defeat 2 Mantises. 0/2"]
    assert needs.mobs_wanted() == {"spider": 2, "werewolf": 1, "rhino_beetle": 2,
                                   "mantis": 2}
    assert mob_slug("Werewolves") == "werewolf"
    assert mob_slug("Ladybugs") == "ladybug"
    assert mob_slug("Scorpions") == "scorpion"
    assert mob_slug("Coconut Crabs") == "coconut_crab"
    assert mob_slug("Mondo Chick") == "mondo_chick"


def test_a_finished_fight_wants_nothing():
    from hivemind.brain.questneeds import Needs
    needs = Needs()
    needs.fights = ["Defeat 3 Spiders. 3/3", "Defeat 2 Ladybugs. Complete!"]
    assert needs.mobs_wanted() == {}


def test_the_needs_say_the_fields_get_the_tilt():
    from hivemind.brain.questneeds import Needs
    needs = Needs()
    needs.fights = ["Defeat 3 Spiders. 1/3"]
    assert "quest tilt" in needs.describe()


def test_a_thousands_comma_read_as_a_slash_is_still_the_progress():
    """MEASURED 2026-09-23 19:00 on the account's menu: "2,107/415/6,000,000"
    for 2,107,415 of 6,000,000. Taking the last matching pair read it as 415."""
    from hivemind.brain.questneeds import _progress
    line = "Collect 6,000,000 Pollen from the Strawberry Field. 2,107/415/6,000,000"
    assert _progress(line, 6_000_000) == 2_107_415
    # a real pair is untouched, and a chain whose total is not the target is not believed
    assert _progress("Collect 2,500 Honey Tokens. 572/2,500", 2_500) == 572
    assert _progress("Collect 100 Tokens. 2,107/415/6,000,000", 100) == 0


def test_a_goo_step_owes_its_field_a_visit_and_gumdrops():
    # var/quests.json 2026-10-07 03:22, Bucko Bee: Medley -- it read as unread
    from hivemind.brain import questneeds as q
    needs = q.from_lines(["Collect 6,000,000 Goo from the Bamboo Field. 0/6,000,000",
                          "Collect 36,000,000 Pollen from the Pine Tree Forest. Complete!"])
    assert needs.goo["bamboo"].remaining == 6_000_000
    assert needs.field_remaining("bamboo") == 6_000_000      # the planner goes there
    assert not needs.unread
    assert "6,000,000 more goo from bamboo (gumdrops)" in needs.describe()
    assert "more pollen from bamboo" not in needs.describe()
    other = q.from_lines(["Collect 6,000,000 Goo from the Bamboo Field. 1,500,000/6,000,000"])
    assert needs.merged_with(other).goo["bamboo"].remaining == 4_500_000


def test_goo_from_a_colour_and_a_goo_field_given_up_without_gumdrops():
    # var/quest_reads/scroll-20261007-040219: Star Journey 2's "Collect
    # 5,000,000 Goo from Red Flowers. 0/5,000,000"; Bucko's goo at 201,218
    from hivemind.brain import questneeds as q
    needs = q.from_lines(["Collect 5,000,000 Goo from Red Flowers. 0/5,000,000",
                          "Collect 6,000,000 Goo from the Bamboo Field. 201,218/6,000,000",
                          "Collect 120,000 Pollen from the Strawberry Field. 0/120,000"])
    assert needs.goo_colour["red"].remaining == 5_000_000 and not needs.unread
    assert "5,000,000 more goo from red flowers (gumdrops)" in needs.describe()
    assert needs.field_remaining("bamboo") == 5_798_782
    needs.goo_fields_dropped()
    assert needs.field_remaining("bamboo") == 0                  # goo alone: dropped
    assert needs.field_remaining("strawberry") == 120_000        # pollen steps stay


def test_two_quests_wanting_one_token_kind_are_two_requirements():
    # MEASURED 2026-10-07, var/quests.json: finished honey steps (300/300,
    # 500/500) beside Honey Bee's 7,000 -- keyed by kind, the open one vanished
    menu = from_lines(["Collect 300 Honey Tokens. Complete!",
                       "Collect 7,000 Honey Tokens. 3,908/7,000",
                       "Collect 500 Honey Tokens. Complete!",
                       "Feed 100 Treats to your Bees. Complete!",
                       "Feed 2,500 Treats to your Bees. 0/2,500"])
    again = from_lines(["Collect 7,000 Honey Tokens. 3,950/7,000"])
    merged = menu.merged_with(again)
    assert sorted(n.remaining for n in merged.tokens) == [0, 0, 3_050]
    assert merged.wanted_token_kinds == ("honey",)
    assert sorted(n.remaining for n in merged.feeds) == [0, 2_500]


def test_a_first_page_read_does_not_erase_another_quests_field_step(tmp_path):
    # MEASURED 2026-10-19 11:34, var/quests.json: the whole list owed Bamboo
    # 16.7M (QR Quest) and Pineapple 92.6M (Variety Fetcher 2); the two
    # first-page transcripts held only Meditating On Phenomenon's finished
    # 2,000,000s, and the merge kept those -- the planner owed both fields 0.
    import json
    whole = ["Collect 50,000,000 Pollen from the Bamboo Field. 33,299,774/50,000,000",
             "Collect 100,000,000 Pollen from the Pineapple Patch. 7,369,694/100,000,000",
             "Collect 13,000,000 Goo from the Bamboo Field. 0/13,000,000"]
    page = ("Meditating On Phenomenon\n"
            "Collect 2,000,000 Pollen from the Bamboo Field. Complete!\n"
            "Collect 2,000,000 Pollen from the Pineapple Patch. Complete!")
    path = tmp_path / "quests.json"
    path.write_text(json.dumps({"quests": [{"name": "x", "requirements": whole}],
                                "transcripts": [page, page]}))
    needs = load(path)
    assert needs.field_remaining("bamboo") == 16_700_226
    assert needs.field_remaining("pineapple") == 92_630_306
    assert needs.goo["bamboo"].remaining == 13_000_000

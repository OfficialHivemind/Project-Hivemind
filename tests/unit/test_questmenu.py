

# ---- what the first REAL panel actually looked like -----------------------
# Transcribed from the owner's own screen, 2026-09-20. Kept verbatim because
# every assumption about this panel's wording had been wrong until it was read.
REAL_PANEL = ("Optimizing Abilities\n"
              "Discover 19 Bee Types. Complete.\n"
              "Collect 820,020 Blue Pollen")


def test_the_real_panel_is_recognised_even_though_it_never_says_quest():
    from hivemind.vision.questmenu import looks_like_quests
    assert "quest" not in REAL_PANEL.lower()
    assert looks_like_quests(REAL_PANEL) is True


def test_the_real_panel_is_one_quest_with_two_requirements():
    from hivemind.vision.questmenu import parse
    quests = parse(REAL_PANEL)
    assert len(quests) == 1
    assert quests[0].name == "Optimizing Abilities"
    assert len(quests[0].requirements) == 2


def test_panels_that_must_never_be_read_as_quests():
    from hivemind.vision.questmenu import looks_like_quests
    # The Roblox menu is the dangerous one: it carries Leave and Log Out.
    for text in ("", "Are you sure you want to leave?", "Settings",
                 "Make Honey", "Shop", "Collect",
                 "Log Out  Leave  Resume Game"):
        assert looks_like_quests(text) is False, text


def test_one_shape_word_is_not_enough():
    from hivemind.vision.questmenu import looks_like_quests
    assert looks_like_quests("Collect") is False
    assert looks_like_quests("Collect 5 things. Complete.") is True


# ---- a bare "Complete!" line belongs to the requirement above it -----------
# MEASURED 2026-09-23 from `var/quests.json`, the "Ready For Infrared" quest
# as this account actually holds it:
#
#     Discover 20 Bee Types.
#     Complete! Talk to Science Bear.
#     Collect 1818181 Red Pollen.
#     Complete! Talk to Science Bear.
#     Collect 313 Red Boost Tokens.
#     Complete! Talk to Science Bear.
#
# The menu puts the verdict on its own line whenever the requirement fills the
# width, and `brain/questneeds._progress` looks for "complete" IN the
# requirement line. So all six read as untouched, and the planner believed 1.8
# million red pollen and 313 Red Boost tokens were still wanted for a quest
# that was finished and waiting to be handed in.

REAL_READ = [
    "Discover 20 Bee Types.",
    "Complete! Talk to Science Bear.",
    "Collect 1818181 Red Pollen.",
    "Complete! Talk to Science Bear.",
    "Collect 313 Red Boost Tokens.",
    "Complete! Talk to Science Bear.",
]


def test_a_verdict_on_its_own_line_is_folded_onto_the_requirement():
    from hivemind.vision.questmenu import merge_progress
    out = merge_progress(REAL_READ)
    assert len(out) == 3, out
    assert all("Complete!" in line for line in out), out
    assert out[2] == "Collect 313 Red Boost Tokens. Complete! Talk to Science Bear."


def test_the_folded_lines_read_as_finished():
    from hivemind.brain.questneeds import from_lines
    needs = from_lines(REAL_READ)
    assert needs.wanted_token_kinds == (), needs.wanted_token_kinds
    assert needs.remaining("red") == 0, needs.describe()


def test_a_verdict_under_a_quest_title_is_dropped_not_folded():
    """There is nothing to cross-check a "Complete!" against, so it is only
    folded onto a line that asks for something."""
    from hivemind.vision.questmenu import merge_progress
    out = merge_progress(["Ready For Infrared", "Complete!"])
    assert out == ["Ready For Infrared"], out


def test_a_second_verdict_is_not_folded_onto_a_line_that_has_one():
    from hivemind.vision.questmenu import merge_progress
    out = merge_progress(["Collect 16,000 Pollen from the Mushroom Field. Complete!",
                          "Complete! Talk to Polar Bear."])
    assert out == ["Collect 16,000 Pollen from the Mushroom Field. Complete!"], out


def test_a_verdict_is_not_folded_onto_a_line_that_already_shows_progress():
    from hivemind.vision.questmenu import merge_progress
    out = merge_progress(["Defeat 3 Spiders. 1/3", "Complete!"])
    assert out == ["Defeat 3 Spiders. 1/3"], out


def test_a_got_over_total_pair_still_folds_as_before():
    from hivemind.vision.questmenu import merge_progress
    out = merge_progress(["Collect 6,000,000 Pollen", "1,497,207/6,000,000"])
    assert out == ["Collect 6,000,000 Pollen 1,497,207/6,000,000"], out

"""Quest progress, against the owner's OWN quest list.

HIS REPORT, 2026-09-21: "quests section ive done parts of them but it shows
0/(whatever value is on quest) on them even tho ive done some".

He was right, and the cause is in the transcription's shape. The menu draws a
requirement and then its progress on the line BELOW it, so the read comes back

    Collect 6,000,000 Pollen
    1,497,207/6,000,000

as two lines. Everything downstream reads one line at a time and a line with
no letters in it is not a requirement, so the pair was dropped and the step
was left with a target and nothing collected.

TRANSCRIPT is that read, verbatim from var/quests.json, timestamp 1789997607.
Every number in the expectations below was on his screen.
"""
from __future__ import annotations

from hivemind.brain import questneeds as qn
from hivemind.vision import questmenu as qm

TRANSCRIPT = (
    "Pollen Fetcher 5\n"
    "Collect 6,000,000 Pollen\n"
    "1,497,207/6,000,000\n"
    "Ready For Infrared\n"
    "Discover 20 Bee Types. Complete!\n"
    "Collect 1816181 Red Pollen\n"
    "1794130/1816181\n"
    "Collect 636.363 Pollen from the Strawberry Field. Complete!\n"
    "Collect 424.242 Pollen from the Mushroom Field. Complete!\n"
    "Collect 313 Red Boost Tokens\n"
    "96/313\n"
    "Defeat 10 Ladybugs.\n"
    "7/10\n"
    "Defeat 10 Scorpions.\n"
    "4/10\n"
    "Honey Bee's Honey Hunt\n"
    "Collect 2,000 Honey Tokens.\n"
    "368/2,000\n"
    "Polar Bear: Candied Beetles\n"
    "Collect 150,000 Pollen from the Strawberry Field. Complete! Talk to Polar Bear.\n"
    "Collect 25,000 Pollen from the Blue Flower Field. Complete! Talk to Polar Bear.\n"
    "Collect 16 Rhino Beetles. Complete! Talk to Polar Bear.\n"
    "12670/1072500\n"
    "Server Version: 624\n"
    "VIP Server commands: /kick playerName /ban playerName /unban playerName"
)


def quests():
    return qm.parse(TRANSCRIPT)


def steps():
    out = []
    for quest in quests():
        out += qn.steps_of(quest.name, quest.requirements)
    return out


def step_named(fragment: str):
    found = [s for s in steps() if fragment.lower() in s.text.lower()]
    assert len(found) == 1, f"{fragment!r} matched {[s.text for s in found]}"
    return found[0]


# ---- THE BUG ---------------------------------------------------------------
def test_progress_on_its_own_line_reaches_the_step():
    """0/6,000,000 was on screen as 1,497,207/6,000,000."""
    step = step_named("Collect 6,000,000 Pollen")
    assert (step.done, step.total) == (1_497_207, 6_000_000)
    assert 0.24 < step.fraction < 0.25


def test_every_step_the_owner_had_started_shows_its_real_progress():
    got = {(s.done, s.total) for s in steps()}
    for pair in [(1_497_207, 6_000_000), (1_794_130, 1_816_181),
                 (96, 313), (7, 10), (4, 10), (368, 2_000)]:
        assert pair in got, f"{pair} is on his screen and not in {sorted(got)}"


def test_not_one_step_is_left_at_zero():
    """The symptom, stated as the test. Every step in that read had either
    progress or a Complete! against it."""
    stuck = [s.text for s in steps() if s.total and not s.done]
    assert stuck == [], stuck


# ---- the backpack HUD behind the menu --------------------------------------
def test_the_backpack_number_is_not_read_as_quest_progress():
    """"12670/1072500" is the pollen pill showing through the menu. It sits
    under "Collect 16 Rhino Beetles", whose target is 16."""
    step = step_named("Rhino Beetles")
    assert (step.done, step.total) == (16, 16)
    assert not any(s.total == 1_072_500 for s in steps())


def test_a_pair_is_only_believed_when_its_total_matches_the_target():
    assert qm.merge_progress(["Collect 16 Beetles.", "12670/1072500"]) == [
        "Collect 16 Beetles."]
    assert qm.merge_progress(["Collect 16 Beetles.", "7/16"]) == [
        "Collect 16 Beetles. 7/16"]


def test_a_pair_with_nothing_above_it_is_dropped():
    assert qm.merge_progress(["4/10"]) == []


def test_a_requirement_that_already_has_its_pair_is_not_given_another():
    assert qm.merge_progress(["Collect 10 Bees. 3/10", "7/10"]) == [
        "Collect 10 Bees. 3/10"]


# ---- the quest list itself -------------------------------------------------
def test_all_four_of_his_quests_are_found():
    assert [q.name for q in quests()] == [
        "Pollen Fetcher 5", "Ready For Infrared",
        "Honey Bee's Honey Hunt", "Polar Bear: Candied Beetles"]


def test_a_bear_s_name_in_a_TITLE_does_not_make_it_a_requirement():
    """"Honey Bee's Honey Hunt" and "Polar Bear: Candied Beetles" are titles.
    Both matched the old requirement word list, so both were filed as steps of
    the quest above them and two of his four quests disappeared."""
    names = [q.name for q in quests()]
    assert "Honey Bee's Honey Hunt" in names
    assert "Polar Bear: Candied Beetles" in names
    infrared = next(q for q in quests() if q.name == "Ready For Infrared")
    assert len(infrared.requirements) == 7, infrared.requirements


def test_the_server_version_line_is_not_a_quest():
    """The transcription runs past the quest list into the rest of the screen.
    "Server Version: 624" became a quest with the VIP command list as its
    requirement and appeared in the GUI."""
    assert not any("Server Version" in q.name for q in quests())
    assert not any("kick" in r for q in quests() for r in q.requirements)


# ---- numbers as the model spells them --------------------------------------
def test_a_thousands_separator_written_as_a_dot_is_still_a_thousand():
    """The model wrote "636.363" for 636,363 twice in the same panel."""
    assert qm.number("636.363") == 636_363
    assert qm.number("424.242") == 424_242
    assert qm.number("1,497,207") == 1_497_207


def test_a_real_decimal_is_not_reinterpreted():
    assert qm.number("1.5") is None
    assert qm.number("0.75") is None
    assert qm.number("") is None and qm.number(None) is None
    assert qm.number("twelve") is None


def test_a_complete_step_with_a_dotted_target_reads_as_finished():
    step = step_named("636.363")
    assert step.complete and step.done == step.total == 636_363


# ---- what the planner does with it -----------------------------------------
def test_the_planner_sees_what_is_actually_left():
    """Before the fold it believed 1,816,181 red pollen were still wanted."""
    needs = qn.from_lines([r for q in quests() for r in q.requirements])
    assert needs.remaining("red") == 22_051
    assert needs.wanted_colours == ("red",)


def test_a_finished_field_requirement_is_not_still_wanted():
    needs = qn.from_lines([r for q in quests() for r in q.requirements])
    assert needs.field_remaining("strawberry") == 0
    assert needs.field_remaining("blue_flower") == 0


# ---- the step text shown to the owner --------------------------------------
def test_the_folded_pair_is_not_repeated_in_the_words():
    step = step_named("Collect 6,000,000 Pollen")
    assert step.text == "Collect 6,000,000 Pollen"

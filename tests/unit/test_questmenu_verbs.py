"""Quest steps that open with a verb REQUIREMENT_WORDS leaves out (vision/questmenu).

WHOLE is the first whole-list read, 2026-09-30 22:58 (act/questscroll,
var/quest_reads/scroll-20260930-225820/texts.txt), as the model read it.
"""
from __future__ import annotations

from hivemind.vision import questmenu

WHOLE = """Bucko Bee: Scavenge
Collect 5,000,000 Blue Pollen.
Complete!
Collect 505 Blue Ability Tokens.
212/505
Collect 25 Blueberry Tokens.
Complete!
Can't Without Ants
Collect 50,000,000 Pollen.
10,709,965/50,000,000
Collect 2,500,000 Pollen from the Ant Field.
0/2,500,000
Honey Bee's Honey Hunt
Collect 4,500 Honey Tokens.
2,077/4,500
Patterns and Probability
Discover 26 Bee Types.
Complete!
Collect 77 Tokens from Sparkles.
Complete!
Collect 7,777,777 Pollen from the Clover Field.
Complete!
Defeat 7 Vicious Bees.
0/7
Craft 7 Ingredients with the Blender.
Complete!
Use 7 Royal Jellies.
0/7
Polar Bear: High Protein Bug Bar
Collect 180,000 Pollen from the Sunflower Field. 49/180,000
Defeat 4 Mantises.
Complete!
Defeat 4 Scorpions.
Complete!
Defeat 1 Spider.
Complete!
Brown Bear: Solo-Cact
Collect 3,200,000 Pollen from the Cactus Field. 1,323,992/3,200,000
Fire Fighter
Defeat 15 Fire Ants.
0/15
Search For Sunflower Seeds
Raise 6 Bees to Level 6.
Complete!
Feed 100 Treats to your Bees.
0/100
Feed 25 Sunflower Seeds to your Bees.
0/25
Star Journey 1
Collect 25,000,000 White Pollen.
Complete!
Collect 10,000,000 Pollen from the Pumpkin Patch. Complete!
Collect 5,000,000 Pollen from the Pineapple Patch. Complete!
Collect 2,500,000 Pollen from the Dandelion Field. Complete!
Collect 1,000,000 Goo from White Flowers. Complete!
Collect 2,500 Haste Tokens. Complete!
Collect 100 Honey Tokens. Complete!
Defeat 10 Giant Ants. 4/10
Defeat 5 Werewolves. Complete!
Repairing Robo Bear
Obtain 1 Red Drive. 0/1
Obtain 1 White Drive. 0/1
Obtain 1 Blue Drive. 0/1
Obtain 1 Glitched Drive. 0/1"""


def test_every_quest_of_the_whole_list_is_parsed():
    quests = questmenu.parse(WHOLE)
    names = [q.name for q in quests]
    assert len(quests) == 10, names
    seeds = quests[names.index("Search For Sunflower Seeds")]
    assert [r.split(".")[0] for r in seeds.requirements] == [
        "Raise 6 Bees to Level 6", "Feed 100 Treats to your Bees",
        "Feed 25 Sunflower Seeds to your Bees"]
    robo = quests[names.index("Repairing Robo Bear")]
    assert len(robo.requirements) == 4 and all(r.startswith("Obtain 1 ") for r in robo.requirements)


def test_a_leading_verb_is_a_step_and_the_same_letters_in_a_title_are_not():
    assert questmenu.asks_for_something("Earn 10 Hotshot Badges")
    assert questmenu.asks_for_something("Obtain 1 Glitched Drive. 0/1")
    assert not questmenu.asks_for_something("Learning Curve")
    assert not questmenu.asks_for_something("Praise The Queen")
    quests = questmenu.parse("Learning Curve\nCollect 100 Pollen. 0/100")
    assert [q.name for q in quests] == ["Learning Curve"]


def test_the_steps_of_21_oct_that_were_read_as_titles():
    # research 2026-10-21 18:59: two steps dropped, three filed as empty quests
    for step in ("Share 50 Jelly Bean Tokens. 6/50",
                 "Purchase 1 Beequip from Dapper Bear's Shop. 0/1",
                 "Match 5 Pairs in Memory Match Games. 0/5",
                 "Equip 5 Beequips. 0/5", "Chase 256 Fireflies. 170/256"):
        assert questmenu.asks_for_something(step), step
    quests = questmenu.parse("Repairing The White Drive\nCollect 4,000,000 White Goo. 0/4,000,000\n"
                             "Chase 256 Fireflies. 170/256")
    assert [q.name for q in quests] == ["Repairing The White Drive"]
    assert len(quests[0].requirements) == 2


def test_the_steps_of_19_to_21_oct_filed_as_quests():
    # night logs, runs 1067-1165: each of these lines was its own "quest"
    text = ("Pleasant Pastimes\nCatch 10 Pink Bloom Petals.\n0/10\n"
            "Get a Score of 75 in the Ant Challenge.\nPop 100 Bubbles.\n"
            "All About Appearances\nCollect 6 Hours of Satisfying Nectar.\n(0%)\n"
            "A Good Infection\nCollect 4 Hours of Invigorating Nectar.\n44m06s (18%)\n"
            "Collect 8,000,000 Red Pollen.\n2,559,937/8,000,000\nGet Red-y\nCollect 5 Red Pollen.")
    quests = questmenu.parse(text)
    assert [q.name for q in quests] == ["Pleasant Pastimes", "All About Appearances",
                                        "A Good Infection", "Get Red-y"]
    assert quests[0].requirements == ("Catch 10 Pink Bloom Petals. 0/10",
                                      "Get a Score of 75 in the Ant Challenge.",
                                      "Pop 100 Bubbles.")
    assert quests[1].requirements == ("Collect 6 Hours of Satisfying Nectar.",)
    assert len(quests[2].requirements) == 2

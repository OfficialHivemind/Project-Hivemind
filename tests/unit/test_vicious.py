"""The Vicious Bee at night (act/vicious, vision/night): which fields, Natro's
search and square, the messages read row by row, the waits after a kill, a
miss and a loss, and night told from day off the pad's floor."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

import hivemind
from hivemind.act import vicious
from hivemind.vision import night


MOBS = Path(hivemind.__file__).resolve().parents[2] / "data" / "knowledge" / "mobs.yaml"


def test_this_hive_hunts_clover_and_spider_only_easiest_first():
    known = vicious.book(MOBS)
    assert known.max_level == 4 and known.levels["clover"] == (1, 3)
    assert [f.node for f in vicious.tour(41, known)] == ["clover", "spider"]
    assert [f.node for f in vicious.tour(5, known)] == ["clover"]   # Natro: skipped at bees >= gate
    assert vicious.tour(0, known) == []
    every = [f.node for f in vicious.tour(41, known, max_level=12)]
    assert every == ["clover", "spider", "cactus", "rose_field", "mountain_top", "pepper"]


def test_unknown_levels_or_gate_mean_skip(tmp_path):
    assert vicious.tour(41, vicious.book(tmp_path / "missing.yaml")) == []
    only = tmp_path / "m.yaml"
    only.write_text("rogue_vicious_bee:\n  levels: {spider: [2, 4]}\n  beatable_max_level: 4\n")
    assert [f.node for f in vicious.tour(41, vicious.book(only))] == ["spider"]   # clover unknown
    only.write_text("rogue_vicious_bee:\n  levels: {clover: [1, 3]}\n")
    assert vicious.tour(41, vicious.book(only)) == []                            # no gate


def test_a_quest_step_is_counted_and_said_look_only():
    from hivemind.brain import questneeds
    assert questneeds.mob_slug("Vicious Bees") == vicious.QUEST_SLUG
    needs = questneeds.Needs()
    needs.fights = ["Defeat 7 Vicious Bees. 5/7"]       # the live menu, 14-15 Oct
    assert vicious.quest_wants(needs.mobs_wanted()) == 2
    assert vicious.quest_wants({"vicious_bee": 2, "spider": 3}) == 2
    assert vicious.quest_wants(None) == 0
    known = vicious.book(MOBS)
    line = vicious.quest_line(vicious.tour(41, known), known, 2)
    assert line == "vicious would: go to clover for a level 1-3 Vicious Bee (quest wants 2 kill(s))"
    assert vicious.quest_line([], known, 2).startswith("vicious would: not go")


def test_a_kill_with_more_owed_waits_a_night_not_a_day():
    assert vicious.record({}, "killed", 0.0, quest_left=2)["next_at"] == vicious.ABSENT_OPEN_S
    assert vicious.record({}, "killed", 0.0, quest_left=1)["next_at"] == vicious.COOLDOWN_S
    assert vicious.record({}, "killed", 0.0)["next_at"] == vicious.COOLDOWN_S


def test_the_search_is_natros_line_up_zigzag_and_last_leg():
    clover = vicious.FIELDS[0]
    steps = vicious.search_steps(clover)
    assert len(steps) == 2 + 4 * clover.reps + 1
    assert steps[:2] == [{"op": "walk", "keys": "d", "studs": 44.0},
                         {"op": "walk", "keys": "w", "studs": 40.0}]
    assert [s["keys"] for s in steps[2:6]] == ["a", "s", "d", "s"]
    assert steps[-1] == {"op": "walk", "keys": "a", "studs": 88.0}


def test_the_fight_square_comes_back_where_it_began():
    walks = [s for s in vicious.FIGHT_STEPS if s["op"] == "walk"]
    assert [s["keys"] for s in walks] == ["w", "d", "s", "a"]
    assert len({s["studs"] for s in walks}) == 1
    assert sum(s["seconds"] for s in vicious.FIGHT_STEPS if s["op"] == "pause") == 3.0


def _words(*rows):
    """tesseract-shaped words, one row per string, 30 px apart."""
    out = []
    for i, row in enumerate(rows):
        for j, text in enumerate(row.split()):
            out.append(SimpleNamespace(text=text, y=900 + 30 * i + (j % 2) * 3, h=14))
    return out


def test_messages_are_read_row_by_row():
    # a ladybug's defeat beside the Vicious Bee's attack is not its defeat
    lines = vicious.rows(_words("Defeated Ladybug! (+1 Battle Point)",
                                "Vicious Bee is attacking ExamplePlayer in the Clover Field!"))
    assert len(lines) == 2
    assert vicious.heard(lines) == "found"
    assert vicious.heard(["Gifted Vicious Bee has been defeated!"]) == "killed"
    assert vicious.heard(["Vicious Bee is attacking ExamplePlayer", "Vicious Bee has been defeated!"]) == "killed"
    assert vicious.heard(["Vicious Bee left..."]) == "left"
    assert vicious.heard(["+ You diee"]) == "died"            # tesseract on the real pill
    assert vicious.heard(["Defeated Ladybug!", "+590 Honey (from Clover Field)"]) == ""
    assert vicious.heard([]) == ""


def test_a_kill_waits_a_day_a_miss_the_next_night_and_losses_double():
    t = 1_791_300_000.0
    killed = vicious.record({}, "killed", t)
    assert not vicious.due(killed, t + vicious.COOLDOWN_S - 1)
    assert vicious.due(killed, t + vicious.COOLDOWN_S)
    absent = vicious.record({}, "absent", t)
    assert absent["next_at"] == t + vicious.ABSENT_OPEN_S
    lost = vicious.record({}, "died", t)
    assert lost["next_at"] == t + vicious.LOST_RETRY_S
    # a night with nothing found between two losses does not forgive the first
    again = vicious.record(vicious.record(lost, "absent", t), "time", t)
    assert again["next_at"] == t + 2 * vicious.LOST_RETRY_S
    # a kill does
    assert vicious.record(vicious.record(again, "killed", t), "left", t)["next_at"] == t + vicious.LOST_RETRY_S
    many = {}
    for _ in range(12):
        many = vicious.record(many, "died", t)
    assert many["next_at"] == t + vicious.LOST_RETRY_MAX_S


def test_the_state_round_trips(tmp_path):
    path = tmp_path / "vicious.json"
    assert vicious.load(path) == {}
    vicious.save(path, vicious.record({}, "killed", 7.0))
    assert vicious.load(path)["killed_at"] == 7.0


def _frame(night_share=0.0, day_share=0.0):
    """A 1080p frame whose lower half holds these shares of each green."""
    frame = np.full((1080, 1920, 3), 200, np.uint8)
    low = frame[540:].reshape(-1, 3)
    n, d = int(night_share * len(low)), int(day_share * len(low))
    low[:n] = night.NIGHT_RGB[::-1]
    low[n:n + d] = night.DAY_RGB[::-1]
    return frame


def test_night_is_night_green_with_no_day_green():
    assert night.is_night(_frame(0.08))
    assert night.is_night(_frame(0.031))
    assert not night.is_night(_frame(0.015, 0.01))     # a day frame: shade beside sunlit floor
    assert not night.is_night(_frame(0.08, 0.001))      # any day green left: not night
    assert not night.is_night(_frame())                 # neither green: another view
    assert not night.is_night(None)
    got = night.shares(_frame(0.05, 0.0))
    assert abs(got[0] - 0.05) < 1e-3 and got[1] == 0.0


def test_the_switch_is_wired():
    from hivemind.world.settings import wired
    assert wired("combat.vicious")

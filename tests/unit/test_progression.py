"""brain/progression: the researched hive plans, the stage the bot reads the
account to be at, and the next goals after the owner's own list."""
import json

import yaml

from hivemind.brain import goals as goals_plan
from hivemind.brain import progression as prog
from hivemind.brain.buyer import bot_buys
from hivemind.world.settings import Settings, defaults


def blue():
    return prog.load("blue")


def owned(*keys):
    return {k: "test" for k in keys}


# An example mid-game account (made up): 40 bees, ~3B honey, Dipper, Bubble
# and Honey Mask, Porcelain Port-O-Hive, Hiking Boots, Propeller Hat, and a
# Bucko Bee quest in the menu (Science Bear's first Translator spent).
EXAMPLE = dict(bees=40,
             owned=owned("porcelain_dipper", "bubble_mask", "honey_mask",
                         "porcelain_port_o_hive", "hiking_boots", "propeller_hat"),
             quests="Bucko Bee: Clean-up\nCollect 5,250,000 Goo")


def test_all_three_files_parse_to_the_same_shape():
    for hive in prog.HIVES:
        data = prog.load(hive)
        assert data["hive"] == hive
        assert [s["id"] for s in data["stages"]] == ["early", "mid", "late", "endgame"]
        for _i, goal in prog._goals(data):
            assert goal["id"] and goal["label"] and "hive_slot_to" not in goal["id"]
            cost = goal["cost"]
            assert all(isinstance(v, int) for k, v in cost.items() if k != "items"), goal["id"]
            assert all(isinstance(v, int) for v in (cost.get("items") or {}).values()), goal["id"]
            assert goal.get("source"), goal["id"]
    ids = {g["id"] for _i, g in prog._goals(blue())}
    # goals.yaml's keys where the two overlap
    assert {"porcelain_dipper", "bubble_mask", "diamond_mask", "honeycomb_belt",
            "cobalt_guard", "hive_slot<=42", "silver_star_amulet"} <= ids


def test_a_fresh_account_is_early():
    acct = prog.Account(bees=5)
    stage = prog.current_stage(acct, blue(), "blue")
    assert stage.id == "early" and not stage.boundary
    nxt = prog.next_goals(acct, 3, blue(), stage)
    assert len(nxt) == 3 and all(n.stage == "early" for n in nxt)


def test_the_example_is_at_the_mid_late_boundary_as_the_research_says():
    acct = prog.Account(**EXAMPLE)
    stage = prog.current_stage(acct, blue(), "blue")
    assert stage.id == "late" and stage.previous == "mid" and stage.boundary
    assert stage.label == "Blue late (mid not finished)"
    behind = {g["id"] for g in stage.behind}
    assert {"glider", "beekeepers_boots"} <= behind
    assert "science_translator_1" not in behind          # Bucko quests read
    nxt = [n.id for n in prog.next_goals(acct, 6, blue(), stage)]
    assert nxt[:2] == ["glider", "beekeepers_boots"]
    assert not {"porcelain_dipper", "bubble_mask", "porcelain_port_o_hive"} & set(nxt)


def test_a_late_account_with_the_ssa_is_late():
    acct = prog.Account(bees=48, owned=owned("supreme_star_amulet"))
    stage = prog.current_stage(acct, blue(), "blue")
    assert stage.id == "late"
    nxt = [n.id for n in prog.next_goals(acct, 10, blue(), stage)]
    # owning the SSA settles every cheaper Star Amulet, and 48 bees slots to 45
    assert not {"supreme_star_amulet", "silver_star_amulet", "gold_star_amulet",
                "hive_slot<=45"} & set(nxt)


def test_next_goals_skip_owned_and_dearer_gear_replaces_cheaper():
    acct = prog.Account(bees=30, owned=owned("porcelain_dipper", "diamond_mask"))
    nxt = [n.id for n in prog.next_goals(acct, 30, blue())]
    assert "porcelain_dipper" not in nxt
    assert "bubble_mask" not in nxt                      # the Diamond Mask replaces it
    assert "petal_wand" not in nxt                       # needs 35 bees


def test_requirements_by_goal_id_and_by_reading():
    red = prog.load("red")
    stuck = prog.Account(bees=10)
    assert "scythe" not in [n.id for n in prog.next_goals(stuck, 20, red)]
    reds = prog.Account(bees=10, types={"red": 4})
    assert "scythe" in [n.id for n in prog.next_goals(reds, 20, red)]
    data = blue()
    assert prog.requirement(prog.Account(badges={"pine tree": 4, "honey": 3}), "10 Ace badges", data)[0] is False
    assert prog.requirement(prog.Account(), "10 Ace badges", data)[0] is None       # never read
    assert prog.requirement(prog.Account(gifted_min=6), "40 gifted types discovered", data)[0] is None


def test_unknown_slots_are_asked_once():
    # no reader sees boots: the example's state without what was typed
    acct = prog.Account(**dict(EXAMPLE, owned=owned("porcelain_dipper", "bubble_mask",
                                                  "porcelain_port_o_hive")))
    nxt = prog.next_goals(acct, 3, blue())
    cards = prog.questions(acct, blue(), nxt)
    boots = next(c for c in cards if c.id == "progression:slot:boots")
    labels = [o.label for o in boots.options]
    # every hive's boots, cheapest first: white's Hiking Boots too
    assert labels[:3] == ["Basic Boots", "Hiking Boots", "Beekeeper's Boots"]
    assert labels[-1] == prog.NONE_YET
    # what they have for a slot settles it: no card
    acct.owned["hiking_boots"] = "typed"
    assert "progression:slot:boots" not in [c.id for c in prog.questions(acct, blue(), nxt)]
    del acct.owned["hiking_boots"]
    acct.answered = {"progression:slot:boots": prog.NONE_YET}
    assert "progression:slot:boots" not in [c.id for c in prog.questions(acct, blue(), nxt)]


def test_the_readers(tmp_path):
    (tmp_path / "bees.json").write_text(json.dumps(
        {"total": 40, "bees": {"bubble": 14, "diamond": 12, "tabby": 1},
         "gifted": ["bubble", "baby"], "unsure": {"rad": [], "rascal": []}}))
    (tmp_path / "purchases.json").write_text(json.dumps(
        [{"item": "Hive Slot", "ok": True}, {"item": "Golden Gushers", "ok": True},
         {"item": "Basic Egg", "ok": True}, {"item": "Bubble Mask", "ok": False}]))
    (tmp_path / "shoplook.json").write_text(json.dumps({"looks": [
        {"shop": "blue_hq", "window": "Bubble Wand | 3,500.000 Honey | Edguip",
         "browsed": ["Bubble Mask | 100,000,000 Honey | Buy for 100,000,000 Honey"]}]}))
    (tmp_path / "quests.json").write_text(json.dumps({"transcript": "Bucko Bee: Clean-up"}))
    page = tmp_path / "badges" / "20261014-200000"
    page.mkdir(parents=True)
    (page / "page.txt").write_text("Pine Tree Badge - Grandmaster\nTree Badge - Master\n"
                                   "Honey Badge - Master\nStump Badge - Ace\nGoo Badge - Ace")
    s = Settings(tmp_path / "settings.yaml")
    acct = prog.account_from_files(tmp_path, s)
    assert acct.bees == 40 and acct.gifted_min == 2 and acct.types["red"] == 2
    assert "golden_gushers" in acct.owned and "bubble_wand" in acct.owned
    assert "hive_slot" not in acct.owned and "basic_egg" not in acct.owned
    assert "bubble_mask" not in acct.owned                         # a "Buy for" window
    assert acct.badge_count("ace") == 4 and acct.badge_count("master") == 2
    assert "tree" not in acct.badges


def test_the_setting_switches_the_file(tmp_path):
    assert defaults()["progression.hive"] == "blue"
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"progression.hive": "red"}))
    s = Settings(path)
    assert prog.hive_from(s) == "red"
    got = prog.progress(tmp_path, s)
    assert got.hive == "red" and got.stage.hive == "red"
    path.write_text(yaml.safe_dump({"progression.hive": "white"}))
    assert prog.progress(tmp_path, Settings(path)).hive == "white"
    path.write_text(yaml.safe_dump({"progression.hive": "purple"}))
    assert prog.hive_from(Settings(path)) == "blue"


def test_the_planner_puts_his_goals_first_and_the_progression_after(tmp_path):
    (tmp_path / "bees.json").write_text(json.dumps({"total": 40, "bees": {}, "gifted": []}))
    (tmp_path / "quests.json").write_text(json.dumps({"transcript": "Bucko Bee: Clean-up"}))
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"goals.owned": "Porcelain Dipper, Porcelain Port-O-Hive, "
                                                   "Honey Mask, Bubble Mask"}))
    plan = goals_plan.from_files(var_root=tmp_path, settings=Settings(path),
                                 honey=3_000_000_000, rows=[], clock=lambda: 0.0)
    keys = [r.key for r in plan.rows]
    extra = [r for r in plan.rows if r.origin]
    assert extra and all(r.origin == "from the Blue progression" for r in extra)
    first_extra = keys.index(extra[0].key)
    assert all(not r.origin for r in plan.rows[:first_extra])      # their list first
    assert keys[:2] == ["porcelain_dipper", "porcelain_port_o_hive"]
    assert [r.key for r in extra][:2] == ["glider", "beekeepers_boots"]
    assert not extra[0].quiet and all(r.quiet for r in extra[1:])
    assert not any(bot_buys(r.shop, r.key) for r in extra)          # never bought by the bot
    assert plan.progress.stage.id == "late"


def test_the_diamond_eggs_are_saved_for_the_mask():
    mask = next(g for _i, g in prog._goals(blue()) if g["id"] == "diamond_mask")
    entry = prog.plan_entry(prog.Next(mask, "late"), "blue", prog.Account())
    assert entry["materials"]["diamond_egg"] == 5 and "never hatched" in entry["what"]
    assert "never hatched" not in prog.plan_entry(prog.Next(mask, "late"), "blue",
                                                  prog.Account(save_diamond=False))["what"]

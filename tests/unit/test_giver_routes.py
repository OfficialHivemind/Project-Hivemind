"""Quest givers the bot could not reach (2026-10-20): Spirit Bear never due."""
from pathlib import Path

import hivemind

REPO = Path(hivemind.__file__).resolve().parents[2]
SRC = (REPO / "scripts" / "run_farm.py").read_text()


def _body(name):
    body = SRC[SRC.index(f"        def {name}("):]
    return body[:body.index("\n        def ", 10)]


def test_spirit_bear_is_due_again_once_her_last_talk_is_old():
    body = _body("spirit_talk_due")
    assert "SPIRIT_TALK_EVERY_S" in body
    # the ground route's misses must not hold off the ramp (2026-10-20)
    assert 'not _giver_resting("spirit_bear")' not in body
    assert "or stale)" in body
    assert "SPIRIT_TALK_EVERY_S = 6 * 3600.0" in SRC


def test_riley_reaches_the_cannon_ramp_by_the_closed_loop_approach():
    import yaml
    paths = yaml.safe_load((REPO / "data" / "world" / "natro_paths.yaml").read_text())
    edges = paths if isinstance(paths, list) else paths.get("routes") or paths.get("edges")
    riley = next(e for e in edges if e["name"] == "natro_out_riley_bee")
    ops = [s["op"] for s in riley["steps"]]
    assert ops[:3] == ["walk", "hive_offset", "cannon_approach"]


def test_panda_ladder_gets_a_second_look_and_is_never_climbed_blind():
    steer = _body("steer_to_ladder")
    assert 'ladder_seen["seen"] = True' in steer
    assert "if not seen and lost:" in steer            # a first miss steps back and looks again
    climb = _body("climb_the_ladder")
    assert 'if not ladder_seen["seen"]:' in climb and "return None" in climb


def test_a_missing_home_tile_makes_the_next_join_go_by_the_private_link():
    """2026-10-20: two joins in a row 'never found the Servers row'
    after other games were played on the account; the private link needs no home page."""
    assert "JOIN_LINK_FALLBACK_S = 15 * 60.0" in SRC
    i = SRC.index("NO BEE SWARM TILE ON THE HOME PAGE")
    block = SRC[i:i + 1600]
    assert "never_found_the_Servers_row.png" in block and "private_link" in block
    assert "lastserver.share_link(" in block and "server = linked" in block


def test_the_ace_shop_is_surveyed_and_checked_for_owned_gear():
    """2026-10-20: the owner bought the Cobalt Guard; the owned check could not
    look at the Ace Shop (only the MTS and Blue HQ were routed)."""
    assert 'ACE_SHOP_NAME = "ace_shop"' in SRC
    assert "ACE_SHOP_LEGS = (GUILD_SHOP_LEGS[:16]" in SRC
    routes = _body("owned_check_routes")
    assert "routed.add(ACE_SHOP_NAME)" in routes
    check = _body("check_owned_at_the_shop")
    assert "if check.shop == ACE_SHOP_NAME:" in check and 'name="the Ace Shop"' in check
    import yaml
    goals = yaml.safe_load((REPO / "data" / "knowledge" / "goals.yaml").read_text())["goals"]
    assert goals["cobalt_guard"]["shop"] == "ace_shop"


def test_a_survey_that_starts_in_the_wrong_place_walks_no_legs():
    """2026-10-21 05:29: the Ace survey's Blender walk ended by the Strawberry
    Field and its look was filed ok, never to be tried again."""
    body = _body("survey_by_walk")
    assert "arrive_on" in body and "the walk did not arrive" in body
    assert 'arrive_on=("blender",)' in SRC


def test_a_survey_walk_ignores_far_mob_bars_and_errands_go_once_the_morph_is_gone():
    """2026-10-21 05:28: a far bar cut the Ace survey's walk; Haste kept the
    morph wait going until a fresh polar morph began."""
    from hivemind.brain import threat
    assert "survey_walk".startswith(threat.OUTBOUND_PREFIX)
    body = _body("wait_out_the_morph")
    assert "(not home or haste_tracker.read(frame).factor <= 1.0)" in body
    survey = _body("survey_by_walk")
    assert "runner.pattern_snaps_left" in survey


def test_a_buying_survey_that_never_reads_its_prompt_is_failed():
    """2026-10-21: the Pro Shop's and Dapper Bear's counter surveys read no
    "Open Shop", were filed ok and never walked again (Paper Planters waited
    eight days). Opt-in: the look-rounds expect no prompt."""
    body = _body("survey_by_walk")
    assert "must_read=False" in body and "if legs and must_read:" in body
    assert "never read" in body
    assert SRC.count("must_read=True") >= 2        # the Pro Shop and the Ace Shop
    # and the priority survey's own call passes it on (09:41 it did not)
    assert "must_read=bool(must and must[0])" in SRC


def test_a_quest_bug_run_takes_turns_ahead_of_the_places():
    """2026-10-21: no bug run for 27 h while a quest wanted 10 Scorpions --
    a place was due at nearly every convert and the chain ended there."""
    assert ('first = (hand_in, planter_errand, learn_ready, bugrun_for_quest, use_a_place)'
            in SRC)
    assert '_turn["quest_bugs"] = False' in SRC and '_turn["quest_bugs"] = True' in SRC
    assert "if e not in first" in SRC          # never twice in one chain


def test_a_due_quest_bug_run_holds_back_the_bosses_no_quest_wants():
    """2026-10-21 12:15: the Tunnel Bear's 3-minute trip took the convert while
    Polar Bear's 10 Scorpions waited."""
    for name in ("tunnelbear_due()", "stumpsnail_due()", "commando_due()"):
        assert f"if not quest_bugs and {name}:" in SRC
    assert "if beetle_due():" in SRC and "if crab_due():" in SRC   # quests want these
    assert "only_quest=True, plan=bugrun_plan" in _body("quest_bugrun_waiting")


def test_a_surveyed_shop_walks_its_legs_only_from_the_right_start():
    """2026-10-21: the owner asked for reliability -- the Ace Shop's legs
    start at the Blender, whose walk once ended by the Strawberry Field."""
    body = _body("look_at_a_surveyed_shop")
    assert "arrive_on=()" in body and 'routine + "_legs"' in body
    assert "did not arrive" in body
    assert 'tag="ace",\n                    arrive_on=("blender",))' in SRC

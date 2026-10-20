"""The transpiler keeps Natro's `switch HiveSlot`, and refuses what it cannot say.

WHY THESE TESTS EXIST. The first transpile resolved every `switch HiveSlot`
to its `default:` body -- the walk to the ramp corner -- on the reasoning
that the ramp was "the same destination, a little further". It is not: the
`default` branch is the first half of Natro's return, and `nm_findHiveSlot`
is the second. On this account (slot 3) the `case 3` branch ends ON the pad,
and the frames under var/routes/attempt-296 show the character standing on
it after leg 09 and then walking 140 studs away because the branch was gone.
See docs/DESIGN.md 8cc.
"""
import importlib.util
import pathlib

import hivemind

# The tree under test -- whichever `hivemind` is imported -- not this file's.
ROOT = pathlib.Path(hivemind.__file__).resolve().parents[2]


def _transpiler():
    spec = importlib.util.spec_from_file_location(
        "transpile_natro", ROOT / "scripts" / "transpile_natro.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Natro's wf-spider.ahk, verbatim apart from the credits.
SPIDER = '''nm_Walk(22.5, FwdKey)
nm_Walk(27, LeftKey)
send "{" RotLeft " 4}"
nm_Walk(64, FwdKey)
nm_Walk(5.5, FwdKey, RightKey)
nm_Walk(36, FwdKey)

switch HiveSlot
    {
    case 3:
    nm_Walk(2.7, BackKey) ;center on hive pad 3

    default:
    nm_Walk(1.5, BackKey) ;walk backwards to avoid thicker hives
    nm_Walk(35, RightKey) ;walk to ramp
    nm_Walk(2.7, BackKey) ;center with hive pads
    }

; [2024-01-15/rpertusio] Aligns with default SpawnLocation, saves walking if player chose Hive 3
'''


def test_a_slot_switch_keeps_both_branches_as_data():
    tn = _transpiler()
    steps, credits = tn.steps_of(SPIDER)
    switch = steps[-1]
    assert switch["op"] == "slot_switch"
    assert switch["cases"] == {"3": [{"op": "walk", "keys": "s", "studs": 10.8}]}
    # "walk to ramp" is a lean (LEAN_WORDS); the two centring walks are not
    assert switch["default"] == [{"op": "walk", "keys": "s", "studs": 6.0},
                                 {"op": "walk", "keys": "d", "studs": 140.0,
                                  "lean": True, "why": "walk to ramp"},
                                 {"op": "walk", "keys": "s", "studs": 10.8}]
    # nothing before the switch was lost or reordered
    assert [s["op"] for s in steps[:-1]] == ["walk", "walk"] + ["camera"] * 4 + ["walk"] * 3
    assert steps[0] == {"op": "walk", "keys": "w", "studs": 90.0}
    # and the credit after it is still read
    assert any("rpertusio" in c for c in credits)


def test_a_path_without_a_switch_is_unchanged():
    tn = _transpiler()
    plain = "nm_Walk(10, FwdKey)\nnm_Walk(5, LeftKey)\n"
    steps, _ = tn.steps_of(plain)
    assert steps == [{"op": "walk", "keys": "w", "studs": 40.0},
                     {"op": "walk", "keys": "a", "studs": 20.0}]
    assert tn.slot_switch(plain) is None


def test_the_routes_quoted_length_is_the_general_path():
    """`default` is the path every slot can walk; its length is the one a
    scheduler should be told."""
    tn = _transpiler()
    steps, _ = tn.steps_of(SPIDER)
    total = sum(s["studs"] for s in tn.walks_in(steps))
    assert total == 90.0 + 108.0 + 256.0 + 22.0 + 144.0 + 6.0 + 140.0 + 10.8


def test_an_unbalanced_switch_is_left_alone_rather_than_guessed():
    tn = _transpiler()
    broken = "nm_Walk(10, FwdKey)\nswitch HiveSlot\n{\ncase 3:\nnm_Walk(1, BackKey)\n"
    assert tn.slot_switch(broken) is None


def test_a_held_key_with_a_jump_in_it_is_expressed_not_dropped():
    """Natro's wf-coconut: hold Back, coast, jump, coast, release. The walks
    either side of a dropped jump are a route off the wrong side of a ledge,
    so the hop is data now: key_down, coast, jump_hold/release, key_up."""
    tn = _transpiler()
    coconut = ('nm_Walk(20.25, RightKey)\nsend "{" Backkey " down}"\nWalk(22.5)\n'
               'send "{space down}"\nHyperSleep(50)\nsend "{space up}"\nWalk(31.5)\n'
               'send "{" BackKey " up}"\nnm_Walk(33.75, LeftKey)\n')
    steps, _ = tn.steps_of(coconut)
    assert [s["op"] for s in steps] == ["walk", "key_down", "coast", "jump_hold", "pause",
                                        "jump_release", "coast", "key_up", "walk"], steps
    assert steps[1] == {"op": "key_down", "keys": "s"}
    assert steps[2] == {"op": "coast", "studs": 90.0}
    assert steps[4] == {"op": "pause", "seconds": 0.05}
    assert steps[7] == {"op": "key_up", "keys": "s"}
    assert tn.unexpressed_lines(coconut) == []


def test_several_statements_on_one_line_are_all_read():
    """gtq-riley.ahk: `send("{" SC_Space " down}"), HyperSleep(300)` and
    `send("{" SC_Space " up}"), nm_Walk(6, FwdKey)`. A reader that stopped at
    the first match produced every space-up and no space-down."""
    tn = _transpiler()
    assert tn.statements('send("{" SC_Space " down}"), HyperSleep(300)') == \
        ['send("{" SC_Space " down}")', "HyperSleep(300)"]
    assert tn.statements("nm_Walk(2, FwdKey), Sleep(1000)") == ["nm_Walk(2, FwdKey)", "Sleep(1000)"]
    steps, _ = tn.steps_of('send("{" SC_Space " down}"), HyperSleep(300)\n'
                           'send("{" SC_Space " up}"), nm_Walk(6, FwdKey)\n')
    assert [s["op"] for s in steps] == ["jump_hold", "pause", "jump_release", "walk"], steps
    assert steps[1]["seconds"] == 0.3 and steps[3] == {"op": "walk", "keys": "w", "studs": 24.0}


def test_the_trailing_walks_after_an_if_else_belong_to_both_branches():
    """gtq-bucko.ahk ends its if/else with a jump and nine walks up onto the
    platform. `rfind("}")` handed them to the cannon branch because
    `send "{space down}"` is full of braces; block_end knows a string when it
    sees one."""
    tn = _transpiler()
    bucko = ('if (MoveMethod = "walk")\n{\n\tnm_gotoramp()\n\tnm_Walk(27, LeftKey)\n}\n'
             'else\n{\n\tnm_gotoramp()\n\tnm_gotocannon()\n\tsend "{e down}"\n'
             '\tsend "{e up}{" LeftKey " down}"\n\tsend "{space 2}"\n}\n'
             'send "{space down}"\nHyperSleep(100)\nsend "{space up}"\n'
             'nm_Walk(6, FwdKey)\nnm_Walk(28, BackKey)\n')
    walking = tn.walking_branch(bucko)
    assert "nm_gotocannon" not in walking
    assert "nm_Walk(6, FwdKey)" in walking and "nm_Walk(28, BackKey)" in walking
    steps, _ = tn.steps_of(walking)
    assert [s["op"] for s in steps][-5:] == ["jump_hold", "pause", "jump_release", "walk", "walk"]
    # and to the flight, once: Natro runs them after either branch (cannon_branch
    # dropped them until 2026-10-12, so the flight stopped short of the platform)
    flight = tn.cannon_branch(bucko)
    assert "nm_gotocannon" in flight and "nm_Walk(27, LeftKey)" not in flight
    assert flight.count("nm_Walk(6, FwdKey)") == 1 and flight.count("nm_Walk(28, BackKey)") == 1
    steps, _, unknown = tn.cannon_steps_of(flight)
    assert unknown == [] and steps[-2:] == [{"op": "walk", "keys": "w", "studs": 24.0},
                                            {"op": "walk", "keys": "s", "studs": 112.0}]


def test_the_checked_in_flights_end_with_the_walk_natro_runs_after_the_if_else():
    """gtq-bucko's 17 lines after its if/else, gtc-megamm's 12: the flight's
    last steps are the walk's last steps (the same lines), and only once."""
    from hivemind.nav.router import Router
    edges = {e.name: e for e in Router().edges}
    for node, shared in (("bucko_bee", 17), ("mega_memory_match", 13)):
        walk = edges[f"natro_out_{node}"].steps
        flight = edges[f"natro_out_{node}_via_red_cannon"].steps
        assert flight[-shared:] == walk[-shared:], node
        assert flight[-shared - 1] != walk[-shared - 1], node


def test_a_walk_home_that_presses_the_portal_is_refused():
    tn = _transpiler()
    portal = 'nm_Walk(18, RightKey)\nsend("{" SC_E " down}")\nsend("{" SC_E " up}")\nnm_Walk(5, RightKey)\n'
    assert tn.presses_e(tn.steps_of(portal)[0])
    assert not tn.presses_e(tn.steps_of("nm_Walk(5, FwdKey)")[0])


def test_what_the_transpiler_still_cannot_say_is_named():
    tn = _transpiler()
    assert tn.unexpressed_lines("nm_Move(1500*round(18/MoveSpeedNum, 8), RightKey)") == \
        ["nm_Move(1500*round(18/MoveSpeedNum, 8), RightKey)"]
    assert tn.unexpressed_lines(SPIDER) == []


def test_the_checked_in_routes_are_what_the_transpiler_says_they_are():
    """Every walk home in data/world/natro_paths.yaml is faithful: all
    seventeen Natro paths -- the two through the blue portal (Bamboo, Blue
    Flower) with its E as a guarded `interact_when` that presses only on a
    panel naming the portal, never a blind E."""
    from hivemind.nav.router import Router
    rt = Router()
    home = {e.name.split("natro_home_")[1] for e in rt.edges
            if e.name.startswith("natro_home_")}
    assert home == {"bamboo", "blue_flower", "cactus", "clover", "coconut",
                    "dandelion", "mountain_top", "mushroom", "pepper", "pine_tree",
                    "pineapple", "pumpkin", "rose_field", "spider", "strawberry",
                    "stump", "sunflower"}, sorted(home)
    for name in ("natro_home_bamboo", "natro_home_blue_flower"):
        edge = next(e for e in rt.edges if e.name == name)
        presses = [s for s in edge.steps if s.get("op") in ("interact", "interact_when")]
        assert presses and all(s.get("op") == "interact_when" and "portal" in s.get("expect", [])
                               for s in presses), (name, presses)
    switched = {e.name.split("natro_home_")[1] for e in rt.edges
                if e.name.startswith("natro_home_")
                and any(s.get("op") == "slot_switch" for s in e.steps)}
    assert switched == {"cactus", "clover", "mountain_top", "mushroom", "pine_tree",
                        "pineapple", "pumpkin", "spider", "strawberry", "stump"}, sorted(switched)


def test_a_loop_is_written_out_as_many_times_as_it_runs():
    """wf-mountaintop: fifteen steps of (back 3, left 1) down the mountain."""
    tn = _transpiler()
    text = "Loop 15\n{\n\tnm_Walk(3, BackKey)\n\tnm_Walk(1, LeftKey)\n}\nnm_Walk(36, FwdKey, RightKey)\n"
    steps, _ = tn.steps_of(text)
    assert len(steps) == 31
    assert steps[:2] == [{"op": "walk", "keys": "s", "studs": 12.0},
                         {"op": "walk", "keys": "a", "studs": 4.0}]
    assert steps[28:30] == steps[:2]
    assert steps[30] == {"op": "walk", "keys": "wd", "studs": 144.0}
    assert tn.expand_loops("nm_Walk(5, FwdKey)") == "nm_Walk(5, FwdKey)"


def test_what_comes_before_the_if_belongs_to_both_branches():
    """wf-pineapple walks nine statements and turns the camera a half turn
    BEFORE its `if (HiveBees < 12)`; dropping them started the route inside
    the branch, a half turn wrong."""
    tn = _transpiler()
    text = ('nm_Walk(18, FwdKey)\nsend "{" RotLeft " 4}"\nif (HiveBees < 12) {\n'
            '\tnm_Walk(12, FwdKey)\n}\nelse {\n\tsend "{e down}"\n}\nnm_Walk(2.7, BackKey)\n')
    steps, _ = tn.steps_of(tn.walking_branch(text))
    assert [s["op"] for s in steps] == ["walk"] + ["camera"] * 4 + ["walk", "walk"], steps
    assert steps[0] == {"op": "walk", "keys": "w", "studs": 72.0}
    assert steps[-1] == {"op": "walk", "keys": "s", "studs": 10.8}


def test_natros_own_comments_mark_the_leans_and_nothing_else():
    """Strawberry: three leans, then "move forward past", "align with
    SpawnLocation" and "walk towards hives", which are not. Sunflower's
    "back out of corner" is the trap: a fixed offset that mentions a corner."""
    tn = _transpiler()
    strawberry = ('nm_Walk(12, BackKey)            ;walk back against wall\n'
                  'nm_Walk(15, BackKey, LeftKey)   ;move to corner (betwen strawberry & vicious bee)\n'
                  'nm_Walk(18, LeftKey)            ;ensure against vicious bee platform\n'
                  'nm_Walk(15, FwdKey)             ;move forward past vicious bee platform\n'
                  'nm_Walk(6, LeftKey)             ;align with SpawnLocation\n'
                  'nm_Walk(95, FwdKey)             ;walk towards hives\n')
    steps, _ = tn.steps_of(strawberry)
    assert [bool(s.get("lean")) for s in steps] == [True, True, True, False, False, False]
    assert steps[0]["why"] == "walk back against wall"
    sunflower = ('nm_Walk(13.5, RightKey) ;walk to edge of field\n'
                 'nm_Walk(45, FwdKey)     ;walk to corner (special sprout)\n'
                 'nm_Walk(2.25, BackKey)  ;back out of corner\n'
                 'nm_Walk(25, FwdKey, LeftKey) ;move diagonally towards hives\n')
    steps, _ = tn.steps_of(sunflower)
    assert [bool(s.get("lean")) for s in steps] == [True, True, False, False]
    # no comment, no lean; a comment in a string is not a comment
    assert not tn.steps_of("nm_Walk(5, FwdKey)\n")[0][0].get("lean")


def test_the_checked_in_strawberry_walk_home_leans_first():
    from hivemind.nav.router import Router
    rt = Router()
    steps = next(e for e in rt.edges if e.name == "natro_home_strawberry").steps
    walks = [s for s in steps if s["op"] == "walk"]
    assert [bool(s.get("lean")) for s in walks] == [True, True, True, False, False, False]


def test_the_cactus_flight_ends_with_a_running_jump_onto_the_field():
    # MEASURED: it came down at the foot of the field's ledge on every kept
    # flight (attempts 283-285, 664); transpile_natro LANDINGS finishes it
    import yaml
    edges = yaml.safe_load((ROOT / "data/world/natro_paths.yaml").read_text())["edges"]
    route = next(e for e in edges if e["name"] == "natro_out_cactus_via_red_cannon")
    tail = [(s["op"], s.get("keys")) for s in route["steps"][-5:]]
    assert tail == [("key_down", "w"), ("pause", None), ("jump", None), ("pause", None),
                    ("key_up", "w")]


def test_the_coconut_walk_ends_with_a_short_running_jump_into_the_field():
    # MEASURED 2026-10-06 12:57: it ended on the sand at the field's front edge
    # (attempt-685); transpile_natro WALK_LANDINGS finishes it, on the walk only
    import yaml
    edges = yaml.safe_load((ROOT / "data/world/natro_paths.yaml").read_text())["edges"]
    route = next(e for e in edges if e["name"] == "natro_out_coconut")
    tail = [(s["op"], s.get("keys"), s.get("seconds")) for s in route["steps"][-6:]]
    # (the walk a 54 before it is a running jump since 2026-10-13: test_route_patches)
    assert tail == [("key_up", "a", None), ("key_down", "w", None), ("pause", None, 0.1),
                    ("jump", None, None), ("pause", None, 0.3), ("key_up", "w", None)]
    home = next(e for e in edges if e["name"] == "natro_home_coconut")
    assert home["steps"][-1]["op"] != "key_up"

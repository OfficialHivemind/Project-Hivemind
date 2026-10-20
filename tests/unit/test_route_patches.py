"""Hand patches to data/world/natro_paths.yaml (a generated file: a
re-transpile of Natro's paths would silently drop them -- this test is what
notices). Each is measured; see the `why:` on the step and git log."""
from hivemind.nav.router import Router


def _walks(name):
    edge = next(e for e in Router().edges if e.name == name)
    return [(s.get("keys"), s.get("studs"), bool(s.get("lean")))
            for s in edge.steps if s.get("op") == "walk"]


def test_sticker_stack_and_honey_bee_lean_past_the_corner():
    # 2026-10-12: d24/a24 stopped at the wall corner (Haste or not)
    for route in ("natro_out_sticker_stack", "natro_out_honey_bee"):
        walks = _walks(route)
        i = walks.index(("d", 36.0, False))
        assert walks[i + 1:i + 3] == [("w", 28.0, False), ("a", 36.0, True)], route


def test_extreme_memory_match_jumps_once_more_before_turning_right():
    # 2026-10-12: 3 of its 4 misses since 10-03 stood at step 39 where the
    # landings stood at step 35 -- one jump + 104 behind; that leg runs twice now
    edge = next(e for e in Router().edges if e.name == "natro_out_extreme_memory_match")
    ops = [(s.get("op"), s.get("keys"), s.get("studs", s.get("seconds"))) for s in edge.steps]
    leg = [("jump_hold", None, None), ("pause", None, 0.2),
           ("jump_release", None, None), ("coast", None, 104.0)]
    i = ops.index(("coast", None, 72.0))
    assert ops[i + 1:i + 10] == leg * 2 + [("key_up", "w", None)]


def test_a_route_revision_changes_only_that_routes_signature():
    from types import SimpleNamespace
    from hivemind.brain import skills
    steps = [{"op": "walk", "keys": "w", "studs": 10.0}]
    plain = SimpleNamespace(name="natro_out_anything", steps=steps)
    bucko = SimpleNamespace(name="natro_out_bucko_bee", steps=steps)
    assert skills.steps_signature(plain) != skills.steps_signature(bucko)
    old = dict(skills.ROUTE_REVISIONS)
    try:
        skills.ROUTE_REVISIONS.clear()
        assert skills.steps_signature(plain) == skills.steps_signature(bucko)
    finally:
        skills.ROUTE_REVISIONS.update(old)


def test_coconut_walk_jumps_left_out_of_the_sand_crack():
    # 2026-10-13: 10 of 16 walks ended the 72-stud coast in the crack under the
    # cliff, and Natro's walk a 54 moved nothing from there in 9 of them
    edge = next(e for e in Router().edges if e.name == "natro_out_coconut")
    ops = [(s.get("op"), s.get("keys"), s.get("studs", s.get("seconds"))) for s in edge.steps]
    i = ops.index(("coast", None, 72.0))
    assert ops[i + 1:i + 6] == [("key_up", "w", None), ("key_down", "a", None),
                                ("jump", None, None), ("coast", None, 54.0),
                                ("key_up", "a", None)]
    assert ("walk", "a", 54.0) not in ops


def test_bamboo_walk_home_leans_left_into_the_wall_first():
    # 2026-10-13: begun at the field's right edge, the timed a60 ended out in
    # the field and the route missed the portal (944, 955, 965, 970, 971)
    assert _walks("natro_home_bamboo")[:2] == [("a", 60.0, True), ("w", 100.0, False)]


def test_dandelion_walk_home_leans_into_the_shop_fence_then_steps_back():
    # 2026-10-14: a timed d168 that ended pressed into the fence under the Noob
    # Shop's corner post sent the w112 into the shop (521, 775, 986 05:22)
    assert _walks("natro_home_dandelion")[:4] == [
        ("w", 54.0, False), ("d", 168.0, True), ("a", 6.0, False), ("w", 112.0, False)]


def test_mushroom_walk_home_is_left_as_natro_wrote_it():
    # 2026-10-14: not a patch -- MEASURED that no leg needs one. Since run-520
    # it landed 30 of 32 walks begun in the field and 0 of 10 begun outside it
    # (7 Sunflower crossings, now R10's); see docs/pending/integration.md.
    assert _walks("natro_home_mushroom")[:4] == [
        ("w", 54.0, False), ("a", 108.0, True), ("a", 46.0, False), ("w", 288.0, False)]


def test_sticker_stack_leans_on_spiders_fence():
    # 2026-10-21: every landing's s36 frame is against the fence, 3 of 4 misses short
    assert _walks("natro_out_sticker_stack")[4] == ("s", 36.0, True)


def test_memory_match_holds_its_ramp_jump_as_pepper_does():
    # 2026-10-21: misses 1159/1162 stayed on the floor at -17-/-18-; w held 0.9 s still
    edge = next(e for e in Router().edges if e.name == "natro_out_memory_match")
    ops = [(s.get("op"), s.get("seconds")) for s in edge.steps]
    i = ops.index(("jump_hold", None))
    assert ops[i:i + 5] == [("jump_hold", None), ("pause", 0.8), ("jump_release", None),
                            ("pause", 0.1), ("key_up", None)]

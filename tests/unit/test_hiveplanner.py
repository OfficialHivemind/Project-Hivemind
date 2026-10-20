"""brain/hiveplanner: the owner's hive plan (ROADMAP H13)."""
from hivemind.brain import hiveplanner as hp

TYPES = {"bubble": {"rarity": "epic"}, "diamond": {"rarity": "legendary"},
         "basic": {"rarity": "common"}, "rad": {"rarity": "rare"},
         "cobalt": {"rarity": "event"}, "tadpole": {"rarity": "mythic"}}


def test_load_save_round_trip(tmp_path):
    path = tmp_path / hp.PLAN_FILE
    assert hp.load(path) == {}
    hp.save(path, {1: "bubble", 50: "diamond", 7: ""})
    assert hp.load(path) == {1: "bubble", 50: "diamond"}


def test_match_counts():
    slots = {1: "bubble", 2: "bubble", 3: "diamond"}
    assert hp.match(slots, {"bubble": 1, "diamond": 4}) == {1: True, 2: False, 3: True}
    assert sum(hp.match(slots, {"bubble": 2, "diamond": 1}).values()) == 3


def test_fill_from_comp():
    slots = hp.fill_from_comp({"bubble": [13, 14], "diamond": [5, 5]})
    assert len(slots) == 19 and slots[1] == "bubble" and slots[19] == "diamond"


def test_targets_never_roll_a_matching_bee():
    assert hp.plan_targets({}, {"basic": 3}, TYPES) is None
    slots = {1: "bubble", 2: "bubble", 3: "diamond", 4: "rad", 5: "bubble"}
    hits, on = hp.plan_targets(slots, {"bubble": 1, "diamond": 1, "rad": 2, "cobalt": 1}, TYPES)
    assert hits == ("bubble",)
    assert on == ("rad",)            # the surplus Rad; never Diamond (matched) nor Cobalt (event)
    # a plan smaller than the hive: only the guide's own unwanted surplus
    _, on = hp.plan_targets({1: "bubble"}, {"basic": 2, "rad": 3}, TYPES, guide_jelly_on=("basic",))
    assert on == ("basic",)
    # nothing short: nothing to roll
    assert hp.plan_targets({1: "bubble"}, {"bubble": 1, "basic": 5}, TYPES) == ((), ())


def test_follow_off_ignores_the_plan(tmp_path):
    """Setting hive.follow_plan off: the plan is only a picture, the guide rules."""
    from hivemind.world.settings import defaults
    assert defaults()["hive.follow_plan"] is False          # U15b: off as shipped
    path = tmp_path / hp.PLAN_FILE
    hp.save(path, {1: "bubble"})
    assert hp.load(path, follow=True) == {1: "bubble"}
    assert hp.load(path, follow=False) == {}
    assert hp.plan_targets(hp.load(path, follow=False), {"basic": 3}, TYPES,
                           guide_jelly_on=("basic",)) is None


def test_bee_faces_fetched_and_squared():
    """scripts/fetch_bee_faces: a face per bee type, 96 x 96 with alpha."""
    import importlib.util
    import pathlib

    import cv2
    import numpy as np
    from hivemind.vision.beemenu import types
    # the tree whose code is under test (hivemind's own package), not this
    # file's: the install gate runs a copy of this test from the live tree
    import hivemind
    root = pathlib.Path(hivemind.__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("fbf", root / "scripts" / "fetch_bee_faces.py")
    fbf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fbf)
    wide = np.zeros((40, 80, 4), np.uint8)
    wide[..., 2] = wide[..., 3] = 255
    out = fbf.square(cv2.imencode(".png", wide)[1].tobytes())
    assert out.shape == (96, 96, 4) and out[0, 0, 3] == 0 and out[48, 48, 3] == 255
    missing = [k for k in types() if not (root / "data" / "bee_faces" / f"{k}.png").exists()]
    assert not missing


def test_slot_numbering_matches_the_view():
    from hivemind.vision import hivecell
    assert hp.cell_of(1) == (0, 1) and hp.cell_of(5) == (4, 1) and hp.cell_of(6) == (0, 2)
    box = (799, 65, 1118, 505)             # hive_box of the 2026-10-13 14:55 jelly view
    (x1, y1), (x2, y2), (x6, y6) = (hivecell.slot_point(box, s) for s in (1, 2, 6))
    assert x2 > x1 and y2 > y1             # column 2 to the right, half a cell lower
    assert x6 == x1 and y6 < y1            # slot 6 straight above slot 1
    assert abs(hivecell.slot_point(box, 41)[1] - 150) < 8   # row 9's left face, measured


def test_slot_targets_never_a_matching_gifted_or_event_cell():
    plan = {1: "bubble", 2: "bubble", 3: "diamond", 4: "rad", 5: "bubble", 6: "bubble"}
    read = {1: "bubble", 2: "rad", 3: "cobalt", 4: "basic", 5: "basic", 6: "tadpole"}
    got = hp.slot_targets(plan, read, TYPES, gifted={5})
    assert [t[0] for t in got] == [4, 2]   # the common Basic first; 1 matches, 3 event,
    assert got[0] == (4, "basic", "rad")   # 5 gifted, 6 a Mythic
    hits, on = hp.plan_targets(plan, {}, TYPES, read=read, gifted={5})
    assert set(hits) == {"rad", "bubble"} and on == ("basic", "rad")
    assert hp.match_slots(plan, {1: "bubble", 2: "rad"}) == {1: True, 2: False}


def test_read_trusted_only_against_the_counts(tmp_path):
    path = tmp_path / hp.SLOTS_FILE
    assert hp.load_read(path) == ({}, set())
    hp.save_read(path, {1: "bubble", 2: "bubble", 3: "rad"}, gifted={3}, at=1.0)
    assert hp.load_read(path, {"bubble": 2, "rad": 1, "basic": 9}) == (
        {1: "bubble", 2: "bubble", 3: "rad"}, {3})
    assert hp.load_read(path, {"bubble": 1, "rad": 1}) == ({}, set())   # stale

"""The hive's bee menu (act/beemenu, vision/beemenu) and its judge (brain/hivejudge)."""
from __future__ import annotations

from pathlib import Path

import yaml

import hivemind

from hivemind.act import beemenu
from hivemind.brain import hivejudge
from hivemind.vision import beemenu as bm
from hivemind.vision import questmenu

# the data beside the CODE under test, not beside this file: the deploy gate copies
# the test into the live tree, whose data is the old one until the install
KNOW = Path(hivemind.__file__).resolve().parents[2] / "data" / "knowledge"


def test_every_bee_type_is_known_with_a_rarity_and_a_colour():
    types = bm.types()
    assert len(types) == 46                          # "46 bee types" (wiki, Bees)
    rarities = {}
    for v in types.values():
        rarities[v["rarity"]] = rarities.get(v["rarity"], 0) + 1
    assert rarities == {"common": 1, "rare": 9, "epic": 11, "legendary": 8,
                        "mythic": 6, "event": 11}
    colours = {}
    for v in types.values():
        colours[v["colour"]] = colours.get(v["colour"], 0) + 1
    assert colours == {"red": 11, "blue": 11, "colourless": 24}


def test_the_button_is_the_smiley_never_the_robux_shop():
    assert questmenu.BUTTONS[bm.BUTTON_INDEX] == "bees"
    assert bm.button() == (139, 128)
    assert beemenu.MENU.button_index != questmenu.BUTTONS.index("robux_shop")


def test_the_header_reads_the_bee_and_type_counts():
    text = "You Have 26 Bees\nYou've Discovered 28 Types of Bees\nBasic Bee: 2"
    assert bm.header(text) == (26, 28)
    assert bm.header("Basic Bee: 2") == (None, None)


def test_rows_are_read_in_the_forms_the_model_writes():
    text = ("You Have 26 Bees\n- Basic Bee: 2\nBubble Bee x4\nDiamond Bee (x1)\n"
            "Rad Bee: 1\nNot A Bee: 9\nName Bee: 3")
    assert bm.counts_in(text) == {"basic": 2, "bubble": 4, "diamond": 1, "rad": 1}


def test_a_quest_panel_is_not_the_bee_list():
    quest = "Bucko Bee: Pollen\nCollect 40,000,000 Blue Pollen. 3/40,000,000\nRiley Bee: Fire"
    assert not bm.looks_like_bee_list(quest)
    assert bm.looks_like_bee_list("You Have 26 Bees")
    assert bm.looks_like_bee_list("Basic Bee: 2\nBubble Bee: 4")
    # names alone, three of them, once the rows' pixels have said it is a list
    assert bm.looks_like_bee_list("Basic Bee\nBomber Bee\nBrave Bee")
    assert not bm.looks_like_bee_list("Basic Bee\nBomber Bee")


def _ocr(totals):
    """A header reader for synthetic pages: page i's (bees, types)."""
    seq = iter(totals)
    return lambda image: next(seq, (None, None))


def page(*greys, top=100):
    """A synthetic page of the list: one 120 px row per grey, a pitch apart,
    on a background no row test takes for a row."""
    import numpy as np
    img = np.zeros((922, 306, 3), np.uint8)
    img[:, :] = (40, 90, 160)                       # the world, beside nothing
    img[::7, :6] = (10, 10, 10)                     # ... and not uniform
    for i, g in enumerate(greys):
        y = top + i * bm.ROW_PITCH
        img[y:y + bm.ROW_H, :] = (g, g + 3, g + 6)
    return img


class RowModel:
    """Answers the row questions from the row's own grey (its left edge)."""

    def __init__(self, rows, again=None, total=None):
        self.rows = rows                 # grey -> (name, count or None)
        self.again = again or {}         # grey -> the second phrasing's answer
        self.total = total               # the header's answer to the question
        self.asked = []

    def __call__(self, image, question):
        if question == bm.TOTAL_QUESTION:
            return None if self.total is None else str(self.total)
        g = int(image[10, 2, 0])
        name, count = self.rows.get(g, (None, None))
        self.asked.append((g, question[:20]))
        if question == bm.ROW_NAME_QUESTION:
            return name
        if question == bm.ROW_COUNT_AGAIN and g in self.again:
            return self.again[g]
        if question in (bm.ROW_COUNT_QUESTION, bm.ROW_COUNT_AGAIN):
            return "none" if count is None else str(count)
        return None


def test_rows_read_on_their_own_crops_add_up_to_the_header():
    rows = {190: ("Basic Bee", None), 196: ("Bubble Bee", 15),
            202: ("Diamond Bee", 1), 208: ("Music Bee", 2)}
    model = RowModel(rows)
    # two overlapping pages: Bubble and Diamond on both
    pages = [(page(190, 196, 202), ""), (page(196, 202, 208), "")]
    result = beemenu.BeeRead()
    beemenu.count_bees(pages, model, lambda t: None, result,
                       ocr=_ocr([(18, 30), (18, 30)]))
    result.ok = True
    assert result.counts == {"bubble": 15, "diamond": 1, "music": 2}
    assert result.total == 18 and result.verified
    # Basic and Music were on one page each: asked a second way, once each
    again = [g for g, q in model.asked if q == bm.ROW_COUNT_AGAIN[:20]]
    assert sorted(again) == [190, 208]


def test_a_row_whose_two_readings_disagree_leaves_the_hive_unbelieved():
    rows = {196: ("Bubble Bee", 15), 202: ("Diamond Bee", 1)}
    model = RowModel(rows, again={202: "2"}, total=16)
    result = beemenu.BeeRead()
    beemenu.count_bees([(page(196, 202), "")], model, lambda t: None, result,
                       ocr=_ocr([(16, 30)]))
    result.ok = True
    # Diamond: 1 then 2 -- unsure; Bubble's 15 alone is not the header's 16
    assert result.counts == {} and result.rejected == {"bubble": 15}
    assert result.unsure["diamond"] == ["1", "2"]
    assert result.total == 16 and not result.verified


def test_the_headers_agreed_total_moves_the_bee_gates(tmp_path):
    path = tmp_path / "bees.json"
    result = beemenu.BeeRead(ok=True, counts={"basic": 2, "bubble": 4}, total=6)
    beemenu.write(path, result)
    assert beemenu.count_for_gates(path) == 6
    result = beemenu.BeeRead(ok=True, counts={}, rejected={"basic": 9}, total=34)
    beemenu.write(path, result)
    assert beemenu.count_for_gates(path) == 34        # the header stands alone
    result = beemenu.BeeRead(ok=True, counts={}, total=None)
    beemenu.write(path, result)
    assert beemenu.count_for_gates(path) is None
    assert beemenu.count_for_gates(tmp_path / "none.json") is None


FIXTURE = Path(hivemind.__file__).resolve().parents[2] / "tests" / "fixtures" / "beemenu" / "top-34-bees.png"


def test_the_first_page_the_bot_opened_reads_its_header_and_rows():
    """var/beemenu/20261001-222944/page-00.png: 34 bees, 33 types, and the
    Bomber, Brave and Bumble rows a pitch apart (Basic's is cut off from them
    by the "Rare Bees" heading)."""
    import cv2
    import shutil
    page = cv2.imread(str(FIXTURE))
    assert bm.bee_rows(page) == [336, 466, 596]
    if shutil.which("tesseract"):
        assert bm.ocr_header(page) == (34, 33)


def test_the_page_transcription_is_never_read_for_counts():
    """What the model wrote for the first page: a count for every row, where
    the page draws none. Counts come from the rows' own crops now; a page's
    words alone count nothing."""
    text = "Basic Bee: 3\nBomber Bee: 2\nBrave Bee: 1\nBumble Bee: 2\nCool Bee: 1"
    result = beemenu.BeeRead()
    beemenu.count_bees([(object(), text), (object(), text)], lambda i, q: None,
                       lambda t: None, result, ocr=_ocr([(34, 33), (34, 33)]))
    result.ok = True
    assert result.total == 34 and result.types_seen == 33
    assert result.counts == {} and result.rejected == {}
    assert "no row's count was read" in result.describe()


def test_the_world_is_not_the_bee_list():
    """A uniform left edge is common in the world; two rows a pitch apart are
    not (0 of 35,509 saved route frames)."""
    import numpy as np
    world = np.full((922, 306, 3), 200, np.uint8)        # one grey wall
    assert bm.bee_rows(world) == []


def _judge(bees, total, jelly=33):
    load = lambda name: yaml.safe_load((KNOW / name).read_text())
    slots = {int(k): int(v) for k, v in load("hive_slots.yaml")["honey_for_bees"].items()}
    return hivejudge.judge(bees, total, types=bm.types(), plan=load("blue_hive_plan.yaml"),
                           items=load("items.yaml"), verified=True, jelly_held=jelly,
                           slots=slots)


def test_the_hive_is_held_against_the_guides_stage_one():
    bees = {"basic": 2, "bubble": 3, "ninja": 1, "shy": 1, "rad": 2, "diamond": 1,
            "looker": 16}
    j = _judge(bees, 26)
    assert j.stage == 1
    assert j.comp == {"bubble": (13, 14, 3), "diamond": (5, 5, 1)}
    assert j.never_run == {"shy": 1}
    assert j.red == {"rad": 2}                      # shy is reported as never-run
    # jelly goes on what the guide does not want: Basic, never-run, red
    assert j.jelly_on == {"basic": 2, "rad": 2, "shy": 1}
    # a roll lands a Bubble (epic, 1 of 11) or a Diamond (legendary, 1 of 8).
    # Mythics are no longer targets (2026-10-14: 1 in 25,000 a roll); a mythic
    # a roll lands is still kept (run_farm stops rolling on one).
    assert abs(j.jelly_hit - (0.27 / 11 + 0.03 / 8)) < 1e-12
    assert j.next_slot == (27, 7_750_000)
    text = " ".join(j.lines(bm.types()))
    assert "26 bees" in text and "Bubble Bee 3/13-14" in text
    assert "short of Bubble Bee, Diamond Bee" in text
    assert "2 Basic Bees" in text and "33 Royal Jelly held" in text
    assert "7,750,000 honey" in text


def test_with_only_the_header_only_the_total_is_said():
    load = lambda name: yaml.safe_load((KNOW / name).read_text())
    slots = {int(k): int(v) for k, v in load("hive_slots.yaml")["honey_for_bees"].items()}
    j = hivejudge.judge({}, 34, types=bm.types(), plan=load("blue_hive_plan.yaml"),
                        items=load("items.yaml"), slots=slots, rows_known=False)
    text = " ".join(j.lines(bm.types()))
    assert "34 bees by the bee menu's own header" in text
    assert "Stage 1" in text and "209,117,953 honey" in text
    assert "Royal Jelly" not in text and "Basic" not in text


def test_a_hive_of_only_wanted_bees_gets_no_jelly():
    j = _judge({"bubble": 14, "diamond": 5, "looker": 7}, 26)
    assert not j.jelly_on and j.jelly_rolls is None
    text = " ".join(j.lines(bm.types()))
    assert "its comp is in" in text and "nothing for Royal Jelly" in text


def test_jelly_never_goes_on_an_event_bee_the_owner_did_not_name():
    # 2026-10-02: event bees Royal Jelly never rolls back are kept -- except
    # Crimson and Cobalt since the owner's YES of 2026-10-21
    # (blue_hive_plan.yaml jelly_event_ok); a red Festive is still kept
    j = _judge({"cobalt": 1, "crimson": 1, "festive": 1, "demon": 1, "riley": 1,
                "bubble": 14, "diamond": 5, "looker": 10}, 34)
    assert j.jelly_on == {"crimson": 1, "demon": 1, "riley": 1, "cobalt": 1}
    assert j.jelly_kept == {"festive": 1}
    text = " ".join(j.lines(bm.types()))
    assert "no jelly on 1 Festive Bee: event bees" in text


def test_held_pages_are_counted_later_off_the_pad():
    rows = {196: ("Bubble Bee", 15), 202: ("Diamond Bee", 1)}
    model = RowModel(rows, total=16)
    got = beemenu.BeeRead(ok=True, held=[(page(196, 202), "")], counted_yet=False)
    beemenu.count_held(got, model, lambda t: None)
    assert got.counted_yet and got.held == []
    # the header comes from tesseract on the page: a synthetic page has none
    assert got.counts == {} and got.rejected == {"bubble": 15, "diamond": 1}
    asked = len(model.asked)
    beemenu.count_held(got, model, lambda t: None)     # counted once only
    assert len(model.asked) == asked


def test_the_hive_read_at_23_41_is_jellied_for_diamonds_with_honey():
    """The verified read of 2026-10-01 23:41 (run-566): 34 bees. THE OWNER,
    2026-10-02: "diamond eggs arnt worth it it should buy roysal jellys with
    honey instead"."""
    bees = {"bubble": 17, "diamond": 4, "bucko": 2, "ninja": 2, "baby": 1, "bear": 1,
            "cobalt": 1, "crimson": 1, "demon": 1, "looker": 1, "music": 1, "rage": 1,
            "tabby": 1}
    load = lambda name: yaml.safe_load((KNOW / name).read_text())
    slots = {int(k): int(v) for k, v in load("hive_slots.yaml")["honey_for_bees"].items()}
    j = hivejudge.judge(bees, 34, types=bm.types(), plan=load("blue_hive_plan.yaml"),
                        items=load("items.yaml"), verified=True, jelly_held=2,
                        slots=slots, tickets=286)
    assert j.comp == {"bubble": (13, 14, 17), "diamond": (5, 5, 4)}
    assert j.never_run == {"cobalt": 1}
    assert j.red == {"crimson": 1, "demon": 1, "rage": 1}
    # the four the guide does not want; never a Bubble, a Diamond or the Tabby
    # -- Crimson and Cobalt too since the owner's YES of 2026-10-21
    assert j.jelly_on == {"crimson": 1, "demon": 1, "rage": 1, "cobalt": 1}
    assert j.jelly_kept == {}
    # a Diamond, then the guide's Mythics (the owner: "jellys also can get u
    # mythics so dont buy mythic egg")
    assert j.jelly_hits_for == ["diamond"]       # mythics: not targets since 2026-10-14
    assert abs(j.jelly_hit - 0.03 / 8) < 1e-12   # 0.375%
    assert round(j.jelly_rolls) == 267
    lo, hi = j.jelly_honey
    assert 200e6 < lo < hi and hi == 267 * 1_000_000           # rolls rounded up
    assert round(j.jelly_tickets) == round(6 * j.jelly_rolls)       # 6 a jelly
    # a Diamond Egg's 400 tickets for a Diamond (11.9%); mythics are not targets
    assert round(j.egg_tickets["Diamond Egg"]) == round(400 / (0.95 / 8))
    # jelly at the dispenser is ~1.85x cheaper in tickets than the best egg
    assert j.jelly_tickets * 1.8 < min(j.egg_tickets.values())
    text = " ".join(j.lines(bm.types()))
    assert "Royal Jelly goes on 1 Crimson Bee, 1 Demon Bee, 1 Rage Bee, 1 Cobalt Bee" in text
    assert "no jelly on" not in text
    assert "about 267 rolls a Diamond Bee" in text
    assert "Royal Jelly Shop" in text and "eggs are not bought" in text
    assert "tickets at the Royal Jelly Dispenser" in text
    assert "209,117,953 honey" in text


def test_the_bee_menus_give_up_is_its_own_code_not_the_inventorys(tmp_path):
    """The review of 2026-10-02: the give-up was keyed to the inventory's two
    modules, so a fix to the bee menu's row test never cleared it."""
    from hivemind.act import inventory
    tried = tmp_path / "tried.json"
    mine = tmp_path / "beemenu.py"
    mine.write_text("rows = 1\n")
    miss = inventory.InventoryRead(reason="no rows", no_marker=True)
    for _ in range(inventory.GIVE_UP_AFTER):
        inventory.note_try(tried, miss, clock=lambda: 0.0, code_paths=(mine,))
    gave_up = inventory.not_due(tried, 60.0, clock=lambda: 10_000.0, code_paths=(mine,))
    assert "rows were not seen" in gave_up
    mine.write_text("rows = 2\n")              # the row test is fixed
    assert inventory.not_due(tried, 60.0, clock=lambda: 10_000.0,
                             code_paths=(mine,)) == ""


def test_a_change_marked_after_the_pages_were_pictured_stands(tmp_path):
    # MEASURED 2026-10-06: pictured 03:07, slot 38's egg hatched 03:08, the rows
    # counted 03:11 -- and the write wiped the hatch's mark
    from hivemind.act import inventory
    path = tmp_path / "bees.json"
    result = beemenu.BeeRead(ok=True, counts={"basic": 2, "bubble": 35}, total=37)
    beemenu.write(path, result, clock=lambda: 100.0)
    inventory.mark_dirty(path, "the Basic Egg hatched", clock=lambda: 205.0)
    beemenu.write(path, result, clock=lambda: 300.0, taken_at=200.0)
    body = beemenu.load(path)
    assert body["read_at"] == 200.0 and body["dirty"].startswith("the Basic Egg hatched")
    # a mark from before the pictures is what the read answers
    beemenu.write(path, result, clock=lambda: 400.0, taken_at=210.0)
    assert "dirty" not in beemenu.load(path)


def test_the_header_reads_with_no_space_before_bees():
    # MEASURED 2026-10-10 21:55 (var/beemenu/20261010-215517/page-00.png):
    # tesseract gave "You Have 41Bees", and every read since 16:29 lost the total
    from hivemind.vision import beemenu as bm
    assert bm.header("You Have 41Bees\n%ou've Discovered 35 Types of Bees\n") == (41, 35)


def test_pages_an_earlier_process_did_not_count_are_read_back(tmp_path):
    import cv2
    import numpy as np
    from hivemind.act import beemenu as menu
    for i in range(2):
        cv2.imwrite(str(tmp_path / f"page-{i:02d}.png"), np.zeros((4, 4, 3), np.uint8))
        (tmp_path / f"page-{i:02d}.txt").write_text(f"page {i}", encoding="utf-8")
    tried = {"at": 100.0, "ok": False, "reason": menu.NOT_COUNTED, "kept": str(tmp_path)}
    left = menu.left_uncounted(tried, {"read_at": 50.0}, now=200.0)
    assert left is not None and left.pages == 2 and not left.counted_yet
    assert left.held[1][1] == "page 1" and left.held[0][0].shape == (4, 4, 3)
    assert menu.left_uncounted(tried, {"read_at": 150.0}) is None     # read since
    assert menu.left_uncounted(tried, {"read_at": 50.0}, now=100.0 + 3601) is None  # stale
    assert menu.left_uncounted({**tried, "ok": True}, {}) is None
    assert menu.left_uncounted({**tried, "reason": "no marker"}, {}) is None
    assert menu.left_uncounted({**tried, "kept": ""}, {}) is None

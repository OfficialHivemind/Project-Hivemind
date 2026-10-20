"""The empty hive cell, found on the real hive (vision/hivecell)."""
from __future__ import annotations

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
FIX = Path(__file__).resolve().parents[1] / "fixtures" / "hive"


def test_the_one_empty_cell_is_found_and_no_shadow():
    from hivemind.vision import hivecell
    got = hivecell.empty_cells(cv2.imread(str(FIX / "egg-before.jpg")))
    assert len(got) == 1
    x, y = got[0]
    assert abs(x - 1213) <= 6 and abs(y - 98) <= 6


def test_a_hive_of_bees_has_no_empty_cell():
    # one PageDown from the pad: every cell in view holds a bee (06:21)
    from hivemind.vision import hivecell
    assert hivecell.empty_cells(cv2.imread(str(FIX / "full-hive.jpg"))) == []


def test_the_held_egg_lights_the_empty_cell_and_not_a_bee():
    from hivemind.vision import hivecell
    held = cv2.imread(str(FIX / "egg-held.jpg"))
    before = cv2.imread(str(FIX / "egg-before.jpg"))
    assert hivecell.lit(held, 1213, 98)
    assert not hivecell.lit(before, 1213, 98)            # no egg held, no light
    assert not hivecell.lit(held, 1200, 180)             # a bee's cell: a face, not flat


def test_the_pointer_on_the_lit_cell_does_not_hide_its_light():
    # MEASURED 07:46: the first hatch carried the egg back from a lit cell --
    # the pointer's arrow sat in the patch that was read
    from hivemind.vision import hivecell
    held = cv2.imread(str(FIX / "hatch-held-pointer.jpg"))
    assert hivecell.lit(held, 1222, 94)


def test_the_cell_the_game_takes_glows_white_under_the_pointer():
    from hivemind.vision import hivecell
    near = cv2.imread(str(FIX / "egg-held-near.jpg"))          # a bee's cell, 06:54
    assert hivecell.hovered(near, 1130, 260)
    assert not hivecell.hovered(near, 1340, 140)               # a lit cell, not under it
    taken = cv2.imread(str(FIX / "hatch-held-hovered.jpg"))    # the empty cell, 08:46
    assert hivecell.hovered(taken, 1287, 63)
    far = cv2.imread(str(FIX / "hatch-held-pointer.jpg"))      # 14 studs back, 07:46
    assert not hivecell.hovered(far, 1222, 94) and hivecell.lit(far, 1222, 94)


def test_the_hatch_question_reads_as_the_run_accepts_it():
    # MEASURED 09:15: "Hatch Festive Bee Egg?" over Yes and No
    import shutil
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is not installed")
    from hivemind.act import inventory, shoplook
    frame = cv2.imread(str(FIX / "hatch-asked.jpg"))
    assert inventory.dialog_open(frame)
    assert inventory.dialog_question(frame, shoplook._ocr_line) == "hatch festive bee egg"


def test_the_new_type_cards_close_is_found_and_nothing_else():
    from hivemind.vision import hivecell
    at = hivecell.new_type_card_close(cv2.imread(str(FIX / "new-type-card.jpg")))
    assert at is not None and abs(at[0] - 827) <= 4 and abs(at[1] - 292) <= 4
    # a red bee in a yellow cell: yellow beside it, but no card under it
    for name in ("egg-before.jpg", "full-hive.jpg", "hatch-asked.jpg", "red-bee-in-cell.jpg"):
        assert hivecell.new_type_card_close(cv2.imread(str(FIX / name))) is None, name


def test_the_demons_cell_is_the_one_aqua_cell_with_a_red_face():
    # MEASURED 2026-10-03 06:21: the hive's bottom row from above; the Demon's
    # aqua strip at (1117, 249) 54 x 24, and no other aqua holds red
    from hivemind.vision import hivecell
    found = hivecell.red_legendary_cells(cv2.imread(str(FIX / "hive-down-demon.jpg")))
    assert len(found) == 1 and abs(found[0][0] - 1144) <= 4 and abs(found[0][1] - 261) <= 4
    # the rows above it from the pad (Diamonds, Ninjas, Baby, Music), a red bee
    # in an Epic's yellow cell, the hatch card: no red face on aqua
    for name in ("full-hive.jpg", "red-bee-in-cell.jpg", "new-type-card.jpg"):
        assert hivecell.red_legendary_cells(cv2.imread(str(FIX / name))) == [], name


def test_zoomed_out_the_small_empty_cell_is_found_in_our_hive_only():
    # MEASURED 2026-10-05 22:37: six zoom taps out, slot 37's cell is a 29 x 33
    # blob at the hive's top; the hive beside ours has an empty cell at x 1345
    from hivemind.vision import hivecell
    f = cv2.imread(str(FIX / "hatch-slot37-z6.jpg"))
    assert hivecell.empty_cells(f) == []                        # too small for the near tests
    (x, y), = hivecell.empty_cells(f, small=True)
    assert abs(x - 969) <= 12 and abs(y - 260) <= 6
    lo, hi = hivecell.hive_band(f)
    assert lo <= 969 <= hi and hi < 1345


def test_a_brighter_lit_small_empty_cell_is_found_too():
    # MEASURED 2026-10-06 01:52: slot 38's cell, at the hive's top between the
    # 5 and an 8, read V 170-181 -- over the old 170 limit, and the egg was
    # never dragged
    from hivemind.vision import hivecell
    f = cv2.imread(str(FIX / "hatch-slot38-z6.jpg"))
    (x, y), = hivecell.empty_cells(f, small=True)
    assert abs(x - 975) <= 12 and abs(y - 282) <= 8


def test_zoomed_in_the_gold_beside_the_hive_is_never_the_one_cell():
    # MEASURED 2026-10-06 02:36: slot 38's cell (the hive's top) out of view, and
    # with the zoomed-out brightness limit the near look found exactly one
    # "cell" in the gold right of the hive -- and the egg was dragged there
    from hivemind.vision import hivecell
    f = cv2.imread(str(FIX / "hatch-slot38-z0.jpg"))
    assert len(hivecell.empty_cells(f)) != 1        # so the hatch zooms on

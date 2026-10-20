"""Route reliability (2026-10-14, branch reliab): the route board, a side panel
left open before a walk out, a sprinkler the game took as proof of a field, and
the Stump rim check before the Dapper climb."""
import json

import numpy as np

from hivemind.act import badges, quests
from hivemind.brain import skills
from hivemind.brain.fieldnotes import pollen_for_verdict, trip_arrived
from hivemind.vision import ground, questlist

H, W = 1080, 1920


def _world(seed=1):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(H, W, 3), dtype=np.uint8)


def _with_panel(bgr, seed=1):
    frame = _world(seed)
    frame[:, 306:308] = bgr                     # the border: one flat colour
    return frame


# ---- the board -----------------------------------------------------------
def _book(verdicts, route="natro_out_pine_tree"):
    book = skills.SkillBook(None)
    for v in verdicts:
        book.skill(route, "out", "pine_tree").add(v, 40.0, 1.0)
    return book


def test_window_rolls_into_before():
    book = _book(["elsewhere"] * 10 + ["landed"] * 10)
    s = book.get("natro_out_pine_tree")
    assert s.recent == ["landed"] * 10 and s.before == ["elsewhere"] * 10
    again = skills.Skill.from_dict(s.route, s.as_dict())
    assert again.before == s.before


def test_board_trend_flag_and_order():
    book = _book(["landed"] * 10 + ["landed"] * 7 + ["elsewhere"] * 3)
    book.skill("natro_home_pine_tree", "home", "pine_tree").add("landed", 40.0, 1.0)
    rows = book.board()
    worst = rows[0]
    assert worst["route"] == "natro_out_pine_tree"
    assert worst["rate"] == 0.7 and worst["before"] == 1.0 and worst["trend"] == -0.3
    assert worst["flagged"]
    # one verdict is too few to flag, whatever it is
    assert not rows[1]["flagged"] and rows[1]["trend"] is None


def test_save_writes_the_board(tmp_path):
    book = _book(["landed", "elsewhere"] * 3)
    book.path = tmp_path / "skill_stats.json"
    book.save()
    body = json.loads((tmp_path / skills.BOARD_FILE).read_text())
    assert body["routes"][0]["route"] == "natro_out_pine_tree"
    assert body["routes"][0]["verdicts"] == 6 and body["routes"][0]["flagged"]


def test_gui_board_rows(tmp_path):
    from hivemind.gui.panels.fields import board_rows
    book = _book(["landed"] * 4 + ["elsewhere"] * 2,
                 route="natro_out_pine_tree_via_red_cannon")
    book.path = tmp_path / "skill_stats.json"
    book.save()
    cells = board_rows(tmp_path / skills.BOARD_FILE)
    assert cells == [["out_pine_tree (flight)", "4/6", "67%", "—", "flagged"]]


# ---- a side panel left open ---------------------------------------------
def test_side_panel_by_its_border():
    assert questlist.side_panel(_with_panel((31, 107, 154))) == "badges"
    assert questlist.side_panel(_with_panel(questlist.BORDER_BGR)) == "quests"
    assert questlist.side_panel(_with_panel((200, 30, 200))) == "panel"
    assert questlist.side_panel(_world()) is None
    # a dark corridor is flat at the border AND beside it: no panel
    assert questlist.side_panel(np.full((H, W, 3), 20, np.uint8)) is None


class FakeVin:
    def __init__(self):
        self.clicks = []

    def click(self, x, y):
        self.clicks.append((x, y))

    def move_mouse(self, x, y):
        pass


def test_close_side_panel_clicks_its_own_button_once():
    vin = FakeVin()
    shown = [_with_panel((31, 107, 154)), _world()]
    said = quests.close_side_panel(vin, lambda: shown.pop(0), sleep=lambda s: None)
    assert vin.clicks == [(27 + 56 * 3, 128)]          # the rosette, never the shop
    assert "closed" in said


def test_close_side_panel_never_clicks_twice_or_on_a_guess():
    vin = FakeVin()
    still = _with_panel((31, 107, 154))
    said = quests.close_side_panel(vin, lambda: still, sleep=lambda s: None)
    assert len(vin.clicks) == 1 and "did not close" in said
    vin = FakeVin()
    said = quests.close_side_panel(vin, lambda: _with_panel((200, 30, 200)),
                                   sleep=lambda s: None)
    assert vin.clicks == [] and "not clicked" in said
    assert quests.close_side_panel(FakeVin(), _world, sleep=lambda s: None) == ""


def test_badge_close_has_its_own_sign():
    gone = badges._list_gone(_with_panel((31, 107, 154)))
    assert gone(_world()) is True and gone(_with_panel((31, 107, 154))) is False
    assert badges._list_gone(_world()) is None


# ---- the sprinkler the game took ----------------------------------------
def test_a_taken_sprinkler_is_not_a_trip_that_reached_no_field():
    # MEASURED: attempt 988 06:58, the sprinkler placed, then a death with
    # 1,673 pollen, one pass and the feed silent -- booked "elsewhere" before
    assert trip_arrived(0, None, 1) is False
    assert trip_arrived(pollen_for_verdict(0, sprinkler_took=True), None, 1) is None
    assert pollen_for_verdict(0, sprinkler_took=False) == 0
    assert pollen_for_verdict(5000, sprinkler_took=True) == 5000
    runs = [{"route": "natro_out_pine_tree_via_red_cannon", "seconds": 18.0}]
    fields = {"pine_tree"}
    got = skills.settle_trip(runs, aim="pine_tree", credited=None, fields=fields,
                             reached_no_field=trip_arrived(None, None, 1) is False)
    assert got[0]["outcome"] == "unknown"


# ---- the Stump rim before the Dapper climb -------------------------------
def test_stump_rim_grey():
    frame = np.zeros((H, W, 3), np.uint8)
    frame[:, :] = (40, 160, 40)                 # flowers' green
    assert ground.stump_rim_grey(frame) < ground.STUMP_RIM_MIN_GREY
    frame[int(0.08 * H):int(0.35 * H), :] = (128, 128, 128)    # the hill ahead
    assert ground.stump_rim_grey(frame) >= ground.STUMP_RIM_MIN_GREY
    frame[int(0.08 * H):int(0.35 * H), :] = (150, 60, 20)      # a blue wall
    assert ground.stump_rim_grey(frame) == 0.0

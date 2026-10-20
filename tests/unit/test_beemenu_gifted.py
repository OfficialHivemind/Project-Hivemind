"""The bee menu's gifted star, and the walkspeed it sets (act/beemenu movespeed_bonus)."""
import json
from pathlib import Path

import cv2

from hivemind.act import beemenu
from hivemind.vision import beemenu as bm

PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "beemenu" / "stars-page.png"


def test_the_dark_star_is_read_and_the_faded_one_is_not():
    # the page: Cool (faded star), Hasty, Looker (dark), Rad (none), Rascal (dark)
    rows = [bm.gifted_star(row) for _top, row in bm.row_crops(cv2.imread(str(PAGE)))]
    assert rows == [False, True, True, False, True]


def _bonus(tmp_path, body):
    p = tmp_path / "bees.json"
    p.write_text(json.dumps(body))
    return beemenu.movespeed_bonus(p)[0]


def test_a_gifted_hasty_is_fifteen_percent(tmp_path):
    assert _bonus(tmp_path, {"gifted": ["bubble", "hasty"], "bees": {"hasty": 1}}) == 1.15


def test_rolled_away_it_is_gone(tmp_path):
    assert _bonus(tmp_path, {"gifted": ["bubble"], "bees": {"hasty": 1}}) == 1.0
    assert _bonus(tmp_path, {"bees": {"bubble": 14}}) == 1.0       # no star read, no Hasty


def test_without_stars_a_counted_hasty_or_no_read_keeps_it(tmp_path):
    assert _bonus(tmp_path, {"bees": {"hasty": 1}}) == 1.15
    assert _bonus(tmp_path, {}) == 1.15
    assert beemenu.movespeed_bonus(tmp_path / "missing.json")[0] == 1.15

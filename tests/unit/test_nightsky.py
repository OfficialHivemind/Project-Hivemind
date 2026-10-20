"""Night by the sky (vision/night.sky, look_up; ROADMAP NIGHT-SKY).

Synthetic frames for the rule, and the owner's saved frames (skipped where
var/ is not on disk) for the measured cases: docs/pending/nightsky.md."""
from __future__ import annotations

import contextlib
import pathlib

import cv2
import numpy as np
import pytest

from hivemind.vision import night

ROOT = pathlib.Path(__import__("hivemind").__file__).resolve().parents[2]
VARS = (ROOT / "var", pathlib.Path.home() / "Hivemind" / "var")   # a checkout, the install


def _frame(sky=None, lower=120, floor_night=0.0):
    """1080p: the sky patch painted `sky` (BGR), the lower half grey `lower`
    with a share of night grass."""
    f = np.full((1080, 1920, 3), 120, np.uint8)
    f[540:] = lower
    if floor_night:
        low = f[540:].reshape(-1, 3)
        low[:int(floor_night * len(low))] = night.NIGHT_RGB[::-1]
    if sky is not None:
        f[100:260, 500:1800] = sky
    return f


def test_sky_reads_day_and_night_and_nothing():
    assert night.sky(_frame(night.DAY_SKY_BGR)) == "day"
    assert night.sky(_frame((1, 1, 1))) == "night"
    assert night.sky(_frame((60, 100, 150))) is None     # the boundary wall's blue
    assert night.sky(_frame()) is None
    assert night.sky(None) is None


def test_a_dimmed_menu_is_not_night_sky():
    # black patch, but the whole frame is dark: a menu's dimming, a black frame
    assert night.sky(_frame((1, 1, 1), lower=15)) is None


def test_sky_overrules_the_floor_and_the_floor_stays_without_sky():
    assert not night.is_night(_frame(night.DAY_SKY_BGR, floor_night=0.08))
    assert night.is_night(_frame((1, 1, 1)))
    assert night.is_night(_frame(floor_night=0.08))      # the pad: no sky, the floor decides
    assert not night.is_night(_frame())


class _Camera:
    def __init__(self):
        self.poses = []

    @contextlib.contextmanager
    def looking(self, pose):
        self.poses.append(pose)
        yield self
        self.poses.append("back")


def test_look_up_is_look_only_by_default():
    said, cam = [], _Camera()
    assert night.NIGHT_SKY_LIVE is False
    assert night.look_up(cam, lambda: _frame((1, 1, 1)), dict, said.append) is None
    assert cam.poses == [] and said and said[0].startswith("night sky would:")


def test_look_up_live_turns_reads_and_puts_back(monkeypatch):
    monkeypatch.setattr(night, "NIGHT_SKY_LIVE", True)
    cam = _Camera()
    assert night.look_up(cam, lambda: _frame((1, 1, 1)), dict, print) == "night"
    assert cam.poses == [night.SKY_LOOK, "back"]


def test_run_farm_night_jobs_go_through_night_now():
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert src.count("night_now(") == 5                  # the def and the four jobs
    # inside night_now, plus vic hop's per-frame spike gate (act/vichunt), which
    # judges the kept frame itself and must never turn the camera to look up
    assert src.count("night_mod.is_night(") == 2


# MEASURED frames (docs/pending/nightsky.md): (frame, sky, is_night)
SAVED = (
    # one cannon flight across the switch: day at 11:30:26, night 4 s later
    ("routes/attempt-1082/113026-natro_out_pine_tree_via_red_cannon-08-pause-.jpg", "day", False),
    ("routes/attempt-1082/113034-natro_out_pine_tree_via_red_cannon-20-pause-.jpg", "night", True),
    # the floor's false night on the pad (3.4% night green): no sky there, so
    # it still says night; the same trip's flight 9 s later reads the day sky
    ("routes/attempt-539/080226-natro_out_spider_via_red_cannon-00-start.jpg", None, True),
    ("routes/attempt-539/080235-natro_out_spider_via_red_cannon-08-jump-.jpg", "day", False),
    # the hunt's pad confirm frame: no sky, the floor's night stands
    ("vicious/20261013-075022/0000.0-confirm.jpg", None, True),
    # night behind the see-through boundary wall, and the same view by day
    ("shoplook/20261022-112741-spirit_bear_survey_ramp_pad:talk:248977-leg4-mark12-w.jpg", "night", True),
    ("shoplook/20261022-071031-spirit_bear_survey_ramp_pad:talk:248975-leg4-mark12-w.jpg", None, False),
    # menus dimming the screen: not sky
    ("memorymatch/20261013-024537/0062.7-turn05.jpg", None, False),
    ("places/sticker_stack-r0c2-asked-no-115815.jpg", None, False),
    # a near wall in shade, black on the right patch only (the Spirit Bear room)
    ("bears/spirit_bear-143916.jpg", None, False),
)


@pytest.mark.parametrize("rel,sky,is_night", SAVED)
def test_saved_frames(rel, sky, is_night):
    path = next((v / rel for v in VARS if (v / rel).exists()), None)
    if path is None:
        pytest.skip(f"{rel} is only on the owner's machine")
    frame = cv2.imread(str(path))
    assert night.sky(frame) == sky
    assert night.is_night(frame) is is_night

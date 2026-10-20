"""The Coconut Crab seen (act/crab.bar) and its field reached (act/crab.reached),
on the 18 real tries of 2026-10-07..12 kept in var/crab/<stamp>/: its bar at
the top edge, where nameplate.find never looks, and the pollen counter that
says whether the character stood in its field at all -- the 14 tries logged
"absent" never did."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from hivemind.act import crab
from hivemind.brain.farm import HudReader
from hivemind.vision import nameplate
from hivemind.vision import screenstate as ss

TRIES = Path.home() / "Hivemind" / "var" / "crab"
TEMPLATES = Path(__file__).resolve().parents[2] / "data" / "templates" / "digits"
STAMPS = ("20261007-102255", "20261007-163158", "20261007-184427", "20261008-044104",
          "20261008-162153", "20261009-064711", "20261009-112643", "20261009-134945",
          "20261011-003311", "20261011-023919", "20261011-050243", "20261011-084015",
          "20261011-105215", "20261011-215345", "20261012-035926", "20261012-085216",
          "20261012-115104", "20261012-180132")
# BY EYE: the four that landed in the field, the crab beside the character and
# the character dead 4-8 s later; every other try's frames show no field.
IN_FIELD = {"20261007-102255", "20261007-184427", "20261011-215345", "20261012-115104"}
# BY EYE: "HP: 250,000" under "Time: 1:59:5x", whole on screen at y 14; in
# that try's other looks it is behind the Roblox buttons or the Honey pill.
BAR_WHOLE = {("20261012-115104", s) for s in
             ("0030.1-look03", "0030.4-look04", "0030.8-look05", "0031.1-look06")}


def _frames(stamp):
    folder = TRIES / stamp
    if not folder.is_dir():
        pytest.skip(f"{folder} is not on this machine")
    return sorted(folder.glob("*.jpg"))


def test_its_bar_is_seen_at_the_top_edge_and_on_no_other_frame():
    for stamp in STAMPS:
        for path in _frames(stamp):
            frame = cv2.imread(str(path))
            seen = crab.bar(frame)
            assert bool(seen) == ((stamp, path.stem) in BAR_WHOLE), f"{stamp}/{path.name}"
            if seen:
                # why the fight never began: nameplate.find skips these rows
                assert seen[0].y < nameplate.WORLD_TOP and not nameplate.find(frame)


def test_the_pollen_counter_says_who_stood_in_the_field():
    templates = ss.load_templates(TEMPLATES)
    for stamp in STAMPS:
        reads = []
        for path in _frames(stamp):
            frame = cv2.imread(str(path))
            reads.append(HudReader(lambda: frame, templates).pollen().value)
        # the bags left the hive empty (each of the 14 reads 0 on all 21 frames)
        assert crab.reached(0, reads) == (stamp in IN_FIELD), f"{stamp}: {reads}"


def test_a_bag_that_left_with_pollen_must_grow():
    assert not crab.reached(None, [0, None, 0])
    assert crab.reached(None, [None, 176])
    # 20261011-215345's walk carried 85 from the hive (var/routes/attempt-889)
    assert not crab.reached(85, [85, 85, None])
    assert crab.reached(85, [85, 913])


def test_the_hud_is_blanked_and_a_bloom_is_not_the_crab():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[14:30, 215:327] = (68, 231, 31)            # BGR of nameplate's green, its 112x16
    frame[18:26, 240:296] = (255, 255, 255)          # its white "HP:" text
    assert [(p.x, p.y, p.w, p.h) for p in crab.bar(frame)] == [(215, 14, 112, 16)]
    assert nameplate.find(frame) == []               # above WORLD_TOP
    x, y, _w, _h = ss.HONEY_REGION                   # the same bar under the Honey pill
    pill = np.zeros_like(frame)
    pill[y + 4:y + 20, x + 20:x + 132] = frame[14:30, 215:327]
    assert crab.bar(pill) == []
    frame[20:26, 300:306] = (180, 105, 255)          # a Bloom's flower icon, pink
    assert crab.bar(frame) == []

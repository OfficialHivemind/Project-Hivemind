"""The Vicious Bee's spike by sight (vision/vicspike) and the look-only
lookout and its per-server memory (act/vicious)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

import hivemind
from hivemind.act import vicious
from hivemind.vision import vicspike

ROOT = Path(hivemind.__file__).resolve().parents[2]
VAR = Path.home() / "Hivemind" / "var"
GRASS = (21, 76, 31)            # BGR, the owner's frame's night grass
SPIKE = (177, 170, 137)         # BGR, the owner's spike's median


def _field(h=400, w=400):
    return np.full((h, w, 3), GRASS, np.uint8)


def _cone(img, base=(200, 330), length=110, base_w=20, tip_w=4, colour=SPIKE):
    bx, by = base
    pts = np.array([[bx - base_w // 2, by], [bx + base_w // 2, by],
                    [bx + tip_w // 2, by - length], [bx - tip_w // 2, by - length]], np.int32)
    cv2.fillPoly(img, [pts], colour)
    return img


def test_a_pale_cone_standing_in_a_field_is_a_spike():
    got = vicspike.find(_cone(_field()))
    assert len(got) == 1
    s = got[0]
    assert abs(s.x - 200) <= 4 and abs(s.y - 330) <= 4        # its base: where to walk
    assert 100 <= s.length <= 115 and s.lean < 5 and s.taper < 0.7


def test_what_is_not_a_spike():
    assert vicspike.find(None) == [] and vicspike.find(np.zeros((0, 0, 3), np.uint8)) == []
    disc = _field()
    cv2.circle(disc, (200, 250), 30, SPIKE, -1)                 # a bubble, a flower
    assert vicspike.find(disc) == []
    bar = _field()
    cv2.rectangle(bar, (195, 200), (205, 330), SPIKE, -1)       # no taper: a post, a "1"
    assert vicspike.find(bar) == []
    assert vicspike.find(_cone(_field(), base_w=4, tip_w=20)) == []   # point down
    sky = _cone(np.zeros((400, 400, 3), np.uint8))              # not standing in a field
    assert vicspike.find(sky) == []
    flat = _field()
    cv2.fillPoly(flat, [np.array([[90, 250], [90, 230], [320, 238]], np.int32)], SPIKE)
    assert vicspike.find(flat) == []                            # lying down
    blue = _cone(_field(), colour=(200, 120, 40))               # saturated blue: a bee, a stripe
    assert vicspike.find(blue) == []


def test_the_crop_is_kept(tmp_path):
    frame = _cone(_field())
    s = vicspike.find(frame)[0]
    path = vicspike.keep_crop(frame, s, tmp_path, "0001.0-check")
    assert path is not None and path.exists() and cv2.imread(str(path)).size > 0


def test_real_spikes_in_our_frames():
    """MEASURED 2026-10-26: the owner's screenshot and two kept hunt frames
    that were recorded 'absent' with a spike in view."""
    shots = [(VAR / "reference/vicious_spike_owner_2026-10-21.png", None),
             (VAR / "vicious/20261015-070531/0029.2-check.jpg", (282, 337)),
             (VAR / "vicious/20261023-204232/0030.5-check.jpg", (842, 352))]
    if not all(p.exists() for p, _ in shots):
        pytest.skip("owner's frames only")
    for path, at in shots:
        got = vicspike.find(cv2.imread(str(path)))
        assert got, path
        if at:
            assert min(np.hypot(s.x - at[0], s.y - at[1]) for s in got) <= 45


def test_the_lookout_is_look_only_and_gives_the_heading_back():
    assert vicious.VIC_LOOK_LIVE is False
    steps = vicious.lookout_steps()
    assert sum(s["taps"] for s in steps if s["op"] == "turn") == vicious.LOOK_TURNS == 8
    assert sum(1 for s in steps if s["op"] == "look") == 8
    keys = [(s["key"], s["n"]) for s in steps if s["op"] == "key"]
    assert keys == [("pageup", vicious.LOOK_TILT), ("o", vicious.LOOK_ZOOM_OUT),
                    ("i", vicious.LOOK_ZOOM_OUT), ("pagedown", vicious.LOOK_TILT)]
    line = vicious.lookout_line("rose_field", steps, ["clover"])
    assert line.startswith("vicious lookout would:") and "rose field" in line and "clover" in line


def test_fields_looked_at_are_remembered_per_server_for_a_night():
    st = vicious.mark_looked({"tries": []}, "abc", "clover", 1000.0)
    st = vicious.mark_looked(st, "abc", "spider", 1100.0)
    assert vicious.looked(st, "abc", 1200.0) == ["clover", "spider"]
    assert vicious.looked(st, "other", 1200.0) == []
    late = 1000.0 + vicious.LOOKED_FOR_S + 1
    assert vicious.looked(st, "abc", late) == ["spider"]
    st = vicious.mark_looked(st, "", "cactus", late + vicious.LOOKED_FOR_S)
    assert st["looked"] == {"home": {"cactus": late + vicious.LOOKED_FOR_S}}   # stale dropped
    assert st["tries"] == []


def test_the_hunt_looks_and_says_what_it_would_do():
    text = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    hunt = text[text.index("def hunt_the_vicious"):text.index("def play_ant_challenge")]
    assert "vicspike_mod.find(frame)" in hunt and "vicious would: walk to the spike" in hunt
    assert "vicious_mod.lookout_line(" in hunt and "vicious_mod.mark_looked(" in hunt

"""Boxes measured at 1920x1080 on another frame size (vision/screen, ROADMAP RL3
stage 1). At 1920x1080 nothing may move. At 1280x720 the fixtures are a real
in-world frame of the Sober client (var/incidents/20261021-024944-hud-missing,
t+30s: its top 70 rows, and the hotbar at x 360-920, y 600-700), the one whose
HUD the old w/1920 stretch could not find."""
from __future__ import annotations

import pathlib

import cv2
import numpy as np
import pytest

import hivemind
from hivemind.act import hotbar as H
from hivemind.act import join
from hivemind.vision import hotbar_items as hi
from hivemind.vision import screen
from hivemind.vision import screenstate as ss
from hivemind.vision import templates as T

FIX = pathlib.Path(hivemind.__file__).resolve().parents[2] / "tests/fixtures/screens"
ANCHORS = (screen.TOP_LEFT, screen.TOP, screen.BOTTOM)


def blank(w, h):
    return np.zeros((h, w, 3), np.uint8)


def test_nothing_moves_at_1920x1080():
    f = blank(1920, 1080)
    for anchor in ANCHORS:
        for x, y in ((0, 0), (660, 22), (1919, 1079), (713, 985), (961, 541)):
            assert screen.point(f, x, y, anchor) == (x, y)
        assert screen.region(f, ss.POLLEN_REGION, anchor) == ss.POLLEN_REGION
        assert screen.box(f, H.SLOT1_INNER, anchor) == H.SLOT1_INNER
    assert screen.to_base(f, 675, 30) == (675, 30)
    assert ss.hud_region(f, ss.HONEY_REGION) == ss.HONEY_REGION


def test_the_measured_moves_at_1280x720():
    f = blank(1280, 720)
    assert ss.hud_region(f, ss.HONEY_REGION) == (340, 22, 294, 36)
    assert screen.point(f, 16, 14) == (16, 14)                    # Roblox button
    assert screen.box(f, (700, 980, 766, 1046), screen.BOTTOM) == (380, 620, 446, 686)
    # the pointer's space still stretches (act/join, 2026-10-21 01:36)
    assert join.to_input(f, 450, 20) == (675, 30)


def test_the_hud_is_found_on_a_1280x720_frame():
    f = blank(1280, 720)
    top = cv2.imread(str(FIX / "hud_1280x720_top.png"))
    f[:top.shape[0]] = top
    assert ss.hud_present(f)
    assert ss.classify(f) is ss.Screen.IN_GAME
    assert ss.pollen_bar_fill(f) is not None


def test_the_hotbar_is_read_on_a_1280x720_frame():
    f = blank(1280, 720)
    f[600:700, 360:920] = cv2.imread(str(FIX / "hotbar_1280x720.png"))
    slots = hi.read(f)
    assert slots[0].item == "sprinkler", slots[0]
    assert H.slot_brightness(f, 1) > 100
    assert H.strip(f).shape[:2] == (97, 710)


def test_a_transparent_template_matches_on_its_own_pixels(tmp_path):
    """vision/templates: alpha is the mask; an opaque PNG loads as plain BGR."""
    rng = np.random.default_rng(1)
    piece = np.zeros((30, 30, 4), np.uint8)
    cv2.circle(piece, (15, 15), 12, (255, 255, 255, 255), -1)
    cv2.rectangle(piece, (10, 10), (19, 19), (20, 20, 20, 255), -1)
    cv2.imwrite(str(tmp_path / "round.png"), piece)
    opaque = piece.copy()
    opaque[..., 3] = 255
    cv2.imwrite(str(tmp_path / "opaque.png"), opaque)
    tpl = T.load(tmp_path / "round.png")
    assert tpl.shape == (30, 30, 4)
    assert T.load(tmp_path / "opaque.png").shape == (30, 30, 3)
    frame = rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)   # the world, noise
    inside = piece[..., 3] > 0
    frame[50:80, 70:100][inside] = piece[..., :3][inside]
    hit = T.find(frame, tpl, threshold=0.95)
    assert hit is not None and (hit.x, hit.y) == (70, 50) and hit.score > 0.99
    assert T.find(frame, tpl[..., :3], threshold=0.95) is None   # the corners voted


def _shifted(frame, dx, dy):
    out = np.zeros_like(frame)
    out[dy:, dx:] = frame[:frame.shape[0] - dy, :frame.shape[1] - dx]
    return out


def test_the_hud_anchors_are_measured(monkeypatch):
    f = cv2.imread(str(FIX / "in_game.png"))
    if f is None:
        pytest.skip("in_game.png is not in this checkout (private frames)")
    monkeypatch.setattr(screen, "_shift", {})
    assert list(screen.offsets(f).values()) == [(0, 0)] * 3
    moved = _shifted(f, 12, 9)
    assert list(screen.measure(moved).values()) == [(12, 9)] * 3
    assert screen.point(moved, 660, 22, screen.TOP) == (660, 22)    # look-only
    monkeypatch.setattr(screen, "ANCHORS_LIVE", True)
    screen.measure(moved)
    assert screen.point(moved, 660, 22, screen.TOP) == (672, 31)
    assert ss.hud_region(moved, ss.HONEY_REGION)[:2] == (672, 31)
    screen.measure(f)                                                # back home
    assert screen.point(f, 660, 22, screen.TOP) == (660, 22)
    assert list(screen.offsets(blank(1920, 1080)).values()) == [None] * 3


def test_the_hud_anchors_at_1280x720():
    f = blank(1280, 720)
    f[:70] = cv2.imread(str(FIX / "hud_1280x720_top.png"))[:70]
    f[600:700, 360:920] = cv2.imread(str(FIX / "hotbar_1280x720.png"))
    assert list(screen.offsets(f).values()) == [(0, 0)] * 3

"""Mob health bars: it must never cry wolf on a real frame."""
from __future__ import annotations

import glob
import pathlib

import cv2
import numpy as np
import pytest

from hivemind.vision import nameplate

ROOT = pathlib.Path(__file__).resolve().parents[2]


def real_frames():
    found = sorted(glob.glob(str(ROOT / "tests/fixtures/screens/**/*.png"),
                             recursive=True))
    return [f for f in found if "app_home" not in f]


@pytest.mark.parametrize("path", real_frames())
def test_no_real_frame_contains_a_mob(path):
    """THE measurement this detector is trusted on.

    None of these frames has a mob in it -- they are the hive, the shop, the
    cannon, both fields, the app UI and the menus. Anything found here is a
    false positive, and a false positive makes the bot cut short a walk in an
    empty field. Measured across all of them: zero.
    """
    img = cv2.imread(path)
    if img is None:
        pytest.skip(f"{path} is not readable")
    hits = nameplate.find(img, top=170)
    assert hits == [], f"{pathlib.Path(path).name}: {[h.describe() for h in hits]}"


def _bar(frame, x=300, y=200, w=80, h=14, text=True, pink=False, tail=False):
    """A health bar the way THIS client draws one: UI green with white text in
    it; optionally a Bloom's pink flower icon, or a dark-red missing-health
    remainder to the right."""
    frame[y:y + h, x:x + w] = (60, 230, 60)
    if text:
        # white glyph strokes inside the bar, ~10% of it
        for gx in range(x + w // 3, x + w // 3 + w // 4, 6):
            frame[y + 3:y + h - 3, gx:gx + 2] = (245, 245, 245)
    if pink:
        frame[y + 3:y + h - 3, x + 4:x + 4 + max(3, h // 2)] = (200, 120, 235)
    if tail:
        frame[y:y + h, x + w:x + w + w // 4] = (30, 20, 120)
    return frame


def test_a_green_bar_with_nothing_written_in_it_is_not_a_mob():
    """Plenty of things are flat green rectangles. A health bar has "HP: 26"
    in it, and that text is what a bare rectangle lacks."""
    frame = _bar(np.zeros((400, 600, 3), np.uint8), text=False)
    assert nameplate.find(frame) == []


def test_a_green_bar_with_white_text_inside_is_a_mob():
    frame = _bar(np.zeros((400, 600, 3), np.uint8))
    hits = nameplate.find(frame)
    assert len(hits) == 1, f"expected one plate, got {hits}"
    assert hits[0].hostile and hits[0].w == 80 and hits[0].h == 14


def test_a_bloom_is_a_bar_but_not_a_mob():
    """MEASURED: 0.0% pink inside all 14 mob bars, 2.2-4.8% inside all 10
    Bloom bars. The flower icon is the whole difference."""
    frame = _bar(np.zeros((400, 600, 3), np.uint8), pink=True)
    assert nameplate.find(frame) == []
    plates = nameplate.find_all(frame)
    assert len(plates) == 1 and plates[0].kind == "bloom"
    assert "not a mob" in plates[0].describe()


def test_missing_health_is_reported_as_a_red_tail():
    frame = _bar(np.zeros((400, 600, 3), np.uint8), tail=True)
    hits = nameplate.find(frame)
    assert len(hits) == 1 and hits[0].tail > 0.3
    assert "depleted" in hits[0].describe()


def test_floating_damage_text_with_no_bar_is_not_a_mob():
    """The false positive the first version made 7 times in 8."""
    frame = np.zeros((400, 600, 3), np.uint8)
    cv2.putText(frame, "+221", (300, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (245, 245, 245), 3)
    cv2.putText(frame, "+69", (300, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 40, 235), 3)
    assert nameplate.find(frame) == []


def test_an_outline_is_not_a_bar():
    """A health bar is a solid rectangle, not a frame around empty space."""
    frame = np.zeros((400, 600, 3), np.uint8)
    cv2.rectangle(frame, (300, 200), (380, 214), (60, 230, 60), 2)
    frame[205:209, 330:350] = (245, 245, 245)
    assert nameplate.find(frame) == []


def test_grass_green_is_not_bar_green():
    """MEASURED: grass in the beetle's own frame tops out at S 132, V 134;
    the bar body is S 220, V 232. A bar-shaped patch of GRASS colour with
    white flowers on it must not pass."""
    frame = np.zeros((400, 600, 3), np.uint8)
    frame[200:214, 300:380] = (55, 130, 70)          # grass, HSV ~ (63, 147, 130)
    frame[203:211, 330:336] = (245, 245, 245)
    assert nameplate.find(frame) == []


def test_an_empty_or_missing_frame_finds_nothing():
    assert nameplate.find(None) == []
    assert nameplate.find(np.zeros((0, 0, 3), np.uint8)) == []


def test_the_frames_that_actually_fooled_it_no_longer_do():
    """Regression on a real mistake, not a hypothetical one.

    These two frames are from a live run in the Pine Tree field. The detector
    called red flowers a mob health bar in both, and did it eleven times that
    run. They are kept because the original validation set -- 55 frames with
    no red flowers at that scale -- could not have caught this, and the next
    threshold change has to answer to them.
    """
    folder = (pathlib.Path(__file__).resolve().parents[1]
              / "fixtures" / "screens" / "field")
    frames = sorted(folder.glob("flowers_no_mob_*.jpg"))
    if not frames:
        pytest.skip("the flower frames are not in the repo")
    for path in frames:
        img = cv2.imread(str(path))
        hits = nameplate.find(img, top=170)
        assert hits == [], (
            f"{path.name}: {[h.describe() for h in hits]} — these are flowers")


def test_a_real_health_bar_is_long_and_thin():
    """The shape rule that separates a bar from a flowerbed.

    MEASURED: the first version's false positives ran 3.0-3.8 in aspect; the
    real bars 4.5-5.5. But a CLOSE beetle's bar is 376x56 (aspect 6.7) and a
    far one 66x14 (4.7), so the band is wide and the text rule does the work.
    """
    frame = _bar(np.zeros((400, 600, 3), np.uint8), w=30, h=20)   # aspect 1.5: chunky
    assert nameplate.find(frame) == [], "a chunky blob passed as a health bar"
    frame = _bar(np.zeros((400, 600, 3), np.uint8), w=66, h=12)   # 5.5: a bar
    assert len(nameplate.find(frame)) == 1


def test_a_correctly_shaped_wall_is_not_a_health_bar():
    """Aspect does not imply size.

    MEASURED in a live run: "health bar 1235x212 at (390, 223), aspect 5.8"
    -- two thirds of the screen. A mob's bar floats above it in world space
    and the closest one measured is 376x56.
    """
    frame = _bar(np.zeros((1080, 1920, 3), np.uint8), x=390, y=223, w=1235, h=212)
    assert nameplate.find(frame) == [], "a wall-sized blob passed as a bar"


# ---- on the real frames the first version was measured wrong on ----------
def _tail_frames(window, n=10):
    f = sorted(glob.glob(str(ROOT / f"var/incidents/{window}/*.jpg")))
    if not f:
        pytest.skip(f"{window} is not in the repo")
    return [cv2.imread(p) for p in f[-n:]]


def test_the_rhino_beetle_in_front_of_the_character_is_found():
    """The one true positive of the old detector's 8. It stood there for the
    whole last half-second of the window; it must be found in that stretch."""
    hits = [h for frame in _tail_frames("035138-mob-sighting") for h in nameplate.find(frame)]
    assert hits, "the beetle's bar was missed across the last ten frames"
    assert any(h.w > 150 for h in hits), [h.describe() for h in hits]


def test_a_bloom_in_a_real_frame_is_not_a_mob():
    """Pink inside the bar is a Bloom's flower icon, MEASURED 2.2-4.8% on all
    ten Bloom bars and 0.0% on all fourteen mob bars."""
    blooms = [p for frame in _tail_frames("023452-mob-sighting")
              for p in nameplate.find_all(frame) if p.pink >= nameplate.BLOOM_MIN_PINK]
    assert blooms, "no Bloom bar found in the last ten frames"
    assert all(not p.hostile and p.kind == "bloom" for p in blooms)


@pytest.mark.parametrize("window", ["000336-mob-sighting", "005926-mob-sighting",
                                    "052257-mob-sighting", "061128-mob-sighting"])
def test_the_frames_the_heart_rule_cried_wolf_on(window):
    """Checked by eye 2026-09-21: floating "+N" numbers, a red cube, the feed."""
    for frame in _tail_frames(window, n=1):
        assert nameplate.find(frame) == []


# ---- a planter's plate is not a mob -------------------------------------------
# The owner, 2026-09-28: it took planters for mobs, because a planter's green
# bar looks like a health bar. A planter's bar carries its own
# name inside ("Paper Planter (100.0%)") and no name above; a mob's name is
# above its bar. MEASURED on 193 bars from 500 saved mob-sighting windows:
# 14 of 15 planters, 0 of 178 mobs and Blooms (vision/nameplate).
_INCIDENTS = pathlib.Path(__file__).resolve().parents[2] / "var" / "incidents"


def _plate_at(rel, x, y):
    frame = cv2.imread(str(_INCIDENTS / rel))
    if frame is None:
        pytest.skip(f"{rel} is not on this machine")
    found = [p for p in nameplate.find_all(frame) if (p.x, p.y) == (x, y)]
    assert found, f"no bar at ({x}, {y}) in {rel}"
    return frame, found[0]


def test_a_planters_bar_is_a_planter_and_never_a_threat():
    frame, plate = _plate_at("20260928-002319-mob-sighting/149_t+10.8s.jpg", 278, 100)
    assert plate.kind == "planter" and not plate.hostile, plate
    assert "planter" in plate.describe()
    assert all((p.x, p.y) != (278, 100) for p in nameplate.find(frame))


def test_a_mob_with_its_name_above_is_still_a_mob():
    _, plate = _plate_at("20260925-021000-mob-sighting/149_t+11.4s.jpg", 650, 186)
    assert plate.kind == "mob" and plate.hostile, plate


def test_a_mob_whose_hp_is_as_wide_as_a_planters_name_is_still_a_mob():
    """ "Ladybug (Lvl 2)" over "1,300,400,000": wide text inside, like a
    planter's, and the name above it says what it is."""
    _, plate = _plate_at("20260925-053114-mob-sighting/149_t+11.1s.jpg", 1369, 195)
    assert plate.text_extent >= nameplate.PLANTER_MIN_TEXT_EXTENT
    assert plate.kind == "mob" and plate.hostile, plate

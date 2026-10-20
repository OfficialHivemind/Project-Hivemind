"""A field name tesseract split or misspelt (vision/whereami._near_field).

MEASURED 2026-10-22 over 700 saved reads of natro_pattern_* frames: "Bamboo
F ield" and "Fine Iree Forest" named no field (8 of 112 field lines). The
strips are the feed crops (`feed.strip`) of var/routes/attempt-1018
115539-natro_pattern_bamboo_* and 123331-natro_pattern_pine_tree_*.
"""
from __future__ import annotations

import pathlib
import shutil

import cv2
import pytest

import hivemind
from hivemind.vision import feed, whereami

ROOT = pathlib.Path(hivemind.__file__).resolve().parents[2]
KNOWN = whereami.field_names(ROOT / "data" / "knowledge" / "world.yaml")


@pytest.mark.parametrize("text, field", [
    ("1192 Honey (from Bamboo F ield)", "bamboo"),
    ("1524 Honey (from Fine Iree Forest)", "pine_tree"),
    ("+5 Honey (from Blue Flower Field)", "blue_flower"),       # exact still wins
])
def test_near_names_resolve(text, field):
    assert whereami.field_in(text, KNOWN) == field


@pytest.mark.parametrize("text", [
    "166 Honey (from Rhino Beetle)", "+9 Honey (from Rhino Beetie)",
    "+1,418 Honey (from Spider)", "+3 Honey (from Honey Gifts)",
    "+1 Honey (from Blue Bloom Petal)", "+2 Honey (from Mantis)",
])
def test_mobs_and_gifts_stay_out(text):
    assert whereami.field_in(text, KNOWN) is None


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="needs tesseract")
@pytest.mark.parametrize("name, field", [
    ("split-bamboo-field.png", "bamboo"),
    ("misspelt-pine-tree-forest.png", "pine_tree"),
])
def test_real_strips(name, field):
    strip = cv2.imread(str(ROOT / "tests" / "fixtures" / "feed" / name))
    assert whereami.field_in(feed.read_text(strip), KNOWN) == field

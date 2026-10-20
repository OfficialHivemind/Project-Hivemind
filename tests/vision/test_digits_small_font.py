"""The HUD shrinks its own font when the number gets long.

MEASURED 2026-09-23 02:05. The Pollen pill's digits are 8x11 px at six
figures and 6x9 at seven, and every template in data/templates/digits had
been cut from the larger font, so a full backpack read

    '11?0?46/111???0' at 0.49 confidence

and `Reading.value` was None for the whole of the busiest hour of the night.
The bar fallback (vision/screenstate.pollen_bar_fill) covered the convert
decision, but the per-trip pollen figure -- which is what the field notes
learn their rates from -- was lost. Small-font variants cut from a frame whose
number was read by eye fix it: '1130846/1113750' at 1.00.
"""
from __future__ import annotations

import glob
import pathlib

import cv2
import pytest

from hivemind.vision import digits
from hivemind.vision import screenstate as ss

ROOT = pathlib.Path(__file__).resolve().parents[2]

# (a frame, the number on its Pollen pill). Every one of these was read off
# the frame or out of the run log that produced it.
KNOWN = [
    ("var/bears/black_bear-234012.jpg", (1_130_846, 1_113_750)),          # small font
    ("tests/fixtures/screens/hive/at_own_hive.png", (627_840, 660_000)),  # normal font
    ("var/routes/attempt-254/*hive_offset*.jpg", (313_642, 1_113_750)),
    ("var/routes/attempt-244/202403-natro_out_cactus-02-hive_offset-d.jpg", (7_214, 1_113_750)),
]


def _templates():
    tmpl = ss.load_templates(ROOT / "data/templates/digits")
    if tmpl is None or not tmpl.templates:
        pytest.skip("the digit templates are not in the repo")
    return tmpl


@pytest.mark.parametrize("pattern, want", KNOWN)
def test_every_known_pollen_pill_reads_back(pattern, want):
    hits = sorted(glob.glob(str(ROOT / pattern)))
    if not hits:
        pytest.skip(f"no frame matching {pattern}")
    frame = cv2.imread(hits[0])
    if frame is None:
        pytest.skip(f"could not read {hits[0]}")
    x, y, w, h = ss.POLLEN_REGION
    text, score = digits.read(frame[y:y + h, x:x + w], _templates())
    assert digits.parse_fraction(text) == want, f"{text!r} at {score:.2f}"


def test_the_small_font_variants_are_registered_and_normalised():
    """Stored at NORM_H like every other template, or the probe and the
    template are compared at different scales -- which is how the first
    attempt at this made the reading WORSE (a slash classified as a 1)."""
    import json
    folder = ROOT / "data/templates/digits"
    index = json.loads((folder / "index.json").read_text())
    smalls = {name: char for name, char in index.items() if "_small" in name}
    assert len(smalls) >= 9, smalls
    for name in smalls:
        img = cv2.imread(str(folder / name), cv2.IMREAD_GRAYSCALE)
        assert img is not None, name
        assert img.shape[0] == digits.NORM_H, (name, img.shape)


def test_a_seven_figure_backpack_is_no_longer_unreadable():
    """The whole point: the counter that was gibberish all night."""
    frame = cv2.imread(str(ROOT / "var/bears/black_bear-234012.jpg"))
    if frame is None:
        pytest.skip("the frame is not in the repo")
    from hivemind.brain.farm import HudReader
    reading = HudReader(lambda: frame, _templates()).pollen()
    assert reading.ok, reading.describe()
    assert reading.value == 1_130_846 and reading.capacity == 1_113_750
    assert reading.fill_measured_by == "the counter"

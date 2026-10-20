"""HUD digit reading.

Templates were cut from a real 1920x1080 Bee Swarm frame whose Honey value was
known to be 10,216,184, so every glyph label is ground truth rather than a guess.
"""
import pathlib

import cv2
import pytest

from hivemind.vision.digits import (TemplateSet, parse_fraction, read, segment,
                                    to_int)

TEMPLATES = pathlib.Path(__file__).resolve().parents[2] / "data" / "templates" / "digits"
# Checked into the repo, not left in a scratch directory: this frame is the
# ground truth the digit templates were cut from, and a scratch path dies with
# the session that made it, silently skipping every test below.
FRAME = pathlib.Path(__file__).resolve().parents[1] / "fixtures/screens/in_game.png"
HONEY = (660, 22, 294, 36)
HONEY_TRUTH = "10,216,184"


@pytest.fixture(scope="module")
def templates():
    if not (TEMPLATES / "index.json").exists():
        pytest.skip("digit templates not extracted yet")
    return TemplateSet.load(TEMPLATES)


@pytest.fixture(scope="module")
def honey_roi():
    if not FRAME.exists():
        pytest.skip("no captured frame available")
    x, y, w, h = HONEY
    return cv2.imread(str(FRAME))[y:y + h, x:x + w]


def test_segments_exactly_the_right_glyph_count(honey_roi):
    assert len(segment(honey_roi)) == len(HONEY_TRUTH)


def test_reads_the_known_value(templates, honey_roi):
    text, conf = read(honey_roi, templates)
    assert text == HONEY_TRUTH
    assert conf > 0.9


def test_label_speckle_is_rejected(honey_roi):
    """The 'Honey' label leaks a 3x4 fragment through the threshold; it must not
    be mistaken for a glyph."""
    assert all(g.h >= 6 for g in segment(honey_roi))


def test_to_int_strips_separators():
    assert to_int("10,216,184") == 10216184
    assert to_int("445,372") == 445372
    assert to_int("") is None
    assert to_int("???") is None


def test_parse_fraction():
    assert parse_fraction("445,372/660,000") == (445372, 660000)
    assert parse_fraction("no slash here") is None


def test_low_confidence_becomes_a_question_mark(templates, honey_roi):
    """A glyph the templates do not really match must be flagged, never silently
    guessed -- a wrong digit in a pollen reading makes the bot convert at the
    wrong moment. Verified by demanding an impossible confidence.
    """
    text, _ = read(honey_roi, templates, min_score=1.01)
    # Commas are also known by their shape (digits._comma_shaped, 2026-10-22),
    # which no template score can veto; every DIGIT must still be "?".
    assert set(text) == {"?", ","}, f"expected all-unknown digits, got {text!r}"
    assert text == "??,???,???"


def test_reading_is_confident_at_the_default_threshold(templates, honey_roi):
    text, conf = read(honey_roi, templates)
    assert "?" not in text and conf > 0.9


def test_templates_cover_what_was_observed(templates):
    for ch in HONEY_TRUTH:
        assert ch in templates.chars, f"missing template for {ch!r}"

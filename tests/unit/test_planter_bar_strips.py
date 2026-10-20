"""act/planter.BAR_STRIPS / bar_names_fuzzy: the planter's own small bar, read
in thin enlarged strips. MEASURED 2026-10-21: 9 of 11 placings filed "no
planter's prompt showed" since 13 Oct had the bar on screen."""
from __future__ import annotations

from pathlib import Path

import pytest

from hivemind.act import planter


def test_the_ocr_slips_seen_on_the_real_bars_still_match():
    for text in ("Blue Clay Planter (0.0%)", "Rlue Clav Planter (0.0%)",
                 "Blus Clay Planuter HIELHT!", "Ticket Planter (0.0%)"):
        label = "Ticket Planter" if "Ticket" in text else "Blue Clay Planter"
        assert planter.bar_names_fuzzy(text, label), text


def test_other_words_and_other_planters_do_not():
    assert not planter.bar_names_fuzzy("Mantis: 8:52", "Blue Clay Planter")
    assert not planter.bar_names_fuzzy("Paper Planter (12%)", "Blue Clay Planter")
    assert not planter.bar_names_fuzzy("", "Blue Clay Planter")


def test_the_0905_frame_is_read_in_a_strip():
    frame_path = Path(Path.home() / "Hivemind/var/planters/place-20261021-090552-unseen.jpg")
    cv2 = pytest.importorskip("cv2")
    if not frame_path.exists():
        pytest.skip("the measured frame is not kept here")
    from hivemind.act import shoplook
    frame = cv2.imread(str(frame_path))
    assert any(planter.bar_names_fuzzy(
        shoplook.white_banner_text(frame, box=b, fx=4.0, white=180, smooth=True),
        "Blue Clay Planter") for b in planter.BAR_STRIPS)

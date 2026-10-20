"""Dates and fonts that work on Windows too (RL6, MEASURED 2026-10-21 on the
owner's Windows PC): strftime's "%-d" raises ValueError there, and no pip
OpenCV wheel has cv2.freetype, so the stats card could not be drawn."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import cv2

import hivemind
from hivemind.stream import privacy

REPO = Path(hivemind.__file__).resolve().parents[2]


def _card():
    sys.path.insert(0, str(REPO / "scripts"))
    import daily_card
    return daily_card


def test_the_day_of_the_month_has_no_leading_zero_on_any_os():
    at = time.mktime((2026, 10, 5, 12, 0, 0, 0, 0, -1))
    assert privacy.date_text(at, "%a %-d %b").split()[1] == "5"
    assert " 5 " in _card().day_line(at)
    assert "%" not in _card().day_line(at)


def test_no_glibc_only_strftime_flag_is_left_in_the_code():
    """"%-d", "%-H" ... raise on Windows; privacy.date_text and
    daily_card.day_line are the portable ways."""
    found = []
    for path in list((REPO / "src").rglob("*.py")) + list((REPO / "scripts").glob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""strftime\(\s*["'][^"']*%-[a-zA-Z]""", line):
                found.append(f"{path.relative_to(REPO)}:{n}")
    assert not found, found


def test_the_card_draws_without_freetype(tmp_path, monkeypatch):
    card = _card()
    monkeypatch.delattr(cv2, "freetype", raising=False)
    assert isinstance(card._font(card.FONT_TEXT), card._Hershey)
    out = card.render({"hours": 24, "honey": 1.5e9, "honey_per_hour": 6.2e7,
                       "series": [(0.0, 1_000_000), (3600.0, 2_000_000)]},
                      tmp_path / "card.png", card.day_line(0))
    assert out.stat().st_size > 10_000


def test_the_fallback_font_measures_and_draws_like_freetype():
    card = _card()
    (w, h), _ = card._Hershey().getTextSize("honey", 32, -1)
    assert 40 < w < 200 and 10 < h < 40

"""Number and duration formatting.

These appear on every panel, so a bug here shows wrong values everywhere while
looking perfectly plausible. Two real ones were found by testing them directly:
`human_number(999_999)` returned "1000K" because the unit was chosen before
rounding, and `fmt_score(0)` returned a bare "honey/hr" with no number at all,
which reads as missing data rather than as zero.
"""
import pytest

from hivemind.gui import theme
from hivemind.gui.widgets import human_duration, human_number


@pytest.mark.parametrize("value,expected", [
    (0, "0"), (1, "1"), (999, "999"),
    (1_000, "1.0K"), (1_500, "1.5K"), (13_377_238, "13.4M"),
    (1_000_000, "1.0M"), (1_440_000, "1.4M"), (150_000_000, "150M"),
    (1e12, "1.0T"),
    (-1_500, "-1.5K"), (-1_440_000, "-1.4M"),
])
def test_human_number(value, expected):
    assert human_number(value) == expected


def test_rounding_promotes_the_unit():
    """The regression: 999,999 used to render as '1000K'."""
    assert human_number(999_999) == "1.0M"
    assert human_number(-999_999) == "-1.0M"
    assert human_number(999.95e9) == "1.0T"


def test_no_value_ever_renders_an_unpromoted_unit():
    import random
    rng = random.Random(1)
    for value in [rng.uniform(-1e13, 1e13) for _ in range(2000)]:
        out = human_number(value)
        if out[-1] in "TBMK":
            head = float(out[:-1].replace(",", "").lstrip("-"))
            assert head < 1000, f"{value} -> {out}"


@pytest.mark.parametrize("seconds,expected", [
    (0, "0s"), (1, "1s"), (59, "59s"),
    (60, "1m 00s"), (61, "1m 01s"), (3599, "59m 59s"),
    (3600, "1h 00m"), (3661, "1h 01m"), (86399, "23h 59m"),
    (86400, "1d 00h"), (90000, "1d 01h"),
])
def test_human_duration(seconds, expected):
    assert human_duration(seconds) == expected


def test_negative_durations_clamp_to_zero():
    """A lapsed deadline must not render as a negative countdown."""
    assert human_duration(-5) == "0s"
    assert human_duration(-99999) == "0s"


@pytest.mark.parametrize("seconds,expected", [
    (30, "30s"), (90, "1m"), (3600, "1h"), (90000, "1d"),
])
def test_short_form_is_actually_short(seconds, expected):
    assert human_duration(seconds, short=True) == expected


def test_fmt_score_keeps_small_numbers_meaningful():
    """A 1.18x multiplier must not render as '1'."""
    assert theme.fmt_score(1.18, "x") == "1.18 x"
    assert theme.fmt_score(1.11, "x") == "1.11 x"
    assert theme.fmt_score(1.0, "x") == "1.00 x"


def test_fmt_score_zero_shows_a_number():
    """The regression: zero used to render as a bare unit."""
    assert theme.fmt_score(0, "honey/hr") == "0 honey/hr"
    assert theme.fmt_score(0) == "0"


def test_fmt_score_uses_separators_for_large_numbers():
    assert theme.fmt_score(431_000, "honey/hr") == "431,000 honey/hr"


def test_fmt_score_handles_negatives():
    assert theme.fmt_score(-3.2, "x") == "-3.20 x"


def test_an_elided_label_keeps_its_whole_text_and_says_it_in_the_tooltip():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.instance() or QApplication([])
    from hivemind.gui.widgets import ElidedLabel
    label = ElidedLabel("Convert at Blue Hive Balloon — 9 studs " * 4)
    label.resize(120, 20)
    label.show()                                              # sizes reach it when shown
    assert label.text().startswith("Convert at Blue") and len(label.text()) > 100
    assert QLabel.text(label).endswith("…")                  # what is drawn
    assert label.toolTip() == label.text()
    label.resize(4000, 20)
    assert QLabel.text(label) == label.text() and label.toolTip() == ""
    from PySide6.QtWidgets import QSizePolicy
    label.setFixedWidth(74)   # a fixed width must not be widened by the row (overlap 2026-10-22)
    assert label.sizePolicy().horizontalPolicy() == QSizePolicy.Fixed


def _contrast(a: str, b: str) -> float:
    def lum(h):
        c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_faint_text_is_readable_on_its_panels():
    """WCAG AA, 4.5:1 (UI panel 2026-10-21, low vision): the faint captions
    were 3.0-3.4:1."""
    assert _contrast(theme.S_FAINT, theme.S_CARD) >= 4.5
    assert _contrast(theme.S_FAINT, theme.S_PANEL) >= 4.5
    assert _contrast("#a8977a", "#19130b") >= 4.5          # the classic TEXT_FAINT on BG_PANEL


def test_a_countdown_marks_soon_and_very_soon_without_colour():
    import os
    import time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from hivemind.gui.widgets import Countdown
    c = Countdown(time.time() + 7200, warn_s=3600, critical_s=600)
    assert not c.text().startswith("!")
    c.set_deadline(time.time() + 1800)
    assert c.text().startswith("! ")
    c.set_deadline(time.time() + 120)
    assert c.text().startswith("!! ")
    c.set_deadline(time.time() - 1)
    assert c.text() == "ready"


def test_the_font_scale_reads_its_choices_and_scales_every_sheet_size():
    """ROADMAP U7: gui.font_scale, applied app-wide (gui/widgets.FontScaler)."""
    from hivemind.gui.widgets import font_scale, scale_sheet
    assert font_scale("130%") == 1.3 and font_scale("100%") == 1.0
    assert font_scale(None) == 1.0 and font_scale("huge") == 1.0
    assert font_scale("500%") == 1.6
    assert scale_sheet("QLabel { font-size: 13px; } a {font-size:10pt}", 1.3) == \
        "QLabel { font-size: 17px; } a {font-size:13pt}"


def test_the_scaler_resizes_widgets_but_not_a_fixed_window():
    """The stream is a fixed 1920x1080 picture for OBS: it keeps its sizes."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QWidget
    from hivemind.gui.widgets import FIXED_FONTS, FontScaler
    app = QApplication.instance() or QApplication([])
    scaler = FontScaler(1.3, app.font())
    app.installEventFilter(scaler)
    try:
        plain = QLabel("hi")
        plain.setStyleSheet("font-size: 10px;")
        fixed = QWidget()
        fixed.setProperty(FIXED_FONTS, True)
        inner = QLabel("hi", fixed)
        inner.setStyleSheet("font-size: 10px;")
        plain.show()
        fixed.show()
        assert plain.styleSheet() == "font-size: 13px;"
        assert inner.styleSheet() == "font-size: 10px;"
        plain.setStyleSheet("font-size: 20px;")        # a later restyle, once
        assert plain.styleSheet() == "font-size: 26px;"
        plain.close()
        fixed.close()
    finally:
        app.removeEventFilter(scaler)


def test_the_stream_window_is_marked_fixed():
    from pathlib import Path
    import hivemind.gui.stream as stream
    source = Path(stream.__file__).read_text(encoding="utf-8")
    assert "self.setProperty(FIXED_FONTS, True)" in source

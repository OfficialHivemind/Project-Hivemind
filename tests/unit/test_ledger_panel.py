"""The tab that answers "what did you do while I was asleep".

It reads a FILE, unlike every other panel, so these tests are about what it
does with the file: honest gaps, both halves of a mis-aimed trip, and not
redrawing itself when nothing changed.
"""
from __future__ import annotations

import json

import pytest

from hivemind.gui.panels.ledger import LedgerPanel, TripRow


def write(path, rows) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def trip(**kw) -> dict:
    base = dict(at=1_000.0, cycle=1, aimed_at="Sunflower", credited="Sunflower",
                seconds=300.0, gather_seconds=240.0, passes=20,
                pollen=100_000, honey=30_000, deaths=0, unreadable_pollen=0,
                recoveries=[], ok=True, reason="", gather_ended="full")
    base.update(kw)
    return base


@pytest.fixture
def path(tmp_path):
    return tmp_path / "trips.jsonl"


def test_it_shows_the_night_with_no_bot_running(qt_app, path):
    """The whole point: nothing is connected, and the numbers are all there."""
    write(path, [trip(at=1_000.0, honey=10_000),
                 trip(at=1_300.0, honey=20_000, cycle=2)])

    panel = LedgerPanel(path)

    assert panel._badge.text() == "2"
    labels = [w.text() for w in panel.findChildren(type(panel._fields))]
    assert any("30.0K" in t for t in labels), labels


def test_a_missing_file_says_so_once_and_stops_redrawing(qt_app, path):
    """A missing file stamps as None, which is also the "never drawn" value
    for a naive implementation -- so it redrew the empty panel for ever."""
    panel = LedgerPanel(path)
    assert panel._empty.isVisible() or panel._empty.title.text()

    first = panel._stamp
    panel.refresh()
    assert panel._stamp is first, "it re-stamped a file that does not exist"


def test_it_does_not_rebuild_when_the_file_has_not_changed(qt_app, path):
    """Sixty rows rebuilt every three seconds would fight the scroll bar."""
    write(path, [trip()])
    panel = LedgerPanel(path)
    rows = panel.findChildren(TripRow)

    panel.refresh()

    assert panel.findChildren(TripRow) == rows, "it rebuilt an unchanged file"


def test_a_new_trip_appears_without_being_asked(qt_app, path):
    write(path, [trip(at=1_000.0)])
    panel = LedgerPanel(path)
    assert len(panel.findChildren(TripRow)) == 1

    write(path, [trip(at=1_000.0), trip(at=1_400.0, cycle=2)])
    panel._stamp = None                    # stand in for the mtime moving
    panel.refresh()
    # deleteLater() only takes effect when the event loop next runs, so
    # without this the replaced row is still a child and the count reads 3.
    qt_app.processEvents()

    assert len(panel.findChildren(TripRow)) == 2


def test_an_unmeasured_trip_is_never_drawn_as_a_zero(qt_app, path):
    """A clean total that quietly understates the night is worse than a gap."""
    write(path, [trip(honey=None, pollen=None)])

    panel = LedgerPanel(path)
    texts = [w.text() for w in panel.findChildren(type(panel._fields))]

    assert any("not measured" in t for t in texts), texts
    assert not any(t.strip() == "0" for t in texts), texts


def test_the_field_that_paid_is_the_one_shown(qt_app, path):
    """MEASURED 2026-09-22: aimed Sunflower, credited Dandelion, 378,000/hr.

    The honey belongs to where the game's reward feed paid it, and the
    intention is kept in the tooltip so the routing fault stays visible.
    """
    write(path, [trip(aimed_at="Sunflower", credited="Dandelion", honey=90_000)])

    panel = LedgerPanel(path)
    row = panel.findChildren(TripRow)[0]
    texts = [w.text() for w in row.findChildren(type(panel._fields))]
    tips = [w.toolTip() for w in row.findChildren(type(panel._fields))]

    assert "Dandelion" in texts
    assert "Sunflower" not in texts, "it must not claim it reached the aim"
    assert any("aimed at Sunflower" in t for t in tips), tips


def test_only_this_sitting_is_totalled(qt_app, path):
    """The morning report once added last night's honey to tonight's and
    claimed 2,051,028 when the night had earned 124,538."""
    write(path, [trip(at=1_000.0, honey=999_999),
                 trip(at=1_000.0 + 5 * 3600, honey=7, cycle=2)])

    panel = LedgerPanel(path)

    assert panel._badge.text() == "1", "it counted a previous sitting"


def test_a_half_written_line_does_not_empty_the_panel(qt_app, path):
    write(path, [trip()])
    with path.open("a") as fh:
        fh.write('{"at": 2000, "honey": 5')          # killed mid-append

    panel = LedgerPanel(path)

    assert len(panel.findChildren(TripRow)) == 1


def test_a_carry_in_bank_is_named_rather_than_folded_into_the_total(qt_app, path):
    """It is part of the honey figure and was not earned in these seconds.

    MEASURED 2026-09-22 04:51: a 59-second cycle with 0 passes banked
    1,019,114 honey -- the previous trip's backpack, kept through the rejoin.
    Shown without a word it reads as a minute's work.
    """
    write(path, [trip(at=1_000.0, seconds=59.0, gather_seconds=0.0, passes=0,
                      pollen=None, honey=1_019_114),
                 trip(at=1_600.0, cycle=2, honey=30_000)])

    panel = LedgerPanel(path)
    texts = [w.text() for w in panel.findChildren(type(panel._fields))]

    assert any(t == "CARRIED IN" for t in texts), texts
    assert any("1.0M" in t for t in texts), texts
    # the rate is over the trip that actually gathered, not the 59-second bank
    assert panel._ledger.totals(rows=panel._ledger.trips()).honey_per_hour \
        == pytest.approx(30_000 * 3600 / 300.0)


def test_unnamed_honey_is_stated_rather_than_left_blank(qt_app, path):
    """An empty fields line reads as "no honey earned". What it means is that
    the game never named a field, which is a different thing."""
    write(path, [trip(aimed_at="sunflower", credited=None, honey=637)])

    panel = LedgerPanel(path)

    assert "named no field" in panel._fields.text()
    assert "sunflower" not in panel._fields.text(), \
        "the aim must not stand in for the field that paid"


def test_a_big_gather_that_never_converted_is_not_shown_as_a_blank(qt_app, path):
    """MEASURED 2026-09-22 05:33: 442,156 pollen over 76 passes, interrupted
    before the convert, so the honey column reads "not measured". With only a
    pass count beside it the row reads as a failure; it was the best
    gathering trip of the night."""
    write(path, [trip(pollen=442_156, honey=None, passes=76, seconds=1044.0)])

    panel = LedgerPanel(path)
    row = panel.findChildren(TripRow)[0]
    texts = [w.text() for w in row.findChildren(type(panel._fields))]
    tips = [w.toolTip() for w in row.findChildren(type(panel._fields))]

    assert any("442" in t for t in texts), texts
    assert any("76 pattern passes" in t for t in tips), tips


def test_the_walk_home_count_is_shown(qt_app, path):
    write(path, [trip(at=1_000.0, converted=True),
                 trip(at=1_300.0, cycle=2, converted=False)])
    panel = LedgerPanel(path)
    texts = [w.text() for w in panel.findChildren(type(panel._fields))]
    assert any("walked 1" in t and "rejoined 1" in t for t in texts), texts


def test_it_shows_which_pattern_is_paying(qt_app, path):
    """The evening's work, made visible: pollen per gathering second by
    pattern, which is how the pattern change was judged."""
    write(path, [trip(at=1_000.0, pollen=114_470, gather_seconds=566.0,
                      pattern="farm_snake"),
                 trip(at=1_600.0, cycle=2, pollen=479_828, gather_seconds=1_221.0,
                      pattern="natro_pattern_dandelion")])
    panel = LedgerPanel(path)
    texts = [w.text() for w in panel.findChildren(type(panel._fields))]
    line = next((t for t in texts if "pollen/sec by pattern" in t), "")
    assert line, texts
    assert "393" in line and "202" in line, line
    assert line.index("393") < line.index("202"), "the better pattern comes first"

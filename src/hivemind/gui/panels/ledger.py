"""Every trip the bot has made, and what each one earned.

WHY THIS PANEL READS A FILE WHILE EVERY OTHER ONE READS EVENTS. The owner
asked for stats in the app showing what the bot did -- a question about
the night, asked in the morning. The live event stream cannot answer it: it
begins empty each time the run restarts, and the night of 2026-09-21 restarted
134 times, so by morning the socket would know about the last few minutes and
nothing else. So this panel reads `var/trips.jsonl`, which outlives the runs
that wrote it, and polls it on a timer. A consequence worth having: the panel
is fully populated with the bot stopped, which is exactly when someone is
looking at it.

WHAT IT WILL NOT DO. It will not show a zero where a number was never
measured. A trip whose honey delta was never legible is listed with "not
measured" against it and left out of the totals, because a clean total that
quietly understates the night is worse than an obvious gap.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from ...brain.ledger import Ledger, latest_session
from .. import gameicons, theme
from ..widgets import Card, EmptyState, human_duration, human_number

# How often the file is re-read. A trip lasts minutes, so this is already far
# more often than the data can change; it is this frequent only so a trip that
# lands while the panel is open appears without the owner reaching for it.
REFRESH_MS = 3000
# Rows kept in the list. The totals are computed over EVERY trip in the
# session regardless -- this caps what is drawn, not what is counted.
SHOWN = 60

_NEVER_DRAWN = object()


def _discard(item) -> None:
    """Drop a widget out of the panel NOW, and free it when Qt is ready.

    `deleteLater()` alone leaves the widget a child of this panel until the
    event loop next runs, so immediately after a redraw the panel still owns
    the rows it just replaced -- which is wrong for anything that reads the
    panel's own state, and was caught by a test counting three rows after two
    were drawn. Reparenting first makes the removal immediate; deleteLater
    then frees it safely rather than while Qt may still be using it.
    """
    widget = item.widget() if item is not None else None
    if widget is not None:
        widget.setParent(None)
        widget.deleteLater()


def _stat(label: str, value: str, colour: str = "") -> QWidget:
    """One big number with its name under it."""
    colour = colour or theme.TEXT
    box = QWidget()
    box.setStyleSheet("background: transparent;")
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(0)
    big = QLabel(value)
    big.setStyleSheet(f"color: {colour}; font-family: {theme.MONO};"
                      " font-size: 20px; font-weight: 700;")
    col.addWidget(big)
    name = QLabel(label.upper())
    name.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 9px;"
                       " letter-spacing: 1px;")
    col.addWidget(name)
    return box


class TripRow(QFrame):
    """One trip, as it was measured."""

    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {theme.BG_RAISED}; border-radius: 4px;")
        line = QHBoxLayout(self)
        line.setContentsMargins(8, 5, 8, 5)
        line.setSpacing(10)

        when = QLabel(time.strftime("%H:%M", time.localtime(row.get("at") or 0)))
        when.setStyleSheet(f"color: {theme.TEXT_FAINT};"
                           f" font-family: {theme.MONO}; font-size: 11px;")
        when.setFixedWidth(40)
        line.addWidget(when)

        # WHERE IT AIMED AND WHERE IT WAS PAID, and both are shown when they
        # differ. MEASURED 2026-09-22: a trip aimed at Sunflower was credited
        # Dandelion by the game's own reward feed and earned 378,000 honey an
        # hour there. Showing only one of the two hides either the earnings or
        # the fact that the routes still land a field over.
        aimed, credited = row.get("aimed_at"), row.get("credited")
        if credited and aimed and credited != aimed:
            where, tip = f"{credited}", f"aimed at {aimed}, paid in {credited}"
        elif credited:
            where, tip = credited, f"aimed at and paid in {credited}"
        elif aimed:
            where, tip = aimed, f"aimed at {aimed}; the feed never named a field"
        else:
            where, tip = "—", "no field recorded for this trip"
        place = QLabel(where)
        place.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px;")
        place.setFixedWidth(120)
        place.setToolTip(tip)
        line.addWidget(place)
        if credited and aimed and credited != aimed:
            off = QLabel("↷")
            off.setStyleSheet(f"color: {theme.WARN}; font-size: 12px;")
            off.setToolTip(f"aimed at {aimed} — a field over is the shape of a"
                           " missing sideways walk to the owned pad")
            off.setFixedWidth(12)
            line.addWidget(off)
        else:
            line.addSpacing(12)

        dur = QLabel(human_duration(float(row.get("seconds") or 0.0), short=True))
        dur.setStyleSheet(f"color: {theme.TEXT_DIM};"
                          f" font-family: {theme.MONO}; font-size: 11px;")
        dur.setFixedWidth(46)
        dur.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        dur.setToolTip(f"{float(row.get('gather_seconds') or 0):.0f}s of it "
                       f"gathering, over {int(row.get('passes') or 0)} passes")
        line.addWidget(dur)

        # POLLEN, NOT THE PASS COUNT. A trip that gathered 442,156 pollen and
        # was interrupted before it could convert shows "not measured" in the
        # honey column, and with only a pass count beside it the row reads as
        # a failure. It was the best gathering trip of the night. The pollen
        # is what says so; the pass count moves to the tooltip.
        got = row.get("pollen")
        gathered = QLabel(human_number(got) if got else
                          "—" if got == 0 else "")
        gathered.setStyleSheet(
            f"color: {theme.INFO if got else theme.TEXT_FAINT};"
            f" font-family: {theme.MONO}; font-size: 11px;")
        gathered.setFixedWidth(56)
        gathered.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gathered.setToolTip(
            f"{got:,} pollen gathered over {int(row.get('passes') or 0)} "
            f"pattern passes" if got is not None else
            "the pollen counter was never read on this trip")
        line.addWidget(gathered)

        line.addStretch(1)

        honey = row.get("honey")
        if honey is None:
            money = QLabel("not measured")
            money.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;"
                                " font-style: italic;")
            money.setToolTip("the honey counter was never legible on this "
                             "trip, so nothing is claimed for it")
        else:
            money = QLabel(f"{human_number(honey)}")
            money.setStyleSheet(
                f"color: {theme.GOOD if honey > 0 else theme.TEXT_FAINT};"
                f" font-family: {theme.MONO}; font-size: 12px;"
                " font-weight: 700;")
            money.setToolTip(f"{honey:,} honey")
        money.setFixedWidth(88)
        money.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        line.addWidget(money)

        # WHY THE TRIP ENDED WHEN IT DID, which is how the 200x honey gap was
        # found: every short trip said `recovered 2x (jump, go_home)` while
        # the pollen counter was unreadable. See docs/DESIGN.md 8m.
        marks = []
        if int(row.get("deaths") or 0):
            marks.append(("✝", theme.BAD, f"{row['deaths']} death(s) — a death "
                                          "empties the backpack"))
        if int(row.get("unreadable_pollen") or 0):
            marks.append(("?", theme.WARN,
                          f"the pollen counter was unreadable "
                          f"{row['unreadable_pollen']}x on this trip"))
        if row.get("recoveries"):
            marks.append(("⟳", theme.WARN,
                          "recovered: " + ", ".join(row["recoveries"])))
        if not row.get("ok", True):
            marks.append(("!", theme.BAD, row.get("reason") or "stopped"))
        flags = QLabel(" ".join(m[0] for m in marks) or "")
        flags.setStyleSheet(f"color: {marks[0][1] if marks else theme.TEXT};"
                            " font-size: 11px;")
        flags.setFixedWidth(40)
        if marks:
            flags.setToolTip("\n".join(m[2] for m in marks))
        elif row.get("gather_ended"):
            flags.setToolTip(str(row["gather_ended"]))
        line.addWidget(flags)


class LedgerPanel(Card):
    """What it did, this sitting, read from the file that survives restarts."""

    def __init__(self, path: str | Path, parent=None):
        super().__init__("what it did", "this sitting", parent)
        self._ledger = Ledger(path)
        # (size, mtime) of the file as last drawn. A distinct sentinel, not
        # None, because None is a real value here -- it is what a MISSING
        # file stamps as, and comparing it against None would redraw the
        # empty panel every three seconds for ever.
        self._stamp: object = _NEVER_DRAWN

        self._stats = QHBoxLayout()
        self._stats.setContentsMargins(6, 2, 6, 6)
        self._stats.setSpacing(18)
        self.add_layout(self._stats)

        self._fields = QLabel("")
        self._fields.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._fields.setWordWrap(True)
        self.add(self._fields)

        # WHAT IT IS LEARNING, in the same panel as what it did: which gather
        # pattern is actually paying (per gathering second, the only fair
        # comparison) and how many labelled token crops the school has. Both
        # were invisible until now and both are the evening's work.
        self._learning = QLabel("")
        self._learning.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._learning.setWordWrap(True)
        self.add(self._learning)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(3)
        self._list.addStretch(1)
        scroll.setWidget(inner)
        self.add(scroll, 1)

        # NO FILE PATH, NO JARGON (UI panel 2026-10-21): the path is in the tooltip
        self._empty = EmptyState(gameicons.pixmap("fields", "Pine Tree", 40),
                                 "No trips yet",
                                 "Every trip the bot finishes shows here: where it went, "
                                 "how long it took and the honey it made. It is kept "
                                 "after the bot stops.")
        self._empty.setToolTip("Read from var/trips.jsonl, one line a trip.")
        self._list.insertWidget(0, self._empty)

        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(REFRESH_MS)

    # ---- drawing ---------------------------------------------------------
    def refresh(self) -> None:
        """Re-read the file, and redraw only when it has actually changed.

        Cheap enough to do on a timer because the stat() comes first: a panel
        that rebuilt sixty rows every three seconds would fight the user for
        the scroll position it is sitting in.
        """
        try:
            info = self._ledger.path.stat()
            stamp = (info.st_size, int(info.st_mtime))
        except OSError:
            stamp = None
        if stamp == self._stamp:
            return
        self._stamp = stamp

        rows = latest_session(self._ledger.trips())
        totals = self._ledger.totals(rows=rows)
        self._draw_stats(totals)
        self._draw_fields(totals)
        self._draw_learning(rows)
        self._draw_rows(rows)
        self.set_badge(str(totals.trips) if totals.trips else "")

    def _draw_stats(self, totals) -> None:
        while self._stats.count():
            _discard(self._stats.takeAt(0))
        rate = totals.honey_per_hour
        # NOTHING MEASURED IS NOT ZERO HONEY, and this line said "0" until a
        # test caught it: `if totals.trips` is true for a trip whose honey
        # counter was never legible, so a night of unreadable trips reported a
        # confident nought. The question is whether anything was MEASURED.
        measured = totals.trips > totals.unmeasured
        cells = [
            ("honey", human_number(totals.honey) if measured else "unknown",
             theme.GOOD if totals.honey else theme.TEXT_FAINT),
            ("per hour", human_number(rate) if rate is not None else "unknown",
             theme.ACCENT if rate else theme.TEXT_FAINT),
            ("trips", str(totals.trips), theme.TEXT),
            ("pollen", human_number(totals.pollen) if totals.pollen
             else "unknown" if totals.trips else "—", theme.TEXT),
            ("time out", human_duration(totals.seconds, short=True)
             if totals.seconds else "—", theme.TEXT),
        ]
        if totals.carried_in:
            # SAID, because it is part of the honey figure above it and it was
            # not earned in these trips' seconds. A trip whose walk home fails
            # keeps its backpack through the rejoin, and the next cycle banks
            # the lot in under a minute -- 1,019,114 honey in 59 seconds on
            # 2026-09-22. Real money, wrong clock. See brain/ledger.Totals.
            cells.append(("carried in", human_number(totals.carried_in),
                          theme.INFO))
        if totals.walked_home or totals.not_home:
            # The walk home, counted: gathered-and-converted against
            # gathered-and-never-got-there (after which the rejoin banks it).
            cells.append(("home",
                          f"walked {totals.walked_home} · rejoined {totals.not_home}",
                          theme.GOOD if totals.walked_home >= totals.not_home else theme.BAD))
        if totals.deaths:
            cells.append(("deaths", str(totals.deaths), theme.BAD))
        if totals.unmeasured:
            cells.append(("unmeasured", str(totals.unmeasured), theme.TEXT_FAINT))
        for label, value, colour in cells:
            cell = _stat(label, value, colour)
            if label == "per hour":
                cell.setToolTip(
                    "Honey earned, over the time the trips that earned it "
                    "took. A cycle that banks a previous trip's backpack is "
                    "left out when it gathered nothing itself — but if it "
                    "also did a little gathering, its honey still counts "
                    "here, which reads high. See brain/ledger.Totals.")
            elif label == "carried in":
                cell.setToolTip(
                    "Honey from cycles that gathered nothing and banked an "
                    "earlier trip's backpack — real money, wrong clock, so "
                    "it is counted in the total but not in the rate.")
            self._stats.addWidget(cell)
        self._stats.addStretch(1)

    def _draw_learning(self, rows) -> None:
        """Pollen per gathering second by pattern, and the school's tally."""
        parts = []
        try:
            by = self._ledger.by_pattern(rows=rows)
        except Exception:
            by = {}
        paying = sorted(((v["per_second"], name, v) for name, v in by.items()
                         if v.get("per_second")), reverse=True)
        if paying:
            parts.append("pollen/sec by pattern: " + "  ·  ".join(
                f"{name.replace('natro_pattern_', 'classic ')} {rate:,.0f}"
                f" ({v['trips']} trip{'s' if v['trips'] != 1 else ''})"
                for rate, name, v in paying[:4]))
        try:
            from ...brain.school import SCHOOL_DIR, School
            from ...datapaths import var
            parts.append("token school: " + School(var(SCHOOL_DIR)).describe())
        except Exception:
            pass
        text = "      ".join(parts)
        self._learning.setText(text)
        # the tallies mean nothing before a trip (an empty page said
        # "token school: 0 token lesson(s)...")
        self._learning.setVisible(bool(text) and bool(rows))

    def _draw_fields(self, totals) -> None:
        best = sorted(totals.by_field.items(), key=lambda kv: -kv[1])
        line = "  ·  ".join(f"{name} {human_number(value)}"
                            for name, value in best[:6])
        if totals.unattributed:
            # SAID RATHER THAN LEFT BLANK. An empty line reads as "no honey";
            # what it actually means is that the game never named a field for
            # those trips, so the honey is not put against one. The aim is NOT
            # used as a stand-in -- that would make a field the trip never
            # reached look like it pays. See brain/ledger.Totals.by_field.
            note = (f"{human_number(totals.unattributed)} from trips where "
                    f"the game named no field")
            line = f"{line}  ·  {note}" if line else note
        if not line:
            self._fields.setText("")
            self._fields.setVisible(False)
            return
        self._fields.setVisible(True)
        self._fields.setText(line)
        self._fields.setToolTip(
            "Honey credited by the game's own reward feed, which names the "
            "field on every pickup — never by where the trip meant to go. A "
            "trip the feed stayed silent about is counted but not attributed.")

    def _draw_rows(self, rows: list[dict]) -> None:
        self._empty.setVisible(not rows)
        while self._list.count() > 2:              # keep the empty label + stretch
            _discard(self._list.takeAt(1))
        for row in list(reversed(rows))[:SHOWN]:   # newest first
            self._list.insertWidget(self._list.count() - 1, TripRow(row))

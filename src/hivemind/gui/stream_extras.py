"""The stream's entertainment, drawn. The logic is stream/extras (no Qt).

    header     the commentary line, where the tagline was
    pager      the bottom-right card turns between TODAY (records and
               streaks), QUESTS (each open step's progress) and GEAR GOALS,
               one page every PAGE_SECONDS, with dots to say there are more
    recap      at midnight (local, or UTC with stream.utc_times), the day
               just ended, over the game picture
    clips      var/stream_clips.txt, a line per highlight

Nothing here runs per frame: it moves on the bot's events, the 5 s file poll
and the window's 1 s tick, so it cannot slow the live view down.

DESIGN 8ec.
"""
from __future__ import annotations

import copy
import time

from PySide6.QtCore import QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout, QLabel, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..stream import extras, privacy
from ..stream.show import human, toast
from . import theme
from .stream_privacy import SafeLabel, scrub
from .widgets import Meter

# How long each page of the bottom-right card stays. A page is four numbers
# or three bars with a line each: 25-35 words, 6-9 s at 238 words a minute
# (Brysbaert 2019), so twelve seconds reads it once with time to look back at
# the game; three pages come round every 36 s.
PAGE_SECONDS = 12
# The recap stays up for this long at midnight: nine rows of a label and a
# number, and a stream's viewers are not all looking at the moment it opens.
RECAP_SECONDS = 30
RECAP_W, RECAP_H = 760, 452

# The toast categories this adds to gui/stream.CATEGORY.
EXTRA_CATEGORY = {"best": ("NEW BEST", theme.ACCENT),
                  "streak": ("STREAK", theme.GOOD),
                  "recap": ("DAILY RECAP", theme.ACCENT)}


def _label(text: str = "", css: str = "", name: str = "", wrap: bool = False) -> QLabel:
    label = SafeLabel(text)
    label.setTextFormat(Qt.PlainText)
    if name:
        label.setObjectName(name)
    if css:
        label.setStyleSheet(css)
    label.setWordWrap(wrap)
    return label


class _Elided(SafeLabel):
    """One line, cut with an ellipsis at its width rather than mid-letter.
    It keeps what it was given (`_raw`) and scrubs as it fits, so a word the
    owner adds to the gate is hidden in it at once (`rescrub`)."""

    def __init__(self, css: str = ""):
        super().__init__("")
        self._raw = ""
        self.setTextFormat(Qt.PlainText)
        if css:
            self.setStyleSheet(css)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text) -> None:           # noqa: N802 (Qt's name)
        self._raw = str(text or "")
        self._fit()

    def rescrub(self) -> None:
        self._fit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        self.ensurePolished()
        QLabel.setText(self, self.fontMetrics().elidedText(
            scrub(self._raw), Qt.ElideRight, max(20, self.width())))


class _Page(QFrame):
    """A titled stream card (the stream's QFrame#Card style)."""

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(8)
        head = QHBoxLayout()
        self.title = _label(title.upper(), name="CardTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        self.subtitle = _label(subtitle, name="CardSub")
        head.addWidget(self.subtitle)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        outer.addLayout(self.body, 1)


class _Stat(QWidget):
    def __init__(self, label: str):
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(_label(label.upper(), name="TileLabel"))
        self.value = _label("—", f"font-family: {theme.MONO}; font-size: 23px;"
                                 " font-weight: 700;")
        box.addWidget(self.value)
        self.sub = _Elided()
        self.sub.setObjectName("TileSub")
        box.addWidget(self.sub)

    def set(self, value: str, sub: str = "", colour: str = theme.TEXT) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"font-family: {theme.MONO}; font-size: 23px;"
                                 f" font-weight: 700; color: {colour};")
        self.sub.setText(sub)


class TodayPage(_Page):
    """Records and streaks, from the ledger (stream/extras.Records)."""

    def __init__(self):
        super().__init__("today so far")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        self.best = _Stat("best trip")
        self.streak = _Stat("streak")
        self.top = _Stat("top field")
        self.tokens = _Stat("tokens chased")
        for i, stat in enumerate((self.best, self.streak, self.top, self.tokens)):
            grid.addWidget(stat, i // 2, i % 2)
        self.body.addLayout(grid)
        self.body.addStretch(1)
        self.note = _label("", f"color: {theme.TEXT_FAINT}; font-size: 12px;")
        self.body.addWidget(self.note)

    def show_day(self, day, run: int, tally) -> bool:
        """False when the day has nothing to show yet."""
        if day is None or not (day.trips or day.honey):
            return False
        self.subtitle.setText(privacy.date_text(day.start, "%a %-d %b")
                              + (" UTC" if privacy.utc_shown() else ""))
        if day.best is not None:
            where = extras.title(day.best.field) if day.best.field else "field unconfirmed"
            self.best.set(f"+{human(day.best.honey)}",
                          f"{where} · {privacy.clock_text(day.best.at, '%H:%M')}",
                          theme.ACCENT)
        else:
            self.best.set("—", "no trip banked yet")
        self.streak.set(f"{run}", "trips without a knock-out",
                        theme.GOOD if run >= 10 else theme.TEXT)
        top = day.top_field()
        if top is not None:
            self.top.set(extras.title(top[0]), f"{top[1]} trip{'' if top[1] == 1 else 's'}"
                                               f" · {human(top[2])}")
        else:
            self.top.set("—", "no field credited yet")
        self.tokens.set(f"{day.tokens:,}", f"over {day.trips} trip{'' if day.trips == 1 else 's'}")
        bits = [f"{day.deaths} knock-out{'' if day.deaths == 1 else 's'} today"]
        if tally is not None and tally.cannon:
            bits.append(f"{tally.cannon} cannon launch{'' if tally.cannon == 1 else 'es'} seen")
        if tally is not None and tally.bosses:
            bits.append(f"{tally.bosses} boss sighting{'' if tally.bosses == 1 else 's'}")
        self.note.setText(" · ".join(bits))
        return True


class QuestsPage(_Page):
    ROWS = 3

    def __init__(self):
        super().__init__("quests")
        self._rows = []
        for _ in range(self.ROWS):
            head = QHBoxLayout()
            text = _Elided("font-size: 14px; font-weight: 700;")
            count = _label("", f"color: {theme.TEXT_DIM}; font-family: {theme.MONO};"
                               " font-size: 12px;")
            head.addWidget(text, 1)
            head.addWidget(count)
            quest = _Elided(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
            bar = Meter(0.0, colour=theme.GOOD, height=7)
            self.body.addWidget(quest)
            self.body.addLayout(head)
            self.body.addWidget(bar)
            self._rows.append((quest, text, count, bar))
        self.body.addStretch(1)
        self.ready = _Elided(f"color: {theme.GOOD}; font-size: 12px; font-weight: 700;")
        self.body.addWidget(self.ready)

    def show_quests(self, body: dict) -> bool:
        bars, ready = extras.quest_bars(body, limit=self.ROWS)
        if not bars and not ready:
            return False
        read = (body or {}).get("read_at")
        self.subtitle.setText("the quest menu, read "
                              + privacy.clock_text(float(read), "%H:%M", zone=True)
                              if read else "the quest menu")
        for i, (quest, text, count, bar) in enumerate(self._rows):
            visible = i < len(bars)
            for widget in (quest, text, count, bar):
                widget.setVisible(visible)
            if not visible:
                continue
            b = bars[i]
            quest.setText(b.quest.upper())
            text.setText(b.text)
            count.setText(f"{b.done:,} / {b.total:,}")
            bar.set_value(b.fraction)
        self.ready.setText(("ready to hand in: " + ", ".join(ready)) if ready else "")
        self.ready.setVisible(bool(ready))
        return True


class _Dots(QWidget):
    """Which page of how many, bottom right of the card."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.count, self.index = 0, 0
        self.setFixedSize(60, 12)

    def paintEvent(self, _event) -> None:
        if self.count < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        x = 0
        for i in range(self.count):
            colour = QColor(theme.ACCENT if i == self.index else theme.TEXT_FAINT)
            painter.setBrush(colour)
            size = 8 if i == self.index else 6
            painter.drawEllipse(QRectF(x + i * 14 + (8 - size) / 2, (12 - size) / 2, size, size))
        painter.end()


class Pager(QStackedWidget):
    """Whole cards, one shown at a time, turning every PAGE_SECONDS. A page
    with nothing to show is skipped; with one page left there are no dots."""

    def __init__(self, pages: dict):
        super().__init__()
        self._names = list(pages)
        self._pages = dict(pages)
        self._on = {name: False for name in self._names}
        for name in self._names:
            self.addWidget(self._pages[name])
        self.dots = _Dots(self)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.turn)
        self._timer.start(PAGE_SECONDS * 1000)

    def show_page(self, name: str, on: bool) -> None:
        was = self._on.get(name)
        self._on[name] = bool(on)
        if was != bool(on):
            if not on and self.currentWidget() is self._pages[name]:
                self.turn()
            elif on and not self._on_names()[1:]:
                self.setCurrentWidget(self._pages[name])
        self._dots()

    def _on_names(self) -> list:
        return [n for n in self._names if self._on[n]]

    def has_pages(self) -> bool:
        return bool(self._on_names())

    def turn(self) -> None:
        names = self._on_names()
        if not names:
            return
        current = next((n for n in self._names
                        if self._pages[n] is self.currentWidget()), None)
        if current in names:
            name = names[(names.index(current) + 1) % len(names)]
        else:
            name = names[0]
        self.setCurrentWidget(self._pages[name])
        self._dots()

    def current(self) -> str:
        return next((n for n in self._names if self._pages[n] is self.currentWidget()), "")

    def _dots(self) -> None:
        names = self._on_names()
        self.dots.count = len(names)
        current = self.current()
        self.dots.index = names.index(current) if current in names else 0
        # BESIDE THE PAGE'S TITLE: at the card's foot the dots sat on the gear
        # goals' last line, and a page change raised the page over them.
        title = getattr(self.currentWidget(), "title", None)
        if title is not None:
            at = title.mapTo(self, title.rect().topLeft())
            width = title.fontMetrics().horizontalAdvance(title.text())
            self.dots.move(at.x() + width + 12,
                           at.y() + (title.height() - self.dots.height()) // 2)
        self.dots.setFixedWidth(max(1, self.dots.count) * 14)
        self.dots.raise_()
        self.dots.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._dots()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._dots)


class RecapCard(QFrame):
    """The day just ended, over the middle of the game picture."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Recap")
        self.setStyleSheet(
            f"QFrame#Recap {{ background: rgba(14,16,20,0.94);"
            f" border: 1px solid {theme.ACCENT}; border-top: 6px solid {theme.ACCENT};"
            " border-radius: 14px; }")
        self.setFixedWidth(RECAP_W)
        box = QVBoxLayout(self)
        box.setContentsMargins(30, 20, 30, 22)
        box.setSpacing(4)
        box.addWidget(_label("DAILY RECAP", f"color: {theme.ACCENT}; font-size: 13px;"
                                            " font-weight: 900; letter-spacing: 3px;"))
        self.head = _label("", "font-size: 30px; font-weight: 900;")
        box.addWidget(self.head)
        box.addSpacing(8)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(24)
        self.grid.setVerticalSpacing(8)
        box.addLayout(self.grid)
        box.addSpacing(10)
        self.foot = _label("", f"color: {theme.TEXT_FAINT}; font-size: 12px;")
        box.addWidget(self.foot)
        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(0.0)
        self.setGraphicsEffect(self.effect)
        self._anim = None
        # a child timer, not a singleShot lambda: it dies with the window
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._fade(0.0, hide=True))
        self.hide()

    def show_recap(self, recap, seconds: float = RECAP_SECONDS) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.head.setText(f"{recap.date} on the stream")
        for i, (label, value, note) in enumerate(recap.lines[:10]):
            r, c = divmod(i, 2)
            cell = QWidget()
            col = QVBoxLayout(cell)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)
            col.addWidget(_label(label, "font-size: 11px; font-weight: 800;"
                                        f" letter-spacing: 1px; color: {theme.TEXT_FAINT};"))
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(_label(value, f"font-family: {theme.MONO}; font-size: 22px;"
                                        " font-weight: 700;"))
            row.addWidget(_label(note, f"color: {theme.TEXT_DIM}; font-size: 13px;"), 1)
            col.addLayout(row)
            self.grid.addWidget(cell, r, c)
        self.foot.setText("from the bot's trip ledger and what this stream saw · "
                          "a new day starts now")
        # AS TALL AS ITS ROWS: at a fixed 452 px a five-row recap was half
        # empty on the first render.
        layout = self.layout()
        layout.activate()
        tall = (layout.totalHeightForWidth(RECAP_W) if layout.hasHeightForWidth()
                else layout.sizeHint().height())
        self.setFixedHeight(min(RECAP_H, tall))
        parent = self.parentWidget()
        if parent is not None:
            self.move((parent.width() - self.width()) // 2,
                      (parent.height() - self.height()) // 2)
        self.show()
        self.raise_()
        self._fade(1.0)
        self._timer.start(int(seconds * 1000))

    def _fade(self, to: float, hide: bool = False) -> None:
        anim = QPropertyAnimation(self.effect, b"opacity", self)
        anim.setDuration(400)
        anim.setStartValue(self.effect.opacity())
        anim.setEndValue(to)
        if hide:
            anim.finished.connect(self.hide)
        self._anim = anim
        anim.start()


class StreamExtras:
    """What the stream window hands its events, rows and toasts to.

    `push(toast)` puts a toast on the picture; `path(name)` is a var file;
    `board()` is chat's leaderboard (stream/show.Show.board); `relayout()` is
    called when a page comes or goes, since the bottom row's widths depend on
    whether the card has any page at all."""

    def __init__(self, view, push, path, board, get, clock=time.time,
                 opened_at: float | None = None, relayout=lambda: None):
        self.clock = clock
        self.push = push
        self.relayout = relayout
        self.board = board
        self.opened_at = clock() if opened_at is None else opened_at
        self.commentary = extras.Commentary(clock=clock)
        self.records = extras.Records(clock=clock)
        # EVERY KNOCK-OUT the bot kept an incident of, and every one the
        # stream toasts (stream/extras.Knockouts): the ledger's own count
        # booked 4 of the 7 real ones (DESIGN 8ec)
        self.knockouts = extras.Knockouts(path("incidents"))
        self.counter = extras.Counter(clock=clock, opened_at=self.opened_at)
        self.clips = extras.Clips(path("stream_clips.txt"), clock=clock,
                                  opened_at=self.opened_at,
                                  enabled=lambda: bool(get("stream.clip_markers")))
        self.today = TodayPage()
        self.quests = QuestsPage()
        self.recap = RecapCard(view)
        self._rows: list = []
        self._day = extras.local_midnight(self.opened_at)
        self._board_at_day = copy.deepcopy(board())
        self._caption = ""

    def pager(self, gear) -> Pager:
        self.pages = Pager({"today": self.today, "quests": self.quests, "gear": gear})
        return self.pages

    # ---- feeding ---------------------------------------------------------------
    def saw(self, event, quiet: bool) -> None:
        from ..telemetry.events import Considered
        if quiet and not isinstance(event, Considered):
            return
        self.commentary.saw(event)
        self.counter.saw(event)

    def toasted(self, item) -> None:
        self.commentary.said(item)
        self.clips.from_toast(item)
        if item.kind == "death":
            # A KNOCK-OUT IS NEWS ON TODAY'S CARD AT ONCE, not at the next
            # ledger row: the row the bot files for it can book none
            self.knockouts.seen(self.clock())
            self.counter.tally.deaths_seen += 1
            self.rows(self._rows, quiet=True)

    def knockout_times(self) -> list:
        return self.knockouts.times(self._rows)

    def knockouts_since(self, since: float) -> int:
        return sum(1 for k in self.knockout_times() if k >= since)

    def rows(self, rows: list, quiet: bool = False) -> None:
        self._rows = rows
        self.records.on_rows(rows, self.knockout_times())
        for kind, head, body in self.records.drain():
            if not quiet:
                self.push(toast(kind, head, body))
        self._show("today", self.today.show_day(
            self.records.today, self.records.streak, self.counter.tally))

    def redraw(self) -> None:
        """Draw today's card again (the stream's clock changed)."""
        self._day = extras.local_midnight(self.clock())
        self.counter.tally.day = self._day
        self.rows(self._rows, quiet=True)

    def quest_file(self, body: dict) -> None:
        self._show("quests", self.quests.show_quests(body))

    def _show(self, page: str, on: bool) -> None:
        had = self.pages.has_pages()
        self.pages.show_page(page, on)
        if self.pages.has_pages() != had:
            self.relayout()

    def caption(self) -> str:
        return scrub(self.commentary.line)

    # ---- the clock ----------------------------------------------------------------
    def tick(self) -> None:
        now = self.clock()
        start = extras.local_midnight(now)
        if start != self._day:
            ended, self._day = self._day, start
            self.show_recap(ended)
            self._board_at_day = copy.deepcopy(self.board())
            # TODAY is a new day: its page empties until the first trip
            self.rows(self._rows, quiet=True)

    def show_recap(self, day_start: float, seconds: float = RECAP_SECONDS) -> bool:
        tally = self.counter.yesterday if (self.counter.yesterday is not None
                                           and self.counter.yesterday.day == day_start) \
            else (self.counter.tally if self.counter.tally.day == day_start else None)
        recap = extras.recap(self._rows, day_start, tally=tally,
                             board_delta=extras.board_delta(self._board_at_day, self.board()),
                             opened_at=self.opened_at, knockouts=self.knockout_times())
        if recap is None:
            return False
        self.recap.show_recap(recap, seconds)
        honey = next((v for label, v, _n in recap.lines if label == "HONEY BANKED"), "")
        self.clips.mark("recap", f"{recap.date}: {honey} honey banked")
        return True


def caption_css() -> str:
    return (f"color: {theme.ACCENT}; font-size: 18px; font-weight: 800;")

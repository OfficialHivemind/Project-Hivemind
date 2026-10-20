"""The "watch it think" pane.

The owner's request was to see the AI think. This is that.

The design problem is that a bot emits reasoning far faster than a person reads
it, so a raw firehose is noise. Two things fix that:

  * thoughts are grouped by topic, and a run of thoughts on the same topic
    collapses into one entry with a count. Twelve lines of "checking planter" is
    one line that says so.
  * decisions are rendered differently from thoughts. A `Considered` event gets
    the options it weighed and the score for each, so the reason for a choice is
    visible without unfolding anything.

Auto-scroll stops the moment you scroll up, and resumes when you return to the
bottom. Watching a log that yanks itself away while you are reading it is the
fastest way to make a dashboard useless.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QLayout, QLineEdit, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from ...telemetry.events import Considered, Thought
from .. import theme
from .. import gameicons
from ..widgets import ElidedLabel, EmptyState

MAX_ENTRIES = 400          # trimmed from the top; the recorder keeps the rest
SERIOUS = ("warn", "error")                 # telemetry.events.Level's words


def _clock(at: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(at))


def breakable(text: str, every: int = 40) -> str:
    """A word longer than `every` gets a zero-width space every `every`
    characters, so a wrapped label can break it instead of widening the
    page (render probe, UI panel round 2, 2026-10-22)."""
    return " ".join(w if len(w) <= every else "\u200b".join(
        w[i:i + every] for i in range(0, len(w), every)) for w in text.split(" "))


class ThoughtRow(QFrame):
    """A single line of reasoning, with a repeat counter."""

    def __init__(self, event: Thought, level: str = "info"):
        super().__init__()
        self.topic = event.topic
        self.level = str(getattr(level, "value", level))     # a Level or its word
        self.count = 1
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 3, 10, 3)
        row.setSpacing(8)

        self._time = QLabel(_clock(event.at))
        self._time.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-family: {theme.MONO}; font-size: 12px;")
        self._time.setMinimumWidth(62)
        row.addWidget(self._time, 0, Qt.AlignTop)

        if event.topic:
            tag = ElidedLabel(event.topic)
            tag.setStyleSheet(
                f"color: {theme.INFO}; font-size: 12px; font-weight: 600;")
            tag.setFixedWidth(74)
            row.addWidget(tag, 0, Qt.AlignTop)

        self._text = QLabel(breakable(event.text))
        self._text.setWordWrap(True)
        self._text.setStyleSheet(f"color: {theme.TEXT};")
        self._text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        row.addWidget(self._text, 1)

        self._badge = QLabel("")
        self._badge.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 12px;")
        row.addWidget(self._badge, 0, Qt.AlignTop)

        self._base = event.text

    def matches(self, event: Thought) -> bool:
        return event.topic == self.topic and event.text == self._base

    def bump(self, event: Thought) -> None:
        self.count += 1
        self._badge.setText(f"x{self.count}")
        self._time.setText(_clock(event.at))


class DecisionCard(QFrame):
    """A decision, showing every option and the number that settled it."""

    def __init__(self, event: Considered):
        super().__init__()
        self.setObjectName("Panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 9, 12, 9)
        outer.setSpacing(5)

        head = QHBoxLayout()
        mark = QLabel("decided")
        mark.setStyleSheet(
            f"color: {theme.GOOD}; font-size: 12px; font-weight: 700;"
            " letter-spacing: 1px;")
        head.addWidget(mark)
        head.addStretch(1)
        if not event.reversible:
            lock = QLabel("irreversible")
            lock.setStyleSheet(f"color: {theme.WARN}; font-size: 12px;"
                               " font-weight: 700; letter-spacing: 1px;")
            head.addWidget(lock)
        stamp = QLabel(_clock(event.at))
        stamp.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-family: {theme.MONO}; font-size: 12px;")
        head.addWidget(stamp)
        outer.addLayout(head)

        question = QLabel(event.question)
        question.setWordWrap(True)
        question.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        outer.addWidget(question)

        best = max((o.score for o in event.options), default=0.0) or 1.0
        for option in event.options:
            picked = option.label == event.chosen
            line = QHBoxLayout()
            line.setSpacing(8)

            # a check and the word, not a filled dot in green alone (UI panel
            # round 2, 2026-10-22, colourblind and pro readers)
            name = ElidedLabel(("✓ " if picked else "○ ") + option.label)
            name.setStyleSheet(
                f"color: {theme.GOOD if picked else theme.TEXT_DIM};"
                f" font-weight: {'600' if picked else '400'};")
            name.setFixedWidth(190)
            line.addWidget(name)

            bar = QFrame()
            bar.setFixedHeight(4)
            share = max(0.02, min(1.0, option.score / best if best else 0))
            # BORDER was too close to the panel background to read as a bar
            bar.setStyleSheet(
                f"background: {theme.GOOD if picked else theme.TEXT_FAINT};"
                " border-radius: 2px;")
            bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            holder = QWidget()
            holder.setFixedHeight(10)
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 3, 0, 3)
            hl.addWidget(bar, int(share * 100))
            hl.addStretch(max(1, int((1 - share) * 100)))
            line.addWidget(holder, 1)

            value = QLabel(theme.fmt_score(option.score, option.unit))
            value.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-family: {theme.MONO};"
                " font-size: 12px;")
            value.setMinimumWidth(110)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            line.addWidget(value)
            outer.addLayout(line)

        if event.rationale:
            why = QLabel(event.rationale)
            why.setWordWrap(True)
            why.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
            outer.addWidget(why)


class ThinkPanel(QWidget):
    """Scrolling stream of thoughts and decisions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._inner = QWidget()
        # THE STREAM IS AS TALL AS ITS ROWS AT THIS WIDTH. Otherwise the scroll
        # area sizes it by the wrapped labels' minimum hints (each laid out
        # narrow, so tall), and the follow scrolled into blank space below the
        # last row: the page looked empty (usability triage 2026-10-26 #13;
        # MEASURED offscreen, 30 rows at 1000 px: 1328 px tall for rows ending
        # at 811). Ignored + no constraint leaves the height to heightForWidth.
        self._inner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        self._stream = QVBoxLayout(self._inner)
        self._stream.setSizeConstraint(QLayout.SetNoConstraint)
        self._stream.setContentsMargins(4, 6, 4, 6)
        self._stream.setSpacing(4)
        self._stream.addStretch(1)
        self._scroll.setWidget(self._inner)
        layout.addWidget(self._scroll)

        self._placeholder = None
        self._show_empty()

        self._last: ThoughtRow | None = None
        self._rows = 0

        # FOLLOW THE STREAM until the user scrolls away, then stop until they
        # scroll back. This has to be a remembered flag rather than a test
        # performed at insert time.
        #
        # The old version read "am I at the bottom?" and then called
        # setValue(maximum()) in the same call -- but the scroll area's range
        # is only recomputed on a later event-loop pass, so maximum() was still
        # the PRE-insert value. The scrollbar therefore ended one row height
        # (~30px) short of the true bottom, which exceeds the 24px tolerance,
        # so the next insert decided the user had scrolled away and it never
        # recovered. Measured with a real event loop: after 60 thoughts the bar
        # sat at value=15 with maximum=3309. The panel the whole GUI is built
        # around froze on the first five thoughts.
        #
        # Deferring with singleShot(0) is not enough either -- the range lags
        # several passes. Reacting to rangeChanged is the only reliable moment,
        # because that IS the signal that the new row has been laid out.
        self._stick = True
        self._programmatic = False
        bar = self._scroll.verticalScrollBar()
        bar.rangeChanged.connect(self._follow_if_sticking)
        bar.valueChanged.connect(self._on_value_changed)

    def _show_empty(self) -> None:
        """The empty state: at the start, and again after clear()."""
        self._placeholder = EmptyState(gameicons.pixmap("items", "Moon Charm", 40),
                                       "Waiting for the bot to think",
                                       "Press Start. Every choice it makes, and why, "
                                       "shows here as it happens.")
        self._stream.insertWidget(0, self._placeholder)

    def _at_bottom(self) -> bool:
        bar = self._scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - 24

    def _on_value_changed(self, _value: int) -> None:
        """Only the USER's scrolling decides whether we keep following."""
        if self._programmatic:
            return
        self._stick = self._at_bottom()

    def _follow_if_sticking(self, *_range) -> None:
        if not self._stick:
            return
        bar = self._scroll.verticalScrollBar()
        self._programmatic = True
        try:
            bar.setValue(bar.maximum())
        finally:
            self._programmatic = False

    def _append(self, widget: QWidget) -> None:
        if self._placeholder is not None:
            # removeWidget, not just deleteLater: deletion is deferred to the
            # next event-loop pass, so the placeholder would keep occupying a
            # row above the first real thought until then.
            self._stream.removeWidget(self._placeholder)
            self._placeholder.setParent(None)
            self._placeholder.deleteLater()
            self._placeholder = None
        self._stream.insertWidget(self._stream.count() - 1, widget)
        self._rows += 1
        if self._rows > MAX_ENTRIES:
            # THE OLDEST ORDINARY ROW GOES, so warnings and errors outlive the
            # chatter around them: MEASURED offscreen, run-1257's 1,433 log
            # rows through this pane kept 6 of its 14 warnings when the
            # oldest row went whatever it was (levels estimated by message
            # prefix; GUI polish 2026-10-27, docs/pending/guismall.md). Never
            # the row just added (count - 2), or _last would point at a dead one
            at = next((i for i in range(self._stream.count() - 2) if getattr(
                self._stream.itemAt(i).widget(), "level", "info") not in SERIOUS), 0)
            old = self._stream.takeAt(at)
            if old and old.widget():
                old.widget().deleteLater()
            self._rows -= 1
        # rangeChanged does the scrolling once the row is actually laid out;
        # this covers the case where the range happens not to change.
        self._follow_if_sticking()

    def add_thought(self, event: Thought, level: str = "info") -> None:
        if self._last is not None and self._last.matches(event):
            self._last.bump(event)
            return
        row = ThoughtRow(event, level)
        self._last = row
        self._append(row)

    def add_decision(self, event: Considered) -> None:
        self._last = None
        self._append(DecisionCard(event))

    def clear(self) -> None:
        while self._stream.count() > 1:
            item = self._stream.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._rows = 0
        self._last = None
        # the old empty state went with the rows (a deleted widget _append
        # would trip on): a cleared pane says it is waiting, not blank
        self._show_empty()


class LogPanel(ThinkPanel):
    """THE LOG TAB, WITH A FILTER ROW (ROADMAP U7 / GUI polish): a topic, a
    "warnings and errors only" switch and a text box. MEASURED 2026-10-27 on
    var/night/run-1257.log (55 min, its lines matched to their Log() calls by
    message prefix, so the level is an estimate; docs/pending/guismall.md):
    about 1,430 rows reached this tab, 1,153 of them the token chase's and
    about 14 of them warnings, and the tab keeps the last 400 (MAX_ENTRIES,
    about 15 minutes) with no way to pick those out. The filter only hides
    rows; it never drops one, so clearing it shows them all again."""

    def __init__(self, parent=None):
        super().__init__(parent)
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 4, 4, 2)
        bar.setSpacing(8)
        self.topic = QComboBox()
        self.topic.addItem("All topics")
        self.topic.setToolTip("Show one topic only (the part of the bot that wrote the line)")
        self.serious = QCheckBox("Warnings and errors only")
        self.text = QLineEdit()
        self.text.setPlaceholderText("Filter by text")
        self.text.setClearButtonEnabled(True)
        self.shown = QLabel("")
        self.shown.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 12px;")
        for widget, stretch in ((self.topic, 0), (self.serious, 0),
                                (self.text, 1), (self.shown, 0)):
            bar.addWidget(widget, stretch)
        self.layout().insertLayout(0, bar)
        self.topic.currentIndexChanged.connect(self.refilter)
        self.serious.toggled.connect(self.refilter)
        self.text.textChanged.connect(self.refilter)

    def _filtering(self) -> bool:
        return bool(self.topic.currentIndex() or self.serious.isChecked()
                    or self.text.text().strip())

    def passes(self, row: QWidget) -> bool:
        if not isinstance(row, ThoughtRow):
            return True                     # the empty state, a decision card
        if self.topic.currentIndex() and row.topic != self.topic.currentText():
            return False
        if self.serious.isChecked() and row.level not in SERIOUS:
            return False
        words = self.text.text().strip().casefold()
        return not words or words in f"{row.topic} {row._base}".casefold()

    def rows(self) -> list[ThoughtRow]:
        items = (self._stream.itemAt(i) for i in range(self._stream.count()))
        return [item.widget() for item in items
                if isinstance(item.widget(), ThoughtRow)]

    def _count(self) -> None:
        rows = self.rows()
        self.shown.setText(f"{sum(not r.isHidden() for r in rows)} of {len(rows)}"
                           if self._filtering() else "")

    def _append(self, widget: QWidget) -> None:
        topic = getattr(widget, "topic", "")
        if topic and self.topic.findText(topic) < 0:
            self.topic.addItem(topic)
        super()._append(widget)
        widget.setVisible(self.passes(widget))      # after: it has a parent now
        self._count()

    def refilter(self, *_args) -> None:
        for row in self.rows():
            row.setVisible(self.passes(row))
        self._count()

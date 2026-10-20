"""Bosses, machines, shrines and events, as deadlines.

Two details here that existing macros get wrong.

**Times are UTC.** Every hardcoded boss clock written in local time drifts by an
hour twice a year when daylight saving moves, and then silently sends the bot to
an empty field for six months.

**Bosses do not all behave the same.** The Coconut Crab resets its health if you
leave the field, so it must never be preempted -- starting it and wandering off
wastes the whole fight. The Stump Snail SAVES damage between visits, so chipping
at it opportunistically is correct. One flag, `persistent_hp`, separates them,
and it changes the scheduler's behaviour completely. Showing it here means you
can see why the bot committed to one fight and walked away from another.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from ...telemetry.events import Timer as TimerEvent
from .. import theme
from .. import gameicons
from ..widgets import Card, Countdown, EmptyState, Pill

CATEGORY_COLOURS = {
    "boss": theme.BAD,
    "machine": theme.INFO,
    "event": theme.ACCENT,
    "shrine": "#a78bfa",
    "mob": theme.WARN,          # the bug runs' respawn timers (act/bugrun)
    "boost": theme.GOOD,        # the running field boost (run_farm show_boost)
    "booster": theme.INFO,      # a field booster's cooldown (U19 show_boost_timers)
    "item": theme.GOOD,         # an item buff still running (U19)
}


class TimerRow(QWidget):
    def __init__(self, timer: TimerEvent, parent=None):
        super().__init__(parent)
        self.id = timer.id
        self.timer_event = timer
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 5, 6, 5)
        row.setSpacing(9)

        self._category = Pill(timer.category or "—",
                              CATEGORY_COLOURS.get(timer.category, theme.TEXT_DIM))
        self._category.setFixedWidth(62)
        self._category.setAlignment(Qt.AlignCenter)
        row.addWidget(self._category, 0, Qt.AlignTop)   # a tag, not a block beside a wrapped note

        middle = QVBoxLayout()
        middle.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(6)
        self._name = QLabel(timer.name)
        self._name.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        self._name.setWordWrap(True)       # a long name must not widen the row either
        head.addWidget(self._name)
        self._hp = Pill("✓ saves damage", theme.GOOD)     # a shape too (2026-10-22)
        self._hp.setToolTip(
            "Damage persists between visits, so this can be chipped at "
            "opportunistically rather than fought in one go.")
        head.addWidget(self._hp)
        head.addStretch(1)
        middle.addLayout(head)
        self._note = QLabel(timer.note)
        self._note.setWordWrap(True)       # was cut off on the right (UI panel 2026-10-22)
        self._note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 12px;")
        middle.addWidget(self._note)
        row.addLayout(middle, 1)

        self._eta = Countdown(timer.ready_at, warn_s=1800, critical_s=600)
        self._eta.setFixedWidth(70)
        self._eta.setAlignment(Qt.AlignRight)
        row.addWidget(self._eta)

        self.update_from(timer)

    def update_from(self, timer: TimerEvent) -> None:
        self.timer_event = timer
        self._category.setText(timer.category or "—")
        self._category.set_colour(
            CATEGORY_COLOURS.get(timer.category, theme.TEXT_DIM))
        self._name.setText(timer.name)
        self._note.setText(timer.note)
        self._note.setVisible(bool(timer.note))
        self._hp.setVisible(timer.persistent_hp)
        self._eta.set_deadline(timer.ready_at)

    @property
    def deadline(self) -> float:
        return self.timer_event.ready_at or float("inf")


class TimersPanel(Card):
    def __init__(self, parent=None):
        super().__init__("timers", "UTC — no daylight-saving drift", parent)
        self._rows: dict[str, TimerRow] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(1)
        self._list.addStretch(1)
        scroll.setWidget(inner)
        self.add(scroll, 1)

        # FRIENDLY AND ILLUSTRATED (UI panel 2026-10-21 polish): the game's
        # icon, what will show here and how it gets there
        self._empty = EmptyState(gameicons.pixmap("items", "Treat", 40),
                                 "No timers yet",
                                 "Dispensers, bosses and boosts show a countdown here after the bot has used them once.")
        self._list.insertWidget(0, self._empty)

        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._resort)
        self._ticker.start(10_000)

    def update_timer(self, timer: TimerEvent) -> None:
        if self._empty is not None:
            self._list.removeWidget(self._empty)
            self._empty.setParent(None)
            self._empty.deleteLater()
            self._empty = None

        row = self._rows.get(timer.id)
        if row is None:
            row = TimerRow(timer)
            self._rows[timer.id] = row
            self._list.insertWidget(self._list.count() - 1, row)
        else:
            row.update_from(timer)
        self._resort()

    def _resort(self) -> None:
        for row in sorted(self._rows.values(), key=lambda r: r.deadline):
            self._list.removeWidget(row)
            self._list.insertWidget(self._list.count() - 1, row)
        now = time.time()
        ready = sum(1 for r in self._rows.values() if r.deadline <= now)
        self.set_badge(f"{ready} ready" if ready else str(len(self._rows)),
                       theme.GOOD if ready else theme.ACCENT)

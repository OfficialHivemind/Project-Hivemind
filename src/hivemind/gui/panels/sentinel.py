"""The Expiry Sentinel: everything that will be lost if nobody acts.

The beequip inbox, the nectar condense window, field boosters, an uncollected
Wealth Clock -- these look like different problems and are one: a resource that
disappears on a timer with no in-game warning.

Durations come from `economy/sentinel.py` and the data file behind it, where
every one is currently marked UNVERIFIED. The panel shows them anyway, with the
hedge carried in the detail line, because warning you about a possible loss
costs nothing if the timing is an hour out. What the engine will NOT do on an
unverified deadline is consume anything by itself -- it raises a question
instead. This panel renders that distinction rather than deciding it.

Sorted by how soon, coloured by severity, and showing what each loss would cost
in honey, so "3 beequips" and "3 beequips worth 11M" never look the same.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from ...telemetry.events import Expiry
from .. import theme
from .. import gameicons
from ..widgets import Card, Countdown, EmptyState, human_number

# a shape for each, not a colour alone (UI panel 2026-10-21, colourblind)
SEVERITY_SHAPES = {"critical": ("▲", "urgent"), "warn": ("◆", "soon"), "info": ("●", "for your information")}
SEVERITY_COLOURS = {
    "critical": theme.BAD,
    "warn": theme.WARN,
    "info": theme.INFO,
}


class ExpiryRow(QWidget):
    def __init__(self, item: Expiry, parent=None):
        super().__init__(parent)
        self.id = item.id
        self.item = item
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 5, 6, 5)
        row.setSpacing(9)

        self._dot = QLabel("●")
        row.addWidget(self._dot, 0, Qt.AlignVCenter)

        middle = QVBoxLayout()
        middle.setSpacing(1)
        self._what = QLabel(item.what)
        self._what.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        self._what.setWordWrap(True)       # a long name must not widen the row (2026-10-22)
        middle.addWidget(self._what)
        self._detail = QLabel(item.detail)
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        middle.addWidget(self._detail)
        row.addLayout(middle, 1)

        self._cost = QLabel("")
        self._cost.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-family: {theme.MONO}; font-size: 11px;")
        self._cost.setAlignment(Qt.AlignRight)
        row.addWidget(self._cost)

        self._eta = Countdown(item.at_risk_at, warn_s=3600, critical_s=900)
        self._eta.setFixedWidth(72)
        self._eta.setAlignment(Qt.AlignRight)
        row.addWidget(self._eta)

        self.update_from(item)

    def update_from(self, item: Expiry) -> None:
        self.item = item
        colour = SEVERITY_COLOURS.get(item.severity, theme.TEXT_DIM)
        shape, word = SEVERITY_SHAPES.get(item.severity, ("●", ""))
        self._dot.setText(shape)
        self._dot.setToolTip(word)
        self._dot.setStyleSheet(f"color: {colour}; font-size: 12px;")
        self._what.setText(item.what)
        self._detail.setText(item.detail)
        self._cost.setText(f"−{human_number(item.value)}" if item.value else "")
        self._eta.set_deadline(item.at_risk_at)

    @property
    def deadline(self) -> float:
        return self.item.at_risk_at or float("inf")


class SentinelPanel(Card):
    def __init__(self, parent=None):
        super().__init__("running out soon", "nothing is lost without a warning", parent)
        self._rows: dict[str, ExpiryRow] = {}

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

        # WHY IT IS EMPTY, not merely that it is. The bot sends the reason as
        # a Thought(topic="gap") the moment it starts, and `explain` puts it
        # here -- so a panel with nothing in it tells the owner what is
        # stopping it rather than looking broken. See brain/dashboard.GAPS.
        # FRIENDLY AND ILLUSTRATED (UI panel 2026-10-21 polish): the game's
        # icon, what will show here and how it gets there
        self._empty = EmptyState(gameicons.pixmap("items", "Glitter", 40),
                                 "Nothing at risk",
                                 "If a boost, a planter or a buff is about to run out, it shows here first.")
        self._list.insertWidget(0, self._empty)

        # re-sort on a timer: the ordering is by deadline, and deadlines move
        # even when no new events arrive
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._resort)
        self._ticker.start(10_000)

    def update_expiry(self, item: Expiry) -> None:
        if self._empty is not None:
            self._list.removeWidget(self._empty)
            self._empty.setParent(None)
            self._empty.deleteLater()
            self._empty = None

        row = self._rows.get(item.id)
        if row is None:
            row = ExpiryRow(item)
            self._rows[item.id] = row
            self._list.insertWidget(self._list.count() - 1, row)
        else:
            row.update_from(item)
        self._resort()

    def _resort(self) -> None:
        for row in sorted(self._rows.values(), key=lambda r: r.deadline):
            self._list.removeWidget(row)
            self._list.insertWidget(self._list.count() - 1, row)

        now = time.time()
        urgent = sum(1 for r in self._rows.values()
                     if r.deadline - now < 3600)
        total = sum(r.item.value for r in self._rows.values())
        self.set_badge(str(len(self._rows)) if self._rows else "",
                       theme.BAD if urgent else theme.ACCENT)
        self.set_subtitle(f"{human_number(total)} honey at risk" if total
                          else "nothing is lost silently")

    def drop(self, expiry_id: str) -> None:
        row = self._rows.pop(expiry_id, None)
        if row:
            row.setParent(None)
            row.deleteLater()
        self._resort()

    def explain(self, reason: str) -> None:
        """Say why this panel is empty. Ignored once it has real rows."""
        if self._empty is None or not reason:
            return
        self._empty.line.setText(reason)

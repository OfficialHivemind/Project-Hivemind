"""What the bot currently believes about the account, and how much it trusts it.

This is the visible face of the design's central idea: nothing here is a setting
you typed in. Every row was observed by the bot -- it opened the hive and
counted, it read the quest dialog -- and every row carries how long ago that was.

Showing age matters more than it sounds. A planner acting on "3,333 royal jelly"
that was true two hours ago can spend jelly you no longer have. Anything the bot
is about to act on irreversibly should be re-observed first, and this table is
where you can see whether it has.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QTableWidget,
                               QTableWidgetItem)

from ...telemetry.events import Belief

FRESH_S = 60.0
STALE_S = 900.0        # 15 minutes; past this a value is shown as untrusted


def _age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h ago"
    return f"{seconds / 86400:.1f}d ago"


class BeliefTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["Fact", "Value", "Seen", "Trust"])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setShowGrid(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self._rows: dict[str, int] = {}
        self._beliefs: dict[str, Belief] = {}

    def update_belief(self, belief: Belief) -> None:
        self._beliefs[belief.name] = belief
        if belief.name not in self._rows:
            self._rows[belief.name] = self.rowCount()
            self.insertRow(self.rowCount())
        self._paint(belief)

    def _paint(self, belief: Belief) -> None:
        row = self._rows[belief.name]
        observed = belief.observed_at or belief.at
        age = max(0.0, time.time() - observed)
        stale = age > STALE_S

        name = QTableWidgetItem(belief.name.replace("_", " "))
        name.setForeground(Qt.GlobalColor.white if not stale else Qt.GlobalColor.gray)

        value = QTableWidgetItem(f"{belief.value:,}" if isinstance(belief.value, int)
                                 else str(belief.value))
        value.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        seen = QTableWidgetItem(_age(age))
        seen.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        trust = QTableWidgetItem(f"{belief.confidence * 100:.0f}%")
        trust.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        for col, item in enumerate((name, value, seen, trust)):
            self.setItem(row, col, item)

    def refresh_ages(self) -> None:
        """Re-render the age column so it ticks without new events."""
        for belief in self._beliefs.values():
            self._paint(belief)

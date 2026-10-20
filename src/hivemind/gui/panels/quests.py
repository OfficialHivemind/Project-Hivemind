"""Quest progress, grouped by who gave it.

Quests are where a Bee Swarm account actually progresses, and they are the part
existing macros skip. Two chains matter more than the rest and neither is
automated by anything else:

    Science Bear   gates the Translator
    Spirit Bear    gates Windy Bee

Both are long multi-step chains, which is precisely why nobody bothers -- and
precisely why a bot that can hold state across hours is worth having.

Each row shows the step, a progress bar and an ETA. The ETA is the honest part:
it comes from the bot's own measured gather rate, so "44m" means 44 minutes at
the rate it is currently achieving, not a number from a wiki. When the rate is
unknown the ETA is blank rather than guessed.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from ...telemetry.events import QuestStep
from .. import theme
from .. import gameicons
from ..widgets import Card, EmptyState, Meter, Pill, human_duration

# Givers whose chains gate something structural, so they are worth flagging.
GATING = {
    "Science Bear": "gates the Translator",
    "Spirit Bear": "gates Windy Bee",
}


class QuestRow(QWidget):
    def __init__(self, quest: QuestStep, parent=None):
        super().__init__(parent)
        self.giver = quest.giver
        self.complete = False
        self.setStyleSheet("background: transparent;")
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 5, 6, 5)
        box.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._giver = QLabel(quest.giver)
        self._giver.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        head.addWidget(self._giver)

        self._gate = Pill("", theme.ACCENT)
        head.addWidget(self._gate)
        head.addStretch(1)

        self._eta = QLabel("")
        self._eta.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-family: {theme.MONO}; font-size: 11px;")
        head.addWidget(self._eta)
        box.addLayout(head)

        self._step = QLabel(quest.step)
        self._step.setWordWrap(True)
        self._step.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        box.addWidget(self._step)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._meter = Meter(0.0, colour=theme.ACCENT)
        bar.addWidget(self._meter, 1)
        self._counts = QLabel("")
        self._counts.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-family: {theme.MONO}; font-size: 10px;")
        self._counts.setMinimumWidth(96)
        self._counts.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bar.addWidget(self._counts)
        box.addLayout(bar)

        self._reward = QLabel("")
        self._reward.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        box.addWidget(self._reward)

        self.update_from(quest)

    def update_from(self, quest: QuestStep) -> None:
        # The quest menu gives a heading, not a bear. Show the heading rather
        # than an empty line where a name would be.
        self._giver.setText(quest.giver or "from the quest menu")
        self._step.setText(quest.step)

        gate = GATING.get(quest.giver, "")
        self._gate.setText(gate)
        self._gate.setVisible(bool(gate))

        # THE SCREEN'S OWN WORD WINS. The menu writes "Complete!" on steps
        # that carry no count -- "Collect 150,000 Pollen from the Strawberry
        # Field. Complete!" had no readable total for a while -- and a step
        # the game calls finished must not be drawn as an empty bar. The
        # owner reported the other half of this: "quests section ive done
        # parts of them but it shows 0/(whatever value is on quest) on them
        # even tho ive done some".
        counted = quest.done / quest.total if quest.total else 0.0
        # COUNT >= TARGET, not 99.9%: 999,999,999,998 of 999,999,999,999
        # read "all done" (UI render pass 2026-10-21)
        self.complete = bool(quest.complete) or (
            bool(quest.total) and quest.done >= quest.total)
        fraction = 1.0 if self.complete else counted
        colour = theme.GOOD if self.complete else theme.ACCENT
        self._meter.set_value(fraction, colour)
        # A step with no numbers at all is still a real step. It gets an empty
        # bar rather than being hidden, because a quest list that silently
        # omits its unmeasurable parts reads as shorter than it is.
        if quest.total:
            self._counts.setText(f"{quest.done:,.0f}/{quest.total:,.0f}")
        else:
            self._counts.setText("done" if self.complete else "—")

        # Blank rather than guessed: an ETA the bot cannot compute is worse than
        # no ETA, because it looks like knowledge.
        # CAPPED: "104166d" was a rate near zero, not a forecast
        self._eta.setText("" if quest.eta_s <= 0 else
                          "over a week" if quest.eta_s > ETA_CAP_S else
                          human_duration(quest.eta_s, short=True))
        self._reward.setText(f"reward: {quest.reward}" if quest.reward else "")
        self._reward.setVisible(bool(quest.reward))


ETA_CAP_S = 7 * 86400


class QuestsPanel(Card):
    def __init__(self, parent=None):
        super().__init__("quests", "where progression actually comes from", parent)
        self._rows: dict[str, QuestRow] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(2)
        self._list.addStretch(1)
        scroll.setWidget(inner)
        self.add(scroll, 1)

        # FRIENDLY AND ILLUSTRATED (UI panel 2026-10-21 polish): the game's
        # icon, what will show here and how it gets there
        self._empty = EmptyState(gameicons.pixmap("items", "Ticket", 40),
                                 "No quests yet",
                                 "With Take quests on, the bot talks to the bears. Each quest and how far along it is shows here.")
        self._list.insertWidget(0, self._empty)

    def update_quest(self, quest: QuestStep) -> None:
        # NO GIVER IS NOT NO QUEST. This used to read `if not quest.giver:
        # return`, and the quest MENU does not name the bear who gave a quest
        # -- so every event was dropped and this panel stayed empty all night
        # while `var/quests.json` filled up with real readings. The owner spotted
        # it: "the quests arnt being picked up on". A row is keyed on the step,
        # which is the thing the screen actually gives.
        key = f"{quest.giver}|{quest.step}"
        if not key.strip("|"):
            return
        if self._empty is not None:
            self._list.removeWidget(self._empty)
            self._empty.setParent(None)
            self._empty.deleteLater()
            self._empty = None

        row = self._rows.get(key)
        if row is None:
            row = QuestRow(quest)
            self._rows[key] = row
            self._list.insertWidget(self._list.count() - 1, row)
        else:
            row.update_from(quest)
        # The badge counts what is still OUTSTANDING, because "12 quests" when
        # nine of them are finished is a worse number than no number.
        left = sum(1 for r in self._rows.values() if not r.complete)
        self.set_badge(f"{left} left" if left else "all done")

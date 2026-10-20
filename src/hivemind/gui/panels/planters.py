"""Planters: growth, field health, and the engine's harvest call.

Each row shows two numbers rather than one -- how close the planter is to done,
and how healthy the field is -- because if field degradation is real, those two
can disagree and the disagreement is the decision.

IMPORTANT: this panel decides nothing. The verdict text comes straight from
`tasks.planters.decide()`, which currently waits for 100% on every planter
because field degradation is UNVERIFIED (docs/DESIGN.md 8a). Until the measuring
experiment has been run, "field health" is displayed as an observation, not as
something acting on you. A panel that rendered its own opinion would be a second
implementation of the rule, free to disagree with the one the bot follows.

The health meter carries a tick at 50% -- the floor the engine WOULD use if the
mechanic is confirmed -- so the display is ready for the measurement either way.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from ...telemetry.events import Planter
from .. import theme
from .. import gameicons
from ..widgets import Card, Countdown, EmptyState, Meter, Pill, Ring, human_number

HEALTH_FLOOR = 0.50        # below this, replanting the field stops paying

SEED_COLOURS = {
    "Paper": "#d4d4d8", "Ticket": "#fbbf24", "Festive": "#f87171",
    "Petal": "#f9a8d4", "Pine": "#4ade80", "Stick": "#a3a3a3",
    "Plenty": "#60a5fa", "Blue Clay": "#60a5fa", "Red Clay": "#f87171",
    "Pesticide": "#a78bfa", "Heat-Treated": "#fb923c",
}


def seed_colour(seed: str) -> str:
    for key, colour in SEED_COLOURS.items():
        if key.lower() in seed.lower():
            return colour
    return theme.TEXT_DIM


class GrowCountdown(Countdown):
    """'grown' at the deadline, never 'ready': ready to harvest is the
    engine's call (harvest_now), and the header counts that. A row saying
    "ready" under a "none to harvest yet" header contradicted it (usability
    triage 2026-10-27 #10: the timer passed, the last verdict still waits)."""

    def refresh(self) -> None:
        super().refresh()
        if self.text() == "ready":
            self.setText("grown")


class PlanterRow(QWidget):
    def __init__(self, planter: Planter, parent=None):
        super().__init__(parent)
        self.id = planter.id
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 5, 4, 5)
        row.setSpacing(10)

        self._ring = Ring(44)
        row.addWidget(self._ring, 0, Qt.AlignVCenter)

        middle = QVBoxLayout()
        middle.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._seed = QLabel(planter.seed)
        self._seed.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        self._seed.setMinimumWidth(0)
        head.addWidget(self._seed)
        self._field = Pill(planter.field, theme.INFO)
        head.addWidget(self._field)
        self._nectar = Pill(planter.nectar or "—", theme.TEXT_FAINT)
        self._nectar.setVisible(bool(planter.nectar))
        head.addWidget(self._nectar)
        head.addStretch(1)
        middle.addLayout(head)
        # ITS OWN WRAPPED LINE, not 22 characters in the head: the cut text
        # read as "ready" on every row (UI panel round 2, 2026-10-22)
        self._verdict = QLabel("")
        self._verdict.setWordWrap(True)
        middle.addWidget(self._verdict)

        # No "field health" caption: the row is narrow, and a labelled meter
        # with its own percentage beside it is already unambiguous. The tooltip
        # carries the word for anyone unsure.
        health_row = QHBoxLayout()
        health_row.setSpacing(8)
        self._health = Meter(planter.field_health, threshold=HEALTH_FLOOR)
        self._health.setToolTip(
            "Field health. The tick marks the 50% floor the engine would use "
            "if field degradation is confirmed.")
        health_row.addWidget(self._health, 1)
        self._health_value = QLabel("")
        self._health_value.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 12px;")   # not MONO: it has no ✓ or ⚠
        self._health_value.setFixedWidth(52)
        self._health_value.setAlignment(Qt.AlignRight)
        health_row.addWidget(self._health_value)
        middle.addLayout(health_row)
        row.addLayout(middle, 1)

        right_host = QWidget()
        right_host.setFixedWidth(92)          # reserve the countdown column
        right_host.setStyleSheet("background: transparent;")
        right = QVBoxLayout(right_host)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(2)
        self._eta = GrowCountdown(planter.ready_at)
        self._eta.setAlignment(Qt.AlignRight)
        right.addWidget(self._eta)
        self._yield = QLabel("")
        self._yield.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-family: {theme.MONO}; font-size: 12px;")
        self._yield.setAlignment(Qt.AlignRight)
        right.addWidget(self._yield)
        row.addWidget(right_host)

        self.update_from(planter)

    def update_from(self, planter: Planter) -> None:
        colour = seed_colour(planter.seed)
        self._ring.set_value(planter.growth, colour=colour)
        self._seed.setText(planter.seed)
        # a long field name is shortened, not cut (render probe 2026-10-22)
        self._field.setText(self._field.fontMetrics().elidedText(planter.field, Qt.ElideRight, 130))
        self._field.setToolTip(planter.field)
        self._nectar.setText(planter.nectar or "")
        self._nectar.setVisible(bool(planter.nectar))
        self._eta.set_deadline(planter.ready_at)
        self._yield.setText(f"~{human_number(planter.yield_estimate)}")

        health = planter.field_health
        health_colour = (theme.GOOD if health >= 0.75 else
                         theme.WARN if health >= HEALTH_FLOOR else theme.BAD)
        self._health.set_value(health, health_colour)
        # a shape as well as the colour (colourblind reader, 2026-10-22)
        self._health_value.setText(f"{'✓' if health >= 0.75 else '⚠'} {health * 100:.0f}%")

        # Display the engine's call verbatim. The GUI deliberately does NOT
        # decide anything here: tasks.planters.decide() owns that, and a second
        # copy of the rule in a widget is a copy that can silently disagree with
        # the one the bot is actually following.
        # The engine's reasons are written to be read, not to fit a column, so
        # the row shows the head of it and the tooltip carries the whole thing.
        short = planter.verdict
        if len(short) > 90:                       # two lines at most
            short = short[:89].rstrip(" ,;—-") + "…"
        self._verdict.setText(("✓ " if planter.harvest_now else "") + short)
        self._verdict.setToolTip(planter.verdict if short != planter.verdict else "")
        self._verdict.setStyleSheet(
            f"color: {theme.GOOD if planter.harvest_now else theme.TEXT_DIM};"
            f" font-size: 12px; font-weight: {'600' if planter.harvest_now else '400'};")


class PlanterPanel(Card):
    def __init__(self, parent=None):
        super().__init__("planters", "field health drives the schedule", parent)
        self._rows: dict[str, PlanterRow] = {}
        self._latest: dict[str, Planter] = {}

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

        # WHY A FIELD HAS NO PLANTER, one line each, from the 24 h plan
        # (brain/nectarplan.unplaced): "no planter placed in Pine Tree because..."
        self._unplaced = QLabel("")
        self._unplaced.setWordWrap(True)
        self._unplaced.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        self._unplaced.setVisible(False)
        self.add(self._unplaced)

        # WHY IT IS EMPTY, not merely that it is. The bot sends the reason as
        # a Thought(topic="gap") the moment it starts, and `explain` puts it
        # here -- so a panel with nothing in it tells the owner what is
        # stopping it rather than looking broken. See brain/dashboard.GAPS.
        # FRIENDLY AND ILLUSTRATED (UI panel 2026-10-21 polish): the game's
        # icon, what will show here and how it gets there
        self._empty = EmptyState(gameicons.pixmap("items", "Sunflower Seed", 40),
                                 "No planters down",
                                 "With Manage planters on, the bot plants seeds in fields and harvests them for nectar and honey.")
        self._list.insertWidget(0, self._empty)

    def update_planter(self, planter: Planter) -> None:
        if self._empty is not None:
            self._list.removeWidget(self._empty)
            self._empty.setParent(None)
            self._empty.deleteLater()
            self._empty = None

        self._latest[planter.id] = planter
        row = self._rows.get(planter.id)
        if row is None:
            row = PlanterRow(planter)
            self._rows[planter.id] = row
            self._list.insertWidget(self._list.count() - 1, row)
        else:
            row.update_from(planter)

        self.set_badge(str(len(self._rows)))
        ready = sum(1 for p in self._latest.values() if p.harvest_now)
        # Describes what the engine decided, not a judgement invented here.
        self.set_subtitle(f"{ready} ready to harvest" if ready
                          else "none to harvest yet")

    def set_unplaced(self, text: str) -> None:
        """The plan's reasons a field has no planter, shown under the rows."""
        self._unplaced.setText("\n".join(f"• {line}" for line in text.splitlines() if line))
        self._unplaced.setVisible(bool(text.strip()))

    def explain(self, reason: str) -> None:
        """Say why this panel is empty. Ignored once it has real rows."""
        if self._empty is None or not reason:
            return
        self._empty.line.setText(reason)

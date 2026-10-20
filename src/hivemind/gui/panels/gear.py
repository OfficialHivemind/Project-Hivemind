"""The gear goals: what they asked for, what it costs, how far off, what next.

THEIR REQUEST: a list of gear goals (for example the Honey Mask and the rest
of the badge-tier equipment). One row per goal, in THEIR order (`goals.order`):

    item · shop · state                                   ETA
    cost, the honey there is, and how much is still short
    [honey bar]
    materials: have/need each, "?" where the bot cannot know
    next step, in words

EVERY NUMBER IS `brain.goals`'s, which is also what the bot plans with and the
morning report prints, so the three cannot disagree. The honey is the bot's
last HUD reading while it is connected, and otherwise the last confirmed
convert in `var/trips.jsonl` -- the subtitle says which, and when. A count the
bot has never seen is drawn as "?", never as 0: the whole point of the panel is
that the owner can catch it being wrong.

OWNED HAS TWO KINDS, DRAWN APART (DESIGN 8ea): "owned" is their word -- in
Settings or on a card -- and "owned? (inferred)" is what the honey balance
says they bought (`brain/owned`), in another colour, with the evidence on the
row and a card in the Decision Inbox asking them to confirm it.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from ...brain import goals as goals_plan
from .. import theme
from ..widgets import Card, Meter, Pill, human_number

STATE_COLOUR = {
    goals_plan.OWNED: theme.GOOD,
    goals_plan.READY: theme.GOOD,
    goals_plan.HONEY_READY: theme.ACCENT,
    goals_plan.SAVING: theme.INFO,
    goals_plan.BLOCKED: theme.WARN,
    goals_plan.UNKNOWN: theme.TEXT_DIM,
}
# An inferred goal is owned for the plan's sake and not yet for theirs: yellow,
# the colour the panel already spends on "the honey is there, check".
INFERRED_COLOUR = theme.ACCENT


class GearRow(QWidget):
    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 6, 6, 6)
        box.setSpacing(3)
        colour = (INFERRED_COLOUR if row.owned and row.owned_how == "inferred"
                  else STATE_COLOUR.get(row.state, theme.TEXT_DIM))

        head = QHBoxLayout()
        head.setSpacing(6)
        name = QLabel(row.label)
        name.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        head.addWidget(name)
        # NOT THEIR GOAL: the research's next one after their list (brain/progression)
        head.addWidget(Pill(row.origin, theme.INFO) if row.origin
                       else Pill(row.shop_label, theme.TEXT_DIM))
        head.addWidget(Pill(row.state_text, colour))
        head.addStretch(1)
        eta = QLabel(goals_plan.hours_text(row.eta_hours)
                     if row.eta_hours else "")
        eta.setToolTip("at the honey rate the bot measured, counting the "
                       "goals above this one first")
        eta.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-family: {theme.MONO}; font-size: 11px;")
        head.addWidget(eta)
        box.addLayout(head)

        money = QLabel(self._money_line(row))
        money.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-family: {theme.MONO}; font-size: 11px;")
        box.addWidget(money)

        if not row.owned:
            # TOWARDS THIS GOAL IN THEIR ORDER, like the "short" beside it: the
            # honey held over the honey held plus what is still missing,
            # counting the goals above it.
            have = row.honey
            fraction = (min(1.0, have / (have + row.queue_short))
                        if have is not None and row.queue_short else
                        1.0 if have is not None else 0.0)
            box.addWidget(Meter(fraction, colour=colour))

        if row.needs and not row.owned:
            mats = QLabel("materials: " + ", ".join(n.describe() for n in row.needs))
            mats.setWordWrap(True)
            mats.setToolTip("\n".join(
                f"{n.label}: {n.need:,} needed; "
                + (f"{n.have:,} towards it ({n.have_from})" if n.have is not None
                   else "count unknown")
                + (f" — {n.where(limit=6)}" if n.where() else "")
                for n in row.needs))
            mats.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
            box.addWidget(mats)

        if row.next_step and (not row.owned or row.owned_how == "inferred"):
            step = QLabel(row.next_step)
            step.setWordWrap(True)
            step.setTextInteractionFlags(Qt.TextSelectableByMouse)
            step.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
            box.addWidget(step)
        self.setToolTip(f"{row.label}: {row.gate}\n{row.source}"
                        + (f"\nowned — {row.owned_why}" if row.owned else ""))

    @staticmethod
    def _money_line(row) -> str:
        if row.owned:
            return ("owned? — the bot's inference from your honey, not your "
                    "word yet" if row.owned_how == "inferred"
                    else f"owned — {row.owned_why or 'you said so'}")
        line = f"{row.cost:,} honey"
        if row.honey is None:
            return line + " — honey not read"
        if row.queue_short:
            line += f" — short {row.queue_short:,}"
            if row.short != row.queue_short:
                line += " counting the goals above it"
        else:
            line += " — the honey is there"
        return line


class GearGoalsPanel(Card):
    """The owner's gear goals, from `brain.goals.from_files`."""

    hive_changed = Signal(str)          # the progression's colour, picked here

    def __init__(self, parent=None):
        super().__init__("gear goals", "what you asked for, and how far off",
                         parent)
        # WHERE THE ACCOUNT IS and the next three goals (brain/progression),
        # beside the hive colour the progression follows (progression.hive)
        from ...brain.progression import HIVES
        top = QHBoxLayout()
        self._stage = QLabel("")
        self._stage.setWordWrap(True)
        self._stage.setTextFormat(Qt.RichText)
        self._stage.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        top.addWidget(self._stage, 1)
        self._hive = QComboBox()
        self._hive.addItems(list(HIVES))
        self._hive.setToolTip("Hive colour for progression (Settings › Progression)")
        self._hive.currentTextChanged.connect(self.hive_changed)
        top.addWidget(self._hive, 0, Qt.AlignTop)
        self.add_layout(top)
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
        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        self.add(self._note)
        self._rows: list = []
        self.plan = None

    def _show_progress(self, prog) -> None:
        stage = getattr(prog, "stage", None)
        if prog is not None and self._hive.currentText() != prog.hive:
            self._hive.blockSignals(True)
            self._hive.setCurrentText(prog.hive)
            self._hive.blockSignals(False)
        if not (stage and stage.id):
            self._stage.setText("stage: not worked out (the progression file could not be read)")
            return
        from html import escape
        lines = [f"<b style='color:{theme.ACCENT}'>stage: {escape(stage.label)}</b>"
                 f" — next, after your list:"]
        for n, item in enumerate(prog.next[:3], 1):
            cost = f"{human_number(item.honey)} honey" if item.honey else item.goal.get("kind", "")
            lines.append(f"{n}. <span style='color:{theme.TEXT}'>{escape(item.label)}</span>"
                         f" · {escape(str(cost))} · {escape(item.stage)}")
        self._stage.setText("<br>".join(lines))
        self._stage.setToolTip("\n\n".join(item.describe() for item in prog.next[:3]))

    def show_plan(self, plan) -> None:
        self.plan = plan                 # the Materials page draws the same plan (G11)
        for widget in self._rows:
            self._list.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._rows = []
        if plan is None:
            self._note.setText("the goal list could not be read")
            return
        self._show_progress(getattr(plan, "progress", None))
        for row in plan.rows:
            widget = GearRow(row)
            self._rows.append(widget)
            self._list.insertWidget(self._list.count() - 1, widget)

        when = (time.strftime("%d %b %H:%M", time.localtime(plan.honey_at))
                if plan.honey_at else "")
        honey = (f"{human_number(plan.honey)} honey ({plan.honey_from}"
                 + (f", {when}" if when else "") + ")"
                 if plan.honey is not None else "honey not read")
        rate = (f"{human_number(plan.rate.per_hour)}/h measured"
                if plan.rate else "no honey rate measured yet")
        self.set_subtitle(f"{honey} · {rate}")
        ready = len(plan.ready())
        self.set_badge(f"{ready} ready" if ready else "", theme.GOOD)

        notes = ["The bot buys the next Hive Slot itself, with honey and never "
                 "Robux; any other ready goal is yours to buy, and the bot sees "
                 "it bought from your honey or the shop's window."]
        if plan.rate:
            notes.append(f"Rate: {plan.rate.describe()}.")
        if plan.unknown_names:
            notes.append("Not goals this list knows: "
                         + ", ".join(plan.unknown_names)
                         + " (Settings › Goals › Gear to work towards).")
        if plan.unread_counts:
            notes.append("Could not read these counts: "
                         + ", ".join(plan.unread_counts)
                         + " (Settings › Goals › Materials you hold — e.g. "
                         "treats=1200).")
        self._note.setText(" ".join(notes))

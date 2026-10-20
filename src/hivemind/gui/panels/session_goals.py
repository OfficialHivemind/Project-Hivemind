"""The Goals tab's 'Session goals' card (ROADMAP G9): a horizon, a few goals,
and Check -- each goal's YES / LIKELY / NO with its ETA and reason, from the
measured rates (brain/session_goals). Saved to var/session_goals.json; while
the horizon lasts its items go first in the goals order."""
from __future__ import annotations

import re

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                               QListWidget, QPushButton)

from ...brain import session_goals as sg
from .. import theme
from ..widgets import Card

KINDS = ("Honey", "Item", "Quest")
_UNITS = {"": 1, "k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def honey_amount(text: str) -> float | None:
    """'500M', '2.5b', '750,000,000' -> a number; None when it is not one."""
    m = re.fullmatch(r"\s*([\d.,]+)\s*([kmbt]?)\s*", str(text or "").lower())
    try:
        return float(m[1].replace(",", "")) * _UNITS[m[2]] if m else None
    except ValueError:
        return None


def goal_text(goal: dict) -> str:
    if goal.get("kind") == "honey":
        return f"{sg.short_number(float(goal.get('amount') or 0))} honey"
    if goal.get("kind") == "item":
        return goal.get("name", "")
    return f"{str(goal.get('giver', '')).title()} quest"


class SessionGoalsPanel(Card):
    def __init__(self, var_root=None, settings=None, parent=None):
        super().__init__("session goals", "set goals, it tells you if they're possible",
                         parent)
        self._var, self._settings = var_root, settings
        saved = sg.load(var_root)
        self.goals: list = list(saved.get("goals") or [])
        top = QHBoxLayout()
        top.addWidget(QLabel("Hours"))
        self.hours = QDoubleSpinBox()
        self.hours.setProperty("read_on_click", "Check")   # read by Check, not on change
        self.hours.setRange(0.5, 72.0)
        self.hours.setSingleStep(1.0)
        self.hours.setValue(float(saved.get("hours") or 8))
        top.addWidget(self.hours)
        self.kind = QComboBox()
        self.kind.addItems(KINDS)
        self.kind.currentTextChanged.connect(self._fill_values)
        top.addWidget(self.kind)
        self.value = QComboBox()
        self.value.setProperty("read_on_click", "Add")     # read by Add, not on change
        self.value.setMinimumWidth(160)
        top.addWidget(self.value, 1)
        add = QPushButton("Add")
        add.clicked.connect(self.add_goal)
        top.addWidget(add)
        self.add_layout(top)
        self.list = QListWidget()
        self.list.setMaximumHeight(90)
        self.add(self.list)
        buttons = QHBoxLayout()
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_goal)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        self.check_button = QPushButton("Check")
        self.check_button.clicked.connect(self.check)
        buttons.addWidget(self.check_button)
        self.add_layout(buttons)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self.add(self.result)
        self._fill_values(self.kind.currentText())
        self._show_list()

    def _fill_values(self, kind: str) -> None:
        self.value.clear()
        self.value.setEditable(kind == "Honey")
        if kind == "Honey":
            self.value.addItems(["500M", "1B", "5B"])
        elif kind == "Item":
            from ...brain import goals
            self.value.addItems([(b or {}).get("label") or k for k, b in
                                 (goals.load().get("goals") or {}).items()])
        else:
            from ...brain.questneeds import QUEST_GIVERS
            self.value.addItems([g.replace("_", " ") for g in QUEST_GIVERS])

    def _show_list(self) -> None:
        self.list.clear()
        self.list.addItems([goal_text(g) for g in self.goals])

    def add_goal(self) -> None:
        kind, text = self.kind.currentText(), self.value.currentText().strip()
        if kind == "Honey":
            amount = honey_amount(text)
            if not amount:
                self.result.setText(f"'{text}' is not an amount (try 500M or 2B).")
                return
            goal = {"kind": "honey", "amount": amount}
        elif kind == "Item":
            goal = {"kind": "item", "name": text}
        else:
            goal = {"kind": "quest", "giver": text}
        if text:
            self.goals.append(goal)
            self._show_list()

    def remove_goal(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.goals):
            del self.goals[row]
            self._show_list()

    def check(self) -> list:
        """Save the session (its horizon starts now) and show the verdicts."""
        hours = self.hours.value()
        try:
            sg.save({"hours": hours, "goals": self.goals}, self._var)
        except OSError as exc:
            self.result.setText(f"Could not save: {exc}")
            return []
        if not self.goals:
            self.result.setText("No goals: add one, then Check.")
            return []
        verdicts = sg.feasibility(self.goals, hours, self._var, self._settings)
        self.result.setText("\n".join(v.text() for v in verdicts))
        return verdicts

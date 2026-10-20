"""AI PROGRESS > MATERIALS: what each gear goal still needs (ROADMAP G11).

THE VIEWER'S ASK (Sonny, Discord #suggestions, 18 Oct): "a checklist for core
ingredients for gear like fruit, glitter". The goals already work this out
('Cobalt Guard: Blue Extract 73/100, Enzymes 16/50, Glitter 9/25'); this
draws it as a checklist, one card per open goal:

    [x] / [ ] / [?]  icon  material   have / need  [bar]  where it comes from   ETA

EVERY NUMBER IS `brain.goals`'s (the plan the window already builds every
30 s, `GearGoalsPanel.plan`): the have is the inventory read, their typed count
or the account file, said in the tooltip; "?" when nobody has seen it, never
0. Where it comes from is `Need.where` -- the goals file's sources, checked
against what the bot can do today (data/knowledge/goals.yaml). The ETA is
only given for a material the bot has MADE itself lately: the Blender's own
crafts in var/blender.json over the last week (`craft_rates`). Nothing else
it does has a measured rate per material, so the rest say so. Read-only.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .. import gameicons, theme

RATE_DAYS = 7.0


def craft_rates(var_root: Path, now: float | None = None, days: float = RATE_DAYS) -> dict:
    """{material: made a day} from the Blender's own record of what it made
    (var/blender.json "made": [at, item, qty]) over the last `days`."""
    now = time.time() if now is None else now
    try:
        made = json.loads((Path(var_root) / "blender.json").read_text()).get("made") or []
    except (OSError, ValueError, AttributeError):
        return {}
    out: dict = {}
    for row in made:
        try:
            at, item, qty = float(row[0]), str(row[1]), int(row[2])
        except (IndexError, TypeError, ValueError):
            continue
        if now - days * 86400 <= at <= now:
            out[item] = out.get(item, 0) + qty
    return {k: v / days for k, v in out.items()}


def eta_text(need, rates: dict) -> str:
    """'about 3 days (Blender, 4.1/day)', '' when met, else why not."""
    if need.met:
        return ""
    if need.have is None:
        return "count unknown"
    rate = rates.get(need.material)
    if not rate:
        return "no rate measured"
    days = need.short / rate
    when = (f"about {days * 24:.0f} h" if days < 2 else f"about {days:.0f} days")
    return f"{when} (Blender, {rate:.1f}/day)"


def icon_name(material: str, label: str) -> str:
    """The game_icons file for a material: its key, its singular, its label."""
    for name in (material, material.rstrip("s"), label):
        if gameicons.has("items", name):
            return name
    return label


class MaterialsPage(QScrollArea):
    """One card per open goal that needs materials; `show_plan(plan)`."""

    def __init__(self, var_root: Path | None = None, parent=None):
        super().__init__(parent)
        if var_root is None:
            from ...datapaths import VAR_ROOT
            var_root = VAR_ROOT
        self.var_root = Path(var_root)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self._box = QVBoxLayout(inner)
        self._box.setContentsMargins(20, 14, 20, 16)
        self._box.setSpacing(10)
        self.head = QLabel()
        self.head.setObjectName("Dim")
        self.head.setWordWrap(True)
        self._box.addWidget(self.head)
        self._box.addStretch(1)
        self.setWidget(inner)
        self.cards: list[QFrame] = []
        self.rows: list[dict] = []          # what each checklist line shows, for tests
        self.show_plan(None)

    def show_plan(self, plan) -> None:
        for card in self.cards:
            self._box.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self.cards, self.rows = [], []
        if plan is None:
            self.head.setText("The goal list has not been read yet.")
            return
        goals = [r for r in plan.rows if not r.owned and r.needs]
        if not goals:
            self.head.setText("None of your open gear goals needs materials. Set goals "
                              "in Settings › Goals, or on the Goals page.")
            return
        rates = craft_rates(self.var_root)
        self.head.setText(
            "What each gear goal still needs, from the same plan the bot works to. "
            "Have: the bot's inventory read, or the count you typed (hover a number). "
            "Where: the bot's own ways to get it first. ETA: only for what the "
            f"Blender has made in the last {RATE_DAYS:.0f} days.")
        for row in goals:
            card = self._card(row, rates)
            self.cards.append(card)
            self._box.insertWidget(self._box.count() - 1, card)

    def _card(self, row, rates: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("SettingCard")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(gameicons.pixmap("items", row.label, 28))
        icon.setFixedSize(28, 28)
        head.addWidget(icon)
        name = QLabel(row.label)
        name.setStyleSheet("font-weight: 700; font-size: 14px;")
        head.addWidget(name)
        done = sum(n.met for n in row.needs)
        count = QLabel(f"{done} of {len(row.needs)} materials ready")
        count.setStyleSheet(f"color: {theme.S_GOOD if done == len(row.needs) else theme.S_DIM};")
        head.addWidget(count)
        head.addStretch(1)
        where = QLabel(" · ".join(x for x in (row.shop_label, row.state_text) if x))
        where.setObjectName("Dim")
        head.addWidget(where)
        box.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for r, need in enumerate(row.needs):
            mark = QLabel("✓" if need.met else "?" if need.have is None else "○")
            mark.setFixedWidth(16)
            mark.setAlignment(Qt.AlignCenter)
            mark.setStyleSheet(f"font-weight: 800; color: "
                               f"{theme.S_GOOD if need.met else theme.S_FAINT if need.have is None else theme.S_AMBER};")
            pic = QLabel()
            pic.setPixmap(gameicons.pixmap("items", icon_name(need.material, need.label), 22))
            pic.setFixedSize(22, 22)
            label = QLabel(need.label[:1].upper() + need.label[1:])
            have = "?" if need.have is None else f"{need.have:,}"
            amount = QLabel(f"{have} / {need.need:,}")
            amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            amount.setStyleSheet("font-weight: 700;" if need.met else "")
            amount.setToolTip(f"{need.have:,} from {need.have_from}" if need.have is not None
                              else "No count yet: the bot has not seen it in the inventory, "
                                   "and none was typed in Settings › Goals.")
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setFixedSize(110, 6)
            bar.setRange(0, max(1, need.need))
            bar.setValue(min(need.need, need.have or 0))
            source = QLabel(need.brief() or "no source on record")
            source.setObjectName("Dim")
            source.setWordWrap(True)
            source.setToolTip(need.where(limit=8))
            eta = QLabel(eta_text(need, rates))
            eta.setObjectName("Dim")
            eta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for col, w in enumerate((mark, pic, label, amount, bar, source, eta)):
                grid.addWidget(w, r, col, Qt.AlignVCenter)
            self.rows.append({"goal": row.label, "material": need.label, "mark": mark.text(),
                              "amount": amount.text(), "where": source.text(),
                              "eta": eta.text()})
        grid.setColumnStretch(5, 1)
        grid.setColumnMinimumWidth(2, 110)
        grid.setColumnMinimumWidth(3, 90)
        grid.setColumnMinimumWidth(6, 120)
        box.addLayout(grid)
        return card


"""Settings > Token priority (Advanced): the player's own token order.

ROADMAP T2, "CUSTOM TOKEN PRIORITIES" (the owner's friend, 2026-10-15: the
user can raise, lower or ignore token types on top of the AI's values), and
a viewer's ask to chase the most wanted tokens first (#suggestions, 23 Oct).

ONE ROW PER TOKEN KIND the bot can name: every kind in
data/knowledge/tokens.yaml, the typed head's kinds (vision/tokentypes) and
"unknown". Per hive colour:
  Weight      the number the token brain starts a token's score from
              (brain/tokenbrain base_for). Until the player saves, it is the
              bot's own -- the same function the bot calls, so the table
              cannot show a number the bot does not use.
  Off         never chased (tokenbrain gates it; a quest's need still wins).
  Suggested   the hive's seed: tokens.yaml `weight_by_hive`, else its
              `priority_by_hive` through the ordering. ASSUMED, every one --
              none has been measured on an account yet (the seeds are
              look-only in the bot, tokenbrain WEIGHTS_LIVE /
              vision/tokens PRIORITY_BY_HIVE_LIVE). "Use the suggestions"
              copies them into the player's table.
Saved whole per hive into settings.yaml (`gather.token_priority`), never into
data/. Reset deletes that hive's rows: the bot's own order again. The bot
reads the table when an attempt starts (run_farm, Kinds.use_own).
"""
from __future__ import annotations

from pathlib import Path

import yaml
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from .. import gameicons, theme
from ...brain.tokenbrain import TokenBrain, base_weight
from ...datapaths import data
from ...vision import tokens, tokentypes
from ...world.settings import TOKEN_HIVES, TOKEN_WEIGHT_MAX

KEY = "gather.token_priority"
COLUMNS = ("Token", "Weight", "Off", "Suggested")


def _table_file(path: Path | None = None) -> dict:
    try:
        body = yaml.safe_load((path or data("knowledge", "tokens.yaml"))
                              .read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return body.get("kinds") or {}


def entries(rows: dict, extra, saved, hive: str) -> list[dict]:
    """The table for a hive, highest weight first: one dict per kind with
    `weight` / `off` (the player's if saved, else the bot's own), `builtin`
    and `suggested` (the hive seed, assumed)."""
    kinds = tokens.Kinds(rows, hive=hive)
    brain = TokenBrain(priority_of=kinds.priority, weight_of=kinds.weight)
    own = {r["kind"]: r for r in saved or () if r.get("hive") == hive}
    out = []
    for kind in dict.fromkeys([*rows, *extra, "unknown"]):
        builtin = brain.base_for(kind)
        seed = kinds.weight(kind)
        by_hive = (rows.get(kind) or {}).get("priority_by_hive") or {}
        if seed is None and hive in by_hive:
            seed = base_weight(kind, lambda _k: by_hive[hive])
        mine = own.get(kind)
        out.append({"kind": kind,
                    "weight": int(round(mine["weight"] if mine else builtin)),
                    "off": bool(mine and mine.get("off")),
                    "builtin": int(round(builtin)),
                    "suggested": int(round(builtin if seed is None else seed)),
                    "seeded": seed is not None})
    out.sort(key=lambda e: (-e["weight"], e["kind"]))
    return out


def _name(kind: str) -> str:
    return "Unnamed token" if kind == "unknown" else kind.replace("_", " ").capitalize()


class TokenPriority(QFrame):
    """The table, its hive picker and its buttons. `save(key, value)` is the
    window's own save path; the setting is saved whole, a copy each time."""

    def __init__(self, values: dict, save, parent=None, table: Path | None = None):
        super().__init__(parent)
        self.setObjectName("Note")
        self._save = save
        self.rows = _table_file(table)
        self.extra = tokentypes.kinds()
        self.saved: list[dict] = [dict(r) for r in values.get(KEY) or []]
        self.shown: list[dict] = []
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("TOKEN PRIORITY")
        title.setObjectName("Section")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(QLabel("Hive colour"))
        self.hive = QComboBox()
        self.hive.addItems([h.capitalize() for h in TOKEN_HIVES])
        hive = str(values.get("progression.hive") or "blue")
        self.hive.setCurrentIndex(TOKEN_HIVES.index(hive) if hive in TOKEN_HIVES else 0)
        self.hive.currentIndexChanged.connect(lambda _i: self._render())
        head.addWidget(self.hive)
        box.addLayout(head)
        sub = QLabel("Which tokens the bot walks to first while gathering. A higher "
                     "weight is chased first and from further away; Off is never "
                     "chased. A token a quest needs still goes first. Suggested "
                     "numbers are the hive's starting guesses (assumed, not yet "
                     "measured). Used from the next attempt.")
        sub.setObjectName("Dim")
        sub.setWordWrap(True)
        box.addWidget(sub)
        self.status = QLabel()
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.SelectedClicked)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, len(COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(320)
        # the Off box as the shell's own check boxes (theme.SHELL styles
        # QCheckBox only; an item's box drew dark on dark, offscreen look)
        self.table.setStyleSheet(
            f"QTableView::indicator {{ width: 14px; height: 14px; border-radius: 3px;"
            f" border: 1px solid {theme.S_FAINT}; }}"
            f"QTableView::indicator:checked {{ background: {theme.S_AMBER};"
            f" border-color: {theme.S_AMBER}; }}")
        self.table.itemChanged.connect(self._edited)
        box.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.up = QPushButton("▲  Up")
        self.down = QPushButton("▼  Down")
        self.suggest = QPushButton("Use the suggestions")
        self.reset = QPushButton("Reset to the bot's order")
        self.up.clicked.connect(lambda: self.move(-1))
        self.down.clicked.connect(lambda: self.move(1))
        self.suggest.clicked.connect(self.use_suggestions)
        self.reset.clicked.connect(self.reset_hive)
        for b in (self.up, self.down):
            buttons.addWidget(b)
        buttons.addStretch(1)
        for b in (self.suggest, self.reset):
            buttons.addWidget(b)
        box.addLayout(buttons)
        self._render()

    # ---- the model ---------------------------------------------------------
    def current_hive(self) -> str:
        return TOKEN_HIVES[max(0, self.hive.currentIndex())]

    def is_custom(self) -> bool:
        hive = self.current_hive()
        return any(r.get("hive") == hive for r in self.saved)

    def _commit(self, table: list[dict]) -> None:
        hive = self.current_hive()
        self.saved = [r for r in self.saved if r.get("hive") != hive] + [
            {"hive": hive, "kind": e["kind"], "weight": int(e["weight"]),
             "off": bool(e["off"])} for e in table]
        self._save(KEY, [dict(r) for r in self.saved])
        self._render()

    def move(self, step: int, kind: str | None = None) -> None:
        """Up (-1) or down (+1) one place: the two rows swap weights; equal
        weights part by one, so the move always shows."""
        kind = kind or self._selected()
        i = next((n for n, e in enumerate(self.shown) if e["kind"] == kind), None)
        if i is None or not 0 <= i + step < len(self.shown):
            return
        table = [dict(e) for e in self.shown]
        a, b = table[i], table[i + step]
        a["weight"], b["weight"] = b["weight"], a["weight"]
        if a["weight"] == b["weight"]:
            a["weight"] = min(TOKEN_WEIGHT_MAX, max(0, a["weight"] - step))
        self._commit(table)
        self._select(kind)

    def use_suggestions(self) -> None:
        self._commit([{**e, "weight": e["suggested"]} for e in self.shown])

    def reset_hive(self) -> None:
        hive = self.current_hive()
        self.saved = [r for r in self.saved if r.get("hive") != hive]
        self._save(KEY, [dict(r) for r in self.saved])
        self._render()

    def show_rows(self, value) -> None:
        """A table saved elsewhere (a preset, the file): shown, not saved."""
        rows = [dict(r) for r in value or []]
        if rows != self.saved:
            self.saved = rows
            self._render()

    # ---- the widget --------------------------------------------------------
    def _selected(self) -> str | None:
        item = self.table.item(self.table.currentRow(), 0)
        return None if item is None else item.data(Qt.UserRole)

    def _select(self, kind: str) -> None:
        for n, e in enumerate(self.shown):
            if e["kind"] == kind:
                self.table.selectRow(n)

    def _icon(self, kind: str) -> QIcon:
        name = (self.rows.get(kind) or {}).get("icon")
        pix = QPixmap(str(data("knowledge", "tokens", "wiki", name))) if name else QPixmap()
        if pix.isNull():
            pix = gameicons.pixmap("items", _name(kind.removeprefix("item_")), 20)
        return QIcon(pix)

    def _render(self) -> None:
        hive = self.current_hive()
        self.shown = entries(self.rows, self.extra, self.saved, hive)
        custom = self.is_custom()
        self.status.setText(
            f"{hive.capitalize()} hive: <b>your own order</b> (saved in your settings)."
            if custom else
            f"{hive.capitalize()} hive: the bot's own order. Change a row to make it yours.")
        self.reset.setEnabled(custom)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self.shown))
            for n, e in enumerate(self.shown):
                name = QTableWidgetItem(self._icon(e["kind"]), _name(e["kind"]))
                name.setData(Qt.UserRole, e["kind"])
                name.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                weight = QTableWidgetItem()
                weight.setData(Qt.EditRole, e["weight"])
                weight.setToolTip(f"The bot's own: {e['builtin']}")
                off = QTableWidgetItem()
                off.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                off.setCheckState(Qt.Checked if e["off"] else Qt.Unchecked)
                seed = QTableWidgetItem(f"{e['suggested']}  (assumed)" if e["seeded"]
                                        else str(e["suggested"]))
                seed.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                seed.setToolTip("From data/knowledge/tokens.yaml for this hive; not "
                                "yet measured on an account" if e["seeded"] else
                                "No hive seed for this token: the bot's own order")
                for col, item in enumerate((name, weight, off, seed)):
                    self.table.setItem(n, col, item)
        finally:
            self.table.blockSignals(False)

    def _edited(self, item: QTableWidgetItem) -> None:
        """A weight typed or an Off ticked: the table as shown, saved whole."""
        table = [dict(e) for e in self.shown]
        row = table[item.row()]
        if item.column() == 1:
            try:
                row["weight"] = min(TOKEN_WEIGHT_MAX, max(0, int(item.data(Qt.EditRole))))
            except (TypeError, ValueError):
                pass
        elif item.column() == 2:
            row["off"] = item.checkState() == Qt.Checked
        else:
            return
        kind = row["kind"]
        # AFTER the edit returns: the commit rebuilds the rows, and deleting
        # the item being edited from inside its own signal is unsafe in Qt.
        QTimer.singleShot(0, lambda: (self._commit(table), self._select(kind)))

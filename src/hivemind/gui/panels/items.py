"""STATS > ITEMS (ROADMAP ITEM-REP): what each item gained and spent per day,
from the inventory's own reads (brain/itemreport). Read when the page is
shown, never while the window is built."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ...brain import itemreport

SHOWN_DAYS = 7              # inventory.json keeps the last 60 reads (about 2-3 days live)


def page_html(var_root) -> str:
    """Per day (newest first), one row per item that moved."""
    reads, labels = itemreport.load(Path(var_root) / "inventory.json")
    if not reads:
        return ("No inventory read yet. The bot reads the inventory about once an hour "
                "on its pad with the bag empty (Settings: goals.read_inventory).")
    days = itemreport.by_day(reads)
    if not days:
        return "No change confirmed yet: a change counts once the next read agrees."
    out = []
    for day in sorted(days, reverse=True)[:SHOWN_DAYS]:
        out.append(f"<h3>{day}</h3><ul>")
        out += [f"<li>{html.escape(line)}</li>" for line in itemreport.day_lines(days[day], labels)]
        out.append("</ul>")
    return "".join(out)


class ItemsPage(QScrollArea):
    def __init__(self, var_root=None, parent=None):
        super().__init__(parent)
        if var_root is None:
            from ...datapaths import VAR_ROOT
            var_root = VAR_ROOT
        self.var_root = Path(var_root)
        self.setWidgetResizable(True)
        inner = QWidget()
        box = QVBoxLayout(inner)
        box.setContentsMargins(20, 16, 20, 16)
        head = QLabel("<b style='font-size:16px'>Items</b><br>What each item gained (+) and "
                      "spent (-) per day, from the inventory reads. A change counts once the "
                      "next read agrees, so a misread number never shows here.")
        head.setWordWrap(True)
        box.addWidget(head)
        again = QPushButton("Refresh")
        again.clicked.connect(self.refresh)
        box.addWidget(again, 0, Qt.AlignLeft)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        box.addWidget(self.body)
        box.addStretch(1)
        self.setWidget(inner)

    def refresh(self) -> None:
        self.body.setText(page_html(self.var_root))

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)

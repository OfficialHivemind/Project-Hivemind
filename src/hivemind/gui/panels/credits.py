"""SETTINGS > CREDITS: who came up with each idea (data/knowledge/credits.yaml).

The owner, 2026-10-21: "a credits tab in hivemind dedicated to showing who
came up with the suggestions". Names only, never Discord IDs. Read-only.
"""
from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .. import theme

STATUS = OrderedDict((("built", ("Built", "✅")), ("testing", ("Testing", "🧪")),
                      ("next", ("Next up", "⏭️")), ("planned", ("Planned", "🗺️")),
                      ("researching", ("Researching", "🔬"))))


def load(path=None) -> list:
    """The credits, built first; [] when the file cannot be read."""
    import yaml
    from ...datapaths import data
    try:
        rows = (yaml.safe_load((path or data("knowledge", "credits.yaml")).read_text())
                or {}).get("credits") or []
    except (OSError, ValueError, AttributeError, yaml.YAMLError):
        return []
    order = list(STATUS)
    rows = [r for r in rows if isinstance(r, dict) and r.get("name") and r.get("idea")]
    return sorted(rows, key=lambda r: (order.index(r.get("status")) if r.get("status") in order
                                       else len(order), str(r.get("date") or "")))


class CreditsPage(QScrollArea):
    def __init__(self, rows=None, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        box = QVBoxLayout(inner)
        box.setContentsMargins(20, 16, 20, 16)
        box.setSpacing(6)
        rows = load() if rows is None else rows
        people = len({r["name"] for r in rows})
        head = QLabel(f"<b style='font-size:16px'>Thank you 🐝</b><br>"
                      f"{len(rows)} ideas from {people} people in the community shaped Hivemind. "
                      f"Got one? Post it in #suggestions on the Discord.")
        head.setWordWrap(True)
        box.addWidget(head)
        for key, (title, icon) in STATUS.items():
            group = [r for r in rows if r.get("status") == key]
            if not group:
                continue
            label = QLabel(f"<b style='color:{theme.ACCENT}'>{icon} {title}</b>")
            label.setContentsMargins(0, 10, 0, 2)
            box.addWidget(label)
            for r in group:
                line = QHBoxLayout()
                name = QLabel(f"<b>{r['name']}</b>")
                # WRAPPED IN ITS OWN 190 px, so a long name no longer runs
                # into the idea beside it (UI panel item 10)
                name.setFixedWidth(190)
                name.setWordWrap(True)
                # left even for a right-to-left name (ابوسوسان sat flush right)
                name.setAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
                name.setTextInteractionFlags(Qt.TextSelectableByMouse)
                idea = QLabel(str(r["idea"]))
                idea.setWordWrap(True)
                line.addWidget(name)
                line.addWidget(idea, 1)
                box.addLayout(line)
        box.addStretch(1)
        self.setWidget(inner)

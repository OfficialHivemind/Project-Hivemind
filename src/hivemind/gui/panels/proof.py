"""STATS > PROGRESS PROOF: every progression step the bot recorded, with how
it knows and a link to the frame that proves it (telemetry/milestones,
var/progression/milestones.jsonl). Read when the page is shown, never while
the window is built."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ...telemetry import milestones

SHOWN_DAYS = 14                     # older days stay in the file and the report tool


def page_html(var_root) -> str:
    """The page's text: per day (newest first) its summary, then its rows."""
    rows = milestones.rows(var_root)
    if not rows:
        return ("Nothing recorded yet. Each purchase, hatch, Royal Jelly roll, quest "
                "hand-in, badge, craft, new bee, gifted bee and honey step the bot makes "
                "is kept here with the frame that shows it.")
    days: dict = {}
    for r in rows:
        days.setdefault(milestones.day_of(r.get("at") or 0), []).append(r)
    out = []
    for day in sorted(days, reverse=True)[:SHOWN_DAYS]:
        said = milestones.summary(var_root, day).split(": ", 2)[-1]
        out.append(f"<h3>{day}</h3><p style='color:gray'>{html.escape(said)}</p><ul>")
        for r in reversed(days[day]):
            frame = str(r.get("frame") or "")
            link = (f" <a href='{Path(frame).as_uri()}'>frame</a>" if frame else " (no frame)")
            out.append(f"<li><b>{datetime.fromtimestamp(r['at']):%H:%M}</b> "
                       f"{html.escape(str(r.get('kind')))}: {html.escape(str(r.get('what')))} "
                       f"<i>{html.escape(str(r.get('proof', '?')).upper())}</i>{link}"
                       f"<br><span style='color:gray'>{html.escape(str(r.get('how') or ''))}"
                       f"</span></li>")
        out.append("</ul>")
    return "".join(out)


class ProofPage(QScrollArea):
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
        # no tools/ path: tools/ is not in the package (usability triage #17)
        head = QLabel("<b style='font-size:16px'>Progress proof</b><br>Each thing the bot "
                      "did, with a screenshot that proves it. PROVEN: it has a picture of "
                      "that moment. LIKELY: no picture, so it is a good guess.")
        head.setWordWrap(True)
        box.addWidget(head)
        again = QPushButton("Refresh")
        again.clicked.connect(self.refresh)
        box.addWidget(again, 0, Qt.AlignLeft)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setOpenExternalLinks(True)
        self.body.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.addWidget(self.body)
        box.addStretch(1)
        self.setWidget(inner)

    def refresh(self) -> None:
        self.body.setText(page_html(self.var_root))

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)

"""STATS > WHY (ROADMAP U3 / L9): each recent trip replayed as a timeline --
the decision that started it (the planner's candidates and their reasons, the
route pick), what happened on the way (route legs, recoveries, why gathering
ended, the convert) and the frames saved while it ran (progress-proof frames
and incident folders). Read-only: it reads var/ when the page is shown and
never moves or presses anything."""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ...telemetry import milestones
from ...telemetry.incidents import tail

# TRIPS SHOWN: the newest few. MEASURED 2026-11-02: the last 300 rows of
# var/trips.jsonl average 13.2 KB each (the planner's candidates and the
# context ride along), so incidents.tail's 256 KB read holds about 19 trips.
SHOWN_TRIPS = 15
CANDIDATES_SHOWN = 3                # the chosen one plus the best two it beat


def _e(x) -> str:
    return html.escape(str(x))


def trips(var_root) -> list:
    """The newest SHOWN_TRIPS rows of var/trips.jsonl, newest first."""
    try:
        text = tail(Path(var_root) / "trips.jsonl", SHOWN_TRIPS + 1)
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue                # the first line of a tail can be cut
        if isinstance(row, dict) and row.get("at"):
            out.append(row)
    return out[::-1][:SHOWN_TRIPS]


def frames_between(var_root, t0: float, t1: float) -> list:
    """(at, label, path) of every frame saved in [t0, t1]: progress-proof
    rows that carry a frame, and incident folders (dated by their
    reason.txt, written last; linked to their LAST frame = the moment)."""
    out = [(float(r["at"]), f"{r.get('kind')}: {r.get('what')}", str(r["frame"]))
           for r in milestones.rows(var_root, since=t0)
           if r.get("frame") and float(r.get("at") or 0) <= t1]
    inc = Path(var_root) / "incidents"
    try:
        folders = list(inc.iterdir())
    except OSError:
        folders = []
    for d in folders:
        try:
            at = (d / "reason.txt").stat().st_mtime
        except OSError:
            continue
        if t0 <= at <= t1:
            shots = sorted(d.glob("*.jpg"))
            out.append((at, d.name.split("-", 2)[-1], str(shots[-1] if shots else d)))
    return sorted(out)


def trip_html(var_root, r: dict) -> str:
    end = float(r["at"])
    start = end - float(r.get("seconds") or 0)
    field = r.get("credited") or r.get("aimed_at") or "?"
    ok = "OK" if r.get("ok") else f"FAILED: {r.get('reason') or '?'}"
    out = [f"<h3>{datetime.fromtimestamp(start):%H:%M}-{datetime.fromtimestamp(end):%H:%M} "
           f"trip {_e(r.get('attempt', '?'))}: {_e(field)} <i>{_e(ok)}</i></h3><ul>"]
    if r.get("chosen"):
        out.append(f"<li><b>Chose</b> {_e(r.get('action') or 'gather')} at "
                   f"{_e(r['chosen'])} (by {_e(r.get('chosen_by') or '?')})<ul>")
        cands = sorted(r.get("candidates") or [], key=lambda c: -float(c.get("score") or 0))
        for c in cands[:CANDIDATES_SHOWN]:
            out.append(f"<li>{_e(c.get('field'))} score {float(c.get('score') or 0):,.0f}"
                       f"<br><span style='color:gray'>{_e(c.get('why') or '')}</span></li>")
        out.append("</ul></li>")
    rc = r.get("route_choice") or {}
    if rc.get("why"):
        out.append(f"<li><b>Route</b> {_e(rc.get('chosen'))}<br>"
                   f"<span style='color:gray'>{_e(rc['why'])}</span></li>")
    for leg in r.get("routes") or []:
        out.append(f"<li>{_e(leg.get('kind'))} {_e(leg.get('route'))}: "
                   f"<b>{_e(leg.get('outcome'))}</b> in {float(leg.get('seconds') or 0):.0f}s</li>")
    if r.get("recoveries"):
        out.append(f"<li>Recoveries: {_e(', '.join(map(str, r['recoveries'])))}</li>")
    out.append(f"<li>Gathered {float(r.get('gather_seconds') or 0):.0f}s, "
               f"{int(r.get('pollen') or 0):,} pollen; ended: {_e(r.get('gather_ended') or '?')}</li>")
    if r.get("convert_note"):
        out.append(f"<li>{_e(r['convert_note'])}</li>")
    shots = frames_between(var_root, start, end)
    for at, label, path in shots:
        out.append(f"<li>{datetime.fromtimestamp(at):%H:%M:%S} frame: {_e(label)} "
                   f"<a href='{Path(path).as_uri()}'>open</a></li>")
    if not shots:
        out.append("<li style='color:gray'>No frames were saved during this trip.</li>")
    out.append("</ul>")
    return "".join(out)


def page_html(var_root) -> str:
    rows = trips(var_root)
    if not rows:
        return "No trips recorded yet. Each trip the bot makes is replayed here with why it went."
    return "".join(trip_html(var_root, r) for r in rows)


class WhyPage(QScrollArea):
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
        head = QLabel("<b style='font-size:16px'>Why</b><br>The last trips, newest first: "
                      "what the AI weighed, why it picked that field and route, what "
                      "happened, and any screenshots saved on the way.")
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

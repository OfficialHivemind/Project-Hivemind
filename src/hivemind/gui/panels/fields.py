"""Every field at a glance, grouped by zone.

Deliberately a grid of cards rather than a map of the mountain. A map would look
better in a screenshot and would be dishonest right now: real field positions
come out of the homography and landmark calibration, and drawing them from
memory would put the bot's "you are here" marker somewhere invented.

What each card shows is what actually drives a routing decision:

    rate        pollen per second, MEASURED by standing in it
    earned      total pollen this field has paid, over how many visits
    mobs        what will interrupt you if you go
    deaths      how often this field has actually killed us
    last seen   how old that information is

IT USED TO SHOW HEALTH AND A TOKEN COUNT AND BOTH WERE CONSTANTS. `health`
defaulted to 1.0 and nothing ever set it, so every card drew a full green bar
-- a grid of invented good news -- and the token line read "0 tokens" for every
field because it was hardcoded. Meanwhile the measured record sat in
`brain.fieldnotes` and was never sent. The owner spotted the result: "the
fields tab isnt linked".

Field degradation is still unverified and nothing counts tokens per field, so
both now arrive as -1 and are simply not drawn. The bar is the measured rate
instead, scaled against the best field on screen, so the comparison a routing
decision actually turns on is the thing you can see.

A field the bot has never visited is drawn faint, so an empty card reads as "not
looked at yet" rather than "nothing there" -- the difference between ignorance
and knowledge is the thing this project is careful about everywhere else, and a
dashboard that blurs it would undo that.
"""
from __future__ import annotations

import json
import time

import yaml
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...datapaths import data, var
from ...telemetry.events import FieldStatus
from .. import theme
from ..widgets import Card, Meter, human_duration

FIELDS_YAML = data("world", "fields.yaml")
COLUMNS = 4
# THE ROUTE BOARD (brain/skills.SkillBook.board), written by the bot after each
# trip; read here on a timer, like the trip ledger panel, so it shows with the
# bot stopped. The worst BOARD_ROWS routes are drawn.
ROUTE_BOARD = var("route_board.json")
BOARD_ROWS = 12
BOARD_REFRESH_MS = 10000


def board_rows(path=ROUTE_BOARD, limit: int = BOARD_ROWS) -> list[list[str]]:
    """The board's cells, worst first: route, last N, share, trend, flag."""
    try:
        body = json.loads(open(path).read())
    except (OSError, ValueError):
        return []
    out = []
    for r in (body.get("routes") or [])[:limit]:
        trend = r.get("trend")
        out.append([str(r.get("route", "")).replace("natro_", "").replace("_via_red_cannon", " (flight)"),
                    f"{r.get('landed', 0)}/{r.get('verdicts', 0)}",
                    f"{float(r.get('rate') or 0):.0%}",
                    "—" if trend is None else f"{float(trend):+.0%}",
                    "quarantined" if r.get("quarantined") else "flagged" if r.get("flagged") else ""])
    return out


class RouteBoard(QTableWidget):
    """Each route's landing share over its last verdicts, worst first."""

    def __init__(self, path=ROUTE_BOARD, parent=None):
        super().__init__(0, 5, parent)
        self.path = path
        self.setHorizontalHeaderLabels(["Route", "Last", "Landed", "Trend", ""])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setShowGrid(False)
        self.setFixedHeight(200)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self._stamp = None
        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(BOARD_REFRESH_MS)

    def refresh(self) -> None:
        try:
            stamp = self.path.stat().st_mtime
        except OSError:
            stamp = None
        if stamp == self._stamp:
            return
        self._stamp = stamp
        rows = board_rows(self.path)
        self.setRowCount(len(rows))
        for i, cells in enumerate(rows):
            for j, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if cells[4]:
                    item.setForeground(Qt.GlobalColor.red if cells[4] == "quarantined"
                                       else Qt.GlobalColor.darkYellow)
                self.setItem(i, j, item)


def load_layout() -> tuple[list[dict], dict[str, dict]]:
    try:
        data = yaml.safe_load(FIELDS_YAML.read_text())
    except (OSError, yaml.YAMLError):
        return [], {}
    zones = data.get("zones", [])
    fields = {f["name"]: f for f in data.get("fields", [])}
    return zones, fields


class FieldCard(QWidget):
    def __init__(self, name: str, colour: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.colour = colour
        self.seen = False
        self.rate = 0.0
        self.setFixedHeight(76)
        self.setStyleSheet(
            f"background: {theme.BG_RAISED}; border-radius: 6px;")

        box = QVBoxLayout(self)
        box.setContentsMargins(9, 7, 9, 7)
        box.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._swatch = QLabel("●")
        self._swatch.setStyleSheet(f"color: {colour}; font-size: 11px;"
                                   " background: transparent;")
        head.addWidget(self._swatch)
        self._name = QLabel(name)
        self._name.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 12px; font-weight: 600;"
            " background: transparent;")
        head.addWidget(self._name, 1)
        self._star = QLabel("")
        self._star.setStyleSheet(f"color: {theme.ACCENT}; font-size: 11px;"
                                 " background: transparent;")
        head.addWidget(self._star)
        box.addLayout(head)

        self._health = Meter(0.0, threshold=0.5, colour=colour, height=4)
        box.addWidget(self._health)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self._counts = QLabel("not visited")
        self._counts.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 10px; background: transparent;")
        foot.addWidget(self._counts, 1)
        self._age = QLabel("")
        self._age.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-family: {theme.MONO};"
            " font-size: 10px; background: transparent;")
        foot.addWidget(self._age)
        box.addLayout(foot)

    def rescale(self, best_rate: float) -> None:
        """Redraw the bar against a new best rate, without new data."""
        share = (self.rate / best_rate) if best_rate > 0 else 0.0
        colour = (theme.GOOD if share >= 0.75 else
                  theme.WARN if share >= 0.35 else theme.BAD)
        self._health.set_value(min(1.0, share),
                               colour if self.rate else theme.BG)

    def update_from(self, status: FieldStatus, best_rate: float = 0.0) -> None:
        self.seen = True
        self.rate = float(getattr(status, "rate", 0.0) or 0.0)
        self._name.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 12px; font-weight: 600;"
            " background: transparent;")
        # THE BAR IS THE MEASURED RATE, against the best field on screen. It
        # used to be `health`, which nothing ever set, so it was a full green
        # bar on every card. A field never stood in shows an empty bar, which
        # is the honest picture: no evidence, not a bad field.
        share = (self.rate / best_rate) if best_rate > 0 else 0.0
        colour = (theme.GOOD if share >= 0.75 else
                  theme.WARN if share >= 0.35 else theme.BAD)
        self._health.set_value(min(1.0, share), colour if self.rate else theme.BG)

        bits = []
        if self.rate:
            bits.append(f"{self.rate:,.0f} pollen/s")
        else:
            bits.append("never measured")
        earned = int(getattr(status, "pollen", 0) or 0)
        visits = int(getattr(status, "visits", 0) or 0)
        if earned:
            bits.append(f"{earned:,} over {visits} visit"
                        f"{'' if visits == 1 else 's'}")
        if status.mobs:
            bits.append(f"{status.mobs} mobs")
        deaths = int(getattr(status, "deaths", 0) or 0)
        if deaths:
            bits.append(f"died here {deaths}x")
        # Health and the token count only appear when something measured them.
        if getattr(status, "health", -1.0) >= 0:
            bits.append(f"{status.health:.0%} health")
        if getattr(status, "tokens", -1) >= 0:
            bits.append(f"{status.tokens} tokens")
        if status.note:
            bits.append(status.note)
        self._counts.setText(" · ".join(bits))
        self._counts.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 10px; background: transparent;")

        if status.last_visited:
            self._age.setText(human_duration(time.time() - status.last_visited,
                                             short=True))
        self._star.setText("★" if status.recommended else "")
        self.setStyleSheet(
            f"background: {theme.BG_RAISED}; border-radius: 6px;"
            + (f" border: 1px solid {theme.ACCENT};" if status.recommended
               else " border: 1px solid transparent;"))


class FieldsPanel(Card):
    def __init__(self, parent=None):
        super().__init__("fields", "health, tokens and what will interrupt you",
                         parent)
        self._cards: dict[str, FieldCard] = {}
        # The measured rate per field, so the bars can be drawn relative to
        # the best one known rather than to an absolute nobody has.
        self._rates: dict[str, float] = {}
        self._best_drawn = 0.0

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)

        zones, fields = load_layout()
        by_zone: dict[str, list[dict]] = {}
        for field in fields.values():
            by_zone.setdefault(field.get("zone", "base"), []).append(field)

        for zone in zones:
            members = by_zone.get(zone["id"], [])
            if not members:
                continue
            heading = QLabel(zone["name"].upper())
            heading.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; font-size: 10px; letter-spacing: 1px;"
                " background: transparent;")
            column.addWidget(heading)

            grid_host = QWidget()
            grid_host.setStyleSheet("background: transparent;")
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(6)
            for index, field in enumerate(members):
                card = FieldCard(field["name"], field.get("colour", theme.TEXT_DIM))
                self._cards[field["name"]] = card
                grid.addWidget(card, index // COLUMNS, index % COLUMNS)
            column.addWidget(grid_host)

        column.addStretch(1)
        scroll.setWidget(inner)
        self.add(scroll, 1)
        heading = QLabel("ROUTES — LANDED OVER THE LAST VERDICTS, WORST FIRST")
        heading.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 10px; letter-spacing: 1px;"
            " background: transparent;")
        self.add(heading)
        self.routes = RouteBoard()
        self.add(self.routes)

        if not self._cards:
            self.set_subtitle("data/world/fields.yaml not found")
        # THE BOT'S NAME FOR EACH CARD (DESIGN 8du). Cards are keyed by the
        # Title Case names in data/world/fields.yaml ("Pine Tree"); the bot
        # sends the world ids ("pine_tree", brain/dashboard.publish_fields).
        # Not one of the 17 matched, so every card said "not visited" all
        # night while the field notes held 37 visits to Pine Tree.
        self._alias = {self._key(name): name for name in self._cards}

    @staticmethod
    def _key(name) -> str:
        return str(name or "").strip().lower().replace(" ", "_")

    def update_field(self, status: FieldStatus) -> None:
        name = self._alias.get(self._key(status.name))
        card = self._cards.get(name) if name else None
        if card is None:
            return
        # THE BAR IS RELATIVE, so every card is redrawn when a new best rate
        # arrives -- otherwise the first field measured would stay a full bar
        # for ever and a better one found later would look the same size.
        self._rates[name] = float(getattr(status, "rate", 0.0) or 0.0)
        best = max(self._rates.values() or [0.0])
        card.update_from(status, best_rate=best)
        if best > self._best_drawn:
            self._best_drawn = best
            for other_name, other in self._cards.items():
                if other.seen and other_name != name:
                    other.rescale(best)
        seen = sum(1 for c in self._cards.values() if c.seen)
        measured = sum(1 for r in self._rates.values() if r > 0)
        self.set_badge(f"{seen}/{len(self._cards)} seen, {measured} measured")

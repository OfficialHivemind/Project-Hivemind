"""The goal web: what the bot wants, drawn as a map with the reasons on it.

THE OWNER ASKED FOR THIS: the AI's goals in the GUI, mapped out in detail and
good-looking, its thoughts as a web, and its priorities.

WHAT IT DRAWS AND WHAT IT REFUSES TO DRAW. Every node comes from
`brain.goalmap.build`, which assembles the graph from the same Ladder and
Planner the bot acts on. Nothing is invented here for the sake of a nicer
picture: if a goal has no price the card says so rather than guessing one, and
if a goal is blocked the card carries the actual blocker text. A diagram that
looked complete while the reasoning underneath had holes in it would be the
worst thing this panel could be, because the whole reason to draw it is so the
owner can catch the bot being wrong.

LAYOUT. The build order is a chain -- each step exists because it unblocks the
next -- so it is drawn as a spine down the middle. Everything else the ladder
wants hangs off to the right as satellites. The node the bot would act on right
now sits at the top in the accent colour, because "what is it doing" is the
question people actually ask first.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ...brain.goalmap import (BLOCKED, DOING, DONE, READY, SKIP,
                              UNKNOWN, GoalMap)
from .. import theme

STATE_COLOUR = {
    DOING: theme.ACCENT,
    READY: theme.GOOD,
    BLOCKED: theme.TEXT_DIM,
    UNKNOWN: theme.INFO,
    DONE: theme.GOOD,
    # A deliberate warning, so it must not look like either an instruction or
    # a thing merely waiting its turn. See brain/goalmap for the Bubble Wand.
    SKIP: theme.WARN,
}
STATE_WORD = {
    DOING: "doing now",
    READY: "ready",
    BLOCKED: "blocked",
    UNKNOWN: "needs looking up",
    DONE: "done",
    SKIP: "DO NOT BUY",
}

CARD_W, CARD_H = 250, 62
GAP_Y = 26
SPINE_X = 40
SATELLITE_X = SPINE_X + CARD_W + 90
PAD = 18


class GoalWeb(QWidget):
    """A node-link view of the bot's goals. Read-only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._map = GoalMap()
        self._places: dict[str, QRectF] = {}
        self.setMinimumHeight(320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)

    # ---- data -------------------------------------------------------------
    def show_map(self, goal_map: GoalMap) -> None:
        self._map = goal_map or GoalMap()
        self._layout()
        self.update()

    def _layout(self) -> None:
        """Place the cards.

        The build order is a chain, so it runs down a spine with the TARGET AT
        THE BOTTOM -- it is the destination, and putting it at the top read as
        though it were the first step. What the bot is doing right now sits
        above everything, and the ladder's other wants sit in a second column
        beside the spine, which is what makes it a web rather than a list.
        """
        self._places.clear()
        nodes = self._map.ordered()
        if not nodes:
            return

        doing = next((n for n in nodes if n.state == DOING), None)
        target = next((n for n in nodes if n.kind == "target"), None)
        chain = [n for n in nodes
                 if n is not doing and n is not target and 1 <= n.priority < 50]
        beside = [n for n in nodes
                  if n is not doing and n is not target and n not in chain]

        top = PAD + 34
        if doing is not None:
            self._places[doing.key] = QRectF(SPINE_X, top, CARD_W, CARD_H)
            top += CARD_H + GAP_Y + 6

        y = top
        for node in chain:
            self._places[node.key] = QRectF(SPINE_X, y, CARD_W, CARD_H)
            y += CARD_H + GAP_Y
        if target is not None:
            self._places[target.key] = QRectF(SPINE_X, y, CARD_W, CARD_H)
            y += CARD_H + GAP_Y

        # The second column starts level with the first chain card, so the two
        # read as parallel tracks rather than one queue.
        sy = top
        for node in beside:
            self._places[node.key] = QRectF(SATELLITE_X, sy, CARD_W, CARD_H)
            sy += CARD_H + GAP_Y

        self.setMinimumHeight(int(max(y, sy) + PAD))
        self.setMinimumWidth(int(SATELLITE_X + CARD_W + PAD))

    # ---- painting ---------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.BG_PANEL))

        if not self._places:
            painter.setPen(QPen(QColor(theme.TEXT_FAINT)))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "no goals yet — the bot has not reported in")
            painter.end()
            return

        self._draw_headline(painter)
        self._draw_edges(painter)
        for node in self._map.ordered():
            rect = self._places.get(node.key)
            if rect is not None:
                self._draw_card(painter, node, rect)
        painter.end()

    def _draw_headline(self, painter: QPainter) -> None:
        if not self._map.headline:
            return
        font = QFont(theme.SANS.split(",")[0], 11, QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QPen(QColor(theme.ACCENT)))
        painter.drawText(QRectF(PAD, PAD - 4, self.width() - PAD * 2, 24),
                         Qt.AlignLeft | Qt.AlignVCenter, self._map.headline)

    def _draw_edges(self, painter: QPainter) -> None:
        pen = QPen(QColor(theme.BORDER), 2)
        painter.setPen(pen)
        for edge in self._map.edges:
            a = self._places.get(edge.before)
            b = self._places.get(edge.after)
            if a is None or b is None:
                continue
            start = QPointF(a.center().x(), a.bottom())
            end = QPointF(b.center().x(), b.top())
            if abs(a.left() - b.left()) > 1:      # spine -> satellite
                start = QPointF(a.right(), a.center().y())
                end = QPointF(b.left(), b.center().y())
            path = QPainterPath(start)
            mid_x = (start.x() + end.x()) / 2
            mid_y = (start.y() + end.y()) / 2
            path.cubicTo(QPointF(start.x(), mid_y), QPointF(mid_x, end.y()), end)
            painter.drawPath(path)

    def _draw_card(self, painter: QPainter, node, rect: QRectF) -> None:
        colour = QColor(STATE_COLOUR.get(node.state, theme.TEXT_DIM))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(theme.BG_RAISED)))
        painter.drawRoundedRect(rect, 8, 8)

        # A state bar down the left edge, so the picture reads at a glance.
        bar = QRectF(rect.left(), rect.top(), 4, rect.height())
        painter.setBrush(QBrush(colour))
        painter.drawRoundedRect(bar, 2, 2)

        if node.state == DOING:
            painter.setPen(QPen(colour, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, 8, 8)

        inner = rect.adjusted(14, 7, -10, -6)
        painter.setFont(QFont(theme.SANS.split(",")[0], 9, QFont.DemiBold))
        painter.setPen(QPen(QColor(theme.TEXT)))
        painter.drawText(QRectF(inner.left(), inner.top(), inner.width(), 16),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         self._elide(painter, node.label, inner.width()))

        painter.setFont(QFont(theme.MONO.split(",")[0], 8))
        painter.setPen(QPen(colour))
        line = node.money or STATE_WORD.get(node.state, node.state)
        painter.drawText(QRectF(inner.left(), inner.top() + 17, inner.width(), 14),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         self._elide(painter, line, inner.width()))

        painter.setFont(QFont(theme.SANS.split(",")[0], 8))
        painter.setPen(QPen(QColor(theme.TEXT_FAINT)))
        detail = node.why or node.detail
        painter.drawText(QRectF(inner.left(), inner.top() + 32, inner.width(), 16),
                         Qt.AlignLeft | Qt.AlignTop,
                         self._elide(painter, detail, inner.width()))

    @staticmethod
    def _elide(painter: QPainter, text: str, width: float) -> str:
        metrics = painter.fontMetrics()
        return metrics.elidedText(str(text or ""), Qt.ElideRight, int(width))

    # ---- the detail the card had no room for ------------------------------
    def mouseMoveEvent(self, event) -> None:
        point = event.position()
        for node in self._map.ordered():
            rect = self._places.get(node.key)
            if rect is not None and rect.contains(point):
                parts = [node.label, STATE_WORD.get(node.state, node.state)]
                if node.money:
                    parts.append(node.money)
                if node.why:
                    parts.append(node.why)
                if node.detail and node.detail != node.why:
                    parts.append(node.detail)
                QToolTip.showText(event.globalPosition().toPoint(),
                                  "\n".join(parts), self)
                return
        QToolTip.hideText()

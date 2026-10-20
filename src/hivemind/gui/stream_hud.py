"""Stream mode's HUD layout: the game fills the canvas, the cards float on it.

THE OWNER, 2026-10-06: "make stream mode better ... it looks boring and too
much like terminal stuff, it should be like the whole screen is like the bots
view plus overlays". So the classic layout -- a 1280x720 picture in a grid of
solid cards -- becomes the whole 1920x1080 frame under:

  - a VIEWFINDER, the bot's eyes: corner brackets and a soft vignette, drawn
    once into a pixmap, and -- while it gathers -- a small targeting reticle on
    the character that turns slowly (only its own square is repainted);
  - GLASS CARDS in the parts of Bee Swarm's screen its own HUD leaves free --
    the honey and pollen counters are top-centre, the menu icons top-left, the
    hotbar bottom-centre and the game's notices bottom-right (gui/stream
    _ToastLayer's survey of a saved frame) -- with the toasts dropping in at
    the top centre, under the counters, as a game's achievements do;
  - a SUBTITLE over the hotbar: the bot's commentary, as a film subtitles it.

Over the key colour (stream.game_view "key colour", DESIGN 8eb) nothing is
translucent -- OBS's Color Key leaves a blend of a card and the green opaque
and green-tinted -- so the cards go solid and the vignette goes (`set_keyed`).
`stream.layout` "classic" keeps the old layout.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QWidget

from . import theme

W, H = 1920, 1080
HONEY = "#ffc42e"                # the HUD's accent: honey, brighter than theme.ACCENT

# WHERE EVERYTHING GOES, (x, y, w, h) on the 1920x1080 canvas.
SIDE_W = 452
LEFT_X, RIGHT_X = 16, W - 16 - SIDE_W           # 16 and 1452
TOP = 168                                        # under the menu icons and the "?"
BOTTOM = 962                                     # right: over the game's notices (~975)
LEFT_BOTTOM = 1056                               # left: nothing of the game's down there
BAR = (1268, 12, 636, 52)                        # right of the honey and pollen
# MEASURED on the owner's screen (21:46): at 216 px RIGHT NOW's DECIDED and THEN
# lines ran into each other, and CHAT PLAYS at 294 piled its sections up (the
# classic layout gave them 248 and 408) -- so taller, the left column to the floor
NOW = (RIGHT_X, TOP, SIDE_W, 258)
FEED = (RIGHT_X, TOP + 258 + 12, SIDE_W, BOTTOM - (TOP + 258 + 12))
STATS = (LEFT_X, TOP, SIDE_W, 200)
PAGER = (LEFT_X, TOP + 200 + 12, SIDE_W, 236)
CHAT = (LEFT_X, PAGER[1] + PAGER[3] + 12, SIDE_W, LEFT_BOTTOM - (PAGER[1] + PAGER[3] + 12))
# two lines of commentary: the lines run 80-140 characters, one line holds ~75
SUBTITLE = (LEFT_X + SIDE_W + 24, 856, W - 2 * (LEFT_X + SIDE_W + 24), 82)   # ends over the hotbar's token count (~945)
TOAST_TOP = 126                                  # under the counters and the game's own notice
RETICLE_AT = (960, 590)                          # the character: just under the camera's centre
# SMALLER, AND ONLY WHILE GATHERING: the owner, 2026-10-06, "make it smaller and
# only show while gathering" (74 px across the character was too much)
RETICLE_R = 44
# THE GAME'S MENUS OPEN ON THE LEFT, under the left cards: while the bot reads
# one (its own narration says when it starts and when it is done) they slide out
# of the way, so the stream shows what it is reading; MENU_MAX_S brings them
# back whatever happens.
MENU_OPENS = ("reading the inventory", "reading the hive from the bee menu",
              "reading the quest menu")
MENU_CLOSES = ("inventory: read", "bee menu: read", "hand-in queue:",
               "the next quest read is", "a finished quest is waiting")
MENU_MAX_S = 90
GATHER_TINT = "#4ade80"          # the reticle's green: it shows only while gathering


def css(keyed: bool) -> str:
    """The cards as glass, or solid over the key colour."""
    # MEASURED on the owner's screen (2026-10-06 21:46): at 76% Bee Swarm's
    # inventory list, open on the left while the bot read it, showed through
    # the left cards and its words ran into theirs -- 90% keeps the glass edge
    card = "rgb(13,15,21)" if keyed else "rgba(9,11,17,0.90)"
    edge = "rgba(255,196,46,0.55)" if keyed else "rgba(255,196,46,0.32)"
    return f"""
QWidget#Stream {{ background: #000000; }}
QFrame#Card {{
    background: {card};
    border: 1px solid {edge};
    border-radius: 18px;
}}
QLabel#CardTitle {{
    color: {HONEY};
    font-size: 13px;
    font-weight: 900;
    letter-spacing: 3px;
}}
QLabel#CardSub {{ color: rgba(230,233,239,0.55); font-size: 12px; }}
QLabel#Big {{
    font-family: {theme.SANS};
    font-size: 28px;
    font-weight: 900;
}}
QLabel#TileLabel {{
    color: rgba(230,233,239,0.62);
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 2px;
}}
QLabel#TileSub {{ color: rgba(230,233,239,0.70); font-size: 12px; }}
QFrame#Subtitle {{
    background: {"rgb(10,12,18)" if keyed else "rgba(6,8,12,0.66)"};
    border-radius: 14px;
}}
"""


def place(widget: QWidget, rect: tuple) -> None:
    widget.setGeometry(*rect)


class Viewfinder(QWidget):
    """The bot's eyes over the picture: a vignette and corner brackets (one
    pixmap, drawn when the size or the key changes) and a reticle on the
    character that turns once every TURN_S. Clicks go through."""

    TURN_S = 8.0
    FPS = 15
    BRACKET, INSET, THICK = 70, 14, 4

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.keyed = False
        self.tint = QColor(GATHER_TINT)
        self.gathering = False
        self._cache: QPixmap | None = None
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._turn)
        self._timer.start(int(1000 / self.FPS))

    def set_keyed(self, keyed: bool) -> None:
        self.keyed = bool(keyed)
        self._cache = None
        self.update()

    def set_task(self, name: str) -> None:
        """The reticle shows while the bot gathers (its running TaskUpdate's
        name is "gather"), and is gone otherwise."""
        gathering = str(name or "") == "gather"
        if gathering != self.gathering:
            self.gathering = gathering
            self.update(self.reticle_rect())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._cache = None

    def reticle_rect(self) -> QRect:
        x, y = self._centre()
        r = RETICLE_R + 12
        return QRect(int(x - r), int(y - r), int(2 * r), int(2 * r))

    def _centre(self) -> tuple[float, float]:
        return (RETICLE_AT[0] * self.width() / W, RETICLE_AT[1] * self.height() / H)

    def _turn(self) -> None:
        if not self.gathering:
            return
        self._angle = (self._angle + 360.0 / (self.TURN_S * self.FPS)) % 360.0
        self.update(self.reticle_rect())

    def _frame(self) -> QPixmap:
        """The vignette and the brackets, drawn once."""
        if self._cache is not None and self._cache.size() == self.size():
            return self._cache
        pix = QPixmap(self.size())
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        if not self.keyed:
            p.setRenderHint(QPainter.Antialiasing)
            # A SOFT VIGNETTE: the cards read better over a darker edge
            grad = QRadialGradient(QPointF(self.width() / 2, self.height() / 2),
                                   max(self.width(), self.height()) * 0.62)
            grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            grad.setColorAt(0.70, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(0, 0, 0, 120))
            p.fillRect(self.rect(), grad)
        pen = QPen(QColor(HONEY), self.THICK)
        pen.setCapStyle(Qt.SquareCap)
        p.setPen(pen)
        i, b, w, h = self.INSET, self.BRACKET, self.width() - 1, self.height() - 1
        for (x, y, dx, dy) in ((i, i, 1, 1), (w - i, i, -1, 1),
                               (i, h - i, 1, -1), (w - i, h - i, -1, -1)):
            p.drawLine(x, y, x + dx * b, y)
            p.drawLine(x, y, x, y + dy * b)
        p.end()
        self._cache = pix
        return pix

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.drawPixmap(0, 0, self._frame())
        if not self.gathering:
            return
        if not self.keyed:
            p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self._centre()
        r = RETICLE_R
        # FOUR ARCS that turn, a still inner ring, and four ticks
        arc = QColor(self.tint)
        arc.setAlpha(210)
        p.setPen(QPen(arc, 2.5, Qt.SolidLine, Qt.FlatCap))
        box = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        for k in range(4):
            p.drawArc(box, int((self._angle + k * 90 + 12) * 16), int(66 * 16))
        p.setPen(QPen(QColor(255, 255, 255, 120), 1.5))
        p.drawEllipse(QPointF(cx, cy), r * 0.58, r * 0.58)
        p.setPen(QPen(self.tint, 2))
        for k in range(4):
            a = math.radians(k * 90 + 45)
            p.drawLine(QPointF(cx + math.cos(a) * (r + 3), cy + math.sin(a) * (r + 3)),
                       QPointF(cx + math.cos(a) * (r + 9), cy + math.sin(a) * (r + 9)))


class Subtitle(QFrame):
    """The commentary over the hotbar, with whatever the window puts in it
    (the caption, the DEMO banner)."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Subtitle")
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(20, 6, 20, 6)
        self.row.setSpacing(12)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        widget.setParent(self)
        self.row.addWidget(widget, stretch, Qt.AlignVCenter)

    def refresh(self) -> None:
        """Shown while anything in it is."""
        shown = any(not self.row.itemAt(i).widget().isHidden()
                    for i in range(self.row.count())
                    if self.row.itemAt(i).widget() is not None)
        self.setVisible(shown)


def subtitle_css() -> str:
    """The caption's look in the subtitle: large, white, centred."""
    return ("color: #ffffff; font-size: 21px; font-weight: 700;"
            " qproperty-alignment: AlignCenter;")

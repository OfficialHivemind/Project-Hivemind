"""Chat's W rain, drawn (DESIGN 8ee). The rules are stream/wrain (no Qt).

One transparent widget over the whole 1920x1080 stream window, above
everything in it -- the picture, its masks, the toasts, the recap and the
cards -- and invisible to the mouse. It draws the falling W's and the "W ×12"
count, and nothing else.

WHAT IT COSTS. A 60 Hz timer runs only while a W is falling or the count is
fading; with none, the timer is stopped and the widget hidden, so an idle
stream never calls it at all. Each W is drawn from a pixmap made once, when
the window opens (every size, pre-tilted in 3-degree steps), so a frame is a
blit per W: no text is laid out and nothing is rotated while it runs. Only
where a W was and is now is repainted, not the window; the stream's cards
and picture under that are repainted with it, which is most of what a frame
costs (measured in docs/pending/wrain.md).

GOLD, NEVER GREEN. With the game picture in key colour (stream.game_view)
OBS's Color Key clears #00ff00, and a half-transparent pixel over it is a
blend of the key green that the key leaves opaque -- a green fringe, the way
the fading toasts flashed green (DESIGN 8eb). So over the picture in key
colour the W's and the count have hard edges (drawn without antialiasing:
every pixel wholly the W or wholly not), no shadow, and the count does not
fade or pulse. Elsewhere, and over the live picture, they are antialiased
with a soft shadow.

NOTHING HERE READS WHAT CHAT WROTE beyond deciding whether it is a W: no
chat words are drawn, only the letter W and a number.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPainterPathStroker, QPen, QPixmap,
                           QRegion, QTransform)
from PySide6.QtWidgets import QWidget

from ..stream import wrain
from ..stream.chat import Moderation
from . import theme

KEY = "stream.chat_w_rain"
# ~60 Hz (62.5), for a stream OBS captures at 60 fps: a W falls 6.6 to 9.7 px
# a frame at this rate, and would jump twice that at 30.
FRAME_MS = 16
# The pre-tilted pixmaps: every ANGLE_STEP degrees across the tilt the rain
# can take. MEASURED on the glyph paths, a 3-degree step moves the farthest
# point of the biggest W's outline 4.7 px (the smallest's 1.6 px), under the
# 9.7 px it falls in the same frame.
ANGLE_STEP = 3.0
ANGLES = int(round(2 * wrain.MAX_TILT_DEG / ANGLE_STEP)) + 1
# The W's look: hive gold (theme.ACCENT) from a pale top to an amber foot,
# inside a near-black outline 9% of its size, which is what keeps it
# readable over a yellow hive wall as well as a green field.
GOLD_TOP, GOLD_MID, GOLD_FOOT = "#fff1bd", theme.ACCENT, "#f59e0b"
OUTLINE = QColor(20, 16, 8)
OUTLINE_SHARE = 0.09            # of the font's pixel size, outside the fill
SHADOW = QColor(0, 0, 0, 105)
SHADOW_SHARE = (0.03, 0.06)     # offset, of the size
FAMILIES = [f.strip() for f in theme.SANS.split(",") if f.strip() != "sans-serif"]
# The count: "W ×12" at the top right of the game picture, clear of the game's
# own HUD (honey top-centre, menus top-left, notices bottom-right) and of the
# toasts (bottom-left). On a dark badge -- the toasts' card colour, with a gold
# edge -- because in a heavy rain the W's behind it are gold too (the first
# render at the cap). Over the key colour the badge is solid, as the toasts are.
COMBO_PX = 40
COMBO_INSET = (18, 14)          # from the picture's right edge and top
COMBO_BUMP = 0.18               # the count grows this much on each new W
BADGE_BG = QColor(14, 16, 20, 237)
BADGE_PAD = (14, 5)


class _Glyph:
    """A pre-drawn W (or count): the pixmap, and where its centre is in it."""

    __slots__ = ("pixmap", "cx", "cy", "w", "h")

    def __init__(self, pixmap: QPixmap, cx: int, cy: int):
        self.pixmap = pixmap
        self.cx, self.cy = cx, cy
        self.w, self.h = pixmap.width(), pixmap.height()


def _font(px: int) -> QFont:
    font = QFont()
    font.setFamilies(FAMILIES)
    font.setPixelSize(px)
    font.setWeight(QFont.Black)
    return font


def _shapes(text: str, px: int):
    """`text` as a path centred on (0, 0), and the path of it with its
    outline round it. Made once a size: a tilt only turns them."""
    path = QPainterPath()
    path.addText(0, 0, _font(px), text)
    centre = path.boundingRect().center()
    path.translate(-centre.x(), -centre.y())
    stroker = QPainterPathStroker()
    stroker.setWidth(2 * OUTLINE_SHARE * px)
    stroker.setJoinStyle(Qt.RoundJoin)
    stroker.setCapStyle(Qt.RoundCap)
    return path, stroker.createStroke(path).united(path)


def _paint(text: str, px: int, angle: float, hard: bool, shapes=None) -> _Glyph:
    """`text` in gold with its outline, tilted by `angle`, in a pixmap just big
    enough for it. `hard`: no antialiasing and no shadow, so every pixel is
    wholly opaque or wholly clear (the key colour's rule)."""
    path, rim = shapes or _shapes(text, px)
    turn = QTransform()
    turn.rotate(angle)
    fill, outer = turn.map(path), turn.map(rim)
    shadow = QPointF(0.0, 0.0) if hard else QPointF(SHADOW_SHARE[0] * px,
                                                    SHADOW_SHARE[1] * px)
    box = outer.boundingRect().united(outer.boundingRect().translated(shadow))
    left, top = int(box.left()) - 2, int(box.top()) - 2
    pixmap = QPixmap(int(box.right()) - left + 3, int(box.bottom()) - top + 3)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, not hard)
    painter.translate(-left, -top)
    painter.setPen(Qt.NoPen)
    if not hard:
        painter.setBrush(SHADOW)
        painter.drawPath(outer.translated(shadow))
    painter.setBrush(OUTLINE)
    painter.drawPath(outer)
    bounds = fill.boundingRect()
    gradient = QLinearGradient(0, bounds.top(), 0, bounds.bottom())
    gradient.setColorAt(0.0, QColor(GOLD_TOP))
    gradient.setColorAt(0.45, QColor(GOLD_MID))
    gradient.setColorAt(1.0, QColor(GOLD_FOOT))
    painter.setBrush(QBrush(gradient))
    painter.drawPath(fill)
    painter.end()
    return _Glyph(pixmap, -left, -top)


def _badge(n: int, hard: bool) -> _Glyph:
    """"W ×n" on its dark badge."""
    text = _paint(f"W ×{n}", COMBO_PX, 0.0, hard)
    w, h = text.w + 2 * BADGE_PAD[0], text.h + 2 * BADGE_PAD[1]
    pixmap = QPixmap(w, h)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, not hard)
    edge = QColor(theme.ACCENT)
    if not hard:
        edge.setAlpha(190)
    painter.setPen(QPen(edge, 2))
    painter.setBrush(QColor(BADGE_BG.red(), BADGE_BG.green(), BADGE_BG.blue())
                     if hard else BADGE_BG)
    radius = (h - 2) / 2
    painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), radius, radius)
    painter.drawPixmap(BADGE_PAD[0], BADGE_PAD[1], text.pixmap)
    painter.end()
    return _Glyph(pixmap, w // 2, h // 2)


def glyph_set(hard: bool) -> list:
    """[size][tilt step] -> _Glyph, for every size the rain uses."""
    out = []
    for px in wrain.SIZES_PX:
        shapes = _shapes("W", px)
        out.append([_paint("W", px, -wrain.MAX_TILT_DEG + i * ANGLE_STEP, hard, shapes)
                    for i in range(ANGLES)])
    return out


class RainOverlay(QWidget):
    """The W rain over the stream window. `get(key)` reads a setting;
    `blocked(*texts)` is the stream's own "Ignore chat containing" rule
    (stream/show.Show._blocked); `picture` is where the game picture is, in
    this widget's coordinates -- the count goes at its top right, and there
    the key colour's hard edges apply."""

    def __init__(self, parent: QWidget, get, blocked=None, picture: QRect | None = None,
                 clock=time.monotonic):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.setGeometry(parent.rect())
        self.get = get
        self.blocked = blocked
        self.clock = clock
        self.picture = QRect(picture) if picture is not None else QRect(self.rect())
        self.keyed = str(get("stream.game_view") or "") == "key colour"
        self.rain = wrain.Rain(self.width(), self.height())
        self._glyphs = {False: None, True: None}      # hard -> glyph_set
        self._counts: dict = {}                       # (n, hard) -> _Glyph
        self._combo_drawn = None                      # (QRect, state) last drawn
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._frame)
        # for the drives: frames run, seconds spent painting
        self.frames = 0
        self.spent = 0.0
        self.hide()
        if self.get(KEY):                             # once, as the window opens
            self._glyphs[False] = glyph_set(False)
            if self.keyed:
                self._glyphs[True] = glyph_set(True)

    # ---- what the stream window tells it -------------------------------------------
    def hear(self, line) -> int:
        """One chat line from StreamWindow._on_chat. NEVER RAISES: the chat
        games hear the same line next, and the rain must not be the reason
        they miss it. Its worth in W's, or 0."""
        try:
            if isinstance(line, Moderation) or not self.get(KEY):
                return 0
            text = str(getattr(line, "text", "") or "")
            user = str(getattr(line, "user", "") or "")
            name = str(getattr(line, "name", "") or user)
            if self.blocked is not None and self.blocked(
                    text, "" if user.startswith("yt:") else user, name):
                return 0
            # the line's own stamp, from its reader's thread: a YouTube poll's
            # lines are microseconds apart however slowly the window hears them
            stamp = getattr(line, "at", None)
            worth = self.rain.hear(user, text, self.clock(),
                                   stamp=stamp if isinstance(stamp, (int, float)) else None)
            if worth and self.rain.busy:
                self._start()
            return worth
        except Exception:
            return 0

    def setting_changed(self, key: str, value) -> None:
        if key == KEY and not value:
            self.clear()
        elif key == "stream.game_view":
            self.set_keyed(str(value) == "key colour")

    def set_keyed(self, keyed: bool) -> None:
        """The game picture is the key colour (or no longer is): the W's over
        it change to their hard-edged pixmaps at the next frame."""
        self.keyed = bool(keyed)
        if self.keyed and self._glyphs[True] is None and self.rain.busy:
            self._glyphs[True] = glyph_set(True)
        self.update()

    def clear(self) -> None:
        """Every W off the screen at once, and the timer stopped."""
        self.rain.clear()
        self._timer.stop()
        self._combo_drawn = None
        self.hide()

    # ---- frames ------------------------------------------------------------------------
    def _start(self) -> None:
        if self._glyphs[False] is None:
            self._glyphs[False] = glyph_set(False)
        if self.keyed and self._glyphs[True] is None:
            self._glyphs[True] = glyph_set(True)
        if self.isHidden():
            self.show()
        if not self._timer.isActive():
            self._frame()
            self._timer.start()

    def _glyph(self, drop, hard_here: bool):
        step = int(round((drop.angle + wrain.MAX_TILT_DEG) / ANGLE_STEP))
        return self._glyphs[hard_here][drop.size][min(ANGLES - 1, max(0, step))]

    def _frame(self) -> None:
        """Move the W's to now and mark where they were and are."""
        self.frames += 1
        gone = self.rain.advance(self.clock())
        dirty = QRegion()
        for drop in gone:
            if drop.drawn is not None:
                dirty += QRect(*drop.drawn[:4])
        pic = self.picture
        px0, py0 = pic.x(), pic.y()
        px1, py1 = px0 + pic.width(), py0 + pic.height()
        keyed = self.keyed and self._glyphs[True] is not None
        for drop in self.rain.drops:
            glyph = self._glyph(drop, False)
            x, y = int(drop.x) - glyph.cx, int(drop.y) - glyph.cy
            if keyed and x < px1 and x + glyph.w > px0 and y < py1 and y + glyph.h > py0:
                glyph = self._glyph(drop, True)
                x, y = int(drop.x) - glyph.cx, int(drop.y) - glyph.cy
            old = drop.drawn
            drop.drawn = (x, y, glyph.w, glyph.h, glyph.pixmap)
            if old is None:
                dirty += QRect(x, y, glyph.w, glyph.h)
            else:
                left, top = min(x, old[0]), min(y, old[1])
                dirty += QRect(left, top, max(x + glyph.w, old[0] + old[2]) - left,
                               max(y + glyph.h, old[1] + old[3]) - top)
        combo = self._combo_state()
        if combo != (self._combo_drawn[1] if self._combo_drawn else None):
            if self._combo_drawn is not None:
                dirty += self._combo_drawn[0]
            self._combo_drawn = self._combo_place(combo)
            if self._combo_drawn is not None:
                dirty += self._combo_drawn[0]
        if not dirty.isEmpty():
            self.update(dirty)
        if not self.rain.busy:
            self._timer.stop()
            self._combo_drawn = None
            self.hide()

    # ---- the count --------------------------------------------------------------------
    def _combo_state(self):
        """What the count looks like now, rounded to what can be seen: the
        number, its opacity and its bump; None when it is not shown."""
        r = self.rain
        if r.combo < wrain.COMBO_FROM or r.combo_alpha <= 0.0:
            return None
        if self.keyed:
            return (r.combo, 1.0, 0.0, True)    # over the key: no fade, no bump
        return (r.combo, round(r.combo_alpha, 2), round(r.combo_pulse, 2), False)

    def _count(self, n: int, hard: bool) -> _Glyph:
        key = (n, hard)
        glyph = self._counts.get(key)
        if glyph is None:
            if len(self._counts) > 64:
                self._counts.clear()
            glyph = self._counts[key] = _badge(n, hard)
        return glyph

    def _combo_place(self, state):
        """(box, state, glyph) for the count as `state` has it, or None: the
        glyph is kept with its box, so a paint before the next frame draws
        what the box was measured for."""
        if state is None:
            return None
        n, _alpha, pulse, hard = state
        glyph = self._count(n, hard)
        scale = 1.0 + COMBO_BUMP * pulse
        w, h = int(glyph.w * scale) + 2, int(glyph.h * scale) + 2
        right = self.picture.x() + self.picture.width() - COMBO_INSET[0]
        top = self.picture.y() + COMBO_INSET[1]
        # grown about its right-hand middle, so the number does not jump
        middle = top + glyph.h // 2
        return QRect(right - w, middle - h // 2, w, h), state, glyph

    # ---- painting ----------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        began = time.perf_counter()
        drops = self.rain.drops
        combo = self._combo_drawn
        if not drops and combo is None:
            return
        area = event.rect()
        x0, y0 = area.x(), area.y()
        x1, y1 = x0 + area.width(), y0 + area.height()
        painter = QPainter(self)
        for drop in drops:
            drawn = drop.drawn
            if drawn is None:
                continue                         # not placed yet: above the top
            x, y, w, h, pixmap = drawn
            if x < x1 and x + w > x0 and y < y1 and y + h > y0:
                painter.drawPixmap(x, y, pixmap)
        if combo is not None and combo[0].intersects(area):
            box, (_n, alpha, _pulse, hard), glyph = combo
            if hard:
                painter.drawPixmap(box.x() + 1, box.y() + 1, glyph.pixmap)
            else:
                painter.setOpacity(alpha)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                painter.drawPixmap(QRectF(box.adjusted(1, 1, -1, -1)), glyph.pixmap,
                                   QRectF(glyph.pixmap.rect()))
        painter.end()
        self.spent += time.perf_counter() - began

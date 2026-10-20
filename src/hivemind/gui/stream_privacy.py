"""The stream window's privacy, drawn: the gate on every label, and the masks
over the game picture. The rules themselves are in stream/privacy (no Qt).

TWO PLACES, ONE GATE. Every event, chat line and file the stream reads is
scrubbed at the door (StreamWindow.handle, _on_chat); every label, toast and
bar is scrubbed again as it is drawn (`SafeLabel`, `scrub`), so a string that
reaches a label some other way -- a replay's file name, a chat reader's
error, a ledger row's reason -- passes the same rules. It is one `Redactor`,
set by the open stream window (`activate`). Every label keeps what it was
given, so a word the owner adds to the gate is hidden at once in what is
already on screen too (`rescrub`).

THE PICTURE IS MASKED FOR THE STREAM ONLY. `PictureGuard` is a widget over
the stream's own copy of the live view. It reads a few pixels of each frame
the live view has already decoded, hears what the bot says it is doing (its
menu, who has the controls), and paints over the picture when it has to. It never changes the picture: the main window's
live view, and the bot, which captures the game in its own process, never
see a mask. What it costs a frame is measured on both frame pipelines
(scratchpad streamsafe/final/guard_cost.py, DESIGN 8ec): integ's QPixmap
and feat/streamfps's Picture, which it reads as a numpy view.

WITH THE KEY COLOUR (stream.game_view) the stream's picture is green and OBS
puts its own capture of the game's window under it, live. The guard keeps
judging the main window's frames and paints SOLID covers, never blurs: a
blur of the game can hold greens that OBS's Color Key clears, and the capture
under it would show through. The whole picture is covered whenever the
stream cannot see what that capture shows -- the bot rejoining or offline,
or no frame for KEYED_BLIND_SECONDS.

DESIGN 8ec.
"""
from __future__ import annotations

import time

# numpy is loaded with the window, not on the first frame: MEASURED, the
# first frame's masks took 43 ms when it was imported there.
import numpy as np
from PySide6.QtCore import QObject, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QLabel, QWidget

from ..stream import privacy
from ..telemetry.events import StatusUpdate
from . import theme

_ACTIVE = privacy.Redactor({})


def activate(redactor: privacy.Redactor) -> None:
    """The open stream window's gate, used by every SafeLabel."""
    global _ACTIVE
    _ACTIVE = redactor


def gate() -> privacy.Redactor:
    return _ACTIVE


def scrub(text) -> str:
    """Text for the stream to draw; a dropped line draws as nothing."""
    return _ACTIVE.text(text)


def rescrub(root: QWidget) -> int:
    """Every widget under `root` that keeps its own words draws them again
    through the gate as it now stands (a word just added to the private
    list, the username switched on). How many were asked."""
    n = 0
    for widget in root.findChildren(QWidget):
        again = getattr(widget, "rescrub", None)
        if callable(again):
            again()
            n += 1
    return n


class SafeLabel(QLabel):
    """A QLabel whose text always passes the gate. Rich text is scrubbed
    whole: the rules match no part of the markup the stream writes (the
    colours are 6-digit hex, the weights 3 digits, and no tag has a slash
    before a word). It keeps what it was given (`_raw`) for `rescrub`."""

    def __init__(self, text: str = ""):
        self._raw = str(text or "")
        super().__init__(scrub(self._raw))

    def setText(self, text) -> None:           # noqa: N802 (Qt's name)
        self._raw = str(text or "")
        super().setText(scrub(self._raw))

    def rescrub(self) -> None:
        QLabel.setText(self, scrub(self._raw))


class GatedMirror(QObject):
    """The stream's live view mirrors the main window's decoded frames with
    each Frame's words through the gate: the live view draws every
    detection's label on the picture (panels/liveview), and a Frame that
    reached the stream this way never passed `StreamWindow.handle`.

    `LiveView.mirror` is called as it is -- on feat/streamfps it also puts
    the view on the source's list of sizes to decode at -- and its own
    connection is then swapped for this one, which hands the view the same
    picture with a scrubbed Frame. The same (Frame, picture) pair on either
    branch: a QPixmap on integ, a Picture on feat/streamfps."""

    def __init__(self, view, source, frame_filter):
        super().__init__(view)
        self.view = view
        self.filter = frame_filter
        view.mirror(source)
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                source.shown.disconnect(view._show_decoded)
        except (RuntimeError, TypeError):
            pass            # still connected: this slot runs after it anyway
        source.shown.connect(self._shown)
        if getattr(view, "_frame", None) is not None:
            view._frame = frame_filter(view._frame)

    def _shown(self, event, picture) -> None:
        self.view._show_decoded(self.filter(event) if event is not None else None,
                                picture)


# ---- the game picture ---------------------------------------------------------------

def _array(pixmap, rect: QRect):
    """The pixels of `rect` of `pixmap` as an (h, w, 3) RGB array."""
    image = pixmap.copy(rect).toImage().convertToFormat(QImage.Format_RGB888)
    w, h, line = image.width(), image.height(), image.bytesPerLine()
    if not w or not h:
        return np.zeros((0, 0, 3), np.uint8)
    raw = np.frombuffer(image.constBits(), np.uint8, count=line * h).reshape(h, line)
    # A COPY: the array is a view of the QImage's buffer, and the QImage is
    # freed when this returns. MEASURED: without the copy the chat test read
    # garbage and fired on 21 of 10,434 saved frames whose badge was there.
    return raw[:, :w * 3].reshape(h, w, 3).copy()


class _Pixels:
    """One decoded frame, whatever the live view hands over: a QPixmap
    (integ's LiveView) or feat/streamfps's `Picture`, a QImage over the BGRA
    array OpenCV decoded (DESIGN 8eb). MEASURED on a merge of the two: the
    guard read `pixmap.isNull()` off a Picture, raised on every frame, and
    the stream showed nothing but its fault card."""

    def __init__(self, source):
        self.source = source
        self.image = getattr(source, "image", None)
        self.pixels = getattr(source, "pixels", None)

    def null(self) -> bool:
        if self.image is not None:
            return self.image.isNull() or not self.image.width()
        return self.source.isNull()

    def size(self) -> QSize:
        return self.image.size() if self.image is not None else self.source.size()

    def rgb(self, rect: QRect):
        """The pixels of `rect` as an (h, w, 3) RGB array."""
        if self.pixels is not None:
            y, x = rect.y(), rect.x()
            # BGRA: channels 2, 1, 0 are red, green, blue; a view, not a copy
            return self.pixels[y:y + rect.height(), x:x + rect.width(), 2::-1]
        return _array(self.source, rect)

    def small(self, rect: QRect, w: int, h: int):
        """`rect` shrunk to w x h, smoothly: the blur's source."""
        part = (self.image if self.image is not None else self.source).copy(rect)
        return part.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


class PictureGuard(QWidget):
    """Masks over the game picture, from the frames `source` decodes and
    what the bot says.

    `source` is a panels/liveview.LiveView (the main window's, when mirrored,
    or the stream's own): its `shown(Frame, picture)` and `held(str)`
    signals, and at the start its `_picture` (feat/streamfps) or `_pixmap`
    (integ), `_frame`, `_missing` and `_hint`, are all this reads of it; the
    picture is a QPixmap or a Picture (`_Pixels`). `get(key)` reads a
    setting. The stream window hands it every event (`hear`), the socket's
    state (`set_link`), the game picture's mode (`set_keyed`) and its 1 s
    tick.
    """

    CAPTION = {"menu": "Roblox menu hidden", "chat": "Roblox chat hidden"}

    def __init__(self, parent, source, get, clock=time.time):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.get = get
        self.clock = clock
        self._picture = None
        self._size = QSize(privacy.FRAME_W, privacy.FRAME_H)
        # name -> (frame QRect, small image or None)
        self._masks: dict = {}
        self._app_until = 0.0
        self._fault_until = 0.0
        self._held_raw = ""
        self._held = ""
        self._keyed = False
        self._linked = True
        self._by_hand = False
        self._last_frame = None         # when the last Frame arrived
        self.menu = privacy.MenuWatch(clock=clock)
        self.frames = 0
        self.fired: dict = {}           # name -> frames masked, for the drives
        self.spent = 0.0                # seconds in on_shown, for the drives
        # KEY COLOUR GOES BLIND the moment frames stop: this fires then.
        self._blind = QTimer(self)
        self._blind.setSingleShot(True)
        self._blind.setInterval(int(privacy.KEYED_BLIND_SECONDS * 1000))
        self._blind.timeout.connect(self.update)
        shown = getattr(source, "shown", None)
        held = getattr(source, "held", None)
        if shown is not None:
            shown.connect(self.on_shown)
        if held is not None:
            held.connect(self.on_held)
        picture = getattr(source, "_picture", None)
        if picture is None:
            picture = getattr(source, "_pixmap", None)
        if picture is not None:
            self.on_shown(getattr(source, "_frame", None), picture)
            # A SOURCE ALREADY HOLDING: its mirror (the stream's live view)
            # draws the hold line, a frame's path among it, from the start.
            if getattr(source, "_missing", False):
                hint = getattr(source, "_hint", None)
                self.on_held(hint.text() if hint is not None else "")

    # ---- what the stream window tells it -----------------------------------------
    def hear(self, event, quiet: bool = False) -> None:
        """Every event, after the gate: the bot's word on the menu, and who
        has the controls."""
        before = self._state()
        if isinstance(event, StatusUpdate):
            self._by_hand = bool(event.handed_over or event.handing_over)
        if not quiet:
            self.menu.hear(event)       # a replayed menu word is old news
        if self._state() != before:
            self.refresh()

    def _state(self):
        return (self.menu.up(), self._by_hand)

    def set_link(self, connected: bool) -> None:
        """The bot's socket. With the key colour, the stream cannot see what
        OBS's capture of the game shows while it is down (a rejoin shows
        the Roblox app), so the whole picture is covered."""
        self._linked = bool(connected)
        self.refresh()

    def set_keyed(self, keyed: bool) -> None:
        self._keyed = bool(keyed)
        self.refresh()

    def tick(self) -> None:
        """The window's 1 s tick: a hold that has run out comes off even
        while no frame arrives."""
        self.refresh()

    def refresh(self) -> None:
        """Work the masks out again for the frame shown."""
        if self._picture is not None:
            self._judge(None, self._picture)
        self.update()

    def rescrub(self) -> None:
        self._held = scrub(self._held_raw)
        self.update()

    # ---- frames ------------------------------------------------------------------
    def on_held(self, why: str) -> None:
        self._held_raw = str(why or "")
        self._held = scrub(self._held_raw)
        self.update()

    def on_shown(self, event, picture) -> None:
        began = time.perf_counter()
        try:
            self._judge(event, picture)
        except Exception:
            # a frame whose masks cannot be worked out is not shown at all,
            # rather than shown unmasked
            self._masks = {}
            self._fault_until = self.clock() + privacy.APP_HOLD_SECONDS
        self.spent += time.perf_counter() - began
        self.update()

    def _rect(self, region, sx: float, sy: float) -> QRect:
        x, y, w, h = region
        return QRect(int(x * sx), int(y * sy), max(1, int(w * sx)), max(1, int(h * sy)))

    def _luma(self, px, region, sx, sy):
        return privacy.luma(px.rgb(self._rect(region, sx, sy)))

    def _menu_seen(self, px, sx: float, sy: float) -> bool:
        """The panel's darkening on its four edges, or the Resume button."""
        top, bottom = privacy.MENU_ROWS[0], privacy.MENU_ROWS[-1] + 1
        step = max(1, int(round((privacy.MENU_ROWS[1] - privacy.MENU_ROWS[0]) * sy)))
        pairs = []
        for inside, outside in ((privacy.MENU_LEFT_IN, privacy.MENU_LEFT_OUT),
                                (privacy.MENU_RIGHT_IN, privacy.MENU_RIGHT_OUT)):
            pair = []
            for x, w in (inside, outside):
                pair.append(self._luma(px, (x, top, w, bottom - top), sx, sy)[::step]
                            .mean(axis=1))
            pairs.append(pair)
        left, right = privacy.MENU_COLUMNS[0], privacy.MENU_COLUMNS[-1] + 1
        cstep = max(1, int(round((privacy.MENU_COLUMNS[1] - privacy.MENU_COLUMNS[0]) * sx)))
        for inside, outside in ((privacy.MENU_TOP_IN, privacy.MENU_TOP_OUT),
                                (privacy.MENU_BOTTOM_IN, privacy.MENU_BOTTOM_OUT)):
            pair = []
            for y, h in (inside, outside):
                pair.append(self._luma(px, (left, y, right - left, h), sx, sy)[:, ::cstep]
                            .mean(axis=0))
            n = min(len(pair[0]), len(pair[1]))
            pairs.append((pair[0][:n], pair[1][:n]))
        if privacy.menu_edges(pairs):
            return True
        # THE PANEL'S OWN OPAQUE BUTTON, for a scene too dark for the edges
        for fill_at, label_x, border_at in privacy.MENU_BUTTONS:
            fill = px.rgb(self._rect(fill_at, sx, sy))
            a, b = (int((x - fill_at[0]) * sx) for x in label_x)
            fill = np.concatenate([fill[:, :a].reshape(-1, 3), fill[:, b:].reshape(-1, 3)])
            border = px.rgb(self._rect(border_at, sx, sy))
            # the brightest row of the border's five
            border = border[int(np.argmax(privacy.luma(border).mean(axis=1)))]
            if privacy.resume_button(fill, border):
                return True
        return False

    def _judge(self, event, picture) -> None:
        now = self.clock()
        if event is not None:
            self._held_raw = self._held = ""
            self.frames += 1
            self._last_frame = now
            if self._keyed:
                self._blind.start()
        self._picture = picture
        px = _Pixels(picture) if picture is not None else None
        if px is None or px.null():
            self._masks = {}
            return
        size = px.size()
        sx = size.width() / privacy.FRAME_W
        sy = size.height() / privacy.FRAME_H
        cover = bool(self.get("stream.cover_menus"))
        screen = str(getattr(event, "screen", "") or "")
        if cover and screen in privacy.APP_SCREENS:
            self._app_until = now + privacy.APP_HOLD_SECONDS
        masks = {}
        if self.cover_reason() is None:
            if cover:
                if event is not None and self._menu_seen(px, sx, sy):
                    self.menu.seen()
                if self.menu.up():
                    masks["menu"] = privacy.MENU_PANEL
            if self.get("stream.blur_roblox_chat"):
                pill = px.rgb(self._rect(privacy.TOPBAR_PILL, sx, sy))
                badge = px.rgb(self._rect(privacy.CHAT_BADGE, sx, sy))
                if privacy.chat_may_be_open(pill, badge):
                    masks["chat"] = privacy.CHAT_REGION
        out = {}
        for name, region in masks.items():
            rect = self._rect(region, sx, sy)
            factor = privacy.BLUR_FACTOR
            # SOLID OVER THE KEY COLOUR, so no pixels are needed for it
            small = None if self._keyed else px.small(
                rect, max(1, rect.width() // factor), max(1, rect.height() // factor))
            out[name] = (rect, small)
            self.fired[name] = self.fired.get(name, 0) + (event is not None)
        self._masks = out
        self._size = size

    def cover_reason(self):
        """(headline, line under it) when the whole picture is covered, else
        None."""
        now = self.clock()
        if now < self._app_until:
            return ("Roblox's own screens are not shown on stream",
                    "back to the game in a moment")
        if self._by_hand and self.get("stream.cover_by_hand"):
            # THE OWNER IS PLAYING BY HAND: anything they open -- the player
            # list (Tab), the Esc menu, chat -- is theirs, and no mask follows
            # a person (DESIGN 8ec).
            return ("the owner is playing by hand",
                    "the picture is back when the bot takes over")
        if self._keyed and not self._linked:
            # rejoining or offline: the header says which
            return ("the bot is not in the game right now",
                    "the picture is back once it is")
        if self._keyed and (self._last_frame is None
                            or now - self._last_frame > privacy.KEYED_BLIND_SECONDS):
            return ("waiting for the game picture", "")
        if now < self._fault_until:
            return ("the picture is hidden for a moment", "")
        return None

    def covered(self) -> bool:
        return self.cover_reason() is not None

    def masks(self) -> list:
        return sorted(self._masks)

    # ---- drawing -----------------------------------------------------------------
    def _view_rect(self):
        """Where the live view draws the frame: letterboxed, as LiveView."""
        size = self._size
        scaled = size.scaled(self.size(), Qt.KeepAspectRatio)
        ox = (self.width() - scaled.width()) / 2
        oy = (self.height() - scaled.height()) / 2
        return (ox, oy, scaled.width() / max(1, size.width()),
                scaled.height() / max(1, size.height()))

    def paintEvent(self, _event) -> None:
        reason = self.cover_reason()
        if reason is not None:
            self._card(*reason)
            return
        if self._picture is None:
            # NOTHING YET: the live view's own hint may be a file path
            # ("frame not found: ..."), so it is covered with a plain card.
            self._card("waiting for the game picture")
            return
        held = self._held and not self._keyed
        if not self._masks and not held:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)
        ox, oy, sx, sy = self._view_rect()
        font = QFont(theme.SANS.split(",")[0])
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        tags = []
        for name, (rect, small) in self._masks.items():
            target = QRectF(ox + rect.x() * sx, oy + rect.y() * sy,
                            rect.width() * sx, rect.height() * sy)
            tags.append((name, target))
            if small is None:
                # OPAQUE AND NOT GREEN: OBS's Color Key leaves this, and it
                # hides the game capture under it
                painter.fillRect(target, QColor(theme.BG_PANEL))
            else:
                if isinstance(small, QImage):
                    painter.drawImage(target, small, QRectF(small.rect()))
                else:
                    painter.drawPixmap(target, small, QRectF(small.rect()))
                painter.fillRect(target, QColor(14, 16, 20, 70))
        # THE TAGS AFTER EVERY MASK: the chat region overlaps the menu
        # panel's corner, and drawn second it covered the menu's tag
        for name, target in tags:
            tag = self.CAPTION.get(name, "hidden")
            metrics = painter.fontMetrics()
            box = QRectF(target.x() + 8, target.y() + 8,
                         metrics.horizontalAdvance(tag) + 16, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(14, 16, 20, 200))
            painter.drawRoundedRect(box, 5, 5)
            painter.setPen(QColor(theme.TEXT_DIM))
            painter.drawText(box, Qt.AlignCenter, tag)
        if held:
            # THE LIVE VIEW'S OWN HOLD LINE is drawn under this band, and it
            # quotes the frame's path; the band covers it and says the same
            # thing through the gate.
            # OPAQUE: at 92% the path under it was still readable on the
            # first render. Two 9-pt lines from 10 px down end by 44 px.
            band = QRectF(0, 0, self.width(), 56)
            painter.fillRect(band, QColor(14, 16, 20))
            font.setPixelSize(14)
            painter.setFont(font)
            painter.setPen(QColor(theme.WARN))
            painter.drawText(band.adjusted(12, 0, -12, 0), Qt.AlignCenter,
                             " ".join(f"the picture is paused — {self._held}".split()))
        painter.end()

    def _card(self, head: str, sub: str = "") -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BG_PANEL))
        font = QFont(theme.SANS.split(",")[0])
        font.setPixelSize(26)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_DIM))
        middle = self.rect().adjusted(40, 0, -40, -30 if sub else 0)
        painter.drawText(middle, Qt.AlignCenter, head)
        if sub:
            font.setPixelSize(17)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor(theme.TEXT_FAINT))
            painter.drawText(self.rect().adjusted(40, 40, -40, 0), Qt.AlignCenter, sub)
        painter.end()

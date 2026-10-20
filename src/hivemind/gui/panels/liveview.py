"""What the bot is looking at, with what it detected drawn on top.

The overlay is the point. A frame alone tells you the capture works; a frame
with the token boxes, the walk target and the read HUD values drawn over it
tells you whether the *vision* works, which is the part that actually fails.
When the bot walks into a wall, this pane is where you see that it was chasing
a yellow flower it believed was a token.

Frames arrive as a path, not as pixels on the socket -- see telemetry.events.

DECODED OFF THE GUI THREAD, AT THE SIZE SHOWN, ON THE BOT'S CLOCK (DESIGN
8eb). Each path goes to a decoder thread, which reads the newest one with
OpenCV: it lets go of the GIL, so the window's own Python keeps running (Qt's
decoder held it; MEASURED, a Python loop beside it ran at 3% of its speed,
beside OpenCV's at 98%). The file is the bot's full 1920x1080 frame; while no
view needs more than 960x540 -- the main window's is about 580x326 -- it is
decoded at half size, which libjpeg does in its DCT (FULL_ABOVE). The decoded
picture is then shown a fixed PRESENT_DELAY_S after the bot captured it, so
frames appear at the spacing they were taken at rather than at the spacing the
socket and the decoder happened to deliver them.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...telemetry.events import Frame, GameInput
from .. import theme

DETECTION_COLOURS = {
    "token": theme.ACCENT,
    "maybe": theme.ACCENT,
    "mob": theme.BAD,
    "target": theme.GOOD,
    "landmark": theme.INFO,
}

# THE OVERLAY'S LOOK. The owner, 2026-09-27, of the token boxes: too many
# plain squares. Each
# kind now has a mark of its own shape, so the picture reads at a glance:
#
#     token      a ring round the thing, with a short label pill
#     target     the same ring, thicker, in green -- what is being walked to
#     maybe      a faint dot and no words: a sighting too weak to chase is
#                worth seeing, not worth a paragraph (its numbers are in `label`)
#     mob        a rounded box, with its name
#     landmark   corner brackets -- the HUD pills, a panel, the honeycomb
#
# The words on the picture are the short `tag` a detection carries, or its
# label cut to PILL_MOST_CHARS; the whole label stays in the event.
RING_MIN_PX = 14            # a ring smaller than this on screen reads as a dot
BRACKET_PX = 10             # a corner bracket's arm, on screen
PILL_MOST_CHARS = 30
PILL_RADIUS = 6.0
PILL_FILL = QColor(12, 14, 18, 200)
HALO = QColor(0, 0, 0, 150)         # under every line, so it reads on any ground
MAYBE_DOT_PX = 3.0

# HOW LONG AFTER ITS CAPTURE A FRAME IS SHOWN. The capture-to-decoded time is
# what it has to cover: MEASURED in the offline replay through the real bot
# and GUI code at 30 fps with the 1920x1080 stream window open (DESIGN 8eb),
# three runs, 3,313 frames: median 7.3 to 7.8 ms, 99th percentile 11.3 to
# 19.7 ms, most 43 ms. At 25 ms, 8 of them (0.24%) were late; a late one is
# shown the moment it is decoded.
PRESENT_DELAY_S = 0.025
# A frame stamped further ahead than this is on another clock (a replay's, or
# a clock that stepped): shown at once rather than held.
PRESENT_MOST_S = 0.5
# A VIEW LARGER THAN THIS NEEDS THE FULL FRAME; otherwise the half-size
# decode serves every view. MEASURED on 1920x1080 live JPEGs at 30 a second,
# one OpenCV thread: full 5.0 ms wall and 6.0 ms CPU, half 2.0 and 2.0.
FULL_ABOVE = (960, 540)
# Decoded frames waiting to be shown. At 30 fps and a 25 ms delay there is
# never more than one; more means the GUI thread fell behind, and the older
# ones are dropped rather than played late.
PRESENT_QUEUE = 3


# TAKE CONTROL THROUGH THE PICTURE (RL1b step 3). Headless, the game has no
# window anywhere, so while the owner has the controls this view IS the game:
# mouse and keys over it go to the bot as GameInput, which it applies through
# its own input (brain/controls.owner_input). The game's size when no frame
# has said:
GAME_SIZE = (1920, 1080)
# AT MOST THIS MANY MOVES A SECOND go down the socket: the game's frame rate.
# A mouse reports at up to 1000 Hz; the newest position waits, the rest drop.
MOVE_HZ = 60
# Qt's key -> the bot's key name (platform/wl/vkeyboard.KEYS). Letters and
# digits are added below. Anything not here is not sent -- F11/F12 included:
# F12 is the panic key (gui/panic), never the game's.
QT_KEYS = {
    Qt.Key_Space: "space", Qt.Key_Escape: "escape", Qt.Key_Return: "enter",
    Qt.Key_Enter: "enter", Qt.Key_Shift: "shift", Qt.Key_Control: "ctrl",
    Qt.Key_Alt: "alt", Qt.Key_Tab: "tab", Qt.Key_Backspace: "backspace",
    Qt.Key_Comma: "comma", Qt.Key_Period: "period", Qt.Key_Slash: "slash",
    Qt.Key_Minus: "minus", Qt.Key_Equal: "equal", Qt.Key_BracketLeft: "leftbracket",
    Qt.Key_BracketRight: "rightbracket", Qt.Key_Semicolon: "semicolon",
    Qt.Key_Apostrophe: "apostrophe", Qt.Key_QuoteLeft: "grave",
    Qt.Key_Backslash: "backslash", Qt.Key_PageUp: "pageup",
    Qt.Key_PageDown: "pagedown", Qt.Key_Home: "home", Qt.Key_End: "end",
    Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right",
    **{getattr(Qt, f"Key_{c}"): c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{getattr(Qt, f"Key_{n}"): str(n) for n in range(10)},
    **{getattr(Qt, f"Key_F{n}"): f"f{n}" for n in range(1, 11)},
}
QT_BUTTONS = {Qt.LeftButton: "left", Qt.RightButton: "right", Qt.MiddleButton: "middle"}
# {key} is the panic key as set (safety.panic_key), filled in by take_control_hint
TAKE_CONTROL_HINT = "You have the controls: click the picture, then play. {key} stops the bot."


class Picture:
    """A decoded frame: the QImage, and the pixels it is drawn from.

    The image is built over OpenCV's array without a copy, so the array is
    kept beside it for as long as anything can draw the image.
    """
    __slots__ = ("image", "pixels")

    def __init__(self, image: QImage, pixels):
        self.image = image
        self.pixels = pixels

    def width(self) -> int:
        return self.image.width()

    def height(self) -> int:
        return self.image.height()


NO_PICTURE = "No game picture yet. Press Start and the bot's view appears here."
# NOT "Press Start" WHILE THE BAR SAYS RUNNING (UI panel round 2, 2026-10-22)
NO_PICTURE_RUNNING = "Working… the bot's view appears here when it sends its first picture."


def decode(path: str, full: bool = True) -> tuple[Picture | None, str]:
    """(the picture, "") or (None, why), at full or half size. Safe on any
    thread."""
    import cv2
    import numpy as np
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except (FileNotFoundError, OSError):
        return None, f"frame not found:\n{path}"
    mode = cv2.IMREAD_COLOR if full else cv2.IMREAD_REDUCED_COLOR_2
    bgr = cv2.imdecode(data, mode) if data.size else None
    if bgr is None:
        # The bot rewrites ONE fixed frame path continuously, so catching
        # it mid-write is routine rather than exceptional.
        return None, "frame could not be decoded"
    # BGRA in memory is what QImage calls RGB32 on a little-endian machine,
    # which is the format the raster engine draws without converting.
    bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    image = QImage(bgra.data, bgra.shape[1], bgra.shape[0], bgra.strides[0],
                   QImage.Format_RGB32)
    return Picture(image, bgra), ""


class _Decoder(QObject):
    """Decodes the newest requested frame on its own thread.

    A request made while one is being decoded replaces the one waiting, so a
    GUI that falls behind skips frames instead of queueing them.
    """
    decoded = Signal(object, object)     # (Frame, Picture)
    failed = Signal(object, str)         # (Frame, why)

    def __init__(self, parent=None):
        super().__init__(parent)
        # ONE OPENCV THREAD IN THE GUI. Its pool's workers spin after every
        # parallel call: MEASURED, the full decode cost 26.8 ms of CPU a
        # frame with the pool and 6.0 without, in the same 5 ms of wall time.
        # Nothing else in the GUI process uses OpenCV.
        import cv2
        cv2.setNumThreads(1)
        self._cond = threading.Condition()
        self._pending: tuple | None = None
        self._stopped = False
        self.skipped = 0
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="hivemind-gui-decode")
        self._thread.start()

    def request(self, event: Frame, full: bool = True) -> None:
        with self._cond:
            if self._pending is not None:
                self.skipped += 1
            self._pending = (event, full)
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._pending is None and not self._stopped:
                    self._cond.wait()
                if self._stopped:
                    return
                (event, full), self._pending = self._pending, None
            try:
                picture, why = decode(event.path, full)
            except Exception as exc:          # never let a frame end the thread
                picture, why = None, f"frame could not be decoded: {exc}"
            try:
                if picture is not None:
                    self.decoded.emit(event, picture)
                else:
                    self.failed.emit(event, why)
            except RuntimeError:
                return                        # the window has gone

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify()


class LiveView(QWidget):
    """Scaled frame with detection boxes drawn in frame coordinates."""

    # STREAM MODE DRAWS THIS SAME PICTURE (DESIGN 8dv). A mirror is handed
    # each frame as decoded here, rather than reading and decoding the file a
    # second time: MEASURED offscreen, 3.1 ms a frame (median of 25 saved
    # 1920x1080 frames, var/routes/attempt-432), which at the live view's
    # then 20 fps was 6% of a core, and another 8 MB pixmap. `shown` fires
    # when the picture is SHOWN (8eb), so a mirror moves on the same beat as
    # this view, and a mirror counts towards the size it is decoded at.
    shown = Signal(object, object)       # (Frame, Picture)
    held = Signal(str)                   # why the picture stopped moving

    def mirror(self, source: "LiveView") -> None:
        """Show whatever `source` shows, from its decoded picture."""
        source._mirrors.append(self)        # so it decodes at our size too
        source.shown.connect(self._show_decoded)
        source.held.connect(self._degrade)
        if source._picture is not None:
            self._show_decoded(source._frame, source._picture)
            if source._missing:
                self._degrade(source._why)

    def __init__(self, parent=None):
        super().__init__(parent)
        # THE WORDS ON A LANDMARK'S BRACKETS ("honey", "pollen", "blue panel
        # (text not read)"): on in the main window, where they are how the
        # vision is checked; off on the stream's HUD, where they sat on the
        # game's own counters (the owner's screen, 2026-10-06)
        self.landmark_words = True
        # the size above which this view wants the full frame (FULL_ABOVE)
        self.full_above = FULL_ABOVE
        self.setMinimumSize(320, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Every paint covers the whole widget (the picture, or the panel
        # colour around and without it), so Qt need not paint what is under.
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._picture: Picture | None = None
        self._frame: Frame | None = None
        self._missing = False
        self._decoder: _Decoder | None = None
        self._mirrors: list = []
        # decoded frames waiting for their moment, oldest first: (due, event,
        # picture), `due` on time.time()'s clock like Frame.at
        self._waiting: deque = deque()
        self._present = QTimer(self)
        self._present.setSingleShot(True)
        self._present.setTimerType(Qt.PreciseTimer)
        self._present.timeout.connect(self._due)
        self.late = 0                    # shown the moment they were decoded
        self.dropped = 0                 # decoded, then overtaken

        # TAKE CONTROL (RL1b step 3): off until `set_take_control`
        self.control = None              # where GameInput goes: bridge.send
        self.taking = False
        self.panic_key = "F12"           # as set: read again at each take control
        self._held_keys: set[str] = set()
        self._held_buttons: set[str] = set()
        self._move_at = 0.0
        self._move_wait: tuple | None = None
        self._move_timer = QTimer(self)
        self._move_timer.setSingleShot(True)
        self._move_timer.timeout.connect(self._send_waiting_move)
        self.sent = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._why = ""                       # the technical reason, for the tooltip
        self._hint = QLabel(NO_PICTURE)
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color: {theme.TEXT_FAINT};")
        layout.addWidget(self._hint)

    def show_frame(self, event: Frame) -> None:
        """Hand the frame to the decoder. Returns at once."""
        if self._decoder is None:
            self._decoder = _Decoder(self)
            self._decoder.decoded.connect(self._decoded)
            self._decoder.failed.connect(self._failed)
            self.destroyed.connect(self._decoder.stop)
        self._decoder.request(event, full=self._needs_full())

    def _needs_full(self) -> bool:
        """Does any view showing this picture need more than FULL_ABOVE?"""
        needed = False
        for view in [self] + list(self._mirrors):
            try:
                limit = view.full_above
                if view.isVisible() and (view.width() > limit[0]
                                         or view.height() > limit[1]):
                    needed = True
            except RuntimeError:           # a closed stream window's view
                self._mirrors.remove(view)
        return needed

    def _decoded(self, event: Frame, picture: Picture) -> None:
        """A picture is ready: show it when its capture time comes round."""
        due = float(getattr(event, "at", 0.0) or 0.0) + PRESENT_DELAY_S
        wait = due - time.time()
        if wait <= 0.0 or wait > PRESENT_MOST_S:
            if wait <= 0.0:
                self.late += 1
            self._waiting.clear()
            self._present.stop()
            self._put(event, picture)
            return
        self._waiting.append((due, event, picture))
        while len(self._waiting) > PRESENT_QUEUE:
            self._waiting.popleft()
            self.dropped += 1
        if not self._present.isActive():
            self._arm()

    def _arm(self) -> None:
        if self._waiting:
            wait = self._waiting[0][0] - time.time()
            self._present.start(max(0, round(wait * 1000.0)))

    def _due(self) -> None:
        now = time.time()
        ready = None
        while self._waiting and self._waiting[0][0] <= now + 0.001:
            if ready is not None:
                self.dropped += 1
            ready = self._waiting.popleft()
        if ready is not None:
            self._put(ready[1], ready[2])
        self._arm()

    def _put(self, event: Frame, picture: Picture) -> None:
        self._show_decoded(event, picture)
        self.shown.emit(event, picture)

    def _failed(self, event: Frame, why: str) -> None:
        self._frame = event
        self._degrade(why)

    def _show_decoded(self, event: Frame | None, picture: Picture) -> None:
        self._frame = event
        self._missing = False
        self._hint.setVisible(False)
        self._picture = picture
        self.update()

    def _degrade(self, why: str) -> None:
        """Hold the last good frame, and say why it has stopped moving.

        Two faults used to meet here. `_hint` is hidden for good on the first
        successful frame and was never made visible again, and paintEvent
        returned early on `_missing` -- so the pane became a bare dark
        rectangle with no image AND no explanation. Because a partially
        written file fails to decode often, it flickered empty during normal
        operation and stayed empty forever once the bot stopped writing.

        Keeping the last frame is the useful behaviour: a frozen picture
        labelled "stale" tells you the bot stopped; an empty panel does not.
        """
        self._missing = True
        self._why = why
        # PLAIN WORDS ON THE PANE, the path in the tooltip (UI panel
        # 2026-10-21: 5 of 8 readers saw a developer's file path here)
        self._hint.setText(self._no_picture() if why.startswith("frame not found") else why)
        self._hint.setToolTip(why)
        # the centred label is for when there is nothing at all to show;
        # otherwise the reason is drawn over the held frame
        self._hint.setVisible(self._picture is None)
        self.update()
        self.held.emit(why)

    def _no_picture(self) -> str:
        return NO_PICTURE_RUNNING if getattr(self, "_bot_running", False) else NO_PICTURE

    def set_running(self, on: bool) -> None:
        """The empty-pane words follow the run state (the shell's bottom bar)."""
        self._bot_running = bool(on)
        if self._hint.text() in (NO_PICTURE, NO_PICTURE_RUNNING):
            self._hint.setText(self._no_picture())

    # ---- take control (RL1b step 3) ----------------------------------------
    def set_take_control(self, on: bool, send=None) -> None:
        """While on, this view forwards the owner's mouse and keys to the game
        through `send` (the bridge's send: GameInput down the socket). Off
        lets go of everything it holds first."""
        on = bool(on)
        if send is not None:
            self.control = send
        if on == self.taking:
            return
        if not on:
            self.release_held()
        self.taking = on
        self.setMouseTracking(on)
        self.setFocusPolicy(Qt.StrongFocus if on else Qt.NoFocus)
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        if on:
            from ...world.settings import panic_key_name
            self.panic_key = panic_key_name()
        self.setToolTip(self.take_control_hint() if on else "")
        self.update()

    def take_control_hint(self) -> str:
        return TAKE_CONTROL_HINT.format(key=self.panic_key)

    def game_point(self, x: float, y: float) -> tuple[float, float] | None:
        """A point on this widget in the game's pixels, or None off the
        picture (the letterbox bars). The same fit as paintEvent's."""
        gw, gh = GAME_SIZE
        if self._frame is not None and self._frame.width and self._frame.height:
            gw, gh = self._frame.width, self._frame.height
        scale = min(self.width() / gw, self.height() / gh)
        if scale <= 0:
            return None
        ox = (self.width() - gw * scale) / 2
        oy = (self.height() - gh * scale) / 2
        fx, fy = (x - ox) / scale, (y - oy) / scale
        if not (0 <= fx < gw and 0 <= fy < gh):
            return None
        return fx, fy

    def _send(self, **fields) -> None:
        if self.control is None:
            return
        self.sent += 1
        self.control(GameInput(**fields))

    def _move(self, pos, now: float | None = None) -> None:
        """A move, at most MOVE_HZ a second: one inside the gap waits on a
        timer, and a newer one replaces it."""
        point = self.game_point(pos.x(), pos.y())
        if point is None:
            return
        now = time.monotonic() if now is None else now
        wait = self._move_at + 1.0 / MOVE_HZ - now
        if wait > 0:
            self._move_wait = point
            if not self._move_timer.isActive():
                self._move_timer.start(max(1, round(wait * 1000)))
            return
        self._move_wait = None
        self._move_at = now
        self._send(op="move", x=point[0], y=point[1])

    def _send_waiting_move(self) -> None:
        if self._move_wait is not None and self.taking:
            point, self._move_wait = self._move_wait, None
            self._move_at = time.monotonic()
            self._send(op="move", x=point[0], y=point[1])

    def _flush_move(self, pos) -> bool:
        """The pointer exactly here now (before a button): False off the picture."""
        point = self.game_point(pos.x(), pos.y())
        if point is None:
            return False
        self._move_timer.stop()
        self._move_wait = None
        self._move_at = time.monotonic()
        self._send(op="move", x=point[0], y=point[1])
        return True

    def release_held(self) -> None:
        """Every key and button this view put down comes up, then the bot
        lets go of everything (release_all): on hand-back, focus loss, hide."""
        if not (self._held_keys or self._held_buttons or self.taking):
            return
        for key in sorted(self._held_keys):
            self._send(op="key_up", key=key)
        for button in sorted(self._held_buttons):
            self._send(op="up", button=button)
        self._held_keys.clear()
        self._held_buttons.clear()
        self._move_timer.stop()
        self._move_wait = None
        self._send(op="release_all")

    def mouseMoveEvent(self, event) -> None:
        # MOVES ONLY WITH FOCUS, as a game window takes the pointer only once
        # clicked: on Hyprland the owner's mouse crosses this window on the
        # way to the nested one, and must not drag the game's pointer along.
        if self.taking and self.hasFocus():
            self._move(event.position())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if not self.taking:
            return super().mousePressEvent(event)
        self.setFocus(Qt.MouseFocusReason)
        button = QT_BUTTONS.get(event.button())
        if button and self._flush_move(event.position()):
            self._held_buttons.add(button)
            self._send(op="down", button=button)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if not self.taking:
            return super().mouseReleaseEvent(event)
        button = QT_BUTTONS.get(event.button())
        if button in self._held_buttons:
            self._flush_move(event.position())      # off the picture: let go anyway
            self._held_buttons.discard(button)
            self._send(op="up", button=button)
        event.accept()

    def wheelEvent(self, event) -> None:
        if not (self.taking and self.hasFocus()):
            return super().wheelEvent(event)
        notches = -round(event.angleDelta().y() / 120)     # the bot's: positive is down
        if notches:
            self._send(op="scroll", steps=notches)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if not self.taking:
            return super().keyPressEvent(event)
        key = QT_KEYS.get(event.key())
        if key and not event.isAutoRepeat() and key not in self._held_keys:
            self._held_keys.add(key)
            self._send(op="key_down", key=key)
        event.accept()

    def keyReleaseEvent(self, event) -> None:
        if not self.taking:
            return super().keyReleaseEvent(event)
        key = QT_KEYS.get(event.key())
        if key and not event.isAutoRepeat() and key in self._held_keys:
            self._held_keys.discard(key)
            self._send(op="key_up", key=key)
        event.accept()

    def focusNextPrevChild(self, forward: bool) -> bool:
        return False if self.taking else super().focusNextPrevChild(forward)  # Tab is the game's

    def focusOutEvent(self, event) -> None:
        if self.taking and (self._held_keys or self._held_buttons):
            self.release_held()
        super().focusOutEvent(event)

    def hideEvent(self, event) -> None:
        if self.taking:
            self.release_held()
        super().hideEvent(event)

    def _paint_control(self, painter: QPainter) -> None:
        """The amber frame and the one line that says the picture is live."""
        painter.save()
        colour = QColor(theme.ACCENT)
        painter.setPen(QPen(colour, 3 if self.hasFocus() else 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5))
        font = QFont(theme.SANS.split(",")[0], 9)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        text = (self.take_control_hint() if not self.hasFocus() else
                f"You have the controls. {self.panic_key} stops the bot.")
        metrics = QFontMetrics(font)
        w, h = metrics.horizontalAdvance(text) + 20, metrics.height() + 8
        box = QRectF((self.width() - w) / 2, self.height() - h - 10, w, h)
        path = QPainterPath()
        path.addRoundedRect(box, h / 2, h / 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(PILL_FILL)
        painter.drawPath(path)
        painter.setPen(colour)
        painter.drawText(box, Qt.AlignCenter, text)
        painter.restore()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        if self.taking:
            # LAST, over everything that returns early below
            try:
                self._paint_frame(painter)
            finally:
                self._paint_control(painter)
            return
        self._paint_frame(painter)

    def _paint_frame(self, painter: QPainter) -> None:
        if self._picture is None:
            painter.fillRect(self.rect(), QColor(theme.BG_PANEL))
            return          # nothing ever arrived; the centred hint says so

        # letterbox the frame into the widget, preserving aspect
        image = self._picture.image
        scaled = image.size().scaled(self.size(), Qt.KeepAspectRatio)
        ox = (self.width() - scaled.width()) / 2
        oy = (self.height() - scaled.height()) / 2
        if scaled != self.size():
            painter.fillRect(self.rect(), QColor(theme.BG_PANEL))
        if scaled != image.size():
            # MEASURED offscreen (8eb): 1920x1080 into the stream's 1280x720
            # is 0.31 ms smooth against 0.24 fast, and 960x540 into the main
            # window's 580x326 0.10 against 0.05 -- cheap enough not to
            # alias. At 1:1 there is nothing to smooth, and it is a copy.
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(QRectF(ox, oy, scaled.width(), scaled.height()),
                          image, QRectF(image.rect()))

        if self._missing:
            # A held frame must be visibly held. An unmarked frozen picture
            # reads as a working live view, which is the wrong answer.
            painter.fillRect(self.rect(), QColor(0, 0, 0, 130))
            painter.setPen(QColor(theme.WARN))
            painter.setFont(QFont(theme.SANS.split(",")[0], 9))
            painter.drawText(self.rect().adjusted(10, 10, -10, -10),
                             Qt.AlignTop | Qt.AlignHCenter,
                             f"last good frame — {self._why}")
            return

        if not self._frame or not self._frame.detections:
            return
        # THE BOXES ARE IN THE FRAME'S PIXELS (Frame.width x height), which a
        # half-size decode is not.
        sx = scaled.width() / max(1, self._frame.width or image.width())
        sy = scaled.height() / max(1, self._frame.height or image.height())
        paint_detections(painter, self._frame.detections, ox, oy, sx, sy,
                         QRectF(self.rect()), landmark_words=self.landmark_words)


def _short(det: dict) -> str:
    """The words for the pill: the detection's `tag`, or its label cut short."""
    text = str(det.get("tag") or det.get("label") or det.get("kind") or "")
    return text if len(text) <= PILL_MOST_CHARS else text[:PILL_MOST_CHARS - 1] + "…"


def _pill(painter: QPainter, text: str, anchor: QPointF, colour: QColor,
          bounds: QRectF, below: float | None = None) -> None:
    """A rounded label whose bottom-left sits at `anchor`, kept on screen.
    With no room above it goes under the mark, its top at `below` -- so the
    HUD's own pills, at the top edge, are labelled without being covered."""
    if not text:
        return
    metrics = QFontMetrics(painter.font())
    w = metrics.horizontalAdvance(text) + 12
    h = metrics.height() + 4
    x = min(max(bounds.left() + 2, anchor.x()), bounds.right() - w - 2)
    y = anchor.y() - h
    if y < bounds.top() + 2 and below is not None:
        y = below + 2
    y = min(max(bounds.top() + 2, y), bounds.bottom() - h - 2)
    box = QRectF(x, y, w, h)
    path = QPainterPath()
    path.addRoundedRect(box, PILL_RADIUS, PILL_RADIUS)
    edge = QColor(colour)
    edge.setAlpha(170)
    painter.setPen(QPen(edge, 1))
    painter.setBrush(PILL_FILL)
    painter.drawPath(path)
    painter.setPen(QColor(theme.TEXT))
    painter.drawText(box, Qt.AlignCenter, text)
    painter.setBrush(Qt.NoBrush)


def _stroke(painter: QPainter, colour: QColor, width: float, draw) -> None:
    """Draw once dark and wide, then in colour: a line that reads on the
    white flowers and on the dark grass alike."""
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(HALO, width + 2.0))
    draw()
    painter.setPen(QPen(colour, width))
    draw()


def _ring_rect(rect: QRectF) -> QRectF:
    side = max(RING_MIN_PX, rect.width(), rect.height())
    return QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)


def _brackets(painter: QPainter, rect: QRectF) -> None:
    arm = min(BRACKET_PX, rect.width() / 2, rect.height() / 2)
    l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
    for (x, y, dx, dy) in ((l, t, 1, 1), (r, t, -1, 1), (l, b, 1, -1), (r, b, -1, -1)):
        painter.drawLine(QPointF(x, y), QPointF(x + dx * arm, y))
        painter.drawLine(QPointF(x, y), QPointF(x, y + dy * arm))


def paint_detections(painter: QPainter, detections, ox: float, oy: float,
                     sx: float, sy: float, bounds: QRectF,
                     landmark_words: bool = True) -> int:
    """Draw every detection in the look above; returns how many were drawn.
    `ox, oy, sx, sy` map frame pixels to the widget."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    font = QFont(theme.SANS.split(",")[0], 8)
    font.setWeight(QFont.DemiBold)
    painter.setFont(font)
    drawn = 0
    for det in detections or ():
        try:
            x, y = float(det["x"]), float(det["y"])
            w, h = float(det.get("w", 0)), float(det.get("h", 0))
        except (KeyError, TypeError, ValueError):
            continue
        kind = str(det.get("kind", ""))
        colour = QColor(DETECTION_COLOURS.get(kind, theme.TEXT_DIM))
        rect = QRectF(ox + x * sx, oy + y * sy, max(0.0, w * sx), max(0.0, h * sy))
        if kind == "maybe":
            dim = QColor(colour)
            dim.setAlpha(110)
            painter.setPen(QPen(HALO, 1.0))
            painter.setBrush(dim)
            painter.drawEllipse(rect.center(), MAYBE_DOT_PX, MAYBE_DOT_PX)
            painter.setBrush(Qt.NoBrush)
        elif kind in ("token", "target"):
            ring = _ring_rect(rect)
            width = 3.0 if kind == "target" else 2.0
            if kind == "target":
                fill = QColor(colour)
                fill.setAlpha(45)
                painter.setPen(Qt.NoPen)
                painter.setBrush(fill)
                painter.drawEllipse(ring)
            _stroke(painter, colour, width, lambda: painter.drawEllipse(ring))
            _pill(painter, _short(det), QPointF(ring.right() - 4, ring.top() + 2),
                  colour, bounds, below=ring.bottom())
        elif kind == "mob":
            _stroke(painter, colour, 2.0, lambda: painter.drawRoundedRect(rect, 4, 4))
            _pill(painter, _short(det), QPointF(rect.left(), rect.top() - 2), colour,
                  bounds, below=rect.bottom())
        else:
            _stroke(painter, colour, 2.0, lambda: _brackets(painter, rect))
            if landmark_words:
                _pill(painter, _short(det), QPointF(rect.left(), rect.top() - 2), colour,
                      bounds, below=rect.bottom())
        drawn += 1
    painter.restore()
    return drawn

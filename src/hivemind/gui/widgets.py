"""Small painted widgets the panels are built from.

Qt's stock controls are fine for a settings dialog and wrong for a dashboard you
leave on a second monitor for eight hours. These are hand-painted so that:

  * a number and its trend occupy one line instead of a chart widget
  * a countdown reads as urgent without a colour legend
  * a health bar shows the THRESHOLD as well as the value, because "62%" means
    nothing until you know 50% is where a field stops being worth planting

Everything here is pure painting over `theme`. No widget in this file knows what
Bee Swarm is, which keeps the panels free to change their mind about layout.
"""
from __future__ import annotations

import re
import time
from collections import deque

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPointF, QRectF, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import theme


def human_duration(seconds: float, short: bool = False) -> str:
    """'2h 14m', or '14m 03s' once it is close enough to watch."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m" if short else f"{m}m {s:02d}s"
    if seconds < 86400:
        h, rem = divmod(int(seconds), 3600)
        return f"{h}h" if short else f"{h}h {rem // 60:02d}m"
    d, rem = divmod(int(seconds), 86400)
    return f"{d}d" if short else f"{d}d {rem // 3600:02d}h"


UNITS = ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K"))


def human_number(value: float) -> str:
    """10,334,621 -> '10.3M'. Dashboards need the magnitude, not the digits.

    The unit is re-checked AFTER rounding. Picking it first gave
    999,999 -> "1000K": the value is under a million so K was chosen, then
    999.999 rounded to 1000.0. When rounding spills past 1000 the next LARGER
    unit is used instead, giving "1.0M".
    """
    for index, (limit, suffix) in enumerate(UNITS):
        if abs(value) < limit:
            continue
        scaled = value / limit
        rounded = round(scaled, 1) if abs(scaled) < 100 else float(round(scaled))
        if abs(rounded) >= 1000 and index > 0:
            limit, suffix = UNITS[index - 1]          # T > B > M > K, so -1 is larger
            scaled = value / limit
            rounded = round(scaled, 1)
        places = 1 if abs(rounded) < 100 else 0
        return f"{rounded:,.{places}f}{suffix}"
    return f"{value:,.0f}"


def can_animate(widget) -> bool:
    """Can anyone see `widget` move? A page that is not shown, or a window
    that is minimised, jumps straight to the new value: nothing animates out
    of sight (the bot shares this PC)."""
    try:
        return widget.isVisible() and not widget.window().isMinimized()
    except RuntimeError:                  # a widget Qt has already deleted
        return False


class Glide(QVariantAnimation):
    """One number eased from where it is to where it is going (ease-out).

    `to(end)` starts from wherever the last glide had got to and LANDS ON
    `end` EXACTLY: the last step is `end` itself, not the interpolation's
    float (0.1 + (0.3 - 0.1) * 1.0 is not 0.3). Tweened only on change and
    only where it can be seen (`can_animate`); otherwise it jumps."""

    def __init__(self, owner: QWidget, step, ms: int = 600, start: float | None = None):
        super().__init__(owner)
        self._owner, self._step = owner, step
        self.now = start
        self._end = start
        self.setDuration(ms)
        self.setEasingCurve(QEasingCurve.OutCubic)
        self.valueChanged.connect(self._frame)
        self.finished.connect(self._land)

    def _frame(self, value) -> None:
        self.now = float(value)
        self._step(self.now)

    def _land(self) -> None:
        self.now = self._end
        self._step(self._end)

    def to(self, end: float) -> None:
        end = float(end)
        self.stop()
        self._end = end
        if self.now is None or self.now == end or not can_animate(self._owner):
            self.now = end
            self._step(end)
            return
        self.setStartValue(self.now)
        self.setEndValue(end)
        self.start()


class Card(QFrame):
    """A titled panel. Optionally carries a count badge in its header."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        header = QWidget()
        header.setStyleSheet("background: transparent;")
        row = QHBoxLayout(header)
        row.setContentsMargins(12, 9, 12, 5)
        row.setSpacing(8)

        self._title = QLabel("\u2b22  " + title.upper())
        self._title.setObjectName("PanelTitle")
        self._title.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._title)

        self._badge = QLabel("")
        self._badge.setStyleSheet(
            f"color: {theme.BG}; background: {theme.ACCENT};"
            " border-radius: 7px; padding: 0 6px; font-size: 10px;"
            " font-weight: 700;")
        self._badge.setVisible(False)
        row.addWidget(self._badge)
        row.addStretch(1)

        self._subtitle = QLabel(subtitle)
        self._subtitle.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        row.addWidget(self._subtitle)
        self._outer.addWidget(header)

        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        self._body_layout = QVBoxLayout(self.body)
        self._body_layout.setContentsMargins(10, 0, 10, 10)
        self._body_layout.setSpacing(6)
        self._outer.addWidget(self.body, 1)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self._body_layout.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self._body_layout.addLayout(layout)

    def set_badge(self, text: str, colour: str = "") -> None:
        colour = colour or theme.ACCENT      # read now: the shell recolours theme
        self._badge.setText(text)
        self._badge.setVisible(bool(text))
        self._badge.setStyleSheet(
            f"color: {theme.BG}; background: {colour};"
            " border-radius: 7px; padding: 0 6px; font-size: 10px;"
            " font-weight: 700;")

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)

    def clear_body(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


class ElidedLabel(QLabel):
    """One line that ends in "…" when it does not fit, the whole text in the
    tooltip (UI panel 2026-10-21: labels were cut mid-word, or pushed the
    window 2,383 px wide). `text()` is the whole text, not the shown one."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(20)
        self.setText(text)

    def setText(self, text) -> None:  # noqa: N802 (Qt's name)
        self._full = str(text or "")
        self._fit()

    def text(self) -> str:
        return self._full

    def setFixedWidth(self, width: int) -> None:  # noqa: N802 (Qt's name)
        # The Ignored policy let the row layout widen a fixed-width label over
        # its neighbour (UI panel 2026-10-22: Thinking tag over its text, the
        # decision option over its bar, Economy name over its sparkline).
        super().setFixedWidth(width)
        self.setSizePolicy(QSizePolicy.Fixed, self.sizePolicy().verticalPolicy())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(20, self.width()))
        QLabel.setText(self, shown)
        self.setToolTip(self._full if shown != self._full else "")


class EmptyState(QFrame):
    """What an empty page will hold, said kindly: the game's icon, a short
    title and one plain line, centred (UI panel 2026-10-21: an empty chart
    box read as broken). `pixmap` is any QPixmap, e.g. gameicons.pixmap."""

    def __init__(self, pixmap, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Empty")
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 36, 24, 36)
        box.setSpacing(8)
        box.setAlignment(Qt.AlignCenter)
        icon = QLabel()
        icon.setPixmap(pixmap)
        icon.setAlignment(Qt.AlignCenter)
        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.line = QLabel(text)
        self.line.setObjectName("Dim")
        self.line.setWordWrap(True)
        self.line.setAlignment(Qt.AlignCenter)
        self.line.setMaximumWidth(460)
        for w in (icon, self.title):
            box.addWidget(w, 0, Qt.AlignHCenter)
        # NOT ALIGNED, CENTRED BY STRETCH: an aligned label gets no
        # height-for-width, and its wrapped lines were cut off
        middle = QHBoxLayout()
        middle.addStretch(1)
        middle.addWidget(self.line, 100)
        middle.addStretch(1)
        box.addLayout(middle)


class Sparkline(QWidget):
    """A value's recent history as a filled line. No axes, on purpose.

    On a dashboard the shape is the message -- rising, flat, collapsed -- and
    axes would cost more pixels than the information is worth. The current value
    is drawn as a dot so the line has an unambiguous "now" end.
    """

    def __init__(self, capacity: int = 120, colour: str = "", parent=None):
        super().__init__(parent)
        self._values: deque[float] = deque(maxlen=capacity)
        self._colour = QColor(colour or theme.ACCENT)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def push(self, value: float) -> None:
        self._values.append(float(value))
        self.update()

    def set_colour(self, colour: str) -> None:
        self._colour = QColor(colour)
        self.update()

    def paintEvent(self, _event) -> None:
        if len(self._values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad = 3.0
        lo, hi = min(self._values), max(self._values)
        span = (hi - lo) or 1.0
        step = (w - pad * 2) / (len(self._values) - 1)

        points = [QPointF(pad + i * step,
                          h - pad - (v - lo) / span * (h - pad * 2))
                  for i, v in enumerate(self._values)]

        fill = QPainterPath(QPointF(points[0].x(), h))
        for p in points:
            fill.lineTo(p)
        fill.lineTo(points[-1].x(), h)
        fill.closeSubpath()
        gradient = QLinearGradient(0, 0, 0, h)
        faded = QColor(self._colour)
        faded.setAlpha(70)
        gradient.setColorAt(0.0, faded)
        transparent = QColor(self._colour)
        transparent.setAlpha(0)
        gradient.setColorAt(1.0, transparent)
        painter.fillPath(fill, QBrush(gradient))

        line = QPainterPath(points[0])
        for p in points[1:]:
            line.lineTo(p)
        painter.setPen(QPen(self._colour, 1.8))
        painter.drawPath(line)

        painter.setBrush(QBrush(self._colour))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(points[-1], 2.6, 2.6)


class Meter(QWidget):
    """A horizontal bar with an optional threshold tick.

    The tick is the point. A planter at 62% health means nothing on its own;
    against a 50% mark where the field stops being worth replanting, it reads
    instantly.
    """

    def __init__(self, value: float = 0.0, threshold: float | None = None,
                 colour: str = "", height: int = 6, parent=None):
        colour = colour or theme.ACCENT
        super().__init__(parent)
        self._value = value
        self._shown = value              # what is drawn: `_value`, or on its way there
        self._glide = None
        self._threshold = threshold
        self._colour = QColor(colour)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # EASED WHEN ASKED (gui/simple): above 0, a new value glides there over
    # this many ms. 0 -- every bar the Advanced window draws -- jumps.
    ease_ms = 0

    def set_value(self, value: float, colour: str | None = None) -> None:
        self._value = max(0.0, min(1.0, value))
        if colour:
            self._colour = QColor(colour)
        if not self.ease_ms:
            self._show(self._value)
            return
        if self._glide is None:
            self._glide = Glide(self, self._show, self.ease_ms, start=self._shown)
        self._glide.to(self._value)

    def _show(self, value: float) -> None:
        self._shown = value
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        radius = h / 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.BG_RAISED))
        painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        if self._shown > 0:
            painter.setBrush(self._colour)
            painter.drawRoundedRect(
                QRectF(0, 0, max(h, w * self._shown), h), radius, radius)

        if self._threshold is not None:
            x = w * self._threshold
            painter.setPen(QPen(QColor(theme.TEXT_FAINT), 1))
            painter.drawLine(QPointF(x, -1), QPointF(x, h + 1))


class Ring(QWidget):
    """Circular progress with the value in the middle. Used for growth."""

    def __init__(self, diameter: int = 46, colour: str = "", parent=None):
        colour = colour or theme.ACCENT
        super().__init__(parent)
        self._value = 0.0
        self._shown = 0.0
        self._glide = None
        self._label = ""
        self._fixed_label = None
        self._colour = QColor(colour)
        self.setFixedSize(diameter, diameter)

    ease_ms = 0                          # as Meter.ease_ms: 0 jumps

    def set_value(self, value: float, label: str | None = None,
                  colour: str | None = None) -> None:
        self._value = max(0.0, min(1.0, value))
        # no label given: the percentage, counting with the arc as it grows
        self._fixed_label = label
        if colour:
            self._colour = QColor(colour)
        if not self.ease_ms:
            self._show(self._value)
            return
        if self._glide is None:
            self._glide = Glide(self, self._show, self.ease_ms, start=self._shown)
        self._glide.to(self._value)

    def _show(self, value: float) -> None:
        self._shown = value
        self._label = (self._fixed_label if self._fixed_label is not None
                       else f"{value * 100:.0f}")
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        thickness = 4.0
        box = QRectF(thickness / 2, thickness / 2,
                     side - thickness, side - thickness)

        painter.setPen(QPen(QColor(theme.BG_RAISED), thickness))
        painter.drawArc(box, 0, 360 * 16)
        painter.setPen(QPen(self._colour, thickness, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(box, 90 * 16, int(-self._shown * 360 * 16))

        painter.setPen(QColor(theme.TEXT))
        font = QFont(theme.MONO.split(",")[0])
        font.setPixelSize(int(side * 0.28))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, self._label)


class Countdown(QLabel):
    """A deadline that ticks itself and reddens as it closes.

    Self-updating matters: a countdown fed only by events freezes whenever the
    bot goes quiet, which is exactly when you are looking at it wondering
    whether anything is still alive.
    """

    def __init__(self, deadline: float = 0.0, warn_s: float = 900.0,
                 critical_s: float = 300.0, parent=None):
        super().__init__(parent)
        self.deadline = deadline
        self.warn_s = warn_s
        self.critical_s = critical_s
        self.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-family: {theme.MONO}; font-size: 11px;")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        self.refresh()

    def set_deadline(self, deadline: float) -> None:
        self.deadline = deadline
        self.refresh()

    def refresh(self) -> None:
        if not self.deadline:
            self.setText("—")
            return
        left = self.deadline - time.time()
        # A MARK AS WELL AS A COLOUR (UI panel 2026-10-21, colourblind): "!"
        # soon, "!!" very soon, so the red and amber rows read without colour
        if left <= 0:
            self.setText("ready")
            colour = theme.GOOD
        else:
            mark = "!! " if left <= self.critical_s else "! " if left <= self.warn_s else ""
            self.setText(mark + human_duration(left))
            if left <= self.critical_s:
                colour = theme.BAD
            elif left <= self.warn_s:
                colour = theme.WARN
            else:
                colour = theme.TEXT_DIM
        self.setStyleSheet(
            f"color: {colour}; font-family: {theme.MONO}; font-size: 11px;")


class Pill(QLabel):
    """A small coloured tag: a seed name, a severity, a field."""

    def __init__(self, text: str, colour: str = "", parent=None):
        super().__init__(text, parent)
        self.set_colour(colour or theme.TEXT_DIM)

    def set_colour(self, colour: str) -> None:
        tint = QColor(colour)
        tint.setAlpha(38)
        self.setStyleSheet(
            f"color: {colour}; background: rgba({tint.red()},{tint.green()},"
            f"{tint.blue()},0.16); border-radius: 4px; padding: 1px 7px;"
            " font-size: 10px; font-weight: 600;")


class Trend(QLabel):
    """A signed percentage with an arrow, coloured by direction."""

    def __init__(self, value: float = 0.0, parent=None):
        super().__init__(parent)
        self.set_value(value)

    def set_value(self, value: float) -> None:
        if abs(value) < 0.005:
            self.setText("–")
            colour = theme.TEXT_FAINT
        else:
            arrow = "▲" if value > 0 else "▼"
            self.setText(f"{arrow} {abs(value) * 100:.0f}%")
            colour = theme.GOOD if value > 0 else theme.BAD
        self.setStyleSheet(f"color: {colour}; font-size: 11px; font-weight: 600;")


class CountUp(QLabel):
    """A number that rolls up (or down) to each new value -- ease-out over
    `ms` -- and lands on it EXACTLY (`Glide`). The first value rolls up from
    zero. `fmt` turns the number into its text; None shows a dash."""

    def __init__(self, fmt=human_number, ms: int = 700, parent=None):
        super().__init__("—", parent)
        self._fmt = fmt
        self.value: float | None = None
        self._glide = Glide(self, self._show, ms, start=0.0)

    def set_number(self, value) -> None:
        if value is None:
            self.value = None
            self._glide.stop()
            self.setText("—")
            return
        self.value = float(value)
        self._glide.to(self.value)

    def _show(self, value: float) -> None:
        self.setText(self._fmt(value))


class PulseDot(QWidget):
    """A status dot. While `pulsing`, a ring breathes out of it: redrawn 10
    times a second, and only while it can be seen -- the one animation that
    keeps running (the bot shares this PC)."""

    PERIOD_S = 1.6
    FRAME_MS = 100                       # 10 fps

    def __init__(self, colour: str = theme.GOOD, diameter: int = 10, parent=None):
        super().__init__(parent)
        self._colour = QColor(colour)
        self._d = diameter
        self._phase = 0.0
        self.pulsing = False
        self.setFixedSize(diameter * 3, diameter * 3)
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._tick)

    def set_state(self, colour: str, pulsing: bool) -> None:
        self._colour = QColor(colour)
        self.pulsing = bool(pulsing)
        if not self.pulsing:
            self._phase = 0.0
        self._arm()
        self.update()

    def _arm(self) -> None:
        if self.pulsing and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._arm()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self) -> None:
        if not can_animate(self):
            return                       # minimised: the timer idles, nothing is drawn
        self._phase = (time.monotonic() % self.PERIOD_S) / self.PERIOD_S
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        centre = QPointF(self.width() / 2, self.height() / 2)
        r = self._d / 2
        painter.setPen(Qt.NoPen)
        if self.pulsing:
            halo = QColor(self._colour)
            halo.setAlphaF(0.55 * (1.0 - self._phase))
            painter.setBrush(halo)
            reach = r * (1.0 + 1.6 * self._phase)
            painter.drawEllipse(centre, reach, reach)
        painter.setBrush(self._colour)
        painter.drawEllipse(centre, r, r)


class ModeSwitch(QWidget):
    """Two choices on one track, the chosen one under a gold thumb that slides
    across. A click on the other half -- or the arrow keys, Space or Enter --
    ASKS for it (`chosen`); the window says what is shown (`set_mode`), so the
    switch never claims a mode that did not happen."""

    chosen = Signal(str)

    def __init__(self, modes=("simple", "advanced"), labels=("Simple", "Advanced"),
                 width: int = 206, height: int = 36, parent=None):
        super().__init__(parent)
        self._modes, self._labels = tuple(modes), tuple(labels)
        self.mode = self._modes[0]
        self._pos = 0.0
        self._glide = Glide(self, self._move, 260, start=0.0)
        self.setFixedSize(width, height)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAccessibleName("Window mode")
        self.setToolTip("Simple: the live view, the numbers and what it is thinking.\n"
                        "Advanced: every tab and setting.")

    def set_mode(self, mode: str) -> None:
        if mode not in self._modes:
            return
        self.mode = mode
        self.setAccessibleDescription(self._labels[self._modes.index(mode)])
        self._glide.to(float(self._modes.index(mode)))

    def _move(self, value: float) -> None:
        self._pos = value
        self.update()

    def _ask(self, mode: str) -> None:
        if mode != self.mode:
            self.chosen.emit(mode)

    def mousePressEvent(self, event) -> None:
        half = 0 if event.position().x() < self.width() / 2 else 1
        self._ask(self._modes[half])

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Left:
            self._ask(self._modes[0])
        elif key == Qt.Key_Right:
            self._ask(self._modes[1])
        elif key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._ask(self._modes[1 - self._modes.index(self.mode)])
        else:
            super().keyPressEvent(event)

    def event(self, event) -> bool:
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.HoverEnter, QEvent.HoverLeave):
            self.update()
        elif event.type() == QEvent.FocusIn:
            # THE RING ONLY FOR THE KEYBOARD (CSS's :focus-visible): focus
            # given by a click or by the window opening is not drawn
            self._ring = event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
            self.update()
        elif event.type() == QEvent.FocusOut:
            self._ring = False
            self.update()
        return super().event(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        track = QRectF(0.5, 0.5, w - 1, h - 1)
        lit = self.underMouse() or (self.hasFocus() and getattr(self, "_ring", False))
        painter.setPen(QPen(QColor(theme.ACCENT if lit else "#5a4520"), 1))
        painter.setBrush(QColor(255, 210, 120, 22))
        painter.drawRoundedRect(track, h / 2, h / 2)
        pad = 3.0
        thumb_w = w / 2 - pad
        thumb = QRectF(pad + self._pos * (w - 2 * pad - thumb_w), pad, thumb_w, h - 2 * pad)
        gold = QLinearGradient(0, thumb.top(), 0, thumb.bottom())
        gold.setColorAt(0.0, QColor(theme.ACCENT_HOVER))
        gold.setColorAt(1.0, QColor(theme.ACCENT_DEEP))
        painter.setPen(QPen(QColor("#ffdf8a"), 1))
        painter.setBrush(QBrush(gold))
        painter.drawRoundedRect(thumb, thumb.height() / 2, thumb.height() / 2)
        font = QFont(theme.SANS.split(",")[0])
        font.setPixelSize(13)
        font.setBold(True)
        painter.setFont(font)
        dim, dark = QColor(theme.TEXT_DIM), QColor("#1a1206")
        for i, label in enumerate(self._labels):
            on = max(0.0, 1.0 - abs(self._pos - i))     # how far under the thumb
            colour = QColor(
                round(dim.red() + (dark.red() - dim.red()) * on),
                round(dim.green() + (dark.green() - dim.green()) * on),
                round(dim.blue() + (dark.blue() - dim.blue()) * on))
            painter.setPen(colour)
            painter.drawText(QRectF(i * w / 2, 0, w / 2, h), Qt.AlignCenter, label)


def fit_pill(button) -> None:
    """A "Pill" button wide enough for its own text in bold, which is how a
    checked pill is drawn, plus ~6 px a side. Stats' "Hourly" read "Hourl"
    (the Windows Claude's UI preview check, 2026-10-22); shell's pills did
    this inline since round 2."""
    from PySide6.QtGui import QFontMetrics
    bold = button.font()
    bold.setBold(True)
    button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(button.text()) + 42)


# ---- the search's flash ----------------------------------------------------------
# HOW LONG A SEARCH HIT STAYS LIT: 2.5 s, long enough to find it on a page
# of cards, gone before it is noise (ASSUMED; settings searches elsewhere
# use the same span).
FLASH_MS = 2500


def flash(widget: QWidget, rect=None, ms: int = FLASH_MS) -> QFrame:
    """A ring drawn over `widget` (or over `rect` inside it) for `ms`, then
    gone: where a Ctrl+K search landed (gui/shell.go_to). A child frame on
    top, so the widget's own look is never touched, and clicks pass through."""
    ring = QFrame(widget)
    ring.setObjectName("Flash")
    ring.setAttribute(Qt.WA_TransparentForMouseEvents)
    ring.setStyleSheet(f"QFrame#Flash {{ border: 2px solid {theme.ACCENT};"
                       " border-radius: 10px; background: rgba(245, 170, 28, 0.14); }")
    ring.setGeometry(rect if rect is not None else widget.rect())
    ring.show()
    ring.raise_()
    QTimer.singleShot(ms, ring.deleteLater)
    return ring


# ---- U7: font scale --------------------------------------------------------------
FIXED_FONTS = "hivemindFixedFonts"     # a window property: keep its sizes (the stream)
_SCALED = "hivemindScaledSheet"
_SIZE = re.compile(r"(font-size:\s*)(\d+(?:\.\d+)?)(px|pt)")


def font_scale(value) -> float:
    """gui.font_scale's '115%' as 1.15; anything unreadable is 1.0, and the
    result stays within 80-160 %."""
    try:
        return min(1.6, max(0.8, float(str(value).strip().rstrip("%")) / 100))
    except ValueError:
        return 1.0


def scale_sheet(sheet: str, scale: float) -> str:
    """Every `font-size: N px|pt` in a style sheet times `scale`."""
    return _SIZE.sub(lambda m: f"{m[1]}{max(1, round(float(m[2]) * scale))}{m[3]}", sheet)


class FontScaler(QObject):
    """U7 FONT SCALE, APP-WIDE. The window's text is sized by style sheets
    in px (about 230 setStyleSheet calls, 214 font sizes, counted 2026-10-27),
    which QApplication.setFont alone does not reach. So this filter sees each
    widget as Qt polishes it (and every later sheet change) and rewrites its
    sheet's font sizes once; the app font is scaled for the rest. A window
    with the FIXED_FONTS property (the stream, a 1920x1080 picture for OBS)
    keeps its own sizes. Installed only when the scale is not 100 %.
    ponytail: text painted with its own QFont (graph labels, the live view's
    overlay) and inline <span style='font-size'> HTML is not scaled."""

    def __init__(self, scale: float, base, parent=None):
        super().__init__(parent)
        self.scale = scale
        self.base = base                    # the app font before scaling

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.Polish or (kind == QEvent.StyleChange and isinstance(
                obj, QWidget) and obj.testAttribute(Qt.WA_WState_Polished)):
            if isinstance(obj, QWidget):
                self.restyle(obj)
        return False

    def restyle(self, widget: QWidget) -> None:
        if widget.window().property(FIXED_FONTS):
            if widget.isWindow():
                widget.setFont(self.base)   # its text from the unscaled font
            return
        sheet = widget.styleSheet()
        if "font-size" not in sheet or sheet == widget.property(_SCALED):
            return
        scaled = scale_sheet(sheet, self.scale)
        widget.setProperty(_SCALED, scaled)     # its own StyleChange stops here
        widget.setStyleSheet(scaled)


def apply_font_scale(app, value) -> FontScaler | None:
    """Scale every font in `app` by gui.font_scale `value`, before any window
    is built (gui/app). None at 100 %: nothing installed, nothing changed."""
    scale = font_scale(value)
    if scale == 1.0:
        return None
    base = QFont(app.font())
    font = QFont(base)
    if font.pointSizeF() > 0:
        font.setPointSizeF(font.pointSizeF() * scale)
    else:
        font.setPixelSize(max(1, round(font.pixelSize() * scale)))
    app.setFont(font)
    scaler = FontScaler(scale, base, app)
    app.installEventFilter(scaler)
    return scaler

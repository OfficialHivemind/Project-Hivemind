"""The first second: the logo and the name while the main window builds.

THE OWNER, 2026-10-14: polish the whole program as if ready to ship, with
animations. A
shipped app says who it is before it shows its work; this is that moment.

DRAWN, NOT FADED. A window's opacity is not something Wayland lets a client
set (Qt ignores setWindowOpacity there, e.g. on KDE Wayland), so
the window appears at once and its CONTENT animates: the logo grows into place,
the name and the line under it fade in, a thin amber bar fills. One
QVariantAnimation drives it; nothing repaints once it is over.

NEVER IN THE WAY. The main window is built behind it and shown the moment the
animation ends (SPLASH_MS); if anything here fails, gui/app shows the window
without it.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from . import theme

SPLASH_MS = 1300
SIZE = (520, 320)


class Splash(QWidget):
    def __init__(self, logo: Path | str):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(*SIZE)
        self._logo = QPixmap(str(logo))
        self._t = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(SPLASH_MS)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._tick)

    def _tick(self, value) -> None:
        self._t = float(value)
        self.update()

    def start(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            centre = screen.availableGeometry().center()
            self.move(centre.x() - SIZE[0] // 2, centre.y() - SIZE[1] // 2)
        self.show()
        self.anim.start()

    def finish(self, window) -> None:
        """Show `window` when the animation is over (at once if it is)."""
        def done():
            self.close()
            window.show()
        if self.anim.state() == QVariantAnimation.Running:
            self.anim.finished.connect(done)
        else:
            done()

    def paintEvent(self, event) -> None:
        t = self._t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        card = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(theme.ACCENT).darker(160), 1.2))
        p.setBrush(QColor("#121418"))
        p.drawRoundedRect(card, 18, 18)

        # the logo grows from 82% to full size as it fades in
        if not self._logo.isNull():
            side = 128 * (0.82 + 0.18 * t)
            p.setOpacity(min(1.0, t * 1.6))
            p.drawPixmap(QRectF(card.center().x() - side / 2, 104 - side / 2, side, side),
                         self._logo, QRectF(self._logo.rect()))

        # the name, then the line under it
        name_alpha = max(0.0, min(1.0, (t - 0.25) / 0.45))
        p.setOpacity(name_alpha)
        p.setPen(QColor(theme.ACCENT))
        font = QFont(p.font())
        font.setPixelSize(34)
        font.setWeight(QFont.Black)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 6)
        p.setFont(font)
        p.drawText(QRectF(0, 182, card.width(), 44), Qt.AlignHCenter | Qt.AlignVCenter, "HIVEMIND")
        p.setOpacity(max(0.0, min(1.0, (t - 0.45) / 0.4)))
        p.setPen(QColor(theme.TEXT_DIM))
        small = QFont(p.font())
        small.setPixelSize(14)
        small.setWeight(QFont.Medium)
        small.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        p.setFont(small)
        p.drawText(QRectF(0, 228, card.width(), 24), Qt.AlignHCenter | Qt.AlignVCenter,
                   "the autonomous Bee Swarm AI")

        # a thin bar fills along the bottom
        p.setOpacity(1.0)
        track = QRectF(card.left() + 60, card.bottom() - 34, card.width() - 120, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(track, 2, 2)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(track.topLeft(), QPointF(track.left() + track.width() * t,
                                                          track.bottom())), 2, 2)
        p.end()

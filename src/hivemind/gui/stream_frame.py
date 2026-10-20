"""The stream layout, scaled to whatever window or screen shows it.

THE OWNER, 2026-09-28: "i gota new moniter so fulls creen no fit" -- a 2560x1440
screen at scale 1. The stream layout is
drawn for exactly 1920x1080, OBS's default canvas (gui/stream), and a window
fixed at that size cannot grow: full screen left it in the corner of the new
screen.

So the layout is drawn inside a QGraphicsView that scales all of it to the
window, keeping 16:9 -- black bars if the window is another shape. The design
stays pixel for pixel what it was, at any size: 2560x1440 full screen, a
smaller window, a 4K screen. Only the stream window scales; the main window
keeps the monitor's own pixels.

The StreamWindow inside keeps doing everything it did -- its events, timers,
voice, masks and chat -- and asks this frame (`host`) whenever it needs the
real window: full screen, the screen it is on.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QTransform
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView

from .stream import STREAM_H, STREAM_W


class StreamFrame(QGraphicsView):
    """A top-level window showing `stream` (a StreamWindow) scaled to fit."""

    closed = Signal()

    def __init__(self, stream, parent=None):
        super().__init__(parent)
        self.stream = stream
        self.setWindowTitle(stream.windowTitle())   # what OBS's capture names
        self.setObjectName("StreamFrame")
        scene = QGraphicsScene(self)
        scene.setSceneRect(0, 0, STREAM_W, STREAM_H)
        self.proxy = scene.addWidget(stream)
        self.setScene(scene)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QColor(0, 0, 0))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform
                            | QPainter.TextAntialiasing)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(STREAM_W // 4, STREAM_H // 4)
        self.resize(STREAM_W, STREAM_H)
        stream.host = self
        stream.closed.connect(self.closed)

    # ---- the scale ----------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        """Scale to fill: `fitInView` keeps a margin of its own (1.3296 at
        2560x1440, MEASURED offscreen), which on a full screen is a border."""
        super().resizeEvent(event)
        port = self.viewport()
        scale = min(port.width() / STREAM_W, port.height() / STREAM_H)
        self.setTransform(QTransform.fromScale(scale, scale))
        self.centerOn(STREAM_W / 2, STREAM_H / 2)

    def scale_factor(self) -> float:
        return float(self.transform().m11())

    # ---- the window's own business -------------------------------------------------------
    def changeEvent(self, event) -> None:
        if event.type() == QEvent.WindowStateChange:
            # the header's "Full screen" button is for leaving a window, not
            # for a screen that is already full
            try:
                self.stream.header.full.setVisible(not self.isFullScreen())
            except (AttributeError, RuntimeError):
                pass
        super().changeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_F11:
            self.stream.toggle_full_screen()
            return
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.stream.close()               # its timers, readers and voice stop there
        super().closeEvent(event)

    # ---- what the main window asks of it --------------------------------------------------
    def setting_changed(self, key: str, value) -> None:
        self.stream.setting_changed(key, value)

    def show_fitting(self) -> None:
        self.stream.show_fitting()

"""The local vision model, and a way to ask it about the current screen.

This panel exists to make one thing checkable by eye: whether the model is
actually there. It shipped once as a settings toggle wired to nothing, which is
the failure this whole project is supposed to avoid, so the status line here
reports the real state of the server rather than the state of a checkbox --
running or not, model pulled or not, and the exact command to fix it when not.

The question box is not a toy. It is the same call path the bot uses for an
unknown dialog or a quest board, so asking by hand is how you find out what the
model can and cannot read BEFORE trusting it with a decision. The answer shows
whether it came from the cache, because a cached answer is free and identical
and an uncached one is neither.
"""
from __future__ import annotations

import pathlib

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QWidget)

from .. import theme
from ..widgets import Card

SUGGESTIONS = [
    "What does this dialog say, and what are its buttons?",
    "List every quest objective visible, with its progress.",
    "Is the ground ahead of the character open, or blocked?",
    "Are these hive slots empty, or do they have hives on them?",
]


class _Ask(QObject):
    """Runs one question off the GUI thread.

    A cold model takes seconds to answer; doing that on the GUI thread would
    freeze the whole window, including the live view and the panic status.
    """
    done = Signal(object, str)

    def __init__(self, model, png: bytes, question: str):
        super().__init__()
        self.model, self.png, self.question = model, png, question

    def run(self) -> None:
        answer = self.model.ask(self.png, self.question)
        self.done.emit(answer, self.model.reason)


class VisionPanel(Card):
    """Model status, and a question box against the latest frame."""

    def __init__(self, model=None, parent=None):
        super().__init__("vision model", "ask it about what is on screen", parent)
        if model is None:
            from ...brain.vlm import from_settings
            model = from_settings()
        self.model = model
        self._frame_path = None       # latest frame on disk, set by the window
        self._thread = None
        self._worker = None

        self.status = QLabel("checking…")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px; background: transparent;")
        self.add(self.status)

        asker = QWidget()
        asker.setStyleSheet("background: transparent;")
        row = QHBoxLayout(asker)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.question = QLineEdit()
        self.question.setPlaceholderText(SUGGESTIONS[0])
        self.question.returnPressed.connect(self.ask)
        row.addWidget(self.question, 1)
        self.button = QPushButton("Ask")
        self.button.setObjectName("Primary")
        self.button.clicked.connect(self.ask)
        row.addWidget(self.button)
        self.add(asker)

        self.answer = QLabel("")
        self.answer.setWordWrap(True)
        self.answer.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.answer.setStyleSheet(
            f"color: {theme.TEXT}; background: transparent; padding: 6px 0;")
        self.add(self.answer, 1)

        self.refresh()

    # ---- state ------------------------------------------------------------
    def refresh(self) -> None:
        """Report what is really true of the server, not of a checkbox."""
        if self.model.available():
            self.status.setText(f"{self.model.model} ready — {self.model.stats()}")
            self.status.setStyleSheet(
                f"color: {theme.GOOD}; font-size: 11px; background: transparent;")
            self.set_badge("ready")
            self.button.setEnabled(True)
        else:
            self.status.setText(self.model.reason or "unavailable")
            self.status.setStyleSheet(
                f"color: {theme.WARN}; font-size: 11px; background: transparent;")
            self.set_badge("off")
            self.button.setEnabled(False)

    def set_frame_path(self, path: str) -> None:
        """The window hands us the latest frame PATH.

        A path rather than an array, because the bot already writes the frame
        to disk for the live view and re-encoding a QPixmap would give the
        model a different byte sequence for the same screen -- which would
        quietly defeat the cache.
        """
        self._frame_path = path

    # ---- asking -----------------------------------------------------------
    def ask(self) -> None:
        if self._thread is not None:
            return                       # one question at a time
        if not self._frame_path:
            self.answer.setText("no frame yet — the bot has not sent one.")
            return
        question = self.question.text().strip() or SUGGESTIONS[0]

        try:
            png = pathlib.Path(self._frame_path).read_bytes()
        except OSError as exc:
            self.answer.setText(f"could not read the frame: {exc}")
            return

        self.button.setEnabled(False)
        self.answer.setText("thinking…")
        self._thread = QThread(self)
        self._worker = _Ask(self.model, png, question)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._answered)
        self._thread.start()

    def _answered(self, answer, reason: str) -> None:
        if answer is None:
            # NEVER a fabricated answer. Say what went wrong instead.
            self.answer.setText(f"no answer — {reason or 'the model did not reply'}")
            self.answer.setStyleSheet(
                f"color: {theme.WARN}; background: transparent; padding: 6px 0;")
        else:
            how = "from cache" if answer.cached else f"{answer.seconds:.1f}s"
            self.answer.setText(f"{answer.text}\n\n— {answer.model}, {how}")
            self.answer.setStyleSheet(
                f"color: {theme.TEXT}; background: transparent; padding: 6px 0;")
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        self.refresh()

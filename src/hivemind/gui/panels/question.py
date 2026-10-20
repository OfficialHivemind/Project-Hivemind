"""The Decision Inbox: choices handed back to you.

This is the other half of the owner's autonomy request -- "a option to toggle
where the ai can ask me what paths i want to take and if thats off then it
chooses for me based on what the best build is".

Two rules make this safe to leave running unattended:

  * a pending question NEVER blocks the bot. It keeps doing reversible work
    while this sits here. Anything else and an eight-hour unattended run ends
    four minutes in, stuck behind a dialog nobody was there to answer.
  * every option carries the number behind it, and the one the bot would have
    picked on its own is marked. Answering is then a matter of overriding a
    recommendation, not of reconstructing the reasoning yourself.

A question may carry an expiry. When it lapses the bot takes its own default,
which is shown on the countdown so there is never a surprise.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ...telemetry.events import Question
from .. import theme
from ..widgets import ElidedLabel

# AT MOST THREE ANSWERS A ROW. A card about a fall of the honey names every
# item tied at its price and "None of these" (brain/owned): the four guards
# at 300,000 make five answers, and one row of five is 1,231 px at its
# narrowest, four 1,044 (offscreen, scratch account-fix3/card_width.py) --
# wider than the 960 px the window gives the column the inbox sits in
# (window.py `split.setSizes`).
BUTTONS_A_ROW = 3


def plain_score(value: float, unit: str) -> str:
    """A multiplier in words a child reads ("about 5% better"); any other
    unit as theme.fmt_score has it (UI panel 2026-10-21: "1.05 x" meant
    nothing to the kid, parent and ESL readers)."""
    if unit.strip() != "x":
        return theme.fmt_score(value, unit)
    change = round((value - 1.0) * 100)
    if change == 0:
        return "no change"
    return f"about {abs(change)}% {'better' if change > 0 else 'worse'}"


def countdown_text(left_s: float, default: str) -> str:
    """The lapse, said as what happens, not as a clock running out."""
    if left_s <= 0:
        return f"Time's up: Hivemind picked “{default}”"
    mins = int(left_s // 60)
    when = f"in {mins} min" if mins >= 1 else "in under a minute"
    return f"Hivemind picks “{default}” {when}"


class QuestionCard(QFrame):
    answered = Signal(str, str)          # (question id, chosen label)

    def __init__(self, event: Question, parent=None):
        super().__init__(parent)
        # NOT `self.event`: QWidget.event() is a Qt virtual method, and
        # shadowing it with a data attribute makes Qt try to CALL the
        # Question object on the next event dispatch.
        self.question = event
        self.setObjectName("Panel")
        self.setStyleSheet(
            f"QFrame#Panel {{ background: {theme.BG_PANEL};"
            f" border: 1px solid {theme.WARN}; border-radius: 8px; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 8, 10, 8)
        outer.setSpacing(8)

        # ONE LINE UNTIL OPENED (UI panel 2026-10-21 item 4: the whole card
        # took ~140 px above every tab for all 8 readers): the tag, the
        # question, what happens if nobody answers, and the arrow.
        head = QHBoxLayout()
        head.setSpacing(10)
        tag = QLabel("needs you")
        tag.setStyleSheet(f"color: {theme.WARN}; font-size: 10px;"
                          " font-weight: 700; letter-spacing: 1px;")
        head.addWidget(tag)
        self._line = ElidedLabel(event.question)
        self._line.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        head.addWidget(self._line, 1)
        keep = self._line.sizePolicy()
        keep.setRetainSizeWhenHidden(True)     # opened, the arrow stays at the right
        self._line.setSizePolicy(keep)
        self._countdown = QLabel("")
        self._countdown.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        head.addWidget(self._countdown)
        self.toggle = QPushButton("Answer  ▾")
        self.toggle.setCheckable(True)
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setToolTip("Show the choices")
        self.toggle.toggled.connect(self.set_open)
        head.addWidget(self.toggle)
        outer.addLayout(head)

        self.body = QWidget()
        inner = QVBoxLayout(self.body)
        inner.setContentsMargins(0, 0, 0, 2)
        inner.setSpacing(8)
        title = QLabel(event.question)
        title.setWordWrap(True)
        title.setStyleSheet(f"color: {theme.TEXT}; font-size: 15px; font-weight: 600;")
        inner.addWidget(title)

        if event.context:
            ctx = QLabel(event.context)
            ctx.setWordWrap(True)
            ctx.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
            inner.addWidget(ctx)

        buttons = QGridLayout()
        buttons.setSpacing(8)
        self._buttons: list = []
        for i, option in enumerate(event.options):
            recommended = option.label == event.default
            score_text = plain_score(option.score, option.unit)
            button = QPushButton(f"{option.label}   ({score_text})"
                                 if score_text else option.label)
            if recommended:
                button.setObjectName("Primary")
                button.setToolTip("what the bot would choose on its own")
            if option.why:
                button.setToolTip((button.toolTip() + "\n" if button.toolTip()
                                   else "") + option.why)
            button.clicked.connect(
                lambda _=False, label=option.label: self._choose(label))
            buttons.addWidget(button, i // BUTTONS_A_ROW, i % BUTTONS_A_ROW)
            self._buttons.append(button)
        buttons.setColumnStretch(BUTTONS_A_ROW, 1)
        inner.addLayout(buttons)
        safe = QLabel("In-game items only, no Robux. The bot keeps playing while this waits.")
        safe.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        inner.addWidget(safe)
        outer.addWidget(self.body)
        self.set_open(False)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if event.expires_at:
            self._timer.start(1000)
            self._tick()

    def _tick(self) -> None:
        left = self.question.expires_at - time.time()
        if left <= 0:
            self._timer.stop()
            # lapsing is not an answer from the user; the bot applies its own
            # default. Say so rather than silently vanishing.
            self._countdown.setText(countdown_text(left, self.question.default))
            # AND IT STOPS ASKING: the buttons went on answering a question the
            # bot had already settled (UI review 2026-10-21)
            for button in self._buttons:
                button.setEnabled(False)
            QTimer.singleShot(5000, self.hide)
            return
        self._countdown.setText(countdown_text(left, self.question.default))

    def set_open(self, on: bool) -> None:
        """Open: the whole question and its choices; shut: the one line."""
        self.body.setVisible(on)
        self._line.setVisible(not on)
        if self.toggle.isChecked() != on:
            self.toggle.setChecked(on)
        self.toggle.setText("Hide  ▴" if on else "Answer  ▾")

    def _choose(self, label: str) -> None:
        self._timer.stop()
        self.answered.emit(self.question.id, label)


class DecisionInbox(QWidget):
    """The pending questions, ONE card at a time: the most important (the
    soonest to lapse, then the newest), with "+N more" to step through the rest.

    MEASURED 2026-10-19 (the owner's 5th Windows run, shot.jpg): seven cards
    stacked above the tabs were squeezed to ~38 px each -- seven empty
    rectangles, every word clipped away. One card always has its room."""

    answered = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._cards: dict[str, QuestionCard] = {}
        self._added: dict[str, int] = {}
        self._count = 0
        self._shown: str | None = None
        self._more = QPushButton("")
        self._more.setFlat(True)
        self._more.setToolTip("show the next question that waits for you")
        self._more.setStyleSheet(f"color: {theme.WARN}; text-align: right; padding: 2px 6px;")
        self._more.clicked.connect(self._next)
        self._layout.addWidget(self._more, 0, Qt.AlignRight)
        self.setVisible(False)

    def add(self, event: Question) -> None:
        old = self._cards.get(event.id)
        if old is not None:
            # THE SAME QUESTION AGAIN IS A REPEAT: a gear-goal card is re-sent
            # on every reading while unanswered (brain/goals.Watch), and its
            # context carries the honey, so only the title is compared. A NEW
            # TITLE under the same id is the situation changing -- "the honey
            # is there, check the materials" becoming "Ready to buy" -- and
            # the card is replaced so it says so.
            if old.question.question == event.question:
                return
            self.remove(event.id)
        card = QuestionCard(event)
        card.answered.connect(self._on_answered)
        self._cards[event.id] = card
        self._count += 1
        self._added[event.id] = self._count
        self._layout.insertWidget(0, card)
        self._shown = None                     # a new card may be the most important
        self._show()

    def order(self) -> list[str]:
        """Question ids, most important first: the soonest to lapse, then
        the newest."""
        def key(qid):
            exp = self._cards[qid].question.expires_at or 0
            return (exp <= 0, exp, -self._added[qid])
        return sorted(self._cards, key=key)

    def _show(self) -> None:
        ids = self.order()
        if self._shown not in self._cards:
            self._shown = ids[0] if ids else None
        for qid, card in self._cards.items():
            card.setVisible(qid == self._shown)
        more = len(ids) - 1
        self._more.setText(f"+{more} more  ›" if more > 0 else "")
        self._more.setVisible(more > 0)
        self.setVisible(bool(self._cards))

    def _next(self) -> None:
        ids = self.order()
        if len(ids) > 1:
            at = ids.index(self._shown) if self._shown in ids else -1
            self._shown = ids[(at + 1) % len(ids)]
            self._show()

    @property
    def shown(self) -> str | None:
        return self._shown

    def _on_answered(self, qid: str, label: str) -> None:
        self.answered.emit(qid, label)
        self.remove(qid)

    def remove(self, qid: str) -> None:
        card = self._cards.pop(qid, None)
        self._added.pop(qid, None)
        if card:
            card.setParent(None)
            card.deleteLater()
        if self._shown == qid:
            self._shown = None
        self._show()

    @property
    def pending(self) -> int:
        return len(self._cards)

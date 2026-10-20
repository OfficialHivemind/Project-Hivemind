"""Header bar: connection, autonomy, the run controls, and live vitals.

The autonomy selector is the owner's toggle, and it is a three-way rather than
an on/off because "ask me" is not one behaviour:

  Autopilot        decides everything, never interrupts
  Ask on strategy  asks about builds and big spends, decides the rest
  Ask on notable   asks before anything irreversible or expensive

The vitals strip shows what the bot believes right now -- honey, pollen, bees --
with a dim value when the reading is stale, so "3 bees" and "3 bees, forty
minutes ago" never look the same.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ...telemetry.events import Autonomy
from .. import theme
from ..widgets import ModeSwitch, Sparkline, human_number


TAKE_OVER_TEXT = "Take over"
PASS_BACK_TEXT = "Pass back"
HANDING_OVER_TEXT = "Handing over…"

AUTONOMY_LABELS = [
    ("Autopilot", Autonomy.AUTOPILOT,
     "Decides everything itself. Never interrupts you."),
    ("Ask on strategy", Autonomy.ASK_STRATEGY,
     "Asks about builds and big spends. Handles the rest alone."),
    ("Ask on notable", Autonomy.ASK_NOTABLE,
     "Asks before anything irreversible or expensive."),
]


class Vital(QWidget):
    """One labelled number in the header."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 4, 12, 4)
        box.setSpacing(0)
        self._caption = QLabel(label.upper())
        self._caption.setObjectName("StatLabel")
        self._value = QLabel("—")
        self._value.setObjectName("Stat")
        box.addWidget(self._caption)
        box.addWidget(self._value)
        # a number on a dashboard is worth much more with its recent shape
        # beside it; 431k/hr means little until you can see it climbing
        self._spark = Sparkline(capacity=80, colour=theme.ACCENT)
        self._spark.setFixedHeight(16)
        box.addWidget(self._spark)

    def set(self, value, stale: bool = False) -> None:
        """Accepts a number (formatted compactly) or a pre-made string."""
        if isinstance(value, (int, float)):
            self._value.setText(human_number(value))
            self._spark.push(float(value))
        else:
            self._value.setText(str(value))
        self._value.setStyleSheet(
            f"color: {theme.TEXT_FAINT if stale else theme.TEXT};"
            f" font-family: {theme.MONO}; font-size: 17px; font-weight: 600;")

    def mark_stale(self) -> None:
        """Dim the number without changing it: it is the LAST reading.

        Called when the bot goes away (DESIGN 8du). Nothing ever passed
        `stale=True`, so after a rejoin or a crash the header kept last
        night's honey at full brightness, which reads as live. The next
        reading un-dims it through `set`.
        """
        self._value.setStyleSheet(
            f"color: {theme.TEXT_FAINT};"
            f" font-family: {theme.MONO}; font-size: 17px; font-weight: 600;")


def _restyle(widget) -> None:
    """Re-apply the stylesheet to a widget whose objectName just changed.

    Qt resolves stylesheet selectors when a widget is polished and does not
    redo it when `setObjectName` is called later, so a name set after
    construction has no visible effect until the widget is unpolished and
    polished again. This is the whole reason the handover button never
    changed colour.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class StatusBar(QFrame):
    start_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    # True to take the controls, False to hand them back. One signal rather
    # than two because the button is one button whose meaning flips, and a
    # GUI that can be in a state where BOTH are enabled would be lying about
    # who is driving.
    handover_clicked = Signal(bool)
    autonomy_changed = Signal(object)
    # STREAM MODE (DESIGN 8dv): opens the 1920x1080 stream window. It reads
    # the same events this window does and presses nothing.
    stream_clicked = Signal()
    # THE RUN CONTROLS OR THE NOTE CHANGED: Simple mode's big buttons and its
    # status chip follow this bar (gui/simple), so the two cannot disagree.
    controls_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(14)

        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {theme.BAD}; font-size: 15px;")
        row.addWidget(self._dot)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        name = QLabel("Hivemind")
        name.setObjectName("Hero")
        self._state = QLabel("not connected")
        self._state.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        title_box.addWidget(name)
        title_box.addWidget(self._state)
        row.addLayout(title_box)

        row.addSpacing(10)
        self.honey = Vital("honey")
        self.pollen = Vital("pollen")
        self.bees = Vital("bees")
        self.rate = Vital("honey/hr")
        for vital in (self.honey, self.pollen, self.bees, self.rate):
            row.addWidget(vital)

        row.addStretch(1)

        mode_box = QVBoxLayout()
        mode_box.setSpacing(2)
        mode_label = QLabel("AUTONOMY")
        mode_label.setObjectName("StatLabel")
        self.autonomy = QComboBox()
        for label, value, tip in AUTONOMY_LABELS:
            self.autonomy.addItem(label, value)
            self.autonomy.setItemData(self.autonomy.count() - 1, tip, Qt.ToolTipRole)
        self.autonomy.currentIndexChanged.connect(
            lambda i: self.autonomy_changed.emit(self.autonomy.itemData(i)))
        # NOT A CONTROL YET, so not drawn as one (DESIGN 8du). The farm loop
        # never reads a mode -- brain/autonomy's Arbiter is not wired in --
        # so a pick here was dropped by the bot and snapped back within 20 s.
        # Autopilot is what it actually does: decides everything, asks nothing.
        self.autonomy.setEnabled(False)
        self.autonomy.setToolTip(
            "The bot runs on autopilot: nothing in the farm loop asks "
            "questions yet (brain/autonomy.Arbiter is not wired in), so "
            "there is no other mode to choose.")
        mode_box.addWidget(mode_label)
        mode_box.addWidget(self.autonomy)
        row.addLayout(mode_box)

        self._start = QPushButton("Start  F1")
        self._start.setObjectName("Primary")
        self._start.clicked.connect(self.start_clicked)
        self._pause = QPushButton("Pause  F2")
        self._pause.clicked.connect(self.pause_clicked)
        self._pause.setEnabled(False)
        self._stop = QPushButton("Stop  F3")
        self._stop.setObjectName("Danger")
        self._stop.clicked.connect(self.stop_clicked)
        self._stop.setEnabled(False)

        # TAKE OVER / PASS BACK. Pressing it releases every key and parks the
        # bot at its next step; pressing it again hands the controls back.
        # NOTHING IS LEARNED IN BETWEEN, so the tooltip no longer says it is
        # (DESIGN 8du): scripts/watch_me_play.py is the recorder.
        self._handover = QPushButton(TAKE_OVER_TEXT)
        self._handover.setToolTip(
            "Stop the bot pressing anything and play yourself, until you press "
            "it again. The keys come up at once; the bot then finishes the "
            "step it is in and waits, and this button says so when it has. "
            "The game stays fullscreen, and fullscreen can keep hold of the "
            "mouse pointer.")
        self._handover.clicked.connect(self._toggle_handover)
        self._handover.setMinimumHeight(32)      # its text was cut by 4 px
        self._stream = QPushButton("Stream mode")
        self._stream.setToolTip(
            "Open the 1920x1080 stream layout for OBS: the live view, the "
            "bot's reasoning as it happens, the numbers, and the games chat "
            "can play (Settings › Stream).")
        self._stream.clicked.connect(self.stream_clicked)
        self._stream.setMinimumHeight(32)
        for button in (self._start, self._pause, self._stop, self._handover,
                       self._stream):
            row.addWidget(button)
        # SIMPLE ⇄ ADVANCED, top right (the owner, 2026-10-14). The window
        # connects it and says which page is up (MainWindow.set_mode). The
        # compact one: this row was already the window's widest thing, and
        # every pixel here is a pixel more of minimum window width.
        row.addSpacing(6)
        self.mode_switch = ModeSwitch(width=164, height=32)
        row.addWidget(self.mode_switch)
        self._paused = False
        self._running = False
        self._handed_over = False
        # Asked for, not yet confirmed: the bot has let go of the keys but is
        # finishing its step (StatusUpdate.handing_over).
        self._handing_over = False
        self._connected = False

    def _toggle_handover(self) -> None:
        """Ask for the swap. It is NOT applied here.

        The window sends the command and only moves the button if it actually
        went somewhere, so a press that could not reach the bot leaves the
        label telling the truth about who is still driving. A press while a
        handover is still pending cancels it.
        """
        self.handover_clicked.emit(not (self._handed_over or self._handing_over))

    def set_handed_over(self, handed_over: bool, pending: bool = False) -> None:
        """Reflect who is driving. Called on click AND on the bot's report.

        The bot confirms a handover, so this is driven by what actually
        happened rather than by what was clicked -- a button that says "Pass
        back" while the bot is still walking would be the worst possible lie
        for this particular control.
        """
        self._handed_over = bool(handed_over)
        # PENDING IS ITS OWN STATE (DESIGN 8du): "Pass back" appeared the
        # moment the command was sent, while the step in progress kept
        # pressing keys for up to eleven minutes.
        self._handing_over = bool(pending) and not self._handed_over
        self._handover.setText(
            PASS_BACK_TEXT if self._handed_over else
            HANDING_OVER_TEXT if self._handing_over else TAKE_OVER_TEXT)
        self._handover.setObjectName("Primary" if self._handed_over else "")
        # QT DOES NOT RESTYLE ON AN OBJECT NAME CHANGE. The stylesheet was
        # matched when the widget was first polished, so setting the name
        # afterwards changed nothing on screen and this button never went
        # yellow when the owner took over. It has to be re-polished by hand.
        _restyle(self._handover)
        self._apply_buttons()

    def _apply_buttons(self) -> None:
        """Which of Start/Pause/Stop are live, decided in ONE place.

        THIS WAS A BUG, and a quiet one. Enablement used to be written by
        `set_status`, by `set_connected` and by the handover in three different
        styles, and the handover's version read

            button.setEnabled(not handed_over and button.isEnabled()
                              if not handed_over else False)

        which, when handing back, evaluates to `button.isEnabled()` -- it set
        every button to the value it already had. So taking over disabled
        Start, Pause and Stop and passing back never brought them back.
        The run controls were dead for the rest of the session.
        """
        # PAUSE AND THE HANDOVER ARE MESSAGES, STOP IS NOT (DESIGN 8du). The
        # first two only mean anything to a bot on the other end of the
        # socket; Stop also works on the process, so it stays live whenever
        # something is running -- including the ~40 s join and the gaps
        # between attempts, when the window used to grey it out.
        self._handover.setEnabled(self._connected or self._handed_over
                                  or self._handing_over)
        # A PENDING HANDOVER IS STILL THE BOT DRIVING. It lasts until the
        # step in progress ends -- one whole trip, 670 s in trips.jsonl
        # (attempt 406, cycle 2) -- and keys are pressed all that time, so
        # Stop stays live; only a handover that has taken hold greys it.
        if self._handed_over or self._handing_over:
            self._start.setEnabled(False)
            self._pause.setEnabled(False)
            self._stop.setEnabled(self._running and not self._handed_over)
        else:
            self._start.setEnabled(not self._running)
            self._pause.setEnabled(self._running and self._connected)
            self._stop.setEnabled(self._running)
        self.controls_changed.emit()

    def set_connected(self, connected: bool) -> None:
        self._connected = bool(connected)
        self._dot.setStyleSheet(
            f"color: {theme.GOOD if connected else theme.BAD}; font-size: 15px;")
        if not connected:
            self._state.setText("not connected — press Start (F1) to run the bot")
            # Nothing is running if nothing is attached, so the run controls
            # follow from that. Routed through _apply_buttons so a handover in
            # progress still wins -- Start must not come back to life while the
            # owner is the one holding the keyboard.
            self._running = False
            self._apply_buttons()
        else:
            # The text used to be written ONLY by set_status, which runs when a
            # StatusUpdate arrives. A bot that connected but had not yet
            # broadcast one left a green dot sitting beside "not connected — is
            # the bot running?", contradicting itself indefinitely.
            self._state.setText("connected — waiting for the bot to report in")
            self._apply_buttons()

    def set_note(self, text: str) -> None:
        """A one-off message: why a button press did nothing, for instance."""
        self._state.setText(text)
        self.controls_changed.emit()

    @property
    def paused(self) -> bool:
        return self._paused

    def set_status(self, running: bool, paused: bool, note: str = "",
                   settled: bool = True) -> None:
        """`paused` is the request (it picks Pause or Resume); `settled` is
        whether the bot has actually stopped at a step, and only then does
        the header say "paused" (DESIGN 8du)."""
        self._paused = paused
        if paused and settled:
            text = "paused"
        elif paused:
            text = "running"
        elif running:
            text = "running"
        else:
            text = "idle"
        # "paused — paused" said nothing twice; the bot's own note is often
        # the same word (brain/controls.describe).
        self._state.setText(f"{text} — {note}" if note and note != text
                            else text)
        self._running = bool(running)
        self._pause.setText("Resume  F2" if paused else "Pause  F2")
        self._apply_buttons()

    def set_autonomy(self, mode: Autonomy) -> None:
        for i in range(self.autonomy.count()):
            if self.autonomy.itemData(i) == mode:
                self.autonomy.blockSignals(True)
                self.autonomy.setCurrentIndex(i)
                self.autonomy.blockSignals(False)
                return

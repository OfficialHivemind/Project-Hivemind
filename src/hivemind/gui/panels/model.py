"""The local vision model's real state, probed rather than assumed.

`perf.vlm` once shipped as a settings checkbox wired to nothing, which is the
exact failure this project exists to avoid. This panel is the antidote: every
line in it comes from a probe of the model server that actually returned, not
from a config value, a default or a hopeful assumption. If it says READY, then
something reached ollama within the last few seconds and saw the model listed.

WHY IT WILL NOT GO GREEN ON ITS OWN

"Unavailable" is cheap to be wrong about -- you look, you read the reason, you
run the command. "Ready" is expensive to be wrong about, because `ask()`
returns None when the model is absent and the bot carries on with classical CV;
a panel claiming the model is answering when it is not sends you hunting for
the fault everywhere except where it is. So green is painted only from a probe
that CAME BACK, never from one merely started, and it expires: a verdict older
than STALE_AFTER_S reverts to grey with its age on show, because a stale yes is
not a yes.

WHY THE CACHE ROW IS SOMETIMES ABSENT

`VisionModel.stats()` counts the questions asked through one client object,
not across the process. This panel never asks anything -- it only probes -- so
on a client it built for itself the row would read "not used yet" for the rest
of the session no matter how busy the model was. A row that can only ever hold
one value is not a reading, so it appears only when the caller passes in the
client the questions really go through.

WHY THE PROBE RUNS OFF THE GUI THREAD

`VisionModel.available()` is a blocking HTTP request bounded by PROBE_TIMEOUT
(2.0 s, brain/vlm.py). Run on the GUI thread that is a two-second freeze of the
whole window -- live view, panic status and all -- every time the server is
down, which is precisely when this panel is worth looking at.

It uses a daemon `threading.Thread` and a queue polled by the panel's own
timer, where panels/vision.py uses a QThread for its one-shot question. The
difference is lifetime, not taste: vision.py owns its thread from click to
answer, whereas this one re-probes for as long as the window is open, so a
probe is often in flight when the window closes. A QThread destroyed while
running aborts the process; a daemon thread writing to a queue nobody reads any
more costs nothing. Qt objects are touched only on the GUI thread.

WHY THE FIX COMMAND GETS ITS OWN ROW

Every `reason` the client produces for a fixable fault already ends in the shell
command that fixes it. Retyping a command out of a wrapped status label is how
it gets typed wrong, so it is lifted into its own row with a button that copies
it exactly. Faults with no command -- "turned off in settings" -- get no row,
rather than a button that does nothing.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton,
                               QWidget)

from ...brain.vlm import PROBE_TIMEOUT
from .. import theme
from ..widgets import Card, human_duration

# How often to re-probe. `available()` is deliberately uncached in the client
# because the server can be started or stopped mid-session, so this panel is
# the thing that notices. 10 s matches the SentinelPanel re-sort ticker.
REFRESH_MS = 10_000
# How often the GUI thread looks for a finished probe and re-renders the age.
# A "Check now" click should feel immediate, and a QLabel whose text has not
# changed does not repaint, so a fast poll is close to free.
POLL_MS = 250
# A healthy loop therefore produces a verdict every REFRESH_MS plus at most
# PROBE_TIMEOUT of waiting, i.e. 12 s. Two missed rounds means the loop itself
# has stopped, and an answer that old is no longer evidence of anything.
STALE_AFTER_S = 2 * (REFRESH_MS / 1000.0 + PROBE_TIMEOUT)          # 24.0 s

# The em dash that separates the sentence from the command in a `reason`.
# MEASURED by printing `reason` from the real client in each failure state
# (2026-09-20), rather than read off the source:
#   'no model server at http://127.0.0.1:1 ([Errno 111] Connection refused)
#    — sudo pacman -S ollama-vulkan && sudo systemctl enable --now ollama'
#   'qwen2.5vl:7b is not pulled yet — ollama pull qwen2.5vl:7b  (installed:
#    llama3:8b)'
#   'turned off in settings'
#   'model server gave an unusable reply: ...'
FIX_SEPARATOR = " — "
# vlm.py appends the installed-model list as f"  (installed: ...)", two spaces,
# and that parenthetical is not part of the command.
FIX_TAIL = "  "


def fix_command(reason: str) -> str:
    """The shell command inside a `reason`, or "" when it carries none.

    Only the two fixable faults above are written with an em dash, so the
    separator is also the test for whether there is a command at all. A reason
    without one gets no command invented for it -- a wrong command in a status
    panel is worse than no command, because it is run before it is doubted.

    The separator rule is a fact about the wording in brain/vlm.py, so it may
    only be applied to a sentence vlm.py wrote. `probe()` is careful never to
    run it over a sentence THIS module composed around an arbitrary exception:
    `repr(RuntimeError('ollama died — rm -rf /var/lib/ollama'))` would parse
    out `rm -rf /var/lib/ollama')` and offer it with a Copy button, which is
    the invention this function exists to refuse.
    """
    if FIX_SEPARATOR not in reason:
        return ""
    tail = reason.split(FIX_SEPARATOR, 1)[1]
    return tail.split(FIX_TAIL, 1)[0].strip()


@dataclass(frozen=True)
class Verdict:
    """What one probe found, carried back to the GUI thread.

    The strings travel WITH the verdict instead of being read back off the
    model afterwards: `available()` writes `reason` from the probe thread, so a
    panel reading that attribute would be reading it mid-write, and could show
    one probe's answer beside another probe's reason.

    `at` travels with it for the same reason the strings do. The age shown on
    the panel is the age of the ANSWER, and the moment the GUI thread happens
    to collect it from the queue is not that: a stopped poller, a blocked GUI
    thread or a long repaint all sit between the two, and stamping on
    collection would re-date an old answer as new -- painting green from a
    probe that returned minutes ago, which is the one thing this panel exists
    to prevent.
    """
    available: bool
    model: str
    reason: str
    stats: str
    at: float
    fix: str


def probe(model) -> Verdict:
    """Ask the client whether it is really there. Never raises.

    A probe that raised would leave the panel waiting on a thread that has
    already died -- honest, since it never turns green, but far less useful
    than the exception itself.
    """
    name, stats = "", ""
    try:
        name = str(model.model)
        ok = bool(model.available())
        reason = "" if ok else (model.reason or "unavailable, with no reason given")
        stats = str(model.stats())
    except Exception as exc:
        # Deliberately everything. The client guards the failures it knows
        # about, so anything arriving here is one nobody anticipated -- which
        # is the case where showing the exception is worth most.
        #
        # No fix command is parsed out of this one. The sentence is OURS, not
        # the client's, and an em dash inside an arbitrary exception repr is
        # punctuation, not a separator -- see fix_command's docstring.
        return Verdict(False, name, f"the check itself failed: {exc!r}", stats,
                       time.monotonic(), "")
    return Verdict(ok, name, reason, stats, time.monotonic(),
                   fix_command(reason))


class _Field(QWidget):
    """One caption-and-value line: MODEL, CACHE, CHECKED.

    The value is selectable because the interesting ones -- a model name, a
    cache summary -- get pasted into a bug report or a shell.
    """

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        label = QLabel(caption.upper())
        label.setObjectName("StatLabel")
        label.setFixedWidth(56)
        row.addWidget(label, 0, Qt.AlignTop)

        self._value = QLabel("—")
        self._value.setWordWrap(True)
        self._value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._paint(theme.TEXT)
        row.addWidget(self._value, 1)

    def _paint(self, colour: str) -> None:
        self._value.setStyleSheet(
            f"color: {colour}; font-family: {theme.MONO}; font-size: 11px;"
            " background: transparent;")

    def set(self, text: str, colour: str = "") -> None:
        self._value.setText(text or "—")
        self._paint(colour or theme.TEXT)

    def text(self) -> str:
        return self._value.text()


class ModelPanel(Card):
    """Whether the local vision model is really reachable, and what it costs.

    Drop it straight into a layout: `ModelPanel()` builds its own client from
    settings, or pass one in. It starts checking immediately and keeps checking
    while it is alive.
    """

    UNKNOWN = "unknown"
    READY = "ready"
    UNAVAILABLE = "unavailable"

    def __init__(self, model=None, parent=None):
        super().__init__("vision model", "", parent)
        # Whether the client is OURS or somebody else's decides what we are
        # entitled to say about it -- see the CACHE row below.
        self._owns_client = model is None
        if model is None:
            # Deferred so that building the window does not read the settings
            # file, the same reason panels/vision.py defers it.
            from ...brain.vlm import from_settings
            model = from_settings()
        self.model = model
        # Read tolerantly: a panel is built inside MainWindow.__init__, where
        # anything raised kills the window before it appears -- the lesson from
        # the settings-panel parse in BUGS.md. The host is a caption, so an
        # empty one costs nothing and a traceback costs the whole GUI.
        self.set_subtitle(str(getattr(model, "host", "")))

        self._verdict: Verdict | None = None
        self._state = self.UNKNOWN
        self._checked_at = 0.0          # monotonic; 0.0 means never
        self._results: queue.Queue[Verdict] = queue.Queue()
        self._probing = False
        self._stopped = False
        self._fix = ""
        self._rendered: tuple | None = None      # what _render last painted

        headline = QWidget()
        headline.setStyleSheet("background: transparent;")
        line = QHBoxLayout(headline)
        line.setContentsMargins(0, 0, 0, 2)
        line.setSpacing(8)
        self._dot = QLabel("●")
        line.addWidget(self._dot, 0, Qt.AlignTop)
        self._headline = QLabel("")
        self._headline.setWordWrap(True)
        line.addWidget(self._headline, 1)
        self.add(headline)

        self._model_field = _Field("model")
        # `VisionModel.stats()` counts the questions asked through THAT ONE
        # client object: `calls` and `cache_hits` are instance attributes, and
        # nothing shares them between clients. This panel only ever calls
        # `available()` and `stats()`, never `ask()`, so a client it built for
        # itself is one nothing has ever asked anything -- and the row could
        # only ever read "not used yet", for ever, whatever the bot is doing
        # through its own client. That is a number no engine computes, so the
        # row is not shown at all unless the caller hands us the client the
        # questions actually go through.
        self._cache_field = None if self._owns_client else _Field("cache")
        self._checked_field = _Field("checked")
        for field in (self._model_field, self._cache_field, self._checked_field):
            if field is not None:
                self.add(field)

        # The reason, verbatim. Wrapped and selectable rather than elided: it
        # ends in the command that fixes the fault, and a status panel that
        # truncates the fix is a status panel that sends you to the source.
        self._reason = QLabel("")
        self._reason.setWordWrap(True)
        self._reason.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._reason.setStyleSheet(
            f"color: {theme.WARN}; font-size: 11px; background: transparent;"
            " padding-top: 4px;")
        self._reason.setVisible(False)
        self.add(self._reason)

        self._fix_row = QWidget()
        self._fix_row.setStyleSheet("background: transparent;")
        fix_line = QHBoxLayout(self._fix_row)
        fix_line.setContentsMargins(0, 2, 0, 0)
        fix_line.setSpacing(8)
        self._fix_label = QLabel("")
        self._fix_label.setWordWrap(True)
        self._fix_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._fix_label.setStyleSheet(
            f"color: {theme.TEXT}; background: {theme.BG_RAISED};"
            f" font-family: {theme.MONO}; font-size: 11px;"
            " border-radius: 4px; padding: 4px 7px;")
        fix_line.addWidget(self._fix_label, 1)
        self._copy = QPushButton("Copy")
        self._copy.clicked.connect(self.copy_fix)
        fix_line.addWidget(self._copy, 0, Qt.AlignTop)
        self._fix_row.setVisible(False)
        self.add(self._fix_row)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 2, 0, 0)
        buttons.addStretch(1)
        self._check = QPushButton("Check now")
        self._check.clicked.connect(self.refresh)
        buttons.addWidget(self._check)
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        holder.setLayout(buttons)
        self.add(holder)

        self.add(QWidget(), 1)          # push the content to the top

        # One timer does both jobs: collect a finished probe, and re-render the
        # age so a check that never comes back visibly ages instead of sitting
        # on a green dot.
        self._poller = QTimer(self)
        self._poller.timeout.connect(self._tick)
        self._poller.start(POLL_MS)
        self._refresher = QTimer(self)
        self._refresher.timeout.connect(self.refresh)
        self._refresher.start(REFRESH_MS)
        # Restores the Copy button's label. Parented to the panel so it cannot
        # fire into a widget that has already been destroyed.
        self._copy_reset = QTimer(self)
        self._copy_reset.setSingleShot(True)
        self._copy_reset.timeout.connect(lambda: self._copy.setText("Copy"))

        self._render()
        self.refresh()

    # ---- what the panel is claiming ---------------------------------------
    def age(self) -> float | None:
        """Seconds since the last verdict came back, or None if none has."""
        if not self._checked_at:
            return None
        return time.monotonic() - self._checked_at

    def shown_state(self) -> str:
        """The state as PAINTED, which is the last verdict unless it aged out.

        This, not `_state`, is what the colours and the badge follow, so the
        panel cannot show a verdict it has not re-confirmed recently -- or one
        it has stopped re-confirming at all.
        """
        if self._stopped or self._state == self.UNKNOWN:
            return self.UNKNOWN
        age = self.age()
        if age is None or age > STALE_AFTER_S:
            return self.UNKNOWN
        return self._state

    @property
    def verdict(self) -> Verdict | None:
        """The last probe result, or None before one has returned."""
        return self._verdict

    # ---- probing ----------------------------------------------------------
    def refresh(self) -> None:
        """Check now, restarting the panel if it had been stopped.

        Never more than one probe at a time: a hung probe must not be answered
        by piling up threads behind it. The panel says the check has not come
        back, which is the true state of affairs.

        Asking a stopped panel to check restarts its timers, because the
        alternative is a probe whose answer nothing collects -- leaving it
        saying "checking the model server…" for ever, which is the one thing
        this panel may never do.
        """
        if self._stopped:
            self._stopped = False
            self._poller.start(POLL_MS)
            self._refresher.start(REFRESH_MS)
        if self._probing:
            return
        self._probing = True
        thread = threading.Thread(
            target=lambda: self._results.put(probe(self.model)),
            name="vlm-probe", daemon=True)
        thread.start()
        self._render()

    def _tick(self) -> None:
        try:
            verdict = self._results.get_nowait()
        except queue.Empty:
            self._render()              # the age moves even when nothing does
            return
        self._probing = False
        self._verdict = verdict
        # When the probe ANSWERED, not when we got round to picking it up.
        self._checked_at = verdict.at
        self._state = self.READY if verdict.available else self.UNAVAILABLE
        self._fix = verdict.fix
        self._render()

    def stop(self) -> None:
        """Stop checking, and stop claiming. Safe to call more than once.

        The timers are children of the panel and die with it; this exists for
        a caller that wants the polling to stop while the panel stays on
        screen. That case is exactly where a last green dot would become a
        lie -- nothing is probing any more, so the state is unknown again, and
        the panel is repainted once to say so. Any probe still in flight is a
        daemon thread writing to a queue, so there is nothing to join.
        """
        self._stopped = True
        self._poller.stop()
        self._refresher.stop()
        self._render()

    # ---- the fix ----------------------------------------------------------
    def copy_fix(self) -> None:
        """Copy the fix command exactly as the client gave it."""
        if not self._fix:
            return
        QApplication.clipboard().setText(self._fix)
        self._copy.setText("copied")
        self._copy_reset.start(1500)

    # ---- rendering --------------------------------------------------------
    def _render(self) -> None:
        """Repaint, but only when something a viewer could see has changed.

        The poller runs four times a second and this writes stylesheets, which
        each cost a style recomputation. The age is rendered in whole seconds,
        so an idle panel re-renders about once a second instead of four times.
        """
        state = self.shown_state()
        verdict = self._verdict
        age = self.age()

        if state == self.READY:
            colour, badge = theme.GOOD, "ready"
            headline = f"answering as {verdict.model}"
        elif state == self.UNAVAILABLE:
            colour, badge = theme.WARN, "unavailable"
            headline = "no answers from the model — classical vision only"
        else:
            colour = theme.TEXT_FAINT
            if self._probing:
                badge, headline = "checking", "checking the model server…"
            elif self._stopped:
                badge, headline = "unknown", "not checking any more — state unknown"
            else:
                badge, headline = "unknown", "the check has not come back — state unknown"

        if age is None:
            checked, checked_colour = (
                "checking…" if self._probing else "never", theme.TEXT_DIM)
        elif age > STALE_AFTER_S:
            checked, checked_colour = (
                f"{human_duration(age)} ago — no longer current", theme.WARN)
        else:
            checked, checked_colour = f"{human_duration(age)} ago", theme.TEXT_DIM

        # The reason survives a verdict ageing out: WHY it last failed is still
        # the most useful thing on the panel, and it is dated by the CHECKED
        # row rather than withdrawn.
        reason = verdict.reason if verdict else ""

        signature = (colour, badge, headline, checked, checked_colour, reason,
                     self._fix, verdict.model if verdict else "",
                     verdict.stats if verdict else "")
        if signature == self._rendered:
            return
        self._rendered = signature

        self._dot.setStyleSheet(f"color: {colour}; font-size: 12px;"
                                " background: transparent;")
        self._headline.setText(headline)
        self._headline.setStyleSheet(
            f"color: {colour}; font-size: 12px; font-weight: 600;"
            " background: transparent;")
        self.set_badge(badge, colour)

        self._model_field.set(verdict.model if verdict else "—")
        if self._cache_field is not None:
            self._cache_field.set(verdict.stats if verdict else "—")
        self._checked_field.set(checked, checked_colour)

        self._reason.setVisible(bool(reason))
        if reason:
            self._reason.setText(reason)
        self._fix_row.setVisible(bool(reason and self._fix))
        if self._fix:
            self._fix_label.setText(self._fix)

"""Stream mode: one 1920x1080 window to put on a 24/7 live stream.

THE OWNER'S ASK: "add a button on GUI called stream mode and its a mode that
shows my macro thinking and playing for a 24/7 live stream but make it
interesting like come up with ideas for chat to interact with the ai macro".

    +--------------------------------------------------------+----------------+
    | HIVEMIND  autonomous Bee Swarm bot            ● LIVE  23:41              |
    +--------------------------------------------------------+----------------+
    |                                                        | THINKING       |
    |   the game, as the bot sees it (1280x720)              |  the bot's own |
    |   [toasts: boss spotted, quest step done, big convert, |  words, as it  |
    |    chat's pick, milestones]                            |  decides       |
    |                                                        |                |
    +------------------+-----------------+-------------------+----------------+
    | RIGHT NOW        | LAST 24 HOURS   | GEAR GOALS        | CHAT PLAYS     |
    | doing, where,    | honey, rate,    | the owner's gear, | vote, predict, |
    | decided, then    | trips, deaths.. | how far off       | leaderboard    |
    +------------------+-----------------+-------------------+----------------+

EVERYTHING ON IT IS SOMETHING THE BOT SAID OR WROTE DOWN. The picture is the
main window's own live view, mirrored (panels/liveview.LiveView.mirror): the
frame the bot already writes, decoded once -- no extra capture of the game (a
fourth screencopy client killed the game twice, DESIGN 8a). The words are the
bot's own narration, folded by `stream/show.Feed`. The numbers are the bot's
metrics and its files: var/trips.jsonl for trips, deaths and the honey rate
(the same balance rate the gear goals' ETAs use, `brain/goals.balance_rate`),
var/errand_ready.json for the Wealth Clock, var/quests.json for quest steps,
`brain/goals` for the gear. A replay says DEMO on the stream as loudly as it
does in the main window.

OBS: add a "Window Capture (PipeWire)" of "Hivemind — stream" (F11 makes it
full screen). The window is exactly 1920x1080 (OBS's default canvas), never
scrolls and never shows a scrollbar, so nothing has to be cropped. The steps
are in docs/pending/stream.md. DESIGN 8dv. For the game at its own 60 fps
under the overlay, the game picture's "key colour" and OBS's Color Key filter
over a capture of the game's window: docs/pending/streamfps.md, DESIGN 8eb.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QPropertyAnimation,
                            QRectF, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..stream import chat as stream_chat
from ..stream import jump as stream_jump
from ..stream import privacy
from ..stream import subs as stream_subs
from ..stream.show import (Facts, Feed, Show, Spotter, Toast, clip, gathered,
                           handed_in_24h, highlight_of, human, plain, where_from)
from ..stream.voice import Announcer
from ..telemetry.events import (ChatBallot, Considered, Frame, Log, Metric,
                                StatusUpdate, TaskUpdate, Thought)
from ..world.settings import defaults
from . import stream_extras, stream_hud, stream_privacy, stream_rain, stream_voice, theme
from .panels.liveview import LiveView
from .widgets import Meter, human_duration

# THE CANVAS. 1920x1080 is OBS's default base resolution and the size of the
# game's own frame, so the capture is 1:1 with no scaling.
STREAM_W, STREAM_H = 1920, 1080
# THE GAME PICTURE: two thirds of the 1920x1080 frame, still 16:9, which
# leaves a 596-px column for the thinking feed -- about 55 characters a line
# at 17 px, so the median narration line (78 characters, stream/show) takes
# two lines and the 90th percentile (136) three.
VIEW_W, VIEW_H = 1280, 720
MARGIN, GAP, HEADER_H = 16, 12, 56
SIDE_W = STREAM_W - 2 * MARGIN - GAP - VIEW_W
BOTTOM_H = STREAM_H - 2 * MARGIN - HEADER_H - 2 * GAP - VIEW_H

# THE FEED ON SCREEN. The panel is 560 px tall and a row is 50 to 95 px by
# its line count (offscreen renders), so six to eight whole rows show; thirty
# are kept so a burst of lines does not delete what was on screen a moment
# ago.
# The chat card takes the rest of the column: 408 px, room for a five-way
# vote, a call and the leaderboard.
FEED_H = 560
FEED_ROWS = 30
# THE BOTTOM ROW's cards, in px, summing to VIEW_W less the gaps (1,256).
BOTTOM_WITH_GOALS = (432, 432, 392)
BOTTOM_WITHOUT_GOALS = (700, 556, 0)

# How often the stream re-reads the bot's files. The ledger gains a row a trip
# (a gathering trip ends every 843 s, median, stream/gate.TRIP_SECONDS) and
# the Wealth Clock file one per errand, so five seconds is far inside either
# and costs three stat() calls.
FILE_POLL_MS = 5000
# The gear plan reads the ledger and three knowledge files; it changes with the
# honey, which the bot re-reads about every pattern pass. Once a minute.
GOALS_POLL_MS = 60000
# How often the voice is asked for its next line (stream/voice paces itself).
VOICE_POLL_MS = 500
# var/stream_voice.txt keeps this many of the lines the voice said.
VOICE_LOG_LINES = 500
# THE CHAT READERS RESTART WHEN TYPING STOPS, not on every key: the settings
# field sends each keystroke, and each prefix of a channel name ("o", "ol",
# "oli") is a real channel to open a connection to and JOIN. Typists' mean
# gap between keys is 239 ms, and the slowest group's 481 ms (Dhakal et al.
# 2018, "Observations on Typing from 136 Million Keystrokes", CHI,
# doi:10.1145/3173574.3174220); 1.5 s is three of the slowest gaps.
CHAT_RESTART_MS = 1500

# THE SETTINGS THE PRIVACY GATE READS (stream/privacy.Redactor.configure):
# a change to one of these scrubs what is on screen again.
GATE_KEYS = ("stream.hide_private_text", "stream.hide_username",
             "stream.private_words", "stream.utc_times", "account.username")

CHAT = "#a78bfa"                 # violet, for everything chat did
SUB_RED = "#ff3355"              # the subscriber goal: YouTube's red, a shade softer
KEY_GREEN = "#00ff00"            # the chroma-key colour OBS's filter defaults to
STREAM_BG = "#0e1014"
CARD_BG = "#161920"

# Each category's tag and colour. Colour is spent the way theme.py spends it:
# yellow for a decision, red for danger, green for progress, blue for errands.
CATEGORY = {
    "decision": ("DECIDED", theme.ACCENT),
    "threat": ("THREAT", theme.BAD),
    "death": ("KNOCKED OUT", theme.BAD),
    "quest": ("QUEST", theme.GOOD),
    "errand": ("ERRAND", theme.INFO),
    "token": ("TOKEN", "#f0abfc"),
    "travel": ("TRAVEL", "#93c5fd"),
    "farm": ("FARM", "#cbd5e1"),
    "convert": ("CONVERT", theme.ACCENT),
    "goal": ("GOAL", "#fcd34d"),
    "chat": ("CHAT", CHAT),
    "vision": ("VISION", "#67e8f9"),
    "health": ("HEALTH", theme.WARN),
    "think": ("THINKING", theme.TEXT_DIM),
    "poll": ("CHAT PLAYS", CHAT),
    "answer": ("CHAT ASKED", CHAT),
    "ask": ("CHAT ASKED", CHAT),            # stream/ask's answers, which are also said
    "milestone": ("MILESTONE", theme.ACCENT),
    "record": ("BIG CONVERT", theme.ACCENT),
    "subs": ("NEW SUBSCRIBER", SUB_RED),    # YouTube's count went up (stream/subs)
    # what a viewer watches for (stream/show SHOP_WORDS and the rest)
    "shop": ("SHOPPING", "#facc15"),
    "hive": ("HIVE", "#fb923c"),
    "fight": ("FIGHT", "#f87171"),
    "item": ("ITEM", "#a78bfa"),
    # the showcase's proof moments (stream/show.highlight_of, 2026-10-14)
    "craft": ("BLENDER", "#c4b5fd"),
    "planter": ("PLANTER", "#86efac"),
}
# THE ROWS DRAWN LARGE: what was decided, bought and hatched
DECISION_CATEGORIES = {"decision", "shop", "hive"}
CATEGORY.update(stream_extras.EXTRA_CATEGORY)     # records, streaks, recap (8ec)

ACTIVITY = {
    "travel to the field": "Travelling to the field",
    "gather": "Gathering pollen",
    "convert": "Making honey at the hive",
}

STREAM_CSS = f"""
QWidget {{
    color: {theme.TEXT};
    font-family: {theme.SANS};
    background: transparent;
}}
QWidget#Stream {{ background: {STREAM_BG}; }}
QFrame#Card {{
    background: {CARD_BG};
    border: 1px solid {theme.BORDER};
    border-radius: 12px;
}}
QLabel#CardTitle {{
    color: {theme.TEXT_DIM};
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 2px;
}}
QLabel#CardSub {{ color: {theme.TEXT_FAINT}; font-size: 12px; }}
QLabel#Big {{
    font-family: {theme.MONO};
    font-size: 27px;
    font-weight: 700;
}}
QLabel#TileLabel {{
    color: {theme.TEXT_FAINT};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#TileSub {{ color: {theme.TEXT_DIM}; font-size: 12px; }}
"""


def _rgba(colour: str, alpha: float) -> str:
    c = QColor(colour)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:.2f})"


def _html(text: str) -> str:
    """Chat-written text, safe to put inside a rich-text label, and through
    the privacy gate (stream/privacy)."""
    return (stream_privacy.scrub(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _score(value: float, unit: str = "") -> str:
    """A ranking score for a viewer: whole numbers from ten up, where the
    main window's `theme.fmt_score` keeps a decimal under 1,000."""
    if abs(value) >= 10:
        return f"{value:,.0f} {unit}".strip()
    return theme.fmt_score(value, unit)


def _clock(at: float) -> str:
    """A feed row's time, on the clock the stream shows (local, or UTC with
    stream.utc_times: stream/privacy)."""
    return privacy.clock_text(at, "%H:%M:%S")


def _label(text: str = "", css: str = "", name: str = "", wrap: bool = False,
           rich: bool = False) -> QLabel:
    """A label that is PLAIN TEXT unless asked otherwise. Chat writes some of
    what these show, and a QLabel left on Qt's AutoText renders anything that
    looks like HTML -- a viewer could draw on the stream with "<h1>"."""
    label = stream_privacy.SafeLabel(text)       # every word passes the gate (8ec)
    label.setTextFormat(Qt.RichText if rich else Qt.PlainText)
    if name:
        label.setObjectName(name)
    if css:
        label.setStyleSheet(css)
    label.setWordWrap(wrap)
    return label


class _FitLabel(QLabel):
    """Plain text cut to `lines` lines at its current width, with an ellipsis.

    The stream window never scrolls, so a card's text has to fit its box:
    the first offscreen render with the gear goals on showed the plan
    sentence wrapping onto a third line and over the line below it.
    """

    def __init__(self, lines: int = 1, css: str = ""):
        super().__init__()
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(lines > 1)
        if css:
            self.setStyleSheet(css)
        self._raw = ""
        self._lines = max(1, lines)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)

    def set_text(self, text: str) -> None:
        # THE RAW TEXT IS KEPT and scrubbed as it is fitted, so a word the
        # owner adds to the gate is hidden in it at once (`rescrub`)
        self._raw = str(text or "")
        self._fit()

    def rescrub(self) -> None:
        self._fit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        self.ensurePolished()
        metrics = self.fontMetrics()
        width = max(40, self.width())
        # The height `lines` lines really take, measured the way the test
        # below measures: two wrapped lines at 15 px came to 42 px against a
        # lineSpacing() of 20, so a limit of 2 x 20 cut every two-line text
        # down to one.
        limit = metrics.boundingRect(0, 0, width, 100000, Qt.TextWordWrap,
                                     "\n".join(["Ag"] * self._lines)).height()
        self.setFixedHeight(limit + 2)

        def fits(text: str) -> bool:
            if self._lines == 1:
                return metrics.horizontalAdvance(text) <= width
            return metrics.boundingRect(0, 0, width, 100000, Qt.TextWordWrap,
                                        text).height() <= limit

        text = stream_privacy.scrub(self._raw)
        if fits(text):
            self.setText(text)
            return
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fits(text[:mid].rstrip() + "…"):
                lo = mid
            else:
                hi = mid - 1
        self.setText(text[:lo].rstrip() + "…")


class _Card(QFrame):
    """A titled stream card. `body` is its layout."""

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.title = _label(title.upper(), name="CardTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        self.subtitle = _label(subtitle, name="CardSub")
        head.addWidget(self.subtitle)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        outer.addLayout(self.body, 1)


# ---- the header -----------------------------------------------------------
class _Header(QFrame):
    def __init__(self, compact: bool = False):
        super().__init__()
        self.setObjectName("Card")
        self.compact = compact
        self.subtitle = None             # the HUD's subtitle, when compact
        self.setFixedHeight(stream_hud.BAR[3] if compact else HEADER_H)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(14)
        mark = _label("HIVEMIND", f"color: {stream_hud.HONEY if compact else theme.ACCENT};"
                                  f" font-size: {24 if compact else 26}px;"
                                  " font-weight: 900; letter-spacing: 3px;")
        # THE NAME IS NEVER CUT (a render 2026-10-14 read "HIVEMIN": the HUD
        # bar is 636 px and its chips asked for ~780, so Qt squeezed the
        # name first). The chips give way instead.
        mark.ensurePolished()
        mark.setMinimumWidth(mark.sizeHint().width())
        mark.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        row.addWidget(mark)
        self.tagline = _label("an autonomous Bee Swarm Simulator bot — every "
                              "decision it makes, on screen",
                              f"color: {theme.TEXT_DIM}; font-size: 15px;")
        # THE COMMENTARY LINE (stream/extras.Commentary) takes the tagline's
        # place once the bot has said something worth a line. In the HUD both
        # leave the bar: the line goes to the subtitle (StreamWindow._build_hud).
        self.caption = _FitLabel(2 if compact else 1, stream_hud.subtitle_css() if compact
                                 else stream_extras.caption_css())
        self.caption.hide()
        if compact:
            self.tagline.hide()
        else:
            row.addWidget(self.tagline)
            row.addWidget(self.caption, 1)
        self._stretch = row.count()
        row.addStretch(1)
        # THE SUBSCRIBER GOAL (stream/subs): YouTube's own count, the next
        # round number, and the pill filled as far as it has come. Hidden
        # until YouTube has said a count -- no number is ever made up.
        self.subs = _label("", rich=True)
        self.subs.hide()
        row.addWidget(self.subs, 0, Qt.AlignVCenter)
        # WHAT CHAT CAN TYPE, where a new viewer looks first. Only while a
        # chat reader is running: with no chat, nothing typed reaches it.
        self.cta = _label("", rich=True)
        self.cta.hide()
        row.addWidget(self.cta, 0, Qt.AlignVCenter)
        self.banner = _label("", f"color: #16161d; background: {theme.BAD};"
                                 " font-weight: 800; font-size: 14px;"
                                 " padding: 5px 12px; border-radius: 6px;")
        self.banner.hide()
        row.addWidget(self.banner, 0, Qt.AlignVCenter)
        self.state = _label("", "font-size: 15px; font-weight: 800;"
                                " letter-spacing: 1px; padding: 5px 12px;"
                                " border-radius: 6px;")
        row.addWidget(self.state, 0, Qt.AlignVCenter)
        self.clock = _label("", f"font-family: {theme.MONO}; font-size: 20px;"
                                f" color: {theme.TEXT_DIM};")
        row.addWidget(self.clock, 0, Qt.AlignVCenter)
        # FULL SCREEN, as a button as well as F11 (the owner: "the stream mode
        # window doesnt cover my entire screen its too big, make a full
        # screen button"). On a 1920x1080 monitor at scale 1 a 1080-px window plus its title bar and the
        # panel cannot fit; full screen is the canvas exactly. The button
        # hides while full screen, so it never appears on the stream; Esc or
        # F11 comes back.
        # In the HUD's bar it is the icon alone: the bar has no room for the
        # words beside the name, the subscriber goal and the clock.
        self.full = QPushButton("⛶" if compact else "⛶  Full screen")
        self.full.setCursor(Qt.PointingHandCursor)
        self.full.setToolTip("Fill the screen with the stream layout "
                             "(F11 or Esc to come back)")
        self.full.setStyleSheet(
            f"QPushButton {{ color: {theme.TEXT}; background: {_rgba(theme.ACCENT, 0.16)};"
            f" border: 1px solid {_rgba(theme.ACCENT, 0.45)}; border-radius: 6px;"
            " font-size: 15px; font-weight: 700; padding: 5px 12px; }"
            f" QPushButton:hover {{ background: {_rgba(theme.ACCENT, 0.30)}; }}")
        row.addWidget(self.full, 0, Qt.AlignVCenter)
        self.set_state("offline")

    def set_cta(self, commands: list) -> None:
        """`commands` are the chat commands that do something right now."""
        if not commands:
            self.cta.hide()
            return
        chips = "&nbsp;&nbsp;".join(
            f"<span style='color:{CHAT}; font-weight:800;'>{_html(c)}</span>"
            for c in commands)
        self.cta.setText(f"<span style='color:{theme.TEXT_DIM};'>type in chat"
                         f"</span>&nbsp;&nbsp; {chips}")
        self.cta.setStyleSheet(f"font-size: 16px; padding: 6px 14px;"
                               f" background: {_rgba(CHAT, 0.10)};"
                               f" border: 1px solid {_rgba(CHAT, 0.35)};"
                               " border-radius: 8px;")
        self.cta.show()

    def set_subs(self, count) -> None:
        """YouTube's subscriber count, or None to hide the goal."""
        if count is None:
            self.subs.hide()
            return
        goal = stream_subs.goal_for(count)
        share = stream_subs.progress(count)
        full, empty = _rgba(SUB_RED, 0.45), _rgba(SUB_RED, 0.08)
        self.subs.setText(
            f"<span style='color:{theme.TEXT}; font-weight:900;'>{count:,}</span>"
            f"<span style='color:{theme.TEXT_DIM};'> / {goal:,} "
            f"{'subs' if self.compact else 'subscribers'}</span>")
        self.subs.setStyleSheet(
            f"font-size: {14 if self.compact else 16}px;"
            f" padding: {'4px 10px' if self.compact else '6px 14px'}; border-radius: 8px;"
            f" border: 1px solid {_rgba(SUB_RED, 0.6)};"
            " background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {full}, stop:{share:.4f} {full},"
            f" stop:{min(1.0, share + 0.001):.4f} {empty}, stop:1 {empty});")
        self.subs.show()

    STATES = {
        "live": ("● LIVE", theme.GOOD),
        "paused": ("❚❚ PAUSED", theme.WARN),
        "owner": ("THE OWNER HAS THE CONTROLS", theme.INFO),
        "rejoining": ("↻ REJOINING", theme.WARN),
        "offline": ("● BOT OFFLINE", theme.BAD),
    }

    def set_state(self, key: str) -> None:
        text, colour = self.STATES.get(key, self.STATES["offline"])
        self.state.setText(text)
        self.state.setStyleSheet(
            f"color: {colour}; background: {_rgba(colour, 0.14)};"
            " font-size: 15px; font-weight: 800; letter-spacing: 1px;"
            " padding: 5px 12px; border-radius: 6px;")

    def tick(self) -> None:
        self.clock.setText(privacy.clock_text(time.time(), "%H:%M", zone=True))

    def set_caption(self, text: str) -> None:
        """The commentary line, or the tagline when there is none."""
        text = str(text or "")
        if self.compact:
            if text:
                self.caption.show()
                self.caption.set_text(text)
                if self.subtitle is not None:
                    self.subtitle.refresh()
            return
        if text and self.caption.isHidden():
            self.tagline.hide()
            self.caption.show()
            # the stretch after it gives its room to the line
            self.layout().itemAt(self._stretch).spacerItem().changeSize(
                0, 0, QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.layout().setStretch(self._stretch, 0)
            self.layout().invalidate()
        if text:
            self.caption.set_text(f"▸  {text}")


# ---- toasts -----------------------------------------------------------------
class _ToastCard(QFrame):
    # A THIRD OF THE PICTURE AT MOST. The first render had them 470 px wide
    # with 21 px titles, and three stacked covered the left third of the
    # game; at 400 px and 18 px three fit in the left 31% and 55% of the
    # height, over the part of the screen with no HUD on it (_ToastLayer).
    WIDTH = 400

    def __init__(self, item, parent, solid: bool = False):
        super().__init__(parent)
        label, colour = CATEGORY.get(item.kind, CATEGORY["think"])
        self.setObjectName("Toast")
        self._colour = colour
        self.set_solid(solid)
        self.setFixedWidth(self.WIDTH)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 8, 14, 10)
        box.setSpacing(1)
        box.addWidget(_label(label, f"color: {colour}; font-size: 11px;"
                                    " font-weight: 900; letter-spacing: 2px;"))
        box.addWidget(_label(item.title, "font-size: 18px; font-weight: 800;",
                             wrap=True))
        if item.body:
            box.addWidget(_label(item.body, f"color: {theme.TEXT_DIM};"
                                            " font-size: 14px;", wrap=True))
        # THE HEIGHT AT THIS WIDTH. `adjustSize` sized the wrapped title for
        # a narrower box, and the first compact render showed a one-line
        # title with a second line's gap under it.
        box.activate()
        self.setFixedHeight(box.totalHeightForWidth(self.WIDTH))
        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(0.0)
        self.setGraphicsEffect(self.effect)

    def set_solid(self, solid: bool) -> None:
        """SOLID OVER THE KEY COLOUR (DESIGN 8eb): 7% of the key green showing
        through the card would tint it green on stream, where 7% of the game
        showing through does not."""
        self.solid = solid
        colour = self._colour
        background = "rgb(14,16,20)" if solid else "rgba(14,16,20,0.93)"
        self.setStyleSheet(
            f"QFrame#Toast {{ background: {background};"
            f" border: 1px solid {_rgba(colour, 0.55)};"
            f" border-left: 6px solid {colour}; border-radius: 10px; }}")


class _ToastLayer(QWidget):
    """Toasts over the BOTTOM-LEFT of the game picture, newest lowest.

    Bottom-left because it is the part of Bee Swarm's screen with nothing on
    it: the honey and pollen counters are top-centre, the menu icons top-left,
    the hotbar bottom-centre and the game's own notices bottom-right (the
    saved frame var/routes/attempt-406/073204-natro_out_pine_tree-16-walk-
    aw132.jpg has all four). Three at most; more wait their turn.
    """

    VISIBLE = 3
    LEFT, BOTTOM, SPACING = 18, 18, 8
    # THE HUD'S ANCHOR (gui/stream_hud): dropping in at the top centre, under
    # the honey and pollen, newest lowest -- "bottom-left" is the classic one.
    anchor = "bottom-left"
    # Material Design's motion guidance puts a medium element's transition at
    # 200-300 ms on screen; 300 in, 250 out (exits are the faster of the two).
    IN_MS, OUT_MS = 300, 250

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # OVER THE KEY COLOUR THE TOASTS SLIDE AND DO NOT FADE (DESIGN 8eb).
        # A fading card is a blend of itself and the key green, which OBS's
        # Color Key leaves opaque: MEASURED offscreen, 13,471 to 65,384 of a
        # card's pixels were green-tinted mid-fade, against 1,508 (its own
        # green accents) once settled; sliding solid, 1,488 at most.
        self.keyed = False
        self._cards: list[_ToastCard] = []
        self._queue: list = []
        self._anims: list = []

    def set_keyed(self, keyed: bool) -> None:
        """Over the key colour or the picture; the cards up now follow. A
        fade already running is left to finish (300 ms at most): stopping
        it would leave a fading-out card on the stack for good."""
        self.keyed = keyed
        for card in self._cards:
            card.set_solid(keyed)

    def _x(self, card) -> int:
        return ((self.width() - card.width()) // 2 if self.anchor == "top-centre"
                else self.LEFT)

    def _away(self, card, y: int) -> QPoint:
        """Where a card slides in from and out to: off the top, or the left."""
        if self.anchor == "top-centre":
            return QPoint(self._x(card), -card.height())
        return QPoint(-card.width(), y)

    def _targets(self) -> list[int]:
        """Each card's y, newest (last) at the bottom."""
        if self.anchor == "top-centre":
            ys, top = [], stream_hud.TOAST_TOP
            for card in self._cards:
                ys.append(top)
                top += card.height() + self.SPACING
            return ys
        ys, bottom = [], self.height() - self.BOTTOM
        for card in reversed(self._cards):
            bottom -= card.height()
            ys.append(bottom)
            bottom -= self.SPACING
        return list(reversed(ys))

    def push(self, item) -> None:
        if len(self._cards) >= self.VISIBLE:
            self._queue = (self._queue + [item])[-6:]
            return
        card = _ToastCard(item, self, solid=self.keyed)
        self._cards.append(card)
        ys = self._targets()
        card.move(self._away(card, ys[-1]))
        card.show()
        self._restack(skip=card)
        slide = QPropertyAnimation(card, b"pos", self)
        slide.setDuration(self.IN_MS)
        slide.setStartValue(self._away(card, ys[-1]))
        slide.setEndValue(QPoint(self._x(card), ys[-1]))
        slide.setEasingCurve(QEasingCurve.OutCubic)
        # TWO ANIMATIONS, NOT A GROUP. Qt stops a running QPropertyAnimation
        # when another starts on the same property of the same object, so the
        # next toast's restack stopped this slide -- and, inside a group, the
        # fade with it: MEASURED on the first offscreen render, two of three
        # toasts sat on screen at opacity 0.0. Apart, the fade always finishes.
        self._run(slide)
        if self.keyed:
            card.effect.setOpacity(1.0)
        else:
            fade = QPropertyAnimation(card.effect, b"opacity", self)
            fade.setDuration(self.IN_MS)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            self._run(fade)
        QTimer.singleShot(int(item.seconds * 1000), lambda c=card: self._dismiss(c))

    def _restack(self, skip=None) -> None:
        for card, y in zip(self._cards, self._targets()):
            if card is skip:
                continue
            move = QPropertyAnimation(card, b"pos", self)
            move.setDuration(self.IN_MS)
            move.setEndValue(QPoint(self._x(card), y))
            move.setEasingCurve(QEasingCurve.OutCubic)
            self._run(move)

    def _run(self, anim) -> None:
        self._anims.append(anim)
        anim.finished.connect(lambda a=anim: self._anims.remove(a)
                              if a in self._anims else None)
        anim.start()

    def _dismiss(self, card) -> None:
        if card not in self._cards:
            return
        if self.keyed or card.solid:
            # Out of the stack first: a restack starts a "pos" animation on
            # every stacked card, which would stop this slide short of its
            # end, and a stopped animation never says it finished.
            self._cards.remove(card)
            out = QPropertyAnimation(card, b"pos", self)
            out.setDuration(self.OUT_MS)
            out.setEndValue(self._away(card, card.y()))
            out.setEasingCurve(QEasingCurve.InCubic)
            out.finished.connect(card.deleteLater)
            self._run(out)
            self._restack()
            if self._queue:
                self.push(self._queue.pop(0))
            return
        fade = QPropertyAnimation(card.effect, b"opacity", self)
        fade.setDuration(self.OUT_MS)
        fade.setStartValue(card.effect.opacity())
        fade.setEndValue(0.0)
        fade.finished.connect(lambda c=card: self._gone(c))
        self._run(fade)

    def _gone(self, card) -> None:
        if card in self._cards:
            self._cards.remove(card)
        card.deleteLater()
        self._restack()
        if self._queue:
            self.push(self._queue.pop(0))


# ---- the game picture --------------------------------------------------------
class _GameView(QWidget):
    def __init__(self, width: int = VIEW_W, height: int = VIEW_H, hud: bool = False):
        super().__init__()
        self.setFixedSize(width, height)
        self.live = LiveView(self)
        self.live.setGeometry(0, 0, width, height)
        self.key = QWidget(self)
        self.key.setGeometry(0, 0, width, height)
        self.key.setStyleSheet(f"background: {KEY_GREEN};")
        self.key.hide()
        self.tag = _label("  WHAT THE BOT SEES  ", self._tag_css(), wrap=False)
        self.tag.setParent(self)
        self.tag.adjustSize()
        self.tag.move(width - self.tag.width() - 16, height - self.tag.height() - 14)
        # THE BOT'S EYES over the whole picture (gui/stream_hud)
        self.viewfinder = None
        if hud:
            self.tag.hide()
            self.viewfinder = stream_hud.Viewfinder(self)
            self.viewfinder.setGeometry(0, 0, width, height)
        self.toasts = _ToastLayer(self)
        if hud:
            self.toasts.anchor = "top-centre"
        self.toasts.setGeometry(0, 0, width, height)
        self.toasts.raise_()

    @staticmethod
    def _tag_css() -> str:
        return ("color: #e6e9ef; background: rgba(14,16,20,0.72);"
                " font-size: 12px; font-weight: 800; letter-spacing: 2px;"
                " padding: 5px 4px; border-radius: 5px;")

    def set_mode(self, mode: str) -> None:
        keyed = str(mode) == "key colour"
        self.toasts.set_keyed(keyed)
        self.key.setVisible(keyed)
        self.live.setVisible(not keyed)
        if self.viewfinder is not None:
            self.viewfinder.set_keyed(keyed)
            self.viewfinder.raise_()
        else:
            self.tag.setVisible(not keyed)
        self.toasts.raise_()


# ---- the feed -------------------------------------------------------------------
class _FeedRow(QFrame):
    def __init__(self, item):
        super().__init__()
        label, colour = CATEGORY.get(item.category, CATEGORY["think"])
        decision = item.category in DECISION_CATEGORIES
        self.setObjectName("FeedRow")
        self.setStyleSheet(
            f"QFrame#FeedRow {{ background: {_rgba(colour, 0.11 if decision else 0.045)};"
            f" border-left: 3px solid {colour}; border-radius: 5px; }}")
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 6, 10, 7)
        box.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_label(label, f"color: {colour}; font-size: 11px;"
                                     " font-weight: 900; letter-spacing: 1px;"))
        self.count = _label("", f"color: {theme.TEXT_FAINT}; font-size: 11px;"
                                " font-weight: 700;")
        head.addWidget(self.count)
        head.addStretch(1)
        self._at = item.at
        self.stamp = _label(_clock(item.at), f"color: {theme.TEXT_FAINT};"
                                             f" font-family: {theme.MONO};"
                                             " font-size: 11px;")
        head.addWidget(self.stamp)
        box.addLayout(head)
        colour_text = theme.WARN if item.warn else theme.TEXT
        text = _label(item.text, f"color: {colour_text};"
                                 f" font-size: {18 if decision else 16}px;"
                                 f" font-weight: {600 if decision else 400};",
                      wrap=True)
        text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        box.addWidget(text)

    def bump(self, item) -> None:
        self.count.setText(f"×{item.count}")
        self._at = item.at
        self.stamp.setText(_clock(item.at))

    def rescrub(self) -> None:
        self.stamp.setText(_clock(self._at))     # the clock may have changed


class _RowBox(QWidget):
    """The feed's rows' container; tells the panel when its size is known."""

    def __init__(self, on_resize):
        super().__init__()
        self._on_resize = on_resize

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._on_resize()


class _FeedPanel(_Card):
    """Newest at the bottom, and only the rows that fit WHOLE.

    A stream window never scrolls, and the first renders did it with a
    scroll area pinned to its bottom: the top row was cut in half, and a
    36 px fade over it, then a 56 px one, still left the cut line legible.
    Now the oldest rows that do not fit are hidden instead (FEED_ROWS are
    kept, so a burst does not delete what was on screen a moment ago).
    """

    def __init__(self, newest_first: bool = False):
        super().__init__("thinking", "the bot's own words, as it decides")
        self._box = _RowBox(self._fit)
        self._list = QVBoxLayout(self._box)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(6)
        # NEWEST AT THE TOP in the main window's Simple mode (gui/simple): a
        # list that starts at its head instead of a column filling upwards
        self._newest_first = newest_first
        if not newest_first:
            self._list.addStretch(1)
        self.body.addWidget(self._box, 1)
        if newest_first:
            self._list.addStretch(1)
        self._rows: dict[int, _FeedRow] = {}
        self._order: list[int] = []

    def add(self, item, new: bool, animate: bool = True) -> None:
        if not new:
            row = self._rows.get(id(item))
            if row is not None:
                row.bump(item)
            return
        row = _FeedRow(item)
        if self._newest_first:
            self._list.insertWidget(0, row)
        else:
            self._list.addWidget(row)
        self._rows[id(item)] = row
        self._order.append(id(item))
        while len(self._order) > FEED_ROWS:
            old = self._rows.pop(self._order.pop(0), None)
            if old is not None:
                self._list.removeWidget(old)
                old.deleteLater()
        self._fit()
        if animate:
            effect = QGraphicsOpacityEffect(row)
            effect.setOpacity(0.0)
            row.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, b"opacity", row)
            fade.setDuration(_ToastLayer.IN_MS)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            # the effect is dropped at the end: a finished opacity effect
            # still renders the row through an offscreen buffer
            fade.finished.connect(lambda r=row: r.setGraphicsEffect(None))
            fade.start()

    def _fit(self) -> None:
        """Show the newest rows whose whole height fits the panel."""
        width, room = self._box.width(), self._box.height()
        if width <= 0 or room <= 0:
            return
        gap = self._list.spacing()
        used, keep = 0, 0
        for key in reversed(self._order):
            row = self._rows[key]
            tall = (row.heightForWidth(width) if row.hasHeightForWidth()
                    else row.sizeHint().height())
            if keep and used + gap + tall > room:
                break
            used += tall + (gap if keep else 0)
            keep += 1
        first = len(self._order) - keep
        for i, key in enumerate(self._order):
            self._rows[key].setVisible(i >= first)


# ---- the cards under the picture ------------------------------------------------
class _NowCard(_Card):
    def __init__(self):
        super().__init__("right now")
        self.activity = _label("waiting for the bot to report in",
                               "font-size: 22px; font-weight: 800;")
        self.body.addWidget(self.activity)
        self.detail = _FitLabel(1, f"color: {theme.TEXT_DIM}; font-size: 14px;")
        self.body.addWidget(self.detail)
        self.bar = Meter(0.0, colour=theme.ACCENT, height=8)
        self.body.addWidget(self.bar)
        self.where = self._line("WHERE", theme.INFO)
        self.plan = self._line("DECIDED", theme.ACCENT, lines=2)
        self.then = self._line("THEN", CHAT, lines=2)
        self.body.addStretch(1)

    def _line(self, tag: str, colour: str, lines: int = 1) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(10)
        head = _label(tag, f"color: {colour}; font-size: 11px; font-weight: 900;"
                           " letter-spacing: 1px;")
        head.setFixedWidth(62)
        head.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        row.addWidget(head, 0, Qt.AlignTop)
        text = _FitLabel(lines, "font-size: 15px;")
        text.set_text("—")
        row.addWidget(text, 1)
        self.body.addLayout(row)
        return text


class _Tile(QWidget):
    def __init__(self, label: str):
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(_label(label.upper(), name="TileLabel"))
        self.value = _label("—", name="Big")
        box.addWidget(self.value)
        self.sub = _FitLabel(1)
        self.sub.setObjectName("TileSub")
        box.addWidget(self.sub)

    def set(self, value: str, sub: str = "", colour: str = theme.TEXT) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {colour};")
        self.sub.set_text(sub)


class _StatsCard(_Card):
    def __init__(self):
        super().__init__("the numbers", "")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        self.honey = _Tile("honey")
        self.rate = _Tile("honey / hour")
        self.trips = _Tile("trips · 24 h")
        self.deaths = _Tile("knocked out")
        self.quests = _Tile("quests handed in")
        self.clock = _Tile("wealth clock")
        for i, tile in enumerate((self.honey, self.rate, self.clock,
                                  self.trips, self.deaths, self.quests)):
            grid.addWidget(tile, i // 3, i % 3)
        self.body.addLayout(grid)
        self.body.addStretch(1)


class _GoalsCard(_Card):
    ROWS = 3

    def __init__(self):
        super().__init__("shopping list", "")
        # THE HIVE'S GROWTH, the thing most of the honey buys (slot + egg)
        self._bees = _FitLabel(1, f"color: {theme.TEXT}; font-size: 13px; font-weight: 800;")
        self._bees_bar = Meter(0.0, colour="#fb923c", height=6)
        self.body.addWidget(self._bees)
        self.body.addWidget(self._bees_bar)
        self._owned = _FitLabel(1, f"color: {theme.GOOD}; font-size: 12px;")
        self._owned.setVisible(False)
        self.body.addWidget(self._owned)
        # THE STAGE AND WHAT COMES AFTER HIS LIST (brain/progression), one line
        self._stage = _FitLabel(2, f"color: {theme.INFO}; font-size: 12px;")
        self._stage.setVisible(False)
        self.body.addWidget(self._stage)
        self._rows = []
        for _ in range(self.ROWS):
            name = _label("", "font-size: 16px; font-weight: 700;")
            state = _label("", f"color: {theme.TEXT_DIM}; font-size: 12px;")
            head = QHBoxLayout()
            head.addWidget(name, 1)
            head.addWidget(state)
            bar = Meter(0.0, colour=theme.GOOD, height=7)
            note = _FitLabel(1, f"color: {theme.TEXT_DIM}; font-size: 12px;")
            self.body.addLayout(head)
            self.body.addWidget(bar)
            self.body.addWidget(note)
            self._rows.append((name, state, bar, note))
        self._held = _FitLabel(1, f"color: {theme.TEXT_DIM}; font-size: 12px;")
        self.body.addStretch(1)
        self.body.addWidget(self._held)

    # The state's colour, the way theme.py spends colour: green for "you can
    # buy it now", yellow for "the honey is there", red for a gate not passed.
    STATE_COLOUR = {"ready to buy": theme.GOOD, "honey ready": theme.ACCENT,
                    "blocked": theme.BAD}

    def show_shopping(self, plan, var_root) -> bool:
        """The bot's own shopping list (brain/buyer: the owner's next goal,
        then jelly from the honey above it, then the Ticket Tent's), each with
        what it waits on and how far the honey has come; the hive's count; what
        is held for it. False when there is nothing to show this way."""
        import json as _json
        from pathlib import Path as _Path

        from ..brain import buyer
        from ..brain.owned import inventory
        try:
            shopping = buyer.from_files(plan, var_root, honey=getattr(plan, "honey", None))
        except Exception:
            return False
        items = shopping.purchases[:self.ROWS]
        if not items:
            return False
        honey = shopping.honey
        self._wanted = len(items)
        for i, (name, state, bar, note) in enumerate(self._rows):
            visible = i < len(items)
            for widget in (name, state, bar, note):
                widget.setVisible(visible)
            if not visible:
                continue
            p = items[i]
            name.setText(f"{p.count} {p.label}" if p.count > 1 else p.label)
            if p.can_buy:
                chip, colour = "BUYING NEXT", theme.GOOD
            elif p.ready:
                chip, colour = "READY · WAITS", theme.ACCENT
            else:
                chip, colour = "SAVING", theme.INFO
            cost = (f"{human(p.honey)} honey" if p.honey else f"{p.tickets:,} tickets")
            state.setText(f"{chip} · {cost}")
            state.setStyleSheet(f"color: {colour}; font-size: 13px; font-weight: 800;")
            fraction = (min(1.0, honey / p.honey) if (honey is not None and p.honey) else
                        1.0 if p.ready else 0.0)
            bar.set_value(fraction, colour=colour)
            note.set_text(p.blocked or p.why)
        # the hive: bees, and the slot it saves for
        try:
            body = _json.loads((_Path(var_root) / "bees.json").read_text())
            bees = int(body.get("total") or 0)
        except Exception:
            bees = 0
        self._bees.set_text(f"hive: {bees} of 50 bees" if bees else "hive: not read yet")
        self._bees_bar.set_value(bees / 50.0 if bees else 0.0)
        counts, _where = inventory(var_root)
        held = [f"{counts[k]:,} {label}" for k, label in (
            ("basic_egg", "Basic Egg"), ("royal_jelly", "Royal Jelly"), ("tickets", "tickets"))
            if counts.get(k)]
        # the page dots sit where a subtitle would: the promise goes last
        self._held.set_text(("held: " + " · ".join(held) + " · " if held else "")
                            + "honey and tickets only, never Robux")
        self._owned.setVisible(False)
        self.subtitle.setText("")
        self._fit_rows()
        return True

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_rows()

    def _fit_rows(self) -> None:
        """FEWER ROWS, NOT ROWS DRAWN OVER EACH OTHER: the stream never
        scrolls, and three rows squeezed into a short card overlapped (UI
        panel round 2, 2026-10-22, the streamer). The last rows go first."""
        wanted = getattr(self, "_wanted", 0)
        for i, row in enumerate(self._rows):
            for widget in row:
                widget.setVisible(i < wanted)
        shown = wanted
        while shown > 1 and self.layout().minimumSize().height() > self.height():
            shown -= 1
            for widget in self._rows[shown]:
                widget.setVisible(False)

    def show_plan(self, plan, var_root=None) -> None:
        prog = getattr(plan, "progress", None)
        line = prog.line() if prog is not None else ""
        self._stage.setVisible(bool(line))
        self._stage.set_text(f"stage: {line}" if line else "")
        if var_root is not None and self.show_shopping(plan, var_root):
            return
        from ..brain.goals import hours_text
        rows = [r for r in (plan.rows if plan else []) if not r.owned][:self.ROWS]
        self._wanted = len(rows)
        for i, (name, state, bar, note) in enumerate(self._rows):
            visible = i < len(rows)
            for widget in (name, state, bar, note):
                widget.setVisible(visible)
            if not visible:
                continue
            row = rows[i]
            name.setText(row.label)
            state.setText(f"{row.state} · {human(row.cost)}")
            state.setStyleSheet(f"color: {self.STATE_COLOUR.get(row.state, theme.TEXT_DIM)};"
                                " font-size: 13px; font-weight: 700;")
            # How far along HIS QUEUE, not the goal alone: the honey the goals
            # above it take is counted, as `queue_short` counts it.
            have = row.honey
            fraction = (min(1.0, have / (have + row.queue_short))
                        if have is not None and row.queue_short else
                        1.0 if have is not None else 0.0)
            bar.set_value(fraction, colour=self.STATE_COLOUR.get(row.state, theme.GOOD))
            bits = []
            if row.queue_short:
                bits.append(f"{human(row.queue_short)} to go")
            if row.eta_hours:
                bits.append(f"~{hours_text(row.eta_hours)} of farming")
            if row.missing:
                bits.append("needs " + ", ".join(n.describe() for n in row.missing[:2]))
            if not bits and row.next_step:
                bits.append(row.next_step)
            note.set_text(" · ".join(bits))
        # WHAT HE ALREADY OWNS, above the bars (DESIGN 8ea): a confirmed one
        # plain, an inferred one "? (inferred)" -- the balance says he bought
        # it, and he has not said so yet.
        owned = plan.owned_text() if plan else ""
        self._owned.setVisible(bool(owned))
        self._owned.set_text(f"owned: {owned}" if owned else "")
        # Not the honey line: the numbers card has the honey, and on stream
        # the thing a viewer needs is that this list is the owner's and what
        # the bot spends on it is honey, never real money (brain/goals).
        self.subtitle.setText("the owner's list · honey only, never Robux")
        self._fit_rows()


class _Bars(QWidget):
    """Rows of `(key, label, right, fraction, lit)`, painted."""

    ROW_H = 29

    def __init__(self):
        super().__init__()
        self._rows: list = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_rows(self, rows) -> None:
        self._given = list(rows)
        scrub = stream_privacy.scrub
        self._rows = [(scrub(k), scrub(label), scrub(right), fraction, lit)
                      for k, label, right, fraction, lit in self._given]
        self.setFixedHeight(max(1, len(self._rows)) * self.ROW_H)
        self.update()

    def rescrub(self) -> None:
        self.set_rows(getattr(self, "_given", []))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        font = QFont(theme.SANS.split(",")[0])
        for i, (key, label, right, fraction, lit) in enumerate(self._rows):
            y = i * self.ROW_H
            box = QRectF(0, y + 3, w, self.ROW_H - 6)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.BG_RAISED))
            painter.drawRoundedRect(box, 6, 6)
            if fraction > 0:
                fill = QColor(CHAT if lit else theme.TEXT_FAINT)
                fill.setAlpha(150 if lit else 110)
                painter.setBrush(fill)
                painter.drawRoundedRect(QRectF(0, y + 3, max(12.0, w * min(1.0, fraction)),
                                               self.ROW_H - 6), 6, 6)
            font.setPixelSize(13)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(CHAT if lit else theme.TEXT_DIM))
            painter.drawText(box.adjusted(10, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, key)
            font.setPixelSize(15)
            painter.setFont(font)
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(box.adjusted(44, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
            font.setBold(False)
            font.setPixelSize(13)
            painter.setFont(font)
            painter.setPen(QColor(theme.TEXT_DIM))
            painter.drawText(box.adjusted(0, 0, -10, 0), Qt.AlignVCenter | Qt.AlignRight, right)


class _Section(QWidget):
    """A small coloured heading with a countdown on its right."""

    def __init__(self, text: str, colour: str = CHAT):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 0)
        self.label = _label(text, f"color: {colour}; font-size: 12px;"
                                  " font-weight: 900; letter-spacing: 1px;")
        row.addWidget(self.label)
        row.addStretch(1)
        self.right = _label("", f"color: {theme.TEXT}; font-family: {theme.MONO};"
                                " font-size: 14px; font-weight: 700;")
        row.addWidget(self.right)


class _ChatCard(_Card):
    def __init__(self):
        super().__init__("chat plays", "")
        self.body.setSpacing(5)
        self.vote_head = _Section("WHERE NEXT?")
        self.body.addWidget(self.vote_head)
        self.bars = _Bars()
        self.body.addWidget(self.bars)
        self.vote_note = _label("", f"color: {theme.TEXT_DIM}; font-size: 13px;", wrap=True)
        self.body.addWidget(self.vote_note)
        self.call_head = _Section("CALL THE TRIP")
        self.body.addWidget(self.call_head)
        self.calls = _Bars()
        self.body.addWidget(self.calls)
        self.result = _label("", f"color: {theme.TEXT_DIM}; font-size: 13px;", wrap=True)
        self.body.addWidget(self.result)
        self.board = _label("", "font-size: 14px;", wrap=True, rich=True)
        self.body.addWidget(self.board)
        self.milestone = _label("", f"color: {theme.ACCENT}; font-size: 14px;", wrap=True)
        self.body.addWidget(self.milestone)
        self.ticker = _label("", f"color: {CHAT}; font-size: 13px;", wrap=True)
        self.body.addWidget(self.ticker)
        self.body.addStretch(1)
        self.help = _label("", f"color: {theme.TEXT_FAINT}; font-size: 12px;"
                               f" font-family: {theme.MONO};", wrap=True)
        self.body.addWidget(self.help)


# ---- the window ----------------------------------------------------------------
class _ChatSignals(QObject):
    """Chat arrives on reader threads; Qt moves it to this one."""
    line = Signal(object)
    state = Signal(str)
    subs = Signal(int)


class StreamWindow(QWidget):
    """The stream layout. Fed the same events as the main window."""

    closed = Signal()

    def __init__(self, bridge=None, settings=None, recent=(), honey=None,
                 replay: str = "", connected: bool = False, var_root=None,
                 parent=None, clock=time.time, live_source=None,
                 bot_alive=None):
        super().__init__(parent)
        self.setObjectName("Stream")
        self.setWindowTitle("Hivemind — stream")
        self.setFixedSize(STREAM_W, STREAM_H)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.bridge = bridge
        self.clock = clock
        self._bot_alive = bot_alive
        # THE REAL WINDOW, when this layout is drawn scaled inside one
        # (gui/stream_frame): full screen and the screen are its, not ours.
        self.host = None
        self._var = Path(var_root) if var_root else None
        self._settings = defaults()
        self._settings.update(dict(settings or {}))
        # THE LAYOUT, read once as the window opens (gui/stream_hud)
        self._hud = str(self._settings.get("stream.layout") or "hud") != "classic"
        self._restyle()
        # THE ONE GATE every word on the stream passes (stream/privacy, 8ec),
        # set before the first label is drawn.
        self.privacy = privacy.Redactor(self._settings)
        stream_privacy.activate(self.privacy)
        privacy.show_utc(self.privacy.utc)
        # the ledger's rows as scrubbed, kept so only new rows are scrubbed
        # at each read (`_clean_rows`)
        self._ledger_clean: list = []
        self._ledger_first = self._ledger_last = None
        self._keyed = False              # the game picture is the key colour

        # what the bot has said, for the cards and for chat's questions
        self._honey = honey
        self._rate = None
        self._where = ""
        self._plan = ""
        self._stay = ""
        self._ranking: list = []
        self._chosen = ""
        self._why = ""
        self._rate_from = ""
        self._balance_rate = None
        self._running = None
        self._totals = None
        self._opened_at = clock()
        self._mtimes: dict = {}
        self._clock_due = None
        self._clock_from = ""
        self._goal_line = ""
        self._trips_24h = 0
        self._quests_24h = 0
        self._chat_state = ""
        self._readers: list = []

        self.feed = Feed()
        self.spotter = Spotter()
        self.games = Show(get=self._get, send=self._send, facts=self._facts,
                          board_path=self._path("stream_points.json"), clock=clock)
        # chat's "jump" (DESIGN 8ef): folded here, sent to the bot at most
        # once a second, and only while the owner's switch is on
        self.jumps = stream_jump.JumpAsks(clock=clock)
        self.extras = None               # set in _build (gui/stream_extras, 8ec)

        self._build()
        self.header.full.clicked.connect(self.toggle_full_screen)
        # THE MAIN WINDOW'S LIVE VIEW, mirrored when there is one; a stream
        # window built on its own (a test, `--stream` before the main window
        # has a frame) decodes the Frame events itself.
        self._mirrored = live_source is not None
        if self._mirrored:
            # THROUGH THE GATE: the live view draws each detection's label
            # on the picture, and a mirrored Frame never passes `handle`
            # (gui/stream_privacy.GatedMirror, 8ec)
            self._mirror = stream_privacy.GatedMirror(
                self.view.live, live_source, self.privacy.frame)
        # THE PICTURE'S MASKS (gui/stream_privacy, 8ec): over the stream's copy
        # of the picture only, from the frames its source has decoded. With
        # the key colour too: then they are solid, over OBS's own capture.
        self.guard = stream_privacy.PictureGuard(
            self.view, live_source if self._mirrored else self.view.live, self._get,
            clock=clock)
        self.guard.setGeometry(0, 0, self.view.width(), self.view.height())
        self.view.toasts.raise_()
        self.extras.recap.raise_()
        self.rain.raise_()
        self.set_connected(connected)
        if replay:
            self.header.banner.setText(f"DEMO — replaying {replay}, not live")
            self.header.banner.show()
        self.view.set_mode(self._get("stream.game_view"))
        self._keyed = str(self._get("stream.game_view")) == "key colour"
        self.guard.set_keyed(self._keyed)

        # The chat readers first, so a ballot replayed below finds a reader
        # to wait for (`Show.set_listening` offers it once one connects).
        self._signals = _ChatSignals()
        self.subs = stream_subs.Tracker()
        self._signals.line.connect(self._on_chat)
        self._signals.state.connect(self._on_chat_state)
        self._signals.subs.connect(self._on_subs)
        self._chat_restart = QTimer(self)
        self._chat_restart.setSingleShot(True)
        self._chat_restart.setInterval(CHAT_RESTART_MS)
        self._chat_restart.timeout.connect(self._restart_chat)
        self._restart_chat()

        # THE VOICE (stream/voice, gui/stream_voice): the bot's own news said
        # out loud while this window is open -- live events only, never the
        # history replayed below, and every line through the gate once more
        # as it is spoken.
        self.announcer = Announcer(
            get=self._get, clock=clock, chat_live=lambda: bool(self._readers),
            # (running, paused, handed over), from the bot's StatusUpdate
            playing=lambda: bool(self._running and self._running[0]
                                 and not self._running[1] and not self._running[2]))
        self.voice = stream_voice.Voice(get=self._get)
        # what chat's questions may be answered with, beyond the bot's facts
        self.games.ask_extra = lambda: {
            "field": self._chosen,
            "quest": (lambda q: f"{q.text}, {q.done} of {q.total} done" if q else "")(
                self.announcer.quests[0] if self.announcer.quests else None),
            "thought": self.announcer.last_thought}

        for event in recent:                 # what happened before it opened
            self.handle(event, quiet=True)

        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start(1000)
        self._files = QTimer(self)
        self._files.timeout.connect(self._poll_files)
        self._files.start(FILE_POLL_MS)
        self._goals = QTimer(self)
        self._goals.timeout.connect(self._refresh_goals)
        self._goals.start(GOALS_POLL_MS)
        self._voice_timer = QTimer(self)
        self._voice_timer.timeout.connect(self._speak_next)
        self._voice_timer.start(VOICE_POLL_MS)
        self._poll_files()
        self._refresh_goals()
        self._tick()

        if bridge is not None:
            bridge.event_received.connect(self.handle)
            bridge.connection_changed.connect(self.set_connected)

    # ---- layout ------------------------------------------------------------
    def _restyle(self) -> None:
        """The stylesheet: the HUD's glass, solid over the key colour."""
        keyed = str(self._settings.get("stream.game_view")) == "key colour"
        self.setStyleSheet(STREAM_CSS + (stream_hud.css(keyed) if self._hud else ""))

    def _build_hud(self) -> None:
        """The game over the whole canvas, the cards on it (gui/stream_hud)."""
        hud = stream_hud
        self.view = _GameView(STREAM_W, STREAM_H, hud=True)
        self.view.setParent(self)
        self.view.move(0, 0)
        self.view.live.landmark_words = False   # brackets, no words, on the game's HUD

        self.header = _Header(compact=True)
        self.header.setParent(self)
        hud.place(self.header, hud.BAR)

        self.now = _NowCard()
        self.stats = _StatsCard()
        self.gear = _GoalsCard()
        self.thinking = _FeedPanel()
        self.chat = _ChatCard()
        self.extras = stream_extras.StreamExtras(
            self.view, push=self._toast, path=self._path,
            board=lambda: self.games.board, get=self._get, clock=self.clock,
            opened_at=self._opened_at,
            relayout=lambda: self._arrange(self._goals_on))
        self.pager = self.extras.pager(self.gear)
        for card, rect in ((self.now, hud.NOW), (self.thinking, hud.FEED),
                           (self.stats, hud.STATS), (self.pager, hud.PAGER),
                           (self.chat, hud.CHAT)):
            card.setParent(self)
            hud.place(card, rect)
            card.show()
        # WHAT CHAT CAN TYPE goes on the chat card, where chat looks
        self.chat.body.insertWidget(0, self.header.cta)

        # THE SUBTITLE: the commentary line, and the DEMO banner
        self.subtitle = hud.Subtitle(self)
        hud.place(self.subtitle, hud.SUBTITLE)
        self.subtitle.add(self.header.banner)
        self.subtitle.add(self.header.caption, 1)
        self.header.subtitle = self.subtitle
        self.subtitle.refresh()
        # the left cards, out of the way of a game menu (_menus)
        self._left_out = False
        self._slides: list = []
        self._left_back = QTimer(self)
        self._left_back.setSingleShot(True)
        self._left_back.setInterval(stream_hud.MENU_MAX_S * 1000)
        self._left_back.timeout.connect(lambda: self._left_away(False))
        self._arrange(goals=False)
        # CHAT'S W RAIN (gui/stream_rain, 8ee), over the whole window: made
        # last, so it is above everything else in it.
        self.rain = stream_rain.RainOverlay(self, get=self._get,
                                            blocked=self.games._blocked,
                                            picture=self.view.geometry())

    def _build(self) -> None:
        if self._hud:
            self._build_hud()
            return
        self.header = _Header()
        self.header.setParent(self)
        self.header.setGeometry(MARGIN, MARGIN, STREAM_W - 2 * MARGIN, HEADER_H)
        top = MARGIN + HEADER_H + GAP

        self.view = _GameView()
        self.view.setParent(self)
        self.view.move(MARGIN, top)

        side_x = MARGIN + VIEW_W + GAP
        self.thinking = _FeedPanel()
        self.thinking.setParent(self)
        self.thinking.setGeometry(side_x, top, SIDE_W, FEED_H)

        self.chat = _ChatCard()
        self.chat.setParent(self)
        self.chat.setGeometry(side_x, top + FEED_H + GAP, SIDE_W,
                              VIEW_H + GAP + BOTTOM_H - FEED_H - GAP)
        bottom_y = top + VIEW_H + GAP

        self.now = _NowCard()
        self.stats = _StatsCard()
        self.gear = _GoalsCard()
        # THE BOTTOM-RIGHT CARD TURNS between today's records, the quests and
        # the gear goals (gui/stream_extras, 8ec).
        self.extras = stream_extras.StreamExtras(
            self.view, push=self._toast, path=self._path,
            board=lambda: self.games.board, get=self._get, clock=self.clock,
            opened_at=self._opened_at,
            relayout=lambda: self._arrange(self._goals_on))
        self.pager = self.extras.pager(self.gear)
        row = QWidget(self)
        row.setGeometry(MARGIN, bottom_y, VIEW_W, BOTTOM_H)
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(GAP)
        box.addWidget(self.now)
        box.addWidget(self.stats)
        box.addWidget(self.pager)
        self._arrange(goals=False)
        # CHAT'S W RAIN (gui/stream_rain, 8ee), over the whole window: made
        # last, so it is above everything else in it.
        self.rain = stream_rain.RainOverlay(self, get=self._get,
                                            blocked=self.games._blocked,
                                            picture=self.view.geometry())

    def _arrange(self, goals: bool) -> None:
        """Fixed widths, because stretch factors let the widest text win.

        With the gear goals the three share 1,256 px; without them the two
        left split it. The stats card is sized for three 17-character
        sub-lines ("an hour after the join" is the longest the code writes).
        """
        self._goals_on = goals
        self.pager.show_page("gear", goals)
        third = self.pager.has_pages()
        self.pager.setVisible(third)
        if self._hud:                    # the HUD's cards have their own places
            return
        widths = BOTTOM_WITH_GOALS if third else BOTTOM_WITHOUT_GOALS
        for card, width in zip((self.now, self.stats, self.pager), widths):
            card.setFixedWidth(width)

    # ---- settings -------------------------------------------------------------
    def _get(self, key: str):
        return self._settings.get(key)

    def _path(self, name: str) -> Path:
        if self._var is not None:
            return self._var / name
        from ..datapaths import var
        return var(name)

    def setting_changed(self, key: str, value) -> None:
        self._settings[key] = value
        if key in ("stream.twitch_channel", "stream.chat_file",
                   "stream.youtube_channel", "stream.youtube_api_key"):
            self._chat_restart.start()          # once typing stops
        elif key == "stream.game_view":
            self.view.set_mode(value)
            self._restyle()                  # the HUD's cards: glass or solid
            # THE MASKS STAY ON OVER THE KEY COLOUR, solid (8ec)
            self._keyed = str(value) == "key colour"
            self.guard.set_keyed(self._keyed)
            self.view.toasts.raise_()
            self.extras.recap.raise_()
            self.rain.raise_()
        self.rain.setting_changed(key, value)    # off clears it; key colour (8ee)
        if key in GATE_KEYS:
            # the gate reads its settings at once, and what is already on
            # screen goes through it again (8ec)
            self.privacy.configure(self._settings)
            privacy.show_utc(self.privacy.utc)
            self._ledger_clean = []
            self._rescrub()
        elif key.startswith("stream."):
            self.guard.refresh()             # the masks read theirs as they draw
        self._refresh_chat()

    def _rescrub(self) -> None:
        """WHAT IS ALREADY ON SCREEN goes through the gate again, as it now
        stands. The owner adds a word to "Also hide these words" exactly when
        he has just seen it on stream, and a label drawn before that kept it:
        MEASURED (review/word_after.py, redteam/rt_late_word.py) 3 of 4 pieces
        still showed it -- the feed's rows, RIGHT NOW's detail and its DECIDED
        line, which changes only when the chosen field does. Every label,
        bar and fitted line keeps the text it was given and draws it through
        the gate again (gui/stream_privacy.rescrub); the text the window
        keeps for chat's answers is scrubbed again as each answer is drawn.
        The clock may have changed too (stream.utc_times)."""
        stream_privacy.rescrub(self)
        self.header.tick()
        self.guard.rescrub()
        self.guard.refresh()
        self.extras.redraw()
        self.header.set_caption(self.extras.caption())
        self._refresh_stats()
        self._refresh_then()

    # ---- chat -----------------------------------------------------------------
    def _restart_chat(self) -> None:
        # YOUTUBE (DESIGN 8ed): the Data API's public read of a live chat,
        # with the owner's API key. A reader already reading what the two
        # YouTube settings say is KEPT: an edit to the Twitch box or the
        # chat file is no reason to drop a live chat and start its twin.
        key = str(self._get("stream.youtube_api_key") or "").strip()
        where = str(self._get("stream.youtube_channel") or "").strip()
        kept = None
        for reader in self._readers:
            if kept is None and isinstance(reader, stream_chat.YouTubeReader) \
                    and reader.same(key, where):
                kept = reader
                continue
            reader.stop()
        self._readers = [kept] if kept is not None else []
        channel = stream_chat.channel_from(self._get("stream.twitch_channel"))
        raw = str(self._get("stream.twitch_channel") or "").strip()
        states = []
        # NO CHAT SETTING'S OWN TEXT IS QUOTED on the card, which is on the
        # stream: what is in a box that is not a channel or a file could be
        # the YouTube key, pasted into the wrong one (review of 8ed). A
        # channel is 25 characters at most, lower-cased, so it cannot hold
        # the whole key, and one that starts like a cut key is refused too.
        if channel and not stream_chat.looks_secret(raw):
            self._readers.append(stream_chat.TwitchReader(
                channel, on_line=self._signals.line.emit,
                on_state=self._signals.state.emit).start())
            states.append(f"connecting to twitch.tv/{channel}")
        elif raw:
            states.append("the Twitch channel setting is not a channel name")
        if where and stream_chat.youtube_target(where) is None:
            states.append("the YouTube setting is not a channel or a video")
        elif where and not key:
            states.append("no YouTube API key set")
        elif where and not stream_chat.YT_KEY.match(key):
            states.append("YouTube API key is malformed")
        elif where and kept is not None:
            states.append(kept.state or "connecting to YouTube chat")
        elif where:
            self._readers.append(stream_chat.YouTubeReader(
                key, where, on_line=self._signals.line.emit,
                on_state=self._signals.state.emit,
                on_subs=self._signals.subs.emit).start())
            states.append("connecting to YouTube chat")
        path = str(self._get("stream.chat_file") or "").strip()
        if path:
            self._readers.append(stream_chat.FileChat(
                path, on_line=self._signals.line.emit,
                on_state=self._signals.state.emit).start())
            states.append("opening the chat file")
        self._update_listening()
        # Seen by viewers too, so it says what is true and not how to set it
        # up: Settings › Stream says that, for the owner.
        self._chat_state = " · ".join(states) or "no chat connected"
        self._refresh_chat()

    def _on_subs(self, count: int) -> None:
        """YouTube's subscriber count (stream/subs), every YT_SUBS_EVERY: the
        goal in the header, and a thank-you when it went up."""
        change = self.subs.seen(count)
        self.header.set_subs(self.subs.count)
        self.announcer.subscribers(self.subs.count, self.subs.goal, change)
        if change is None:
            return
        if change.reached:
            title = f"{change.reached:,} subscribers!"
            body = f"Thank you all! Next goal: {change.goal:,}"
        else:
            title = "New subscriber!" if change.new == 1 else f"{change.new} new subscribers!"
            body = f"{change.count:,} / {change.goal:,} — thank you!"
        self._toast(Toast("subs", title, body, seconds=8.0))

    def _update_listening(self) -> None:
        """The games listen only while a reader is really connected: a
        TwitchReader after its JOIN, a FileChat while its file is there. A
        reader that exists but cannot reach chat -- no network, a file that
        is not there -- must not open polls nobody can answer."""
        self.games.set_listening(any(getattr(reader, "connected", False)
                                     for reader in self._readers))
        self._drain()

    def _on_chat(self, line) -> None:
        self.rain.hear(line)       # chat's W rain (8ee): never raises, and the games still hear it
        try:
            self.games.hear(self.privacy.chat(line))
            self._drain()
            self._refresh_chat()
        except Exception:
            pass
        self._jump_asked(line)

    def _jump_asked(self, line) -> None:
        """Chat's "jump", to the bot (DESIGN 8ef). The bot decides whether
        and when; this only asks, and says nothing on screen itself -- the
        bot's own "chat made me jump" line does, once it has jumped."""
        try:
            if not self._get(stream_jump.KEY_ON):
                self.jumps.clear()
                return
            if self.jumps.hear(line):
                self._send_jumps()
        except Exception:
            pass

    def _send_jumps(self) -> None:
        event = self.jumps.due()
        if event is not None:
            self._send(event)

    def _on_chat_state(self, text: str) -> None:
        self._chat_state = clip(text, 60)
        self._update_listening()
        self._refresh_chat()

    def _send(self, event) -> bool:
        return bool(self.bridge is not None and self.bridge.send(event))

    def _facts(self) -> Facts:
        return Facts(honey=self._honey, rate=self._honey_rate()[0],
                     trips=self._trips_24h, deaths=self._deaths_24h(),
                     plan=self._plan, why=self._why, where=self._where,
                     goal=self._goal_line)

    # ---- the bot's events --------------------------------------------------
    def set_connected(self, connected: bool) -> None:
        was = getattr(self, "_connected", False)
        self._connected = bool(connected)
        guard = getattr(self, "guard", None)
        if guard is not None:
            guard.set_link(self._connected)
        if connected and not was:
            # A new bot process, most likely after a rejoin: chat's vote goes
            # again if the last one never reached the gate (stream/show).
            self.games.resend()
        self._header_state()

    def _header_state(self) -> None:
        if not getattr(self, "_connected", False):
            # THE SOCKET IS DOWN AT EVERY REJOIN. MEASURED over run-393 to
            # run-432: 66 s median and 83 s at most between one run's last
            # line and the next's first, 32 restarts, and most trips end in
            # one (stream/gate). While the watchdog is alive that is the bot
            # rejoining, not the bot gone, and the header says so.
            try:
                alive = bool(self._bot_alive and self._bot_alive())
            except Exception:
                alive = False
            self.header.set_state("rejoining" if alive else "offline")
        elif self._running is not None and self._running[2]:
            self.header.set_state("owner")
        elif self._running is not None and self._running[1]:
            self.header.set_state("paused")
        else:
            self.header.set_state("live")

    def handle(self, event, quiet: bool = False) -> None:
        """Every event the bot sends. Never raises: the stream must not be
        the reason the main window stops drawing.

        THROUGH THE GATE FIRST (stream/privacy, 8ec): every string in the
        event is scrubbed, and a line that is only a system detail never
        arrives. A Frame passes untouched."""
        try:
            event = self.privacy.event(event)
            if event is None:
                return
            self._handle(event, quiet)
            self._side(event, quiet)
            self._menus(event, quiet)
        except Exception:
            pass

    def _menus(self, event, quiet: bool) -> None:
        """The HUD's left cards slide away while the bot reads a game menu
        (stream_hud.MENU_OPENS), and back when it is done (MENU_CLOSES)."""
        if not self._hud or quiet or not isinstance(event, Log):
            return
        text = str(event.message or "")
        if text.startswith(stream_hud.MENU_OPENS):
            self._left_away(True)
        elif text.startswith(stream_hud.MENU_CLOSES):
            self._left_away(False)

    def _left_away(self, away: bool) -> None:
        if away == self._left_out:
            return
        self._left_out = away
        x = -(stream_hud.SIDE_W + 24) if away else stream_hud.LEFT_X
        for card in (self.stats, self.pager, self.chat):
            slide = QPropertyAnimation(card, b"pos", self)
            slide.setDuration(380)
            slide.setEndValue(QPoint(x, card.y()))
            slide.setEasingCurve(QEasingCurve.InOutCubic)
            slide.finished.connect(lambda a=slide: self._slides.remove(a)
                                   if a in self._slides else None)
            self._slides.append(slide)
            slide.start()
        if away:
            self._left_back.start()
        else:
            self._left_back.stop()

    def _side(self, event, quiet: bool) -> None:
        """The masks and the entertainment (8ec) hear every event after the
        stream has: the bot's word on its menu, who has the controls, the
        commentary line, the day's counters."""
        self.guard.hear(event, quiet)
        if isinstance(event, (Considered, TaskUpdate, Thought, Log)):
            self.extras.saw(event, quiet)
            self.header.set_caption(self.extras.caption())
            if not quiet:
                self.announcer.hear(event)

    def _toast(self, item) -> None:
        """Every toast goes on the picture through here, through the gate,
        so the commentary and the clip markers hear of it too (8ec)."""
        item = self.privacy.data(item)
        self.view.toasts.push(item)
        self.extras.toasted(item)
        self.announcer.toasted(item)
        self.header.set_caption(self.extras.caption())

    def _handle(self, event, quiet: bool) -> None:
        if isinstance(event, Frame):
            # decoded for the masks too while the picture is keyed (8ec): the
            # guard judges the frames the stream no longer shows
            if not quiet and not self._mirrored and (self.view.live.isVisible()
                                                     or self._keyed):
                self.view.live.show_frame(event)
            return
        if isinstance(event, Thought) and event.topic == "where":
            self._where = where_from(event.text)
            self.now.where.set_text(self._where)
            spot = self.spotter.seen(event)
            if spot is not None and not quiet:
                self._toast(spot)
            return
        if isinstance(event, Thought) and event.topic == "plan":
            if event.text.startswith("staying up to"):
                self._stay = event.text
            else:
                self._plan = event.text
                self.now.plan.set_text(plain(event.text))
            self._refresh_then()
        if isinstance(event, (Thought, Log)):
            item, new = self.feed.add(event)
            if item is not None:
                self.thinking.add(item, new, animate=not quiet)
            self.games.on_bot_said(event, count=not quiet)
            spot = highlight_of(event, trip=self._chosen.replace("_", " "))
            if (spot is not None and spot.kind == "death"
                    and not self.spotter.first_death_line(event)):
                spot = None                  # one death, told two to four times
            if spot is not None and not quiet:
                self._toast(spot)
            return
        if isinstance(event, Considered):
            self._ranking = list(event.options or [])
            self._chosen = event.chosen
            # !why answers from the newest decision: the plan thought is sent
            # only when the chosen field changes (brain/report.Reporter.plan),
            # the ranking with its rationale on every plan.
            if event.rationale:
                self._why = (f"{event.chosen.replace('_', ' ')}: {event.rationale}"
                             if event.chosen else event.rationale)
            # DECIDED IS NEVER BLANK WHILE THE BOT IS DECIDING (the owner: "in
            # the decided category nothing shows"). The plan thought that fills
            # it is sent only when the chosen field changes, so with the field
            # pinned a window opened mid-session showed "—" for hours; this
            # ranking arrives with every plan, so it stands in until one does.
            if event.chosen and not self._plan:
                self.now.plan.set_text(
                    f"gather in {event.chosen.replace('_', ' ')}"
                    + (f" — {plain(event.rationale)}" if event.rationale else ""))
            self._refresh_chat()
            return
        if isinstance(event, TaskUpdate):
            self._task(event, quiet)
            return
        if isinstance(event, Metric):
            if event.name == "honey":
                self._honey = float(event.value)
                self.games.on_honey(self._honey, self._honey_rate()[0])
            elif event.name == "honey_per_hour":
                self._rate = float(event.value)
            self._refresh_stats()
            return
        if isinstance(event, StatusUpdate):
            self._running = (event.running, event.paused, event.handed_over)
            self._header_state()
            return
        if isinstance(event, ChatBallot):
            self.games.on_ballot(event)
            if not quiet:
                self._drain()
            self._refresh_chat()

    def _task(self, event: TaskUpdate, quiet: bool) -> None:
        name = ACTIVITY.get(event.name, event.name[:1].upper() + event.name[1:])
        if event.status == "failed":
            name = f"{name} — did not work"
        self.now.activity.setText(name)
        self.now.detail.set_text(plain(event.detail))
        if self.view.viewfinder is not None:
            self.view.viewfinder.set_task(event.name if event.status == "running" else "")
        if event.progress is not None and event.progress >= 0:
            self.now.bar.set_value(float(event.progress))
            self.now.bar.setVisible(True)
        elif event.name != "gather":
            self.now.bar.setVisible(False)
        if (event.name == "travel to the field" and event.status == "running"
                and not quiet):
            # The last trip's row is in the ledger by now (it is filed before
            # the next trip plans), but the 5 s poll may not have read it:
            # read it first, so it settles the last call before this one.
            self._poll_files()
            self.games.trip_started()
            self._drain()

    # ---- the clock and the files -----------------------------------------------
    def _tick(self) -> None:
        try:
            self.header.tick()
            if not self._connected:
                self._header_state()
            self.games.tick()
            self._send_jumps()               # asks folded in the last second
            self.extras.tick()               # the recap at midnight (8ec)
            self.guard.tick()                # a mask's hold runs out (8ec)
            self._drain()
            self._refresh_stats()
            self._refresh_then()
            self._refresh_chat()
        except Exception:
            pass

    def _drain(self) -> None:
        for item in self.games.drain():
            self._toast(item)

    def _changed(self, path: Path) -> bool:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        if self._mtimes.get(path) == mtime:
            return False
        self._mtimes[path] = mtime
        return True

    def _poll_files(self) -> None:
        """The bot's own files: the ledger, the errand timers, the quests."""
        try:
            ledger_path = self._path("trips.jsonl")
            if self._changed(ledger_path) or self._totals is None:
                from ..brain.goals import balance_rate
                from ..brain.ledger import Ledger
                ledger = Ledger(ledger_path)
                # the ledger's words (a reason, a convert note) through the
                # gate: a void call and a clip marker quote them (8ec)
                rows = self._clean_rows(ledger.trips())
                self.games.on_trips(rows)
                self.extras.rows(rows)       # records and streaks (8ec)
                day = [r for r in rows
                       if float(r.get("at") or 0) >= self.clock() - 86400]
                self._totals = ledger.totals(rows=day)
                # A TRIP IS ONE THAT GATHERED. The ledger also has a row for
                # each carry-in convert after a rejoin and for each cycle that
                # never left (a stop, a failed claim): MEASURED, 52 rows in
                # the 24 h to 2026-09-26 07:11, 31 of which gathered.
                self._trips_24h = sum(1 for r in day if gathered(r))
                # once a trip, with the ledger: the logs' hand-ins (show)
                self._quests_24h = handed_in_24h(self._path("night"), self.clock())
                rate = balance_rate(rows)
                self._balance_rate = rate.per_hour if rate else None
                self._rate_from = (f"rise over {rate.hours:.1f} h"
                                   if rate else "")
            ready = self._path("errand_ready.json")
            if self._changed(ready):
                body = json.loads(ready.read_text())
                clock = body.get("wealth_clock") if isinstance(body, dict) else None
                if isinstance(clock, dict) and clock.get("ready_at"):
                    self._clock_due = float(clock["ready_at"])
                    panel = str(clock.get("panel") or "")
                    # "predicted: an hour after joining this server" is the
                    # errand's own booking (DESIGN 8dd); said plainly here.
                    self._clock_from = ("an hour after the join"
                                        if panel.startswith("predicted")
                                        else "read off its panel")
            quests = self._path("quests.json")
            if self._changed(quests):
                body = self.privacy.data(json.loads(quests.read_text()))
                self.games.on_quests(body)
                self.extras.quest_file(body)     # the quest bars (8ec)
                self.announcer.quest_file(body)  # and the voice's check-ins
            self._drain()
            self._refresh_stats()
            self._refresh_then()
        except Exception:
            pass

    def _refresh_goals(self) -> None:
        """The gear goals from `brain.goals`, when this build has it.

        It is the feat/goals planner (DESIGN 8dp). Without it the card is not
        drawn at all: an empty "goals" box on a stream reads as broken.
        """
        try:
            from ..brain import goals as goals_plan
        except Exception:
            self._arrange(goals=False)
            return
        try:
            plan = goals_plan.from_files(
                var_root=self._var, honey=int(self._honey) if self._honey else None,
                honey_from="the bot's HUD reading" if self._honey else "",
                honey_at=self.clock() if self._honey else None)
            self._goal_line = plan.headline()
            self.gear.show_plan(plan, var_root=self._var)
            self._arrange(goals=bool([r for r in plan.rows if not r.owned]))
        except Exception:
            self._arrange(goals=False)

    # ---- drawing ----------------------------------------------------------------
    def _refresh_stats(self) -> None:
        s = self.stats
        s.honey.set(human(self._honey) if self._honey is not None else "—",
                    "read off the HUD" if self._honey is not None else "not read yet")
        totals = self._totals
        rate, rate_from = self._honey_rate()
        s.rate.set(human(rate) if rate else "—", rate_from if rate else
                   "no convert measured yet")
        if totals is not None:
            s.trips.set(f"{self._trips_24h}",
                        f"{human(totals.honey)} honey banked")
            deaths = self._deaths_24h()
            s.deaths.set(f"{deaths}", "in the last 24 h",
                         theme.BAD if deaths else theme.TEXT)
        s.quests.set(f"{max(self._quests_24h, self.games.handed_in)}", "in the last 24 h")
        if self._clock_due:
            left = self._clock_due - self.clock()
            s.clock.set("ready" if left <= 0 else human_duration(left),
                        self._clock_from,
                        theme.GOOD if left <= 0 else theme.ACCENT)
        else:
            s.clock.set("—", "no time booked")

    def _deaths_24h(self) -> int:
        """Knock-outs in the last 24 hours: the ones the bot kept an incident
        of or the stream saw, or the ledger's count if that is more. MEASURED:
        the ledger booked 4 of the 7 real ones in its span (stream/extras.
        Knockouts)."""
        totals = self._totals
        booked = totals.deaths if totals is not None else 0
        try:
            seen = self.extras.knockouts_since(self.clock() - 86400)
        except Exception:
            seen = 0
        return max(booked, seen)

    def _clean_rows(self, raw: list) -> list:
        """The ledger's rows through the gate, scrubbing only the rows added
        since the last read. The ledger is append-only (brain/ledger.append)
        and never trimmed, about 96 rows a day, almost every one with its own
        gather_ended string: MEASURED (review/ledger_cost.py) a whole scrub
        at every read cost 20.5 ms at 414 rows, and 246 ms at 10,350 once
        the distinct strings outgrew the gate's cache, on the GUI thread at
        every trip. A read that is not the last one plus new rows (another
        file, a rewrite) is scrubbed whole."""
        have = self._ledger_clean
        keep = (have and len(raw) >= len(have)
                and raw[0].get("at") == self._ledger_first
                and raw[len(have) - 1].get("at") == self._ledger_last)
        if keep:
            have = have + self.privacy.data(raw[len(have):])
        else:
            have = self.privacy.data(raw)
        self._ledger_clean = have
        self._ledger_first = raw[0].get("at") if raw else None
        self._ledger_last = raw[-1].get("at") if raw else None
        return have

    def _honey_rate(self):
        """(honey per hour, where it came from).

        THE BALANCE'S RISE, the rate the gear goals' ETAs use, so the stream
        and the Goals tab cannot disagree: MEASURED in DESIGN 8dp, the
        ledger's own `honey_per_hour` read 1,957,015/h over a sitting in
        which the balance rose 7,956,853/h, because most honey is banked by
        carry-in cycles after a rejoin. The bot's `honey_per_hour` metric is
        `FarmLoop.Report`'s, honey over THIS run's elapsed time, and a run
        ends at every rejoin, so it is the fallback and says so.
        """
        if self._balance_rate:
            return self._balance_rate, self._rate_from
        if self._rate:
            return self._rate, "this run so far"
        return None, ""

    def _refresh_then(self) -> None:
        bits = []
        if self._stay:
            bits.append(self._stay)
        if self._clock_due and self._clock_due > self.clock():
            bits.append("Wealth Clock at "
                        + privacy.clock_text(self._clock_due, "%H:%M", zone=True))
        if self.games.pending:
            bits.append(self.games.pending)
        self.now.then.set_text(plain(" · ".join(bits)) or "—")

    def _refresh_chat(self) -> None:
        c, g = self.chat, self.games
        # The chat's connection state belongs to CHAT PLAYS; on the planner a
        # line like "waiting for a live stream on @…" is noise to a viewer.
        c.subtitle.setText(self._chat_state if g.listening else "")
        c.title.setText("CHAT PLAYS" if g.listening else "THE PLANNER")
        now = self.clock()
        poll = g.poll

        def plural(n: int, word: str) -> str:
            return f"{n} {word}{'' if n == 1 else 's'}"

        if poll is not None:
            counts = poll.counts()
            total = sum(counts) or 1
            left = max(0, int(poll.ends_at - now))
            c.vote_head.label.setText("CHAT PICKED THE NEXT FIELD" if poll.closed
                                      else "WHERE SHOULD THE NEXT TRIP GO?")
            c.vote_head.right.setText("" if poll.closed else f"{left // 60}:{left % 60:02d}")
            c.bars.set_rows([(f"!{i + 1}", o["label"],
                              f"{plural(counts[i], 'vote')} · {o.get('share', 0):.0%} of best",
                              counts[i] / total, counts[i] == max(counts) and counts[i] > 0)
                             for i, o in enumerate(poll.options)])
            c.bars.show()
            c.vote_note.setText(g.pending if poll.closed else
                                "only fields the planner ranks near its own best "
                                f"· type !1 to !{len(poll.options)}")
        elif self._ranking:
            best = max((o.score for o in self._ranking), default=0.0) or 1.0
            c.vote_head.label.setText("WHAT THE PLANNER IS WEIGHING")
            c.vote_head.right.setText("")
            chosen = self._chosen.replace("_", " ")
            # With no chat there is room for the whole of the top of the
            # ranking the bot sent (brain/report.TOP_FIELDS).
            shown = self._ranking[:4 if g.listening else 7]
            c.bars.set_rows([(f"#{i + 1}", o.label, _score(o.score, o.unit),
                              max(0.0, o.score) / best, o.label == chosen)
                             for i, o in enumerate(shown)])
            c.bars.show()
            # With no chat, the chosen field's own reasoning, in the
            # planner's words (brain/decide.FieldScore.why, via Considered).
            mine = next((o for o in self._ranking if o.label == chosen), None)
            c.vote_note.setText((f"why {chosen}: {clip(plain(mine.why), 200)}"
                                 if mine is not None and mine.why else "")
                                if not g.listening else
                                g.pending or g.poll_note or
                                ("chat may not pick fields — that is the owner's "
                                 "switch" if not self._get("stream.chat_may_pick_fields")
                                 else ""))
        else:
            c.vote_head.label.setText("WAITING FOR THE PLANNER")
            c.vote_head.right.setText("")
            c.bars.hide()
            c.vote_note.setText(g.pending or g.poll_note)

        # THE GAMES NEED A CHAT. With no reader running nothing typed can
        # reach them, so the call and the board are not drawn at all.
        games = bool(self._get("stream.chat_games")) and g.listening
        p = g.prediction
        calling = p is not None and now <= p.ends_at
        for widget in (c.call_head, c.calls, c.result, c.board):
            widget.setVisible(games)
        if p is not None:
            yes = sum(1 for v in p.calls.values() if v)
            no = len(p.calls) - yes
            total = (yes + no) or 1
            left = int(p.ends_at - now)
            c.call_head.label.setText(f"CALL THE TRIP — OVER {human(p.line)} HONEY?")
            c.call_head.right.setText(f"{left // 60}:{left % 60:02d}" if left > 0
                                      else "locked")
            c.calls.set_rows([("!yes", "over", plural(yes, "call"), yes / total, yes >= no and yes > 0),
                              ("!no", "under", plural(no, "call"), no / total, no > yes)])
            c.calls.setVisible(games)
            c.result.setText(g.last_result or
                             ("calls are locked — the trip is under way" if not calling
                              else "type !yes or !no before the timer runs out"))
        else:
            c.call_head.label.setText("CALL THE TRIP")
            c.call_head.right.setText("")
            c.calls.hide()
            c.result.setText(g.last_result or "a call opens when the next trip leaves the hive")
        top = g.top(3)
        c.board.setText(("<span style='color:%s; font-weight:800;'>TOP CALLERS</span>&nbsp;&nbsp; "
                         % CHAT) + " &nbsp;·&nbsp; ".join(
            f"{i + 1}. {_html(n)} <b>{r}</b>/{k}" for i, (n, r, k) in enumerate(top))
            if top else "")
        named = g.leading_name()
        c.milestone.setText((f"NEXT MILESTONE {human(g.milestone)} honey"
                             + (f" — “{named[0]}” leads with {named[2]}" if named else
                                " — name it with !name" if self._get("stream.chat_names")
                                and g.listening else "")) if g.milestone else "")
        crowded = poll is not None and len(poll.options) > 3
        c.ticker.setText("   ".join(text for _user, text in g.ticker[-2:]))
        # WHAT TYPING DOES RIGHT NOW, in the header and at the card's foot.
        voting = poll is not None and not poll.closed and g.listening
        live = [f"!1-!{len(poll.options)}" if voting else "",
                "!yes !no" if games and calling else "",
                "!why" if games else "", "!stats" if games else ""]
        self.header.set_cta([x for x in live if x])
        c.help.setText("  ".join(filter(None, [
            f"!1-!{len(poll.options)}" if voting else "",
            "!yes !no !stats !why !where !goal !points !top" if games else "",
            "!name" if self._get("stream.chat_names") and g.listening else ""])))
        # An empty line is not drawn: the first render had two blank rows
        # between the call and the milestone, which read as a layout fault.
        for label, allowed in ((c.vote_note, True), (c.result, games),
                               (c.board, games), (c.milestone, True),
                               (c.ticker, not crowded), (c.help, True)):
            label.setVisible(allowed and bool(label.text()))

    def _window(self):
        """The window this layout is shown in: its scaling frame, or itself."""
        return self.host if self.host is not None else self

    def toggle_full_screen(self) -> None:
        """The header's Full screen button and F11."""
        win = self._window()
        if win.isFullScreen():
            win.showNormal()
        else:
            win.showFullScreen()

    def fits_on_screen(self) -> bool:
        """Does the whole 1920x1080 layout fit in the screen's usable area
        (the panel and a title bar take some of it)?"""
        screen = self._window().screen()
        if screen is None:
            return True
        area = screen.availableGeometry()
        return area.width() >= STREAM_W and area.height() >= STREAM_H

    def show_fitting(self) -> None:
        """Open windowed where the layout fits, full screen where it does not
        -- a 1920x1080 monitor, where a windowed layout loses its foot. In a
        scaling frame (gui/stream_frame) full screen fills any screen."""
        win = self._window()
        if self.fits_on_screen():
            win.show()
        else:
            win.showFullScreen()

    def changeEvent(self, event) -> None:
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.WindowStateChange:
            self.header.full.setVisible(not self.isFullScreen())
        super().changeEvent(event)

    def keyPressEvent(self, event) -> None:
        """F11: full screen, Esc: back. On a 1920x1080 monitor the title bar
        pushes a 1080-px window's foot off the screen; full screen is the
        canvas exactly, for OBS to capture (docs/pending/stream.md)."""
        if event.key() == Qt.Key_F11:
            self.toggle_full_screen()
            return
        if event.key() == Qt.Key_Escape and self._window().isFullScreen():
            self._window().showNormal()
            return
        super().keyPressEvent(event)

    def _speak_next(self) -> None:
        """The next line, when the voice is free (stream/voice's pacing)."""
        try:
            if not self._get("stream.voice") or self.voice.busy():
                return
            line = self.announcer.next_line(self.clock())
            if line:
                line = stream_privacy.scrub(line)
                if self.voice.say(line):
                    self._said(line)
        except Exception:
            pass                 # the stream must never go down with its voice

    def _said(self, line: str) -> None:
        """WHAT THE VOICE SAID, in var/stream_voice.txt: the newest
        VOICE_LOG_LINES, "HH:MM:SS  words" (on the stream's clock), to read
        back what viewers heard -- the words are not written anywhere else."""
        path = self._path("stream_voice.txt")
        try:
            kept = path.read_text().splitlines()[-(VOICE_LOG_LINES - 1):] if path.exists() else []
        except OSError:
            kept = []
        kept.append(f"{privacy.clock_text(self.clock(), '%H:%M:%S')}  {line}")
        try:
            path.write_text("\n".join(kept) + "\n")
        except OSError:
            pass

    def closeEvent(self, event) -> None:
        for reader in self._readers:
            reader.stop()
        self._readers = []
        for timer in (self._ticker, self._files, self._goals, self._chat_restart,
                      self._voice_timer):
            timer.stop()
        self.voice.stop()
        self.rain.clear()                        # and its frame timer
        if self.bridge is not None:
            try:
                self.bridge.event_received.disconnect(self.handle)
                self.bridge.connection_changed.disconnect(self.set_connected)
            except (RuntimeError, TypeError):
                pass
        self.closed.emit()
        super().closeEvent(event)

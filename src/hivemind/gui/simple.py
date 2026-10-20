"""Simple mode: the window as a finished product (the owner, 2026-10-14).

THE OWNER'S ASK: "make our UI user friendly ... a simple mode and then an
advanced mode but like the window should be more proffessional and really nice
looking smart with animations, animations can mean alot to people". It opens
by default; the switch top right flips to Advanced (today's window) and back.

    +--------------------------------------------------------------------------+
    | ⬢ Hivemind  ● LIVE          [▶ Start] [❚❚ Pause] [■ Stop]  [Simple|Adv.] |
    +------------------------------------------------+-------------------------+
    | the game, as the bot sees it (16:9)            | WHAT IT'S THINKING      |
    |  [pop-ups when something happens]              |  its own words, plain   |
    | GATHERING                                      |  English, newest last   |
    | Gathering in Pine Tree · bag 94%               |                         |
    +-----------+-----------+-----------+------------+-------------------------+
    | HONEY     | HONEY/HR  | TRIPS     | QUESTS     | WHAT IT'S SAVING FOR    |
    +-----------+-----------+-----------+------------+  the shopping list, with|
    | PLANTERS   (ring)  (ring)  (ring)              |  bars                   |
    +------------------------------------------------+-------------------------+

NOTHING ON IT IS NEW DATA, AND LITTLE OF IT IS NEW CODE. The picture is the
Advanced live view, mirrored through the privacy gate as the stream does
(LiveView.mirror, stream_privacy.GatedMirror): decoded once. The feed, the
pop-ups, the shopping list and the plain English are stream mode's (stream/show
Feed, highlight_of, Spotter, plain; gui/stream _FeedPanel, _ToastLayer,
_GoalsCard). The numbers are the stream's too: honey from the bot's HUD (or
the ledger's last convert), honey an hour as the balance's rise
(brain/goals.balance_rate), trips from var/trips.jsonl, quests from the run
logs (stream/show.handed_in_24h). The planters are var/planters.json, the
bot's own record of what it put out (act/planter), or Planter events.

EVERY WORD PASSES THE GATE (stream/privacy): each event at the door, and every
label as it is drawn -- this window may be the one on TikTok.

ANIMATION IS CHEAP AND ONLY ON CHANGE: a number rolls, a bar or ring glides,
a card or row fades in, a pop-up slides -- each 300-900 ms, ease-out, and only
while it can be seen (widgets.can_animate). The one thing that keeps moving is
the live dot, at 10 fps (widgets.PulseDot). Files are read every few seconds
only while this page is up, and the ledger only when it changed.
"""
from __future__ import annotations

import json
import re
import time

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..stream import privacy
from ..stream.show import (Feed, Spotter, gathered, handed_in_24h, highlight_of, human,
                           plain, toast)
from ..telemetry.events import Considered, Frame, Log, Metric, Planter, TaskUpdate, Thought
from ..world.settings import defaults
from . import stream_privacy, theme
from .panels.liveview import LiveView
from .panels.planters import seed_colour
from .stream import GATE_KEYS, _FeedPanel, _FitLabel, _GoalsCard, _ToastLayer
from .widgets import (Card, CountUp, Meter, ModeSwitch, PulseDot, Ring, can_animate,
                      human_duration)

GAP = 12
HEADER_H = 64
TILES_H = 116
PLANTERS_H = 132
RIGHT_MIN_W = 440            # the feed and the goals: narrower and the rows wrap to mush
CAPTION_H = 108              # the sentence over the bottom of the picture
POLL_MS = 5000               # the bot's files, while this page is up
GOALS_EVERY_S = 20.0         # the shopping list reads five files; honey arrives far faster

# The activity's tag and colour, as theme.py spends colour: green is progress
# in the field, blue is moving, gold is honey.
ACTIVITY = {
    "gather": ("GATHERING", theme.GOOD),
    "travel to the field": ("ON THE WAY", theme.INFO),
    "return to the hive": ("HEADING HOME", theme.INFO),
    "convert": ("MAKING HONEY", theme.ACCENT),
}
PERCENT = re.compile(r"\((\d{1,3})%\)")

CSS = f"""
QFrame#Card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 200, 90, 0.075), stop:1 rgba(255, 170, 40, 0.025));
    border: 1px solid {theme.GLASS_EDGE};
    border-radius: 14px;
}}
QLabel#CardTitle {{
    color: {theme.ACCENT}; font-size: 11px; font-weight: 700; letter-spacing: 2px;
}}
QLabel#CardSub {{ color: {theme.TEXT_FAINT}; font-size: 11px; }}
QLabel#Count {{
    font-family: {theme.MONO}; font-size: 34px; font-weight: 800; color: #ffe2a0;
}}
QLabel#TileCaption {{
    color: {theme.TEXT_DIM}; font-size: 11px; font-weight: 700; letter-spacing: 2px;
}}
QPushButton[big="true"] {{
    font-size: 15px; font-weight: 700; min-height: 28px;
    padding-left: 20px; padding-right: 22px;
}}
"""


def place(name) -> str:
    """'pine_tree' -> 'Pine Tree'."""
    return " ".join(w.capitalize() for w in str(name or "").replace("_", " ").split())


def first_clause(text: str, limit: int = 140) -> str:
    """The head of a planner's why, in plain English: up to its first ';'."""
    head = plain(str(text or "")).split(";")[0].strip()
    return head if len(head) <= limit else head[:limit - 1].rstrip() + "…"


def sentence(task, field: str) -> tuple[str, str, str]:
    """(tag, colour, the one plain sentence) for the bot's newest TaskUpdate:
    "Gathering in Pine Tree · bag 94%"."""
    where = place(field) or "the field"
    if task is None:
        return "READY", theme.TEXT_DIM, "Waiting for its first move"
    if task.name not in ACTIVITY:          # a step this page has no words for
        name = str(task.name or "working")
        p = task.progress if task.progress is not None and task.progress >= 0 else None
        return "WORKING", theme.TEXT_DIM, name[:1].upper() + name[1:] + (
            f" · {p:.0%}" if p is not None and task.status == "running" else "")
    tag, colour = ACTIVITY[task.name]
    detail = str(task.detail or "")
    pct = PERCENT.search(detail)
    bag = f" · bag {pct.group(1)}%" if pct else ""
    p = task.progress if task.progress is not None and task.progress >= 0 else None
    if task.status == "failed":
        doing = {"gather": "Gathering", "convert": "Making honey",
                 "travel to the field": f"The trip to {where}",
                 "return to the hive": "The walk home"}.get(task.name, place(task.name))
        return tag, theme.WARN, f"{doing} didn't work — recovering"
    if task.name == "gather":
        if task.status == "running":
            return tag, colour, f"Gathering in {where}" + (
                f" · bag {p:.0%}" if p is not None else bag)
        return tag, colour, f"Bag full in {where}{bag} — heading home"
    if task.name == "travel to the field":
        if task.status == "running":
            how = "Flying" if "cannon" in detail else "Walking"
            return tag, colour, f"{how} to {where}"
        return tag, colour, f"Reached {where}"
    if task.name == "return to the hive":
        return tag, colour, ("Walking home to the hive" if task.status == "running"
                             else "Home at the hive")
    if task.name == "convert":
        if task.status == "running":
            return tag, colour, "Making honey at the hive" + (
                f" · {p:.0%} done" if p is not None else bag)
        return tag, colour, "Honey made — planning the next trip"
    return tag, colour, place(task.name)


# ---- motion ---------------------------------------------------------------------
def rise_in(widgets, step_ms: int = 55, ms: int = 450, rise: int = 14) -> None:
    """Cards fade in and slide up into place, one after another. Opacity is
    an effect dropped at the end (a finished one still renders through an
    offscreen buffer); the slide gives way to the layout if it moves them."""
    live = [w for w in widgets if can_animate(w)]
    for w in live:
        effect = QGraphicsOpacityEffect(w)
        effect.setOpacity(0.0)
        w.setGraphicsEffect(effect)
    for i, w in enumerate(live):
        QTimer.singleShot(i * step_ms, lambda w=w: _rise(w, ms, rise))


def _rise(w: QWidget, ms: int, rise: int) -> None:
    try:
        effect = w.graphicsEffect()
    except RuntimeError:                    # the window has gone
        return
    if not isinstance(effect, QGraphicsOpacityEffect):
        return
    base = QPoint(w.pos())
    state = {"at": None}
    anim = QVariantAnimation(w)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def frame(t) -> None:
        if w.graphicsEffect() is not effect:  # a newer entrance took over (Qt
            anim.stop()                       # deleted this effect with it)
            return
        t = float(t)
        effect.setOpacity(t)
        if state["at"] is not None and w.pos() != state["at"]:
            state["at"] = False             # the layout placed it: fade only
        if state["at"] is not False:
            state["at"] = QPoint(base.x(), base.y() + round((1.0 - t) * rise))
            w.move(state["at"])

    def done() -> None:
        if w.graphicsEffect() is not effect:
            return
        w.setGraphicsEffect(None)
        if state["at"] is not False:
            w.move(base)

    anim.valueChanged.connect(frame)
    anim.finished.connect(done)
    anim.start()


def crossfade(stack, page, ms: int = 320) -> None:
    """Show `page` in the QStackedWidget `stack`, the old page's picture
    fading out over it -- one grab, then a fading pixmap, ~20 frames."""
    old = stack.currentWidget()
    if old is page:
        return
    if old is None or not can_animate(stack):
        stack.setCurrentWidget(page)
        return
    cover = QLabel(stack)
    cover.setPixmap(old.grab())
    cover.setGeometry(old.geometry())
    stack.setCurrentWidget(page)
    cover.show()
    cover.raise_()
    effect = QGraphicsOpacityEffect(cover)
    cover.setGraphicsEffect(effect)
    fade = QPropertyAnimation(effect, b"opacity", cover)
    fade.setDuration(ms)
    fade.setStartValue(1.0)
    fade.setEndValue(0.0)
    fade.setEasingCurve(QEasingCurve.InOutQuad)
    fade.finished.connect(cover.deleteLater)
    fade.start()


# ---- the pieces ---------------------------------------------------------------------
class _Chip(QFrame):
    """● LIVE, and the other states: a pill with the pulsing dot."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Chip")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 12, 2)
        row.setSpacing(2)
        self.dot = PulseDot(theme.BAD, 8)
        row.addWidget(self.dot)
        self.word = QLabel("OFFLINE")
        row.addWidget(self.word)
        self.set_state("OFFLINE", theme.BAD, False)

    def set_state(self, word: str, colour: str, pulsing: bool) -> None:
        if getattr(self, "_state", None) == (word, colour, pulsing):
            return                        # every StatusUpdate asks; restyle on change
        self._state = (word, colour, pulsing)
        c = QColor(colour)
        rgb = f"{c.red()}, {c.green()}, {c.blue()}"
        self.setStyleSheet(
            f"QFrame#Chip {{ background: rgba({rgb}, 0.12); border: 1px solid rgba({rgb}, 0.45);"
            " border-radius: 13px; }")
        self.word.setText(word)
        self.word.setStyleSheet(f"color: {colour}; font-size: 11px; font-weight: 800;"
                                " letter-spacing: 2px; background: transparent;")
        self.dot.set_state(colour, pulsing)


class _Header(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.setFixedHeight(HEADER_H)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 8, 12, 8)
        row.setSpacing(12)
        mark = QLabel("⬢")
        mark.setStyleSheet(f"color: {theme.ACCENT}; font-size: 26px; background: transparent;")
        row.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        brand = QLabel("Hivemind")
        brand.setObjectName("Hero")
        names.addWidget(brand)
        self.note = _FitLabel(1, f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self.note.setMinimumWidth(180)
        names.addWidget(self.note)
        row.addLayout(names)
        row.addSpacing(6)
        self.chip = _Chip()
        row.addWidget(self.chip, 0, Qt.AlignVCenter)
        # QUESTIONS FOR HIM live on the Advanced page (the Decision Inbox);
        # here, how many wait, and one click to them
        self.questions = QPushButton("")
        self.questions.setObjectName("Primary")
        self.questions.setCursor(Qt.PointingHandCursor)
        self.questions.setToolTip("Questions the bot is asking you: answer them on the Advanced page")
        self.questions.hide()
        row.addWidget(self.questions, 0, Qt.AlignVCenter)
        row.addStretch(1)
        self.start = self._button("▶  Start", "Primary", "Start the bot, or resume it (F1)")
        self.pause = self._button("❚❚  Pause", "", "Pause after the current step (F2)")
        self.stop = self._button("■  Stop", "Danger", "Release every key and stop (F3)")
        for button in (self.start, self.pause, self.stop):
            row.addWidget(button)
        row.addSpacing(10)
        self.mode_switch = ModeSwitch()
        row.addWidget(self.mode_switch)

    @staticmethod
    def _button(text: str, name: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        if name:
            button.setObjectName(name)
        button.setProperty("big", True)
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        return button


class _Caption(QWidget):
    """The sentence over the foot of the picture, on a dark gradient."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 10, 24, 12)
        box.setSpacing(2)
        box.addStretch(1)
        self.tag = QLabel("")
        box.addWidget(self.tag, 0, Qt.AlignLeft)
        self.line = _FitLabel(1, "color: #fff7e6; font-size: 22px; font-weight: 800;"
                                 " background: transparent;")
        box.addWidget(self.line)
        self.why = _FitLabel(1, f"color: {theme.TEXT_DIM}; font-size: 13px;"
                                " background: transparent;")
        box.addWidget(self.why)

    def set(self, tag: str, colour: str, line: str, why: str) -> None:
        self.tag.setText(f"●  {tag}")
        self.tag.setStyleSheet(f"color: {colour}; font-size: 11px; font-weight: 800;"
                               " letter-spacing: 2px; background: rgba(8, 6, 3, 0.6);"
                               " border-radius: 4px; padding: 2px 8px 2px 6px;")
        self.line.set_text(line)
        self.why.set_text(why)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0.0, QColor(8, 6, 3, 0))
        shade.setColorAt(0.35, QColor(8, 6, 3, 160))
        shade.setColorAt(1.0, QColor(8, 6, 3, 232))
        painter.fillRect(self.rect(), shade)


class _Picture(QFrame):
    """The game as the bot sees it, the sentence and the pop-ups over it."""

    def __init__(self, source, frame_filter):
        super().__init__()
        self.setObjectName("Panel")
        self.inner = QWidget(self)
        self.live = LiveView(self.inner)
        # brackets without words on the game's own counters, as on the stream
        self.live.landmark_words = False
        self.live._hint.setText("the game appears here while the bot plays")
        # HALF-SIZE FRAMES UP TO 1024 WIDE: at the default 1560x940 the picture
        # is 1003 px, and the full decode for a 4% enlargement nobody can see
        # cost 8% of a core more (MEASURED offscreen, 25 fps, 21.8% against
        # 13.5% for Advanced). From 1024 up it is the full frame, crisp.
        self.live.full_above = (1024, 576)
        self.mirror = (stream_privacy.GatedMirror(self.live, source, frame_filter)
                       if source is not None else None)
        self.caption = _Caption(self.inner)
        self.toasts = _ToastLayer(self.inner)
        self.toasts.VISIBLE = 2

    PAD = 6

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        p = self.PAD
        self.inner.setGeometry(p, p, self.width() - 2 * p, self.height() - 2 * p)
        w, h = self.inner.width(), self.inner.height()
        self.live.setGeometry(0, 0, w, h)
        self.caption.setGeometry(0, h - CAPTION_H, w, CAPTION_H)
        self.toasts.setGeometry(0, 0, w, h - CAPTION_H + 10)
        self.toasts.raise_()


class _Tile(QFrame):
    """One big number that rolls up, its caption and one plain line."""

    def __init__(self, caption: str, colour: str, fmt=human):
        super().__init__()
        self.setObjectName("Panel")
        box = QVBoxLayout(self)
        box.setContentsMargins(20, 12, 18, 12)
        box.setSpacing(0)
        head = QLabel(f"<span style='color:{colour}'>⬢</span>&nbsp;&nbsp;{caption.upper()}")
        head.setObjectName("TileCaption")
        head.setTextFormat(Qt.RichText)
        box.addWidget(head)
        self.number = CountUp(fmt)
        self.number.setObjectName("Count")
        box.addWidget(self.number)
        self.sub = _FitLabel(1, f"color: {theme.TEXT_DIM}; font-size: 12px;"
                                " background: transparent;")
        box.addWidget(self.sub)
        box.addStretch(1)

    def set(self, value, sub: str) -> None:
        self.number.set_number(value)
        self.sub.set_text(sub)


class _PlanterCell(QWidget):
    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(12)
        self.ring = Ring(60)
        self.ring.ease_ms = 900
        row.addWidget(self.ring, 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addStretch(1)
        self.name = QLabel("")
        self.name.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 700;")
        self.field = QLabel("")
        self.field.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        self.eta = QLabel("")
        col.addWidget(self.name)
        col.addWidget(self.field)
        col.addWidget(self.eta)
        col.addStretch(1)
        row.addLayout(col, 1)

    def set_planter(self, name: str, field: str, growth: float, ready_at: float,
                    now: float) -> None:
        self.ring.set_value(growth, colour=seed_colour(name))
        self.name.setText(name)
        self.field.setText(f"in {place(field)}" if field else "")
        left = ready_at - now if ready_at else None
        if growth >= 1.0:
            text, colour = "ready to harvest", theme.GOOD
        elif left is not None and left > 0:
            # minutes, not seconds: the page redraws every few seconds
            text = ("ready in " + (human_duration(left) if left >= 3600 else
                                   f"{max(1, round(left / 60))} min"))
            colour = theme.ACCENT
        else:
            text, colour = "growing", theme.TEXT_DIM
        self.eta.setText(text)
        self.eta.setStyleSheet(f"color: {colour}; font-size: 12px; font-weight: 700;"
                               f" font-family: {theme.MONO};")


class _Planters(Card):
    MOST = 3                             # "up to 3 planters active" (act/planter)

    def __init__(self):
        super().__init__("planters", "nectar growing in the fields")
        self.setFixedHeight(PLANTERS_H)
        row = QHBoxLayout()
        row.setSpacing(18)
        row.setContentsMargins(6, 0, 6, 0)
        self.cells = [_PlanterCell() for _ in range(self.MOST)]
        for cell in self.cells:
            row.addWidget(cell, 1)
            cell.hide()
        self.empty = QLabel("No planters out right now")
        self.empty.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 13px;")
        row.addWidget(self.empty, 1, Qt.AlignCenter)
        self.add_layout(row)

    def show_rows(self, rows: list, now: float) -> None:
        rows = rows[:self.MOST]
        for cell, data in zip(self.cells, rows):
            cell.set_planter(*data, now=now)
        for i, cell in enumerate(self.cells):
            cell.setVisible(i < len(rows))
        self.empty.setVisible(not rows)
        self.set_badge(str(len(rows)) if rows else "")


def planters_from_file(state: dict, now: float) -> list:
    """(name, field, growth, ready at) for each planter var/planters.json says
    is out -- the bot's own record (act/planter)."""
    from ..act import planter as planter_mod
    rows = []
    for key, body in (state.get("out") or {}).items():
        try:
            at = float((body or {}).get("at") or 0.0)
            grow = planter_mod.planter_grow_s(state, key)
        except (TypeError, ValueError, AttributeError):
            continue
        if not at or not grow:
            continue
        name = planter_mod.PLANTERS.get(key, (place(key),))[0]
        rows.append((name, body.get("field") or "", max(0.0, min(1.0, (now - at) / grow)),
                     at + grow))
    return sorted(rows, key=lambda r: r[3])


class _Columns(QWidget):
    """The two columns, placed by hand: a fixed size inside a layout is a
    floor the window can never shrink below (a banner appearing made the
    window grow by its height), and these sizes follow the window."""

    def __init__(self, left: QWidget, right: QWidget, fit):
        super().__init__()
        self._left, self._right, self._fit = left, right, fit
        left.setParent(self)
        right.setParent(self)
        self.setMinimumSize(320 + GAP + RIGHT_MIN_W, TILES_H + PLANTERS_H + 2 * GAP + 120)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        wide = self._fit(w, h)
        self._left.setGeometry(0, 0, wide, h)
        self._right.setGeometry(wide + GAP, 0, w - wide - GAP, h)


# ---- the page ------------------------------------------------------------------------
class SimplePage(QWidget):
    """Simple mode. Fed every event the window gets (`handle`); never raises."""

    start_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    questions_clicked = Signal()

    def __init__(self, live_source=None, settings=None, var_root=None, clock=time.time,
                 parent=None):
        super().__init__(parent)
        self.setStyleSheet(CSS)
        self.clock = clock
        self._var = var_root
        self._settings = defaults()
        self._settings.update(dict(settings or {}))
        # THE GATE (stream/privacy): every event at the door, and every label
        # this page draws through it again -- the stream window's gate when one
        # is open, which is made from the same settings.
        self.privacy = privacy.Redactor(self._settings)
        stream_privacy.activate(self.privacy)

        self.feed = Feed()
        self.spotter = Spotter()
        self._task = None
        self._field = ""
        self._why = ""
        self._where = ""
        self._connected = False
        self._honey = None
        self._honey_live = False
        self._run_rate = None
        self._rows_read = None            # (honey, at) of the ledger's last convert
        self._rate = None
        self._rate_hours = 0.0
        self._trips_today = None
        self._banked_today = 0
        self._quests_24h = None
        self._handed: list = []           # hand-ins seen since the window opened
        self._ledger_rows = None
        self._mtimes: dict = {}
        self._planter_events: dict = {}
        self._planter_state: dict = {}
        self._plan = None
        self._plan_at = 0.0
        self._plan_due = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(GAP)
        self.header = _Header()
        self.mode_switch = self.header.mode_switch
        self.header.start.clicked.connect(self.start_clicked)
        self.header.pause.clicked.connect(self.pause_clicked)
        self.header.stop.clicked.connect(self.stop_clicked)
        self.header.questions.clicked.connect(self.questions_clicked)
        outer.addWidget(self.header)

        self.left = QWidget()
        left = QVBoxLayout(self.left)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(GAP)
        self.picture = _Picture(live_source, self.privacy.frame)
        left.addWidget(self.picture)
        tiles = QHBoxLayout()
        tiles.setSpacing(GAP)
        self.honey = _Tile("honey", theme.ACCENT)
        self.rate = _Tile("honey / hour", theme.GOOD)
        self.trips = _Tile("trips today", theme.INFO, fmt=lambda v: f"{v:,.0f}")
        self.quests = _Tile("quests · 24 h", "#c4b5fd", fmt=lambda v: f"{v:,.0f}")
        self.tiles = [self.honey, self.rate, self.trips, self.quests]
        for tile in self.tiles:
            tile.setFixedHeight(TILES_H)
            tiles.addWidget(tile, 1)
        left.addLayout(tiles)
        self.planters = _Planters()
        left.addWidget(self.planters)

        self.right = QWidget()
        right = QVBoxLayout(self.right)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(GAP)
        self.thinking = _FeedPanel(newest_first=True)
        # its rows must not stretch the window: the panel shows the newest
        # that fit whole (_FeedPanel._fit), so it asks for no height itself
        self.thinking._box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        self.thinking.title.setText("⬢  WHAT IT'S THINKING")
        self.thinking.subtitle.setText("its own words, as it decides")
        self._quiet = QLabel("Its thoughts appear here as it plays.")
        self._quiet.setAlignment(Qt.AlignCenter)
        self._quiet.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 13px;")
        self.thinking.body.insertWidget(0, self._quiet)
        right.addWidget(self.thinking, 1)
        self.goals = _GoalsCard()
        self.goals.title.setText("⬢  WHAT IT'S SAVING FOR")
        for bar in self.goals.findChildren(Meter):
            bar.ease_ms = 700
        # its own height: the feed takes what is left, not the other way
        self.goals.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        right.addWidget(self.goals)
        outer.addWidget(_Columns(self.left, self.right, self._fit), 1)

        self._poll = QTimer(self)
        self._poll.timeout.connect(self.refresh)
        self._poll.start(POLL_MS)
        self._goals_timer = QTimer(self)
        self._goals_timer.setSingleShot(True)
        self._goals_timer.timeout.connect(self._apply_plan)
        self.set_run_state(False, False, False, False, False, "")
        self._draw_caption()

    # ---- layout -----------------------------------------------------------------
    def _fit(self, width: int, height: int) -> int:
        """THE PICTURE IS 16:9 EXACTLY, never letterboxed: the left column is
        as wide as the height left over allows, and the right takes the rest
        -- or, on a narrow window, the picture gives its spare height to the
        planters. Returns the left column's width."""
        pad = 2 * _Picture.PAD
        tall = height - TILES_H - PLANTERS_H - 2 * GAP
        wide = round((tall - pad) * 16 / 9) + pad
        wide = max(320, min(wide, width - GAP - RIGHT_MIN_W))
        shown = min(tall, round((wide - pad) * 9 / 16) + pad)
        self.picture.setFixedHeight(max(120, shown))
        self.planters.setFixedHeight(max(PLANTERS_H, height - shown - TILES_H - 2 * GAP))
        return wide

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        if self._plan_due:
            self._apply_plan()
        if not event.spontaneous():       # not a restore from minimised
            rise_in([self.picture, *self.tiles, self.planters, self.thinking, self.goals])

    # ---- from the window -----------------------------------------------------------
    def setting_changed(self, key: str, value) -> None:
        """A privacy setting: the gate changes at once, and what is on screen
        goes through it again (stream_privacy.rescrub)."""
        self._settings[key] = value
        if key in GATE_KEYS:
            self.privacy.configure(self._settings)
            stream_privacy.rescrub(self)

    def set_controls(self, buttons) -> None:
        """Start, Pause and Stop as the Advanced bar has them: [(enabled, text)]."""
        (start, _), (pause, pause_text), (stop, _) = buttons
        self.header.start.setEnabled(start)
        self.header.pause.setEnabled(pause)
        self.header.pause.setText("▶  Resume" if "Resume" in pause_text else "❚❚  Pause")
        self.header.stop.setEnabled(stop)

    def set_questions(self, count: int) -> None:
        """How many of the Decision Inbox's questions wait for him."""
        self.header.questions.setText(f"{count} question{'' if count == 1 else 's'} for you  →")
        self.header.questions.setVisible(count > 0)

    def set_run_state(self, connected: bool, running: bool, paused: bool, handed: bool,
                      alive: bool, note: str) -> None:
        self._connected = bool(connected)
        self._alive = bool(alive)
        if handed:
            state = ("YOU'RE PLAYING", theme.INFO, False)
        elif connected and paused:
            state = ("PAUSED", theme.WARN, False)
        elif connected and running:
            state = ("LIVE", theme.GOOD, True)
        elif connected:
            state = ("IDLE", theme.TEXT_DIM, False)
        elif alive:
            state = ("STARTING", theme.WARN, True)
        else:
            state = ("OFFLINE", theme.BAD, False)
        self.header.chip.set_state(*state)
        self.header.note.set_text(privacy.utc_clock(note) if self.privacy.utc else note)
        self._draw_caption()

    def set_plan(self, plan) -> None:
        """The gear plan the window just built (brain/goals); drawn at most
        every GOALS_EVERY_S, and only while this page is up."""
        self._plan = plan
        self._plan_due = True
        if not can_animate(self):
            return                        # drawn when the page is next shown
        wait = GOALS_EVERY_S - (self.clock() - self._plan_at)
        if wait <= 0:
            self._apply_plan()
        elif not self._goals_timer.isActive():
            self._goals_timer.start(int(wait * 1000))

    def _apply_plan(self) -> None:
        if self._plan is None or not can_animate(self):
            return
        self._plan_due = False
        self._plan_at = self.clock()
        try:
            self.goals.show_plan(self._plan, var_root=self._var_root())
        except Exception:
            pass

    # ---- events ------------------------------------------------------------------
    def handle(self, event) -> None:
        if isinstance(event, Frame):
            return                        # the picture is the Advanced view's, mirrored
        try:
            event = self.privacy.event(event)
            if event is not None:
                self._handle(event)
        except Exception:
            pass                          # Simple must never stop the window drawing

    def _handle(self, event) -> None:
        if isinstance(event, Metric):
            if event.name == "honey":
                self._honey, self._honey_live = float(event.value), True
            elif event.name == "honey_per_hour":
                self._run_rate = float(event.value)
            else:
                return
            self._numbers()
            return
        if isinstance(event, TaskUpdate):
            self._task = event
            self._draw_caption()
            return
        if isinstance(event, Considered):
            if not event.chosen:
                return
            why = first_clause(event.rationale)
            if "field" in str(event.question or "").lower():
                self._field, self._why = event.chosen, why
                self._draw_caption()
                text = f"going to {place(event.chosen)}"
            else:
                text = str(event.chosen)
            # THE DECISION, in its own words, once a plan: the plan thought
            # is only sent when the field changes (brain/report)
            self._feed(Thought(at=event.at, topic="plan",
                               text=text + (f" — {why}" if why else "")))
            return
        if isinstance(event, Planter):
            self._planter_events[event.id] = event
            self._draw_planters()
            return
        if isinstance(event, Thought) and event.topic == "where":
            self._where = event.text.split(" · ")[0].replace("I am ", "", 1)
            self._pop(self.spotter.seen(event))
            if not self._why:
                self._draw_caption()
            return
        if isinstance(event, (Thought, Log)):
            if isinstance(event, Thought) and event.topic == "plan" and \
                    str(event.text).startswith("gather in the"):
                return                    # the Considered above said it, with its why
            self._feed(event)
            spot = highlight_of(event, trip=place(self._field))
            if spot is not None and spot.kind == "death" and \
                    not self.spotter.first_death_line(event):
                spot = None               # one death, told two to four times
            if spot is not None and spot.kind == "quest":
                self._handed.append(self.clock())
                self._numbers()
            self._pop(spot)

    def _feed(self, event) -> None:
        item, new = self.feed.add(event)
        if item is None:
            return
        self._quiet.hide()
        self.thinking.add(item, new, animate=can_animate(self.thinking))

    def _pop(self, item) -> None:
        """A pop-up over the picture, through the gate -- only where it can
        be seen: one that slid in unseen would be stale by the time it was."""
        if item is not None and can_animate(self.picture):
            self.picture.toasts.push(self.privacy.data(item))

    # ---- drawing --------------------------------------------------------------------
    def _draw_caption(self) -> None:
        if not self._connected:
            tag, colour = ("STARTING", theme.WARN) if self._alive else ("OFFLINE", theme.TEXT_FAINT)
            line = ("Joining the game…" if self._alive
                    else "The bot is not running — press Start")
            why = self._why and f"Last plan: {place(self._field)} — {self._why}"
        else:
            tag, colour, line = sentence(self._task, self._field)
            why = (f"Why {place(self._field)}: {self._why}" if self._why and self._field
                   else plain(self._where) if self._where else "")
        self.picture.caption.set(tag, colour, line, why or "")

    def _numbers(self) -> None:
        if self._honey is not None:
            self.honey.set(self._honey, "live, read off the game" if self._honey_live
                           else "at its last convert")
        else:
            self.honey.set(None, "not read yet")
        if self._rate:
            self.rate.set(self._rate, f"the balance's rise over {self._rate_hours:.1f} h")
        elif self._run_rate:
            self.rate.set(self._run_rate, "this run so far")
        else:
            self.rate.set(None, "measuring…")
        if self._trips_today is not None:
            self.trips.set(self._trips_today, f"{human(self._banked_today)} honey banked"
                           if self._banked_today else "since midnight")
        else:
            self.trips.set(None, "no trips read yet")
        since = self.clock() - 86400
        seen = sum(1 for at in self._handed if at >= since)
        quests = max(self._quests_24h or 0, seen)
        self.quests.set(quests if (self._quests_24h is not None or seen) else None,
                        "handed in, last 24 hours")

    def _draw_planters(self) -> None:
        now = self.clock()
        if self._planter_events:
            rows = [(p.seed, p.field, float(p.growth), float(p.ready_at or 0.0))
                    for p in self._planter_events.values()]
        else:
            rows = planters_from_file(self._planter_state, now)
        self.planters.show_rows(rows, now)

    # ---- the bot's files -------------------------------------------------------------
    def _var_root(self):
        if self._var is not None:
            return self._var
        from ..datapaths import VAR_ROOT
        return VAR_ROOT

    def _changed(self, path) -> bool:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        if self._mtimes.get(path) == mtime:
            return False
        self._mtimes[path] = mtime
        return True

    def refresh(self) -> None:
        """Re-read what changed: the ledger (a row a trip), the planters. Only
        while the page can be seen; showing it calls this first."""
        if not can_animate(self):
            return
        try:
            root = self._var_root()
            ledger = root / "trips.jsonl"
            if self._changed(ledger):
                self._read_ledger(ledger, root)
            planters = root / "planters.json"
            if self._changed(planters):
                body = json.loads(planters.read_text())
                self._planter_state = body if isinstance(body, dict) else {}
            self._draw_planters()          # growth moves with the clock
            self._numbers()
        except Exception:
            pass

    def _read_ledger(self, path, root) -> None:
        from ..brain.goals import balance_rate, latest_balance
        from ..brain.ledger import Ledger
        now = self.clock()
        rows = Ledger(path).trips()
        day = privacy.day_start(now)
        today = [r for r in rows if float(r.get("at") or 0.0) >= day]
        self._trips_today = sum(1 for r in today if gathered(r))
        self._banked_today = sum(int(r.get("honey") or 0) for r in today
                                 if r.get("converted") and (r.get("honey") or 0) > 0)
        rate = balance_rate(rows)
        self._rate = rate.per_hour if rate else None
        self._rate_hours = rate.hours if rate else 0.0
        if not self._honey_live:
            last = latest_balance(rows)
            self._honey = float(last[0]) if last else self._honey
        self._quests_24h = handed_in_24h(root / "night", now)
        # A TRIP BANKED SINCE THE LAST READ: its pop-up
        before = self._ledger_rows
        self._ledger_rows = len(rows)
        if before is not None and len(rows) > before:
            row = rows[-1]
            honey = int(row.get("honey") or 0)
            if gathered(row) and row.get("converted") and honey > 0:
                self._pop(toast("convert", f"+{human(honey)} honey",
                                f"a trip to {place(row.get('credited') or row.get('chosen'))}"
                                " banked at the hive"))

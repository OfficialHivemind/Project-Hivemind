"""The Hivemind window.

    +------------------------------------------------------------------+
    | status: connection · vitals · autonomy · run controls            |
    +--------------------------+---------------------------------------+
    |                          | [pending questions, when any]         |
    |   live view              +---------------------------------------+
    |   (what it sees, with    | Think | Economy | Fields | Account |   |
    |    detections drawn)     |                                       |
    +--------------------------+                                       |
    |   planters               |   the reasoning stream, or whichever  |
    |   (growth + field health)|   workspace tab is selected           |
    +--------------------------+---------------------------------------+
    | current task + progress                                          |
    +------------------------------------------------------------------+

The left column answers "is it working" -- what it sees, and what it has
growing. The right column answers "is it working *sensibly*", which is the
question you spend far longer on, so it gets the tabs and the space.

Pending questions sit above the tabs rather than in a modal dialog. A modal
would freeze the window while the bot carried on playing behind it, which is
backwards: the bot should keep going and the question should wait.

That is the ADVANCED page. The window opens on SIMPLE (gui/simple, the owner,
2026-10-14): the same live view, big, with the numbers, the plain-English
feed, the goals and the planters. The switch top right flips between them and
is kept in settings (`gui.mode`).
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QProgressBar, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QTabWidget, QVBoxLayout,
                               QWidget)

from .launcher import BotProcess
from ..telemetry.events import (Action, Answer, Autonomy, Belief, Command,
                                Considered, Event, Expiry, FieldStatus, Frame,
                                Log, Metric, Planter, Question, QuestStep,
                                ShadowPrice, StatusUpdate, TaskUpdate, Thought)
from ..telemetry.events import Timer as TimerEvent
from ..world.settings import SECRET, defaults
from . import theme
from .panels.beliefs import BeliefTable
from .panels.economy import EconomyPanel
from .panels.fields import FieldsPanel
from .panels.gear import GearGoalsPanel
from .panels.goals import GoalWeb
from .panels.hiveplanner import HivePlannerPanel
from .panels.ledger import LedgerPanel
from .panels.liveview import LiveView
from .panels.planters import PlanterPanel
from .panels.question import DecisionInbox
from .panels import report
from .panels.quests import QuestsPanel
from .panels.sentinel import SentinelPanel
from .panels.settings import SettingsPanel
from .panels.telegram import TelegramTab
from .panels.status import StatusBar
from .panels.storage import StorageTab
from .panels.think import LogPanel, ThinkPanel
from .panels.timers import TimersPanel
from .panels.vision import VisionPanel
from .widgets import Card, ElidedLabel
from .simple import SimplePage, crossfade
from .stream import StreamWindow
from .stream_frame import StreamFrame


# THE TRIP LEDGER, written by scripts/run_farm.py as each trip ends. Same path
# as its TRIP_LEDGER; read here rather than received as an event because the
# event stream restarts with the run and this file does not.
TRIP_LEDGER = Path(__file__).resolve().parents[3] / "var" / "trips.jsonl"

# HOW MUCH A STREAM WINDOW OPENED MID-TRIP IS HANDED (DESIGN 8dv): the last
# 300 events that are not frames. The bot narrates 18.8 lines a minute
# (stream/show), and a trip adds a few task and metric updates besides, so this
# is several minutes -- more than the 30 rows the stream's feed can show.
STREAM_RECENT = 300


class _Chose:
    """The bot's own words about its choice, shaped like a Decision.

    Deliberately NOT a re-derived decision: the panel must show what the bot
    said it was doing, not what the GUI would have decided in its place.
    """

    __slots__ = ("action", "field", "why")

    def __init__(self, text: str):
        import re
        self.why = str(text or "")
        # THE SHAPE brain/decide.Decision.describe() WRITES (DESIGN 8du):
        # "<action> in the <field words> field — <why>". The old parse looked
        # for a colon that is never there, so the field was always None and
        # the node read just "gather"; and any why mentioning a convert made
        # a gather look like one.
        head, _, _ = self.why.partition(" — ")
        found = re.match(r"(\w+)(?: in the (.+?) field)?$", head.strip())
        self.field = (found.group(2).strip().lower().replace(" ", "_")
                      if found and found.group(2) else None)
        self.action = (found.group(1).lower() if found else
                       "convert" if "convert" in self.why.lower() else "gather")


class MainWindow(QMainWindow):
    # Stop's outcome, posted back from the thread that waits for the bot to
    # exit, because that wait is 11-25 s and used to freeze the window.
    _stop_finished = Signal(str)

    def __init__(self, bridge, parent=None, bot=None):
        super().__init__(parent)
        self.bridge = bridge
        self.setWindowTitle("Hivemind")
        self.resize(1560, 940)
        self.setStyleSheet(theme.STYLESHEET)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        # A banner that only appears for a replay. See set_replay_banner.
        self._replay_banner = QLabel()
        self._replay_banner.setAlignment(Qt.AlignCenter)
        self._replay_banner.setStyleSheet(
            f"background: {theme.BAD}; color: #16161d; font-weight: 800;"
            " font-size: 13px; letter-spacing: 1px; padding: 7px;"
            " border-radius: 6px;")
        self._replay_banner.hide()
        outer.addWidget(self._replay_banner)
        # START ON BOOT's countdown (ROADMAP U13, gui/autostart): only after
        # a login start with the setting on. See begin_autostart.
        self._boot_banner = self._make_boot_banner()
        outer.addWidget(self._boot_banner)

        # TWO PAGES (the owner, 2026-10-14: a simple mode and an advanced
        # mode). ADVANCED is the window as it was -- the bar, the
        # columns, the task line -- untouched; SIMPLE (gui/simple) is the
        # finished-product face, built on Advanced's own live view. Every
        # event reaches both, whichever is shown (`handle`).
        self.advanced = QWidget()
        page = QVBoxLayout(self.advanced)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(10)
        self.status = StatusBar()
        page.addWidget(self.status)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._left_column())
        split.addWidget(self._right_column())
        split.setSizes([600, 960])
        page.addWidget(split, 1)

        page.addWidget(self._task_bar())

        self.simple = SimplePage(live_source=self.live,
                                 settings=self.settings.values)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.simple)
        self.pages.addWidget(self.advanced)
        outer.addWidget(self.pages, 1)
        # THE FOCUS STARTS ON THE PAGE, not on Start: Start greys out the
        # moment the bot runs, and Qt then hands its focus -- with a gold
        # focus ring -- to whatever comes next (the switch, "Stream mode").
        self.pages.setFocusPolicy(Qt.ClickFocus)
        self.pages.setFocus()

        bridge.event_received.connect(self.handle)
        # THE BOT AS A PROCESS THIS WINDOW OWNS. Play starts it, Stop ends it.
        # See gui/launcher for why signalling is by pid only and never by name.
        self.bot = bot if bot is not None else BotProcess()
        self._connected = False
        self._stopping = False
        self._stop_finished.connect(self._stop_done)
        # THE LAST CHOICE THE BOT ANNOUNCED. The plan thought is only re-sent
        # when the choice changes (brain/report), and the 30 s goal ticker
        # and every honey metric redrew the web with no decision -- so "doing
        # now" vanished within half a minute of appearing (DESIGN 8du).
        self._decision = None
        # THE BAR FIRST, THEN THE WINDOW (DESIGN 8du). Qt runs slots in the
        # order they were connected, and `set_connected(False)` resets the
        # bar to "nothing running"; run after it, `_on_connection` can say a
        # watchdog is alive and keep Stop live.
        bridge.connection_changed.connect(self.status.set_connected)
        bridge.connection_changed.connect(self._on_connection)
        self.status.autonomy_changed.connect(self._set_autonomy)
        # The run controls. These were declared and emitted by StatusBar but
        # connected to NOTHING, while set_status kept enabling and disabling
        # them -- so they looked live and clicking Stop on a running bot did
        # absolutely nothing.
        self.status.start_clicked.connect(self._start)
        self.status.pause_clicked.connect(self._pause_or_resume)
        self.status.stop_clicked.connect(self._stop)
        self.status.handover_clicked.connect(self._handover)
        # SIMPLE'S BIG BUTTONS are the same three, and follow the bar's state.
        self.simple.start_clicked.connect(self._start)
        self.simple.pause_clicked.connect(self._pause_or_resume)
        self.simple.stop_clicked.connect(self._stop)
        self.status.controls_changed.connect(self._sync_simple)
        # ITS QUESTIONS are answered on Advanced; Simple says how many wait
        self.simple.questions_clicked.connect(lambda: self.set_mode("advanced"))
        self.inbox.answered.connect(
            lambda *_: QTimer.singleShot(0, self._sync_questions))
        # THE SWITCH, top right on both pages; the mode is a setting
        # (`gui.mode`), so the window opens the way it was left.
        for switch in (self.status.mode_switch, self.simple.mode_switch):
            switch.chosen.connect(self.set_mode)
        self.show_mode(self.settings.values.get("gui.mode")
                       or defaults()["gui.mode"], animate=False)
        # STREAM MODE (DESIGN 8dv). The last events are kept so that a stream
        # window opened mid-trip starts with the plan, the numbers and the
        # recent reasoning instead of blank cards.
        self._stream = None
        self._stream_recent: list = []
        self._replay_name = ""
        bridge.event_received.connect(self._stream_keep)
        self.status.stream_clicked.connect(self.open_stream)
        # F1 START, F2 PAUSE, F3 STOP, as in Natro (while this window has focus).
        for key, slot in (("F1", self._start), ("F2", self._pause_or_resume),
                          ("F3", self._stop)):
            QShortcut(QKeySequence(key), self, slot)
        # THE PANIC KEY, IN LAYERS (gui/panic, RL1b step 3): F12 in this
        # window always, and a global one (the desktop's portal, an X11 grab)
        # where the bot's /dev/input watcher cannot read the keyboard. Each
        # ends in Stop. Which ones are armed is said in the log.
        from .panic import PanicLayers
        self.panic = PanicLayers(self, key=str(self.settings.values.get("safety.panic_key")
                                               or "F12"))
        self.panic.fired.connect(self._panic)
        self.panic.start()
        self.logs.add_thought(Thought(topic="run", text=self.panic.describe(),
                                      detail="; ".join(f"{k}: {v}" for k, v in
                                                       self.panic.notes.items())))
        print(f"  {self.panic.describe()}", flush=True)

        # Ages and countdowns must tick even when no events arrive, or a stale
        # reading looks fresh simply because the bot went quiet.
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self.beliefs.refresh_ages)
        self._ticker.start(5000)
        # The bot can die without ever connecting; the buttons must not keep
        # claiming it is running.
        self._bot_ticker = QTimer(self)
        self._bot_ticker.timeout.connect(self._watch_bot)
        self._bot_ticker.start(3000)

        self.status.set_connected(False)

        # DRAW THE GOALS IMMEDIATELY, not when the first event happens to
        # arrive. The owner opened the GUI before starting the bot and
        # reported no goals and no data in any tab, and they were right:
        # `refresh_goals` was only reachable
        # from a `honey` metric -- which the bot never sent -- or from the
        # once-per-cycle plan thought, so the tab stayed blank for minutes and
        # looked broken. The goal web is built from the knowledge files, which
        # are on disk and true whether or not a bot is running, so there is no
        # reason to make the owner wait for a socket to show them the plan.
        self.refresh_goals()
        # AND DRAW THE QUESTS THE SAME WAY, for the same reason.
        #
        # The quest panel filled from live events only, so opening the window
        # with the bot stopped showed "no quests picked up yet" -- while
        # `var/quests.json` held five real quests read off the game's own
        # menu minutes earlier. That reads as a bot that does not do quests,
        # which is exactly what the owner concluded: it did no quests and made
        # no progress. The file is the bot's own last reading,
        # on disk and true whether or not anything is running.
        self.seed_quests()
        self._goal_ticker = QTimer(self)
        self._goal_ticker.timeout.connect(self.refresh_goals)
        self._goal_ticker.timeout.connect(self.hive_planner.refresh)
        self._goal_ticker.start(30000)

    def _on_connection(self, connected: bool) -> None:
        """Remember whether the socket is up; Play needs to know.

        Also notices a bot that died before it ever connected -- the common
        failure, because the game's launch fails transiently -- and says so
        instead of leaving the window looking like nothing happened.
        """
        self._connected = bool(connected)
        if connected:
            return
        # EVERYTHING ON SCREEN IS NOW THE LAST READING, and says so (DESIGN
        # 8du): dimmed vitals, a held frame marked as held, no "doing now"
        # for a bot that is not there, and no handover it could confirm.
        for vital in (self.status.honey, self.status.pollen,
                      self.status.bees, self.status.rate):
            vital.mark_stale()
        self.live._degrade("the bot is not connected")
        self.status.set_handed_over(False)
        self._sync_take_control()
        if self._decision is not None:
            self._decision = None
            self.refresh_goals()
        if self.bot.running():
            # ALIVE, JUST NOT TALKING: joining, or between attempts. Stop
            # must stay live here -- it is a minute or more of every attempt.
            self.status.set_status(running=True, paused=False,
                                   note=self.bot.describe_state())
            return
        if self.bot.process is not None and not self.bot.running():
            code = self.bot.exit_code()
            if code:
                self.status.set_note(
                    f"the bot exited (code {code}) — see {self.bot.log_path}")
                self.status.set_status(running=False, paused=False)

    def _watch_bot(self) -> None:
        """Notice the bot going away on its own, so the buttons stay honest.

        And notice a WATCHDOG that is alive while the socket is down -- the
        bot between attempts, or joining -- so the bar does not ask "is the
        bot running?" of a bot that is. `set_connected(False)` writes that
        default text after this window's own slot has run, so the refinement
        lives here, on the three-second tick, rather than in the slot.

        AND STOP STAYS LIVE (DESIGN 8du). Only the note used to change, so the
        bar kept "nothing running" underneath it and Stop stayed grey for the
        whole join -- while the note said "Stop here stops it".
        """
        if self._stopping:
            return                  # the stop worker owns the bar until done
        self._show_ledger()
        if not self._connected and self.bot.running():
            self.status.set_status(running=True, paused=False,
                                   note=self.bot.describe_state())
            return
        if self.bot.process is None or self.bot.running():
            return
        if self._connected:
            return
        code = self.bot.exit_code()
        if code is not None and self.status._running:
            self.status.set_status(running=False, paused=False)
            self.status.set_note(
                f"the bot is no longer running (exit {code}) — "
                f"see {self.bot.log_path}")

    def _show_ledger(self) -> None:
        """The watchdog's own reasons (game guard, memory) as log rows."""
        from .launcher import ledger_news
        path = Path(self.bot.night) / "attempts.log" if hasattr(self.bot, "night") else None
        if path is None:
            return
        if not hasattr(self, "_ledger_at"):
            try:
                self._ledger_at = path.stat().st_size      # only what is new from now
            except OSError:
                self._ledger_at = 0
            return
        news, self._ledger_at = ledger_news(path, self._ledger_at)
        if any(" exited " in line and "exited 0" not in line for line in news):
            from .launcher import last_failure
            why = last_failure(path.parent)
            if why:
                news.append(f"the bot stopped while starting: {why}")
        for line in news:
            self.logs.add_thought(Thought(topic="run", text=f"watchdog: {line}", detail=""))
            self.status.set_note(f"watchdog: {line}")

    def set_replay_banner(self, name: str) -> None:
        """Mark the window as showing a RECORDING, not the live account.

        Every value in a replay is invented -- honey, bees, planters, the
        reasoning stream, the picture in the live view. Without this the window
        is indistinguishable from a live session, and it was: the owner asked
        where the stats came from while the game was not even open. Anything
        that can be mistaken for a real reading of their account has to announce
        itself.
        """
        self._replay_banner.setText(
            f"DEMO — REPLAYING {name}.  Every number here is made up; "
            "this is NOT your account.")
        self._replay_banner.show()
        self.setWindowTitle("Hivemind  —  DEMO (recorded data)")
        self._replay_name = name              # the stream window says so too

    # ---- layout -----------------------------------------------------------
    def _left_column(self) -> QWidget:
        column = QWidget()
        box = QVBoxLayout(column)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)

        live_card = Card("live view", "what it sees")
        self.live = LiveView()
        live_card.add(self.live, 1)
        # "SAVE THIS MOMENT" for a problem report (ROADMAP BUG-PACK)
        self.moment_row = report.moment_row(
            lambda: self.status.set_note(report.save_moment(self.bridge.send)))
        live_card.add(self.moment_row)
        box.addWidget(live_card, 3)

        self.planters = PlanterPanel()
        box.addWidget(self.planters, 2)
        return column

    def _right_column(self) -> QWidget:
        column = QWidget()
        box = QVBoxLayout(column)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)

        self.inbox = DecisionInbox()
        self.inbox.answered.connect(self._answer)
        box.addWidget(self.inbox)

        self._honey = None
        self._honey_at = None
        self.tabs = QTabWidget()
        self.think = ThinkPanel()
        self.beliefs = BeliefTable()
        self.logs = LogPanel()
        self.economy = EconomyPanel()
        self.sentinel = SentinelPanel()
        self.timers = TimersPanel()

        self.goals = GoalWeb()
        # THE GEAR THEY ASKED FOR (DESIGN 8dp), above the guide's goal web on
        # the same tab: "get me the porcelain staff and backpack and honey
        # mask/all ace equipment".
        self.gear = GearGoalsPanel()
        # THE HIVE COLOUR THE PROGRESSION FOLLOWS (progression.hive), picked
        # on the gear panel: saved like any setting, and re-planned at once.
        self.gear.hive_changed.connect(self._progression_hive)
        # WHAT IT DID, from the file rather than the event stream. The socket
        # restarts with the run -- 134 times on the night of 2026-09-21 -- so
        # it cannot answer "what did you do while I was asleep". See
        # panels/ledger and brain/ledger.
        self.ledger = LedgerPanel(TRIP_LEDGER)
        self.fields = FieldsPanel()
        self.quests = QuestsPanel()
        self.vision = VisionPanel()
        self.settings = SettingsPanel()
        self.settings.changed.connect(self._setting_changed)

        # LIKE OTHER MACRO GUIS (the owner, 2026-10-09: user friendly, laid out
        # the way macro GUIs usually are): the jobs first, one tab each,
        # as plain switches -- Natro's Gather / Collect / Kill / Quests -- and
        # the bot's thinking, ledgers and logs under one Advanced tab.
        self.macro_tabs = []
        for label, sections, sub in (
                ("Gather", ("Gathering",), "which field, when to go home, tokens"),
                ("Collect", ("Economy", "Spending"), "dispensers, boosters, the Wealth Clock, buying"),
                ("Kill", ("Combat",), "mobs, bug runs, the Ant Challenge"),
                ("Quests", ("Quests",), "which quest givers it works for")):
            panel = SettingsPanel(only=sections, title=label, subtitle=sub, compact=True)
            panel.changed.connect(self._setting_changed)
            self.macro_tabs.append(panel)
            self.tabs.addTab(self._page(panel), label)
        # THE GOAL WEB: "what is it working towards" is the next question.
        self.tabs.addTab(self._goals_tab(), "Goals")
        # THE HIVE PLANNER (ROADMAP H13, their idea): the bee wanted in each
        # slot; the jelly errand follows it (brain/hiveplanner)
        self.hive_planner = HivePlannerPanel(
            hive=self.gear._hive.currentText,
            set_follow=lambda v: self.settings.set_value("hive.follow_plan", v),
            set_grind=lambda slot: self.settings.set_value("hive.grind_slot", slot))
        self.tabs.addTab(self._page(self.hive_planner), "Hive Planner")
        rest = SettingsPanel(only=("Autonomy", "Goals", "Progression", "Movement", "Safety",
                                   "Performance", "Stream"),
                             title="Settings", subtitle="movement, safety, autonomy, stream",
                             compact=True)
        rest.changed.connect(self._setting_changed)
        self.macro_tabs.append(rest)
        self.tabs.addTab(self._page(rest), "Settings")
        # TELEGRAM (the owner, 2026-10-14): their own bot -- set it up, choose
        # the alerts and the stats cards (panels/telegram).
        self.telegram = TelegramTab()
        for panel in self.telegram.panels:
            panel.changed.connect(self._setting_changed)
        self.tabs.addTab(self.telegram, "Telegram")

        advanced = QTabWidget()
        advanced.addTab(self._wrap("reasoning", self.think), "Think")
        advanced.addTab(self._economy_tab(), "Economy")
        advanced.addTab(self._page(self.ledger), "Ledger")
        advanced.addTab(self._page(self.fields), "Fields")
        advanced.addTab(self._page(self.quests), "Quest steps")
        advanced.addTab(self._wrap("account state", self.beliefs), "Account")
        advanced.addTab(self._page(self.vision), "Vision")
        advanced.addTab(self._page(self.settings), "All settings")
        # DISK (telemetry/storage): var's size and the retention switch.
        self.storage = StorageTab()
        self.storage.panel.changed.connect(self._setting_changed)
        advanced.addTab(self.storage, "Storage")
        advanced.addTab(self._wrap("log", self.logs), "Log")
        self.tabs.addTab(advanced, "Advanced")
        box.addWidget(self.tabs, 1)
        return column

    def _goals_tab(self) -> QWidget:
        """The gear goals over the goal web. Both are plans; the gear is the
        one with prices, so it goes first."""
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 8, 0, 0)
        box.setSpacing(10)
        box.addWidget(self.gear, 2)
        # SESSION GOALS (ROADMAP G9): a horizon, goals, and a feasibility check
        from .panels.session_goals import SessionGoalsPanel
        self.session_goals = SessionGoalsPanel()
        box.addWidget(self.session_goals, 1)
        box.addWidget(self._scrolled("goals", self.goals), 3)
        return page

    def _economy_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 8, 0, 0)
        box.setSpacing(10)
        box.addWidget(self.economy, 3)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.sentinel, 1)
        row.addWidget(self.timers, 1)
        box.addLayout(row, 4)
        return page

    def seed_quests(self, path=None) -> int:
        """Draw the last quest reading from disk. Returns the rows drawn.

        The panel's own rows come from `QuestStep` events, so this builds the
        same events from `var/quests.json` -- the file `scripts/run_farm`
        writes every time it reads the quest menu -- and hands them over. The
        card then says WHEN it was read, so a reading from last night is
        never mistaken for a live one.

        Never raises: a window that will not open because a data file moved
        is worse than a window with one empty panel.
        """
        try:
            import json
            import time as _time
            from ..brain import questneeds
            from ..telemetry.events import QuestStep as _Step
            where = Path(path) if path else (
                Path(__file__).resolve().parents[3] / "var" / "quests.json")
            body = json.loads(Path(where).read_text())
            drawn = 0
            for quest in body.get("quests") or ():
                name = str(quest.get("name") or "")
                for item in questneeds.steps_of(
                        name, list(quest.get("requirements") or ())):
                    self.quests.update_quest(_Step(
                        giver=str(quest.get("giver") or "") or name,
                        step=item.text,
                        done=float(item.done),
                        total=float(item.total),
                        complete=bool(item.complete)))
                    drawn += 1
            read_at = float(body.get("read_at") or body.get("at") or 0.0)
            if drawn and read_at > 0:
                age = max(0.0, _time.time() - read_at)
                when = (f"{age / 3600:.0f}h ago" if age >= 3600
                        else f"{age / 60:.0f}m ago" if age >= 60
                        else "just now")
                self.quests.set_subtitle(
                    f"last read off the game's menu {when}")
            return drawn
        except Exception:
            return 0

    def refresh_goals(self, honey: int | None = None, decision=None) -> None:
        """Rebuild the goal web from the SAME knowledge the bot reasons with.

        Deliberately not a separate copy of the plan: if this picture and the
        bot ever disagreed, the picture would be the lie. Reads the knowledge
        files directly and asks the real Ladder, so a mistake in the reasoning
        shows up here instead of being hidden by a tidier diagram.

        `decision` defaults to the last one the bot announced (`_decision`).
        """
        if decision is None:
            decision = self._decision
        try:
            from ..brain import knowledge
            from ..brain.goalmap import build
            from ..brain.progress import Ladder
            from ..brain.progress import load as load_progression
            from ..datapaths import data as data_path
        except Exception:
            return
        try:
            standing = knowledge.standing()
            if honey is not None:
                standing.honey = int(honey)
            elif self._honey is not None:
                standing.honey = self._honey
            ladder = Ladder(load_progression(data_path("knowledge",
                                                       "progression.yaml")),
                            (knowledge.world() or {}).get("fields") or {})
            # THE QUESTS THE BOT LAST READ OFF THE SCREEN, as goals. The owner
            # asked for exactly this: "it should read what quests i have ... so
            # it knows what goals to set next". None means the menu has not
            # been read, and the web simply draws without them rather than
            # failing -- a goal web that disappears when a read fails is a goal
            # web that disappears precisely when something is wrong.
            self.goals.show_map(build(ladder, standing,
                                      knowledge.blue_hive_plan(), decision,
                                      quests=_quests_read()))
        except Exception as exc:                      # never break the GUI
            self.logs.add_thought(Thought(topic="goals",
                                          text=f"could not draw the goals: {exc}"), "warn")
        # THE GEAR GOALS, from `brain.goals` -- the module the bot plans with
        # and the morning report prints -- so the three cannot disagree. The
        # honey is the bot's last HUD reading when it is connected; with no
        # bot, `from_files` falls back to the last confirmed convert in the
        # ledger and says so.
        try:
            from ..brain import goals as goals_plan
            live = honey if honey is not None else self._honey
            plan = goals_plan.from_files(
                honey=live,
                honey_from="the bot's HUD reading" if live is not None else "",
                honey_at=(self._honey_at or time.time()) if live is not None
                else None)
            self.gear.show_plan(plan)
            self.simple.set_plan(plan)          # what it saves for, in Simple
        except Exception as exc:                      # never break the GUI
            self.logs.add_thought(Thought(
                topic="goals", text=f"could not draw the gear goals: {exc}"), "warn")

    def _progression_hive(self, hive: str) -> None:
        self.settings.set_value("progression.hive", hive)   # saved, the bot told
        self.refresh_goals()

    def _page(self, card: QWidget) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 8, 0, 0)
        box.addWidget(card)
        return page

    def _scrolled(self, title: str, widget: QWidget) -> QWidget:
        """A card that scrolls, for panels taller than the window."""
        area = QScrollArea()
        area.setWidget(widget)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        return self._wrap(title, area)

    def _wrap(self, title: str, widget: QWidget) -> QWidget:
        card = Card(title)
        card.add(widget, 1)
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 8, 0, 0)
        box.addWidget(card)
        return page

    def _task_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Panel")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 8)
        self.task_label = ElidedLabel("idle")
        self.task_label.setStyleSheet(f"color: {theme.TEXT_DIM};")
        self.task_bar = QProgressBar()
        self.task_bar.setTextVisible(False)
        self.task_bar.setFixedWidth(220)
        row.addWidget(self.task_label, 1)
        row.addWidget(self.task_bar)
        return bar

    # ---- the two pages ----------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """The switch: saved as `gui.mode` (the All settings panel holds it),
        which comes back through `_setting_changed` and shows the page."""
        self.settings.set_value("gui.mode", mode)

    def show_mode(self, mode: str, animate: bool = True) -> None:
        """Show Simple or Advanced (anything else is Simple, the default).
        Nothing is rebuilt: both pages hold their state while hidden."""
        mode = "advanced" if str(mode) == "advanced" else "simple"
        page = self.advanced if mode == "advanced" else self.simple
        for switch in (self.status.mode_switch, self.simple.mode_switch):
            switch.set_mode(mode)
        had_focus = self.status.mode_switch.hasFocus() or self.simple.mode_switch.hasFocus()
        if animate:
            crossfade(self.pages, page)
        else:
            self.pages.setCurrentWidget(page)
        if had_focus:
            # the switch that was clicked is hidden now: its twin takes the
            # focus, rather than whatever button comes next in the chain
            (self.status if mode == "advanced" else self.simple).mode_switch.setFocus()

    @property
    def mode(self) -> str:
        return "simple" if self.pages.currentWidget() is self.simple else "advanced"

    def _sync_simple(self) -> None:
        """Simple's buttons and chip, from the Advanced bar: ONE place
        decides what is live (StatusBar._apply_buttons)."""
        s = self.status
        self.simple.set_controls([(b.isEnabled(), b.text())
                                  for b in (s._start, s._pause, s._stop)])
        self.simple.set_run_state(s._connected, s._running, s._paused,
                                  s._handed_over or s._handing_over,
                                  self.bot.running(), s._state.text())

    def _sync_questions(self) -> None:
        self.simple.set_questions(self.inbox.pending)

    # ---- event routing ----------------------------------------------------
    def handle(self, event: Event) -> None:
        # SIMPLE HEARS EVERYTHING TOO, shown or not, so switching loses
        # nothing; it never raises (gui/simple).
        self.simple.handle(event)
        if isinstance(event, Thought) and event.topic == "plan":
            # THE BOT NARRATES ITS CHOICE BEFORE EVERY TRIP, and that IS the
            # "doing now" node of the goal web -- so the web shows what it
            # decided rather than a guess made here about what it might be up
            # to.
            #
            # THIS BRANCH WAS DEAD. It sat BELOW the catch-all
            # `elif isinstance(event, Thought)` a dozen branches up, so every
            # plan Thought was consumed there and `refresh_goals(decision=...)`
            # was never once called from a running bot. The Goals tab has shown
            # no current decision for the whole life of the project. It is
            # first now, beside the other Thought special case, and the
            # narration still reaches the thinking panel underneath.
            self._decision = _Chose(event.text)
            self.refresh_goals()
            self.think.add_thought(event)
        elif isinstance(event, Thought) and event.topic == "gap":
            # A panel that cannot be filled says why, in the panel. The bot
            # sends one of these per unfillable panel at startup; see
            # brain/dashboard.GAPS.
            name, _, reason = event.text.partition(":")
            target = {"planters": self.planters,
                      "expiry sentinel": self.sentinel}.get(name.strip())
            if target is not None and reason.strip():
                target.explain(reason.strip())
            self.logs.add_thought(event)
        elif isinstance(event, Thought) and event.topic == "planters unplaced":
            # why no planter went in a field (brain/dashboard.publish_planters)
            self.planters.set_unplaced(event.text)
        elif isinstance(event, Thought):
            self.think.add_thought(event)
        elif isinstance(event, Considered):
            self.think.add_decision(event)
        elif isinstance(event, Question):
            self.inbox.add(event)
        elif isinstance(event, Belief):
            if not self._goal_card(event):
                self.beliefs.update_belief(event)
        elif isinstance(event, Frame):
            self.live.show_frame(event)
            # the vision model answers about the CURRENT screen, so it gets
            # the same frame path the live view is showing
            self.vision.set_frame_path(event.path)
        elif isinstance(event, Planter):
            self.planters.update_planter(event)
        elif isinstance(event, Expiry):
            self.sentinel.update_expiry(event)
        elif isinstance(event, ShadowPrice):
            self.economy.update_price(event)
        elif isinstance(event, TimerEvent):
            self.timers.update_timer(event)
        elif isinstance(event, FieldStatus):
            self.fields.update_field(event)
        elif isinstance(event, QuestStep):
            self.quests.update_quest(event)
        elif isinstance(event, TaskUpdate):
            self._task(event)
        elif isinstance(event, Metric):
            self._metric(event)
            if event.name in ("honey", "honey_total"):
                self._honey = int(event.value)
                self._honey_at = time.time()
                self.refresh_goals()
        elif isinstance(event, StatusUpdate):
            self.status.set_status(event.running, event.paused, event.note,
                                   settled=(event.parked is not False))
            # Only a mode somebody actually reported; see StatusUpdate.autonomy.
            if event.autonomy is not None:
                self.status.set_autonomy(event.autonomy)
            # The bot gets the last word on who is driving; the button above
            # is only a request until this arrives -- and "handed over" means
            # the loop has parked, not that the command arrived (8du).
            self.status.set_handed_over(event.handed_over,
                                        pending=event.handing_over)
            self._sync_take_control()
        elif isinstance(event, Log):
            self.logs.add_thought(Thought(at=event.at, text=event.message,
                                          topic=event.source), event.level)
        if isinstance(event, (Question, Belief)):
            self._sync_questions()          # a card added, or taken down

    def _goal_card(self, event: Belief) -> bool:
        """A gear-goal card's state from the bot (DESIGN 8dp), not a fact for
        the belief table. WITHDRAWN takes the card down: the honey fell back
        below the price, or the goal is owned, and a "Ready to buy" left up
        would contradict the Goals tab (`brain/goals.Watch`). The owned and
        fall cards (brain/owned, DESIGN 8ea) work the same way: one is taken
        down once they have settled it some other way, in Settings."""
        from ..brain import goals as goals_plan
        from ..brain import owned as owned_mod
        from ..brain.progression import QUESTION_PREFIX as ASK
        if not str(event.name or "").startswith(
                (goals_plan.QUESTION_PREFIX, ASK) + owned_mod.CARD_PREFIXES):
            return False
        if event.value == goals_plan.WITHDRAWN:
            self.inbox.remove(event.name)
        return True

    def _task(self, event: TaskUpdate) -> None:
        self.task_label.setText(f"{event.name} — {event.detail}"
                                if event.detail else event.name)
        if event.progress < 0:
            self.task_bar.setRange(0, 0)          # indeterminate
        else:
            self.task_bar.setRange(0, 100)
            self.task_bar.setValue(int(event.progress * 100))

    def _metric(self, event: Metric) -> None:
        mapping = {
            "honey": self.status.honey,
            "pollen": self.status.pollen,
            "bees": self.status.bees,
            "honey_per_hour": self.status.rate,
        }
        vital = mapping.get(event.name)
        if vital:
            vital.set(event.value)

    # ---- outbound ---------------------------------------------------------
    def _answer(self, qid: str, choice: str) -> None:
        self.bridge.send(Answer(id=qid, choice=choice))
        # A GEAR GOAL THE OWNER BOUGHT (DESIGN 8dp). The bot only notes the
        # answer, so the card stops coming back (`goals.Watch.answer`), and it
        # may not even be running -- so the window writes the purchase itself,
        # into the `goals.owned` setting, which is saved, sent to the bot, and
        # read again by the bot's planner on its next heartbeat.
        try:
            from ..brain import goals as goals_plan
            if (qid.startswith(goals_plan.QUESTION_PREFIX)
                    and choice == goals_plan.BOUGHT):
                key = qid[len(goals_plan.QUESTION_PREFIX):]
                owned = goals_plan.with_owned(
                    self.settings.values.get("goals.owned") or "", key)
                self.settings.set_value("goals.owned", owned)
                self.refresh_goals()
        except Exception as exc:                      # never break the GUI
            self.logs.add_thought(Thought(
                topic="goals", text=f"could not mark the goal owned: {exc}"), "warn")
        # WHAT THEY HAVE IN A GEAR SLOT NO READER SEES (brain/progression's
        # "Which boots do you wear?"): their pick goes into `goals.owned`, their
        # word from then on; "None of these yet" changes nothing there.
        try:
            from ..brain import progression
            if (qid.startswith(progression.QUESTION_PREFIX)
                    and choice and choice != progression.NONE_YET):
                have = str(self.settings.values.get("goals.owned") or "")
                names = [n.strip() for n in have.split(",") if n.strip()]
                if choice.lower() not in {n.lower() for n in names}:
                    self.settings.set_value("goals.owned", ", ".join(names + [choice]))
                self.refresh_goals()
        except Exception as exc:                      # never break the GUI
            self.logs.add_thought(Thought(
                topic="goals", text=f"could not record the answer: {exc}"), "warn")
        # WHAT THEY SAY THEY BOUGHT, ON AN OWNED OR FALL CARD (DESIGN 8ea). The
        # answer is written into var/owned.json here as well as by the bot,
        # which may not be running; a "yes" goes into `goals.owned` too, so it
        # is their word from then on, the same as "I bought it" above.
        try:
            from ..brain import owned as owned_mod
            from ..datapaths import VAR_ROOT
            if qid.startswith(owned_mod.CARD_PREFIXES):
                key = owned_mod.record_answer(VAR_ROOT, qid, choice)
                if key:
                    self.settings.set_value("goals.owned", owned_mod.with_owned(
                        self.settings.values.get("goals.owned") or "", key))
                self.refresh_goals()
        except Exception as exc:                      # never break the GUI
            self.logs.add_thought(Thought(
                topic="goals", text=f"could not record the answer: {exc}"), "warn")

    def _setting_changed(self, key: str, value) -> None:
        """The panel has saved the file; tell the bot to re-read it.

        Not "nothing needs a restart" (DESIGN 8du): the bot re-reads the file
        on this message, but most settings are read once per attempt and
        apply from the next one. The panel labels those, and the bot's Log
        line says which of the changes took effect now.
        """
        # THE WINDOW'S OWN (gui.*): shown here, and nothing for the bot.
        if key.startswith("gui."):
            if key == "gui.mode":
                self.show_mode(str(value))
            elif key == "gui.start_on_boot":
                from . import autostart
                self.status.set_note(autostart.apply(bool(value)))
            return
        self.simple.setting_changed(key, value)     # its privacy gate
        # A SECRET IS NOT SENT (DESIGN 8ed): the bot re-reads the file and
        # never uses the value, so the YouTube key does not cross the socket.
        self.bridge.send(Belief(name=f"setting:{key}",
                                value="(hidden)" if key in SECRET else value,
                                confidence=1.0, source="gui"))
        if self._stream is not None:
            self._stream.setting_changed(key, value)

    def _set_autonomy(self, mode: Autonomy) -> None:
        self.bridge.send(StatusUpdate(autonomy=mode, note="set from GUI"))

    # ---- run control ------------------------------------------------------
    def _start(self) -> None:
        """Play. Starts the bot if there is not one, resumes it if there is.

        THE OWNER'S REPORT: the Play button did nothing. It sent START down a
        socket with nothing on the other
        end, and said so in a corner. A bot that is not running cannot be
        told to start; it has to be LAUNCHED. See gui/launcher.
        """
        # A DEMO IS NOT A BOT (2026-10-22: Start in a replay launched the real
        # bot, and the UI preview build is a replay only). Every number in a
        # replay is invented, so Play has nothing to start.
        if getattr(self, "_replay_name", ""):
            self.status.set_note("Demo only: Start does nothing here.")
            return
        if self._connected:
            self._command(Action.START)
            return
        if self.bot.running():
            # Alive but not connected yet -- the watchdog is between attempts
            # or the game is still loading. Whoever started it, say so rather
            # than start a second one (gui/launcher).
            self.status.set_note(self.bot.describe_state())
            return
        launch = self.bot.start()
        self.status.set_note(launch.describe())
        self.logs.add_thought(Thought(
            topic="run", text=launch.describe(),
            detail="" if launch.ok else
            "Start launches scripts/overnight.sh — the watchdog that runs "
            "scripts/run_farm.py and relaunches it after a rejoin or a crash, "
            "always from the code on disk. If that failed, var/gui-run.log "
            "says why."), "info" if launch.ok else "error")
        if launch.ok:
            # The buttons follow the PROCESS until the bot reports for itself,
            # and the note goes THROUGH set_status -- calling set_note first
            # and set_status after silently replaced "started the bot (pid
            # 1234)" with a bare "running", so the one message the owner needs
            # after pressing Play never appeared.
            self.status.set_status(running=True, paused=False,
                                   note=launch.describe())

    # ---- start on boot (ROADMAP U13) ----------------------------------------
    def _make_boot_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("BootBanner")
        banner.setStyleSheet(
            f"QFrame#BootBanner {{ background: {theme.ACCENT}; border-radius: 6px; }}"
            " QFrame#BootBanner QLabel { color: #16161d; font-weight: 800; }")
        row = QHBoxLayout(banner)
        row.setContentsMargins(14, 6, 8, 6)
        self._boot_label = QLabel()
        row.addWidget(self._boot_label, 1)
        self.boot_cancel = QPushButton("Cancel")
        self.boot_cancel.setCursor(Qt.PointingHandCursor)
        self.boot_cancel.clicked.connect(lambda: self.cancel_autostart("cancelled"))
        row.addWidget(self.boot_cancel)
        self._boot_timer = QTimer(self)
        self._boot_timer.setInterval(1000)
        self._boot_timer.timeout.connect(self._boot_tick)
        self._boot_left = 0
        banner.hide()
        return banner

    def _boot_tell(self, text: str) -> None:
        """A Telegram line, off the GUI thread (the API call can take seconds);
        nothing when Telegram is not set up (telegram_alerts.send says so)."""
        import threading
        from .panels.telegram import tg
        threading.Thread(target=tg.send, args=(text,), daemon=True).start()

    def begin_autostart(self) -> bool:
        """Opened at login (--autostart): count down GRACE_S with Cancel and a
        Telegram note, then Start through the gates. False when it does not
        count down at all (the setting is off, or the bot already runs)."""
        from . import autostart
        from ..world.settings import Settings
        if not autostart.wanted(Settings()):
            self.status.set_note("opened at login; 'Start farming when the PC starts' "
                                 "is off, so nothing was started")
            return False
        if self._connected or self.bot.running():
            return False
        try:
            path = autostart.pending_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{time.time():.0f}\n")
        except OSError:
            pass                       # Cancel still works; /stop cannot reach it
        self._boot_left = autostart.GRACE_S
        self._boot_show()
        self._boot_banner.show()
        self._boot_timer.start()
        self._boot_tell(f"Hivemind opened at login: starting to farm in "
                        f"{autostart.GRACE_S} s. /stop to cancel.")
        return True

    def _boot_show(self) -> None:
        self._boot_label.setText(
            f"Starting to farm in {self._boot_left} s (Start farming when the PC "
            "starts). It checks for a running game and free memory first.")

    def _boot_tick(self) -> None:
        from . import autostart
        if not autostart.pending_path().exists():
            self.cancel_autostart("cancelled from Telegram")
            return
        if self._connected or self.bot.running():      # Start pressed meanwhile
            self.cancel_autostart("not needed: the bot is already running")
            return
        self._boot_left -= 1
        if self._boot_left > 0:
            self._boot_show()
            return
        self._boot_timer.stop()
        self._boot_banner.hide()
        autostart.pending_path().unlink(missing_ok=True)
        from ..world.settings import Settings
        why = autostart.blocker(Settings())
        if why:
            self.status.set_note(f"start on boot: not started, {why}")
            self._boot_tell(f"Did not start farming: {why}. Press Start in Hivemind "
                            "when you are ready.")
            return
        self._start()

    def cancel_autostart(self, why: str = "cancelled") -> None:
        from . import autostart
        self._boot_timer.stop()
        self._boot_banner.hide()
        try:
            autostart.pending_path().unlink(missing_ok=True)
        except OSError:
            pass
        self.status.set_note(f"start on boot {why}: press Start when you want it")

    def _pause_or_resume(self) -> None:
        self._command(Action.RESUME if self.status.paused else Action.PAUSE)

    def _stop(self) -> None:
        """Stop. Asks the bot first, then makes sure it actually went.

        The request matters more than the kill: `brain/controls` handles STOP
        by releasing every held key, and a bot killed with W down leaves the
        character walking into a wall. So the command goes first, then the
        process is given time to honour it.
        """
        sent = self.bridge.send(Command(action=Action.STOP))
        if sent:
            self.status.set_note("stop sent — releasing the keys")
        if not self.bot.running():
            if not sent:
                self.status.set_note(
                    "nothing to stop: no bot and no watchdog are running "
                    "(var/night/watchdog.pid names nothing alive)")
            return
        # Give the clean path a moment, then supervise the process itself.
        QTimer.singleShot(2000, self._finish_stop)

    def _finish_stop(self) -> None:
        if not self.bot.running():
            self.status.set_note("the bot stopped")
            self.status.set_status(running=False, paused=False)
            return
        if self._stopping:
            return
        # OFF THE GUI THREAD (DESIGN 8du). `BotProcess.stop` waits for the
        # process to exit -- MEASURED "farm gone after 11s" in
        # restart-watchdog.log, and up to GRACE_SECONDS (25) when the request
        # is ignored -- and the window was frozen for all of it.
        import threading
        self._stopping = True
        self.status.set_note("stopping — waiting for the bot to release its "
                             "keys and exit")
        threading.Thread(target=lambda: self._stop_finished.emit(self.bot.stop()),
                         name="hivemind-stop", daemon=True).start()

    def _stop_done(self, outcome: str) -> None:
        """The stop worker's result, back on the GUI thread."""
        self._stopping = False
        self.logs.add_thought(Thought(topic="run", text=outcome))
        self.status.set_status(running=False, paused=False, note=outcome)

    def _handover(self, take_over: bool) -> None:
        """Hand the controls to the owner, or take them back.

        THEIR REQUEST: a Take Over button; from then on the bot watches them play
        and learns, until they press Pass Back.

        The button only moves if the command actually reached the bot. A
        control that says "Pass back" while the bot is still walking around
        would be the worst lie this interface could tell, because the owner
        would be fighting it for the keyboard without knowing.
        """
        action = Action.TAKE_OVER if take_over else Action.PASS_BACK
        if not take_over:
            self.live.set_take_control(False)     # their keys up before the bot's
        if self.bridge.send(Command(action=action)):
            # ASKED FOR, NOT GIVEN (DESIGN 8du). The keys come up when the
            # command lands, but the bot only stops at its next step, and
            # says so itself (StatusUpdate.handed_over) -- so the button waits
            # for that. Nothing watches or learns meanwhile.
            self.status.set_handed_over(False, pending=take_over)
            self.status.set_note(
                "asked for the controls — the keys are up; the bot finishes "
                "its current step, then they are yours"
                if take_over else "handed back to the bot")
        else:
            self.status.set_note(
                f"could not send {action.value} — not connected to the bot")

    def _sync_take_control(self) -> None:
        """TAKE CONTROL THROUGH THE LIVE VIEW (RL1b step 3): live while the
        bot says the owner has the controls -- its loop parked -- and this
        window is connected to it; their mouse and keys over the picture then
        go to the game through the bot's own input (GameInput)."""
        self.live.set_take_control(self._connected and self.status._handed_over,
                                   self.bridge.send)

    def _panic(self, layer: str) -> None:
        """A panic layer fired (gui/panic): everything the live view holds
        comes up, then Stop -- the command first, every key up, then the
        process."""
        self.live.set_take_control(False)
        self.logs.add_thought(Thought(topic="run", text=f"panic key ({layer}): stopping"))
        self._stop()
        self.status.set_note(f"panic key ({layer}): stop sent, every key released")

    def _command(self, action: Action) -> None:
        """Send a run-control command, and SAY SO if it could not be sent.

        A button that silently does nothing is worse than a disabled one: the
        user believes the bot has stopped when it is still playing.
        """
        if getattr(self, "_replay_name", ""):     # a demo: plain words, no bot (2026-10-22)
            self.status.set_note("Demo only: these buttons do nothing here.")
            return
        if self.bridge.send(Command(action=action)):
            self.status.set_note(f"{action.value} sent")
        else:
            self.status.set_note(
                f"could not send {action.value} — not connected to the bot")

    # ---- stream mode (DESIGN 8dv) ------------------------------------------
    def _stream_keep(self, event) -> None:
        if not isinstance(event, Frame):
            self._stream_recent.append(event)
            del self._stream_recent[:-STREAM_RECENT]

    def open_stream(self) -> None:
        """Open the stream layout, or bring it forward if it is open."""
        if self._stream is None:
            # SCALED TO ITS WINDOW (gui/stream_frame): full screen on a 1440p
            # screen did not fit at a fixed 1920x1080.
            self._stream = StreamFrame(StreamWindow(
                self.bridge, settings=self.settings.values,
                recent=list(self._stream_recent), honey=self._honey,
                replay=self._replay_name, connected=self._connected,
                live_source=self.live, bot_alive=self.bot.running))
            self._stream.closed.connect(self._stream_closed)
            self.telegram.set_streaming(True)
            self._stream.show_fitting()     # full screen when it cannot fit
        else:
            self._stream.show()
        self._stream.raise_()
        self._stream.activateWindow()

    def _stream_closed(self) -> None:
        self._stream = None
        self.telegram.set_streaming(False)

    def closeEvent(self, event) -> None:
        self.live.set_take_control(False)
        self.panic.stop()
        if self._stream is not None:
            self._stream.close()
        self.bridge.stop()
        super().closeEvent(event)


def _quests_read():
    """The last quest reading from disk, or None if there is not one.

    Read from the same file the farm loop writes, rather than accumulated from
    events, so the web is correct the moment the GUI opens instead of only
    after the next quest read comes through.
    """
    try:
        from ..brain import questneeds
        from ..datapaths import var as var_path
        return questneeds.load(var_path("quests.json"))
    except Exception:
        return None

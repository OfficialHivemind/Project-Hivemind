"""The first-run window: Install Sober, Log in to Roblox, Start (RL1b step 3).

Shown when the game runs in the headless labwc (`platform.compositor`), or
on a fresh install (the Linux launcher's --first-run-check), until step 3
has passed once (the same `first-run-passed` marker as gui/app's check).

    1  Install Sober     flatpak install --user -y flathub org.vinegarhq.Sober,
                         in the background with its output shown; the user's
                         own flathub remote is added first when it is missing
    2  Log in to Roblox  Sober in the bot's own compositor (act/login), the
                         picture here, and the owner's mouse and keys going
                         into it through the bot's input (take control)
    3  Start             `hivemind doctor`'s checks, then Play

NO ROOT, EVER: everything is --user, no command here is sudo or pkexec, and
nothing asks for a password (`test_firstrun` checks every argv).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from . import theme
from .panels.liveview import LiveView
from ..telemetry.events import Action, Command, Log, StatusUpdate

SOBER = "org.vinegarhq.Sober"
FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"
REMOTES = ["flatpak", "remotes", "--user", "--columns=name"]
REMOTE_ADD = ["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB]
INSTALL = ["flatpak", "install", "--user", "-y", "flathub", SOBER]
LISTED = ["flatpak", "list", "--app", "--columns=application"]
LOGIN = [sys.executable, "-m", "hivemind.act.login"]
SRC = Path(__file__).resolve().parents[2]          # the `hivemind` package's parent
# How long Done waits for the login to end Sober and its compositor itself
# before it is sent SIGTERM (which still closes them: act/login's finally).
DONE_GRACE_MS = 15000


def wanted(compositor: str, fresh_install: bool, marker: Path) -> bool:
    """Show this window? labwc or a fresh install, until step 3 passed once."""
    return (compositor == "labwc" or fresh_install) and not marker.exists()


class Runner(QObject):
    """One command in the background (QProcess), its output line by line.
    The seam the tests replace: they never start a real process."""

    output = Signal(str)
    done = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._p = QProcess(self)
        self._p.setProcessChannelMode(QProcess.MergedChannels)
        self._p.readyReadStandardOutput.connect(self._read)
        self._p.finished.connect(lambda code, _status: self.done.emit(int(code)))
        self._p.errorOccurred.connect(self._error)

    def start(self, argv: list[str], env: dict | None = None) -> None:
        if env:
            penv = QProcessEnvironment.systemEnvironment()
            for k, v in env.items():
                penv.insert(k, v)
            self._p.setProcessEnvironment(penv)
        self._p.start(argv[0], argv[1:])

    def _read(self) -> None:
        text = bytes(self._p.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.replace("\r", "\n").splitlines():
            if line.strip():
                self.output.emit(line)

    def _error(self, error) -> None:
        if error == QProcess.FailedToStart:
            self.output.emit(f"could not start {self._p.program()}")
            self.done.emit(127)

    def running(self) -> bool:
        return self._p.state() != QProcess.NotRunning

    def stop(self) -> None:
        self._p.terminate()


def _run_text(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        return done.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


class Step(QFrame):
    """One numbered step: badge, title, words, status line, button."""

    def __init__(self, number: int, title: str, words: str, button: str):
        super().__init__()
        self.setObjectName("Panel")
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(14)
        self.badge = QLabel(str(number))
        self.badge.setFixedSize(30, 30)
        self.badge.setAlignment(Qt.AlignCenter)
        row.addWidget(self.badge, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.words = QLabel(words)
        self.words.setWordWrap(True)
        self.words.setStyleSheet(f"color: {theme.S_DIM};")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {theme.S_FAINT}; font-size: 12px;")
        for w in (self.title, self.words, self.status):
            text.addWidget(w)
        row.addLayout(text, 1)
        self.button = QPushButton(button)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setMinimumWidth(150)
        self.button.setMinimumHeight(36)
        row.addWidget(self.button, 0, Qt.AlignVCenter)
        self.set_state("todo")

    def set_state(self, state: str, status: str | None = None) -> None:
        """todo, now (the next thing to do), busy, done or bad."""
        colour, fill, mark = {
            "todo": (theme.S_DIM, theme.S_CARD, None),
            "now": (theme.S_ON_AMBER, theme.S_AMBER, None),
            "busy": (theme.S_AMBER, theme.S_CARD, None),
            "done": (theme.S_ON_AMBER, theme.S_GOOD, "✓"),
            "bad": ("#ffffff", theme.S_BAD, "!"),
        }[state]
        if mark:
            self.badge.setText(mark)
        self.badge.setStyleSheet(f"background: {fill}; color: {colour}; border-radius: 15px;"
                                 " font-weight: 800; font-size: 14px;")
        self.button.setObjectName("Primary" if state == "now" else "")
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)
        if status is not None:
            self.status.setText(status)
        self.status.setVisible(bool(self.status.text()))


class FirstRunWindow(QWidget):
    """The three steps. `window` is the main window: its bridge carries the
    login's picture and the owner's input, its live view is mirrored here,
    and its Start is step 3's Play."""

    def __init__(self, window, marker: Path | None = None, run_text=None,
                 runner=None, doctor_run=None):
        super().__init__()
        from ..datapaths import config_dir
        self.window = window
        self.marker = marker or config_dir() / "first-run-passed"
        self.run_text = run_text or _run_text
        # A TEST NEVER STARTS A REAL PROCESS: under pytest a runner must be given
        self._runner = runner or (None if os.environ.get("PYTEST_CURRENT_TEST") else Runner)
        self.doctor_run = doctor_run
        self.commands: list[list[str]] = []        # every argv started, for the record
        self._queue: list[list[str]] = []
        self.job = None
        self.login = None
        self._login_ready = False

        self.setWindowTitle("Set up Hivemind")
        self.setObjectName("FirstRun")
        self.setStyleSheet(theme.SHELL + f"QWidget#FirstRun {{ background: {theme.S_BG}; }}")
        self.resize(780, 470)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(12)
        head = QLabel("Set up Hivemind")
        head.setStyleSheet("font-size: 22px; font-weight: 800;")
        sub = QLabel("Three steps, about five minutes. Nothing here needs your password, "
                     "and Hivemind never spends Robux.")
        sub.setStyleSheet(f"color: {theme.S_DIM};")
        outer.addWidget(head)
        outer.addWidget(sub)
        outer.addSpacing(4)

        self.install = Step(1, "Install Sober",
                            "Sober is the Roblox app for Linux. It installs from Flathub, "
                            "just for your user.", "Install Sober")
        self.install.button.clicked.connect(self.install_sober)
        self.signin = Step(2, "Log in to Roblox",
                           "Press Open Roblox. Log in as usual. When you see the Roblox "
                           "home, press Done, I'm logged in.", "Open Roblox")
        self.signin.button.clicked.connect(self.login_clicked)
        self.start = Step(3, "Start",
                          "Hivemind checks that everything is in place, then starts "
                          "playing.", "Check and start")
        self.start.button.clicked.connect(self.check_and_start)
        for step in (self.install, self.signin, self.start):
            outer.addWidget(step)

        # THE GAME, for step 2: the main window's picture, and this one takes
        # the controls while the login has them (gui/panels/liveview)
        self.view = LiveView()
        self.view.setMinimumSize(640, 360)
        self.view._hint.setText("Roblox appears here")
        self.view.mirror(window.live)
        self.view.setVisible(False)
        outer.addWidget(self.view, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(400)
        self.log.setFont(QFont(theme.MONO.split(",")[0], 9))
        self.log.setFixedHeight(130)
        self.log.setStyleSheet(f"background: {theme.S_PANEL}; color: {theme.S_DIM};"
                               f" border: 1px solid {theme.S_LINE}; border-radius: 8px;")
        self.log.setVisible(False)
        outer.addWidget(self.log)
        outer.addStretch(0)

        window.bridge.event_received.connect(self._event)
        self.refresh()

    # ---- state ---------------------------------------------------------------
    def sober_installed(self) -> bool:
        return SOBER in self.run_text(LISTED).split()

    def refresh(self) -> None:
        """Each step's badge and button from what is true now."""
        has = self.sober_installed()
        busy = self.job is not None
        if has:
            self.install.set_state("done", "Sober is installed.")
            self.install.button.setText("Installed")
        elif not busy:
            self.install.set_state("now", "Not installed yet.")
        self.install.button.setEnabled(not has and not busy)
        self.signin.button.setEnabled(has and not busy)
        if self.login is None:
            self.signin.set_state("now" if has else "todo")
        self.start.set_state("now" if has and self.login is None else "todo")
        self.start.button.setEnabled(has and not busy)

    def say(self, line: str) -> None:
        if self.log.isHidden():
            self.log.setVisible(True)
            self.resize(self.width(), self.height() + self.log.height() + 12)
        self.log.appendPlainText(line)

    def _spawn(self, argv: list[str], env: dict | None = None):
        if self._runner is None:
            self.say("(not started: a test run never starts real programs)")
            return None
        assert argv[0] not in ("sudo", "pkexec", "su", "doas"), argv  # never root
        self.commands.append(list(argv))
        runner = self._runner(self)
        runner.output.connect(self.say)
        runner.start(argv, env)
        return runner

    # ---- step 1 ------------------------------------------------------------------
    def install_sober(self) -> None:
        if self.job is not None or self.sober_installed():
            return
        remotes = self.run_text(REMOTES).split()
        self._queue = ([] if "flathub" in remotes else [REMOTE_ADD]) + [INSTALL]
        self.install.set_state("busy", "Installing… this downloads about 1 GB the "
                                       "first time.")
        self._next()

    def _next(self, code: int = 0) -> None:
        if code != 0:
            self.job = None
            self._queue = []
            self.install.set_state("bad", f"That did not work (exit {code}). The "
                                          "lines below say why; press Install Sober "
                                          "to try again.")
            self.install.button.setEnabled(True)
            self.signin.button.setEnabled(False)
            return
        if not self._queue:
            self.job = None
            self.refresh()
            if self.sober_installed():
                self.say("Sober is installed.")
            return
        argv = self._queue.pop(0)
        self.say("$ " + " ".join(argv))
        self.job = self._spawn(argv)
        if self.job is None:
            self._queue = []
            return
        self.job.done.connect(self._next)
        self.refresh()

    # ---- step 2 ------------------------------------------------------------------
    def login_clicked(self) -> None:
        if self.login is None:
            self.open_roblox()
        else:
            self.login_done()

    def open_roblox(self) -> None:
        env = {"PYTHONPATH": os.pathsep.join(
            p for p in (str(SRC), os.environ.get("PYTHONPATH", "")) if p)}
        self.say("Opening Roblox in Hivemind's own game session…")
        self.login = self._spawn(LOGIN, env)
        if self.login is None:
            return
        self.login.done.connect(self._login_ended)
        self.view.setVisible(True)
        self.resize(self.width(), max(self.height(), 960))
        self.signin.set_state("busy", "Opening Roblox… the picture appears below in "
                                      "about ten seconds.")
        self.signin.button.setText("Done, I'm logged in")
        self.start.set_state("todo")
        self.start.button.setEnabled(False)          # the game runs once: Done first

    def login_done(self) -> None:
        """Ask the login to end Sober itself; SIGTERM if it has not soon."""
        self.view.set_take_control(False)
        self.window.bridge.send(Command(action=Action.STOP, reason="the login is done"))
        self.signin.status.setText("Closing Roblox…")
        self.signin.button.setEnabled(False)
        login = self.login
        QTimer.singleShot(DONE_GRACE_MS, lambda: login.running() and login.stop())

    def _login_ended(self, code: int) -> None:
        self.view.set_take_control(False)
        self.view.setVisible(False)
        self.login = None
        self._login_ready = False
        self.signin.button.setText("Open Roblox again")
        self.refresh()
        self.signin.set_state("done", "Roblox closed. Your login stays saved in Sober.")
        self.start.set_state("now")

    def _event(self, event) -> None:
        if self.login is None:
            return
        if isinstance(event, StatusUpdate):
            on = bool(event.handed_over)
            self.view.set_take_control(on, self.window.bridge.send)
            if on and not self._login_ready:
                self._login_ready = True
                self.signin.set_state("busy", "Roblox is open: click the picture and "
                                              "log in. F12 or Done stops it.")
                self.signin.button.setEnabled(True)
        elif isinstance(event, Log) and event.source == "login":
            self.say(event.message)

    # ---- step 3 ------------------------------------------------------------------
    def check_and_start(self) -> bool:
        if self.login is not None:
            self.start.set_state("bad", "Press Done in step 2 first: the game can "
                                        "only run once.")
            return False
        from ..cli import doctor
        checks = (self.doctor_run or doctor.run)()
        failed = [c for c in checks if c.status == doctor.FAIL]
        if failed:
            self.start.set_state("bad", f"{len(failed)} thing(s) to fix first:")
            for c in failed:
                self.say(f"✗ {c.name}: {c.fix or c.detail}")
            return False
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text("every check passed\n")
        self.start.set_state("done", "Everything is in place. Starting…")
        self.window._start()
        self.close()
        return True

    def closeEvent(self, event) -> None:
        self.view.set_take_control(False)
        if self.login is not None and self.login.running():
            self.window.bridge.send(Command(action=Action.STOP, reason="set-up closed"))
        super().closeEvent(event)

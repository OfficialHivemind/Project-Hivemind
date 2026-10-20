"""U15f, AUTO UPDATE, second half: the Updates card on Settings > General.

The first half (hivemind/update) finds a newer release and downloads its
installer checked against the sha256 in the release notes. This card:

- contacts GitHub only while `gui.check_updates` is on (default OFF, AGENTS
  rule 5), and asks once, on the card, while that setting was never chosen
  (no pop-up: a modal question would also block every offscreen test);
- checks and downloads on a worker thread, never the GUI's;
- offers Download and install only on Windows, from an installed copy, and
  only while the bot is stopped (never mid-trip). Then it starts the
  installer and closes the app; the installer keeps settings.yaml and var/
  (installer/hivemind.iss: onlyifdoesntexist, [InstallDelete] leaves var\\).
  Elsewhere it says a newer version is out, with the releases page's link.

Everything that reaches the network, a process or the app is passed in, so
the tests run it with fakes.
"""
from __future__ import annotations

import html
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import selftest, update

KEY = "gui.check_updates"


def wanted(values) -> bool:
    """Is the app allowed to contact GitHub? Off unless the person said yes."""
    return bool(values.get("gui.check_updates"))


def installed_copy(root: Path = selftest.ROOT) -> bool:
    """Run from what the installer put down -- Setup's uninstaller sits in the
    app folder -- rather than from a git checkout, which updates by git pull.
    ponytail: Inno names it unins000.exe (unins001... beside another one)."""
    return any(Path(root).glob("unins*.exe"))


def why_not_install(platform: str = sys.platform, root: Path = selftest.ROOT) -> str:
    """'' when this copy can run the installer, else why not, in plain words."""
    if platform != "win32":
        return "The installer is for Windows: get the new version from the releases page."
    if not installed_copy(root):
        return ("This copy runs from source, not from the installer: update it with "
                "git pull, or get the installer from the releases page.")
    return ""


def start_installer(path, popen=subprocess.Popen):
    """The installer as its own process, so it outlives this app (it replaces
    the app's files; Setup's CloseApplications=yes closes anything left)."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return popen([str(path)], close_fds=True, creationflags=flags)


def _in_thread(work) -> None:
    threading.Thread(target=work, daemon=True, name="hivemind-update").start()


def _dotted(version) -> str:
    return ".".join(map(str, version))


class UpdateCard(QFrame):
    """Check for updates, the result in a line, and Download and install."""

    # the worker's results, delivered on the GUI thread (a queued connection)
    checked = Signal(object, str)        # (update.Release or None, the line)
    fetched = Signal(object, str)        # (the installer's path or None, the line)

    def __init__(self, values, save, bot_stopped, quit_app, *, chosen=lambda: True,
                 check=update.check, download=update.download, start=start_installer,
                 run=_in_thread, why_not=why_not_install, tell=None, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingCard")
        self._values, self._save = values, save          # values: () -> the settings dict
        self._bot_stopped, self._quit = bot_stopped, quit_app
        self._check_fn, self._download_fn, self._start = check, download, start
        self._run, self._why_not, self._tell = run, why_not, tell
        self.release: update.Release | None = None
        self.installer: Path | None = None
        self.busy = False
        self._said = ""

        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 14, 12)
        box.setSpacing(8)
        title = QLabel("Updates")
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        box.addWidget(title)
        mine = QLabel(f"This is Hivemind {selftest.version()}.")
        mine.setObjectName("Dim")
        box.addWidget(mine)

        # THE FIRST-RUN QUESTION (U15f: "first run asks"), shown until chosen
        self.question = QFrame()
        ask = QVBoxLayout(self.question)
        ask.setContentsMargins(0, 0, 0, 0)
        # the promise fits this copy: only Windows' installer has the button
        # (usability triage 2026-10-27 #9: Linux was promised one it never shows)
        words = QLabel("Look for new versions of Hivemind? It asks GitHub's public "
                       "Releases page when the app opens. Nothing about you or your "
                       "game is sent. " + (
                           "It only tells you when a new version is out." if why_not()
                           else "Nothing is installed unless you press Download "
                                "and install."))
        words.setWordWrap(True)
        ask.addWidget(words)
        answers = QHBoxLayout()
        self.yes_button = QPushButton("Yes, look for updates")
        self.no_button = QPushButton("No thanks")
        self.yes_button.clicked.connect(lambda: self.answer(True))
        self.no_button.clicked.connect(lambda: self.answer(False))
        answers.addWidget(self.yes_button)
        answers.addWidget(self.no_button)
        answers.addStretch(1)
        ask.addLayout(answers)
        self.question.setVisible(not chosen())
        box.addWidget(self.question)

        self.line = QLabel()
        self.line.setWordWrap(True)
        self.line.setTextFormat(Qt.RichText)
        self.line.setOpenExternalLinks(True)
        box.addWidget(self.line)
        row = QHBoxLayout()
        self.check_button = QPushButton("Check for updates")
        self.install_button = QPushButton("Download and install")
        self.check_button.clicked.connect(self.check)
        self.install_button.clicked.connect(self.install)
        row.addWidget(self.check_button)
        row.addWidget(self.install_button)
        row.addStretch(1)
        box.addLayout(row)

        self.checked.connect(self._show_check)
        self.fetched.connect(self._show_download)
        self.sync()

    # ---- what shows -------------------------------------------------------
    def _say(self, text: str) -> None:
        self._said = text
        self.line.setText(text)

    def sync(self) -> None:
        """Buttons and line from the setting, the bot's state and the result.
        The window calls it whenever the run controls change."""
        on = wanted(self._values())
        stopped = bool(self._bot_stopped())
        # THE QUESTION OR ITS ANSWER, never both (usability triage #9: "Off:
        # turn it on" showed under the Yes / No question)
        asking = not self.question.isHidden()
        self.line.setVisible(not asking)
        self.check_button.setVisible(not asking)
        self.check_button.setEnabled(on and not self.busy)
        offer = self.release is not None and not self._why_not()
        self.install_button.setVisible(offer)
        self.install_button.setEnabled(offer and on and stopped and not self.busy)
        self.install_button.setText("Install" if self.installer else "Download and install")
        self.install_button.setToolTip(
            "" if stopped else "Stop the bot first: Hivemind never updates mid-trip.")
        if not on and not self.busy:
            self.line.setText("Off: Hivemind does not contact GitHub. Turn on "
                              "'Look for updates on GitHub' to check.")
        elif self._said:
            self.line.setText(self._said)
        else:
            self.line.setText("Not checked yet.")

    def show_setting(self, _on) -> None:
        """The setting changed (here or anywhere else): it has been chosen."""
        self.question.setVisible(False)
        self.sync()

    def answer(self, yes: bool) -> None:
        """The first-run question's answer, saved like any setting."""
        self.question.setVisible(False)
        self._save(KEY, bool(yes))
        self.sync()
        if yes:
            self.check()

    # ---- checking ---------------------------------------------------------
    def check_soon(self, ms: int = 8000) -> None:
        """The check when the app opens, when allowed; a moment later, so the
        window is up first."""
        if wanted(self._values()):
            QTimer.singleShot(ms, self.check)

    def check(self) -> None:
        if self.busy or not wanted(self._values()):
            self.sync()
            return
        self.busy = True
        self._say("Asking GitHub for a newer Hivemind…")
        self.sync()

        def work():
            try:
                found, said = self._check_fn()
            except Exception as exc:          # update.check never raises; a fake might
                found, said = None, f"could not check for updates ({exc})"
            self.checked.emit(found, said)
        self._run(work)

    def _show_check(self, found, said: str) -> None:
        self.busy = False
        if found is None or self.release is None or found.tag != self.release.tag:
            self.installer = None
        self.release = found
        text = html.escape(said[:1].upper() + said[1:]) + "."
        if found is not None:
            why = self._why_not()
            if why:
                text += f" {html.escape(why)}"
            else:
                text += " Press Download and install while the bot is stopped."
            text += f' <a href="{html.escape(found.page, quote=True)}">The releases page</a>'
            if self._tell is not None:
                self._tell(f"Hivemind {_dotted(found.version)} is out: Settings > General "
                           "to update")
        self._say(text)
        self.sync()

    # ---- installing -------------------------------------------------------
    def install(self) -> None:
        """Download (checked by sha256), then start the installer and close.
        Refuses unless allowed, offered and the bot is stopped."""
        release = self.release
        if (self.busy or release is None or not wanted(self._values())
                or self._why_not() or not self._bot_stopped()):
            self.sync()
            return
        if self.installer is not None:
            self._launch()
            return
        self.busy = True
        size = f" ({release.size / 1e6:.0f} MB)" if release.size else ""
        self._say(f"Downloading Hivemind {_dotted(release.version)}{size} and checking "
                  "it against the release notes…")
        self.sync()

        def work():
            try:
                self.fetched.emit(self._download_fn(release), "")
            except Exception as exc:        # a bad checksum is a ValueError
                self.fetched.emit(None, f"The download did not work: {exc}")
        self._run(work)

    def _show_download(self, path, said: str) -> None:
        self.busy = False
        if path is None:
            self._say(html.escape(said))
            self.sync()
            return
        self.installer = Path(path)
        self._launch()

    def _launch(self) -> None:
        # STILL STOPPED? Start may have been pressed during the download.
        if not self._bot_stopped():
            self._say("Downloaded. The bot is running now: stop it, then press Install.")
            self.sync()
            return
        try:
            self._start(self.installer)
        except OSError as exc:
            self._say(html.escape(f"Could not start the installer ({exc}). It is saved "
                                  f"at {self.installer}."))
            self.sync()
            return
        self._say("Starting the installer. Hivemind closes now; your settings and what "
                  "the bot learned are kept.")
        self.sync()
        self._quit()

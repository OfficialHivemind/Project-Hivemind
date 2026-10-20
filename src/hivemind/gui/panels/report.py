"""Report a problem in one click, and "Save this moment" (ROADMAP BUG-PACK).

Settings > Help > Report a problem runs scripts/debug_bundle.py, the same tool
a terminal runs, in a process of its own (a slow tesseract check or a crash
never stalls the window), then opens the folder the zip is in and says what to
do with it. "Save this moment" under the live view asks the running bot to keep
its last ~10 s of frames and run-log lines (Action.SAVE_MOMENT,
telemetry/incidents.save_moment); the next bundle carries them.

NOTHING LEAVES THE PC. The person sends the zip themselves, privately (RL4:
no telemetry, RL5: crash reports stay local).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ...datapaths import var
from ...telemetry.events import Action, Command
from ..launcher import CREATE_NO_WINDOW, UTF8_ENV, WINDOWS

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "debug_bundle.py"
# MEASURED 2026-10-27 on the owner's var (6,421 incident folders): the build
# took 1.7 s without the selftest; the selftest's tesseract call adds a few.
BUNDLE_TIMEOUT_S = 300
TITLE = "Report a problem"
STEPS = (
    "Press Report a problem. Hivemind makes one zip of its newest logs, "
    "pictures and settings, with your secrets and username taken out, and "
    "opens the folder it is in.",
    "Send that zip in a direct message (DM) to the Hivemind team on the "
    "Hivemind Discord. Say what you did and what went wrong.",
    "Never post it in a public channel: its pictures of your game can show "
    "your name, your friends or chat.",
    "Saw something odd while it played? Press Save this moment under the "
    "live view first: the next zip then has those seconds too.",
)
SEARCH_WORDS = "report problem bug crash broken debug bundle zip discord send help"
MOMENT_TIP = ("Keep the last few seconds of what the bot saw, and its log, "
              "for a problem report (Settings › Help › Report a problem).")


def make_bundle(run=subprocess.run, folder: Path | None = None) -> tuple[Path | None, str]:
    """Run the bundle tool: (the new zip, "") or (None, why not). Blocks:
    call it off the GUI thread."""
    folder = folder or var("reports")
    started = time.time()
    try:
        done = run([sys.executable, str(SCRIPT)], cwd=str(ROOT), capture_output=True,
                   text=True, encoding="utf-8", errors="replace", timeout=BUNDLE_TIMEOUT_S,
                   **({"env": {**os.environ, **UTF8_ENV}, "creationflags": CREATE_NO_WINDOW}
                      if WINDOWS else {}))
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"The report could not be made: {exc}"
    # THE NEWEST ZIP, not the tool's printed words: a windowless python on
    # Windows may print nothing at all
    zips = [p for p in folder.glob("debug-bundle-*.zip") if p.stat().st_mtime >= started - 1]
    if done.returncode or not zips:
        said = (done.stderr or done.stdout or "").strip().splitlines()
        return None, ("The report could not be made: "
                      + (said[-1] if said else f"exit code {done.returncode}"))
    return max(zips, key=lambda p: p.stat().st_mtime), ""


def open_folder(folder: Path) -> bool:
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def save_moment(send) -> str:
    """Ask the running bot to keep this moment. Returns the words for the
    status bar; the bot says in the log where it put them."""
    if send(Command(action=Action.SAVE_MOMENT, reason="saved from the live view")):
        return ("asked the bot to keep the last ~10 s of frames and log lines — "
                "the log says where")
    return ("could not save this moment: the bot is not running. After a crash, "
            "Settings › Help › Report a problem still has its logs.")


def moment_row(on_click) -> QWidget:
    """The live view's "Save this moment" button, on the right."""
    row = QWidget()
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    box.addStretch(1)
    row.button = QPushButton("Save this moment")
    row.button.setToolTip(MOMENT_TIP)
    row.button.clicked.connect(lambda: on_click())
    box.addWidget(row.button)
    return row


class ReportCard(QFrame):
    """Help's Report a problem: the steps, the button, what happened."""
    _made = Signal(object, str)          # (zip or None, why not)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Note")
        self._spawn = lambda job: threading.Thread(target=job, daemon=True,
                                                   name="hivemind-report").start()
        self.open = open_folder
        self._made.connect(self._show)           # bound: queued to the GUI thread
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(6)
        head = QLabel(TITLE.upper())
        head.setObjectName("Section")
        steps = QLabel("<br>".join(f"<b>{n}.</b>&nbsp; {s}" for n, s in enumerate(STEPS, 1)))
        steps.setWordWrap(True)
        self.button = QPushButton(TITLE)
        self.button.clicked.connect(self.report)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.hide()
        for widget in (head, steps, self.button, self.result):
            box.addWidget(widget)

    def report(self) -> None:
        self.button.setEnabled(False)
        self.result.setText("Making the zip… this takes a few seconds.")
        self.result.show()
        self._spawn(lambda: self._made.emit(*make_bundle()))

    def _show(self, path, why: str) -> None:
        self.button.setEnabled(True)
        if path is None:
            self.result.setText(why)
            return
        opened = self.open(path.parent)
        self.result.setText(
            # var/reports, not the full path: it names the login (the window
            # can be on stream; debug_bundle hides it in the zip too)
            f"Made {path.name} ({path.stat().st_size / 1e6:.1f} MB) in Hivemind's "
            f"var/reports folder. "
            + ("Its folder is open: " if opened else "Open that folder and ")
            + "send the zip by DM, as step 2 says.")

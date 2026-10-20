"""The first-run check on Windows: what this PC still needs, in plain words.

gui/firstrun's three steps (Install Sober, Log in, Start) are Linux's: on
Windows there is no Sober to install and Roblox logs in by itself. What a
beginner on Windows needs is its step 3 alone -- `hivemind doctor`'s checks
(cli/doctor_win on Windows), each problem with its fix -- shown at every start
until every check has passed once (the same `first-run-passed` marker as
gui/firstrun and gui/app.first_run_check).

LOOK ONLY: the checks read the PC and change nothing, and this window never
starts the bot or Roblox. When everything passes it says so and the player
presses Start (F1) in the main window -- the button's own name in both
layouts (gui/simple, panels/status, gui/shell).

OFF THE GUI THREAD: the checks take about half a second (MEASURED
2026-10-26 on the Windows test PC, 26 checks) and doctor.state reads
var/harvests.jsonl, which grows, so they run on a worker thread and the
window stays responsive with "Checking...". The checks touch no widget.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from . import theme
from .firstrun import Step

WINDOWS = os.name == "nt"


def wanted(marker: Path, windows: bool = WINDOWS, autostart: bool = False) -> bool:
    """Show this window? On Windows, until the checks have passed once --
    but not over a start at login (--autostart): nobody is there to read it,
    and the login start has its own countdown."""
    return windows and not autostart and not marker.exists()


def panic_key() -> str:
    """The emergency stop key the player set (safety.panic_key), as gui/shell
    shows it; F12 when the settings cannot be read."""
    from ..world.settings import panic_key_name
    return panic_key_name()


class WinCheckWindow(QWidget):
    """One step, Check this PC, and the list of what it found: problems
    first, each with its fix, then what is already fine."""

    finished = Signal(object)          # the checks, from the worker thread

    def __init__(self, marker: Path | None = None, doctor_run=None):
        super().__init__()
        from ..datapaths import config_dir
        self.marker = marker or config_dir() / "first-run-passed"
        self.doctor_run = doctor_run
        self.checks: list = []

        self.setWindowTitle("Set up Hivemind")
        self.setObjectName("WinCheck")
        self.setStyleSheet(theme.SHELL + f"QWidget#WinCheck {{ background: {theme.S_BG}; }}")
        self.resize(780, 620)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(12)
        head = QLabel("Set up Hivemind")
        head.setStyleSheet("font-size: 22px; font-weight: 800;")
        sub = QLabel("Hivemind checks this PC before it plays. The check only looks: it "
                     "changes nothing and does not open Roblox.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {theme.S_DIM};")
        outer.addWidget(head)
        outer.addWidget(sub)

        self.step = Step(1, "Check this PC",
                         "Each problem says what is wrong and how to fix it. Fix them, "
                         "then press Check again.", "Check again")
        self.step.button.clicked.connect(self.check_soon)
        self.step.set_state("busy", "Checking…")
        self.finished.connect(self.show_checks)     # queued: back on the GUI thread
        self._busy = False
        outer.addWidget(self.step)

        self._rows = QWidget()
        self._rows.setObjectName("WinCheckRows")
        self._rows.setStyleSheet(f"QWidget#WinCheckRows {{ background: {theme.S_BG}; }}")
        self.rows = QVBoxLayout(self._rows)
        self.rows.setContentsMargins(4, 4, 4, 4)
        self.rows.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        # a long path cannot wrap: it is cut at the edge rather than making
        # the whole list scroll sideways (seen offscreen, 2026-10-26)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self._rows)
        outer.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.done = QPushButton("Close")
        self.done.setMinimumHeight(34)
        self.done.clicked.connect(self.close)
        bottom.addWidget(self.done)
        outer.addLayout(bottom)

    def _row(self, check, doctor) -> QWidget:
        mark, colour = {doctor.OK: ("✓", theme.S_GOOD), doctor.WARN: ("!", theme.S_AMBER),
                        doctor.FAIL: ("✗", theme.S_BAD)}[check.status]
        row = QWidget()
        box = QVBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        line = QLabel(f"{mark}  {check.name}" + (f": {check.detail}" if check.detail else ""))
        line.setTextFormat(Qt.PlainText)          # paths and names are never markup
        line.setWordWrap(True)
        line.setStyleSheet(f"color: {colour if check.status != doctor.OK else theme.S_DIM};"
                           + (" font-weight: 700;" if check.status != doctor.OK else ""))
        box.addWidget(line)
        if check.fix and check.status != doctor.OK:
            fix = QLabel(f"How to fix: {check.fix}")
            fix.setTextFormat(Qt.PlainText)
            fix.setWordWrap(True)
            fix.setStyleSheet(f"color: {theme.S_TEXT}; padding-left: 22px;")
            box.addWidget(fix)
        return row

    def _run(self) -> list:
        from ..cli import doctor
        try:
            return list((self.doctor_run or doctor.run)())
        except Exception as exc:                       # noqa: BLE001 - shown, not raised
            return [doctor.Check("environment", "the check itself", doctor.FAIL,
                                 f"it stopped with an error ({exc})",
                                 "run `hivemind doctor` in a terminal to see the "
                                 "whole error, and send it to the team")]

    def check_soon(self) -> None:
        """Run the checks on a worker thread; show_checks lists them."""
        if self._busy:
            return
        self._busy = True
        self.step.button.setEnabled(False)
        self.step.set_state("busy", "Checking…")
        threading.Thread(target=self._work, name="wincheck", daemon=True).start()

    def _work(self) -> None:
        checks = self._run()
        try:
            self.finished.emit(checks)
        except RuntimeError:                           # the window was deleted meanwhile
            pass

    def check(self) -> list:
        """Run the checks here and now, list them, and remember a clean pass."""
        return self.show_checks(self._run())

    def show_checks(self, checks: list) -> list:
        """List the checks, problems first, and remember a clean pass."""
        from ..cli import doctor
        self._busy = False
        self.step.button.setEnabled(True)
        self.checks = checks
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)     # gone now, not at the next event loop
                item.widget().deleteLater()
        order = {doctor.FAIL: 0, doctor.WARN: 1, doctor.OK: 2}
        for c in sorted(self.checks, key=lambda c: order[c.status]):
            self.rows.addWidget(self._row(c, doctor))
        self.rows.addStretch(1)
        failed = sum(1 for c in self.checks if c.status == doctor.FAIL)
        warned = sum(1 for c in self.checks if c.status == doctor.WARN)
        if failed:
            self.step.set_state("bad", f"{failed} thing(s) to fix before Hivemind can play"
                                + (f", and {warned} worth a look" if warned else "")
                                + ". Each one says how, below.")
            return self.checks
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text("every check passed\n", encoding="utf-8")
        self.step.set_state("done", "Everything Hivemind needs is on this PC"
                            + (f" ({warned} thing(s) worth a look below)" if warned else "")
                            + ". Press Start (F1) in the main window when you are ready; "
                            + f"{panic_key()} stops everything.")
        self.step.button.setText("Check again")
        return self.checks

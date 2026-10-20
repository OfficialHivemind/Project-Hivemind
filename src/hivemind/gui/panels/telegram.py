"""The Telegram tab: the user's own bot, the alerts it sends, the stats cards.

Everything a new user needs on one page (the owner, 2026-10-14: a Telegram
setup tab for alerts and stats, with a switch per kind of notification, ready
for any user):
BotFather's steps, the token, the chat found from the message they send their
bot, a test message, and the switches that scripts/telegram_alerts.py (the
hivemind-telegram service) and scripts/daily_card.py read.

THE TOKEN is a password for the bot: whoever holds it can post as it. It is
typed into a dotted box, checked with Telegram (getMe) and only then written
to telegram.env, 0600, atomically -- never to settings.yaml, a preset, the Log
or this window's labels -- and it is never read back into the box. Errors are
told in this module's own words (`friendly`), never str() of an unknown
exception, which could quote the URL the token sits in.

NETWORK CALLS run on a thread, each with a timeout, and post back through a
signal, so a slow or absent Telegram never freezes the window.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import threading
import urllib.error
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import theme
from ...files import atomic_write
from ..widgets import Card
from .settings import SettingsPanel

ROOT = Path(__file__).resolve().parents[4]
# The service's own module (stdlib only): one env() / api() / private_chat()
# for the window and the service.
_spec = importlib.util.spec_from_file_location(
    "telegram_alerts", ROOT / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)

# 8-10 digits, a colon, 35 of [A-Za-z0-9_-] (core.telegram.org/bots/api);
# loose on the lengths, strict on the characters -- a space or a newline in
# the URL is what makes urllib's error quote it.
TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
WAIT_S = 15
TEST_TEXT = ("🐝 Hivemind is connected! The alerts you switch on in Hivemind's "
             "Telegram tab arrive here.")
# run-log lines (real ones' shapes) whose alerts the tab shows as examples
SAMPLES = ("a dialogue was read at the Polar Bear, so it leaves the hand-in queue",
           "Commando Chick: CAPTURED after 2.4 min of fighting",
           "died: pollen fell 60,053 -> 1,259 (58,794 lost)")
# theme's names, read when drawn (the new layout recolours theme)
COLOURS = {"off": "TEXT_FAINT", "busy": "INFO", "wait": "WARN", "ok": "GOOD", "bad": "BAD"}


def friendly(exc: BaseException) -> str:
    """What went wrong, in words a user can act on."""
    if isinstance(exc, urllib.error.HTTPError):
        return {
            401: "Telegram refused that token. Copy it again from BotFather "
                 "(the whole line, with the colon).",
            404: "Telegram refused that token. Copy it again from BotFather "
                 "(the whole line, with the colon).",
            400: "Telegram can't find your chat. Send your bot a message, then "
                 "press Detect chat.",
            403: "Your bot can't message you. Open it in Telegram and press "
                 "Start (or unblock it).",
            409: "Hivemind's alert service is reading the same messages right "
                 "now. Press Detect chat again in a few seconds.",
            429: "Telegram asks to slow down. Try again in a minute.",
        }.get(exc.code, f"Telegram answered with error {exc.code}. Try again later.")
    if isinstance(exc, OSError):              # URLError, a timeout, no network
        return ("Couldn't reach Telegram. Check the internet connection and "
                "try again.")
    if isinstance(exc, (RuntimeError, subprocess.SubprocessError)):
        return str(exc)                       # our own words (tg.api, the card)
    return f"Something went wrong ({type(exc).__name__})."


def heading(text: str) -> QLabel:
    """A section heading, as the settings panels draw theirs."""
    label = QLabel(text.upper())
    label.setStyleSheet(f"color: {theme.ACCENT}; font-size: 10px; font-weight: 700;"
                        " letter-spacing: 1px; padding: 10px 0 2px 0;")
    return label


def words(text: str, size: int = 12, colour: str = "",
          rich: bool = False) -> QLabel:
    """Wrapped text; plain unless `rich` (a chat's first name is anyone's)."""
    colour = colour or theme.TEXT_DIM
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText if rich else Qt.PlainText)
    label.setStyleSheet(f"color: {colour}; font-size: {size}px;")
    return label


class TelegramTab(QWidget):
    # (what to do next, the job's result or its exception), from the worker
    _done = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # how a job runs: a thread here, inline in the tests
        self._spawn = lambda job: threading.Thread(target=job, daemon=True).start()
        # A BOUND METHOD, so Qt queues it to this widget's thread; a lambda
        # here would run the GUI code on the worker thread
        self._done.connect(self._finish)
        self._buttons: list[QPushButton] = []

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 8, 0, 0)
        row.setSpacing(10)
        row.addWidget(self._setup_card(), 1)
        right = QVBoxLayout()
        right.setSpacing(10)
        self.alerts = SettingsPanel(only=("Telegram",), title="alerts",
                                    subtitle="choose what reaches your phone")
        self.alerts.set_badge("")
        self.alerts.changed.connect(self._master)
        right.addWidget(self.alerts, 1)
        self.cards = SettingsPanel(only=("Stats cards",), title="reports",
                                   subtitle="your numbers as a picture")
        self.cards.set_badge("")
        self.cards.add(self._card_row())
        self.cards.setFixedHeight(215)
        right.addWidget(self.cards)
        row.addLayout(right, 1)
        self.panels = [self.alerts, self.cards]
        self._master()
        self.refresh()
        self._looked = False

    def showEvent(self, event) -> None:
        """SAY WHETHER IT WORKS, not only that a file exists: one getMe the
        first time the tab is opened -- not when the window is built, which
        every GUI test does (and those must not reach Telegram)."""
        super().showEvent(event)
        if not self._looked and tg.env().get("TELEGRAM_TOKEN") \
                and not os.environ.get("PYTEST_CURRENT_TEST"):
            self._looked = True
            self._run(lambda: tg.api("getMe", wait=WAIT_S), self._checked,
                      "Checking your bot with Telegram…", quiet=True)

    # ---- layout ------------------------------------------------------------
    def _setup_card(self) -> Card:
        card = Card("telegram bot", "alerts and stats on your phone")
        light = QFrame()
        light.setStyleSheet(f"QFrame {{ background: {theme.GLASS_RAISED};"
                            f" border: 1px solid {theme.GLASS_EDGE}; border-radius: 12px; }}"
                            " QLabel { border: none; background: transparent; }")
        line = QHBoxLayout(light)
        line.setContentsMargins(14, 10, 14, 10)
        line.setSpacing(12)
        self._light = QLabel("●")
        line.addWidget(self._light, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self._state = QLabel()
        self._state.setStyleSheet(f"color: {theme.TEXT}; font-size: 15px; font-weight: 700;")
        self._detail = words("")
        text.addWidget(self._state)
        text.addWidget(self._detail)
        line.addLayout(text, 1)
        card.add(light)

        # THE STEPS SCROLL rather than squash: at the window's own 1560x940,
        # under a Decision Inbox card, the tab is ~540 px tall
        inner = QWidget()
        steps = QVBoxLayout(inner)
        steps.setContentsMargins(0, 0, 6, 0)
        steps.setSpacing(6)
        steps.addWidget(heading("Set it up — about two minutes"))
        steps.addWidget(self._step(1, "In Telegram, open <b>@BotFather</b> and send "
                                      "<b>/newbot</b>. Give your bot any name, then a "
                                      "username ending in <b>bot</b>."))
        steps.addWidget(self._step(2, "BotFather replies with a <b>token</b> that looks "
                                      "like <b>123456789:AAH…</b> Paste it here and press "
                                      "<b>Save token</b>.", self._token_row()))
        steps.addWidget(self._step(3, "Open your new bot in Telegram (BotFather links it) "
                                      "and press <b>Start</b>, or send it any message."))
        detect = self._button("Detect chat", self._detect)
        test = self._button("Send test message", self._test)
        self._detect_button, self._test_button = detect, test
        buttons = QWidget()
        line = QHBoxLayout(buttons)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(detect)
        line.addWidget(test)
        line.addStretch(1)
        steps.addWidget(self._step(4, "Press <b>Detect chat</b> so Hivemind knows where "
                                      "to send, then <b>Send test message</b>.", buttons))
        # PLAIN WORDS, NOT "a password" (UI panel round 2, 2026-10-22: a parent
        # read it as their Roblox password); the file path is on hover only
        keep = words("The token is a private key for the alert bot you made (not your "
                     "Roblox password). It is kept only on this PC, readable by you alone, "
                     "and is never shown, logged or put in a preset. Alerts go only to "
                     "your own private chat with the bot.", 12, theme.TEXT_FAINT)
        keep.setToolTip("Kept in ~/.config/hivemind/telegram.env")
        steps.addWidget(keep)
        steps.addWidget(heading("What you can send it"))
        steps.addWidget(words("<b>/status</b> &nbsp;<b>/screenshot</b> &nbsp;<b>/pause</b> "
                              "&nbsp;<b>/resume</b> &nbsp;<b>/stop</b> &nbsp;<b>/report</b> "
                              "— from your own chat only, while <b>Allow commands from "
                              "Telegram</b> is on. <b>/screenshot</b> is a picture of "
                              "the Roblox window only, never your whole screen.",
                              12, theme.TEXT, rich=True))
        # THE HEADING ONLY OVER SOMETHING (UI panel item 10: with the alerts
        # off it stood over nothing)
        bubbles = [self._bubble(hit[2]) for hit in
                   (tg.triage(line, {}, 0.0, settings=None) for line in SAMPLES) if hit]
        if bubbles:
            steps.addWidget(heading("What it sends"))
        for bubble in bubbles:
            steps.addWidget(bubble)
        steps.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        card.add(scroll, 1)
        return card

    @staticmethod
    def _bubble(text: str) -> QWidget:
        """One message as the chat shows it -- the service's own words for a
        sample log line (SAMPLES), so the preview cannot drift from them."""
        bubble = QLabel(f"🐝 {text}")              # short: one line each
        bubble.setTextFormat(Qt.PlainText)
        bubble.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; padding: 7px 12px;"
                             f" background: {theme.GLASS_RAISED}; border: 1px solid "
                             f"{theme.GLASS_EDGE}; border-radius: 12px;"
                             " border-top-left-radius: 3px;")
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(36, 0, 60, 0)
        line.addWidget(bubble, 0, Qt.AlignLeft)
        return row

    def _step(self, number: int, text: str, extra: QWidget | None = None) -> QWidget:
        step = QWidget()
        line = QHBoxLayout(step)
        line.setContentsMargins(0, 4, 0, 4)
        line.setSpacing(12)
        badge = QLabel(str(number))
        badge.setFixedSize(24, 24)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"color: #1a1206; font-weight: 800; font-size: 12px;"
                            f" border-radius: 12px; background: qlineargradient("
                            f"x1:0, y1:0, x2:0, y2:1, stop:0 {theme.ACCENT_HOVER},"
                            f" stop:1 {theme.ACCENT_DEEP});")
        line.addWidget(badge, 0, Qt.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(8)
        column.addWidget(words(text, 13, theme.TEXT, rich=True))
        if extra is not None:
            column.addWidget(extra)
        line.addLayout(column, 1)
        return step

    def set_streaming(self, on: bool) -> None:
        """No Show button while the stream window is open: one click must not
        put the token on a stream (UI panel round 2, 2026-10-22)."""
        if on:
            self._show.setChecked(False)
        self._show.setVisible(not on)

    def _token_row(self) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.token = QLineEdit()
        # DOTS (and Qt's Password mode will not copy the text out either)
        self.token.setEchoMode(QLineEdit.Password)
        self.token.returnPressed.connect(self._save)
        line.addWidget(self.token, 1)
        self._show = QPushButton("Show")
        self._show.setCheckable(True)
        self._show.setCursor(Qt.PointingHandCursor)
        self._show.toggled.connect(lambda on: (
            self.token.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
            self._show.setText("Hide" if on else "Show")))
        line.addWidget(self._show)
        self._show.setToolTip("Hidden while the stream window is open")
        save = self._button("Save token", self._save)
        save.setObjectName("Primary")
        save.setStyleSheet(theme.PRIMARY)
        line.addWidget(save)
        return row

    def _card_row(self) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(2, 4, 8, 0)
        self._card_button = self._button("Send a stats card now", self._card_now)
        line.addWidget(self._card_button)
        self._card_note = words("", 11)
        line.addWidget(self._card_note, 1)
        return row

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(slot)
        self._buttons.append(button)
        return button

    # ---- state ---------------------------------------------------------------
    def status(self, kind: str, title: str, detail: str) -> None:
        """The light: off (not set up), busy, wait (a step left), ok, bad."""
        self._light.setStyleSheet(f"color: {getattr(theme, COLOURS[kind])}; font-size: 22px;")
        self._state.setText(title)
        self._detail.setText(detail)

    def refresh(self) -> None:
        """The light and the buttons from telegram.env (no network)."""
        e = tg.env()
        self.token.setPlaceholderText(
            "token saved — paste a new one to replace it"
            if e.get("TELEGRAM_TOKEN") else "paste the token from BotFather")
        self._detect_button.setEnabled("TELEGRAM_TOKEN" in e)
        self._test_button.setEnabled("TELEGRAM_TOKEN" in e and "TELEGRAM_CHAT" in e)
        self._card_button.setEnabled("TELEGRAM_TOKEN" in e and "TELEGRAM_CHAT" in e)
        if "TELEGRAM_TOKEN" not in e:
            self.status("off", "Not set up", "Follow the four steps below to get "
                        "alerts and stats cards on your phone.")
        elif "TELEGRAM_CHAT" not in e:
            self.status("wait", "One step left", "Your bot's token is saved. Send "
                        "your bot a message in Telegram, then press Detect chat.")
        else:
            self.status("ok", "Set up", "Alerts go to your private chat with your bot.")

    def _master(self, key: str = "telegram.alerts", _value=None) -> None:
        """The card says so while the master switch is off. The switches
        under it keep their ticks (a disabled box draws empty, which would
        read as every choice wiped)."""
        if key != "telegram.alerts":
            return
        on = bool(self.alerts.values.get("telegram.alerts", True))
        self.alerts.set_badge("" if on else "ALL OFF", theme.BAD)
        self.alerts.set_subtitle("choose what reaches your phone" if on else
                                 "nothing is sent while the master switch is off")

    def _write(self, **changes) -> None:
        """telegram.env with `changes` (None removes a line), 0600, atomic."""
        values = {**tg.env(), **changes}
        atomic_write(tg.ENV, "".join(f"{k}={v}\n" for k, v in values.items()
                                     if v is not None), mode=0o600)

    # ---- jobs ------------------------------------------------------------------
    def _run(self, job, then, busy: str, quiet: bool = False) -> None:
        """`job` on a thread, then `then(result or exception)` back here."""
        for button in self._buttons:
            button.setEnabled(False)
        if not quiet:
            self.status("busy", "Working…", busy)

        def work():
            try:
                result = job()
            except Exception as exc:          # handed to `then`, told by friendly()
                result = exc
            try:
                self._done.emit((then, result))
            except RuntimeError:              # the window closed meanwhile
                pass
        self._spawn(work)

    def _finish(self, pair) -> None:
        then, result = pair
        then(result)

    def _after(self, result, ok_title: str, ok_detail: str) -> bool:
        """Buttons back, and the light: False (said) on an exception."""
        for button in self._buttons:
            button.setEnabled(True)
        self.refresh()
        if isinstance(result, BaseException):
            self.status("bad", "Last try failed", friendly(result))
            return False
        if ok_title:
            self.status("ok", ok_title, ok_detail)
        return True

    def _checked(self, result) -> None:
        if isinstance(result, BaseException):
            self._after(result, "", "")
        elif "TELEGRAM_CHAT" in tg.env():
            name = (result.get("result") or {}).get("username", "")
            self._after(result, "Connected", f"Alerts go to your private chat "
                        f"with @{name}." if name else "Alerts go to your private chat.")
        else:
            self._after(result, "", "")

    def _save(self) -> None:
        token = self.token.text().strip()
        if not TOKEN.match(token):
            self.status("bad", "That isn't a bot token", "A token looks like "
                        "123456789:AAH… — copy the whole line BotFather sent.")
            return
        self._run(lambda: tg.api("getMe", token=token, wait=WAIT_S),
                  lambda result: self._saved(token, result),
                  "Checking the token with Telegram…")

    def _saved(self, token: str, result) -> None:
        if not isinstance(result, BaseException):
            # A NEW BOT IS A NEW CHAT: the old one may never have messaged it
            same = tg.env().get("TELEGRAM_TOKEN") == token
            self._write(TELEGRAM_TOKEN=token,
                        TELEGRAM_CHAT=tg.env().get("TELEGRAM_CHAT") if same else None)
            self.token.clear()
            self._show.setChecked(False)
        name = (result.get("result") or {}).get("username", "your bot") \
            if isinstance(result, dict) else ""
        self._after(result, "Token saved", f"Now open @{name} in Telegram, press "
                    "Start (or send it any message), then press Detect chat."
                    if "TELEGRAM_CHAT" not in tg.env() else
                    f"Connected to @{name}. Press Send test message to check.")

    def _detect(self) -> None:
        # timeout=0: a quick look, not a long poll; nothing is confirmed, so
        # the service's own learn_chat and any listener still see the message
        self._run(lambda: tg.private_chat(
            tg.api("getUpdates", wait=WAIT_S, timeout=0).get("result", [])),
            self._detected, "Looking for your message…")

    def _detected(self, result) -> None:
        if isinstance(result, urllib.error.HTTPError) and result.code == 409 \
                and "TELEGRAM_CHAT" in tg.env():
            result = None                     # the service found it first
            self._after(result, "Chat found", "Press Send test message to check.")
        elif result is None:
            self._after(result, "", "")
            self.status("wait", "No message yet", "In Telegram, open your bot and "
                        "press Start or send it “hi”, then press Detect chat again. "
                        "Only a private chat counts, not a group.")
        elif not isinstance(result, BaseException):
            self._write(TELEGRAM_CHAT=result[0])
            self._after(result, "Chat found", f"Hello{' ' + result[1] if result[1] else ''}! "
                        "Press Send test message to check.")
        else:
            self._after(result, "", "")

    def _test(self) -> None:
        self._run(lambda: tg.api("sendMessage", wait=WAIT_S, text=TEST_TEXT,
                                 chat_id=tg.env()["TELEGRAM_CHAT"]),
                  lambda r: self._after(r, "Connected", "Test message sent — "
                                        "check Telegram."),
                  "Sending a test message…")

    def _card_now(self) -> None:
        def job():
            # the venv's python (cv2 draws the card); the schedule is skipped
            done = subprocess.run([sys.executable, str(ROOT / "scripts" / "daily_card.py"),
                                   "--hours", "24", "--send", "--now"], cwd=ROOT,
                                  capture_output=True, text=True, timeout=180)
            if done.returncode:
                last = (done.stderr.strip().splitlines() or ["exit %d" % done.returncode])[-1]
                raise RuntimeError(last[:200])
        self._card_note.setText("drawing the card…")
        self._run(job, self._card_sent, "Drawing and sending a stats card…", quiet=True)

    def _card_sent(self, result) -> None:
        self._after(result, "", "")
        self._card_note.setText("sent — check Telegram" if not isinstance(
            result, BaseException) else friendly(result))

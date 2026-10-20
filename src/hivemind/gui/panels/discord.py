"""Settings > Notifications: the user's own Discord webhook (ROADMAP U21).

scripts/telegram_alerts.py already posts every alert to the webhook in
~/.config/hivemind/discord.env (DISCORD_WEBHOOK=, optional DISCORD_PING=);
this page is the box that writes that file. The URL is a secret -- whoever
holds it can post in the channel -- so it is typed into a dotted box, checked
to be a real Discord webhook address, written 0600 atomically and never read
back into the box, logged or shown. "Send test" runs the service's own
`--discord-test`, on a thread, and shows its one-line answer.
"""
from __future__ import annotations

import re
import subprocess
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from .. import theme
from ...files import atomic_write
from ..widgets import Card
from .telegram import ROOT, heading, tg, words

PYTHON = "/usr/bin/python3"            # the service's own interpreter (stdlib only)
# the hosts telegram_alerts posts to, then the id and the token: digits, and
# the token's own characters only (a space or newline would break the file)
WEBHOOK = re.compile(r"^https://(?:discord\.com|discordapp\.com|ptb\.discord\.com"
                     r"|canary\.discord\.com)/api/webhooks/\d{5,25}/[A-Za-z0-9_-]{20,100}$")
PING = re.compile(r"^\d{17,20}$")      # a Discord user id (a snowflake)


def valid_webhook(url: str) -> bool:
    return bool(WEBHOOK.match(url)) and url.startswith(tg.DISCORD_HOSTS)


class DiscordPage(QWidget):
    _done = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spawn = lambda job: threading.Thread(target=job, daemon=True).start()
        self._done.connect(self._tested)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        card = Card("discord", "alerts in your own server")
        card.setMaximumWidth(720)
        self._state = QLabel()
        self._state.setStyleSheet("font-size: 15px; font-weight: 700;")
        self._detail = words("")
        card.add(self._state)
        card.add(self._detail)
        card.add(heading("Webhook URL"))
        card.add(words("In Discord: Server Settings > Integrations > Webhooks > New "
                       "Webhook, pick the channel, then Copy Webhook URL and paste it here."))
        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setEchoMode(QLineEdit.Password)
        self.url.returnPressed.connect(self.save)
        row.addWidget(self.url, 1)
        self.show_button = QPushButton("Show")
        self.show_button.setCheckable(True)
        self.show_button.toggled.connect(lambda on: (
            self.url.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
            self.show_button.setText("Hide" if on else "Show")))
        row.addWidget(self.show_button)
        card.add_layout(row)
        card.add(heading("Ping (optional)"))
        card.add(words("Your Discord user ID, to be mentioned on each alert (Developer "
                       "Mode on, then right-click your name > Copy User ID). Empty: no ping."))
        self.ping = QLineEdit()
        self.ping.setPlaceholderText("e.g. 123456789012345678")
        self.ping.setMaximumWidth(260)
        card.add(self.ping)
        buttons = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.save_button.setStyleSheet(theme.PRIMARY)
        self.save_button.clicked.connect(self.save)
        self.test_button = QPushButton("Send test")
        self.test_button.clicked.connect(self.test)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setObjectName("Danger")
        self.remove_button.clicked.connect(self.remove)
        for button in (self.save_button, self.test_button, self.remove_button):
            button.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(button)
        buttons.addStretch(1)
        card.add_layout(buttons)
        card.add(words("The webhook URL is kept only in ~/.config/hivemind/discord.env, "
                       "readable by you alone, and is never shown, logged or put in a "
                       "preset. The same alerts as Telegram are posted there.",
                       11, theme.TEXT_FAINT))
        box.addWidget(card, 0, Qt.AlignTop)
        box.addStretch(1)
        self.refresh()

    def status(self, colour: str, title: str, detail: str) -> None:
        self._state.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {colour};")
        self._state.setText(title)
        self._detail.setText(detail)

    def refresh(self) -> None:
        e = tg.discord_env()
        saved = bool(e.get("DISCORD_WEBHOOK"))
        self.url.setPlaceholderText("webhook saved: paste a new one to replace it"
                                    if saved else "https://discord.com/api/webhooks/...")
        self.ping.setText(e.get("DISCORD_PING", ""))
        self.test_button.setEnabled(saved)
        self.remove_button.setEnabled(saved)
        if saved:
            self.status(theme.GOOD, "Set up", "Alerts are also posted to your Discord channel.")
        else:
            self.status(theme.TEXT_DIM, "Not set up", "Paste a channel's webhook URL to "
                        "get the alerts in Discord too.")

    def save(self) -> bool:
        url, ping = self.url.text().strip(), self.ping.text().strip()
        if not url:                              # only the ping changed
            url = tg.discord_env().get("DISCORD_WEBHOOK", "")
        if not valid_webhook(url):
            self.status(theme.BAD, "That isn't a Discord webhook URL", "It starts with "
                        "https://discord.com/api/webhooks/ followed by two parts. Copy it "
                        "again from the channel's Webhooks page.")
            return False
        if ping and not PING.match(ping):
            self.status(theme.BAD, "That isn't a user ID", "A Discord user ID is 17 to "
                        "20 digits. Leave it empty for no ping.")
            return False
        atomic_write(tg.DISCORD_ENV, f"DISCORD_WEBHOOK={url}\n"
                     + (f"DISCORD_PING={ping}\n" if ping else ""), mode=0o600)
        self.url.clear()
        self.show_button.setChecked(False)
        self.refresh()
        self.status(theme.GOOD, "Saved", "Press Send test to check the channel.")
        return True

    def remove(self) -> None:
        atomic_write(tg.DISCORD_ENV, "", mode=0o600)
        self.refresh()

    def test(self) -> None:
        def job():
            try:
                done = subprocess.run([PYTHON, str(ROOT / "scripts" / "telegram_alerts.py"),
                                       "--discord-test"], cwd=ROOT, capture_output=True,
                                      text=True, timeout=60)
                said = done.stdout.strip().splitlines()[-1:] or ["no answer"]
                why = done.stderr.strip().splitlines()[-1:]     # curl's code, never the URL
                answer = said[0] if said[0] == "sent" or not why else why[0]
            except (OSError, subprocess.SubprocessError) as exc:
                answer = f"not sent ({type(exc).__name__})"
            url = tg.discord_env().get("DISCORD_WEBHOOK")
            if url:                              # never on screen, whatever printed it
                answer = answer.replace(url, "<webhook>")
            try:
                self._done.emit(answer)
            except RuntimeError:                 # the window closed meanwhile
                pass
        self.test_button.setEnabled(False)
        self.status(theme.INFO, "Sending a test…", "")
        self._spawn(job)

    def _tested(self, answer: str) -> None:
        self.refresh()
        if answer == "sent":
            self.status(theme.GOOD, "Test sent", "Check your Discord channel.")
        else:
            self.status(theme.BAD, "Test not sent", answer[:200])

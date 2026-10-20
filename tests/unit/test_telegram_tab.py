"""The Telegram tab and the two scripts behind it (gui/panels/telegram,
scripts/telegram_alerts.py, scripts/daily_card.py). No network: Telegram's
API is patched. Nothing here reads or writes the real ~/.config/hivemind."""
from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

import pytest
import yaml

# BEFORE the tab's module loads the service's: its ENV is fixed at import
os.environ["HIVEMIND_TELEGRAM_ENV"] = str(Path(tempfile.mkdtemp()) / "telegram.env")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels import settings as panel_mod  # noqa: E402
from hivemind.gui.panels import telegram as tab_mod  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402

APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[2]
tg = tab_mod.tg
TOKEN = "987654321:AAHfake_token_for_tests_only_0123456789"
HANDED = "    22:01:02  a dialogue was read at the Polar Bear, so it leaves the hand-in queue"
MYTHIC = "royal jelly: 5 rolled on the cell at (962, 165); it now holds the Tadpole Bee"
PLAIN = "royal jelly: 2 rolled on the cell at (962, 165); it now holds the Brave Bee"


def _settings(tmp_path, **values) -> Path:
    path = tmp_path / "settings.yaml"
    values = {"alerts": True, **values}          # the master ships off (U15b)
    path.write_text(yaml.safe_dump({f"telegram.{k}": v for k, v in values.items()}))
    return path


# ---- the switches ----------------------------------------------------------
def test_the_switches_filter_the_alerts(tmp_path):
    assert tg.triage(HANDED, {}, 0.0, _settings(tmp_path))[0] == "telegram.quest"
    assert tg.triage(HANDED, {}, 0.0, _settings(tmp_path, quest=False)) is None
    off = _settings(tmp_path, alerts=False)
    assert tg.triage(HANDED, {}, 0.0, off) is None and tg.triage(MYTHIC, {}, 0.0, off) is None
    # a Mythic is a picture even with the rolls switched off; a plain roll is not sent
    no_rolls = _settings(tmp_path, royal_jelly=False)
    assert tg.triage(MYTHIC, {}, 0.0, no_rolls)[:2] == ("telegram.alerts", True)
    assert tg.triage(PLAIN, {}, 0.0, no_rolls) is None
    # off by default: the chatty ones
    assert tg.triage("self-review: slow walks home", {}, 0.0, None) is None
    assert tg.triage("    08:27:07  planter: harvested the Paper Planter in the bamboo — its loot",
                     {}, 0.0, None) is None


def test_a_switch_counts_at_once_and_the_gap_is_per_pattern(tmp_path):
    line, sent = "x — asking for a rejoin, which lands", {}
    path = _settings(tmp_path)
    assert tg.triage(line, sent, 1000.0, path)
    assert tg.triage(line, sent, 1000.0 + 60, path) is None       # within 30 min
    assert tg.triage(line, sent, 1000.0 + 1801, path)
    path.write_text(yaml.safe_dump({"telegram.rejoin": False}))   # the tab's click
    assert tg.triage(line, sent, 1e6, path) is None


def test_the_needs_you_line_is_an_alert(tmp_path):
    hit = tg.triage("    12:35:59  goals: Ready to buy the Parachute at the Noob Shop for "
                    "500,000 honey — a card is in the Decision Inbox; the bot buys it",
                    {}, 0.0, _settings(tmp_path))
    assert hit[0] == "telegram.needs_you" and "Parachute" in hit[2]


def test_the_reader_takes_what_the_gui_writes_and_its_defaults_are_the_schemas(tmp_path):
    ours = {k: v for k, v in schema.defaults().items() if k.startswith("telegram.")}
    assert tg.DEFAULTS == ours
    flipped = {k: (not v if isinstance(v, bool) else "every 4 hours + daily")
               for k, v in ours.items()}
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({**flipped, "goals.order": "a long sentence: with a colon " * 9},
                                   sort_keys=True))
    assert tg.toggles(path) == flipped
    for choice in ("off", "daily at 21:00"):
        path.write_text(yaml.safe_dump({"telegram.stats_cards": choice}))
        assert tg.toggles(path)["telegram.stats_cards"] == choice
    assert tg.toggles(tmp_path / "missing.yaml") == ours
    assert set(ours) == ({kind for kind, *_ in tg.ALERTS}
                         | {"telegram.stats_cards", "telegram.commands"})


def test_check_passes_on_the_services_own_python():
    python = shutil.which("python3", path="/usr/bin")
    if python is None:
        pytest.skip("no /usr/bin/python3")
    done = subprocess.run([python, str(ROOT / "scripts" / "telegram_alerts.py"), "--check"],
                          capture_output=True, text=True, timeout=60,
                          env={**os.environ, "PYTHONPATH": ""})
    assert done.stdout.strip() == "ok", done.stderr


# ---- the tab -------------------------------------------------------------------
@pytest.fixture
def tab(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "ENV", tmp_path / "telegram.env")
    monkeypatch.setattr(panel_mod, "CONFIG", tmp_path / "settings.yaml")
    calls = []

    def api(method, token=None, wait=70, **params):
        calls.append((method, token, wait, params))
        answer = api.answers.get(method)
        if isinstance(answer, BaseException):
            raise answer
        return answer
    api.answers = {"getMe": {"ok": True, "result": {"username": "my_hive_bot"}}}
    monkeypatch.setattr(tg, "api", api)
    t = tab_mod.TelegramTab()
    t._spawn = lambda job: job()                  # inline: no thread in a test
    t.calls, t.answers = calls, api.answers
    return t


def _shown(t) -> str:
    return " ".join([t._state.text(), t._detail.text(), t._card_note.text(), t.token.text(),
                     t.token.placeholderText()])


def test_the_token_is_saved_0600_and_never_shown_logged_or_exported(tab, tmp_path, capsys):
    assert tab._state.text() == "Not set up"
    tab.token.setText(TOKEN)
    tab._save()
    assert tab.calls[-1][:2] == ("getMe", TOKEN) and tab.calls[-1][2] <= 30
    assert tg.env() == {"TELEGRAM_TOKEN": TOKEN}
    assert os.name == "nt" or stat.S_IMODE(os.stat(tg.ENV).st_mode) == 0o600   # chmod is a no-op on Windows (MEASURED 2026-10-21: files come out 0o666); %LOCALAPPDATA% is the user's own
    assert tab.token.text() == "" and "@my_hive_bot" in tab._detail.text()
    # every alert switch saved, and a preset of the whole setup exported
    for key, widget in tab.alerts._widgets.items():
        widget.setChecked(not widget.isChecked())
    out = tmp_path / "preset.yaml"
    panel_mod.SettingsPanel().export_preset(out)
    for text in (panel_mod.CONFIG.read_text(), out.read_text(), _shown(tab),
                 "".join(capsys.readouterr())):
        assert TOKEN not in text and TOKEN.split(":")[1] not in text


def test_a_refused_or_strange_token_is_not_saved_and_not_quoted(tab):
    tab.answers["getMe"] = urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, None)
    tab.token.setText(TOKEN)
    tab._save()
    assert tg.env() == {} and tab._state.text() == "Last try failed"
    assert "refused" in tab._detail.text() and TOKEN not in _shown(tab).replace(tab.token.text(), "")
    tab.token.setText("not a token")
    tab._save()
    assert tab.calls[-1][0] == "getMe" and len(tab.calls) == 1   # no call for junk
    assert tab._state.text() == "That isn't a bot token"
    # an error that quotes the URL (and so the token) is told by its type only
    assert TOKEN not in tab_mod.friendly(ValueError(f"bad url /bot{TOKEN}/getMe"))


def test_detect_takes_only_a_private_chat(tab):
    group = {"message": {"chat": {"id": -100123, "type": "group", "title": "pals"}}}
    mine = {"message": {"chat": {"id": 4242, "type": "private", "first_name": "Ana"}}}
    assert tg.private_chat([group]) is None
    assert tg.private_chat([group, mine]) == (4242, "Ana")
    tab._write(TELEGRAM_TOKEN=TOKEN)
    tab.answers["getUpdates"] = {"ok": True, "result": [group]}
    tab._detect()
    assert "TELEGRAM_CHAT" not in tg.env() and tab._state.text() == "No message yet"
    tab.answers["getUpdates"] = {"ok": True, "result": [group, mine]}
    tab._detect()
    assert tg.env()["TELEGRAM_CHAT"] == "4242" and "Ana" in tab._detail.text()
    assert tab.calls[-1][3] == {"timeout": 0}            # a quick look, not a long poll
    tab._test()
    assert tab.calls[-1][0] == "sendMessage" and tab.calls[-1][3]["chat_id"] == "4242"
    assert tab._detail.text().startswith("Test message sent")


def test_a_new_bot_forgets_the_old_chat(tab):
    tab._write(TELEGRAM_TOKEN="111111111:AAHold_token_xxxxxxxxxxxxxxxxxxxxxxxx", TELEGRAM_CHAT="7")
    tab.token.setText(TOKEN)
    tab._save()
    assert tg.env() == {"TELEGRAM_TOKEN": TOKEN}


def test_the_master_switch_says_so_and_keeps_the_ticks(tab):
    master = tab.alerts._widgets["telegram.alerts"]
    quest = tab.alerts._widgets["telegram.quest"]
    master.setChecked(False)
    assert tab.alerts._badge.text() == "ALL OFF" and quest.isChecked() and quest.isEnabled()
    master.setChecked(True)
    assert tab.alerts._badge.text() == ""


# ---- daily_card's schedule ---------------------------------------------------------
def _daily_card():
    spec = importlib.util.spec_from_file_location("daily_card_t", ROOT / "scripts" / "daily_card.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_stats_card_follows_the_schedule(monkeypatch):
    dc = _daily_card()
    assert [h for h in (9, 13, 17, 21) if dc.due("daily at 21:00", h)] == [21]
    assert all(dc.due("every 4 hours + daily", h) for h in (9, 13, 17, 21))
    assert not any(dc.due("off", h) for h in range(24))
    drawn = []
    monkeypatch.setattr(dc, "render", lambda *a: drawn.append(a))
    monkeypatch.setattr(dc, "stats", lambda hours: {"hours": hours})
    monkeypatch.setattr(dc.tg, "post_photo", lambda *a: drawn.append("sent"))
    monkeypatch.setattr(dc.tg, "toggles", lambda: {"telegram.stats_cards": "off"})
    monkeypatch.setattr(sys, "argv", ["daily_card.py", "--hours", "4", "--send"])
    dc.main()
    assert drawn == []                                   # off: quietly, nothing drawn
    monkeypatch.setattr(sys, "argv", ["daily_card.py", "--send", "--now"])
    dc.main()
    assert drawn[-1] == "sent"                           # the tab's "now" skips it


def test_a_gui_test_never_reaches_telegram(tab):
    tab._write(TELEGRAM_TOKEN=TOKEN, TELEGRAM_CHAT="1")
    fresh = tab_mod.TelegramTab()
    fresh.show()
    APP.processEvents()
    assert tab.calls == [] and fresh._state.text() == "Set up"
    fresh.close()


def test_no_show_button_while_the_stream_window_is_open(tab):
    """UI panel round 2 (2026-10-22): one click must not put the token on stream."""
    from PySide6.QtWidgets import QLineEdit
    tab._show.setChecked(True)
    tab.set_streaming(True)
    assert tab._show.isHidden() and tab.token.echoMode() == QLineEdit.Password
    tab.set_streaming(False)
    assert not tab._show.isHidden()

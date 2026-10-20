"""S7: the hand-written "what's new" (data/whats_new.md), once per reader, in
the GUI (gui/tour.show_whats_new) and on Telegram (scripts/telegram_alerts.py
send_whats_new). Offscreen; tmp files only, send is patched (no network)."""
from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget  # noqa: E402

from hivemind.gui import tour  # noqa: E402
from hivemind.telemetry import whatsnew  # noqa: E402

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
APP = QApplication.instance() or QApplication([])
NOTES = "# What's new\nintro\n\n## Faster trips\n- Walks home sooner.\n\n## Old one\n- old\n"


def test_the_shipped_file_has_an_entry():
    head, body = whatsnew.newest()
    assert head and body


def test_newest_entry_once_per_reader(tmp_path):
    notes, seen = tmp_path / "n.md", tmp_path / "seen.json"
    notes.write_text(NOTES)
    assert whatsnew.newest(notes) == ("Faster trips", "- Walks home sooner.")
    assert whatsnew.unseen("gui", notes, seen) == ("Faster trips", "- Walks home sooner.")
    whatsnew.mark_seen("gui", "Faster trips", seen)
    assert whatsnew.unseen("gui", notes, seen) is None
    assert whatsnew.unseen("telegram", notes, seen) is not None     # its own reader
    notes.write_text("## Next update\n- more\n" + NOTES)            # a new top entry
    assert whatsnew.unseen("gui", notes, seen) == ("Next update", "- more")
    seen.write_text("not json")
    assert whatsnew.unseen("gui", notes, seen) is not None
    assert whatsnew.newest(tmp_path / "missing.md") == ("", "")


def test_gui_card_shows_once_and_never_over_the_tour(tmp_path):
    notes, seen = tmp_path / "n.md", tmp_path / "seen.json"
    notes.write_text(NOTES)
    window = QMainWindow()
    window.setCentralWidget(QWidget())
    window.tour = object()
    assert tour.show_whats_new(window, notes, seen) is None
    window.tour = None
    card = tour.show_whats_new(window, notes, seen)
    assert card is not None and "Faster trips" in card.findChildren(type(card.body))[0].text()
    card.ok_button.click()
    assert window.whats_new is None
    assert tour.show_whats_new(window, notes, seen) is None


def test_telegram_sends_once_under_the_master_switch(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("telegram_alerts_s7",
                                                  ROOT / "scripts" / "telegram_alerts.py")
    tg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tg)
    notes, seen = tmp_path / "n.md", tmp_path / "seen.json"
    notes.write_text(NOTES)
    monkeypatch.setattr(whatsnew, "NOTES", notes)
    monkeypatch.setattr(whatsnew, "_seen_path", lambda: seen)
    sent = []
    monkeypatch.setattr(tg, "send", sent.append)
    assert tg.send_whats_new({"telegram.alerts": False}) is False and not sent
    assert tg.send_whats_new({"telegram.alerts": True}) is True
    assert sent == ["What's new: Faster trips\n- Walks home sooner."]
    assert tg.send_whats_new({"telegram.alerts": True}) is False and len(sent) == 1

"""Report a problem in one click, and Save this moment (gui/panels/report,
ROADMAP BUG-PACK). Offscreen; the bundle tool is a stand-in."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels import report  # noqa: E402
from hivemind.telemetry.events import Action  # noqa: E402

APP = QApplication.instance() or QApplication([])


def fake_tool(folder: Path, code: int = 0, write: bool = True):
    def run(argv, **kw):
        assert argv[-1].endswith("debug_bundle.py") and kw["timeout"]
        if write:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "debug-bundle-20261027-120000.zip").write_bytes(b"PK")
        return subprocess.CompletedProcess(argv, code, "", "Traceback...\nOSError: disk full\n")
    return run


def test_the_bundle_is_found_by_its_new_zip(tmp_path):
    path, why = report.make_bundle(fake_tool(tmp_path), tmp_path)
    assert path == tmp_path / "debug-bundle-20261027-120000.zip" and why == ""


def test_a_failed_bundle_says_why_in_one_line(tmp_path):
    path, why = report.make_bundle(fake_tool(tmp_path, code=1, write=False), tmp_path)
    assert path is None and why.endswith("OSError: disk full")

    def missing(argv, **kw):
        raise FileNotFoundError("no python")
    assert report.make_bundle(missing, tmp_path)[0] is None


def test_an_old_zip_is_not_taken_for_the_new_one(tmp_path):
    old = tmp_path / "debug-bundle-20261001-000000.zip"
    old.write_bytes(b"PK")
    os.utime(old, (1, 1))
    assert report.make_bundle(fake_tool(tmp_path, write=False), tmp_path)[0] is None


def test_the_card_makes_the_zip_off_the_gui_thread_and_opens_its_folder(tmp_path, monkeypatch):
    zip_ = tmp_path / "reports" / "debug-bundle-x.zip"
    zip_.parent.mkdir()
    zip_.write_bytes(b"PK" * 1000)
    card = report.ReportCard()
    jobs, opened = [], []
    card._spawn = jobs.append
    card.open = lambda folder: opened.append(folder) or True
    monkeypatch.setattr(report, "make_bundle", lambda: (zip_, ""))
    card.report()
    assert not card.button.isEnabled() and jobs          # nothing ran on the GUI thread
    jobs[0]()
    APP.processEvents()
    assert opened == [zip_.parent] and card.button.isEnabled()
    text = card.result.text()
    assert "debug-bundle-x.zip" in text and "DM" in text
    assert str(tmp_path) not in text                    # no login name on screen
    monkeypatch.setattr(report, "make_bundle", lambda: (None, "The report could not be made: x"))
    card.report()
    jobs[-1]()
    APP.processEvents()
    assert card.result.text() == "The report could not be made: x"


def test_the_steps_say_dm_never_public():
    words = " ".join(report.STEPS)
    assert "direct message" in words and "Hivemind Discord" in words
    assert "Never post it in a public channel" in words


def test_save_this_moment_asks_the_bot_and_says_when_it_cannot():
    sent = []
    said = report.save_moment(lambda e: sent.append(e) or True)
    assert sent[0].action == Action.SAVE_MOMENT and "asked the bot" in said
    assert "not running" in report.save_moment(lambda e: False)


def test_the_bot_answers_save_this_moment():
    """run_farm's socket handler keeps the moment (incidents.save_moment) on
    a thread of its own, before Controls (which would drop it)."""
    src = (report.ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    at = src.index("event.action == Action.SAVE_MOMENT")
    assert at < src.index("        controls.handle(event)\n", at)
    assert "box.save_moment(log, event.reason)" in src[at:at + 1500]
    assert 'name="hivemind-save-moment"' in src[at:at + 2000]

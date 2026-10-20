"""The PLAN tab (gui/panels/plan): one click writes a plan, says so, Undo puts
it back, your own changes are kept and Reset gives them back, Hybrid's ticks
are the target, "I have it" is one tap, and NOW/NEXT read the bot's files.
Offscreen; never the real ~/.config/hivemind or var/."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ["HIVEMIND_TELEGRAM_ENV"] = str(Path(tempfile.mkdtemp()) / "telegram.env")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind import datapaths  # noqa: E402
from hivemind.gui.panels import settings as panel_mod  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def page(tmp_path, monkeypatch):
    path = tmp_path / "cfg" / "settings.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump({"combat.bug_runs": True}))     # one of "yours"
    var = tmp_path / "var"
    var.mkdir()
    monkeypatch.setattr(panel_mod, "CONFIG", path)
    monkeypatch.setattr(schema, "CONFIG", path)
    monkeypatch.setattr(schema.Settings.__init__, "__defaults__", (path,))
    monkeypatch.setattr(datapaths, "VAR_ROOT", var)
    from hivemind.gui.panels.plan import PlanPanel
    settings = panel_mod.SettingsPanel()
    heard = []
    settings.changed.connect(lambda k, v: heard.append(k))
    panel = PlanPanel(settings, clock=lambda: 1_000_000.0)
    panel.heard, panel.path, panel.var = heard, path, var
    yield panel
    panel.deleteLater()
    settings.deleteLater()


def _saved(page) -> dict:
    return yaml.safe_load(page.path.read_text())


def test_a_fresh_file_shows_your_own_setup_and_every_choice(page):
    assert page.radios["custom"].isChecked()
    for choice in ("progress", "item", "honey", "quests", "tickets", "macro",
                   "fuzzy_alt", "tad_alt", "hybrid"):
        assert choice in page.radios
    assert page.quest_box.currentText() == "Bucko Bee"      # nothing read: the default
    assert page.item_box.count() > 0
    assert page.hybrid_box.isHidden()


def test_one_click_writes_the_plan_tells_the_bot_and_undo_puts_it_back(page):
    page.radios["honey"].click()
    saved = _saved(page)
    assert saved["plan.goal"] == "honey" and schema.Settings(page.path).get("quests.enabled") is False
    assert "plan.goal" in page.heard and {k for k in saved if not k.startswith("_")} - {"combat.bug_runs"} <= set(page.heard)
    assert page.settings.values["plan.goal"] == "honey"
    # combat.bug_runs was the player's own: kept, counted, Reset gives it back
    assert saved["combat.bug_runs"] is True
    assert page.kept_line.text() == "1 of your own change kept"
    assert "Now: Make the most honey" in page.said.text() and "1 of yours kept" in page.said.text()
    page.reset_button.click()
    assert _saved(page)["combat.bug_runs"] is False and not page.reset_button.isVisibleTo(page)
    page.undo_button.click()
    assert _saved(page)["combat.bug_runs"] is True
    page.undo_button.setVisible(True)
    page._undo = page._undo_plan
    page.undo_button.click()
    assert _saved(page)["plan.goal"] == "custom"
    assert page.radios["custom"].isChecked()


def test_quests_and_item_take_their_dropdown(page):
    page.quest_box.setCurrentText("Riley Bee")
    page.radios["quests"].click()
    saved = _saved(page)
    assert saved["plan.target"] == "Riley Bee" and saved["quests.riley"] is True
    page.item_box.setCurrentIndex(0)
    page.radios["item"].click()
    assert _saved(page)["plan.target"] == page.item_box.currentText()


def test_hybrid_ticks_are_its_targets(page):
    page.radios["hybrid"].click()
    assert _saved(page)["plan.target"] == "fuzzy_alt, tad_alt"
    assert not page.hybrid_box.isHidden()
    page.hybrid_checks["tide_popper"].click()
    assert _saved(page)["plan.target"] == "fuzzy_alt, tad_alt, tide_popper"
    from hivemind.brain import plan
    names = plan.targets(schema.Settings(page.path))
    assert "Supreme Star Amulet" in names and "Tide Popper" in names


def test_the_card_reads_now_why_next_and_i_have_it_is_one_tap(page):
    (page.var / "trips.jsonl").write_text(json.dumps({
        "at": 1_000_000.0 - 600, "chosen": "Pine Tree",
        "candidates": [{"field": "Pine Tree", "why": "most blue pollen an hour"}]}) + "\n")
    page.radios["fuzzy_alt"].click()
    assert page.lines["NOW"].text() == "Gathering at Pine Tree (10 min ago)"
    assert page.lines["WHY"].text() == "most blue pollen an hour"
    assert page.lines["GOAL"].text().startswith("Fuzzy alt")
    from PySide6.QtWidgets import QPushButton
    buttons = [b for b in page.findChildren(QPushButton) if b.text() == "I have it"]
    assert len(buttons) == 1
    buttons[0].click()
    assert "Porcelain Dipper" in _saved(page)["goals.owned"]
    page.undo_button.click()
    assert "Porcelain Dipper" not in (_saved(page).get("goals.owned") or "")


def test_it_refreshes_only_while_on_screen(page):
    assert not page.timer.isActive()
    page.show()
    assert page.timer.isActive()
    page.hide()
    assert not page.timer.isActive()


def _next_text(page) -> str:
    from PySide6.QtWidgets import QLabel
    shown = [page.next_box.itemAt(i).widget() for i in range(page.next_box.count())]
    labels = [w for w in shown if isinstance(w, QLabel)]
    labels += [lab for w in shown for lab in w.findChildren(QLabel)]
    return " ".join(lab.text() for lab in labels)


def test_your_own_setup_promises_no_next_item_it_will_not_work_on(page):
    """Usability triage 2026-10-27 #3: a fresh install (buying and quests off)
    listed egg quests and shop tools under NEXT as if it would do them."""
    rows = [{"what": "Porcelain Dipper", "state": "no", "item": "Porcelain Dipper"}]
    page._show_next(rows)
    assert "buying and quests are off" in _next_text(page)
    assert "Porcelain Dipper" not in _next_text(page)
    page.settings.set_value("economy.buy", True)          # their own switch on: shown
    page._show_next(rows)
    assert "Porcelain Dipper" in _next_text(page)

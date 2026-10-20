"""Stats > Wax calculator (ROADMAP H4b, gui/panels/waxcalc): no odds without
the wiki's table, the waxes it can model, and an answer in plain words."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hivemind.brain import waxcalc                          # noqa: E402
from hivemind.gui.panels import waxcalc as page_mod         # noqa: E402

POOL = [waxcalc.Upgrade("Pollen", 3), waxcalc.Upgrade("Convert Rate", 1),
        waxcalc.Upgrade("Gold Bubble Pollen", 1, caustic_only=True)]


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_only_waxes_that_add_points_are_offered():
    table = {"limit": "text", "soft": {"power": 1}, "hard": {"power": 2},
             "caustic": {"power": 4}, "swirled": {"power": 0}, "turpentine": {"effect": "x"}}
    assert page_mod.wax_choices(table) == ["soft", "hard", "caustic"]
    assert "swirled" not in page_mod.wax_choices()


def test_the_beequip_names_read_as_the_wiki_writes_them():
    names = page_mod.beequip_names()
    assert "Camphor Lip Balm" in names and names == sorted(names)


def test_the_answer_says_the_chance_the_risk_and_how_it_was_worked_out():
    said = page_mod.describe({"p": 0.372, "destroyed": 0.12, "trials": 20000,
                              "method": "seeded Monte Carlo", "note": waxcalc.QUALITY_NOTE},
                             "Pollen", 2)
    assert "37.2%" in said and "2 or more wax points" in said
    assert "12.0%" in said and "destroys" in said
    assert "20,000 tries" in said and "UNCONFIRMED" in said


def test_no_odds_until_the_table_has_loaded_and_then_real_ones():
    _app()
    asked = []
    page = page_mod.WaxCalcPage(fetch=lambda name: asked.append(name) or POOL)
    assert not page.calculate.isEnabled() and not asked     # nothing read at build time
    page._on_loaded(POOL, "Pinecone: 3 stats")
    assert page.calculate.isEnabled()
    assert [page.stat.itemText(i) for i in range(page.stat.count())] == [u.name for u in POOL]
    page.run()
    assert "Choose at least one wax" in page.answer.text()
    page.waxes[0].setCurrentText("Soft")
    page.run()
    # one Soft point: Pollen 3 against Convert Rate 1 (the Caustic-only stat
    # is out of a Soft pick), so 3 in 4
    said = page.answer.text()
    assert "chance that Pollen gets 1 or more" in said
    assert abs(float(said.split("%")[0].split(">")[-1]) - 75.0) < 1.5, said


def test_a_failed_load_shows_why_and_keeps_calculate_off():
    _app()
    page = page_mod.WaxCalcPage(fetch=lambda name: POOL)
    page._on_loaded(None, "could not read the wiki's beequip table (offline)")
    assert not page.calculate.isEnabled()
    assert "could not read" in page.answer.text()


def test_the_load_runs_off_the_gui_thread_and_reports_back():
    import threading
    _app()
    seen = threading.Event()
    page = page_mod.WaxCalcPage(fetch=lambda name: (seen.set(), POOL)[1])
    page.beequip.setCurrentText("Pinecone")
    page.load_stats()
    assert seen.wait(5)
    from PySide6.QtCore import QCoreApplication
    for _ in range(50):
        QCoreApplication.processEvents()
        if page.calculate.isEnabled():
            break
    assert page.calculate.isEnabled() and "3 stats" in page.answer.text()

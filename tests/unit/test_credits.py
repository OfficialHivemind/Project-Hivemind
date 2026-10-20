"""data/knowledge/credits.yaml and the Credits tab: every viewer the roadmap
credits is on it, by name only (the owner, 2026-10-21)."""
from __future__ import annotations

import re
from pathlib import Path

import hivemind
from hivemind.gui.panels import credits

REPO = Path(hivemind.__file__).resolve().parents[2]


def test_every_named_viewer_in_the_roadmap_is_credited():
    roadmap = REPO / "docs" / "ROADMAP.md"
    if not roadmap.exists():
        import pytest
        pytest.skip("the roadmap is not in this checkout")
    road = roadmap.read_text()
    rows = credits.load(REPO / "data" / "knowledge" / "credits.yaml")
    by_item = {r["roadmap"] for r in rows}
    for line in road.splitlines():
        m = re.match(r"- ([A-Z0-9$]+[a-z]?) `", line)
        if not m or "(VIEWER " not in line:
            continue
        who = re.search(r"\(VIEWER ([^,;)]+)", line).group(1).strip(" '")
        if who.startswith("suggestion via"):      # M2b: no name was given
            continue
        assert m.group(1) in by_item, (m.group(1), who)


def test_names_only_and_known_statuses():
    rows = credits.load(REPO / "data" / "knowledge" / "credits.yaml")
    assert rows and all(r["status"] in credits.STATUS for r in rows)
    assert not any(re.search(r"\d{15,}", str(v)) for r in rows for v in r.values())
    assert [credits.STATUS and r["status"] for r in rows][0] == "built"   # built first


def test_the_page_draws(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel
    app = QApplication.instance() or QApplication([])
    page = credits.CreditsPage(credits.load(REPO / "data" / "knowledge" / "credits.yaml"))
    text = " ".join(l.text() for l in page.widget().findChildren(QLabel))
    assert "Sonny" in text and "ideas from" in text
    assert app is not None

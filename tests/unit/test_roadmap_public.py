"""docs/ROADMAP-PUBLIC.md, the roadmap the public repo shows: every credited
community idea is on it with a status the Credits tab agrees with, every status
is one of the five, and it never names another macro."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import hivemind
from hivemind.gui.panels import credits

REPO = Path(hivemind.__file__).resolve().parents[2]
ITEM = re.compile(r"- \*\*(?:([A-Z$][A-Za-z0-9$]*)(?: / [A-Z$][A-Za-z0-9$]*)? · )?[^*]+\*\* `(\w+)`")
# Other macros' names, kept as sha256 prefixes so this file doesn't name them.
OTHER_MACROS = {"d605c8dc445875ec", "70b6144fae4d4c16", "cfef850d0830a8bc",
                "46dc36a26fbcfb8c", "a73eb4ec31aa38b7"}


def _road() -> str:
    return (REPO / "docs" / "ROADMAP-PUBLIC.md").read_text(encoding="utf-8")


def _items():
    """(code or None, status, line) for every item line."""
    for line in _road().splitlines():
        m = ITEM.match(line)
        if m:
            yield m.group(1), m.group(2), line


def test_every_status_is_one_of_the_five():
    items = list(_items())
    assert len(items) > 100
    assert {s for _, s, _ in items} <= set(credits.STATUS)


def test_every_credited_idea_is_on_it_with_a_credited_status():
    rows = credits.load(REPO / "data" / "knowledge" / "credits.yaml")
    shown = {code: status for code, status, _ in _items() if code}
    for code in {r["roadmap"] for r in rows}:
        assert code in shown, code
        assert shown[code] in {r["status"] for r in rows if r["roadmap"] == code}, code


def test_every_community_idea_line_is_credited():
    by_item = {r["roadmap"] for r in credits.load(REPO / "data" / "knowledge" / "credits.yaml")}
    for code, _, line in _items():
        if "(community idea)" in line:
            assert code in by_item, line


def test_no_other_macro_is_named():
    words = set(re.findall(r"[a-z]+", _road().lower()))
    named = {w for w in words if hashlib.sha256(w.encode()).hexdigest()[:16] in OTHER_MACROS}
    assert not named

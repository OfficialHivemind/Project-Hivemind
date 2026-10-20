"""tools/wiki_revcheck.py (K12): cited wiki revids vs the wiki's current ones."""
import importlib.util
from pathlib import Path

import hivemind

ROOT = Path(hivemind.__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("wiki_revcheck", ROOT / "tools" / "wiki_revcheck.py")
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)


def test_every_citation_shape():
    text = "\n".join([
        "  source: https://bee-swarm-simulator.fandom.com/wiki/Honey_Bee_(NPC) (api.php rev 449569, read x)",
        "    title: 'BSS Wiki: Stick Bug Amulet (rev 448576, 2026-07-28)'",
        "# wiki Commando_Chick rev 448352, and Commando_Chick's_Hideout page (rev 449613)",
        "  * Module:Beequip Stats/data (revid 446414): each beequip",
        "    title: 'BSS Fanon wiki: Hive:White Hive (community article, rev 44549)'",
    ])
    assert rc.citations(text) == [
        ("Honey Bee (NPC)", 449569, 1),
        ("Stick Bug Amulet", 448576, 2),
        ("Commando Chick", 448352, 3),
        ("Commando Chick's Hideout", 449613, 3),
        ("Module:Beequip Stats/data", 446414, 4),
    ]


def test_repo_citations_found():
    found = rc.scan()
    assert ("Black Bear" in found and "Module:Beequip Stats/data" in found)


def test_diff_flags_changed_and_missing():
    found = {"Egg": [(100, "a:1"), (100, "a:2")], "Onett": [(5, "b:9")], "Gone": [(7, "c:3")]}

    def fetch(titles):
        assert titles == ["Egg", "Gone", "Onett"]
        return {"query": {
            "normalized": [{"from": "Egg", "to": "Egg"}],
            "pages": [{"title": "Egg", "revisions": [{"revid": 100, "timestamp": "t1"}]},
                      {"title": "Onett", "revisions": [{"revid": 6, "timestamp": "t2"}]},
                      {"title": "Gone", "missing": True}]}}

    now = rc.current_revids(found, fetch=fetch)
    assert rc.diff(found, now) == [
        "MISSING Gone: not on the wiki now (cited at c:3)",
        "CHANGED Onett: cited rev 5 (b:9), now rev 6 (t2)",
    ]

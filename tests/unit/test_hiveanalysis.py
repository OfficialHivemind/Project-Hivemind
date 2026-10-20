"""H3 hive analysis: token pickups credited to the bees that make them."""
import json

import yaml

from hivemind.brain import hiveanalysis
from hivemind.vision import beemenu


def _log(tmp_path, rows):
    p = tmp_path / "lessons.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    return p


def test_pickups_counts_collected_in_window(tmp_path):
    rows = ([{"kind": "haste", "outcome": "collected"}] * 3
            + [{"kind": "focus", "outcome": "nothing"}, {"kind": "focus", "outcome": "unknown"}]
            + [{"kind": "baby_love", "outcome": "collected"}])
    got, judged = hiveanalysis.pickups(_log(tmp_path, rows))
    assert got == {"haste": 3, "baby_love": 1} and judged == 5
    got, judged = hiveanalysis.pickups(_log(tmp_path, rows), window=2)
    assert got == {"baby_love": 1} and judged == 2
    assert hiveanalysis.pickups(tmp_path / "missing") == ({}, 0)


def test_shared_kind_split_by_held_and_zero_said_softly():
    counts = {"hasty": 1, "ninja": 3, "diamond": 5, "bubble": 10}
    lines = hiveanalysis.would_lines(counts, {"haste": 8}, 100, {"ninja": "Ninja Bee"})
    assert ("hive analysis: 3 Ninja Bee -> 6 haste picked up in the last "
            "100 judged chases (2.0 a bee)") in lines[:2]
    assert any("1 hasty -> 2 haste" in line for line in lines[:2])
    assert "5 diamond -> no measured token" in lines[2] and "gathering" in lines[2]
    assert not any("bubble" in line for line in lines)   # no token kind known
    assert "nothing measured" in hiveanalysis.would_lines(counts, {}, 0)[0]


def test_makers_are_real_kinds_and_bees():
    kinds = set(yaml.safe_load(open(beemenu.TYPES_FILE.parent / "tokens.yaml"))["kinds"])
    types = beemenu.types()
    for kind, bees in hiveanalysis.MAKERS.items():
        assert kind in kinds
        assert all(b in types for b in bees)

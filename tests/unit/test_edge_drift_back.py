"""A-WALKS: the edge drift-back (act/drift EDGE_DRIFT_BACK_LIVE), look-only."""
from pathlib import Path

import hivemind
from hivemind.act import drift


def test_owed_is_the_ground_since_the_aim_was_last_named():
    trail = [(10.0, 0.0, 0.0), (20.0, 100.0, -50.0), (30.0, 400.0, 200.0)]
    # the feed last named the aim at t=25: the trail's last entry before it
    assert drift.owed_since(trail, (400.0, 200.0), 25.0) == (300.0, 250.0)
    assert drift.owed_since(trail, (400.0, 200.0), 30.0) == (0.0, 0.0)
    # nothing that old (cleared or capped): no walk
    assert drift.owed_since(trail, (400.0, 200.0), 5.0) is None
    assert drift.owed_since([], (1.0, 1.0), 99.0) is None


def test_ships_look_only_and_only_for_dandelion():
    assert drift.EDGE_DRIFT_BACK_LIVE is False
    assert drift.EDGE_DRIFT_BACK_AIMS == frozenset({"dandelion"})


def test_wired_into_the_edge_of_the_field_branch():
    root = Path(hivemind.__file__).resolve().parents[2]
    src = (root / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    edge = src.index("not a mis-delivery; gathering on here")
    assert "edge_drift_back(aim, here, seen_aim)" in src[edge:edge + 200]
    body = src[src.index("def edge_drift_back("):src.index("def landed_elsewhere(")]
    # the look-only branch logs and returns before any key is held
    look = body.index("if not drift_mod.EDGE_DRIFT_BACK_LIVE:")
    assert body.index("edge drift-back would: ", look) < body.index("return", look)
    assert body.index("return", look) < body.index("steer_by_drift(")

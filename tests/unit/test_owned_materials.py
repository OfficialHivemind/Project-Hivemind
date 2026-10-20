"""A gear goal whose materials were used up is inferred bought (2026-10-20:
the Cobalt Guard, Blue Extract 107 -> 8, while the balance said nothing)."""
import json

from hivemind.brain import owned


def _read(var, at, counts):
    (var / "inventory.json").write_text(json.dumps({
        "read_at": at, "items": {k: {"count": v, "label": k} for k, v in counts.items()}}))


def test_used_materials_mark_the_cobalt_guard_inferred(tmp_path):
    p = owned.Purchases(tmp_path, say=lambda t: None)
    _read(tmp_path, 1000.0, {"blue_extract": 107, "stinger": 149, "enzymes": 55})
    assert p.observe_materials() == []                    # the first read is the baseline
    _read(tmp_path, 2000.0, {"blue_extract": 8, "stinger": 49, "enzymes": 5})
    assert "cobalt_guard" in p.observe_materials()
    state = owned.load_state(tmp_path)
    assert state["items"]["cobalt_guard"]["state"] == owned.INFERRED
    assert "blue extract 107 -> 8" in state["items"]["cobalt_guard"]["why"]
    assert p.observe_materials() == []                    # same read: nothing new


def test_one_material_falling_or_any_rising_is_not_a_purchase(tmp_path):
    p = owned.Purchases(tmp_path, say=lambda t: None)
    _read(tmp_path, 1000.0, {"blue_extract": 107, "stinger": 149, "enzymes": 55})
    p.observe_materials()
    _read(tmp_path, 2000.0, {"blue_extract": 8, "stinger": 149, "enzymes": 60})
    assert "cobalt_guard" not in p.observe_materials()

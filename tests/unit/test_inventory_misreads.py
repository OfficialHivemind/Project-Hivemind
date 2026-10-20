"""Impossible inventory reads held back (act/inventory), each a real one from
the night logs of 2026-10-19..21 (runs 1067-1167)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np

from hivemind.act import inventory


def _read(counts):
    r = inventory.InventoryRead()
    r.ok, r.counts = True, dict(counts)
    return r


def test_a_one_read_jump_keeps_the_last_count_until_a_read_agrees(tmp_path):
    path = tmp_path / "inventory.json"
    inventory.write(path, _read({"royal_jelly": 7, "moon_charm": 11}), {}, clock=lambda: 100.0)
    held = inventory.write(path, _read({"royal_jelly": 17, "moon_charm": 36}), {},
                           clock=lambda: 200.0)
    assert held == {"royal_jelly": ["7", "17"], "moon_charm": ["11", "36"]}
    body = json.loads(path.read_text())
    assert body["items"]["royal_jelly"]["count"] == 7          # the spike not believed
    # 7 -> 17 -> 7: the next read is the true one
    assert inventory.write(path, _read({"royal_jelly": 7, "moon_charm": 11}), {},
                           clock=lambda: 300.0) == {}
    # a real gain (spent from since) is believed on the second read
    inventory.write(path, _read({"royal_jelly": 17}), {}, clock=lambda: 400.0)
    assert inventory.write(path, _read({"royal_jelly": 16}), {}, clock=lambda: 500.0) == {}
    assert json.loads(path.read_text())["items"]["royal_jelly"]["count"] == 16


def test_small_rises_falls_and_purchases_are_believed(tmp_path):
    path = tmp_path / "inventory.json"
    inventory.write(path, _read({"treats": 114903, "royal_jelly": 4}), {}, clock=lambda: 100.0)
    assert inventory.write(path, _read({"treats": 32982, "royal_jelly": 8}), {},
                           clock=lambda: 200.0) == {}
    (tmp_path / "purchases.json").write_text(json.dumps(
        [{"at": 250.0, "item": "10 Royal Jelly", "ok": True}]))
    assert inventory.write(path, _read({"royal_jelly": 18}), {}, clock=lambda: 300.0) == {}


def test_a_cap_whose_slash_was_lost_reads_the_count():
    crop = np.full((20, 40, 3), 255, np.uint8)             # white digits

    def run(text):
        return lambda *a, **k: SimpleNamespace(stdout=text.encode())
    one = inventory._one_count
    assert one(crop, 0, 3, 245, run("27100")) == 27          # MEASURED "27100 -> 26"
    assert one(crop, 0, 3, 245, run("21/100")) == 21
    assert one(crop, 0, 3, 245, run("x18")) == 18
    assert one(crop, 0, 3, 245, run("x32982")) == 32982
    assert one(crop, 0, 3, 245, run("100")) == 100
    assert one(crop, 0, 3, 245, run("x1100")) == 1100        # uncapped, its "x" read


def test_a_steady_rise_waits_one_read_not_hours(tmp_path):
    # runs 1103-1108: tickets read 77, 83, 90, 115 after 5 and stayed held at 5
    path = tmp_path / "inventory.json"
    inventory.write(path, _read({"tickets": 5}), {}, clock=lambda: 100.0)
    assert inventory.write(path, _read({"tickets": 77}), {}, clock=lambda: 200.0) == {
        "tickets": ["5", "77"]}
    for at, n in ((300.0, 83), (400.0, 90), (500.0, 115)):
        assert inventory.write(path, _read({"tickets": n}), {}, clock=lambda: at) == {}
    assert json.loads(path.read_text())["items"]["tickets"]["count"] == 115


def test_a_whirligig_restock_from_a_written_zero_and_a_craft_are_believed(tmp_path):
    path = tmp_path / "inventory.json"
    done = _read({"glitter": 3})
    done.complete = True
    inventory.write(path, done, {}, clock=lambda: 100.0, zero_unseen=("whirligig",))
    assert json.loads(path.read_text())["items"]["whirligig"]["count"] == 0
    assert inventory.write(path, _read({"whirligig": 8, "glitter": 3}), {}, clock=lambda: 200.0,
                           zero_unseen=("whirligig",)) == {}
    # a Blender craft collected since the last read is a gain, not a jump
    (tmp_path / "blender.json").write_text(json.dumps({"made": [[250.0, "enzymes", 10]]}))
    inventory.write(path, _read({"enzymes": 16}), {}, clock=lambda: 240.0)
    assert inventory.write(path, _read({"enzymes": 51}), {}, clock=lambda: 300.0) == {}

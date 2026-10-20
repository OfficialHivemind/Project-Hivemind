"""ROADMAP H17: hive presets -- the built-in starters, the HMH1 share code
(strict, fuzzed, malicious codes) and the Hive Planner's Presets menu."""
from __future__ import annotations

import base64
import json
import os
import random
import zlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from hivemind.brain import hiveplanner as hp  # noqa: E402
from hivemind.brain import hivepresets as hpre  # noqa: E402
from hivemind.world import userpatterns as up  # noqa: E402


def raw_code(body: bytes, prefix="HMH1:", crc=None) -> str:
    payload = base64.urlsafe_b64encode(zlib.compress(body)).decode().rstrip("=")
    return f"{prefix}{payload}.{(zlib.crc32(body) if crc is None else crc):08x}"


def js(obj) -> bytes:
    return json.dumps(obj).encode()


# ---- the starters -----------------------------------------------------------
def test_starters_load_valid_and_cover_every_hive():
    presets = hpre.starters()
    assert len({p["id"] for p in presets}) == len(presets)
    for hive in ("blue", "red", "white"):
        stages = {p["stage"] for p in presets if p["hive"] == hive}
        assert "endgame" in stages and len(stages) >= 3, hive
    for p in presets:
        slots = hpre.slots_of(p)
        assert len(slots) == sum(p["bees"].values()) <= hp.SLOTS
        assert set(slots) == set(range(1, len(slots) + 1))      # from slot 1, no gaps
        assert set(slots.values()) <= hpre.bee_names()
        assert p["source"]                                         # every one cited
        assert hpre.decode(hpre.encode(slots)) == slots


def test_blue_stage_one_is_the_guides_comp():
    """The AG guide's 13-14 Bubbles | 5 Diamonds, low end, biggest group first:
    the same order "Fill from guide plan" (fill_from_comp) uses."""
    p = next(p for p in hpre.starters() if p["id"] == "blue_ag1")
    slots = hpre.slots_of(p)
    assert slots == {**{s: "bubble" for s in range(1, 14)}, **{s: "diamond" for s in range(14, 19)}}


# ---- the share code ---------------------------------------------------------
def test_round_trip_canonical_and_short():
    plan = {1: "bubble", 2: "bubble", 50: "diamond", 7: "tadpole"}
    code = hpre.encode(plan)
    assert code.startswith("HMH1:") and len(code) < 200
    assert hpre.decode(code) == plan
    assert hpre.encode(dict(reversed(list(plan.items())))) == code   # same plan, same code
    assert hpre.decode("  " + code[:20] + "\n" + code[20:] + " ") == plan   # pasted, wrapped
    full = {s: "carpenter" for s in range(1, 51)}
    assert len(hpre.encode(full)) < hpre.MAX_CODE_CHARS


def test_encode_refuses_what_decode_would():
    for bad in ({}, {1: "notabee"}, {0: "bubble"}, {51: "bubble"}):
        with pytest.raises(ValueError):
            hpre.encode(bad)


MALICIOUS = [
    js({"slots": {"1": "bubble"}, "run": "rm -rf ~"}),          # anything else read: no
    js({"slots": {"1": "bubble"}, "name": "x"}),
    js({"slots": {}}),
    js({"slots": []}),
    js({"slots": ["bubble"]}),
    js({"slots": "bubble"}),
    js({"slots": None}),
    js(["slots"]),
    js("slots"),
    js(None),
    js({}),
    js({"slots": {"0": "bubble"}}),
    js({"slots": {"51": "bubble"}}),
    js({"slots": {"-1": "bubble"}}),
    js({"slots": {"07": "bubble"}}),
    js({"slots": {" 7": "bubble"}}),
    js({"slots": {"7.0": "bubble"}}),
    js({"slots": {"1e1": "bubble"}}),
    js({"slots": {"٣": "bubble"}}),                         # an Arabic-Indic 3
    js({"slots": {"²": "bubble"}}),                         # superscript 2: isdigit, not int
    js({"slots": {"1": "Bubble"}}),
    js({"slots": {"1": "bubble "}}),
    js({"slots": {"1": "../../etc/passwd"}}),
    js({"slots": {"1": "<b>bubble</b>"}}),
    js({"slots": {"1": 5}}),
    js({"slots": {"1": None}}),
    js({"slots": {"1": ["bubble"]}}),
    js({"slots": {"1": {"bee": "bubble"}}}),
    js({"slots": {"1": "x" * 3000}}),
    js({"slots": {str(i): "bubble" for i in range(1, 52)}}),     # 51 entries
    b"[" * 3000 + b"]" * 3000,                                   # deep nesting
    b'{"slots": {"1": "bubble"}',                                # cut short
    b"\xff\xfe not ascii",
    b"",
    b"NaN",
]


@pytest.mark.parametrize("body", MALICIOUS)
def test_malicious_bodies_are_refused(body):
    with pytest.raises(hpre.InvalidCode):
        hpre.decode(raw_code(body))


@pytest.mark.parametrize("code", [
    None, 12, b"HMH1:", ["HMH1:"], {}, "", "HMH1:", "HMH1:.", "hello",
    "HMH2:abc.00000000", "HMH1:abc", "HMH1:@@@@.00000000", "HMH1:abc.0000000G",
    "HMH1:" + "A" * 3000 + ".00000000",
    "HMH1:" + base64.urlsafe_b64encode(b"not zlib at all").decode().rstrip("=") + ".00000000",
])
def test_malformed_codes_are_refused(code):
    with pytest.raises(hpre.InvalidCode):
        hpre.decode(code)


def test_wrong_checksum_other_prefix_and_zip_bomb():
    body = js({"slots": {"1": "bubble"}})
    with pytest.raises(hpre.InvalidCode, match="checksum"):
        hpre.decode(raw_code(body, crc=zlib.crc32(body) ^ 1))
    # a pattern code is not a hive code, and a hive code is not a pattern code
    with pytest.raises(hpre.InvalidCode, match="HMH1"):
        hpre.decode(up.encode({"name": "x", "steps": [{"move": "w", "studs": 5}]}))
    with pytest.raises(up.InvalidCode):
        up.decode(hpre.encode({1: "bubble"}))
    # a megabyte of zeros packs into a short code: refused before it is inflated
    bomb = raw_code(b"0" * 1_000_000)
    assert len(bomb) < hpre.MAX_CODE_CHARS
    with pytest.raises(hpre.InvalidCode, match="too big"):
        hpre.decode(bomb)


def test_fuzz_never_raises_anything_but_invalid_code():
    rng = random.Random(17)
    good = hpre.encode({s: rng.choice(sorted(hpre.bee_names())) for s in range(1, 51)})
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.:= \n"
    for _ in range(3000):
        kind = rng.random()
        if kind < 0.4:                                   # flip characters
            chars = list(good)
            for _ in range(rng.randint(1, 4)):
                chars[rng.randrange(len(chars))] = rng.choice(alphabet)
            code = "".join(chars)
        elif kind < 0.6:                                 # cut short
            code = good[:rng.randrange(len(good))]
        elif kind < 0.8:                                 # random bytes, well packed
            blob = bytes(rng.randrange(256) for _ in range(rng.randint(0, 200)))
            code = raw_code(blob)
        else:                                            # random text
            code = "HMH1:" + "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 300)))
        try:
            plan = hpre.decode(code)
        except hpre.InvalidCode:
            continue
        # the rare survivor is a plan that passes the whole check
        assert plan and all(1 <= s <= 50 and b in hpre.bee_names() for s, b in plan.items())


# ---- the Hive Planner's Presets menu ----------------------------------------
@pytest.fixture
def panel(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from hivemind.gui.panels.hiveplanner import HivePlannerPanel
    p = HivePlannerPanel(hive=lambda: "red")
    p.path = tmp_path / hp.PLAN_FILE
    p.slots = {}
    p.asked = []
    p.confirm = lambda text: p.asked.append(text) or p.answer
    p.answer = True
    yield p
    p.deleteLater()


def test_starter_dialog_previews_and_apply_writes_the_planners_own_file(panel, tmp_path):
    from hivemind.gui.panels.hiveplanner import PresetDialog
    dlg = PresetDialog(panel, hive="red")
    assert dlg.hive.currentData() == "red"                      # opens on the current hive
    assert dlg.list.count() == sum(p["hive"] == "red" for p in hpre.starters())
    dlg.hive.setCurrentIndex(dlg.hive.findData("blue"))
    names = [dlg.list.item(i).text() for i in range(dlg.list.count())]
    dlg.list.setCurrentRow(next(i for i, t in enumerate(names) if "Stage 1" in t))
    assert dlg.apply_button.isEnabled() and len(dlg.plan) == 18
    assert dlg.view.shown == dlg.plan and "AG guide" in dlg.source.text()
    # an empty plan: applied with no question
    assert panel.apply_plan(dlg.plan, dlg.title) and panel.asked == []
    ref = tmp_path / "ref.json"
    hp.save(ref, dlg.plan)
    assert (tmp_path / hp.PLAN_FILE).read_text() == ref.read_text()   # byte for byte
    assert hp.load(tmp_path / hp.PLAN_FILE) == dlg.plan
    # a plan there: asked first; "no" keeps it
    panel.answer = False
    other = hpre.slots_of(hpre.starters()[-1])
    assert not panel.apply_plan(other, "x") and "replaces your plan of 18" in panel.asked[0]
    assert hp.load(tmp_path / hp.PLAN_FILE) == dlg.plan
    dlg.deleteLater()


def test_import_dialog_validates_before_apply_and_copy_code(panel):
    from PySide6.QtWidgets import QApplication
    from hivemind.gui.panels.hiveplanner import PresetDialog
    assert panel.share_code() is None
    panel.copy_code()
    assert "No plan" in panel._note.text()
    panel.apply_plan({1: "spicy", 2: "precise"})
    panel.copy_code()
    code = QApplication.clipboard().text()
    assert code == panel.share_code() and code.startswith("HMH1:")
    dlg = PresetDialog(panel)
    dlg.code.setPlainText("HMH1:garbage.00000000")
    assert dlg.plan is None and not dlg.apply_button.isEnabled()
    dlg.code.setPlainText(raw_code(js({"slots": {"1": "<img src=x>"}})))
    assert dlg.plan is None and "&lt;img" in dlg.verdict.text()
    dlg.code.setPlainText(code)
    assert dlg.plan == {1: "spicy", 2: "precise"} and dlg.apply_button.isEnabled()
    assert "1 Spicy Bee" in dlg.verdict.text()
    dlg.deleteLater()

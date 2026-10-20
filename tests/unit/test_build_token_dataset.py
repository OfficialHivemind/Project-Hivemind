"""scripts/build_token_dataset: a look group's kind, kept only after a confirmed chase, split by run."""
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np

import hivemind

REPO = Path(hivemind.__file__).resolve().parents[2]


def _builder():
    spec = importlib.util.spec_from_file_location("build_token_dataset",
                                                  REPO / "scripts" / "build_token_dataset.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _disc(bgr, size=192):
    img = np.full((size, size, 3), (40, 140, 40), np.uint8)          # grass
    cv2.circle(img, (size // 2, size // 2), 40, bgr, -1)
    return img


YELLOW, BLUE = (0, 200, 240), (200, 80, 20)


def _fixture(tmp_path):
    home = tmp_path / "home"
    school = home / "var" / "school-coins"
    (school / "crops-wide").mkdir(parents=True)
    lessons = [  # id, colour, outcome, evidence, sight, attempt
        ("a", YELLOW, "collected", "honey rose 900 in 2.0s against 100 expected from the trickle", "", 1),
        ("b", YELLOW, "unknown", "the chase never reached it", "", 1),
        ("c", BLUE, "unknown", "a unknown leaves no mark this can read on the HUD", "collected", 2),
        ("d", YELLOW, "collected", "haste absent -> 1", "", 3),
        ("e", BLUE, "collected", "the buff bar's stacks went from 1 to 3 altogether", "", 2),
        ("f", BLUE, "collected", "honey rose 900 in 2.0s against 100 expected from the trickle", "", 4),
    ]
    for rid, colour, *_ in lessons:
        cv2.imwrite(str(school / "crops-wide" / f"{rid}.jpg"), _disc(colour))
    rows = [{"id": rid, "at": 0.0, "kind": "unknown", "confidence": 1.0, "x": 1, "y": 1,
             "outcome": outcome, "evidence": ev, "attempt": att, "sight": sight}
            for rid, _, outcome, ev, sight, att in lessons]
    rows.append({"id": "g", "at": 0.0, "kind": "unknown", "confidence": 1.0, "x": 1, "y": 1,
                 "outcome": "collected", "evidence": "haste absent -> 1", "attempt": 5})  # no crop
    (school / "lessons.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    frame = np.full((720, 1280, 3), (40, 140, 40), np.uint8)
    cv2.circle(frame, (300, 180), 40, YELLOW, -1)
    (home / "var" / "incidents" / "w1").mkdir(parents=True)
    cv2.imwrite(str(home / "var" / "incidents" / "w1" / "f.jpg"), frame)
    (home / "data" / "models").mkdir(parents=True)
    labels = home / "data" / "models" / "coin_labels.json"
    labels.write_text(json.dumps({"note": "", "frames": [{
        "path": "var/incidents/w1/f.jpg", "window": "w1", "field": "pineapple", "partial": False,
        "coins": [{"box": [260, 140, 340, 220], "kind": "honey", "sure": True, "from": "eye"},
                  {"box": [500, 100, 560, 160], "kind": "haste", "sure": False, "from": "eye"}],
        "not_coins": [{"box": [100, 100, 150, 150], "from": "review"}]}]}))
    return home, school, labels


def test_builds_typed_rows_from_named_looks_and_confirmed_chases(tmp_path):
    b = _builder()
    home, school, labels = _fixture(tmp_path)
    lab_dir = tmp_path / "labeller"
    groups = b.cluster(school, lab_dir, 2)
    assert (lab_dir / "sheets" / "sheet0.jpg").exists()
    ids = list(np.load(lab_dir / "groups.npz")["ids"])
    yellow_group = int(groups[ids.index("a")])
    names = {str(yellow_group): {"kind": "honey", "purity": 1.0},
             str(1 - yellow_group): {"kind": "blue_boost", "purity": 1.0}}
    (lab_dir / "names.json").write_text(json.dumps(names))

    stats = b.build(home, school, labels, tmp_path / "out", "blue", lab_dir)

    rows = [json.loads(line) for line in (tmp_path / "out" / "blue" / "manifest.jsonl").read_text().splitlines()]
    selfs = {r["id"]: r for r in rows if r["source"] == "self"}
    # a: honey look + honey lump; c: blue look, sight only; d: honey look but a
    # Haste verdict (a neighbour paid); e: blue look + stacks; f: blue look +
    # honey lump. b was never reached and nothing confirmed it; g has no crop.
    assert {k: (r["label"], r["confidence"]) for k, r in selfs.items()} == {
        "self-a": ("honey", 1.0), "self-c": ("blue_boost", 0.9), "self-d": ("honey", 0.75),
        "self-e": ("blue_boost", 1.0), "self-f": ("blue_boost", 0.75)}
    assert all((tmp_path / "out" / "blue" / r["wide"]).exists() for r in selfs.values())
    assert stats["dropped_self"] == {"nothing after the chase said a token was there": 1,
                                     "no wide crop (48 px only, before 2026-10-20)": 1}
    # hand rows: the sure coin (the unsure one is left out), the reviewed
    # not-coin, and background points away from every box
    hand = [r for r in rows if r["source"].startswith("hand")]
    assert [r["label"] for r in hand if r["source"] == "hand"] == ["honey"]
    assert sum(r["source"] == "hand_not_coin" for r in hand) == 1
    backgrounds = [r for r in hand if r["source"] == "hand_background"]
    assert len(backgrounds) == b.BACKGROUND_PER_FRAME
    for r in backgrounds:
        assert not b.overlaps(r["box"], [260, 140, 340, 220])
    assert stats["labeller_vs_hand"]["coins_of_named_kinds"] == 1
    # one split per run, and every file written where the row says
    split_by_run = {}
    for r in rows:
        assert split_by_run.setdefault(r["run"], r["split"]) == r["split"]
        assert r["split"] == b.split_of(r["run"])
        img = cv2.imread(str(tmp_path / "out" / "blue" / r["file"]))
        assert img.shape == (b.OUT_PX, b.OUT_PX, 3)


def test_evidence_class_reads_every_collected_verdict_school_writes():
    b = _builder()
    assert b.evidence_class("honey rose 1,200 in 2.0s against 90 expected from the trickle") == "honey"
    assert b.evidence_class("haste 2 -> 3") == "haste"
    assert b.evidence_class("haste absent -> 1") == "haste"
    assert b.evidence_class("the Haste's square refilled: 3s -> 20s left") == "haste"
    assert b.evidence_class("a buff's stacks rose x1 -> x2") == "stacks"
    assert b.evidence_class("a buff appeared on the bar (1 icons with counts -> 2)") == "stacks"
    assert b.evidence_class("pollen rose 9,000 in 2.0s against 100 expected from gathering") == "pollen"
    assert b.evidence_class("the chase never reached it") is None

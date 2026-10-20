"""train_coins --school takes only trustworthy, post-label 'collected' chases."""
import importlib.util
import json
import os
from pathlib import Path

import cv2
import numpy as np

import hivemind

REPO = Path(hivemind.__file__).resolve().parents[2]


def _trainer():
    spec = importlib.util.spec_from_file_location("train_coins", REPO / "scripts" / "train_coins.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_school_crops_keeps_collected_after_the_labels_and_holds_out_late_attempts(tmp_path):
    tc = _trainer()
    (tmp_path / "crops").mkdir()
    rows = [("a", "collected", "haste absent -> 1", 900, True),
            ("b", "collected", "haste absent -> 1", tc.SCHOOL_HELD_FROM, True),
            ("c", "nothing", "reached it", 900, True),
            ("d", "unknown", "the chase never reached it", 900, True),
            ("e", "collected", "haste absent -> 1", 900, False),       # before the labels
            ("f", "collected", "a buff's stacks rose x1 -> x2", 900, True)]   # legacy for honey
    lines = []
    for rid, outcome, evidence, attempt, late in rows:
        path = tmp_path / "crops" / f"{rid}.png"
        cv2.imwrite(str(path), np.full((48, 48, 3), 128, np.uint8))
        when = tc.SCHOOL_AFTER + (3600 if late else -3600)
        os.utime(path, (when, when))
        lines.append(json.dumps({"id": rid, "at": 0.0, "kind": "honey" if rid == "f" else "unknown",
                                 "confidence": 1.0, "x": 1, "y": 1, "outcome": outcome,
                                 "evidence": evidence, "attempt": attempt}))
    (tmp_path / "lessons.jsonl").write_text("\n".join(lines) + "\n")
    train, held, n_wide = tc.school_crops(tmp_path)
    assert len(train) == 1 and len(held) == 1 and n_wide == 0   # no crops-wide/ here
    assert train[0].shape == (tc.coins.CROP_SIZE, tc.coins.CROP_SIZE, 3)

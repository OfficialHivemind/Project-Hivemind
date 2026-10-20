"""scripts/build_sprinkler_dataset.py: the log reading that decides which
frames may hold a sprinkler, and the colour gate that proposes boxes."""
import datetime as dt
import importlib.util
from pathlib import Path

import cv2
import numpy as np

_p = Path(__import__("hivemind").__file__).resolve().parents[2] / "scripts" / "build_sprinkler_dataset.py"
_spec = importlib.util.spec_from_file_location("build_sprinkler_dataset_t", _p)
b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b)


def _epoch(y, mo, d, h, mi, s):
    return dt.datetime(y, mo, d, h, mi, s).timestamp()


LOG = [
    "    23:58:00  gathering with natro_pattern_pepper_as_natro instead of farm_snake",
    "    23:58:40  sprinkler: placed — hotbar slot 1 dimmed",
    "    23:58:42  sprinkler stack: 2 of 2 more stacked on the first by a jump's press",
    "    00:05:00  gathering with natro_pattern_stump_as_natro instead of x",
    "    00:05:30  sprinkler: refused — 'You must be standing in a field'",
    "    00:05:40  sprinkler: already standing — the game: 'Cannot place'",
]


def test_log_events_cross_midnight():
    ev = b.log_events(LOG, _epoch(2026, 10, 13, 0, 6, 0))
    kinds = [k for _, k, _ in ev]
    assert kinds == ["gather", "placed", "gather", "standing"]
    assert ev[0][0] == _epoch(2026, 10, 12, 23, 58, 0)      # the day before
    assert ev[3][0] == _epoch(2026, 10, 13, 0, 5, 40)
    assert ev[2][2] == "natro_pattern_stump_as_natro"


def test_sprinkler_state_per_gather():
    ev = b.log_events(LOG, _epoch(2026, 10, 13, 0, 6, 0))
    assert b.sprinkler_state(_epoch(2026, 10, 12, 23, 57, 0), ev) == "no_gather"
    assert b.sprinkler_state(_epoch(2026, 10, 12, 23, 58, 20), ev) == "not_yet"
    assert b.sprinkler_state(_epoch(2026, 10, 12, 23, 59, 0), ev) == "down"
    # the next gather starts clean: the old field's sprinkler does not count
    assert b.sprinkler_state(_epoch(2026, 10, 13, 0, 5, 10), ev) == "not_yet"
    assert b.sprinkler_state(_epoch(2026, 10, 13, 0, 6, 0), ev) == "down"


def test_sprinklers_in_run_and_split():
    assert b.sprinklers_in_run(LOG) == 3
    assert b.sprinklers_in_run(["    10:00:00  sprinkler: placed"]) is None
    assert b.split_of(1247) == b.split_of(1247)
    shares = [b.split_of(r) for r in range(2000)]
    assert 0.6 < shares.count("train") / 2000 < 0.8


def test_proposals_take_an_upright_tan_post_not_a_slab():
    img = np.zeros((1080, 1920, 3), np.uint8)
    img[:] = (40, 140, 40)                                      # grass
    tan = cv2.cvtColor(np.uint8([[[22, 100, 160]]]), cv2.COLOR_HSV2BGR)[0, 0]
    img[400:560, 900:940] = tan                                 # post: 40 x 160
    img[700:740, 200:400] = tan                                 # slab: 200 x 40
    got = b.proposals(img)
    assert len(got) == 1
    x, y, w, h = got[0]
    assert abs(x - 900) <= 4 and abs(y - 400) <= 4 and h > w
    f = b.features(img, got[0])
    assert f.shape == (756 + 24 + 3,) and np.isfinite(f).all()


def test_logreg_separates():
    rng = np.random.default_rng(0)
    X = np.concatenate([rng.normal(0, 1, (200, 5)), rng.normal(2, 1, (50, 5))])
    y = np.concatenate([np.zeros(200), np.ones(50)])
    s = b.LogReg().fit(X, y).score(X)
    assert s[200:].mean() > 0.8 and s[:200].mean() < 0.2


def test_sequences_split_on_step_reset():
    rows = [{"run": 1, "field": "pepper", "step": k, "epoch": 100.0 + k} for k in (0, 1, 2)]
    rows += [{"run": 1, "field": "pepper", "step": k, "epoch": 110.0 + k} for k in (0, 1)]
    b.sequences(rows)
    assert [r["seq"] for r in rows] == [1, 1, 1, 2, 2]

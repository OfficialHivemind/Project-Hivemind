"""Token detector v2 (vision/tokdet): the trainer's gradients, the ONNX file
the bot runs against the numpy network, decoding, and the switch that keeps
today's detector in charge until the owner flips it."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import cv2
import numpy as np
import pytest

import hivemind
from hivemind.vision import coins, tokdet

SCRIPTS = pathlib.Path(hivemind.__file__).resolve().parents[2] / "scripts"


def _trainer():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("train_tokdet", SCRIPTS / "train_tokdet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("loss_name", ["focal", "bce"])
def test_gradients_match_finite_differences(loss_name):
    tr = _trainer()
    tr.LOSS = loss_name
    rng = np.random.default_rng(3)
    params = {k: v.astype(np.float64) for k, v in tokdet.fresh(seed=3).items()}
    x = rng.random((2, 32, 32, 3))
    row = {"partial": False, "not_coins": [],
           "coins": [[10.0, 12.0, 20.0, 4, True], [20.0, 18.0, 60.0, -1, True]]}
    tg = [tr.targets(row, 32, 32, False, (0, 0), 1.0)] * 2

    def loss():
        return tr.batch_loss(tokdet.forward(params, x), tg)[0]

    keep: dict = {}
    _l, douts = tr.batch_loss(tokdet.forward(params, x, keep), tg)
    grads = tr.backward(params, keep, x.shape, douts)
    for name, idx in (("c1.w", (5, 3)), ("c4.w", (100, 7)), ("p3h.w", (40, 2)),
                      ("p3.w", (3, 0)), ("p3.w", (10, 8)), ("p4.b", (3,)), ("c7.b", (5,))):
        old = params[name][idx]
        params[name][idx] = old + 1e-5
        up = loss()
        params[name][idx] = old - 1e-5
        down = loss()
        params[name][idx] = old
        num = (up - down) / 2e-5
        assert abs(num - grads[name][idx]) <= 1e-4 + 1e-3 * abs(num), (name, num, grads[name][idx])


def test_onnx_runs_the_same_network(tmp_path):
    params = tokdet.fresh(seed=1)
    x = np.random.default_rng(0).random((1, tokdet.IN_H, tokdet.IN_W, 3)).astype(np.float32)
    want = tokdet.forward(params, x)
    path = tmp_path / "t.onnx"
    path.write_bytes(tokdet.to_onnx(params))
    net = tokdet.load(path)
    net.setInput(np.ascontiguousarray(x.transpose(0, 3, 1, 2)))
    for lvl, got in zip(("p3", "p4"), net.forward(["p3", "p4"])):
        assert np.abs(got[0].transpose(1, 2, 0) - want[lvl][0]).max() < 1e-4


def test_decode_finds_a_planted_coin_in_frame_pixels():
    c = tokdet.EXTRA + len(tokdet.CLASSES)
    outs = {"p3": np.full((40, 80, c), -9.0, np.float32),
            "p4": np.full((20, 40, c), -9.0, np.float32)}
    cell = outs["p3"][10, 20]
    cell[0] = 3.0                                   # p 0.95
    cell[1:3] = 0.0                                 # centre of the cell
    cell[3] = np.log(32 / 8)                        # side 32 input px
    cell[tokdet.EXTRA + tokdet.CLASSES.index("honey")] = 5.0
    found = tokdet.decode(outs)
    assert len(found) == 1
    cx, cy, side, p, kind, _q = found[0]
    assert (cx, cy, round(side), kind) == (164.0, 84.0, 32, "honey") and p > 0.9
    frame = np.zeros((1080, 1920, 3), np.uint8)
    _img, x0, y0, sx, sy = tokdet.to_input(frame)
    (fx, fy, fside, logit, _s1, fkind), = tokdet.to_frame(found, x0, y0, sx, sy)
    assert abs(fx - (x0 + 164 / sx)) < 1e-6 and fkind == "honey"
    assert abs(coins.confidence_of(logit) - p) < 1e-6


def test_off_or_missing_model_means_todays_detector(monkeypatch, tmp_path):
    tokdet.switch(False)
    assert tokdet.look(np.zeros((1080, 1920, 3), np.uint8)) is None
    monkeypatch.setattr(tokdet, "MODEL", tmp_path / "nope.onnx")
    monkeypatch.setattr(tokdet, "_error", "")
    monkeypatch.setattr(tokdet, "_local", type(tokdet._local)())
    tokdet.switch(True)
    try:
        assert tokdet.look(np.zeros((1080, 1920, 3), np.uint8)) is None
        assert "nope.onnx" in tokdet.error()
    finally:
        tokdet.switch(False)


def test_shipped_model_loads_and_runs():
    if not tokdet.MODEL.exists():
        return
    net = tokdet.load()
    frame = np.full((1080, 1920, 3), 90, np.uint8)
    cv2.circle(frame, (900, 500), 40, (0, 200, 255), -1)
    out = tokdet.run(net, frame)
    assert all(len(d) == 6 and d[5] in tokdet.CLASSES + ("unknown",) for d in out)


def test_detect_uses_v2s_coins_and_kinds_when_it_answers(monkeypatch):
    from hivemind.vision import tokens
    frame = np.zeros((1080, 1920, 3), np.uint8)
    coin = (900.0, 500.0, 80.0, 0.9 * coins.LOGIT_FULL, 0.0, "blue_boost")
    monkeypatch.setattr(tokdet, "look", lambda f: [coin])
    (s,) = tokens.detect(frame)
    assert (s.x, s.y, s.kind, s.confidence) == (900, 500, "blue_boost", 0.9)
    monkeypatch.setattr(tokdet, "look", lambda f: None)
    monkeypatch.setattr(tokens.coindet, "look", lambda f: [coin[:5]])
    monkeypatch.setattr(tokens.coins, "kinds_of", lambda f, m: ["unknown"] * len(m))
    (s,) = tokens.detect(frame)
    assert s.kind == "unknown"

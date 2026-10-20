"""The typed token head: its gradients with several outputs, its file, and
the switch that keeps today's honey head in charge until the owner flips it."""
from __future__ import annotations

import importlib.util
import pathlib

import numpy as np

from hivemind.vision import coinnet, coins, tokentypes

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _trainer():
    spec = importlib.util.spec_from_file_location("train_coins", ROOT / "scripts/train_coins.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_softmax_gradients_match_finite_differences():
    trainer = _trainer()
    rng = np.random.default_rng(2)
    params = {k: v.astype(np.float64) for k, v in
              coinnet.fresh(size=16, chans=(3, 4, 5, 6), hidden=7, seed=2, outputs=4).items()}
    x = rng.random((3, 16, 16, 3))
    y = np.array([0, 3, 1])

    def loss():
        z = coinnet.forward(params, x)
        z = z - z.max(1, keepdims=True)
        return -(z[np.arange(3), y] - np.log(np.exp(z).sum(1))).sum()

    cache: list = []
    z = coinnet.forward(params, x, keep=cache)
    assert z.shape == (3, 4)
    p = np.exp(z - z.max(1, keepdims=True))
    p /= p.sum(1, keepdims=True)
    p[np.arange(3), y] -= 1
    grads = trainer.backward(params, cache, p)
    worst = 0.0
    for name, value in params.items():
        flat = value.ravel()
        for j in rng.choice(flat.size, size=min(5, flat.size), replace=False):
            old = flat[j]
            flat[j] = old + 1e-5
            up = loss()
            flat[j] = old - 1e-5
            down = loss()
            flat[j] = old
            numeric = (up - down) / 2e-5
            analytic = np.asarray(grads[name]).ravel()[j]
            worst = max(worst, abs(numeric - analytic) / max(1e-8, abs(numeric) + abs(analytic)))
    assert worst < 1e-4, f"worst relative gradient error {worst:.2e}"


def test_a_saved_model_loads_and_names_or_says_unknown(tmp_path):
    classes = ["background", "haste", "honey", "other"]
    params = coinnet.fresh(size=32, seed=0, outputs=4)
    params["w4"][:] = 0
    params["b4"][:] = [0, 0, 5, 0]                     # always "honey", p ~0.94
    tokentypes.Model(params, classes, 0.5).save(tmp_path / "t.npz")
    m = tokentypes.Model.load(tmp_path / "t.npz")
    batch = np.random.default_rng(0).random((2, 32, 32, 3)).astype(np.float32)
    assert m.classes == classes and m.name(batch) == ["honey", "honey"]
    m.tau = 0.99
    assert m.name(batch) == ["unknown", "unknown"]
    params["b4"][:] = [5, 0, 0, 0]                     # background -> no claim
    assert tokentypes.Model(params, classes, 0.0).name(batch) == ["unknown", "unknown"]


def test_switched_off_the_honey_head_names_and_on_the_typed_head_does(tmp_path, monkeypatch):
    m = coins.model()
    if m is None:
        return
    frame = np.random.default_rng(0).integers(0, 255, (1080, 1920, 3), np.uint8)
    found = [(900.0, 500.0, 100.0)]
    classes = ["background", "haste", "other"]
    params = coinnet.fresh(size=32, seed=0, outputs=3)
    params["w4"][:] = 0
    params["b4"][:] = [0, 9, 0]
    tokentypes.Model(params, classes, 0.5).save(tmp_path / "t.npz")
    monkeypatch.setattr(tokentypes, "MODEL", tmp_path / "t.npz")
    monkeypatch.setattr(tokentypes, "_model", None)
    monkeypatch.setattr(tokentypes, "_error", "")
    tokentypes.switch(False)
    assert coins.kinds_of(frame, found) in (["honey"], ["unknown"])
    try:
        tokentypes.switch(True)
        assert coins.kinds_of(frame, found) == ["haste"]
    finally:
        tokentypes.switch(False)

"""coinnet through cv2.dnn: the same answers as the numpy forward pass, for
every model shape the bot runs (the coin and honey heads, the typed head),
and a fresh net whenever a trainer swaps the weights."""
from __future__ import annotations

import numpy as np
import pytest

from hivemind.vision import coinnet

cv2 = pytest.importorskip("cv2")


def _x(n=7, size=32, seed=0):
    return np.random.default_rng(seed).random((n, size, size, 3)).astype(np.float32)


@pytest.mark.parametrize("outputs", [1, 12])
def test_dnn_gives_the_numpy_answer(outputs):
    params = coinnet.fresh(seed=4, outputs=outputs)
    x = _x()
    got = coinnet._dnn_logits(params, x)
    assert got is not None, coinnet.dnn_error()
    want = coinnet.forward(params, x)
    assert got.shape == want.shape
    assert np.allclose(got, want, atol=1e-4), np.abs(got - want).max()
    assert np.allclose(coinnet.logits(params, x), want, atol=1e-4)


def test_new_weights_get_a_new_net():
    """A trainer assigns new arrays each step (params[k] = ...): the cached
    net must not answer with the old ones."""
    params = coinnet.fresh(seed=5)
    x = _x()
    before = coinnet.logits(params, x)
    params["b4"] = params["b4"] + np.float32(3.0)
    after = coinnet.logits(params, x)
    assert np.allclose(after, before + 3.0, atol=1e-4)


def test_numpy_answers_what_dnn_does_not_take(monkeypatch):
    """float64 weights (the gradient tests) and the switch keep numpy."""
    p64 = {k: v.astype(np.float64) for k, v in coinnet.fresh(seed=6).items()}
    x = _x(3).astype(np.float64)
    assert coinnet._dnn_logits(p64, x) is None
    assert coinnet.logits(p64, x).dtype == np.float64
    monkeypatch.setattr(coinnet, "USE_DNN", False)
    called = []
    monkeypatch.setattr(coinnet, "_dnn_logits", lambda *a: called.append(1))
    coinnet.logits(coinnet.fresh(seed=6), _x(2))
    assert not called


def test_threads_looking_at_once_each_get_the_right_answer():
    """The boxes worker and the chaser look at the same time: one net per
    thread and model, so no thread reads another's input or answer."""
    import threading
    models = [coinnet.fresh(seed=8), coinnet.fresh(seed=9, outputs=12)]
    wrong = []

    def look(seed):
        rng = np.random.default_rng(seed)
        for _ in range(30):
            p = models[rng.integers(2)]
            x = _x(int(rng.integers(1, 40)), seed=int(rng.integers(1000)))
            if not np.allclose(coinnet.logits(p, x), coinnet.forward(p, x), atol=1e-4):
                wrong.append(seed)
    threads = [threading.Thread(target=look, args=(s,)) for s in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not wrong and not coinnet.dnn_error()


def test_a_crop_size_the_net_was_not_built_for_falls_back():
    params = coinnet.fresh(seed=7)                       # 32 px crops
    assert coinnet._dnn_logits(params, _x(2, size=16)) is None

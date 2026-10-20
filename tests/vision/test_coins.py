"""The coin detector's machinery: the network's arithmetic, the model file,
the merge, the confidence scale and the world box.

What it FINDS on real frames is tests/vision/test_tokens.py; these pin the
parts that must hold on any machine, with or without the incident frames.
"""
from __future__ import annotations

import importlib.util
import pathlib

import numpy as np
import pytest

from hivemind.vision import coinnet, coins

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _trainer():
    spec = importlib.util.spec_from_file_location("train_coins", ROOT / "scripts/train_coins.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- the network --------------------------------------------------------------
def test_the_trainers_gradients_match_finite_differences():
    """The backward pass is hand-written, so it is checked against the
    forward pass the bot runs, in float64 on a small network."""
    trainer = _trainer()
    rng = np.random.default_rng(1)
    params = {k: v.astype(np.float64)
              for k, v in coinnet.fresh(size=16, chans=(3, 4, 5, 6), hidden=7, seed=1).items()}
    x = rng.random((3, 16, 16, 3))
    y = np.array([1.0, 0.0, 1.0])

    def loss():
        p = 1 / (1 + np.exp(-coinnet.forward(params, x)))
        return -(y * np.log(p) + (1 - y) * np.log(1 - p)).sum()

    cache: list = []
    p = 1 / (1 + np.exp(-coinnet.forward(params, x, keep=cache)))
    grads = trainer.backward(params, cache, p - y)
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


def test_logits_in_batches_are_the_same_as_in_one_go():
    params = coinnet.fresh(seed=3)
    x = np.random.default_rng(3).random((10, 32, 32, 3)).astype(np.float32)
    whole = coinnet.forward(params, x)
    assert np.allclose(coinnet.logits(params, x, batch=3), whole, atol=1e-5)
    assert coinnet.logits(params, x[:0]).shape == (0,)


# ---- the model file -------------------------------------------------------------
def _model(seed=5):
    rng = np.random.default_rng(seed)
    return coins.Model(rng.standard_normal(324).astype(np.float32) * 0.01, -3.0,
                       coinnet.fresh(seed=seed))


def test_a_model_survives_the_round_trip(tmp_path):
    m = _model()
    path = tmp_path / "coins.npz"
    m.save(path)
    back = coins.Model.load(path)
    assert np.array_equal(back.stage1, m.stage1)
    for k in coinnet.PARAM_NAMES:
        assert np.array_equal(back.params[k], m.params[k])


def test_a_model_trained_for_another_geometry_is_refused(tmp_path):
    m = _model()
    path = tmp_path / "coins.npz"
    m.save(path)
    with np.load(path) as z:
        body = dict(z)
    body["hog_window"] = np.int64(48)
    np.savez(path, **body)
    with pytest.raises(ValueError):
        coins.Model.load(path)


def test_the_shipped_model_loads():
    m = coins.Model.load(coins.MODEL)
    assert m.stage1.shape == (325,)            # 324 HOG weights and the bias


# ---- one coin, one sighting -------------------------------------------------------
def test_candidates_on_one_coin_merge_and_two_coins_do_not():
    one = [(500, 500, 80, 6.0), (520, 510, 100, 4.0), (495, 480, 60, 5.0)]
    assert len(coins.merge(one)) == 1
    assert coins.merge(one)[0][3] == 6.0, "the strongest is the one kept"
    two = [(500, 500, 80, 6.0), (700, 500, 80, 5.0)]
    assert len(coins.merge(two)) == 2


# ---- the confidence scale ------------------------------------------------------------
def test_confidence_is_the_log_odds_scaled_to_one():
    def logit(p):
        return float(np.log(p / (1 - p)))
    assert coins.confidence_of(logit(0.99)) == pytest.approx(0.5, abs=0.01)
    assert coins.confidence_of(logit(0.9999)) == pytest.approx(1.0, abs=1e-6)
    assert coins.confidence_of(-5.0) == 0.0
    assert coins.confidence_of(50.0) == 1.0


# ---- the interface is never looked at --------------------------------------------------
def test_no_candidate_is_reported_outside_the_world_box():
    """The hotbar, the HUD pills and the reward feed are excluded by where
    they are, which is exact. A stage 1 that fires everywhere shows it."""
    everywhere = coins.Model(np.zeros(324, np.float32), 10.0, coinnet.fresh())
    frame = np.random.default_rng(0).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
    work = coins.work_image(frame)
    found = coins.candidates(work, everywhere, 1920, 1080)
    assert found, "a stage 1 that scores everything must return candidates"
    x0, y0, x1, y1 = coins.world_box(1920, 1080)
    assert all(x0 <= cx <= x1 and y0 <= cy <= y1 for cx, cy, _, _ in found)


def test_extra_candidates_are_scored_by_the_network_too():
    """The union column (train_coindet eval): a stage 1 that finds nothing
    still scores the candidates another finder hands in."""
    nowhere = coins.Model(np.zeros(324, np.float32), -1e6, coinnet.fresh())
    frame = np.zeros((1080, 1920, 3), np.uint8)
    assert coins.look(frame, nowhere) == []
    got = coins.look(frame, nowhere, extra=[(900.0, 500.0, 110.0, 0.0)])
    assert len(got) == 1 and got[0][:2] == (900.0, 500.0)
    assert got[0][2] == 110.0 / coins.WINDOW_TO_COIN


def test_no_model_means_no_sightings_not_an_error():
    coins.use(None)
    try:
        coins._model_error = "no coin model (test)"
        assert coins.look(np.zeros((1080, 1920, 3), np.uint8)) == []
    finally:
        coins.use(None)          # the next `model()` loads the real file again


# ---- the honey head ------------------------------------------------------------------
def _head(bias):
    head = coinnet.fresh(seed=9)
    for k in head:
        head[k] = np.zeros_like(head[k])
    head["b4"] = np.array([bias], np.float32)       # every crop: this logit
    return head


def test_the_honey_head_survives_the_round_trip(tmp_path):
    m = _model()
    m.honey, m.honey_p = _head(3.0), 0.9
    path = tmp_path / "coins.npz"
    m.save(path)
    back = coins.Model.load(path)
    assert back.honey is not None and back.honey_p == pytest.approx(0.9)
    assert np.array_equal(back.honey["b4"], m.honey["b4"])
    plain = _model()
    plain.save(tmp_path / "plain.npz")
    assert coins.Model.load(tmp_path / "plain.npz").honey is None


def test_honey_is_named_only_above_the_heads_own_threshold():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    found = [(900.0, 600.0, 80.0, 7.0, 3.0)]
    sure, unsure, none = _model(), _model(), _model()
    sure.honey, sure.honey_p = _head(4.0), 0.9          # p 0.982
    unsure.honey, unsure.honey_p = _head(1.0), 0.9      # p 0.731
    assert coins.kinds_of(frame, found, sure) == ["honey"]
    assert coins.kinds_of(frame, found, unsure) == ["unknown"]
    assert coins.kinds_of(frame, found, none) == ["unknown"], "no head, no name"


def test_a_kind_the_detector_named_survives_the_colour_table():
    from hivemind.vision import tokens
    table = tokens.load_kinds(ROOT / "data/knowledge/tokens.yaml")
    assert table.classify(tokens.Sighting(x=1, y=1, kind="honey")) == "honey"
    assert table.classify(tokens.Sighting(x=1, y=1)) == "unknown"

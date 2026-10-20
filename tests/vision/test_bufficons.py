"""The buff-icon reader: its file, the rule reads (percent, stacks), the
drain line by rule, the switch that keeps it off, and the trainer's monotone
fit."""
from __future__ import annotations

import importlib.util
import pathlib

import numpy as np

import hivemind
from hivemind.vision import bufficons, buffs, coinnet
from hivemind.datapaths import data


def _script(name):
    # through the package, not __file__: the deploy gate runs tests from the live tree
    root = pathlib.Path(hivemind.__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(name, root / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_saved_model_round_trips_and_reads_a_bar(tmp_path):
    classes = ["background", "melody", "focus"]
    params = coinnet.fresh(size=bufficons.SIZE, seed=0, outputs=len(classes) + 1)
    model = bufficons.Model(params, classes, tau=0.0, rates={"melody": 1.26})
    path = tmp_path / "m.npz"
    model.save(path)
    back = bufficons.Model.load(path)
    assert back.classes == classes and back.rates == {"melody": 1.26}
    frame = np.random.default_rng(0).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
    bar = back.read(frame)
    assert len(bar.icons) <= buffs.MAX_SLOTS
    for i in bar.icons:
        assert i.name in ("melody", "focus") and 0.0 <= i.left <= 1.0
        assert (i.seconds is None) == (i.name != "melody")


def test_the_rule_reads():
    icon = bufficons.Icon
    bar = bufficons.Bar(icons=(icon(0, "melody", 0.9, 0.25, 7.5, None),
                               icon(1, "focus", 0.9, 0.8, 16.0, 7),
                               icon(2, "melody", 0.9, 0.5, 15.0, None)))
    assert bar.percent("melody") == 50.0           # the fuller one
    assert bar.stacks("focus") == 7
    assert bar.stacks("melody") == 1               # up, no count drawn
    assert bar.percent("baby_love") is None and bar.stacks("baby_love") is None
    assert "focus x7 80%" in bar.describe()


def test_off_by_default_and_a_missing_file_is_none(monkeypatch, tmp_path):
    frame = np.zeros((1080, 1920, 3), np.uint8)
    bufficons.switch(False)
    assert bufficons.read(frame) is None
    monkeypatch.setattr(bufficons, "MODEL", tmp_path / "missing.npz")
    monkeypatch.setattr(bufficons, "_model", None)
    monkeypatch.setattr(bufficons, "_error", "")
    bufficons.switch(True)
    try:
        assert bufficons.read(frame) is None
        assert "missing.npz" in bufficons.error()
    finally:
        bufficons.switch(False)


def test_an_empty_melody_is_dropped_and_a_read_at_the_mask_top_is_at_least():
    fill = np.array([250, 250, 250], np.float32)
    mask = np.zeros((38, 38), bool)
    mask[11:37, 1:30] = True                          # the rule sees rows 11-36 only

    class Fixed(bufficons.Model):
        def predict(self, crops):                     # every slot: this class, sure
            p = np.zeros((len(crops), 2), np.float32)
            p[:, 1] = 1.0
            return p, np.full(len(crops), 0.5, np.float32)

    def one(name, full):
        m = Fixed(coinnet.fresh(size=bufficons.SIZE, outputs=3), ["background", name], 0.5,
                  {}, {name: fill}, {name: mask})
        frame = np.zeros((1080, 1920, 3), np.uint8)
        if full:
            frame[buffs.BAR_TOP:buffs.BAR_BOTTOM, :38 * 12] = 250
        return m.read(frame)

    assert one("melody", full=False).icons == ()      # scenery with no white: not up
    assert len(one("focus", full=False).icons) == 12  # only Melody is dropped
    full = one("baby_love", full=True)
    i = full.icons[0]
    assert i.at_least and abs(i.left - 27 / 38) < 1e-9 and ">=71%" in full.describe()


def test_a_read_that_raises_is_none_not_a_raise(monkeypatch):
    # inside run_farm's movespeed_factor: a raise would zero Haste's factor
    class Broken:
        def read(self, frame):
            raise ValueError("shapes")
    monkeypatch.setattr(bufficons, "_model", Broken())
    monkeypatch.setattr(bufficons, "_error", "")
    bufficons.switch(True)
    try:
        assert bufficons.read(np.zeros((1080, 1920, 3), np.uint8)) is None
        assert "shapes" in bufficons.error()
    finally:
        bufficons.switch(False)


def test_the_shipped_model_loads():
    m = bufficons.Model.load(data("models", "bufficons.npz"))
    assert m.classes[0] == "background"
    assert {"haste", "melody", "baby_love", "focus"} <= set(m.classes)
    p, left = m.predict(np.zeros((2, 38, 38, 3), np.uint8))
    assert p.shape == (2, len(m.classes)) and left.shape == (2,)


def test_isotonic_fit_never_falls():
    bd = _script("bufficons_data")
    fit = bd.isotonic([3, 5, 4, 4, 9, 8, 10])
    assert all(b >= a - 1e-9 for a, b in zip(fit, fit[1:]))
    assert abs(sum(fit) - sum([3, 5, 4, 4, 9, 8, 10])) < 1e-9


def test_the_drain_line_by_rule_reads_the_fill_left():
    fill = np.array([240, 220, 130], np.float32)
    mask = np.zeros((38, 38), bool)
    mask[:, 1:20] = True
    icon = np.zeros((38, 38, 3), np.uint8)            # drained: the world shows (black)
    icon[28:, :] = fill.astype(np.uint8)              # the last 10 rows still full
    assert bufficons.fill_line(icon, fill, mask) == 28
    m = bufficons.Model(coinnet.fresh(size=bufficons.SIZE, outputs=3), ["background", "x"], 0.5,
                        {}, {"x": fill}, {"x": mask})
    assert abs(m.left_of(icon, "x", 0.9) - 10 / 38) < 1e-9
    assert m.left_of(icon, "no_mask", 0.9) == 0.9     # the head's guess is the fallback

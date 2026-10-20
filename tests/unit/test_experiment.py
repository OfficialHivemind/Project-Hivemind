"""brain/experiment: try each value, then keep trying the one that measures best."""
import random

from hivemind.brain.experiment import Experiment


def test_it_tries_every_value_then_settles_on_the_best(tmp_path):
    exp = Experiment(tmp_path / "e.json", "press", [0.25, 0.35, 0.45], rng=random.Random(1))
    truth = {0.25: 0.2, 0.35: 0.9, 0.45: 0.5}
    world = random.Random(2)
    picks = []
    for _ in range(300):
        v = exp.pick()
        picks.append(v)
        exp.learn(v, 1.0 if world.random() < truth[v] else 0.0)
    assert exp.best.value == 0.35
    assert picks[-100:].count(0.35) > 70          # it keeps trying the winner
    assert "learned: 0.35" in exp.describe()
    again = Experiment(tmp_path / "e.json", "press", [0.25, 0.35, 0.45])
    assert abs(again.tries - exp.tries) < 0.01    # remembered across sessions


def test_it_follows_a_change_in_what_works(tmp_path):
    # the hive grows: what was best stops being best, and the old evidence fades
    exp = Experiment(tmp_path / "e.json", "x", [1, 2], rng=random.Random(3))
    world = random.Random(4)
    for _ in range(200):
        v = exp.pick()
        exp.learn(v, 1.0 if world.random() < (0.8 if v == 1 else 0.2) else 0.0)
    assert exp.best.value == 1
    for _ in range(300):
        v = exp.pick()
        exp.learn(v, 1.0 if world.random() < (0.2 if v == 1 else 0.8) else 0.0)
    assert exp.best.value == 2


def test_a_measured_number_is_scaled(tmp_path):
    exp = Experiment(tmp_path / "e.json", "y", [1])
    exp.learn(1, 30_000, scale=60_000)
    assert abs(exp.arms[0].mean - 0.5) < 1e-9

"""The watcher: it observes, it never decides, and it never raises."""
from __future__ import annotations

import numpy as np

from hivemind.brain.supervisor import Supervisor


class FakeModel:
    def __init__(self, text="the player is standing at a shop counter", up=True):
        self.text, self.up, self.asks = text, up, 0

    def available(self):
        return self.up

    def ask(self, png, question):
        self.asks += 1
        return type("A", (), {"text": self.text})()


def frames():
    return np.full((64, 96, 3), 50, np.uint8)


def test_it_reports_what_it_sees_as_a_thought():
    seen = []
    model = FakeModel()
    sup = Supervisor(frames, model, emit=seen.append)
    answer = sup.diagnose_stall("120s flat")
    assert "shop counter" in answer
    assert seen and getattr(seen[0], "topic", "") == "watching"
    assert "120s flat" in getattr(seen[0], "detail", "")


def test_a_model_that_is_down_is_silent_not_fatal():
    sup = Supervisor(frames, FakeModel(up=False), emit=lambda e: None)
    assert sup.diagnose_stall("x") is None


def test_a_model_that_explodes_does_not_stop_the_run():
    class Boom(FakeModel):
        def ask(self, png, question):
            raise RuntimeError("ollama died")
    seen = []
    sup = Supervisor(frames, Boom(), emit=seen.append)
    assert sup.look("where", "checking") is None
    assert any("could not look" in getattr(e, "message", "") for e in seen)


def test_repeated_reasons_are_rate_limited():
    """A stall lasting a minute must not ask the same question twenty times."""
    model = FakeModel()
    clock = [0.0]
    sup = Supervisor(frames, model, emit=lambda e: None,
                     clock=lambda: clock[0], min_gap=20.0)
    assert sup.diagnose_stall("same") is not None
    clock[0] = 5.0
    assert sup.diagnose_stall("same") is None
    assert sup.skipped == 1
    clock[0] = 30.0
    assert sup.diagnose_stall("same") is not None
    assert model.asks == 2


def test_a_different_reason_is_always_worth_asking():
    model = FakeModel()
    sup = Supervisor(frames, model, emit=lambda e: None, clock=lambda: 0.0)
    sup.diagnose_stall("first")
    sup.check_danger("something else entirely")
    assert model.asks == 2


def test_no_frame_means_no_question():
    model = FakeModel()
    sup = Supervisor(lambda: None, model, emit=lambda e: None)
    assert sup.diagnose_lost("x") is None
    assert model.asks == 0


def test_an_empty_answer_is_not_reported_as_an_observation():
    seen = []
    sup = Supervisor(frames, FakeModel(text="   "), emit=seen.append)
    assert sup.diagnose_stall("x") is None
    assert not seen

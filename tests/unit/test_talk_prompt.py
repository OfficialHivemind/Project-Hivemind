"""act/shoplook.talk_prompt: a giver's prompt raised one panel-height (the
Bucko Bee, 2026-10-12 attempt-832) is read off the raised box."""
import numpy as np

from hivemind.act import shoplook


class FakeTesseract:
    """Answers per box: the raised box (y0 8) reads the prompt, the normal
    box only its last line -- as attempt-832's frame did."""

    def __init__(self, raised_says, normal_says):
        self.says = {8: raised_says, 58: normal_says}
        self.calls = 0

    def __call__(self, args, input=None, **kw):
        self.calls += 1
        y0 = shoplook.PROMPT_BOX[1] if self.calls == 1 else shoplook.RAISED_PROMPT_BOX[1]
        return type("Out", (), {"stdout": self.says[y0].encode(), "returncode": 0})()


def test_raised_prompt_found_after_the_normal_box():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    run = FakeTesseract("E Talk to Gifted Bucko\nBee", "ad")
    assert shoplook.talk_prompt(frame, run) == "talk to gifted bucko bee"


def test_hud_alone_is_not_a_talk_prompt():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    run = FakeTesseract("Honey 337,3 Pollen 3,232/5,045,625", "")
    assert shoplook.talk_prompt(frame, run) == ""

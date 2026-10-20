"""B8: the errand choice reaches the think pane and the feed in plain words."""
import inspect

from hivemind.brain import report
from hivemind.brain.value import Scored
from hivemind.telemetry.events import Considered


def test_errand_considered_says_pay_and_cost():
    sent = []
    rows = [Scored("wealth_clock", q=900_000.0, seconds=40, p=0.9, v=1_200_000.0),
            Scored("glue_dispenser", q=None, seconds=60, p=0.8, v=None)]
    report.Reporter(sent.append).errand(rows, "wealth_clock", rate=2_000.0, picker="plan")
    (ev,) = sent
    assert isinstance(ev, Considered)
    assert ev.question == "Which errand next?"
    assert ev.chosen == "wealth clock"
    assert [o.label for o in ev.options] == ["wealth clock", "glue dispenser"]
    assert "pays about 1.08M honey" in ev.rationale
    assert "0.08M of gathering" in ev.rationale
    assert "best-paying order" in ev.rationale
    assert "no measured price" in ev.options[1].why


def test_no_choice_sends_nothing():
    sent = []
    report.Reporter(sent.append).errand([], None)
    assert sent == []


def test_wired_into_the_errand_choice_and_the_feed():
    import hivemind
    from pathlib import Path
    from hivemind.gui import simple
    root = Path(hivemind.__file__).resolve().parents[2]
    src = (root / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert "reporter.errand(rows or [], name, gathering_rate(), picker)" in src
    assert "next errand:" in inspect.getsource(simple)


# ---- B8 fix: the errand card must not pass for the FIELD choice -----------
# The held-back review: stream/extras, stream/voice and gui/stream read every
# Considered as the field ranking, so the overlay said "Next stop: Wealth
# Clock - the best of N fields" and the voice re-announced the field.
def _errand_event():
    sent = []
    rows = [Scored("wealth_clock", q=900_000.0, seconds=40, p=0.9, v=1_200_000.0)]
    report.Reporter(sent.append).errand(rows, "wealth_clock", rate=2_000.0)
    return sent[0]


def test_errand_card_is_tagged_and_survives_the_wire():
    from hivemind.telemetry.events import from_json
    ev = _errand_event()
    assert ev.topic == "errand"
    assert from_json(ev.to_json()).topic == "errand"
    assert Considered().topic == ""          # the field choice stays untagged


def test_overlay_commentary_ignores_the_errand():
    from hivemind.stream.extras import Commentary
    c = Commentary(clock=lambda: 0.0)
    c.saw(_errand_event())
    assert c.line == "" and c._rank == ""


def test_voice_does_not_announce_the_errand_as_the_next_field():
    import random
    from hivemind.stream import voice
    a = voice.Announcer(get={"stream.voice": True}.get, clock=lambda: 0.0,
                        rng=random.Random(1), chat_live=lambda: False)
    a.hear(_errand_event())
    assert a.waiting == [] and a._field == ""


def test_stream_window_keeps_the_field_ranking():
    from types import SimpleNamespace
    from hivemind.gui.stream import StreamWindow
    me = SimpleNamespace(_ranking=["field"], _chosen="pine_tree")
    StreamWindow._handle(me, _errand_event(), False)
    assert me._ranking == ["field"] and me._chosen == "pine_tree"


def test_simple_feed_names_the_errand():
    from types import SimpleNamespace
    from hivemind.gui.simple import SimplePage
    fed = []
    me = SimpleNamespace(_feed=fed.append)
    SimplePage._handle(me, _errand_event())
    assert fed[0].text.startswith("next errand: wealth clock — pays about 1.08M")

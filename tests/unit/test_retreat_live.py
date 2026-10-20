"""RETREAT_LIVE (brain/alive): the own health bar saying leave ends the gather
through the farm loop's leave-by exit, so the normal walk home and convert
follow. Once a gather, never under WORTH_PROTECTING, and nothing but the
look-only line when the flag is off."""
from hivemind.brain import alive
from hivemind.brain.decide import WORTH_PROTECTING
from tests.unit.test_alive import Frames, watcher
from tests.unit.test_farm import FakeClock, FakeHud, build, honey, pollen


def bar(monkeypatch, live, bag, hp, retreat):
    from hivemind.vision import hurt
    monkeypatch.setattr(alive, "RETREAT_LIVE", live)
    monkeypatch.setattr(hurt, "own_health", lambda f: f.hp)
    frames, logs = Frames(), []
    w, clock, _ = watcher([bag] * len(hp), frame=frames, emit=logs.append)
    w.retreat = retreat
    for h in hp:
        frames.hp = h
        w.check()
        clock.tick(1)
    return " ".join(getattr(e, "message", "") for e in logs)


def test_live_hands_the_line_to_the_farm_and_says_no_would(monkeypatch):
    asked = []
    said = bar(monkeypatch, True, 1_045_384, [0.9, 0.4, 0.2],
               lambda why: asked.append(why) or True)
    assert asked == ["retreat: health 0.40 then 0.20 with 1,045,384 in the bag "
                     "-- ending the gather to bank it"]
    assert "retreat would:" not in said


def test_off_only_says_would_and_asks_nothing(monkeypatch):
    asked = []
    said = bar(monkeypatch, False, 1_045_384, [0.9, 0.4, 0.2], asked.append)
    assert asked == [] and "retreat would:" in said


def test_a_refused_live_retreat_still_says_the_would_line(monkeypatch):
    """No gather to end (the farm says False): the signal stays logged, so
    tools/death_predictors keeps scoring it (review of rp/retreat-live)."""
    said = bar(monkeypatch, True, 1_045_384, [0.9, 0.4, 0.2], lambda why: False)
    assert "retreat would:" in said and "refused" in said


def test_a_small_bag_never_retreats(monkeypatch):
    asked = []
    bar(monkeypatch, True, WORTH_PROTECTING - 1, [0.9, 0.4, 0.2, 0.1], asked.append)
    assert asked == []


def test_the_gather_ends_through_the_leave_by_exit_once():
    """A retreat mid-gather ends it at the next pass top, the walk home and
    convert follow, and a second ask in the same gather is refused."""
    clock = FakeClock()
    hud = FakeHud(clock, [pollen(0)] + [pollen(100_000 * i) for i in range(1, 6)]
                  + [pollen(0)], honey_script=[honey(1), honey(2)])
    loop, _, routes, _ = build(clock, hud)
    assert loop.retreat("not gathering") is False          # outside a gather
    answers = []

    def on_run(name, n):
        if name == "collect_around":
            answers.append(loop.retreat("retreat: health 0.40 then 0.20"))
    routes.on_run = on_run

    report = loop.run(cycles=1)
    cycle = report.cycles[0]
    assert cycle.gather_ended == "retreat: health 0.40 then 0.20"
    assert routes.ran.count("collect_around") == 1, routes.ran
    assert cycle.converted, cycle.convert_note             # walked home and banked
    assert answers == [True] and report.retreats == 1
    assert "1 retreats" in report.describe()
    assert loop.retreat("again") is False                  # gather over

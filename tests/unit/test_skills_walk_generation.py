"""brain/skills WALK_GENERATION: a walkspeed change resets failing routes' windows, keeps landing ones."""
from types import SimpleNamespace

from hivemind.brain import skills
from hivemind.brain.skills import SkillBook, steps_signature

STEPS = [{"op": "walk", "keys": "sa", "studs": 179.0}]


def _book(route, kind, outcomes, old_sig):
    book = SkillBook(path=None)
    edge = SimpleNamespace(name=route, steps=STEPS)
    s = book.skill(route, kind, "x")
    for o in outcomes:
        s.add(o)
    s.steps = old_sig(edge)
    return book, SimpleNamespace(edges=[edge])


def test_a_failing_walk_starts_afresh_after_the_walkspeed_change():
    book, router = _book("natro_out_honey_bee", "errand", ["elsewhere"] * 5,
                         lambda e: steps_signature(e, skills.ERRAND_WALK_TIMING))
    said = book.watch_steps(router)
    assert book.get("natro_out_honey_bee").recent == [] and said


def test_a_landing_flight_keeps_its_window():
    book, router = _book("natro_out_pine_tree_via_red_cannon", "flight", ["landed"] * 9 + ["elsewhere"],
                         lambda e: steps_signature(e))
    assert book.watch_steps(router) == []
    assert book.get("natro_out_pine_tree_via_red_cannon").window == (9, 1)


def test_new_steps_still_reset_even_when_landing():
    book, router = _book("natro_out_wealth_clock", "errand", ["landed"] * 5,
                         lambda e: "deadbeef0000")
    book.watch_steps(router)
    assert book.get("natro_out_wealth_clock").recent == []


def test_settled_signature_is_left_alone():
    book, router = _book("natro_home_bamboo", "home", ["elsewhere"] * 3,
                         lambda e: steps_signature(e, skills._timing("home")))
    assert book.watch_steps(router) == []
    assert book.get("natro_home_bamboo").window == (0, 3)

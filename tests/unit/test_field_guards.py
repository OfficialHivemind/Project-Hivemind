"""A boss that holds a field (world/timers FieldGuard, data/world/timers.yaml):
the Mondo Chick on the clock, the Coconut Crab all the time -- both trips that
reached the Coconut Field on 2026-10-06 died within seconds of landing."""
from __future__ import annotations

from hivemind.world.timers import load_guards


def test_the_coconut_crab_holds_its_field_at_every_moment():
    crab = load_guards()["coconut"]
    assert crab.name == "Coconut Crab" and crab.stays_s >= 3600
    for now in (0.0, 1.0, 1799.5, 3599.9, 1_791_300_000.0, 1_791_303_599.0):
        arrives, leaves = crab.visit(now)
        assert arrives <= now < leaves


def test_the_mondo_chick_still_comes_for_a_quarter_hour():
    chick = load_guards()["mountain_top"]
    assert chick.visit(1_791_302_400.0 + 60)[0] <= 1_791_302_400.0 + 60    # :01, there
    arrives, _ = chick.visit(1_791_302_400.0 + 1200)                       # :20, gone
    assert arrives > 1_791_302_400.0 + 1200

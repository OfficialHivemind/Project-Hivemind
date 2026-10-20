"""$5 ticket spending by ROI (brain/roi Ranking.tickets): the open goals whose
short materials tickets buy, fewest tickets per % of honey/h gained first."""
from types import SimpleNamespace

from hivemind.brain import goals as g
from hivemind.brain import roi

DATA = {"shops": {"s": {"label": "Shop"}},
        "goals": {"mask": {"label": "Mask", "shop": "s", "honey": 1_000_000,
                           "materials": {"diamond_egg": 5}},
                  "belt": {"label": "Belt", "shop": "s", "honey": 0,
                           "materials": {"glue": 1}},
                  "wand": {"label": "Wand", "shop": "s", "honey": 0,
                           "materials": {"magic_bean": 3}},
                  "hat": {"label": "Hat", "shop": "s", "honey": 50}}}
GAINS = {"gains": {"mask": {"low": 40, "central": 70, "high": 120, "why": "w"},
                   "belt": {"low": 3, "central": 8, "high": 12, "why": "w"},
                   "hat": {"low": 1, "central": 2, "high": 3, "why": "w"}}}


def glue_by_gumdrops(plan, held):
    # the Blender's Glue: 50 Gumdrops lacking for the belt's one Glue
    if any(r.key == "belt" for r in plan.rows):
        return SimpleNamespace(crafts=[("Glue", 1)], jelly=0, lacking={"gumdrops": 50})
    return SimpleNamespace(crafts=[], jelly=0, lacking={})


def test_ticket_spends_ranked_by_tickets_per_percent():
    held = {"diamond_egg": 2, "glue": 0, "magic_bean": 0}
    plan = g.build(DATA, honey=0, rate=None, order=["hat", "mask", "belt", "wand"],
                   held={k: (v, "") for k, v in held.items()})
    r = roi.rank(plan, held, GAINS, crafting=glue_by_gumdrops)
    # mask 3 eggs short = 1,200 tickets / 70% = 17 a %; belt 50 gumdrops =
    # 17 tickets / 8% = 2 a %; wand 60 tickets, no gain: last; hat no tickets
    assert [(o.key, o.tickets) for o in r.tickets] == [("belt", 17), ("mask", 1200),
                                                       ("wand", 60)]
    text = r.text()
    assert "Where tickets pay most" in text and "gain unknown" in text
    assert "1. Belt: 17 tickets" in text


def test_nothing_ticket_bought_short_says_nothing():
    held = {"diamond_egg": 5}
    plan = g.build(DATA, honey=0, rate=None, order=["mask", "hat"],
                   held={"diamond_egg": (5, "")})
    r = roi.rank(plan, held, GAINS, crafting=glue_by_gumdrops)
    assert r.tickets == [] and "Where tickets pay most" not in r.text()

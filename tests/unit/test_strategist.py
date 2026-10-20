"""brain/strategist (G5): roi's ranking laid out on a farming-hours clock."""
from types import SimpleNamespace

from hivemind.brain import goals as g
from hivemind.brain import roi, strategist

DATA = {"shops": {"s": {"label": "Shop"}},
        "goals": {"belt": {"label": "Belt", "shop": "s", "honey": 100_000_000},
                  "mask": {"label": "Mask", "shop": "s", "honey": 1_000_000_000,
                           "materials": {"oil": 20}},
                  "guard": {"label": "Guard", "shop": "s", "honey": 50_000_000_000},
                  "hat": {"label": "Hat", "shop": "s", "honey": 50_000_000}}}
GAINS = {"gains": {"belt": {"low": 5, "central": 10, "high": 15, "why": "w"},
                   "mask": {"low": 40, "central": 50, "high": 60, "why": "w"},
                   "guard": {"low": 1, "central": 2, "high": 3, "why": "w"}}}
RATE = g.Rate(per_hour=100_000_000, hours=2, readings=5, since=0, until=0)


def no_crafts(plan, held):
    return SimpleNamespace(crafts=[], jelly=0, lacking={"moon_charm": 5})


def ranking(rate=RATE):
    p = g.build(DATA, honey=0, rate=rate, order=["belt", "mask", "guard", "hat"],
                held={"oil": (0, "")})
    return roi.rank(p, {"oil": 0}, GAINS, crafting=no_crafts)


def test_timeline_compounds_and_lists_the_rest_apart():
    s = strategist.plan(ranking(), honey=50_000_000, horizon_hours=24 * 14)
    assert [x.label for x in s.steps] == ["Belt"]
    belt = s.steps[0]
    assert belt.at_hours == 0.5                       # 50M short at 100M/h
    assert round(belt.rate_after) == 110_000_000      # +10% central
    assert s.beyond == ["Guard"]                      # 50B: past two weeks
    assert s.first[0][0] == "Mask" and "moon charm" in s.first[0][1]
    assert s.unranked == ["Hat"]
    text = s.text(hours_per_day=12)
    assert "ESTIMATED" in text and "Belt" in text and "Later: Guard" in text


def test_no_rate_no_timeline():
    s = strategist.plan(ranking(rate=None), honey=0)
    assert not s.steps and "no honey rate" in s.text()

"""brain/roi: payback = cost / honey-an-hour gained, every number sourced.
Small plans from goals.build; the Blender's recipes from the real files."""
from pathlib import Path
from types import SimpleNamespace

import hivemind
from hivemind.brain import goals as g
from hivemind.brain import roi
from hivemind.brain.buyer import JELLY_PRICE_PLANNED

ROOT = Path(hivemind.__file__).resolve().parents[2]
DATA = {"shops": {"s": {"label": "Shop"}},
        "goals": {"belt": {"label": "Belt", "shop": "s", "honey": 100_000_000},
                  "mask": {"label": "Mask", "shop": "s", "honey": 1_000_000_000,
                           "materials": {"oil": 20}},
                  "hive_slot_43": {"label": "Hive Slot (bee 43)", "shop": "s",
                                   "honey": 4_000_000_000},
                  "hat": {"label": "Hat", "shop": "s", "honey": 50_000_000}}}
GAINS = {"gains": {"belt": {"low": 5, "central": 10, "high": 15, "vs": "Old", "why": "w"},
                   "mask": {"low": 40, "central": None, "high": 60, "why": "w"},
                   "hive_slot": {"low": 1, "central": 2, "high": 3, "why": "w"}}}
RATE = g.Rate(per_hour=100_000_000, hours=2, readings=5, since=0, until=0)


def no_crafts(plan, held):
    return SimpleNamespace(crafts=[], jelly=0, lacking={})


def plan(order=("hive_slot_43", "belt", "mask", "hat"), rate=RATE):
    return g.build(DATA, honey=0, rate=rate, order=list(order), held={"oil": (20, "")})


def test_ranked_by_payback_with_unknown_apart_and_the_plans_next_explained():
    r = roi.rank(plan(), {"oil": 20}, GAINS, crafting=no_crafts,
                 order_from="your order")
    assert [o.key for o in r.known] == ["belt", "mask", "hive_slot_43"]
    belt = r.known[0]
    assert belt.payback() == 100_000_000 / (0.10 * 100_000_000)        # 10 h
    assert belt.payback(2) < belt.payback() < belt.payback(0)
    assert [o.key for o in r.unknown] == ["hat"]                        # no estimate
    mask = r.known[1]
    assert mask.gain[1] == 50 and "midpoint" in mask.gain_note          # null central
    slot = r.known[2]
    assert slot.honey == 4_000_000_000 + roi.BASIC_EGG_HONEY            # no egg held
    assert r.plan_next.key == "hive_slot_43"
    assert "Hive Slot (bee 43)" in r.why_differ and "your order" in r.why_differ
    text = r.text()
    assert "Hat" in text and "No gain estimate" in text and "upper estimates" in text


def test_a_held_egg_costs_nothing_more_and_same_pick_says_so():
    r = roi.rank(plan(order=("belt", "hive_slot_43")), {"basic_egg": 1}, GAINS,
                 crafting=no_crafts)
    assert next(o for o in r.known if o.key == "hive_slot_43").honey == 4_000_000_000
    assert "same" in r.why_differ


def test_materials_cost_royal_jelly_counted_alone_not_after_the_goals_above():
    # 7 oil held, 13 short: the Blender's recipe (goals.yaml oil: 50
    # Sunflower Seeds + 10 Royal Jelly) is 130 RJ, less the 30 held
    p = g.build(DATA, honey=0, rate=RATE, order=["mask"], held={"oil": (7, "")})
    held = {"oil": 7, "royal_jelly": 30, "sunflower_seed": 10_000}
    data = g.load(ROOT / "data" / "knowledge" / "goals.yaml")
    p.rows[0].needs[0].sources = [dict(s, now=s.get("bot"))
                                  for s in data["materials"]["oil"]["sources"]]
    opt = roi.rank(p, held, GAINS).known[0]
    assert opt.jelly == 130 - 30
    assert opt.cost == 1_000_000_000 + 100 * JELLY_PRICE_PLANNED
    assert not opt.unpriced
    held["sunflower_seed"] = 0                 # the recipe's seeds missing: a floor
    opt = roi.rank(p, held, GAINS).known[0]
    assert opt.unpriced and "at least" in opt.reason()


def test_no_rate_ranks_by_cost_per_percent_and_says_so():
    r = roi.rank(plan(rate=None), {}, GAINS, crafting=no_crafts)
    assert r.known[0].key == "belt" and r.known[0].payback() is None
    assert "no honey rate" in r.text()


def test_gains_file_is_sane():
    body = roi.load_gains(ROOT / "data" / "knowledge" / "gains.yaml")
    assert body.get("source")
    for key, e in body["gains"].items():
        mid = e["central"] if e["central"] is not None else e["low"]
        assert 0 < e["low"] <= mid <= e["high"], key
        assert e.get("why"), key

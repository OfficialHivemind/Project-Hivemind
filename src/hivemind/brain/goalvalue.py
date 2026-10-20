"""The G term: what an action is worth beyond its own payout, because it also
moves a goal forward (backlog B5 + P2, docs/pending/brain-research-3.md
section 3: "Goals become value terms (G_a)." and docs/pending/brain-research-2.md
section 4's quest tables).

Q(a) = p_a*(V_a + G_a) - ... -- `value.py` already does V_a and the rest;
this is the G_a half, in honey, so it can be added the same way.

WHAT IT REFUSES TO DO. A sub-goal this project has no honey figure for (the
Diamond Mask's non-honey materials, a quest band the research table doesn't
cover) contributes 0 to the sum, not an invented one -- `goal_terms` always
returns a float, because it is a sum of possibly-zero parts, not a single
unpriced amount; see the module docstring of `calendar.py` for the
different rule that applies there (`value_honey=None`, never 0).
"""
from __future__ import annotations

from . import value

# ---------------------------------------------------- Brown Bear quests ----
# docs/pending/brain-research-2.md "Brown Bear": "Each pays 1 ticket plus
# jelly by quests done" -- the table, by the NEXT quest number. Gaps (41-60,
# 101-125, 226+) are not in the research; a quest number outside every band
# contributes 0, not a guess.
BROWN_RJ_BANDS = ((31, 40, 10), (61, 75, 50), (76, 100, 100),
                  (126, 150, 500), (151, 200, 750), (201, 225, 1000))
# docs/pending/brain-research-3.md section 3: "Royal Jelly = the shop price
# min(1M, 250k + 10k.n), from research pass 2." Confirmed in
# data/knowledge/gear_prices.yaml ("royal jelly (250,000 plus 10,000 per
# jelly)"). `n` is the jelly already bought this account -- the marginal
# price keeps rising, so every jelly in one quest's reward is priced at
# today's marginal rate, a slight underestimate for a reward over 1 jelly.
ROYAL_JELLY_SHOP_PRICE_FLOOR = 250_000.0
ROYAL_JELLY_SHOP_PRICE_STEP = 10_000.0
ROYAL_JELLY_SHOP_PRICE_CAP = 1_000_000.0


def _royal_jelly_price(jelly_bought: int) -> float:
    if "royal_jelly" in value.PRICES:
        return float(value.PRICES["royal_jelly"])
    return min(ROYAL_JELLY_SHOP_PRICE_CAP,
              ROYAL_JELLY_SHOP_PRICE_FLOOR + ROYAL_JELLY_SHOP_PRICE_STEP * jelly_bought)


def _brown_rj_for_quest(quest_number: int) -> int | None:
    for lo, hi, rj in BROWN_RJ_BANDS:
        if lo <= quest_number <= hi:
            return rj
    return None


def _brown_quest_term(brown: dict) -> float:
    if not brown or not brown.get("advances"):
        return 0.0
    quest_number = int(brown.get("quests_done", 0)) + 1
    rj = brown.get("rj_reward")
    if rj is None:
        rj = _brown_rj_for_quest(quest_number)
    if not rj:
        return 0.0          # a band the research table doesn't cover: no guess
    return float(rj) * _royal_jelly_price(int(brown.get("royal_jelly_bought", 0)))


# ---------------------------------------------------- Polar Bear quests ----
# docs/pending/brain-research-2.md "Polar Bear": "Reward per quest: 100k-163k
# honey, 10 treats, one Polar Power". A range, not a point -- the midpoint is
# used and the uncertainty stays in this comment, not hidden in the number.
POLAR_QUEST_HONEY_RANGE = (100_000.0, 163_000.0)
POLAR_QUEST_HONEY_MIDPOINT = sum(POLAR_QUEST_HONEY_RANGE) / 2.0
# "Polar Power is additive ... Max bee energy is x(1 + 0.05n)" (research-2.md
# section 1) -- +5% per quest, additive. Pricing the energy itself needs
# rho and a horizon ("Polar Power valued at rho x 5% energy x the horizon, as
# a CALIBRATION SETTING" -- brain-research-3.md section 3), and nothing cites
# a default horizon, so that half of the term is 0 unless the caller supplies
# both `rho` and `horizon_s`.
POLAR_POWER_STEP = 0.05


def _polar_quest_term(polar: dict) -> float:
    if not polar or not polar.get("advances"):
        return 0.0
    term = POLAR_QUEST_HONEY_MIDPOINT
    rho = polar.get("rho")
    horizon_s = polar.get("horizon_s")
    if rho is not None and horizon_s is not None:
        term += float(rho) * POLAR_POWER_STEP * float(horizon_s)
    return term


# -------------------------------------------------------------- nectar ----
def _nectar_term(nectar: dict) -> float:
    if not nectar or not nectar.get("rows") or not nectar.get("name"):
        return 0.0
    try:
        from ..act.planter import NECTAR_MIN
    except ImportError:
        NECTAR_MIN = {}
    name = nectar["name"]
    minimum = NECTAR_MIN.get(name)
    current = nectar.get("current_pct")
    if minimum is not None and current is not None and current >= minimum:
        return 0.0          # already at or above its minimum: no urgency bonus
    # docs/pending/brain-research-3.md section 3: price nectar off the wiki's
    # m(t) growth formula, "check this against the honey/s by nectar level
    # that reflect.nectar_effect already measures, and trust the measurement
    # when they disagree." The wiki formula needs a min/max this project
    # cannot verify (NECTAR_MIN is the bot's OWN target, not the wiki's growth
    # bound), so only the measured path is used here.
    from .reflect import nectar_effect
    measured = nectar_effect(nectar["rows"], name, nectar.get("field"))
    if measured is None:
        return 0.0           # under 3 trips either side: no measurement yet
    hi_rate, lo_rate, _n_hi, _n_lo = measured
    hold_hours = float(nectar.get("hold_hours", 0.0))
    return max(0.0, hi_rate - lo_rate) * hold_hours * 3600.0


# -------------------------------------------------------------- materials ----
def _mask_material_term(mask: dict) -> float:
    if not mask:
        return 0.0
    honey_cost_each = mask.get("honey_cost_each")
    if honey_cost_each is None:
        return 0.0          # e.g. the Diamond Mask (gear_prices.yaml): honey only,
                            # no material has a cost in this project's data
    return float(mask.get("amount", 0.0)) * float(honey_cost_each)


def goal_terms(action_name: str, context: dict) -> float:
    """The honey-equivalent G_a for `action_name`, summed from whichever of
    these `context` carries (a key left out contributes 0, not a guess):

    context["brown_quest"] = {"advances": bool, "quests_done": int,
        "rj_reward": int|None, "royal_jelly_bought": int}
        -- an action that finishes a Brown Bear quest step. `rj_reward`
        overrides the research table when the account's own band is known;
        `royal_jelly_bought` prices the jelly at today's shop rate.
    context["polar_quest"] = {"advances": bool, "rho": float|None,
        "horizon_s": float|None}
        -- an action that finishes a Polar Bear quest step.
    context["nectar"] = {"rows": list, "name": str, "field": str|None,
        "current_pct": float|None, "hold_hours": float}
        -- a planter/nectar action; `rows` is the trip ledger
        (brain/ledger, what reflect.nectar_effect reads).
    context["mask_material"] = {"amount": float, "honey_cost_each": float|None}
        -- a material gathered toward a gear goal.

    `action_name` is not matched against anything here -- the caller decides
    which terms apply by what it puts in `context`; it is carried through for
    the self-check and any future explanation text.
    """
    del action_name
    return (_brown_quest_term(context.get("brown_quest") or {})
            + _polar_quest_term(context.get("polar_quest") or {})
            + _nectar_term(context.get("nectar") or {})
            + _mask_material_term(context.get("mask_material") or {}))


def field_quest_value(field: str, quest_needs, rho: float) -> float:
    """Honey/s bonus for gathering in `field` because a quest wants it, for
    the field score to ADD (brain-research-3.md section 3: "replace the
    quest-first sort in rank() with score + G_f/gather_seconds").

    Only the piece this project can actually price: a wanted mob living in
    `field` (`questneeds.Needs.mobs_wanted()`) is killed by the bees for free
    while the character gathers (same fact `brain/decide.py` already uses),
    so its honey + ticket chance (measured with a wiki prior, brain/mobtable) is a genuine
    honey/s bonus. A quest step asking for THIS FIELD'S POLLEN BY NAME
    (`field_remaining`) adds nothing extra here: that pollen is already
    counted in the field's own measured rate, so crediting it again would
    double the same honey. `rho` is accepted (matching value.py's other
    honey/s terms) but unused by this piece; a future direct-pollen-match
    term would need it to avoid exactly that double-count, which is why it
    stays in the signature.
    """
    del rho
    if quest_needs is None:
        return 0.0
    from .calendar import FIELD_MOBS, MOB_HONEY, MOB_TICKET_CHANCE, RESPAWN_SECONDS
    try:
        wanted = quest_needs.mobs_wanted() or {}
    except Exception:
        return 0.0
    if not wanted:
        return 0.0
    bonus = 0.0
    for mob in FIELD_MOBS.get(field, ()):
        if mob not in wanted:
            continue
        respawn = RESPAWN_SECONDS.get(mob)
        if not respawn:
            continue
        honey = MOB_HONEY[mob] + MOB_TICKET_CHANCE[mob] * value.PRICES["ticket"]
        bonus += honey / respawn
    return bonus


if __name__ == "__main__":
    # Brown Bear: quest 83 done -> next is 84, in the 76-100 band, 100 RJ.
    v = goal_terms("hand_in_brown", {"brown_quest": {"advances": True, "quests_done": 83}})
    assert v == 100 * _royal_jelly_price(0)
    # A band the table doesn't cover contributes nothing.
    assert goal_terms("x", {"brown_quest": {"advances": True, "quests_done": 50}}) == 0.0
    # Not advancing: nothing.
    assert goal_terms("x", {"brown_quest": {"advances": False, "quests_done": 83}}) == 0.0
    # An explicit reward overrides the table.
    v2 = goal_terms("x", {"brown_quest": {"advances": True, "quests_done": 83, "rj_reward": 9}})
    assert v2 == 9 * _royal_jelly_price(0)

    # Polar: the direct honey reward always counts; the energy term only
    # with both rho and a horizon.
    assert goal_terms("x", {"polar_quest": {"advances": True}}) == POLAR_QUEST_HONEY_MIDPOINT
    with_energy = goal_terms("x", {"polar_quest": {"advances": True, "rho": 8000.0,
                                                   "horizon_s": 3600.0}})
    assert with_energy > POLAR_QUEST_HONEY_MIDPOINT

    # Nectar: below its minimum with no measured rows yet -> 0, not a guess.
    assert goal_terms("x", {"nectar": {"rows": [], "name": "comforting",
                                      "current_pct": 10.0, "hold_hours": 2.0}}) == 0.0
    rows = ([{"converted": True, "honey": 100, "seconds": 10, "nectar": {"comforting": 80}}] * 3
           + [{"converted": True, "honey": 40, "seconds": 10, "nectar": {"comforting": 10}}] * 3)
    measured = goal_terms("x", {"nectar": {"rows": rows, "name": "comforting",
                                           "current_pct": 10.0, "hold_hours": 1.0}})
    assert measured == (10.0 - 4.0) * 1.0 * 3600.0
    # Already at the minimum: no urgency bonus even with the same rows.
    assert goal_terms("x", {"nectar": {"rows": rows, "name": "comforting",
                                       "current_pct": 90.0, "hold_hours": 1.0}}) == 0.0

    # Mask materials: unpriced unless a cost is given.
    assert goal_terms("x", {"mask_material": {"amount": 50, "honey_cost_each": None}}) == 0.0
    assert goal_terms("x", {"mask_material": {"amount": 50, "honey_cost_each": 1000.0}}) == 50_000.0

    # field_quest_value: a field with a wanted mob gets its honey/s; one with
    # none, or no quest data, gets 0.
    class FakeNeeds:
        def mobs_wanted(self):
            return {"scorpion": 3}
    bonus = field_quest_value("rose", FakeNeeds(), rho=8000.0)
    from .calendar import MOB_HONEY, MOB_TICKET_CHANCE
    assert bonus == (MOB_HONEY["scorpion"] + MOB_TICKET_CHANCE["scorpion"] * 100_000.0) / 1230
    assert field_quest_value("sunflower", FakeNeeds(), rho=8000.0) == 0.0
    assert field_quest_value("rose", None, rho=8000.0) == 0.0

    print("ok")

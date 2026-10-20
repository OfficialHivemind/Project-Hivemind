"""Hotbar rules (ROADMAP $11, the owner's friend; Natro's hotbar slots): the
user's own "press this item when ..." rules, decided here, pressed by run_farm.

A RULE (world/settings `hotbar.rules`, checked by `hotbar_rules`) names one
item, a trigger and optional conditions. run_farm checks every rule at the
two moments it already has, and nowhere else:

  tick     each pattern pass of a gather (`stay_in_field`): 'every' and
           'gathering' rules, and 'boost' ones -- a field boost that started
           since the rule last saw one fires it once, at the first pass in the
           boosted field (a booster's press happens away from the field);
  convert  on the pad after a convert (`after_convert`): 'convert' rules,
           and 'every' ones not tied to a field.

`due` says whether the trigger fires; `check` whether the press may go ahead,
skipping -- with the reason, which run_farm logs -- when the field or hive
level condition is not met, the materials rule says no (brain/protips
material_boost_ok), the reserve would be touched, the item is not on the
hotbar or its tile is greyed, the boost keeper owns the item and the rule is
not ticked 'rule over AI', or the boost AI vetoes it. The press itself is
act/hotbar.press_slot, the tested path every other hotbar use takes.
"""
from __future__ import annotations

from . import protips

# items the boost keeper itself spends (brain/boostkeeper: booster, Glitter,
# Field Dice); of the hotbar items only the dice
KEEPER_ITEMS = frozenset({"field_dice"})


def _slug(field) -> str:
    return str(field or "").strip().lower().replace(" ", "_")


def due(rule: dict, hook: str, now: float, state: dict, *, boost_at=None,
        boost_field=None, field=None) -> bool:
    """Does `rule`'s trigger fire at `hook` ('tick' | 'convert')? `state` is
    the rule's own {'last': press time, 'boost': the boost start it fired
    for}; `boost_at`/`boost_field`: the running field boost's start and field."""
    trigger, last = rule.get("trigger"), float(state.get("last") or 0.0)
    if trigger == "every":
        # one only for a field waits for the gather there: the pad is no field
        return ((hook == "tick" or not rule.get("field"))
                and now - last >= 60.0 * float(rule.get("minutes") or 0))
    if trigger == "convert":
        return hook == "convert"
    if trigger == "gathering":
        return hook == "tick" and now - last >= float(rule.get("seconds") or 0)
    if trigger == "boost":
        return (hook == "tick" and bool(boost_at) and state.get("boost") != boost_at
                and _slug(boost_field) == _slug(field))
    return False


def check(rule: dict, *, field, hive_level, role, count, slot, keeper_on: bool,
          vetoed=None) -> tuple[bool, str]:
    """(press, why not). `slot`: vision/hotbar_items' Slot for the item, or
    None when no slot shows it; `count`: the stash's count (None: not
    counted); `keeper_on`: the boost keeper is keeping this item's kind up;
    `vetoed`: () -> bool, the boost AI's 'act' veto (it logs its own why)."""
    name = str(rule.get("item", "")).replace("_", " ")
    if rule.get("field") and _slug(rule["field"]) != _slug(field):
        return False, f"only in {rule['field']}, and this is {_slug(field).replace('_', ' ') or 'no field'}"
    want = int(rule.get("hive_level") or 0)
    if want and (hive_level is None or float(hive_level) < want):
        return False, (f"only from hive level {want}, and the hive level is "
                       + ("not known" if hive_level is None else f"{hive_level:g}"))
    ok, why = protips.material_boost_ok(role, hive_level)
    if not ok:
        return False, why
    keep = int(rule.get("keep") or 0)
    if count is None and keep:
        return False, f"{name} not counted yet, and {keep} are to be kept"
    if count is not None and count <= keep:
        return False, f"{count} {name} held, {keep} kept back"
    if slot is None:
        return False, f"no {name} on the hotbar (or its tile is cooling down)"
    if getattr(slot, "greyed", False):
        return False, f"the {name} tile in slot {slot.slot} is greyed: none left"
    if rule.get("item") in KEEPER_ITEMS and keeper_on and not rule.get("over_ai"):
        return False, f"the boost keeper keeps {name} up; the AI decides (tick 'rule over AI' to win)"
    if vetoed is not None and vetoed():
        return False, "the boost AI vetoed it"
    return True, ""


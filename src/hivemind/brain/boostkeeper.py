"""The boost keeper (ROADMAP B19, a boosting macro that keeps
boosts alive): which refresh is due now, so the field the bot gathers stays
boosted instead of a boost running out mid-trip.

WHAT IT KNOWS OF A BOOST. The buff bar reader (vision/buffs) has templates for
Haste, Melody and the bear morphs only -- no field-boost icon -- so a boost is
what run_farm's `boost_box` holds: the press time (a booster, a Glitter, a
Field Dice) and the field and stacks the game's feed named ('Activated "Blue
Flower Field Boost" x 3', `read_the_boost`). A field boost lasts 15 minutes
(wiki Field_Boost) and a new boost on the same field adds a stack and starts
its 15 minutes again, so a refresh just before the end keeps it alive.

WHAT IT USES, cheapest first:
  a field booster  free, on its own cooldown (brain/calendar); boosts one
                   field of its set at random, so only one whose set holds
                   the field;
  Glitter          "Boosts the field you're standing in" -- used at a trip's
                   start in the field (run_farm `use_a_field_consumable`);
  Field Dice       a random field -- only when no Glitter is held, rolled at
                   the pad (`roll_a_field_dice`) and followed where it pays.
Only items held past what the goals keep (brain/stash `spare`); nothing is
ever bought. It never acts during a convert or a walk home: its callers are
the pad errands after a convert and the trip's start in the field.
"""
from __future__ import annotations

BOOST_SECONDS = 15 * 60.0     # a field boost (wiki Field_Boost)
LEAD_SECONDS = 60.0           # refresh when the boost would end within the trip plus this
ITEM_TITLES = {"glitter": "Glitter", "field_dice": "Field Dice"}


def left_of(box: dict, now: float) -> dict:
    """{field: (stacks, seconds left)} from run_farm's `boost_box` -- the one
    boost it tracks -- or {} when none is known to run."""
    at, field = (box or {}).get("at"), (box or {}).get("field")
    if not at or not field:
        return {}
    left = BOOST_SECONDS - (float(now) - float(at))
    return {field: (int(box.get("stacks") or 1), left)} if left > 0 else {}


def due(*, on: bool, field: str | None, boosts: dict, trip_seconds: float,
        spare: dict, boosters_ready: dict,
        kinds=("booster", "glitter", "field_dice")) -> list[tuple[str, str]]:
    """[(action, why)] due now to keep `field` boosted through the next trip,
    best first. `action` is a booster's name, 'glitter' or 'field_dice'.
    `boosts`: `left_of`; `trip_seconds`: the trip's planned stay; `spare`:
    {item key: how many may be used}; `boosters_ready`: {booster: fields it
    boosts} for those off cooldown; `kinds`: which of booster/glitter/
    field_dice the owner lets it keep up (U19 boost.boosters/glitter/dice).
    Nothing while the boost lasts the trip."""
    if not on or not field:
        return []
    label = field.replace("_", " ")
    stacks, left = boosts.get(field, (0, 0.0))
    if left > float(trip_seconds or 0.0) + LEAD_SECONDS:
        return []
    state = (f"boost {left:.0f} s left" if left > 0 else "no boost running")
    out = []
    for name, fields in sorted((boosters_ready or {}).items() if "booster" in kinds else ()):
        if field in (fields or ()):
            out.append((name, f"the {name.replace('_', ' ')} is off cooldown and can "
                              f"boost {label} ({state})"))
            break
    if "glitter" in kinds and int((spare or {}).get("glitter") or 0) > 0:
        out.append(("glitter", f"Glitter on {label} ({state})"))
    elif "field_dice" in kinds and int((spare or {}).get("field_dice") or 0) > 0:
        out.append(("field_dice", f"Field Dice for {label} ({state}; a random "
                                  f"field, followed where it pays)"))
    return out


def stacked(box: dict, field: str, now: float) -> int:
    """The stacks on `field` after one more boost there: one more than a boost
    still running on it, else 1."""
    return left_of(box, now).get(field, (0, 0.0))[0] + 1

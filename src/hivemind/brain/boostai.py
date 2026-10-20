"""The boost AI (ROADMAP U19, the owner's "an AI that boosts"): whether a boost
pays, from what the bot has MEASURED, never from a guess.

WHAT A BOOST IS WORTH. The trip ledger (var/trips.jsonl) has every trip's
field, pollen and gathering seconds; var/boosts.jsonl has every booster press
and Field Dice roll with the field the game's feed named. A trip is BOOSTED
when the whole trip sat inside a read press's fifteen minutes on its field,
and UNBOOSTED when no read press overlapped it and the trip's own `boosted`
was another field (a Glitter is not in boosts.jsonl, so a trip it boosted is
left out of the baseline). Each boosted trip is set against the same field's
unboosted trips within MATCH_WINDOW_S -- the hive grows, so a ratio across
weeks would not be one -- and the field's gain is the median of those ratios.
A field with fewer than MIN_PAIRS matched trips is NOT MEASURED, and says so.
MEASURED 2026-10-19 from the live ledger: Pine Tree x1.80 (102 pairs), Bamboo
x1.45 (41), Blue Flower x3.54 (18), Rose x2.21 (7); every other field under
MIN_PAIRS.

WHAT IT DECIDES (run_farm, setting boost.ai: off | look | act):
  item_pays     Glitter / Field Dice for the boost keeper. Neither is sold for
                honey or tickets (data/knowledge consumables.yaml, goals.yaml),
                so their only cost is the goals' keep, which brain/stash
                already holds back; the rest pays when the honey it adds is
                MEASURED to be above nothing. Unmeasured: no.
  booster_pays  a booster the walk alone would not pay for: the boost's
                measured extra pollen times the odds it lands on the field,
                against the pollen the walk costs.
  stack_target  the field where a boost adds the most pollen a second (look-
                only: moving the bot there is the planner's, not ours yet).
  booster_timing when to press the next booster so its stack lands before the
                running boost ends (look-only).
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass

BOOST_SECONDS = 15 * 60.0        # a field boost (wiki Field_Boost)
MATCH_WINDOW_S = 6 * 3600.0      # an unboosted trip this close is "the same hive"
MIN_PAIRS = 5                    # fewer matched trips: not measured
MIN_GATHER_S = 60.0              # as boostwindow.measured_ratios
BASE_TRIPS = 10                  # the base rate: the field's newest unboosted trips
# MOVING THE BOT (the field it farms, when a booster is walked to) is LOOK-
# ONLY until it is seen working live: in 'act' too, those are only logged.
MOVES_LIVE = False
MODES = ("off", "look", "act")
LEAD_S = 60.0                    # boostkeeper.LEAD_SECONDS: refresh this close to the end


@dataclass
class Gain:
    field: str
    ratio: float          # boosted pollen/s over unboosted, median of the pairs
    pairs: int
    base_rate: float      # the field's newest unboosted pollen/s

    @property
    def extra_rate(self) -> float:
        """Pollen a second a boost adds here."""
        return max(0.0, self.ratio - 1.0) * self.base_rate

    def describe(self) -> str:
        return (f"{_name(self.field)} boosted gathers x{self.ratio:.2f} "
                f"({self.pairs} measured trips)")


def _name(field) -> str:
    return str(field or "?").replace("_", " ")


def read_jsonl(path) -> list[dict]:
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def measure(trips, presses) -> dict[str, Gain]:
    """{field: Gain} for every field with MIN_PAIRS matched trips (module doc)."""
    windows: dict[str, list[float]] = {}
    for p in presses or ():
        if p.get("field") and not p.get("frame"):
            try:
                windows.setdefault(p["field"], []).append(float(p["at"]))
            except (TypeError, ValueError):
                continue
    rows: dict[str, list[tuple[float, bool, float]]] = {}
    for t in trips or ():
        try:
            field, gather = t.get("aimed_at"), float(t.get("gather_seconds") or 0.0)
            if not field or t.get("credited") != field or not t.get("pollen") \
                    or gather <= MIN_GATHER_S:
                continue
            end = float(t["at"])
            start = end - float(t.get("seconds") or gather)
            rate = float(t["pollen"]) / gather
        except (TypeError, ValueError, KeyError):
            continue
        presses_here = windows.get(field, ())
        if any(a <= start and end <= a + BOOST_SECONDS for a in presses_here):
            rows.setdefault(field, []).append((end, True, rate))
        elif not any(a < end and start < a + BOOST_SECONDS for a in presses_here) \
                and t.get("boosted") != field:
            rows.setdefault(field, []).append((end, False, rate))
    out = {}
    for field, got in rows.items():
        base = [(at, r) for at, boosted, r in got if not boosted]
        ratios = []
        for at, boosted, rate in got:
            if not boosted:
                continue
            near = [r for b_at, r in base if abs(b_at - at) < MATCH_WINDOW_S]
            if len(near) >= 2 and statistics.median(near) > 0:
                ratios.append(rate / statistics.median(near))
        if len(ratios) >= MIN_PAIRS and base:
            newest = [r for _, r in sorted(base)[-BASE_TRIPS:]]
            out[field] = Gain(field, statistics.median(ratios), len(ratios),
                              statistics.median(newest))
    return out


def item_pays(item: str, field, gains: dict, *, seconds: float,
              landings: dict | None = None, follows=()) -> tuple[bool, str]:
    """(pays, why) for one Glitter on `field`, or one Field Dice (a random
    field: `landings` is {field: rolls read there}, boostwindow.read_counts;
    only a landing on `field` or a field in `follows` -- the ones the next
    trip would gather boosted -- adds anything)."""
    seconds = min(BOOST_SECONDS, max(0.0, float(seconds or 0.0)))
    if item == "glitter":
        g = gains.get(field)
        if g is None:
            return False, f"a boost on {_name(field)} is not measured yet"
        more = g.extra_rate * seconds
        return more > 0, (f"{g.describe()}: about {more:,.0f} more pollen this trip; "
                           f"Glitter has no honey or ticket price, the goals' share is kept")
    if item == "field_dice":
        read = sum((landings or {}).values())
        if read < MIN_PAIRS:
            return False, (f"where a Field Dice lands is not measured "
                           f"({read} rolls read, {MIN_PAIRS} needed)")
        where = {field, *(follows or ())}
        gain = sum(n * gains[f].extra_rate for f, n in landings.items()
                   if f in gains and f in where)
        more = gain / read * seconds
        return more > 0, (f"a Field Dice adds about {more:,.0f} pollen on average over "
                          f"{read} read rolls (measured fields the trip would gather)")
    return False, f"{item}: not a boost item the AI prices"


def booster_pays(field, gains: dict, *, p_land: float, boosted_s: float,
                 detour_s: float) -> tuple[bool, str]:
    """(pays, why) for a booster press the walk alone would not pay for."""
    g = gains.get(field)
    if g is None:
        return False, f"a boost on {_name(field)} is not measured yet"
    added = float(p_land) * g.extra_rate * max(0.0, float(boosted_s))
    lost = g.base_rate * max(0.0, float(detour_s))
    return added > lost, (f"{g.describe()}, lands there {p_land:.0%}: +{added:,.0f} "
                          f"pollen against {lost:,.0f} the walk costs")


def stack_target(gains: dict, open_fields=None) -> tuple[str | None, str]:
    """(field, why): where a boost adds the most pollen a second, of the
    measured fields the bot may gather (`open_fields`; None: any)."""
    best = max((g for f, g in gains.items() if open_fields is None or f in open_fields),
               key=lambda g: g.extra_rate, default=None)
    if best is None:
        return None, "no field's boost is measured yet"
    return best.field, (f"stack boosts on {_name(best.field)}: {best.describe()}, "
                        f"+{best.extra_rate:,.0f} pollen/s")


# FOLLOW A BOOST ONLY WHERE IT IS MEASURED TO BEAT HOME. Research 2026-10-21
# (var/trips.jsonl, 72 h, Pine Tree home): Bamboo boosted ~43.9k pollen/s
# against Pine's 28.9-33.2k, but Blue Flower x3 only ~19.8k -- yet the
# theoretical 1 + stacks (boostwindow.follow_the_boost, its BLUE_INDEX guess)
# scores Blue Flower x3 at 1.48 and would follow it, likely why the owner
# turned gather.follow_boost off. ponytail: the walk there is not priced, only
# a floor on the boost time left; add the route's median seconds when it moves.
FOLLOW_MARGIN = 1.15                 # the boosted rate must beat home's by this
FOLLOW_MIN_LEFT_S = 150.0


def follow_target(gains: dict, boosted: dict, home, open_fields=None) -> tuple[str | None, str]:
    """(field, why): a boosted field (`boosted` {field: seconds left}) worth
    leaving `home` for -- its measured boosted rate (ratio x base, MIN_PAIRS
    trips) at least FOLLOW_MARGIN x home's newest unboosted rate, open, and
    FOLLOW_MIN_LEFT_S left -- or (None, why) to stay."""
    h = gains.get(home)
    if h is None:
        return None, f"stay on {_name(home)}: its own rate is not measured yet"
    bar = FOLLOW_MARGIN * h.base_rate
    best, best_rate, said = None, bar, []
    for f, left in (boosted or {}).items():
        if f == home or (open_fields is not None and f not in open_fields):
            continue
        g = gains.get(f)
        if g is None:
            said.append(f"{_name(f)} not measured")
            continue
        rate = g.ratio * g.base_rate
        if float(left or 0.0) < FOLLOW_MIN_LEFT_S:
            said.append(f"{_name(f)} {left:.0f}s left")
        elif rate >= best_rate:
            best, best_rate = f, rate
        else:
            said.append(f"{_name(f)} boosted {rate:,.0f}/s under {bar:,.0f}")
    if best is None:
        return None, (f"stay on {_name(home)} ({h.base_rate:,.0f}/s)"
                      + (f": {'; '.join(said)}" if said else ""))
    return best, (f"follow the boost to {_name(best)}: {best_rate:,.0f}/s boosted against "
                  f"{_name(home)}'s {h.base_rate:,.0f}/s")


def booster_timing(field, boost_left: float, ready_in: dict, boosts: dict) -> str:
    """When to press a booster for `field` so its stack lands before the
    running boost (`boost_left` s) ends. `ready_in`: {booster: s until off
    cooldown}; `boosts`: {booster: fields it boosts}. '' when none boosts it."""
    mine = sorted((s, b) for b, s in (ready_in or {}).items()
                  if field in ((boosts or {}).get(b) or ()))
    if not mine:
        return ""
    s, booster = mine[0]
    name = _name(booster)
    if boost_left <= 0:
        return (f"press the {name} now for {_name(field)}" if s <= 0 else
                f"press the {name} in {s / 60:.0f} min, when it is off cooldown")
    if s <= boost_left:
        return (f"press the {name} in the boost's last minutes "
                f"({max(0.0, boost_left - LEAD_S) / 60:.0f} min from now) for a stack more")
    return (f"the {name} is ready {(s - boost_left) / 60:.0f} min after the "
            f"boost on {_name(field)} ends")

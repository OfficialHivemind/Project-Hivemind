"""Whether a field boost is running where the bot gathers: if so, no errands.

THE PLAYBOOK, `no_errands_in_a_boost` (data/knowledge/playbook.yaml): every
macro the community runs keeps gathering through a field boost. Natro's main
loop starts no side task while the gather field is boosted
(nm_GatherBoostInterrupt, 900 s), and another macro's docs say to leave gather
interrupts off when farming honey -- a boost's fifteen minutes are the most a
trip ever earns. This bot used to walk its errand chain after every convert,
boosted or not.

A BOOST IS SEEN, NOT ASSUMED. A field booster boosts one of its fields at
random (data/knowledge/errands.yaml), and the bot cannot yet read which one
from the screen. What it can measure is the trip itself: a boosted trip
gathers far faster than the field's own rate. MEASURED 2026-10-01/02 on Pine
Tree: ordinary trips 8,400-14,500 pollen a second, the 02:00 boosted trip
22,000 (14.4M pollen in 648 s). So the window is open only when a booster was
pressed within its fifteen minutes AND the trip just gathered in one of its
fields at BOOSTED_RATE_FACTOR times that field's measured rate or more.
"""
from __future__ import annotations

import json

BOOST_SECONDS = 15 * 60.0          # a field booster's boost (errands.yaml)
BOOSTED_RATE_FACTOR = 1.5          # over the 14,500 an ordinary trip reached
BOOST_MIN_LEFT_SECONDS = 150.0     # less than this left is not worth a trip


def boost_landed(*, pressed_at: float | None, now: float, fields, field: str | None,
                 pollen: int | None, seconds: float, usual_rate: float | None,
                 boosted: str | None = None) -> str:
    """Why the errands should wait -- the boost is live on the field just
    gathered -- or "" when they need not. `pressed_at`: when a booster was
    used (time.time()), `fields`: the fields it boosts, `field`: where the
    trip gathered, `pollen`/`seconds`: the trip's own gathering, `usual_rate`:
    the field's measured pollen a second. `boosted`: the field the game's own
    feed named ('Activated "Blue Flower Field Boost" x 3') -- when it is known
    it is the answer, and the rate is the evidence only when it is not."""
    if not pressed_at:
        return ""
    left = BOOST_SECONDS - (float(now) - float(pressed_at))
    if left < BOOST_MIN_LEFT_SECONDS:
        return ""
    if boosted:
        if field != boosted:
            return ""
        return (f"the game boosted {field.replace('_', ' ')} and the trip "
                f"gathered there — about {left / 60:.0f} min of it left")
    if not field or field not in set(fields or ()):
        return ""
    if not pollen or float(seconds or 0.0) < 30.0 or not usual_rate or usual_rate <= 0:
        return ""
    rate = float(pollen) / float(seconds)
    if rate < BOOSTED_RATE_FACTOR * float(usual_rate):
        return ""
    return (f"the {field.replace('_', ' ')} trip gathered {rate:,.0f} pollen a "
            f"second against its usual {float(usual_rate):,.0f} — the boost "
            f"landed there, about {left / 60:.0f} min of it left")


# WHERE A BOOST IS WORTH FOLLOWING (the playbook's `gather_where_the_boost_
# landed`). A blue hive's pollen in a field, as a proxy: the field's blue
# share times its average flower size (research honey_tactics.md section 3,
# from the wiki's field pages) -- Pine Tree 85% blue x 2.45, Bamboo 75% x 1.85,
# Blue Flower 70% x 1.10. A boost of N stacks multiplies pollen by 1 + N.
# MEASURED 2026-10-02 over 71 read Blue Field Booster presses
# (var/places/blue_field_booster-pressed-*.jpg): Blue Flower x3 30 times,
# Pine Tree x1 22, Bamboo x1 19 -- so on 69% of them the boost landed on a
# field the bot was not going to. The proxy says a boosted Blue Flower (3.08)
# and Bamboo (2.78) both beat an unboosted Pine Tree (2.08); it is a proxy,
# so every followed boost is written down (var/boosts.jsonl) for the trips'
# own rates to settle. Stump is left out: while its snail lives the bees
# fight it instead of gathering (wiki Stump_Snail, 30M HP).
BLUE_INDEX = {"pine_tree": 2.08, "bamboo": 1.39, "blue_flower": 0.77}
FOLLOW_MARGIN = 1.15               # a boost elsewhere must beat home by this


def measured_ratios(rows, home: str, fields, *, min_trips: int = 10,
                    margin_s: float = 86400.0) -> dict:
    """{field: its pollen a gathering second over `home`'s} from the trip
    ledger (var/trips.jsonl), each MEASURED over the same days: the median
    of the field's own trips (aimed and credited there, over a minute of
    gathering) against home's trips from a day before its first to a day
    after its last -- the hive grows, so a ratio across weeks would not be
    one. A field with fewer than `min_trips` trips, or home with fewer in
    that span, is left out (the caller keeps BLUE_INDEX for it).
    MEASURED 2026-10-02: Bamboo 5,573 a second over 62 trips (09-27 to
    09-30) against Pine Tree's 6,988 over 192 then -- 0.80, where the blue-
    flower proxy said 0.67."""
    import statistics

    def trips(field):
        out = []
        for row in rows or ():
            try:
                if (row.get("credited") == field == row.get("aimed_at")
                        and row.get("pollen")
                        and float(row.get("gather_seconds") or 0.0) > 60.0):
                    out.append((float(row["at"]),
                                float(row["pollen"]) / float(row["gather_seconds"])))
            except (TypeError, ValueError, KeyError):
                continue
        return out
    home_trips = trips(home)
    out = {}
    for field in fields or ():
        if field == home:
            continue
        own = trips(field)
        if len(own) < min_trips:
            continue
        t0, t1 = min(t for t, _ in own) - margin_s, max(t for t, _ in own) + margin_s
        base = [r for t, r in home_trips if t0 <= t <= t1]
        if len(base) < min_trips:
            continue
        here = statistics.median(r for _, r in own)
        there = statistics.median(base)
        if there > 0:
            out[field] = (here / there, len(own))
    return out


def _ratio(boosted: str, home: str, ratios: dict | None):
    """(boosted's pollen over home's, how it is known)."""
    got = (ratios or {}).get(boosted)
    if got:
        ratio, n = got
        return float(ratio), (f"{boosted.replace('_', ' ')} gathers {ratio:.2f} of "
                              f"{home.replace('_', ' ')} over {n} measured trips")
    return (BLUE_INDEX[boosted] / BLUE_INDEX[home],
            "by the fields' blue flowers (a proxy until measured)")


def follow_the_boost(boosted: str | None, stacks: int, home: str | None,
                     ratios: dict | None = None) -> tuple:
    """(field to gather, why) when a boost on `boosted` with `stacks` stacks
    beats gathering `home` unboosted, else (None, why not). `ratios`:
    `measured_ratios`, which wins over BLUE_INDEX wherever it has a field."""
    if not boosted or boosted == home:
        return None, ""
    if boosted not in BLUE_INDEX or home not in BLUE_INDEX:
        return None, f"the boost is on {str(boosted).replace('_', ' ')}, not a blue field"
    ratio, how = _ratio(boosted, home, ratios)
    worth = ratio * (1 + max(1, int(stacks)))
    if worth < FOLLOW_MARGIN:
        return None, (f"a x{stacks} boost on {boosted.replace('_', ' ')} is worth "
                      f"{worth:.2f}x {home.replace('_', ' ')}, under {FOLLOW_MARGIN}x ({how})")
    return boosted, (f"the booster boosted {boosted.replace('_', ' ')} x{stacks} — "
                     f"about {worth:.1f}x {home.replace('_', ' ')} unboosted ({how})")


def follow_gain(boosted: str, stacks: int, home: str, ratios: dict | None = None) -> float:
    """How much more a followed boost on `boosted` gathers than `home`
    unboosted, as a fraction (0.48 is 48% more), or 0.0 when
    `follow_the_boost` would not follow it."""
    if follow_the_boost(boosted, stacks, home, ratios)[0] is None:
        return 0.0
    return _ratio(boosted, home, ratios)[0] * (1 + max(1, int(stacks))) - 1.0


def read_counts(path, booster: str) -> dict:
    """{field: presses read} for `booster` in var/boosts.jsonl -- the odds of
    where its next boost lands, as measured (act/errands.booster_worth). A
    press whose line was not read counts nowhere."""
    counts: dict = {}
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return counts
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("booster") == booster and row.get("field"):
            counts[row["field"]] = counts.get(row["field"], 0) + 1
    return counts


def last_boost(path, now: float) -> dict | None:
    """The newest press read live (var/boosts.jsonl; rows read from kept
    frames carry "frame" and are history, not a running boost) whose fifteen
    minutes are not over at `now` -- what a restarted run is still inside."""
    best = None
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("frame") or not row.get("booster"):
            continue
        try:
            at = float(row.get("at") or 0.0)
        except (TypeError, ValueError):
            continue
        if 0.0 <= now - at < BOOST_SECONDS and (best is None or at > float(best["at"])):
            best = row
    return best

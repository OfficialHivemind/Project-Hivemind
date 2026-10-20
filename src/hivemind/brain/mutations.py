"""Mutation knowledge: which mutation is worth chasing on which bee, and what
it costs to roll (ROADMAP K11, for H1/H5).

The facts live in data/knowledge/mutations.yaml (the wiki's datamined table
and the colour guides, each cited). This answers three questions: the range a
mutation can land in at a bee level (a bounds check for a mutation read off a
roll card), the chance one use lands a mutation at least that good, and what a
<colour> hive wants on a bee. Nothing here touches the game: the bee menu's
hive judgement only logs `would_lines`.
"""
from __future__ import annotations

import math

from . import knowledge

# THE ROLL'S SHAPE (wiki Module:RandomBias, read 2026-10-27): value =
# U(lo, top) * (1 - r) + lo * r, r = U(0, INFLUENCE): pulled towards `lo`.
INFLUENCE = 0.5
# THE HIVE LEVEL STANDS IN FOR EACH BEE'S (the bee menu does not read levels).
# ASSUMED 18 while unknown: the blue guide's "get at lvl 18" moment.
LEVEL_UNKNOWN = 18


def load() -> dict:
    """{'odds', 'mutations', 'worth', ...}; {} if the file is missing."""
    return knowledge._load("mutations.yaml")


def bounds(kind: str, level: int) -> tuple:
    """(lowest, highest) value `kind` can land on a level-`level` bee, in the
    file's units (percent for *_pct)."""
    data = load()
    m = data["mutations"][kind]
    top = int(data.get("level_max") or 25)
    f = (min(max(int(level), 1), top) - 1) / (top - 1)
    return float(m["lo"]), m["hi"][0] + (m["hi"][1] - m["hi"][0]) * f


def _below(x: float) -> float:
    """P(roll fraction <= x) for the biased roll, x in [0, 1] of (lo, top).
    Closed form of value-lo = W*(1-r), W~U(0,1), r~U(0,k): own derivation,
    checked against a simulation in tests/unit/test_mutations.py."""
    k = INFLUENCE
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if x <= 1 - k:
        return x * -math.log(1 - k) / k
    return (x - x * math.log(x) - (1 - k)) / k


def chance_at_least(kind: str, value, level: int) -> float:
    """The chance a mutation (once one happens) is `kind` at `value` or more,
    after the game rounds it to the mutation's step. `value` None = any."""
    data = load()
    muts = data["mutations"]
    share = muts[kind]["weight"] / sum(m["weight"] for m in muts.values())
    lo, hi = bounds(kind, level)
    if value is None or value <= lo:
        return share
    if hi <= lo:
        return 0.0
    return share * (1 - _below((value - muts[kind]["step"] / 2 - lo) / (hi - lo)))


def _rj_lands(bee: str) -> float:
    """The chance one Royal Jelly turns a bee into `bee` (0 for event bees).
    ASSUMED: each type equally likely within its rarity."""
    types = knowledge._load("bee_types.yaml").get("types") or {}
    rarity = (types.get(bee) or {}).get("rarity")
    n = sum(1 for t in types.values() if t.get("rarity") == rarity)
    return (load().get("royal_jelly_rarity") or {}).get(rarity, 0.0) / max(n, 1)


def expected_uses(kind: str, value, level: int, bee: str, item: str = "bitterberry",
                  radioactive: bool = False) -> float:
    """How many `item` ("bitterberry" keeps the bee; "royal_jelly" must also
    land `bee` itself) one such mutation takes on average; inf if never."""
    odds = load()["odds"][item + ("_radioactive" if radioactive else "")]
    p = odds * chance_at_least(kind, value, level)
    if item == "royal_jelly":
        p *= _rj_lands(bee)
    return 1 / p if p > 0 else math.inf


def worth(hive_colour: str, bee: str) -> dict | None:
    """The first rule in mutations.yaml `worth.<colour>` naming `bee` or its
    rarity: {'want': [{kind, min}], 'avoid', 'why', 'source'}; None if none."""
    rarity = ((knowledge._load("bee_types.yaml").get("types") or {}).get(bee) or {}).get("rarity")
    for rule in (load().get("worth") or {}).get(hive_colour) or []:
        if bee in (rule.get("bees") or ()) or rarity in (rule.get("rarity") or ()):
            return rule
    return None


def _fmt(n: float) -> str:
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if n >= div:
            return f"{n / div:.3g}{unit}"
    return f"{n:.0f}"


def plan(hive_colour: str, bees: dict, level=None) -> list[dict]:
    """For each bee type the hive holds (`bees` {type: count}, the bee menu's
    read), its best wanted mutation and what one costs on average, LOOK-ONLY.
    ponytail: by type, at the hive level; per bee once a card read gives levels
    and current mutations (none is read today)."""
    lvl = int(level) if level else LEVEL_UNKNOWN
    muts = load().get("mutations") or {}
    out = []
    for bee, count in sorted((bees or {}).items()):
        rule = worth(hive_colour, bee) if int(count or 0) > 0 else None
        if not rule:
            continue
        want = rule["want"][0]
        kind, at = want["kind"], want.get("min")
        # the first level the wanted value can roll at (a value above this
        # level's top would otherwise cost "inf"); None: not even at the top
        top = int(load().get("level_max") or 25)
        ready = next((v for v in range(min(lvl, top), top + 1)
                      if chance_at_least(kind, at, v) > 0), None)
        out.append({"bee": bee, "count": int(count), "kind": kind, "min": at, "level": lvl,
                    "ready": ready,
                    "name": muts[kind]["name"] + ("%" if muts[kind]["unit"] == "pct" else ""),
                    "bitterberry": expected_uses(kind, at, lvl, bee),
                    "bitterberry_radioactive": expected_uses(kind, at, lvl, bee, radioactive=True),
                    "royal_jelly": expected_uses(kind, at, lvl, bee, "royal_jelly"),
                    "royal_jelly_radioactive": expected_uses(kind, at, lvl, bee, "royal_jelly", True),
                    "why": rule.get("why", "")})
    return out


def would_lines(picks: list[dict], level_known: bool = True) -> list[str]:
    """The log's words for `plan`: "mutations would chase ... because ..."."""
    if not picks:
        return ["mutations would: nothing -- no rule names a bee the hive holds"]
    lvl = "" if level_known else " (hive level unknown, assumed)"
    lines = []
    for p in picks:
        want = f"{p['name']} {p['min']}+" if p["min"] is not None else f"any {p['name']}"
        if p["ready"] is None or p["ready"] > p["level"]:
            lines.append(
                f"mutations would wait: {want} on {p['bee'].title()} Bee (x{p['count']}) "
                f"cannot roll at level {p['level']}{lvl}, only from level {p['ready']}, "
                f"because {p['why']}")
            continue
        lines.append(
            f"mutations would chase {want} on {p['bee'].title()} Bee (x{p['count']}) at level "
            f"{p['level']}{lvl}: ~{_fmt(p['bitterberry'])} Bitterberries each "
            f"(~{_fmt(p['bitterberry_radioactive'])} radioactive), "
            + (f"or ~{_fmt(p['royal_jelly'])} Royal Jelly (~{_fmt(p['royal_jelly_radioactive'])} "
               f"radioactive)" if not math.isinf(p["royal_jelly"]) else "no Royal Jelly lands this bee")
            + f" because {p['why']}")
    return lines

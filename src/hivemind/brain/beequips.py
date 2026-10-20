"""Beequip knowledge: which beequip goes on which bee, and why (ROADMAP K8).

The facts live in data/knowledge/beequips.yaml (sourced, with a confidence per
entry); this only answers "what should this bee wear in a <colour> hive".
H4 (equip / wax / swap) builds on it once the bot can READ what each bee
wears -- nothing here touches the game.
"""
from __future__ import annotations

from . import knowledge


def load() -> dict:
    """{'mechanics', 'beequips', 'rankings', ...}; {} if the file is missing."""
    return knowledge.beequips()


def _bee_colour(bee_type: str) -> str | None:
    types = (knowledge._load("bee_types.yaml").get("types") or {})
    return (types.get(bee_type) or {}).get("colour")


def can_wear(beequip_id: str, bee_type: str) -> bool | None:
    """True/False from an explicit bee list or 'any'; None when the rule is
    prose ("rare or epic bees", "any mutated bee") and can't be judged here.
    ponytail: prose rules unparsed; parse them when H4 needs to auto-equip."""
    eq = (load().get("beequips") or {}).get(beequip_id)
    if not eq:
        return False
    colour = eq.get("colour")
    if colour and _bee_colour(bee_type) not in (colour, None):
        return False
    bees = eq.get("bees")
    if bees == "any":
        return True
    if isinstance(bees, list):
        return bee_type in bees
    return None


def best_for(hive_colour: str, bee_type: str | None = None) -> list[dict]:
    """Ranked picks for a hive colour, best first, each with its reason.

    With `bee_type`, only picks that bee should wear: first the colour
    ranking's entries naming it, then any other beequip it can provably wear
    (marked unranked)."""
    data = load()
    eqs = data.get("beequips") or {}
    out, seen = [], set()
    for rank, row in enumerate((data.get("rankings") or {}).get(hive_colour) or [], 1):
        on = row.get("wearers") or []
        if bee_type and bee_type not in on:
            continue
        eq = eqs.get(row["beequip"]) or {}
        out.append({"beequip": row["beequip"], "rank": rank, "count": row.get("count", 1),
                    "wearers": on, "why": row.get("why", ""),
                    "beesmas_only": bool(eq.get("beesmas")),
                    "confidence": eq.get("confidence", "unverified")})
        seen.add(row["beequip"])
    if bee_type:
        for bid, eq in eqs.items():
            if bid not in seen and can_wear(bid, bee_type):
                out.append({"beequip": bid, "rank": None, "count": 1, "wearers": [bee_type],
                            "why": f"{bee_type} can wear it; not in the {hive_colour} ranking: "
                                   + ", ".join(eq.get("stats") or []),
                            "beesmas_only": bool(eq.get("beesmas")),
                            "confidence": eq.get("confidence", "unverified")})
    return out


def _name(beequip_id: str) -> str:
    return beequip_id.replace("_", " ").title()


def plan(hive_colour: str, bees: dict, owned=None, gifted=(), level=None) -> list[dict]:
    """Which beequip would go on which bee (ROADMAP H4), LOOK-ONLY: nothing
    here equips anything; run_farm only logs it.

    `bees` {type: count} (the bee menu's read, var/bees.json); `owned`
    {beequip_id: count} from account.yaml, or None while unknown -- then every
    ranked pick is planned and marked not owned ("if he had it"). `gifted` the
    types with a gifted copy (the menu's dark star); `level` the hive level,
    standing in for each bee's own (the menu does not read them).
    One beequip per bee; the colour ranking's order and counts decide.
    ponytail: by type, not slot -- per-slot placement (the guide: best CA% on
    the most-mutated Diamond nearest the balloon) when hive_slots.json is trusted."""
    data = load()
    eqs = data.get("beequips") or {}
    free = {k: int(v) for k, v in (bees or {}).items() if int(v or 0) > 0}
    free_gifted = {t: 1 for t in gifted or ()}   # the menu says "a gifted one", not how many
    left = None if owned is None else {k: int(v) for k, v in owned.items()}
    out = []
    for row in (data.get("rankings") or {}).get(hive_colour) or []:
        bid = row["beequip"]
        eq = eqs.get(bid) or {}
        for _ in range(int(row.get("count", 1))):
            if left is not None and left.get(bid, 0) <= 0:
                break
            if level is not None and int(eq.get("lvl") or 0) > int(level):
                if left is not None:      # said only of one he has
                    out.append({"beequip": bid, "bee": None, "owned": True,
                                "why": f"needs a level-{eq['lvl']} bee; the hive is level {level}"})
                break
            pool = free_gifted if eq.get("gifted") else free
            bee = next((b for b in row.get("wearers") or []
                        if pool.get(b, 0) > 0 and free.get(b, 0) > 0
                        and can_wear(bid, b) is not False), None)
            if bee is None:
                break
            free[bee] -= 1
            if eq.get("gifted"):
                free_gifted[bee] -= 1
            if left is not None:
                left[bid] -= 1
            out.append({"beequip": bid, "bee": bee, "owned": left is not None,
                        "why": row.get("why", "")})
    return out


def would_lines(picks: list[dict]) -> list[str]:
    """The log's words for `plan`: "beequips would: put X on a Y Bee because ..."."""
    if not picks:
        return ["beequips would: nothing -- no ranked beequip fits a bee the hive holds"]
    lines = []
    for p in picks:
        name = _name(p["beequip"])
        if p["bee"] is None:
            lines.append(f"beequips would: leave {name} off -- {p['why']}")
            continue
        own = "" if p["owned"] else " (if he had it: his beequips are not known yet)"
        lines.append(f"beequips would: put {name} on a {p['bee'].title()} Bee"
                     f"{own} because {p['why']}")
    return lines


def owned_from_account() -> dict | None:
    """{beequip_id: count} from account.yaml `beequips.owned`, None while unknown."""
    owned = (knowledge.account().get("beequips") or {}).get("owned")
    return dict(owned) if isinstance(owned, dict) else None

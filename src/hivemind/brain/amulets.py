"""Amulet knowledge: what each amulet can roll, and which roll is better (ROADMAP K9).

The facts live in data/knowledge/amulets.yaml (the wiki's DATAMINED table,
cited there). This only scores rolls someone has already read; nothing here
reads the screen or presses a button. vision/amulet.py still answers every
Keep Old / Replace table with "Keep Old" -- this is the knowledge a later
reader of the table's stats would decide with.
"""
from __future__ import annotations

from . import knowledge

COLOURS = ("Red", "Blue", "White")
TIERS = ("bronze", "silver", "gold", "diamond", "supreme")


def load() -> dict:
    """{'sources', 'groups', 'amulets'}; {} if the file is missing."""
    return knowledge.amulets()


def stats(amulet_id: str) -> list[dict]:
    """Every stat the amulet can have: the fixed ones and every pool member."""
    out = []
    for mod in (load().get("amulets") or {}).get(amulet_id, {}).get("mods") or []:
        out.extend(mod["pool"] if "pool" in mod else [mod])
    return out


def _off_colour(stat_name: str, hive_colour: str | None) -> bool:
    """'Red Pollen', 'Instant Red Conversion', 'Red Bomb Pollen' in a blue
    hive. Multi-colour names ('Red/Colorless/Blue Bee Attack') and colourless
    ones always count."""
    colour = next((w for w in stat_name.split() if w in COLOURS), None)
    return bool(hive_colour and colour) and colour.lower() != hive_colour.lower()


def roll_quality(amulet_id: str, rolled: dict, hive_colour: str | None = None) -> dict:
    """How good a read roll is: each stat's place in its range, 0 (min) .. 1 (max).

    `rolled` {display name: value}, as amulets.yaml names them ('Blue Pollen':
    0.45, 'Convert Rate': 1.12, 'Pop Star': 1). A name the amulet cannot have
    lands in `unknown`; a stat of another hive colour in `skipped`. `score` is
    the mean over the rest, None when nothing counted.
    ponytail: every counted stat weighs the same; weigh by honey/hr once K1's
    model can price a stat."""
    by_name: dict[str, list[dict]] = {}
    for s in stats(amulet_id):
        by_name.setdefault(s["stat"], []).append(s)
    per, unknown, skipped = {}, [], []
    for name, value in rolled.items():
        cands = by_name.get(name)
        if not cands:
            unknown.append(name)
            continue
        if _off_colour(name, hive_colour):
            skipped.append(name)
            continue
        # SAME NAME, SEVERAL RANGES (the Cog's 'Red Bee Attack' 1-1 and 1-2):
        # place the value in the range that holds it, else the nearest one.
        s = min(cands, key=lambda c: 0 if "range" not in c else
                max(c["range"][0] - value, value - c["range"][1], 0))
        lo, hi = s.get("range") or (1, 1)
        per[name] = 1.0 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    score = sum(per.values()) / len(per) if per else None
    return {"score": score, "per_stat": per, "unknown": unknown, "skipped": skipped}


def compare(old: tuple[str, dict], new: tuple[str, dict], hive_colour: str | None = None) -> dict:
    """Keep Old or Replace, with the reason. `old`/`new` are (amulet_id, rolled).

    Same amulet: the better roll_quality wins, a tie keeps the old (Replace
    cannot be undone, wiki Amulet). Another tier of one group: the higher tier
    ("Higher tier amulets grant more and better buffs", wiki Shell/Stick
    Bug/Cog). Different groups never meet in one table (one amulet per type),
    so they get 'keep'. LOOK-ONLY knowledge: the caller decides what to click."""
    data = load().get("amulets") or {}
    (oid, orolls), (nid, nrolls) = old, new
    o, n = data.get(oid) or {}, data.get(nid) or {}
    if not o or not n or o.get("group") != n.get("group"):
        return {"choice": "keep", "why": f"cannot compare {oid} with {nid}"}
    if oid != nid:
        ot, nt = TIERS.index(o.get("tier", "bronze")), TIERS.index(n.get("tier", "bronze"))
        better = nt > ot
        return {"choice": "replace" if better else "keep",
                "why": f"{n['name'] if better else o['name']} is the higher tier"}
    oq = roll_quality(oid, orolls, hive_colour)["score"]
    nq = roll_quality(nid, nrolls, hive_colour)["score"]
    if oq is None or nq is None or nq <= oq:
        return {"choice": "keep", "why": f"new roll {nq} is not better than old {oq}"}
    return {"choice": "replace", "why": f"new roll {nq:.2f} beats old {oq:.2f}"}

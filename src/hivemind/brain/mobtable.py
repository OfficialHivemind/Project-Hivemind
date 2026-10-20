"""The mob table (ROADMAP K7): every mob the bot can meet, from
data/knowledge/mobs.yaml -- the six bug-run mobs (`mobs:`), the bosses and
the Sprout (`other_mobs:`) and the Vicious Bee (`rogue_vicious_bee:`).

Each value there is tagged "measured: ..." or "[assumed: ...]" in the mob's
`src:` map (tests/unit/test_mobtable.py holds every mob to it); the measured
respawns, drops and deaths are in docs/pending/mobs-k7.md.

    mob(name)                 the mob's row (a dict), or None
    mobs_in(field, night)     the mobs that live in a field, in mobs.yaml order
    danger(field, night)      0 none .. 3 high: the worst mob there
    respawn(name)             seconds, or None (no timer, or unknown mob)
    ticket_rate(name)         (tickets a kill, source): measured, blended with the wiki
    kill_honey(name)          (honey a kill, source): the same blend

A field the Werewolf only defends (`also_defends`) counts as its field. With
`night=True` the fields where the feed named kills off the wiki's list
(`also_seen`) count too -- why the mobs are there is unproven (mobs.yaml).
"""
from __future__ import annotations

from functools import lru_cache

from . import knowledge


@lru_cache(maxsize=1)
def table() -> dict:
    """{slug: row} for every mob; a missing or broken file is an empty table."""
    body = knowledge._load("mobs.yaml")
    if not isinstance(body, dict):
        return {}
    out = {}
    for section in ("mobs", "other_mobs"):
        for slug, row in (body.get(section) or {}).items():
            if isinstance(row, dict):
                out[str(slug)] = row
    vicious = body.get("rogue_vicious_bee")
    if isinstance(vicious, dict):
        out["rogue_vicious_bee"] = vicious
    return out


def mob(name: str) -> dict | None:
    return table().get(name)


def fields_of(row: dict, night: bool = False) -> list:
    where = row.get("fields") or ()
    out = [str(f) for f in where]          # a dict's keys or a list's items
    out += [str(f) for f in row.get("also_defends") or ()]
    if night:
        out += [str(f) for f in row.get("also_seen") or ()]
    return out


def mobs_in(field: str, night: bool = False) -> tuple:
    """The mobs of `field`. A daytime-only mob (`night: day`) is left out at
    night and a night-only one (`night: night`) by day."""
    out = []
    for slug, row in table().items():
        when = row.get("night", "both")
        if (when == "night" and not night) or (when == "day" and night):
            continue
        if field in fields_of(row, night):
            out.append(slug)
    return tuple(out)


def danger(field: str, night: bool = False) -> int:
    return max((int(table()[m].get("danger") or 0) for m in mobs_in(field, night)),
               default=0)


def respawn(name: str) -> float | None:
    row = mob(name)
    if row is None or row.get("respawn_seconds") is None:
        return None
    return float(row["respawn_seconds"])


# WHAT A KILL IS WORTH: MEASURED, WITH THE WIKI AS THE PRIOR. The wiki's ticket
# chances are about 10x what reached this account (docs/pending/mobs-k7.md,
# var/mob_kills.jsonl + mob_drops.jsonl 3-19 Oct 2026, mobs.yaml `measured:`):
#   Ladybug 0 of 1,214 kills (wiki 2%)    Rhino Beetle 0 of 1,952 (wiki 2%)
#   Spider 8 of 283 = 2.8% (wiki 25%)     Mantis 4 of 527 = 0.8% (wiki 20%)
#   Scorpion 2 of 155 = 1.3% (wiki 13.3%) Werewolf 54 of 171 = 32% (wiki 50%)
# so pricing by the wiki sent the AI after Spiders and Mantises for tickets
# that do not come. A Beta(PRIOR_KILLS x wiki, PRIOR_KILLS x (1 - wiki)) prior
# is the wiki's rate worth PRIOR_KILLS kills; its posterior mean is
#   (PRIOR_KILLS x wiki + measured) / (PRIOR_KILLS + kills)
# -- the wiki until kills come in, the bot's own rate once they outnumber the
# prior, and never a flat 0 from a few unlucky kills.
#
# HONEY THE SAME WAY, MEASURED rather than wiki x a multiplier: the measured
# honey a kill is 0.4-12x the wiki's (Spider 416 vs 1,000, Mantis 2,988 vs
# 250), so no one account multiplier fits it -- the feed's figure already
# holds the multipliers AND the tokens the bees left lying, which is what a
# kill actually pays. The wiki's honey is the prior: a floor below every
# measured figure but the Spider's.
PRIOR_KILLS = 50


def blend(wiki: float, measured_total: float, kills: int) -> tuple:
    """(posterior mean a kill, source) for `measured_total` over `kills`."""
    kills = max(0, int(kills or 0))
    rate = (PRIOR_KILLS * float(wiki) + float(measured_total)) / (PRIOR_KILLS + kills)
    source = ("wiki" if kills == 0 else
              f"measured, {kills} kills" if kills >= PRIOR_KILLS else
              f"wiki + {kills} kills")
    return rate, source


def _counts(row: dict) -> tuple:
    measured = row.get("measured") or {}
    drops = row.get("drops") or {}
    kills = int(measured.get("kills") or 0)
    honey = (drops.get("honey") or {}).get("mean")
    return kills, int(measured.get("ticket_kills") or 0), float(honey or 0) * kills


def ticket_rate(name: str, kills: int | None = None,
                ticket_kills: int | None = None) -> tuple:
    """(tickets a kill, source). The counts default to mobs.yaml `measured:`;
    act/bugrun passes the live logs' own. An unknown mob is (0.0, "unknown")."""
    row = mob(name)
    if row is None:
        return 0.0, "unknown"
    k, t, _ = _counts(row)
    if kills is not None:
        k, t = kills, int(ticket_kills or 0)
    return blend(float(row.get("ticket_chance") or 0.0), t, k)


def kill_honey(name: str, kills: int | None = None,
               honey_total: float | None = None) -> tuple:
    """(honey a kill, source), the same blend over the wiki's `honey`."""
    row = mob(name)
    if row is None:
        return 0.0, "unknown"
    k, _, h = _counts(row)
    if kills is not None:
        k, h = kills, float(honey_total or 0.0)
    return blend(float(row.get("honey") or 0.0), h, k)

"""The badge planner: which field pays off its Ace badge soonest, and when
that adds up to ten of them.

THE OWNER, 2026-10-11 (docs/pending/brain-research-2.md, "research everything,
build everything"): pass 2 ranked this P4 -- "Badges are the cheap route to
better sprinklers." Golden Gushers (3 sprinklers, radius 8, power 8, against
Silver Soakers' 2/7/7) need 10 Ace badges plus 333,333,333 honey
(data/knowledge/economy.yaml:125 `golden_gushers: {..., badges: "10 Ace",
honey: 333333333}`). A field's own Ace badge needs 25,000,000 pollen collected
on that field, and Cadet + Hotshot + Ace together pay 30 tickets per field
(tickets.yaml:27 `tickets_by_tier: {cadet: 5, hotshot: 10, ace: 15, ...}`,
5+10+15=30) plus a permanent buff (Pine Tree +15% blue field capacity, Bamboo
+15% blue pollen, Blue Flower +9% instant blue conversion, Sunflower +30%
capacity -- brain-research-2.md §6). `act/badges.py` can already read the
badge menu's text; turning that OCR into a per-field pollen count is a
separate job (vision, not here). This module is the pure part: given whatever
progress IS known and the field rates `brain/fieldnotes` already measures, say
which field to park on next.

Nothing here acts, reads a screen, or spends anything -- see the owner rules
in blenderplan.py's docstring, which hold here too (no Robux, ever; this
module does not touch tickets or honey, it only prices time).
"""
from __future__ import annotations

# brain-research-2.md §6, "Other high-value items" > "Badges are the cheap
# route to better sprinklers": "A field's Ace badge needs 25M pollen
# collected there."
ACE_POLLEN = 25_000_000

# data/knowledge/economy.yaml:125
#   golden_gushers: {count: 3, radius: 8, power: 8, rate_s: 4.5, setup_s: 5,
#                    badges: "10 Ace", honey: 333333333}
GUSHERS_ACES_NEEDED = 10
GUSHERS_HONEY = 333_333_333


def next_aces(badge_progress: dict, field_rates: dict) -> list:
    """Rank fields by seconds left to that field's Ace badge (ACE_POLLEN).

    `badge_progress`: {field: pollen already counted toward that field's Ace
    (0 or absent if unstarted)}.
    `field_rates`: {field: measured pollen/second on that field} -- the same
    shape `brain/fieldnotes` measures pollen/s in (paid-seconds rate where
    there is one, diluted rate otherwise; see that module for how it is
    earned -- this function only ranks what it is given).

    Returns [(field, seconds_remaining, pollen_remaining)], soonest first.
    A field already at or past ACE_POLLEN, or with no positive rate, is left
    out -- there is nothing to rank it on, not a guess at zero.
    """
    out = []
    for field_name, rate in (field_rates or {}).items():
        rate = float(rate or 0.0)
        if rate <= 0:
            continue
        have = float((badge_progress or {}).get(field_name, 0) or 0)
        remaining = ACE_POLLEN - have
        if remaining <= 0:
            continue
        out.append((field_name, remaining / rate, remaining))
    return sorted(out, key=lambda row: row[1])


def gushers_eta(badge_progress: dict, field_rates: dict, *, aces_held: int = 0) -> dict:
    """Seconds of sequential gathering (one field at a time, cheapest first)
    to reach GUSHERS_ACES_NEEDED Ace badges in total, and which fields that
    means working.

    `aces_held`: Ace badges already read off ANY category -- field badges
    (Pine Tree, Bamboo, ...) and the account-wide ones alike (Honey, Quest,
    Battle, Ability, Goo, Playtime, Sticker Stack -- economy.yaml's own
    reading of this account held Hotshot there, not yet Ace). They all count
    the same toward the Guild's "10 Ace" gate.

    Returns {fields: [...], seconds: total, honey_needed: GUSHERS_HONEY,
    short: how many more Aces still have no field to rank (no rate known)}.
    """
    need = max(0, GUSHERS_ACES_NEEDED - int(aces_held))
    ranked = next_aces(badge_progress, field_rates)
    chosen = ranked[:need]
    return {
        "fields": [row[0] for row in chosen],
        "seconds": sum(row[1] for row in chosen),
        "honey_needed": GUSHERS_HONEY,
        "short": need - len(chosen),
    }


if __name__ == "__main__":
    # A field already past the threshold is left out.
    progress = {"pine_tree": 20_000_000, "rose": 0, "bamboo": 25_000_000, "cactus": 1_000_000}
    rates = {"pine_tree": 1_470.0, "rose": 930.0, "bamboo": 300.0, "cactus": 0.0}
    ranked = next_aces(progress, rates)
    # bamboo is done (left out); cactus has no rate (left out); pine_tree is
    # closer in pollen AND faster, so it must come first
    assert [f for f, _s, _p in ranked] == ["pine_tree", "rose"], ranked
    pine_seconds = (ACE_POLLEN - 20_000_000) / 1_470.0
    assert abs(ranked[0][1] - pine_seconds) < 1e-6
    assert ranked[0][2] == ACE_POLLEN - 20_000_000

    # no progress recorded at all: ranked purely by rate, against the full 25M
    fresh = next_aces({}, {"pine_tree": 1_000.0, "rose": 500.0})
    assert [f for f, _s, _p in fresh] == ["pine_tree", "rose"]
    assert fresh[0][2] == ACE_POLLEN

    eta = gushers_eta(progress, rates, aces_held=8)
    assert eta["short"] == 0          # only 2 more Aces needed, 2 fields rank
    assert eta["fields"] == ["pine_tree", "rose"]
    assert eta["honey_needed"] == GUSHERS_HONEY

    eta_short = gushers_eta(progress, rates, aces_held=0)
    assert eta_short["short"] == 10 - len(ranked)   # only 2 fields rank at all

    print("badgeplan: self-check OK")

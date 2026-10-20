"""Which stickers the Sticker Stack may take: data/knowledge/stickers.yaml.

The owner, 2026-10-07: teach it the Sticker Stack, and which stickers to keep
for their rarity. The table ranks all 260 stickers by their easiest source (the
wiki's own data; the file's header says how), and `keep_from` is the line: a
sticker at or above it is never stacked. Stacking consumes the sticker, and
each type stacks once, so the commonest new type goes first.
"""
from __future__ import annotations

import yaml

from ..datapaths import data

PATH = data("knowledge", "stickers.yaml")


def load(path=PATH) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def keep(name: str, table: dict) -> bool:
    """Kept for rarity -- and so is a sticker the table does not know: an
    unknown sticker is never consumed on a guess."""
    row = table["stickers"].get(name)
    return row is None or int(row["rarity"]) >= int(table["keep_from"])


def stackable(held, stacked, table: dict) -> list[str]:
    """The held stickers the stack may take: not kept, not stacked before,
    the commonest first."""
    done = set(stacked)
    pick = [n for n in dict.fromkeys(held) if n not in done and not keep(n, table)]
    return sorted(pick, key=lambda n: (int(table["stickers"][n]["rarity"]), n))


# K10. STACK VALUE AND THE PRINTER, from the `stack:` and `printer:` blocks.
def buff_seconds(stacked: int, table: dict) -> int:
    """How long one stacking (or 25 tickets) keeps the buff: 900 s + 10 s a
    type ever stacked, capped at 1 h (wiki, not measured)."""
    s = table["stack"]
    return min(int(s["buff_max_s"]), int(s["buff_base_s"]) + int(s["buff_per_sticker_s"]) * int(stacked))


def badge_pollen(stacked: int, table: dict) -> int:
    """The badge's permanent % bee pollen at this many types stacked."""
    got = [pct for n, pct in table["stack"]["badge"].items() if stacked >= int(n)]
    return max(got, default=0)


def reward_tickets(name: str, table: dict) -> int:
    """Tickets a FIRST stacking of `name` pays (its Stack Reward); 0 for a
    non-ticket reward or a name the table does not know."""
    reward = str((table["stickers"].get(name) or {}).get("reward", "")).split()
    return int(reward[0]) if len(reward) == 2 and reward[1].startswith("Ticket") and reward[0].isdigit() else 0


def printer_tickets(table: dict, stacked=(), egg: str = "basic") -> float:
    """Expected Stack-Reward tickets of one print: the egg's odds times each
    print's reward. A type already stacked, or kept for rarity, pays nothing."""
    done = set(stacked)
    return sum(pct / 100 * reward_tickets(n, table)
               for pct, names in table["printer"][egg] for n in names
               if n not in done and not keep(n, table))

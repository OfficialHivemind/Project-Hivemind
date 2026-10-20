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

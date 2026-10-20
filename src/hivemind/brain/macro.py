"""Macro mode's field choice (ROADMAP U16): the user's own list, in order.

THE OWNER, 2026-10-16: the app is a classic macro as well as an auto-progress
AI. Macro mode is the classic loop the user sets up -- their fields, their
patterns, their times -- with nothing decided for them; AI mode is the
auto-progress AI as before. Both settings (`mode.macro`, `macro.fields`) are
checked in world/settings; this module only says which entry the next trip
takes, so run_farm's `plan` can be tested without a game.
"""
from __future__ import annotations

from ..world.settings import macro_fields, macro_pattern_label


def active(settings) -> list[dict]:
    """The entries to rotate through, or [] in AI mode (the switch off, or an
    empty list): [] is what leaves `plan` exactly as it was."""
    try:
        if not bool(settings.get("mode.macro")):
            return []
        return macro_fields(settings.get("macro.fields"))[0]
    except Exception:
        return []                    # a broken setting is AI mode, never a guess


def slug(name: str) -> str:
    """'Pine Tree' -> 'pine_tree', the planner's own field names
    (brain/decide.from_settings does the same for `gather.field`)."""
    return name.strip().lower().replace(" ", "_")


def pick(entries: list[dict], start: int, usable) -> tuple[int, dict] | None:
    """The first entry from `start` on (wrapping round) whose field
    `usable(slug)` allows: (its index, it). None when none can be used now --
    a field a boss guards, or one with no route, is passed over rather than
    walked into (the safety rails are both modes')."""
    n = len(entries)
    for k in range(n):
        i = (start + k) % n
        if usable(slug(entries[i]["field"])):
            return i, entries[i]
    return None


def describe(index: int, count: int, entry: dict) -> str:
    """The run log's line: 'macro: field 2 of 3, Pine Tree, 15 min, pattern
    Snake, wide (232 studs)'."""
    minutes = entry["minutes"]
    stay = f"{minutes} min" if minutes else f"until the bag is {entry['convert_at']}% full"
    return (f"macro: field {index + 1} of {count}, {entry['field']}, {stay}, "
            f"pattern {macro_pattern_label(entry['pattern'])}")

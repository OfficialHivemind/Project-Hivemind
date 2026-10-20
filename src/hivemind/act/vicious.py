"""The Vicious Bee at night: Natro's hunt, for the stingers the Cobalt Guard needs.

WHY. The Cobalt Guard wants 100 Stingers (wiki), 87 are held
(docs/pending/brain-research-4.md rec 9), and a kill is the one source that
costs no tickets: 1 stinger at levels 1-3, 2 at 4-6, plus "a daily bonus of
5 Stingers ... for the first Rogue Vicious Bee defeated that day, with a
cooldown of 22 hours" (wiki Rogue_Vicious_Bee).

NATRO'S HUNT (submacros/natro_macro.ahk:18214-18560, read 2026-10-12): at
night, from the hive, each enabled field in turn (VBData, :18282): walk there
(`nm_gotoField`, our natro_out_* routes), hold the tool, walk a search pattern
over it -- an alignment, a left-back-right-back zigzag `reps` times, a last
left leg (:18374) -- until the server message says it is attacking (that is
how it is found: stepping on its spike calls it up), then a four-tile square
with a second's pause at each corner (:18488) until the message says it is
defeated, a death, or 5 minutes in that field (:18499); a field where nothing
answered ends in a reset to the next. No new field after 5 minutes in all
(:18349 "This is built into the game" -- wiki: its spike "despawn[s] after five
minutes"). It skips a field whose bee gate (`bees`) the hive does not pass
(:18345). Fuzzy Macro (src/modules/macro.py:5811-5928) is the same tour in the
same order, reads the same messages off the notification column, and gives
the fight 3 minutes (:5911).

WHAT IS DIFFERENT HERE, ALL OF IT BECAUSE THE ACCOUNT IS WEAK FOR BOSSES
(2026-10-12: the Tunnel Bear, 10,000 HP, killed the character 6 s after it
arrived): the tour goes EASIEST FIRST by the wiki's levels and stops at
the beatable level (mobs.yaml rogue_vicious_bee), where Natro goes hardest
first; a death ends the hunt (Natro walks back to the field); and each loss since the last kill doubles the wait, as
act/beetle's losses in a row do.
The messages are read by tesseract (vision/amulet.read_words) instead of
Natro's chat bitmaps, row by row.
"""
from __future__ import annotations

from typing import NamedTuple

from ..brain.calendar import VICIOUS_COOLDOWN_S
from . import beetle

load, save = beetle.load, beetle.save    # the same small JSON state file

TILE = 4.0                        # studs in one of Natro's tiles (lib/Walk.ahk)


class Field(NamedTuple):
    node: str                     # router node (natro_out_<node>)
    bees: int                     # Natro's gate: skipped when bees >= the hive's
    reps: int                     # Natro's zigzag repeats
    lr: float                     # Natro's lrdist, tiles
    fb: float                     # fbdist
    right: float                  # initRight
    fwd: float                    # initFwd


# Natro's VBData (natro_macro.ahk:18282-18330), easiest first by the wiki's
# levels. THE LEVELS AND THE GATE ARE KNOWLEDGE, NOT CODE (ROADMAP Q3):
# data/knowledge/mobs.yaml `rogue_vicious_bee` (`levels`, `beatable_max_level`,
# with their source); a field it does not list is skipped.
FIELDS = (
    Field("clover", 0, 2, 22, 5.7, 11, 10),
    Field("spider", 5, 2, 21, 5.7, 10.5, 9.5),
    Field("cactus", 15, 1, 26, 5.5, 13, 3.7),
    Field("rose_field", 15, 2, 13, 6, 6.5, 12),
    Field("mountain_top", 25, 2, 17, 5.5, 8.5, 10.5),
    Field("pepper", 35, 1, 20, 7, 10, 7),
)

SEARCH_CAP_S = 300.0              # no new field after 5 min (Natro :18349)
MAX_FIGHT_S = 180.0               # Fuzzy's 3 minutes (macro.py:5911); Natro's is 5
COOLDOWN_S = VICIOUS_COOLDOWN_S   # 22 h after a kill: the daily bonus's cooldown
ABSENT_OPEN_S = 600.0             # nothing found: the next night is 10+ min of day away (wiki Nighttime)
# ponytail: Natro has no back-off for a lost fight; act/beetle's 2 h, doubled
LOST_RETRY_S = 7200.0
LOST_RETRY_MAX_S = 7 * 86400.0

# WHERE THE MESSAGES ARE: the notification column, Fuzzy's region for them
# (macro.py:4219-4221: the right quarter, the lower two fifths), at 1920x1080.
MESSAGE_REGION = (1440, 648, 1920, 1080)
# Words within this many pixels of each other vertically are one message:
# half the feed's measured row pitch (~29 px, vision/feed.py).
ROW_SPLIT = 14


class Book(NamedTuple):
    levels: dict                  # router node -> (lowest, highest) level
    max_level: int | None         # the highest level this hive is taken to beat


def book(path) -> Book:
    """data/knowledge/mobs.yaml `rogue_vicious_bee`. A missing or broken entry
    is an empty book: every field unknown, so the tour is empty (skip)."""
    import yaml
    try:
        row = (yaml.safe_load(open(path).read()) or {}).get("rogue_vicious_bee") or {}
        levels = {str(k): (int(v[0]), int(v[1])) for k, v in (row.get("levels") or {}).items()}
        top = row.get("beatable_max_level")
        return Book(levels, int(top) if top is not None else None)
    except (OSError, yaml.YAMLError, AttributeError, TypeError, ValueError, IndexError):
        return Book({}, None)


def tour(bees: int, known: Book, max_level: int | None = None) -> list[Field]:
    """The fields to look in, in order: past Natro's bee gate, every level the
    field spawns at no higher than the beatable one. Unknown levels or an
    unknown gate: skipped."""
    top = known.max_level if max_level is None else max_level
    if top is None:
        return []
    return [f for f in FIELDS if f.bees < bees and f.node in known.levels
            and known.levels[f.node][1] <= top]


QUEST_SLUG = "vicious_bee"        # questneeds.mob_slug("Vicious Bees")


def quest_wants(mobs_wanted) -> int:
    """How many more Vicious Bees the held quests want (questneeds
    Needs.mobs_wanted(), e.g. 'Patterns and Probability': "Defeat 7 Vicious
    Bees. 5/7", read 29 Sep - 15 Oct)."""
    try:
        return max(0, int((mobs_wanted or {}).get(QUEST_SLUG, 0) or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


def quest_line(fields: list[Field], known: Book, wanted: int) -> str:
    """The look-only sentence for a quest's Vicious Bee step."""
    if not fields:
        return (f"vicious would: not go -- the quest wants {wanted} kill(s), but no field "
                f"of its is past the bee gate at a level this hive is taken to beat "
                f"(mobs.yaml rogue_vicious_bee)")
    f = fields[0]
    lo, hi = known.levels[f.node]
    return (f"vicious would: go to {f.node.replace('_', ' ')} for a level {lo}-{hi} "
            f"Vicious Bee (quest wants {wanted} kill(s))")


def _walk(keys: str, tiles: float) -> dict:
    return {"op": "walk", "keys": keys, "studs": round(tiles * TILE, 2)}


def search_steps(field: Field) -> list[dict]:
    """Natro's search (natro_macro.ahk:18374): line up, zigzag, a last leg."""
    out = [_walk("d", field.right), _walk("w", field.fwd)]
    for _ in range(field.reps):
        out += [_walk("a", field.lr), _walk("s", field.fb),
                _walk("d", field.lr), _walk("s", field.fb)]
    return out + [_walk("a", field.lr)]


# Natro's battle pattern (natro_macro.ahk:18488-18497), repeated.
FIGHT_STEPS = (
    _walk("w", 4), {"op": "pause", "seconds": 1.0},
    _walk("d", 4), {"op": "pause", "seconds": 1.0},
    _walk("s", 4), {"op": "pause", "seconds": 1.0},
    _walk("a", 4),
)


def rows(words) -> list[str]:
    """tesseract's words (anything with .text, .y, .h) as one string per
    message row, top to bottom. Row by row so a "Defeated Ladybug!" in the
    feed beside the Vicious Bee's own line is never read as its defeat."""
    out: list[list] = []
    for w in sorted(words, key=lambda w: w.y + w.h / 2):
        mid = w.y + w.h / 2
        if out and abs(mid - out[-1][0]) <= ROW_SPLIT:
            out[-1][1].append(w.text)
        else:
            out.append([mid, [w.text]])
    return [" ".join(texts) for _, texts in out]


def heard(lines) -> str:
    """"killed", "died", "left", "found" or "" from the message rows -- the
    wiki's words: "Vicious Bee is attacking {Username} in the {Field}!",
    "Vicious Bee has been defeated!", "Vicious Bee left...", and the feed's
    "You died"."""
    said = ["".join(str(x).lower().split()) for x in lines]
    vicious = [s for s in said if "vicious" in s]
    if any("defeated" in s for s in vicious):
        return "killed"
    # "You diee", "You dic": tesseract on Fuzzy's crop of it (2026-10-12)
    if any("youdi" in s for s in said):
        return "died"
    if any("left" in s for s in vicious):
        return "left"
    if any("attack" in s for s in vicious):
        return "found"
    return ""


def record(state: dict, result: str, now: float, quest_left: int = 0) -> dict:
    """The state after a hunt: "killed", "absent", or a loss ("died", "time",
    "left", "walk"). `quest_left`: the kills a quest wanted BEFORE this hunt
    (quest_wants); with more still owed after a kill, the next night is the
    wait, not the daily bonus's 22 h (ROADMAP Q3; timing only)."""
    out = dict(state)
    out["tries"] = (list(state.get("tries") or []) + [{"at": now, "result": result}])[-20:]
    if result == "killed":
        out["killed_at"] = now
        out["next_at"] = now + (ABSENT_OPEN_S if quest_left > 1 else COOLDOWN_S)
    elif result == "absent":
        out["next_at"] = now + ABSENT_OPEN_S
    else:
        # each loss since the last KILL doubles the wait -- unlike act/beetle,
        # a night with no bee found ("absent", most nights) proves nothing
        # about the fight, so it does not reset the count (only the 20 kept
        # tries are counted)
        lost = 0
        for t in reversed(out["tries"]):
            if t.get("result") == "killed":
                break
            lost += t.get("result") != "absent"
        out["next_at"] = now + min(LOST_RETRY_S * 2 ** (lost - 1), LOST_RETRY_MAX_S)
    return out


def due(state: dict, now: float) -> bool:
    return now >= float(state.get("next_at", 0.0) or 0.0)

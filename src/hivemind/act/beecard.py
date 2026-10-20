"""A bee's card, read: the card a hatch, a jelly or a click on a cell's face
brings up -- "You hatched a..." / "Festive Bee!!!" / "Red Event" / its words.

MEASURED 2026-10-03 on the Festive Bee's card (tests/fixtures/hive/
new-type-card.jpg): every line sits at a fixed place from the card's red close
box (vision/hivecell.new_type_card_close finds it), and tesseract reads them as
'You hatched a...', 'FestiveBeel!' (the spaces gone, the bangs half letters)
and 'RedlEvent |'. So the name is matched to a known bee type with one letter
of slack, only when no other type is as near, and the tier comes from the
rarity line, not from the bangs. Anything else is unknown -- never a guess.
"""
from __future__ import annotations

import re

# each line's box from the close box's centre (x0, y0, x1, y1), MEASURED
CARD_BAR = (20, -16, 290, 16)
CARD_NAME = (-20, 28, 290, 78)
CARD_RARITY = (-10, 186, 285, 218)
RARITIES = ("common", "rare", "epic", "legendary", "mythic", "event")


def read_card(frame, at, ocr) -> dict:
    """{"bar", "name", "rarity"}: the three lines' words, `at` the close box."""
    x, y = int(at[0]), int(at[1])

    def box(rel):
        return (max(0, x + rel[0]), max(0, y + rel[1]), x + rel[2], y + rel[3])
    return {"bar": str(ocr(frame, box(CARD_BAR)) or ""),
            "name": str(ocr(frame, box(CARD_NAME)) or ""),
            "rarity": str(ocr(frame, box(CARD_RARITY)) or "")}


def _letters(text) -> str:
    return re.sub(r"[^a-z]", "", str(text or "").lower())


def bee_of(name_text, labels: dict) -> str | None:
    """The bee type slug the card's name line names, or None. `labels` is
    {slug: "Demon Bee"} (data/knowledge/bee_types.yaml). The line is cut at
    its last "bee" (the bangs read as letters after it) and matched with one
    edit of slack -- "Demo Bee" and "Demon Bee" are one letter apart, so a
    match no nearer than the next type's is no match."""
    from .inventory import _edits
    read = _letters(name_text)
    cut = read.rfind("bee")
    if cut < 0:
        return None
    read = read[:cut + 3]
    scored = sorted((_edits(read, _letters(label)), slug) for slug, label in labels.items())
    if not scored or scored[0][0] > 1:
        return None
    if len(scored) > 1 and scored[1][0] <= scored[0][0]:
        return None
    return scored[0][1]


def rarity_of(rarity_text) -> tuple:
    """(colour, rarity) from the rarity line ("Red Event"), each None unread.
    One letter of slack at the line's end: MEASURED 2026-10-05 22:55 the roll
    card's "Epic" read "' Epie |" -- and a "Mythie" read the same way must
    still stop a roll."""
    from .inventory import _edits
    read = _letters(rarity_text)
    rarity = next((r for r in RARITIES if r in read), None)
    if rarity is None:
        near = [r for r in RARITIES if len(read) >= len(r) - 1
                and _edits(read[-len(r):], r) <= 1]
        rarity = near[0] if len(near) == 1 else None
    colour = ("red" if read.startswith("red") else "blue" if read.startswith("blue")
              else "colourless" if read.startswith(("colo", "white")) else None)
    return colour, rarity


def gifted(card: dict) -> bool:
    """Whether any line of the card says gifted (its form is not yet measured,
    so a roll stops on the word anywhere)."""
    return any("gift" in _letters(v) for v in (card or {}).values())


def names_in(text, labels: dict) -> list:
    """The bee types whose full label ("Demon Bee") stands in `text` as words,
    for a card whose lines are not where the hatch card's are -- the card a
    click on a cell's face brings (its name with "(Lvl 8)" and the stats under
    it, MEASURED 2026-10-04: 'am ,m Demon Bee (Lvl 8) . : M p Bond:|').
    "Demo Bee" is not in "Demon Bee": the words must match whole."""
    words = " " + re.sub(r"[^a-z]+", " ", str(text or "").lower()) + " "
    return sorted(slug for slug, label in labels.items()
                  if " " + re.sub(r"[^a-z]+", " ", str(label).lower()).strip() + " " in words)


def rolled_into(card: dict, labels: dict) -> list:
    """The bee types a roll card's words name as what the bee became, when its
    name line is unreadable: the whole card less "Your X Bee transformed into
    a...", which names the bee it WAS, with "Bee!" read as "Beel" taken for
    "Bee". MEASURED 2026-10-07 10:22: the name line read 'ETe Bee!', the bar
    'Your Honey Bee transformed into a...' and the card 'I Rad Beel | Red Rare
    A stylish bee...' -- the bar's Honey Bee was taken as the result, and an
    hour of rolls looked for a Honey Bee that was a Rad Bee."""
    text = str((card or {}).get("whole") or "")
    text = re.sub(r"(?is)\byour\b.*?\btransformed\s+into\s+an?\b", " ", text)
    text = re.sub(r"(?i)\bbeel\b", "bee", text)
    return names_in(text, labels)


def rarity_in(text) -> tuple:
    """(colour, rarity) from "Red Legendary" anywhere in a card's words (the
    click card's rarity bar, MEASURED 2026-10-05 22:38), each None unread."""
    m = re.search(r"\b(red|blue|colou?rless|white)\s*(" + "|".join(RARITIES) + r")\b",
                  str(text or "").lower())
    if not m:
        return None, None
    colour = "colourless" if m.group(1) in ("colorless", "colourless", "white") else m.group(1)
    return colour, m.group(2)


# THE ROLL CARD'S "Use Another" (MEASURED 2026-10-05 22:55,
# var/shoplook/20261005-225522-jelly-roll1.jpg): a cyan button under the card,
# read 'fê Use Another' in this box from the card's red X; it uses another
# Royal Jelly on the same bee.
USE_ANOTHER = (30, 365, 245, 415)


def use_another_at(frame, at, ocr):
    """(x, y) of the roll card's "Use Another" when it reads so, else None."""
    if frame is None or at is None:
        return None
    x, y = int(at[0]), int(at[1])
    box = (x + USE_ANOTHER[0], y + USE_ANOTHER[1], x + USE_ANOTHER[2], y + USE_ANOTHER[3])
    if "useanother" not in _letters(ocr(frame, box)):
        return None
    return (box[0] + box[2]) // 2, (box[1] + box[3]) // 2

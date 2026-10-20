"""Turning the game's own prompt into a position fix.

The top-centre panel says what the character is standing at -- "Make Honey",
"Fire the Red Cannon", "Open Shop" -- and says nothing when it is standing at
nothing in particular. That is a LANDMARK in the plain sense: an instant,
certain fix on where the character is, straight from the game, needing no
calibration and no model of the world.

This module is the pure half: text in, landmark out. It knows nothing about
frames, models or input, which is what lets `world/bearings` and `nav/journey`
use it and still be tested with a list of strings.

WHERE THE TABLE COMES FROM. `data/knowledge/landmarks.yaml`, and every prompt in
it was read off a live frame -- the file says so per entry, with the date. The
matching here is deliberately strict: a prompt must CONTAIN one of the recorded
phrases, after the same normalisation the reader applies. Free text is never a
landmark, because the vision model has been measured inventing "claim hive" on
an empty crop 11 times in 24, and the only defence against a fabricated place
is refusing to recognise a place from anything but its exact recorded words.

`absent` is the other half of the signal and matters as much as a match. The
panel is not there when the character is not at anything, so "no panel" is
positive evidence of NOT being at the hive, the cannon or a shop. Callers pass
that through as an empty string; None means they could not look at all, which
is a different thing and is reported as one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SPACES = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9' ]+")


def normalise(text: str | None) -> str:
    """Lower-case, punctuation gone, one space between words."""
    if not text:
        return ""
    low = _PUNCT.sub(" ", str(text).lower().replace("’", "'"))
    return _SPACES.sub(" ", low).strip()


@dataclass(frozen=True)
class Landmark:
    """One place the game just told us we are standing at."""
    place: str                  # "hive", "red_cannon", ...
    kind: str                   # hive | transport | shop | dispenser | npc
    prompt: str                 # the recorded phrase that matched
    router_node: str | None     # the route graph's name for it, if it has one
    near: str | None = None     # a router node it is beside, when it has none
    mine: bool | None = None    # for a hive pad: ours (True) or free (False)

    @property
    def reachable(self) -> bool:
        """Can the route graph walk to this place? Recognising is not reaching."""
        return self.router_node is not None

    def describe(self) -> str:
        if self.place == "hive":
            pad = ("our own hive pad" if self.mine else
                   "a free hive pad" if self.mine is False else "a hive pad")
            return f"on {pad} (panel: {self.prompt!r})"
        return f"at the {self.place.replace('_', ' ')} (panel: {self.prompt!r})"


class Table:
    """The recorded prompts, and the one question they answer."""

    def __init__(self, landmarks: dict, not_prompts=()):
        self._not = tuple(normalise(t) for t in not_prompts if normalise(t))
        rows: list[tuple[str, Landmark]] = []
        for place, body in (landmarks or {}).items():
            body = body or {}
            for entry in body.get("prompts") or ():
                if isinstance(entry, str):
                    entry = {"text": entry}
                phrase = normalise(entry.get("text"))
                if not phrase:
                    continue
                rows.append((phrase, Landmark(
                    place=str(place), kind=str(body.get("kind", "")),
                    prompt=phrase,
                    router_node=body.get("router_node"),
                    near=body.get("near"),
                    mine=entry.get("mine"))))
        # Longest phrase first, so "claim this hive" wins over "claim hive"
        # when both would match. Ties keep file order.
        self._rows = sorted(rows, key=lambda r: -len(r[0]))

    def __len__(self) -> int:
        return len(self._rows)

    def places(self) -> list[str]:
        return sorted({lm.place for _, lm in self._rows})

    def landmark(self, place: str) -> Landmark | None:
        """The recorded landmark for `place`, or None. First prompt wins."""
        return next((lm for _, lm in self._rows if lm.place == place), None)

    def match(self, text: str | None) -> Landmark | None:
        """The landmark this panel text names, or None.

        None for an empty string too -- an absent panel is a real observation,
        but it is `Bearings`' job to say what it means, not this table's.
        """
        low = normalise(text)
        if not low:
            return None
        if any(bad in low for bad in self._not):
            return None
        for phrase, landmark in self._rows:
            if phrase in low:
                return landmark
        return None

    def is_prompt(self, text: str | None) -> bool:
        return self.match(text) is not None

    def elsewhere(self, text: str | None, place: str) -> Landmark | None:
        """The landmark this panel names when it is NOT `place`, or None.

        A route named after one place that ends at another reads the other
        place's prompt, and that reading is news about the route, not a
        prompt for the place. MEASURED: `var/place_panels.json` holds
        honey_dispenser = "Open Shop" (a shop counter; the frame is inside
        the Blue HQ, DESIGN 8bh) and strawberry_dispenser = "Claim Hive" (a
        free hive pad). None for a panel this table does not know, which says
        nothing either way.
        """
        mark = self.match(text)
        return mark if mark is not None and mark.place != str(place) else None


def load(path: str | Path) -> Table:
    """Read the table from disk. A missing or broken file is an EMPTY table.

    Empty rather than an error because every caller can carry on without
    landmarks -- it just cannot confirm where it is, and it says so. A bot that
    refuses to start because a knowledge file has a typo helps nobody.
    """
    import yaml
    try:
        body = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return Table({})
    return Table(body.get("landmarks") or {}, body.get("not_prompts") or ())

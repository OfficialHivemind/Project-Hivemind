"""Turning a gather pattern into steps the route runner already knows how to run.

THE OWNER'S REQUEST AND THE BETTER ANSWER TO IT. He asked for the bot to see
tokens and run into them. docs/DESIGN.md 8a records four ways of detecting a
token failing on one real frame -- bright blobs found 85 flowers, shape and
shading found 13 flowers and no tokens, template matching peaked at 0.65 because
tokens are 3D and rotate, and the vision model spent 45 seconds returning
nothing. 8c records what the most-used macro in the game does instead: it does
not look for tokens at all, it walks a pattern that covers the field.

So this collects tokens by covering ground. It is also the only one of the two
approaches that works today.

FIELD-RELATIVE, WHICH IS THE WHOLE POINT. A pattern says "toward the centre",
not "hold W". Which key that is depends on which side of the field we walked in
from, and `Facing` is the small piece of arithmetic that decides. One pattern
covers every field, and adding a field never means recording a new pattern.

WHAT IS MEASURED AND WHAT IS NOT. `FIELD_STUDS` is an ESTIMATE and is labelled
as one. Everything else here is arithmetic on it, and `size` multiplies it, so
the day a field is measured end to end the estimate is replaced in one place and
every pattern in every field follows. Nothing pretends to a precision it has not
earned.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# HOW FAR ACROSS A FIELD IS, and this is the one number here that is not
# arithmetic. It is an ESTIMATE, not a measurement.
#
# What we actually have: BeeTuxMacro's `farm_snake` covers 231.6 studs over a
# whole pass, and its `collect_around` covers 80.7. A pass of a snake is a few
# lanes, so a single crossing sits somewhere near a third of the first figure.
# 75 studs is that, rounded.
#
# TO SETTLE IT: walk `toward` with span 1.0 in a known field and watch where the
# character ends up. If it stops short, this is low; if it leaves the field, it
# is high. Until then treat every distance in this module as approximate.
FIELD_STUDS = 75.0

# A lane shift is not scaled by `size`. `size` changes how much of the field is
# covered; lane spacing changes how THOROUGHLY it is covered, and multiplying
# both would leave the coverage identical while pretending to have changed.
DEFAULT_SIZE = 1.0

# The four relative directions, and the offset in quarter-turns clockwise from
# "toward the centre".
TURNS = {"toward": 0, "right": 1, "away": 2, "left": 3}

# Keys by compass heading, in the order the quarter-turns run through them.
# Shift-lock makes these mean the same thing every run; see act/routes.
KEYS = ("w", "d", "s", "a")


@dataclass(frozen=True)
class Step:
    dir: str
    span: float
    lane: bool = False


@dataclass(frozen=True)
class Pattern:
    name: str
    steps: tuple[Step, ...]
    description: str = ""
    best_for: str = ""

    @property
    def covers(self) -> float:
        """Total distance walked in one repetition, in field-widths."""
        return sum(s.span for s in self.steps)


@dataclass
class Facing:
    """Which key means "toward the centre" from where we came in.

    `entry` is a quarter-turn count: 0 when the centre lies in the direction W
    already walks, 1 when it is to the right, and so on. It is the only thing a
    field has to declare for every pattern to work in it.
    """
    entry: int = 0

    def key(self, direction: str) -> str:
        if direction not in TURNS:
            raise ValueError(f"unknown direction {direction!r}")
        return KEYS[(TURNS[direction] + self.entry) % 4]


def load(path: str | Path) -> dict[str, Pattern]:
    """Read the pattern file. Returns {} rather than raising if it is missing,
    because a missing pattern file must not stop the bot farming."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, Pattern] = {}
    for name, body in data.items():
        if not isinstance(body, dict):
            continue
        steps = tuple(
            Step(dir=str(s.get("dir", "")), span=float(s.get("span", 0.0)),
                 lane=bool(s.get("lane", False)))
            for s in (body.get("steps") or [])
            if str(s.get("dir", "")) in TURNS
        )
        out[name] = Pattern(name=name, steps=steps,
                            description=str(body.get("description", "")).strip(),
                            best_for=str(body.get("best_for", "")).strip())
    return out


def steps_for(pattern: Pattern, facing: Facing, size: float = DEFAULT_SIZE,
              reps: int = 1, field_studs: float = FIELD_STUDS) -> list[dict]:
    """The pattern as route-runner ops. Empty for `stationary`, which is correct.

    Emits `walk` ops, so this rides on the same executor, the same watcher hooks
    and the same mob interrupt as every recorded route. Nothing new drives the
    keyboard.
    """
    size = max(0.05, float(size))
    out: list[dict] = []
    for _ in range(max(0, int(reps))):
        for step in pattern.steps:
            scale = 1.0 if step.lane else size
            studs = step.span * scale * float(field_studs)
            if studs <= 0:
                continue
            out.append({"op": "walk", "keys": facing.key(step.dir),
                        "studs": round(studs, 1)})
    return out


def describe(pattern: Pattern, facing: Facing, size: float = DEFAULT_SIZE,
             reps: int = 1) -> str:
    total = pattern.covers * size * reps * FIELD_STUDS
    if not pattern.steps:
        return f"{pattern.name}: stand still"
    return (f"{pattern.name}: {len(pattern.steps)} legs x{reps}, "
            f"about {total:,.0f} studs, starting {facing.key('toward')}")

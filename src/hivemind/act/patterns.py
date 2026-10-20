"""Turning a gather pattern into steps the route runner already knows how to run.

THE OWNER'S REQUEST AND THE BETTER ANSWER TO IT. They asked for the bot to see
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

import math
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


# ---- HIVEMIND'S OWN GATHER PATTERNS (closed loops, sized to each field) -------
#
# WHY. Every field farms one shape today, a transpiled CornerXSnake, whose legs
# do not sum to zero: a pass ends 24.5 studs right and 27.3 forward of where it
# began (act/routes `pass_drift`), leaning on the field's walls to stay in.
# MEASURED where the walls do not hold (docs/pending/offfield.md, run logs
# 739-1247): Pepper ended 21 of 33 gathers off its field, Pine Tree 60 of 220.
# These are drawn from first principles instead, with nothing taken from any
# other macro's patterns:
#
#   1. CLOSED. Every pass sums to zero (`userpatterns.drift`), and so does a
#      pass walked at any one speed: a uniform haste error scales every leg
#      alike, so the loop still closes (tests simulate x0.85 and x1.15).
#   2. CENTRED ON THE ARRIVAL. The trip's route ends where its walk home
#      starts and where the sprinkler goes down, so the loop is built round
#      that point; ENTER walks to the loop's start corner, EXIT walks back, so
#      the walk home starts where its route expects it to (backlog W3).
#   3. SIZED TO THE FIELD ("per-field align", `side`): the loop's box, grown
#      by the measured worst speed error, fits the field's SHORT side less the
#      arrival slack, so it stays on the flowers whichever way the field lies
#      on screen -- proven by `footprint` in tests/unit/test_patterns. And no
#      wider than the sprinkler's reach either way, where the flowers regrow.
#   4. NO CAMERA TURN. The vision thresholds and the walk home assume the
#      camera the route out left (transpile_natro_patterns.py's docstring).
#
# NO WALL LEANS, deliberately: a pass that closes has no drift of its own for
# a lean to undo, and Pepper's leaks are a gate's open passage (offfield.md),
# which a lean would walk straight through.
OWN_PREFIX = "own_pattern_"
OWN_SHAPES = ("sweep", "weave", "rings", "petals")
# LOOK-ONLY (AGENTS rule 4): with gather.own_patterns on, the A/B only says
# "own pattern would: ..." and the field's own pattern is walked; the enter /
# exit legs of any pattern likewise only say what they would walk.
OWN_PATTERNS_LIVE = False
ENTER_EXIT_LIVE = False

# FIELD SIZES IN FLOWERS, from each field's wiki page (bee-swarm-simulator.
# fandom.com/wiki/<Field>, read through search 2026-10-27); each product is
# the page's flower count in data/knowledge/world.yaml (a test holds them
# equal). Which side lies along W on screen is NOT KNOWN, so only the short
# side is used. Stump is left out: its page says it is not a rectangle.
FIELD_FLOWERS = {
    "sunflower": (20, 33), "dandelion": (18, 36), "mushroom": (23, 32),
    "blue_flower": (17, 43), "clover": (26, 29), "strawberry": (22, 26),
    "bamboo": (18, 39), "spider": (26, 28), "pineapple": (23, 33),
    "cactus": (18, 33), "pumpkin": (17, 33), "rose_field": (20, 31),
    "pine_tree": (23, 31), "mountain_top": (24, 28), "coconut": (21, 30),
    "pepper": (21, 27),
}
# A flower is 4 studs: the tile every transpiled route walks in
# (act/routes TILE_STUDS; ASSUMED from the community's lib/Walk.ahk).
FLOWER_STUDS = 4.0
# The sprinklers' radius, 7 flowers for Basic and Silver Soakers (the wiki,
# data/knowledge/economy.yaml): the flowers they regrow lie within it.
SPRINKLER_REACH = 7 * FLOWER_STUDS
# MEASURED 2026-10-09 (run_farm NO_CHASE_FIELDS note): the gifted Hasty Bee's
# 15% overshoot drifted the timed holds; the box must fit even that long.
SPEED_ERROR = 1.15
# ASSUMED, to be measured live (docs/pending/patterns.md): how far from the
# field's middle a route's arrival can be, plus half the character.
ARRIVAL_SLACK = 12.0
BODY_STUDS = 2.0
# ASSUMED: two flowers between lanes, so each lane's bees reach the next's.
LANE_STUDS = 8.0


def _lanes(span: float) -> tuple[int, float]:
    """An ODD number of lane gaps across `span`, about LANE_STUDS apart (so
    a snake of up-and-down legs ends on the edge it started from), and the
    gap, to the hundredth."""
    n = max(1, round(span / LANE_STUDS))
    n += 1 - n % 2
    return n, round(span / n, 2)


def side(field: str) -> float | None:
    """The side in studs of the square an own pattern covers in router node
    `field`, or None when the field's size is not known (point 3 above).
    A whole number of lanes, so every loop closes to the hundredth."""
    dims = FIELD_FLOWERS.get(field)
    if dims is None:
        return None
    room = 2 * (min(dims) * FLOWER_STUDS / 2 - ARRIVAL_SLACK - BODY_STUDS) / SPEED_ERROR
    n, lane = _lanes(min(2 * SPRINKLER_REACH, room))
    return round(n * lane, 2)


def _m(key: str, studs: float) -> dict:
    return {"move": key, "studs": round(studs, 2)}


def _snake(span: float, up: str, down: str, across: str) -> list[dict]:
    """Legs `span` long, `up` then `down`, `across` a lane between them: an
    even number of them, so it ends on its starting edge, `span` across."""
    n, lane = _lanes(span)
    out = []
    for i in range(n + 1):
        out.append(_m(up if i % 2 == 0 else down, span))
        if i < n:
            out.append(_m(across, lane))
    return out


def own_pattern(shape: str, field: str, size: float = 1.0) -> dict | None:
    """One of OWN_SHAPES sized for `field`, as an HMP pattern (world/
    userpatterns) with `enter` and `exit`, or None for an unknown field.
    `size` scales every leg (SMALL_SIZE: the size twin, `twin`)."""
    s = side(field)
    if s is None or shape not in OWN_SHAPES:
        return None
    enter = [_m("s", s / 2), _m("a", s / 2)]      # the middle to the near-left corner
    leave = [_m("d", s / 2), _m("w", s / 2)]
    if shape == "sweep":
        # Lanes along W, left to right, then back along the near edge.
        legs = _snake(s, "w", "s", "d") + [_m("a", s)]
    elif shape == "weave":
        # The sweep's lanes, then the same lanes across them (along A/D) from
        # the near-right corner up to the far edge, then the right edge down
        # and the near edge back.
        legs = _snake(s, "w", "s", "d") + _snake(s, "a", "d", "w") + [_m("s", s), _m("a", s)]
    elif shape == "rings":
        # Squares from the edge inwards, a lane apart, then back out to the
        # corner by the same steps.
        n, lane = _lanes(s)
        legs, ring, steps_in = [], s, 0
        while ring >= lane - 0.01:
            legs += [_m("w", ring), _m("d", ring), _m("s", ring), _m("a", ring)]
            if ring - 2 * lane >= lane - 0.01:
                legs += [_m("w", lane), _m("d", lane)]
                steps_in += 1
            ring = round(ring - 2 * lane, 2)
        if steps_in:
            legs += [_m("s", lane * steps_in), _m("a", lane * steps_in)]
    else:
        # PETALS: a small snake in each quarter, each back on the middle --
        # over the sprinkler four times a pass. It starts and ends on the
        # arrival, so it has no enter or exit.
        legs, enter, leave = [], [], []
        for up, down, out_key, home in (("w", "s", "d", "a"), ("s", "w", "d", "a"),
                                        ("s", "w", "a", "d"), ("w", "s", "a", "d")):
            petal = _snake(s / 2, up, down, out_key)
            legs += petal + [_m(home, sum(m["studs"] for m in petal if m["move"] == out_key))]
    return {"schema": "hmp", "name": f"hivemind {shape}", "author": "hivemind",
            "version": 1, "size": size, "steps": legs, "enter": enter, "exit": leave}


def own_name(shape: str, field: str, size: float = 1.0) -> str:
    """`own_pattern_<shape>_<field>`; a size twin carries its percent on the
    shape: `own_pattern_sweep75_pepper`."""
    return f"{OWN_PREFIX}{shape}{'' if size == 1.0 else round(size * 100)}_{field}"


def own_field(name) -> str | None:
    """The router node an own pattern's routine walks, or None."""
    if not str(name).startswith(OWN_PREFIX):
        return None
    shape, _, field = str(name)[len(OWN_PREFIX):].partition("_")
    return (field if shape.rstrip("0123456789") in OWN_SHAPES and field in FIELD_FLOWERS
            else None)


# ---- PER-FIELD PICKS: SIZE AND SPRINKLER SPOT (ROADMAP AI-N5) ---------------
#
# The hour-block A/B (brain/experiment `field_pick`) first settles the SHAPE
# per field; the champion then meets its TWIN, the one other thing worth that
# field's hours. So a field never splits its hours more than five ways: every
# extra arm slows every verdict (docs/pending/patab.md: 2-4 weeks for a busy
# field with five).
#   - an own shape's twin is the SAME shape at SMALL_SIZE: a tighter loop over
#     the sprinkler's regrown flowers against more ground. Every own shape is
#     already as big as the field's short side allows (`side`), so the only
#     size worth trying is smaller. ASSUMED step: 0.75; the A/B says if it pays.
#   - the field's own pattern's twin is `natro_pattern_<field>` against
#     `..._as_natro`: no classic field start, so the sprinkler goes down
#     where the route lands. NEW MOVEMENT, so its own switch SPOT_TWIN_LIVE:
#     MEASURED var/trips.jsonl (read 2026-10-27) it was walked only on Pine
#     Tree (124 trips, 24-26 Sep) and Mountain Top (3), never on Pepper,
#     Bamboo or Blue Flower. And it is not only the spot: Blue Flower's is
#     width 3 against 7, Mountain Top's width 1 against 3, both mirrored left
#     to right (data/world/natro_patterns.yaml), so there it tries two things.
SMALL_SIZE = 0.75
SPOT_TWIN_LIVE = False
# THE SPRINKLER SPOT ALREADY SETTLED, so not tried again. MEASURED
# var/trips.jsonl (brain/experiment pattern_blocks, read 2026-10-27): Pine
# Tree from the arrival 3,547 pollen/s over 64 trips (22 h, 24-26 Sep), walk
# home landed 7/11, against the classic spot's next 3 days (26-29 Sep) 6,891
# over 163 trips, landed 157/158: the classic spot +94% [99% +53%..+156%];
# and 5 of 25 arrival trips were credited to the Pumpkin Patch (world/
# settings gather.natro_field_start). Back to back, not interleaved.
SPOT_SETTLED = frozenset({"pine_tree"})
_NATRO, _AS_NATRO = "natro_pattern_", "_as_natro"


def twin(name) -> str | None:
    """The one variant of the pattern routine `name` that the A/B tries once
    that pattern is its field's champion (above), or None."""
    name = str(name)
    field = own_field(name)
    if field is not None:
        shape = name[len(OWN_PREFIX):].partition("_")[0]
        return own_name(shape, field, SMALL_SIZE) if shape in OWN_SHAPES else None
    if name.startswith(_NATRO) and name.endswith(_AS_NATRO):
        field = name[len(_NATRO):-len(_AS_NATRO)]
        return None if field in SPOT_SETTLED else f"{_NATRO}{field}"
    return None


def own_routines() -> dict[str, dict]:
    """{routine name: {"steps", "studs"}} of every own pattern in every field
    it is sized for, its `_enter` and `_exit` legs beside it. Each goes
    through the Pattern Studio's own validator; one that fails is left out."""
    from ..world import userpatterns
    out = {}
    for field in FIELD_FLOWERS:
        for shape in OWN_SHAPES:
            for size in (1.0, SMALL_SIZE):
                checked = userpatterns.validate(own_pattern(shape, field, size))
                if not checked.ok:
                    continue
                p, name = checked.pattern, own_name(shape, field, size)
                out[name] = {"steps": userpatterns.compile_steps(p),
                             "studs": userpatterns.studs(p)}
                for part in userpatterns.ENDS:
                    if p.get(part):
                        out[f"{name}_{part}"] = {
                            "steps": userpatterns.compile_steps(p, part),
                            "studs": round(sum(m["studs"] for m in p[part]) * size, 1)}
    return out


def footprint(steps) -> tuple[float, float, float, float]:
    """(left, right, near, far): the extremes, in studs from the start, of
    the route runner's `walk` ops walked in order -- the box they cover."""
    x = y = 0.0
    xs, ys = [0.0], [0.0]
    for st in steps:
        if st.get("op") != "walk":
            continue
        keys = str(st.get("keys", ""))
        each = float(st.get("studs", 0.0)) / (math.sqrt(2) if len(keys) == 2 else 1.0)
        x += each * (("d" in keys) - ("a" in keys))
        y += each * (("w" in keys) - ("s" in keys))
        xs.append(x)
        ys.append(y)
    return min(xs), max(xs), min(ys), max(ys)

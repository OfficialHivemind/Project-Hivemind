"""User gather patterns: the data format, its strict check, share codes and the
library (ROADMAP T17, the PATTERN STUDIO).

A viewer asked for "custom patterns for people to make and others download...
like natro and other macros but better". Natro and other macros share patterns as
SCRIPTS (an .ahk file is code the macro runs). Ours are DATA ONLY: a list of
moves and turns with numbers, checked against hard limits, so a code pasted
from a Discord forum can never do more than walk a shape in a field.

THE FORMAT (one JSON object, schema "hmp" version 1):

    {"name": "Wide zigzag", "author": "a community member", "version": 1, "size": 1.0,
     "steps": [{"move": "w", "studs": 20},
               {"turn": "left"},
               {"repeat": 3, "steps": [{"move": "a", "studs": 6},
                                       {"move": "s", "studs": 20}]}]}

  move    keys: w, a, s, d or one diagonal pair (wa, wd, sa, sd); studs > 0.
          Keys are camera-relative, as in every other route (shift lock).
  turn    "left" or "right": one camera tap (45 degrees; act/routes
          CAMERA_KEYS, the comma and period keys the routes already use).
  repeat  2..MAX_REPEAT times a list of moves and turns (one level deep).
  size    multiplies every move's studs (MIN_SIZE..MAX_SIZE).

The pattern loops for the whole gather, so ONE PASS MUST LEAVE THE CAMERA WHERE
IT FOUND IT (the turns cancel, mod 8 taps): the walk home is a recorded route
that assumes the camera never moved.

THE SHARE CODE: "HMP1:" + base64url(zlib(canonical JSON)) + "." + 8 hex of the
CRC32 of that JSON. Canonical = the validated pattern, sorted keys, no spaces,
so the same pattern always gives the same code. `decode` only ever raises
InvalidCode, whatever it is fed.

THE BOT RUNS ONE AS A ROUTINE: `compile_steps` turns it into the route
runner's own `walk` and `camera` ops, the same ops farm_snake is made of, so
nothing new touches the keyboard.
"""
from __future__ import annotations

import base64
import binascii
import json
import math
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from ..datapaths import config_dir, data
from ..files import atomic_write

SCHEMA = "hmp"
FORMAT_VERSION = 1
CODE_PREFIX = "HMP1:"
ROUTE_PREFIX = "user_pattern_"          # the routine name the bot runs it under

# THE LIMITS. Generous for a real field (a whole Natro CornerXSnake is ~610
# studs in ~60 legs), and small enough that nothing pasted can hold a key for
# minutes or bloat the settings.
MAX_STUDS_STEP = 100.0      # one move: more than a field across is a typo
MIN_STUDS_STEP = 0.5
MAX_LEGS = 400              # moves + turns after repeats are expanded
MAX_ENTRIES = 64            # steps as written, a repeat's inner steps included
MAX_REPEAT = 20
MAX_TOTAL_STUDS = 3000.0    # one pass, after size
MIN_SIZE, MAX_SIZE = 0.25, 3.0
MAX_NAME, MAX_AUTHOR = 40, 40
MAX_VERSION = 9999
MAX_CODE_CHARS = 8192
MAX_JSON_BYTES = 32768
TAPS_PER_TURN = 8           # act/camsweep: 8 taps = 360 degrees

MOVE_KEYS = ("w", "a", "s", "d", "wa", "wd", "sa", "sd")
TURNS = ("left", "right")
TOP_KEYS = {"schema", "name", "author", "version", "size", "steps"}


class InvalidCode(ValueError):
    """The only thing `decode` raises."""


@dataclass
class Checked:
    """What `validate` found: `pattern` (canonical, safe to run) or None."""
    pattern: dict | None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)     # numbers it clamped

    @property
    def ok(self) -> bool:
        return self.pattern is not None


def _key(raw) -> str | None:
    """'aw' -> 'wa': one canonical spelling, or None for anything else."""
    if not isinstance(raw, str) or not 1 <= len(raw) <= 2:
        return None
    k = "".join(sorted(raw.lower(), key="wsad".index)) if set(raw.lower()) <= set("wasd") else ""
    return k if k in MOVE_KEYS else None


def _number(raw, low: float, high: float, what: str, notes: list, errors: list):
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        errors.append(f"{what}: {raw!r} is not a number")
        return None
    if raw < low or raw > high:
        clamped = min(high, max(low, raw))
        notes.append(f"{what}: {raw} clamped to {clamped}")
        return clamped
    return raw


def _text(raw, limit: int) -> str:
    """Printable characters only, cut to `limit`: shown, never executed."""
    text = "".join(c for c in str(raw) if c.isprintable())
    return text.strip()[:limit]


def _step(raw, where: str, nested: bool, notes: list, errors: list) -> dict | None:
    if not isinstance(raw, dict):
        errors.append(f"{where}: not a step")
        return None
    kinds = [k for k in ("move", "turn", "repeat") if k in raw]
    if len(kinds) != 1:
        errors.append(f"{where}: a step is one of move, turn or repeat")
        return None
    kind = kinds[0]
    allowed = {"move": {"move", "studs"}, "turn": {"turn"}, "repeat": {"repeat", "steps"}}[kind]
    if set(raw) - allowed:
        errors.append(f"{where}: unknown keys {sorted(map(str, set(raw) - allowed))}")
        return None
    if kind == "move":
        key = _key(raw["move"])
        if key is None:
            errors.append(f"{where}: move {raw['move']!r} is not one of {', '.join(MOVE_KEYS)}")
            return None
        studs = _number(raw.get("studs"), MIN_STUDS_STEP, MAX_STUDS_STEP,
                        f"{where} studs", notes, errors)
        return None if studs is None else {"move": key, "studs": round(float(studs), 2)}
    if kind == "turn":
        if raw["turn"] not in TURNS:
            errors.append(f"{where}: turn {raw['turn']!r} is not left or right")
            return None
        return {"turn": raw["turn"]}
    if nested:
        errors.append(f"{where}: a repeat inside a repeat is not allowed")
        return None
    times = raw["repeat"]
    if isinstance(times, bool) or not isinstance(times, int):
        errors.append(f"{where}: repeat {times!r} is not a whole number")
        return None
    times = int(_number(times, 2, MAX_REPEAT, f"{where} repeat", notes, errors))
    inner = raw.get("steps")
    if not isinstance(inner, list) or not inner:
        errors.append(f"{where}: a repeat needs a list of steps")
        return None
    steps = [_step(s, f"{where}.{i + 1}", True, notes, errors) for i, s in enumerate(inner)]
    return None if None in steps else {"repeat": times, "steps": steps}


def legs(pattern: dict) -> list[dict]:
    """The steps with every repeat written out: moves and turns only."""
    out: list[dict] = []
    for step in pattern.get("steps", []):
        if "repeat" in step:
            out += [dict(s) for _ in range(step["repeat"]) for s in step["steps"]]
        else:
            out.append(dict(step))
    return out


def validate(raw) -> Checked:
    """The strict check. Anything it does not know is an error; a number out
    of range is clamped and said. Nothing in `raw` is ever executed."""
    errors: list[str] = []
    notes: list[str] = []
    if not isinstance(raw, dict):
        return Checked(None, ["a pattern is a JSON object"])
    if set(raw) - TOP_KEYS:
        return Checked(None, [f"unknown keys {sorted(map(str, set(raw) - TOP_KEYS))}"])
    if raw.get("schema", SCHEMA) != SCHEMA:
        return Checked(None, [f"schema {raw.get('schema')!r} is not {SCHEMA!r}"])
    name = _text(raw.get("name", ""), MAX_NAME)
    if not slug(name):
        errors.append("name: needs at least one letter or digit")
    version = raw.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int):
        errors.append(f"version: {version!r} is not a whole number")
        version = 1
    version = int(min(MAX_VERSION, max(1, version)))
    size = _number(raw.get("size", 1.0), MIN_SIZE, MAX_SIZE, "size", notes, errors)
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps: needs at least one step")
        steps = []
    entries = len(steps) + sum(len(s["steps"]) for s in steps
                               if isinstance(s, dict) and isinstance(s.get("steps"), list))
    if entries > MAX_ENTRIES:
        return Checked(None, errors + [f"steps: {entries} written, the most is {MAX_ENTRIES}"])
    checked = [_step(s, f"step {i + 1}", False, notes, errors) for i, s in enumerate(steps)]
    if errors:
        return Checked(None, errors, notes)
    pattern = {"schema": SCHEMA, "name": name, "author": _text(raw.get("author", ""), MAX_AUTHOR),
               "version": version, "size": round(float(size), 3), "steps": checked}
    walked = legs(pattern)
    if len(walked) > MAX_LEGS:
        errors.append(f"steps: {len(walked)} after repeats, the most is {MAX_LEGS}")
    if not any("move" in s for s in walked):
        errors.append("steps: needs at least one move")
    total = studs(pattern)
    if total > MAX_TOTAL_STUDS:
        errors.append(f"length: {total:,.0f} studs a pass, the most is {MAX_TOTAL_STUDS:,.0f}")
    net = sum(1 if s.get("turn") == "right" else -1 for s in walked if "turn" in s)
    if net % TAPS_PER_TURN:
        errors.append(f"turns: one pass turns the camera {net:+d} taps; they must cancel "
                      f"(as many left as right) or the walk home starts facing the wrong way")
    return Checked(None if errors else pattern, errors, notes)


def studs(pattern: dict) -> float:
    """One pass, after size."""
    return round(sum(s["studs"] for s in legs(pattern) if "move" in s) * pattern.get("size", 1.0), 1)


def compile_steps(pattern: dict) -> list[dict]:
    """The route runner's own ops (act/routes): `walk` and `camera`. Only a
    VALIDATED pattern comes here."""
    size = float(pattern.get("size", 1.0))
    out = []
    for s in legs(pattern):
        if "move" in s:
            out.append({"op": "walk", "keys": s["move"], "studs": round(s["studs"] * size, 2)})
        else:
            out.append({"op": "camera", "direction": s["turn"]})
    return out


# ---- share codes ------------------------------------------------------------
def canonical(pattern: dict) -> bytes:
    return json.dumps(pattern, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode()


def pack(prefix: str, body: bytes) -> str:
    """prefix + base64url(zlib(body)) + "." + 8 hex of CRC32(body): the share
    code shape every Hivemind code uses (HMP1 patterns, HMH1 hive plans)."""
    payload = base64.urlsafe_b64encode(zlib.compress(body, 9)).decode().rstrip("=")
    return f"{prefix}{payload}.{zlib.crc32(body):08x}"


def unpack(code, prefix: str, max_chars: int, max_bytes: int, what: str = "pattern") -> bytes:
    """The bytes `pack` packed, checked: right prefix, size-capped before and
    after inflating, checksum. Raises InvalidCode, only, whatever it is fed."""
    try:
        if not isinstance(code, str) or len(code) > max_chars:
            raise InvalidCode(f"not a {what} code")
        m = re.fullmatch(re.escape(prefix) + r"([A-Za-z0-9_-]+)\.([0-9a-f]{8})", "".join(code.split()))
        if m is None:
            raise InvalidCode(f"not a {what} code (they start with {prefix})")
        packed = base64.urlsafe_b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4))
        unzip = zlib.decompressobj()
        body = unzip.decompress(packed, max_bytes + 1)
        if len(body) > max_bytes or unzip.unconsumed_tail:
            raise InvalidCode("the code is too big")
        if f"{zlib.crc32(body):08x}" != m.group(2):
            raise InvalidCode("the code is damaged (checksum)")
        return body
    except InvalidCode:
        raise
    except (binascii.Error, zlib.error, ValueError, TypeError, MemoryError) as exc:
        raise InvalidCode(f"invalid code: damaged or cut short ({type(exc).__name__})") from None
    except Exception:                                    # never anything else
        raise InvalidCode("invalid code") from None


def encode(pattern: dict) -> str:
    checked = validate(pattern)
    if not checked.ok:
        raise ValueError("; ".join(checked.errors))
    return pack(CODE_PREFIX, canonical(checked.pattern))


def decode(code) -> Checked:
    """A share code back to a checked pattern. Raises InvalidCode, only, for
    anything that is not a well-formed code; a well-formed code of a pattern
    that breaks the limits comes back as a Checked with its errors."""
    body = unpack(code, CODE_PREFIX, MAX_CODE_CHARS, MAX_JSON_BYTES)
    try:
        return validate(json.loads(body.decode("ascii")))
    except (ValueError, UnicodeError, RecursionError, TypeError) as exc:
        raise InvalidCode(f"invalid code: damaged or cut short ({type(exc).__name__})") from None
    except Exception:                                    # never anything else
        raise InvalidCode("invalid code") from None


# ---- the library ------------------------------------------------------------
def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")[:MAX_NAME]


def folder() -> Path:
    return config_dir() / "patterns"


def route_name(pattern_or_name) -> str:
    name = pattern_or_name["name"] if isinstance(pattern_or_name, dict) else pattern_or_name
    return ROUTE_PREFIX + slug(name)


def is_route_name(value) -> bool:
    """`macro.fields` may name one: checked by shape here; whether it is
    saved is the bot's to find at the trip (and it says so if not)."""
    return isinstance(value, str) and re.fullmatch(ROUTE_PREFIX + r"[a-z0-9_]{1,40}", value) is not None


def save(pattern: dict, where: Path | None = None) -> Path:
    """Validated, then written as <slug>.json. Raises ValueError if invalid."""
    checked = validate(pattern)
    if not checked.ok:
        raise ValueError("; ".join(checked.errors))
    path = (where or folder()) / f"{slug(checked.pattern['name'])}.json"
    atomic_write(path, json.dumps(checked.pattern, indent=1))
    return path


def delete(name: str, where: Path | None = None) -> None:
    (where or folder()).joinpath(f"{slug(name)}.json").unlink(missing_ok=True)


def load_user(where: Path | None = None) -> dict[str, dict]:
    """{slug: pattern} of every saved pattern that still passes the check; a
    file that does not is skipped, never half-run."""
    out: dict[str, dict] = {}
    where = where or folder()
    if not where.is_dir():
        return out
    for path in sorted(where.glob("*.json")):
        try:
            if path.stat().st_size > MAX_JSON_BYTES:
                continue
            checked = validate(json.loads(path.read_text()))
        except (OSError, ValueError, RecursionError):
            continue
        if checked.ok:
            out[slug(checked.pattern["name"])] = checked.pattern
    return out


def routines(where: Path | None = None) -> dict[str, dict]:
    """{route name: {"steps", "studs"}} for the bot's router."""
    return {route_name(p): {"steps": compile_steps(p), "studs": studs(p)}
            for p in load_user(where).values()}


# ---- built-ins, read-only ---------------------------------------------------
BUILTIN_SHAPES = {"farm_snake": "Snake, wide", "farm_better_snake": "Snake, short",
                  "farm_square": "Square, small"}


def _from_routine(name: str, title: str, steps: list) -> dict | None:
    out = []
    for s in steps:
        if s.get("op") == "walk" and _key(s.get("keys")) and float(s.get("studs", 0)) > 0:
            out.append({"move": _key(s["keys"]), "studs": round(min(MAX_STUDS_STEP, float(s["studs"])), 2)})
        elif s.get("op") == "camera" and s.get("direction") in TURNS:
            out.append({"turn": s["direction"]})
    if not out:
        return None
    return {"schema": SCHEMA, "name": title, "author": "built-in", "version": 1,
            "size": 1.0, "steps": out, "route": name}


def builtins() -> list[dict]:
    """The bot's own patterns, shown for preview and copying, never edited:
    BeeTuxMacro's shapes (paths.yaml) and Natro's per-field patterns. Each
    carries `route`, the routine it already runs under."""
    import yaml
    out = []
    for file, pick in ((data("world", "paths.yaml"), lambda n: n in BUILTIN_SHAPES),
                       (data("world", "natro_patterns.yaml"),
                        lambda n: n.startswith("natro_pattern_") and not n.endswith("_as_natro"))):
        try:
            rows = (yaml.safe_load(file.read_text()) or {}).get("routines", [])
        except (OSError, yaml.YAMLError):
            continue
        for row in rows:
            name = str(row.get("name", ""))
            if not pick(name):
                continue
            title = BUILTIN_SHAPES.get(name) or \
                "Classic " + name.removeprefix("natro_pattern_").replace("_", " ").title()
            p = _from_routine(name, title, row.get("steps") or [])
            if p:
                out.append(p)
    return out

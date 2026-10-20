"""Hive presets for the Hive Planner (ROADMAP H17, a viewer's ask): the
built-in starter plans and the HMH1 share code.

STARTERS: data/knowledge/hive_presets.yaml, Blue / Red / White per stage, each
count cited to the guide or progression file it comes from. Read-only: a
preset becomes a plan through `slots_of` (hiveplanner.fill_from_comp, the
planner's own fill) and is saved by hiveplanner.save, so the bot reads an
applied preset exactly as one the owner clicked in.

THE SHARE CODE: "HMH1:" + base64url(zlib(canonical JSON)) + "." + CRC32, the
pattern code's shape (world/userpatterns.pack/unpack). The JSON is the plan
file's own body, {"slots": {"1": "bubble", ...}}. `decode` reads NOTHING else:
any other key, a slot outside 1..50, a bee not in bee_types.yaml, more than
50 entries -- the whole code is refused (InvalidCode), never half-applied.
"""
from __future__ import annotations

import json
from functools import lru_cache

import yaml

from ..datapaths import data
from ..world.userpatterns import InvalidCode, pack, unpack
from . import hiveplanner as hp
from .progression import HIVES

CODE_PREFIX = "HMH1:"
MAX_CODE_CHARS = 2048       # a full 50-slot plan of long names packs to ~350
MAX_JSON_BYTES = 4096       # 50 x '"50":"carpenter",' is ~850
STAGES = ("early", "mid", "late", "endgame")

__all__ = ["InvalidCode", "encode", "decode", "starters", "slots_of", "bee_names"]


@lru_cache(maxsize=1)
def bee_names() -> frozenset:
    """Every bee type's slug (data/knowledge/bee_types.yaml): the only names a
    plan may hold."""
    body = yaml.safe_load(data("knowledge", "bee_types.yaml").read_text()) or {}
    return frozenset(body.get("types") or {})


def starters() -> list[dict]:
    """The built-in presets, in file order: {id, hive, stage, name, bees,
    source, note}. One that names an unknown bee or holds more than 50 slots
    is a broken file -- raises ValueError (the test suite reads them all)."""
    body = yaml.safe_load(data("knowledge", "hive_presets.yaml").read_text()) or {}
    out = []
    for p in body.get("presets") or ():
        bees = {str(b): int(n) for b, n in (p.get("bees") or {}).items()}
        bad = sorted(set(bees) - bee_names())
        if bad or not bees or sum(bees.values()) > hp.SLOTS or min(bees.values()) < 1 \
                or p.get("hive") not in HIVES or p.get("stage") not in STAGES:
            raise ValueError(f"hive preset {p.get('id')!r} is broken: {bad or bees}")
        out.append({"id": str(p["id"]), "hive": p["hive"], "stage": p["stage"],
                    "name": str(p["name"]), "bees": bees,
                    "source": " ".join(str(p.get("source", "")).split()),
                    "note": str(p.get("note", ""))})
    return out


def slots_of(preset: dict) -> dict:
    """{slot: bee}: the planner's own fill, biggest group first from slot 1."""
    return hp.fill_from_comp({b: [n, n] for b, n in preset["bees"].items()})


# ---- share codes ------------------------------------------------------------
def _body(slots: dict) -> bytes:
    return json.dumps({"slots": {str(s): b for s, b in sorted(slots.items())}},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def check(slots) -> dict:
    """The strict check of a plan: {int slot 1..50: known bee}, at least one.
    Raises InvalidCode naming the first thing wrong."""
    if not isinstance(slots, dict) or not slots:
        raise InvalidCode("invalid code: no slots in it")
    if len(slots) > hp.SLOTS:
        raise InvalidCode(f"invalid code: {len(slots)} slots, a hive has {hp.SLOTS}")
    out = {}
    for k, bee in slots.items():
        # canonical keys only: "7", never "07", " 7", "7.0" or 7
        if not isinstance(k, str) or not (k.isascii() and k.isdigit()) or k != str(int(k)) \
                or not 1 <= int(k) <= hp.SLOTS:
            raise InvalidCode(f"invalid code: {str(k)[:12]!r} is not a slot 1-{hp.SLOTS}")
        if not isinstance(bee, str) or bee not in bee_names():
            raise InvalidCode(f"invalid code: slot {k}: {str(bee)[:20]!r} is not a bee")
        out[int(k)] = bee
    return out


def encode(slots: dict) -> str:
    """A plan ({slot: bee}) as a share code. Raises ValueError for a plan the
    decoder would refuse (empty, unknown bee)."""
    plan = {int(s): b for s, b in slots.items() if b}
    try:
        check({str(s): b for s, b in plan.items()})
    except InvalidCode as exc:
        raise ValueError(str(exc).removeprefix("invalid code: ")) from None
    return pack(CODE_PREFIX, _body(plan))


def decode(code) -> dict:
    """A share code back to {slot: bee}. Raises InvalidCode, only, whatever
    it is fed."""
    body = unpack(code, CODE_PREFIX, MAX_CODE_CHARS, MAX_JSON_BYTES, what="hive plan")
    try:
        raw = json.loads(body.decode("ascii"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InvalidCode(f"invalid code: damaged ({type(exc).__name__})") from None
    if not isinstance(raw, dict) or set(raw) != {"slots"}:
        raise InvalidCode("invalid code: a hive plan code holds only slots")
    return check(raw["slots"])

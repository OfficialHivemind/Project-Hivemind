"""H4b, the Wax Calculator's maths: the chance a beequip stat gets N wax points.

SOURCE, READ 2026-10-22 (the Windows Claude, docs/pending windows-claude note):
the Bee Swarm Simulator wiki's Lua modules, through its api.php parse endpoint
(the plain pages answer 402/403 to scripts):
  * Module:Beequip Stats/data (revid 446414): each beequip's `Upgrades`, every
    upgradable stat with a `Chance` (its weight), a `Max` (wax points it can
    take) and `CausticOnly`;
  * Beequip/Generation (revid 447732), "Upgrade": a wax point picks a stat
    with P = weight / pool's weight sum; a stat at its Max leaves the pool;
    Caustic (and Debug) points pick from every stat, other waxes' points from
    the stats that are not CausticOnly;
  * Module:RQValue (revid 446090) Resolve and Module:RandomBias (445165):
    how a `Chance` table becomes a number for a given quality.
The wiki is CC BY-SA, so its tables are NOT in this GPL repo: `fetch` reads
them at use time and caches them under var/waxcalc/.

ponytail: quality = potential / 5 is UNCONFIRMED (the pages say higher
potential gives higher weights, not the mapping); it is a parameter, and
every `odds` result says so.

Waxes (success chance, points) come from data/knowledge/beequips.yaml
(mechanics.waxes). A failed Caustic destroys the beequip (and so the stat).
"""
from __future__ import annotations

import json
import random
import re
import time
import urllib.request
from dataclasses import dataclass

from .. import datapaths
from . import knowledge

API = ("https://bee-swarm-simulator.fandom.com/api.php?action=parse"
       "&page=Module:Beequip_Stats/data&prop=wikitext%7Crevid&format=json")
CACHE = datapaths.var("waxcalc", "beequip_stats.json")
QUALITY_NOTE = "quality = potential / 5 is UNCONFIRMED (no written source for the mapping)"


# ---- Module:RQValue, Resolve ----------------------------------------------------
def random_bias(lo: float, hi: float, bias: float, influence: float, rng) -> float:
    """Module:RandomBias.randomBias, line for line."""
    value = rng() * (hi - lo) + lo
    pull = rng() * influence
    return value * (1 - pull) + bias * pull


def resolve(stat, quality: float, rng=random.random):
    """Module:RQValue's Resolve: a number, or None when the stat's own Chance
    roll fails. Two places follow the module's evident intent, not its text:
    the Lua declares `local ret` inside the nested-Value branch and
    `local biasValue` inside the quality >= 1 branch, so as written those
    values never leave their block; here they do."""
    if isinstance(stat, (int, float)):
        return stat
    if isinstance(stat, list):              # a bare {lo, hi}: Lua's `stat.Value or stat`
        stat = {"Value": stat}
    chance = stat.get("Chance")
    if chance is not None:
        roll = resolve(chance, quality, rng)
        if roll is None or roll <= rng():
            return None
    value = stat.get("Value", stat)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        ret = resolve(value, quality, rng)
    else:
        lo, hi = value[0], value[1]
        q = min(1.0, max(0.0, quality))
        if stat.get("ScalingPower"):
            q = q ** stat["ScalingPower"]
        if stat.get("Linear") or (stat.get("ScalingPower") and not stat.get("Bias")):
            linear = stat.get("Linear")
            scaling = 1 if (linear is True or not linear) else linear
            ret = lo + (hi - lo) * min(1.0, q / scaling)
        else:
            if q >= 1:
                bias_value = hi
            elif not stat.get("Bias"):
                bias_value = lo + (hi - lo) * q
            else:
                left, right = stat["Bias"]
                if right != 1:
                    left = left / right
                influence = q ** (1 + (left - 1) * 0.5)
                bias_value = lo * (1 - influence) + hi * influence
            ret = random_bias(lo, hi, bias_value, 1, rng)
    resolution = stat.get("Resolution")
    if resolution and ret is not None:
        ret = (ret / resolution + 0.5) // 1 * resolution
    return ret


# ---- the pool and the odds ------------------------------------------------------
@dataclass
class Upgrade:
    name: str            # BeeStat / HiveBonusStat / ability, as the table names it
    chance: object       # the wiki's Chance: a number or an RQValue table
    max: int | None = None
    caustic_only: bool = False


def pool_from(upgrades: list[dict]) -> list[Upgrade]:
    """The wiki's Upgrades array as Upgrade rows (a hive bonus and a bee stat
    of the same name are told apart, as the game's display does)."""
    out, seen = [], {}
    for u in upgrades:
        name = (u.get("BeeStat") or (u.get("HiveBonusStat") and f"[HB] {u['HiveBonusStat']}")
                or u.get("BeeAbility") or u.get("BeeAbilityPoolId") or u.get("BeeAbilityPool")
                or "?")
        if u.get("Op"):
            name += f" ({u['Op']})"
        # Lei's four "+% Pollen" upgrades differ only by Params' Zone
        params = u.get("Params")
        if isinstance(params, dict) and params:
            name += " [" + ", ".join(f"{v}" for v in params.values()) + "]"
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:                                  # still a twin: number it
            name += f" #{seen[name]}"
        out.append(Upgrade(name, u.get("Chance", 0), u.get("Max"), bool(u.get("CausticOnly"))))
    return out


def wax_table() -> dict[str, dict]:
    """{'soft': {'power': 1, 'success': 1.0, ...}, ...} from beequips.yaml."""
    return dict(((knowledge.beequips().get("mechanics") or {}).get("waxes") or {}))


def odds(pool: list[Upgrade], waxes: list[str], target: str, points: int = 1, *,
         quality: float, trials: int = 20_000, seed: int = 1, table: dict | None = None) -> dict:
    """The chance `target` holds >= `points` wax points after `waxes` (in order,
    e.g. ["caustic", "hard", "soft"]). A seeded Monte Carlo (the weights
    themselves can be random -- RandomBias -- so it is not exact); the same
    seed gives the same answer."""
    table = table if table is not None else wax_table()
    for w in waxes:
        if w not in table:
            raise KeyError(f"no wax {w!r} in beequips.yaml (have {sorted(table)})")
        # ponytail: Swirled rerolls every point already applied (beequips.yaml);
        # with power 0 the loop below would treat it as "nothing happens", so
        # it is refused until the reroll is modelled.
        if not int(table[w].get("power", 0)):
            raise ValueError(f"{w!r} wax is not modelled yet (it rerolls, it adds no points)")
    if target not in {u.name for u in pool}:
        raise KeyError(f"no upgradable stat {target!r} (have {[u.name for u in pool]})")
    rng = random.Random(seed)
    hits = destroyed = 0
    for _ in range(trials):
        weight = {u.name: max(0.0, resolve(u.chance, quality, rng.random) or 0.0) for u in pool}
        got = {u.name: 0 for u in pool}
        gone = False
        for w in waxes:
            spec = table[w]
            if rng.random() >= float(spec.get("success", 1)):
                if w == "caustic":
                    gone = True
                    break
                continue
            for _ in range(int(spec.get("power", 0))):
                open_ = [u for u in pool if (w == "caustic" or not u.caustic_only)
                         and (u.max is None or got[u.name] < u.max) and weight[u.name] > 0]
                total = sum(weight[u.name] for u in open_)
                if total <= 0:
                    break
                r = rng.random() * total
                for u in open_:
                    r -= weight[u.name]
                    if r <= 0:
                        got[u.name] += 1
                        break
        if gone:
            destroyed += 1
        elif got[target] >= points:
            hits += 1
    return {"p": hits / trials, "destroyed": destroyed / trials, "trials": trials,
            "seed": seed, "method": "seeded Monte Carlo", "quality": quality,
            "note": QUALITY_NOTE}


# ---- the wiki's table, at use time ----------------------------------------------
_TOKEN = re.compile(r'--\[\[.*?\]\]|--[^\n]*|\[\[.*?\]\]|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
                    r'|\[|\]|[{}=,]|-?\d+(?:\.\d+)?(?:[eE]-?\d+)?|\w+', re.S)
_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "'": "'"}


def _lua_string(token: str) -> str:
    if token.startswith("[["):
        return token[2:-2]
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), token[1:-1])


def _is_string(token: str) -> bool:
    return token[:1] in "\"'" or token.startswith("[[")


def lua_table(text: str, start: int = 0):
    """Parse one Lua table literal starting at text[start] == "{": dicts for
    keyed tables, lists for arrays -- the data module's subset of Lua (its
    strings, long strings, comments; a `function ... end` value reads as
    None)."""
    tokens = [t for t in _TOKEN.findall(text, start) if not t.startswith("--")]
    pos = 0

    def skip_function():
        nonlocal pos
        depth = 1
        while depth:
            t = tokens[pos]
            pos += 1
            if t in ("function", "if", "do"):
                depth += 1
            elif t == "end":
                depth -= 1

    def value():
        nonlocal pos
        t = tokens[pos]
        pos += 1
        if t == "{":
            items, keyed = [], {}
            while tokens[pos] != "}":
                if tokens[pos] == "[":                   # ["key"] = value, [1] = value
                    raw = tokens[pos + 1]
                    key = _lua_string(raw) if _is_string(raw) else json.loads(raw)
                    pos += 4
                    keyed[key] = value()
                elif tokens[pos + 1] == "=" and re.fullmatch(r"[A-Za-z_]\w*", tokens[pos]):
                    key = tokens[pos]
                    pos += 2
                    keyed[key] = value()
                else:
                    items.append(value())
                if tokens[pos] == ",":
                    pos += 1
            pos += 1
            return keyed if keyed else items
        if _is_string(t):
            return _lua_string(t)
        if t == "function":
            skip_function()
            return None
        if t in ("true", "false"):
            return t == "true"
        if t == "nil":
            return None
        return float(t) if any(c in t for c in ".eE") else int(t)

    return value()


def fetch(beequip: str, *, offline: bool = False, max_age_s: float = 7 * 86400) -> list[Upgrade]:
    """`beequip`'s Upgrades from the wiki (cached a week under var/waxcalc/).
    RuntimeError with a plain reason when it is not in the cache and the wiki
    cannot be reached (or `offline`)."""
    body = stale = None
    try:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        if offline or time.time() - cached["at"] < max_age_s:
            body = cached
        else:
            stale = cached                   # kept for when the wiki is unreachable
    except (OSError, ValueError, KeyError):
        pass
    if body is None:
        if offline:
            raise RuntimeError("offline and no cached copy of the wiki's beequip table")
        try:
            req = urllib.request.Request(API, headers={"User-Agent": "Hivemind waxcalc"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                parsed = json.loads(resp.read().decode("utf-8"))["parse"]
        except Exception as exc:
            if stale is None:
                raise RuntimeError(f"could not read the wiki's beequip table ({exc}); "
                                   "no cached copy either") from exc
            body = stale                     # an old table beats none; its "at" says how old
        else:
            body = {"at": time.time(), "revid": parsed.get("revid"),
                    "wikitext": parsed["wikitext"]["*"]}
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(body), encoding="utf-8")
    text = body["wikitext"]
    want = beequip.replace("_", " ").strip().lower()
    for m in re.finditer(r'\ndata(?:\.(\w+)|\["([^"]+)"\])\s*=\s*\{', text):
        name = (m.group(1) or m.group(2))
        if name.lower() == want:
            table = lua_table(text, m.end() - 1)
            return pool_from(table.get("Upgrades") or [])
    raise KeyError(f"no beequip {beequip!r} in the wiki's table (revid {body.get('revid')})")

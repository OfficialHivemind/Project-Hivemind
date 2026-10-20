"""The bot trying its own settings and keeping what measures best.

WHY. The owner, 2026-10-11: improve its thinking until it can train itself,
since it felt like it was following if-then statements. A
number this bot was given -- when to press the sprinkler in a jump, how full to
let the bag get -- is a guess until it is measured. An Experiment holds a few
values (arms) for one such number, picks one for each try, takes the try's
measured reward, and over the tries settles on the best, saying what it learned.

HOW IT PICKS. Thompson sampling on each arm's measured mean: every arm is drawn
from its own Beta (rewards 0..1) and the highest draw is tried. Arms with few
tries stay uncertain and keep being tried; an arm that keeps losing fades out
on its own. Nothing is decided on a guess: an arm untried is tried.

WHAT IT KEEPS. var/experiments.json: per experiment, per arm, the tries and the
summed reward -- read back every session, so it learns across sessions.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

SETTLE_TRIES = 30          # tries before an experiment says what it learned
# FORGETTING (backlog 6; Garivier & Moulines' discounted bandits): every new try
# shrinks the weight of the old ones by this, so as the hive grows the bot's
# settings follow it instead of the hive it had (an effective memory of ~50 tries).
DISCOUNT = 0.98

# CONTEXT (backlog 6b). The same setting can measure differently by situation
# (a boost running, haste up, nectar level): below this many tries in a given
# context, its own stats are too thin to trust, so pick() falls back to the
# pooled, global stats -- same idea as SETTLE_TRIES, just for one context.
MIN_CONTEXT_TRIES = 5
THOMPSON_DRAWS = 200        # Monte-Carlo draws to estimate a pick's probability


@dataclass
class Arm:
    value: float
    tries: float = 0.0        # discounted count
    reward: float = 0.0

    @property
    def mean(self) -> float:
        return self.reward / self.tries if self.tries else 0.0


class Experiment:
    """One number the bot measures itself on. Rewards are 0..1."""

    def __init__(self, path, name: str, values, rng=None):
        self.path = Path(path)
        self.name = name
        self.rng = rng or random.Random()
        self.arms = [Arm(float(v)) for v in values]
        self.last_p: float | None = None      # set by pick(): the chosen arm's
                                               # estimated Thompson probability
        self._contexts: dict[str, list[Arm]] = {}
        self._load()

    def _load(self) -> None:
        try:
            body = json.loads(self.path.read_text()).get(self.name) or {}
        except (OSError, ValueError, AttributeError):
            body = {}
        for arm in self.arms:
            got = body.get(f"{arm.value:g}") or {}
            arm.tries = float(got.get("tries", 0) or 0)
            arm.reward = float(got.get("reward", 0.0) or 0.0)
        for ckey, cbody in (body.get("_contexts") or {}).items():
            arms = [Arm(a.value) for a in self.arms]
            for arm in arms:
                got = cbody.get(f"{arm.value:g}") or {}
                arm.tries = float(got.get("tries", 0) or 0)
                arm.reward = float(got.get("reward", 0.0) or 0.0)
            self._contexts[ckey] = arms

    def _save(self) -> None:
        try:
            body = json.loads(self.path.read_text())
            body = body if isinstance(body, dict) else {}
        except (OSError, ValueError):
            body = {}
        body[self.name] = {f"{a.value:g}": {"tries": round(a.tries, 4), "reward": round(a.reward, 4)}
                           for a in self.arms}
        if self._contexts:
            body[self.name]["_contexts"] = {
                ckey: {f"{a.value:g}": {"tries": round(a.tries, 4), "reward": round(a.reward, 4)}
                       for a in arms}
                for ckey, arms in self._contexts.items()
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, indent=1))
        tmp.replace(self.path)

    @staticmethod
    def _context_key(context: dict) -> str:
        return "&".join(f"{k}={context[k]!r}" for k in sorted(context))

    def _context_arms(self, key: str) -> list[Arm]:
        if key not in self._contexts:
            self._contexts[key] = [Arm(a.value) for a in self.arms]
        return self._contexts[key]

    def _thompson_p(self, arms: list[Arm], chosen_value: float,
                     draws: int = THOMPSON_DRAWS) -> float:
        """Monte-Carlo estimate of the chance Thompson sampling lands on
        `chosen_value` among `arms`, for callers to log (offline evaluation)."""
        if len(arms) <= 1:
            return 1.0
        wins = 0
        for _ in range(draws):
            draw = max(arms, key=lambda a: self.rng.betavariate(1 + a.reward, 1 + a.tries - a.reward))
            if abs(draw.value - chosen_value) < 1e-9:
                wins += 1
        return wins / draws

    def _pick_from(self, arms: list[Arm]) -> float:
        untried = [a for a in arms if a.tries < 0.5]
        if untried:
            chosen = untried[0].value
        else:
            draws = [(self.rng.betavariate(1 + a.reward, 1 + a.tries - a.reward), a.value)
                     for a in arms]
            chosen = max(draws)[1]
        self.last_p = self._thompson_p(arms, chosen)
        return chosen

    def pick(self, context: dict | None = None) -> float:
        """The value to try now: an untried arm first, else Thompson's draw.
        With `context` (a small dict of discrete features, e.g. {"boost": True,
        "nectar": "high"}), picks from that context's own stats once it has
        MIN_CONTEXT_TRIES tries of its own; otherwise falls back to the pooled
        global stats, same as calling pick() with no context. Either way sets
        `last_p`, a Monte-Carlo estimate of the chosen arm's Thompson
        probability, for callers to log for offline evaluation."""
        arms = self.arms
        if context is not None:
            c_arms = self._context_arms(self._context_key(context))
            if sum(a.tries for a in c_arms) >= MIN_CONTEXT_TRIES:
                arms = c_arms
        return self._pick_from(arms)

    @staticmethod
    def _apply(arms: list[Arm], value: float, reward: float) -> None:
        for arm in arms:
            arm.tries *= DISCOUNT
            arm.reward *= DISCOUNT
            if abs(arm.value - float(value)) < 1e-9:
                arm.tries += 1
                arm.reward += reward

    def learn(self, value: float, reward: float, scale: float | None = None,
              context: dict | None = None) -> None:
        """A try of `value` measured `reward`. Rewards are 0..1; a measured
        number (honey a second) is put on that scale by `scale` (its best
        plausible value) first. Older tries are discounted (DISCOUNT). With
        `context`, also folds the try into that context's own stats (kept
        alongside, never instead of, the global stats)."""
        if scale:
            reward = float(reward) / float(scale)
        reward = min(1.0, max(0.0, float(reward)))
        self._apply(self.arms, value, reward)
        if context is not None:
            self._apply(self._context_arms(self._context_key(context)), value, reward)
        self._save()

    @property
    def best(self) -> Arm:
        tried = [a for a in self.arms if a.tries] or self.arms
        return max(tried, key=lambda a: (a.mean, a.tries))

    @property
    def tries(self) -> int:
        return sum(a.tries for a in self.arms)

    def describe(self) -> str:
        arms = ", ".join(f"{a.value:g}: {a.mean:.0%} of {a.tries:.0f}" for a in self.arms)
        verdict = (f"learned: {self.best.value:g} is best"
                   if self.tries >= SETTLE_TRIES else "still learning")
        return f"{self.name} -- {arms} ({verdict})"


# ---- PATTERN A/B IN HOUR BLOCKS (ROADMAP T3/P5) -------------------------------
#
# WHY NOT THE BANDIT ABOVE. A gather pattern's trip is not an independent draw:
# trips in one clock hour share the hour's buffs, boosts, server and quest set,
# and the hive grows over the days. scripts/benchmark.py MEASURED this on the
# 72 h to 14 Oct: a per-trip bootstrap called honey/h better or worse at
# p < 0.01 on 18% of no-change splits (1% expected), so it resamples whole
# clock hours. And `Experiment.best` names a winner on any lead at all. Here,
# per field: each clock hour belongs to one pattern arm (`block_arm`, so the
# arms take turns through the day and the days), every hour's trips are
# summed into one block, and a challenger is promoted over the field's own
# pattern ONLY when the CI_LEVEL (99%) block-bootstrap range of its pollen
# per gathering second is wholly above, and neither its walk-home landing nor
# its drift-outs are measurably worse. Stateless: the verdict is re-read from the ledger
# (var/trips.jsonl) every time, so a promotion whose evidence ages out of
# WINDOW_S goes back to being tested.
#
# SHADOW FIRST (AGENTS rule 4): with PATTERN_AB_LIVE False, run_farm only says
# "pattern A/B would: ..." once an hour; the trip walks what it walked before.
PATTERN_AB_LIVE = False
BLOCK_S = 3600.0
# the same floors as scripts/benchmark.py's verdict (MIN_TRIPS, MIN_BLOCKS):
# fewer on either arm and it says "too few", never a winner
MIN_BLOCKS = 8
MIN_TRIPS = 15
# run_farm's own floor for the bandit (OWN_PATTERNS_MIN_GATHER_S): a shorter
# gather is mostly the walk in and the sprinkler, not the pattern
MIN_GATHER_S = 60.0
# ponytail: two weeks of evidence; the hive's growth over it is shared by the
# arms (they interleave), so it widens the ranges and biases neither arm
WINDOW_S = 14 * 86400.0
BOOT = 1000
# HOW SURE "CLEARLY" IS. MEASURED 2026-10-27 on var/trips.jsonl (14 days to
# 27 Oct 04:43): each of the 5 most-walked fields' own pattern split into two
# made-up arms by 100 random hour-block draws (an A/A test: no real
# difference). At a 95% range it called the copy "better" 19 times in 500 and
# "worse" 43 (three checks can each say worse); at 99%, 6 and 9. A field has
# up to 4 challengers, so 95% would promote a no-better pattern about one
# field in seven. The price: a real +20% is found in 14 days of a field's
# hours 61-81% of the time on Pine Tree / Mountain Top / Bamboo at 99%
# (80-88% at 95%), 21-23% on the thin Stump / Pepper.
CI_LEVEL = 0.99
_KEYS =("pollen", "seconds", "trips", "landed", "judged", "drift")


def block_arm(at: float, arms) -> str:
    """The arm clock hour `at` belongs to. The hour of the day plus the day
    index, so an arm does not get the same hours every day: each arm sees
    every hour of the day across len(arms) days. (The absolute hour plus the
    day would not do: with 5 arms 25 hours is a whole cycle, so each arm kept
    the same 4-5 hours of the day for ever, a time-of-day confound.)"""
    hour = int(at // BLOCK_S)
    return arms[(hour % 24 + hour // 24) % len(arms)]


def pattern_blocks(rows, arms, since: float = 0.0) -> dict:
    """{arm: [block]} over the ledger `rows`: one block per clock hour of a
    pattern's trips -- pollen, gathering seconds, trips, walks home landed
    and judged, drift-outs. Only trips that walked one of `arms`, gathered at
    least MIN_GATHER_S with a legible pollen counter, did not die, and were
    not credited to another field (a mis-delivery is the route's doing, not
    the pattern's)."""
    from .skills import FLAT_COUNTER_WORDS, GO_HOME_RUNG, node
    out: dict = {arm: {} for arm in arms}
    for r in rows:
        arm, at = r.get("pattern"), float(r.get("at") or 0.0)
        gs, pollen = float(r.get("gather_seconds") or 0.0), r.get("pollen")
        if (arm not in out or at < since or gs < MIN_GATHER_S or pollen is None
                or r.get("deaths")):
            continue
        if r.get("credited") and node(r["credited"]) != node(r.get("aimed_at")):
            continue
        b = out[arm].setdefault(int(at // BLOCK_S), dict.fromkeys(_KEYS, 0))
        b["pollen"] += int(pollen)
        b["seconds"] += gs
        b["trips"] += 1
        homes = [x.get("outcome") for x in r.get("routes") or () if x.get("kind") == "home"]
        if homes and homes[-1] in ("landed", "elsewhere"):      # unknown: not judged
            b["judged"] += 1
            b["landed"] += homes[-1] == "landed"
        # a DRIFT-OUT: the gather ended off the flowers (brain/skills `ended_off`)
        rec = list(r.get("recoveries") or ())
        b["drift"] += bool(rec and rec[-1] == GO_HOME_RUNG
                           and str(r.get("gather_ended") or "").startswith(FLAT_COUNTER_WORDS))
    return {arm: [bs[k] for k in sorted(bs)] for arm, bs in out.items()}


def _sums(blocks) -> dict:
    return {k: sum(b[k] for b in blocks) for k in _KEYS}


def _rate(blocks) -> float:
    s = sum(b["seconds"] for b in blocks)
    return sum(b["pollen"] for b in blocks) / s if s else 0.0


def _ci(draws) -> tuple[float, float]:
    draws, tail = sorted(draws), (1 - CI_LEVEL) / 2
    return draws[int(tail * len(draws))], draws[int((1 - tail) * len(draws)) - 1]


def pattern_verdict(a, b, boot: int = BOOT, seed: int = 0) -> dict:
    """Arm `b`'s blocks against arm `a`'s: point numbers and CI_LEVEL ranges.
    Pollen/s: whole blocks resampled with replacement on each side, as the
    relative gain b/a - 1. Landing and drift-out shares: differences drawn
    from Beta(k+1, n-k+1) posteriors, as benchmark.py does (27 landings of 27
    resample to 100% every time and would beat 90% "for certain"). "better"
    only when the pollen/s range is wholly above 0 and landing is not worse
    and drift-outs not more; "worse" when any of the three is measurably
    worse; else "unsure". One seed every call: the verdict does not flicker."""
    sa, sb = _sums(a), _sums(b)
    out = {"blocks": (len(a), len(b)), "trips": (sa["trips"], sb["trips"])}
    if min(len(a), len(b)) < MIN_BLOCKS or min(sa["trips"], sb["trips"]) < MIN_TRIPS:
        out["verdict"] = "too few"
        return out
    rng = random.Random(seed)
    ra, rb = _rate(a), _rate(b)
    out["pollen_s"] = (ra, rb)
    out["gain"] = rb / ra - 1 if ra else 0.0
    out["gain_ci"] = _ci([_rate(rng.choices(b, k=len(b)))
                          / max(1e-9, _rate(rng.choices(a, k=len(a)))) - 1
                          for _ in range(boot)])

    def diff(k, n):
        return _ci([rng.betavariate(sb[k] + 1, sb[n] - sb[k] + 1)
                    - rng.betavariate(sa[k] + 1, sa[n] - sa[k] + 1) for _ in range(boot)])

    out["landing"] = tuple(s["landed"] / s["judged"] if s["judged"] else None for s in (sa, sb))
    out["landing_ci"] = diff("landed", "judged")
    out["drift"] = (sa["drift"] / sa["trips"], sb["drift"] / sb["trips"])
    out["drift_ci"] = diff("drift", "trips")
    worse = out["gain_ci"][1] < 0 or out["landing_ci"][1] < 0 or out["drift_ci"][0] > 0
    out["verdict"] = "worse" if worse else "better" if out["gain_ci"][0] > 0 else "unsure"
    return out


def pattern_ab(rows, arms, now: float) -> dict:
    """What to walk in one field this clock hour. `arms[0]` is the field's
    own pattern. A challenger the verdict calls "better" is PROMOTED (the
    best-gaining one when several are) and walked every hour; one called
    "worse" leaves the turns; the rest take turns by `block_arm`.
    {"walk", "winner", "turns", "verdicts", "line"}: `line` says it in words."""
    blocks = pattern_blocks(rows, arms, since=now - WINDOW_S)
    verdicts = {arm: pattern_verdict(blocks[arms[0]], blocks[arm]) for arm in arms[1:]}
    better = [arm for arm, v in verdicts.items() if v["verdict"] == "better"]
    winner = max(better, key=lambda arm: verdicts[arm]["gain"]) if better else None
    turns = [arms[0]] + [arm for arm, v in verdicts.items() if v["verdict"] != "worse"]
    walk = winner or block_arm(now, turns)
    own = _sums(blocks[arms[0]])
    bits = [f"{arms[0]} {_rate(blocks[arms[0]]):,.0f} pollen/s over {len(blocks[arms[0]])} h, "
            f"walk home landed {own['landed']}/{own['judged']}, "
            f"drift-outs {own['drift']}/{own['trips']}"]
    unwalked = [arm for arm, v in verdicts.items() if not v["trips"][1]]
    if unwalked:
        bits.append("not walked yet: " + ", ".join(unwalked))
    for arm, v in verdicts.items():
        if arm in unwalked:
            continue
        if v["verdict"] == "too few":
            bits.append(f"{arm} too few ({v['blocks'][1]} h, {v['trips'][1]} trips; "
                        f"{MIN_BLOCKS} h and {MIN_TRIPS} trips a side)")
            continue
        lo, hi = v["gain_ci"]
        land = " vs ".join("-" if x is None else f"{x:.0%}" for x in v["landing"])
        bits.append(f"{arm} {v['verdict']}: {v['gain']:+.0%} pollen/s "
                    f"[{CI_LEVEL:.0%} {lo:+.0%}..{hi:+.0%}], walk home landed {land}, "
                    f"drift-outs {v['drift'][0]:.0%} vs {v['drift'][1]:.0%}")
    head = f"promote {winner}" if winner else f"this hour {walk}"
    return {"walk": walk, "winner": winner, "turns": turns, "verdicts": verdicts,
            "line": f"{head} ({'; '.join(bits)})"}


def field_pick(rows, arms, twin, now: float) -> dict:
    """PER-FIELD PICK (ROADMAP AI-N5): `pattern_ab` over the field's `arms`
    (the shape); once that has a CHAMPION -- a promoted winner, or arm 0
    when every challenger is measurably worse -- the champion against
    `twin(champion)` (act/patterns `twin`: a smaller size, or the sprinkler
    where the route lands), the same way. pattern_ab's dict, from the stage
    that decides this hour, plus "stage" (1 or 2) and "champion"; stage 2's
    line ends with stage 1's verdict. Still stateless: when the shape's
    evidence ages out of WINDOW_S the champion goes and stage 1 runs again."""
    first = pattern_ab(rows, arms, now)
    verdicts = first["verdicts"].values()
    champ = first["winner"] or (arms[0] if verdicts and all(
        v["verdict"] == "worse" for v in verdicts) else None)
    other = twin(champ) if champ else None
    if not other:
        return dict(first, stage=1, champion=champ)
    second = pattern_ab(rows, [champ, other], now)
    return dict(second, stage=2, champion=champ,
                line=f"{second['line']}; the shape is settled: {first['line']}")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "e.json"

        # unchanged: pick()/learn(v, r) with no context behave as before,
        # and every pick now also sets last_p, a probability in [0, 1]
        exp = Experiment(path, "press", [0.25, 0.35, 0.45], rng=random.Random(1))
        world = random.Random(2)
        truth = {0.25: 0.2, 0.35: 0.9, 0.45: 0.5}
        picks = []
        for _ in range(300):
            v = exp.pick()
            assert exp.last_p is not None and 0.0 <= exp.last_p <= 1.0
            picks.append(v)
            exp.learn(v, 1.0 if world.random() < truth[v] else 0.0)
        assert exp.best.value == 0.35
        assert picks[-100:].count(0.35) > 70          # it keeps trying the winner
        assert "learned: 0.35" in exp.describe()

        # 6b: a context's own stats are kept alongside the global ones, and
        # pick() uses them once the context has a few tries of its own
        ctx = Experiment(path, "ctx", [1, 2], rng=random.Random(5))
        for _ in range(20):
            ctx.learn(2, 1.0, context={"mode": "hot"})
            ctx.learn(1, 0.0, context={"mode": "hot"})
            ctx.learn(1, 1.0, context={"mode": "cold"})
            ctx.learn(2, 0.0, context={"mode": "cold"})
        hot = [ctx.pick(context={"mode": "hot"}) for _ in range(60)]
        cold = [ctx.pick(context={"mode": "cold"}) for _ in range(60)]
        assert hot.count(2) > hot.count(1)            # this context likes 2
        assert cold.count(1) > cold.count(2)          # this one likes 1
        assert 0.0 <= ctx.last_p <= 1.0

        # persisted: context stats round-trip through the file, nested under
        # the experiment's own body, next to (not instead of) the arm stats
        body = json.loads(path.read_text())
        assert set(body["ctx"]) >= {"1", "2", "_contexts"}
        assert set(body["ctx"]["_contexts"]) == {"mode='hot'", "mode='cold'"}
        again = Experiment(path, "ctx", [1, 2])
        hot_again = [again.pick(context={"mode": "hot"}) for _ in range(30)]
        assert hot_again.count(2) > hot_again.count(1)

        # under MIN_CONTEXT_TRIES, an unfamiliar context falls back to the
        # (here, equally untried) global stats rather than erroring
        fresh = Experiment(path, "fallback", [10, 20], rng=random.Random(7))
        assert fresh.pick(context={"mode": "brand-new"}) == 10

    print("ok")

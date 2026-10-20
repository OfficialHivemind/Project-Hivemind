"""The bot trying its own settings and keeping what measures best.

WHY. The owner, 2026-10-11: "improve its thinking ... to the point where it can
also train itself", after "it feels like its following if then statements". A
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

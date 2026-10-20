"""Self-tuning arms beside the sprinkler one (ROADMAP F0; the lead Claude's yes,
2026-10-21/22): per field, how full the bag goes before converting, and whether
tokens are chased at all. Each is a brain/experiment bandit in the field's
context, rewarded by the trip's honey a second (trips.jsonl's honey / seconds).

OFF BY DEFAULT (ARMS_LIVE False). Off, nothing the bot does changes: the trip
runs on the owner's settings, `would` says what the arm would have picked, and
`learn` still files the trip's reward under the value it really ran with -- so
the arms collect on-policy data for today's values before they are trusted to
choose. On, `pick` chooses.

THE CHASE ARM ONLY TURNS CHASING OFF (the lead, 2026-10-22 11:13): it is
asked only where chasing is already on, never where act/chase STAND_STILL or
run_farm NO_CHASE_FIELDS stop it, so it cannot bring chasing back there.

ponytail: the convert values (0.8 / 0.9 / 1.0 of the bag) bracket the 90%
default; whether 1.0 costs more in walking home full than it banks is exactly
what the arm is for.
"""
from __future__ import annotations

from . import experiment

ARMS_LIVE = False
CONVERT_AT = "convert at (share of the bag), per field"
CHASE = "chase tokens (1) or not (0), per field"
VALUES = {CONVERT_AT: (0.8, 0.9, 1.0), CHASE: (0.0, 1.0)}
LABEL = {CONVERT_AT: "convert at", CHASE: "chase"}
# Rewards are 0..1 (brain/experiment); honey a second over this is 1.
# ponytail: about twice the best measured rate (177M/h ~ 49k/s, the lead's
# STATUS 2026-10-21); a run that beats it simply saturates at 1.
REWARD_SCALE = 100_000.0


class Arms:
    """The two field arms over one experiments file."""

    def __init__(self, path, rng=None):
        self.exps = {name: experiment.Experiment(path, name, list(values), rng=rng)
                     for name, values in VALUES.items()}
        self.trip: dict = {}             # this trip's {name: value used}

    def begin(self, field: str, convert_at: float, chase_on: bool) -> dict:
        """A trip to `field` starts with the owner's `convert_at` and chase
        switch. Returns the values to run with: the owner's, unless ARMS_LIVE.
        Chasing is only ever turned off (see the module docstring)."""
        ctx = {"field": field}
        use = {CONVERT_AT: round(float(convert_at), 2), CHASE: 1.0 if chase_on else 0.0}
        if ARMS_LIVE:
            use[CONVERT_AT] = self.exps[CONVERT_AT].pick(context=ctx)
            if chase_on:
                use[CHASE] = self.exps[CHASE].pick(context=ctx)
        self.trip = {"field": field, **use}
        return use

    def would(self, field: str, chase_on: bool) -> str:
        """The look-only line: what the arms would pick for this trip."""
        ctx = {"field": field}
        bits = [f"convert at {self.exps[CONVERT_AT].pick(context=ctx):.0%}"]
        if chase_on:
            bits.append("chase" if self.exps[CHASE].pick(context=ctx) else "no chase")
        return f"arms would ({field}): " + ", ".join(bits)

    def learn(self, row: dict) -> list[str]:
        """File the finished trip's honey a second under the values it ran
        with. A trip with no measured honey or no seconds teaches nothing."""
        if not self.trip:
            return []
        field = self.trip["field"]
        honey, seconds = row.get("honey"), float(row.get("seconds") or 0)
        said = []
        if honey is not None and seconds > 0:
            reward = float(honey) / seconds
            for name in (CONVERT_AT, CHASE):
                value = self.trip.get(name)
                if value in VALUES[name]:      # a value outside the arm teaches it nothing
                    self.exps[name].learn(value, reward, scale=REWARD_SCALE,
                                          context={"field": field})
                    said.append(f"{LABEL[name]} {value:g}")
        self.trip = {}
        return said

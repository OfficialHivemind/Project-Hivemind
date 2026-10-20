"""Every next action priced in honey (backlog B1, docs/pending/brain-research-3.md).

WHY. The owner, 2026-10-11: the bot "feels like old siri" -- its errands run in
a fixed order because tickets, treats and honey had no exchange rate. Here each
due errand gets one number, its value against gathering for the same time:

    Q = p*(V + D) - rho * E[T]          E[T] = p*T_landed + (1-p)*T_failed

p is the route's landing odds (brain/skills), V the payout in honey (PAYS x
PRICES), rho the honey a second gathering would make instead, D what a
cooldown errand loses by waiting one more trip (V * trip / cooldown). Q > 0 is
"worth leaving the field for"; the order is Smith's rule, Q per second first.

B1 IS A SHADOW: run_farm logs "would have run ..." and nothing acts on it.
A payout nobody priced stays None (unpriced), never 0, and keeps today's order.
"""
from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path

# HONEY A UNIT. A ticket's ceiling is the Ticket Shop's marginal price
# (100,000 + 1,000 n^1.2, research pass 2, n = 0 here); the owner keeps tickets
# for Star Treats and Diamond Eggs, so it is a price, not a reason to buy.
PRICES = {
    "honey": 1.0,
    "ticket": 100_000.0,
}


def _honey_dispenser(bees: int) -> dict:
    return {"honey": math.floor(bees ** 1.7 + 0.5) * 100}      # errands.yaml


def _wealth_clock(bees: int) -> dict:
    return {"ticket": 5}            # 1, 2, 3, 4, then 5 a use (errands.yaml)


# WHAT EACH ERRAND PAYS, from errands.yaml's `gives:`. Only the goods with a
# price are here; the rest (treats, blueberries, boosts, ant passes) are B2's,
# once payouts are measured.
PAYS = {
    "honey_dispenser": _honey_dispenser,
    "wealth_clock": _wealth_clock,
}


@dataclass
class Scored:
    name: str
    q: float | None                 # None: unpriced
    seconds: float
    p: float
    v: float | None
    ready_in: float = 0.0           # B5: seconds until it is due (0: due now)


# B2: MEASURED PAYOUTS. Each place use appends {name, at, honey} (the HUD's
# honey either side of the use); the place's honey is their discounted mean,
# the newest weighing most (as experiment.DISCOUNT), so it follows a growing
# hive. Under MIN_PAYOUTS rows the formula above still prices it.
PAYOUT_DISCOUNT = 0.9
MIN_PAYOUTS = 3


def record_payout(path, name: str, honey: int, at: float) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"name": name, "at": round(at, 1), "honey": int(honey)}) + "\n")


def measured_honey(path, name: str) -> float | None:
    """The discounted mean honey of `name`'s recorded uses; None under MIN_PAYOUTS."""
    try:
        rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    except (OSError, ValueError):
        return None
    got = [float(r.get("honey") or 0) for r in rows if r.get("name") == name]
    if len(got) < MIN_PAYOUTS:
        return None
    weights = [PAYOUT_DISCOUNT ** k for k in range(len(got) - 1, -1, -1)]
    return sum(w * h for w, h in zip(weights, got)) / sum(weights)


# B6a: THOMPSON FOR UNMEASURED PLACES. Under MIN_PAYOUTS, measured_honey() is
# None -- the place's p (landing odds) is as thin as its payout, so score()
# may draw a Thompson sample of p instead of trusting the caller's point
# estimate, the same way skills.choose already explores routes.
def explore_bonus(landed: int, failed: int, rng) -> float:
    """A Thompson draw of a landing probability from Beta(landed+1, failed+1)."""
    return rng.betavariate(1 + landed, 1 + failed)


def payout(name: str, bees: int, measured_honey: float | None = None) -> float | None:
    """V in honey, or None when it pays nothing priced and nothing measured.
    Measured honey replaces the formula's; with it, unpriced goods (treats,
    boosts) are left out, so V is a lower bound."""
    pays = PAYS.get(name)
    goods = dict(pays(bees)) if pays else {}
    # A MEASURED ZERO IS NOT A PRICE: an ant pass or a booster pays nothing
    # on the HUD, and V = 0 would read "worthless" -- with nothing else priced
    # it stays unpriced
    if measured_honey is not None and (measured_honey >= 1 or goods):
        goods["honey"] = measured_honey
        goods = {g: n for g, n in goods.items() if g in PRICES}
    if not goods or any(g not in PRICES for g in goods):
        return None
    return float(sum(PRICES[g] * n for g, n in goods.items()))


def q(v: float | None, p: float, seconds: float, rho: float,
      fail_seconds: float | None = None, cooldown_s: float = 0.0,
      trip_s: float = 0.0) -> float | None:
    """The formula above; None when the payout is unpriced."""
    if v is None:
        return None
    t = p * seconds + (1.0 - p) * (fail_seconds if fail_seconds is not None else seconds)
    d = v * trip_s / cooldown_s if cooldown_s > 0 else 0.0
    return p * (v + d) - rho * t


def score(name: str, *, bees: int, p: float | None, seconds: float | None,
          rho: float, fail_seconds: float | None = None, cooldown_s: float = 0.0,
          trip_s: float = 0.0, measured_honey: float | None = None,
          rng=None, landed: int = 0, failed: int = 0) -> Scored:
    """`rng=None` keeps today's deterministic behaviour (`p`, or 0.5 with no
    verdict). With an `rng` and an unmeasured place (measured_honey is None,
    i.e. under MIN_PAYOUTS), `p` is instead a Thompson draw from `landed`/
    `failed` (explore_bonus) -- an untried place gets tried, same as an arm."""
    if rng is not None and measured_honey is None:
        p = explore_bonus(landed, failed, rng)
    else:
        p = 0.5 if p is None else p             # the skills prior with no verdict
    seconds = seconds or 60.0
    v = payout(name, bees, measured_honey)
    return Scored(name, q(v, p, seconds, rho, fail_seconds, cooldown_s, trip_s),
                  seconds, p, v)


def order(rows: list[Scored]) -> list[Scored]:
    """Smith's rule: the highest Q a second first; unpriced last, in the
    order given (today's order)."""
    priced = sorted((r for r in rows if r.q is not None),
                    key=lambda r: r.q / max(r.seconds, 1.0), reverse=True)
    return priced + [r for r in rows if r.q is None]


def due_in(ready_at: float, read_at: float, last: float, hours: float,
           now: float) -> float:
    """Seconds until a place is TRULY due: 0 when due, inf when it never will
    be (no cooldown known and used once). A timer read after the last use is
    a deadline and wins over `hours`, the wiki's period. How early a walk may
    set out is the caller's (run_farm `_next_usable`), never folded in here:
    MEASURED 2026-10-22 (var/night, 16:52:25) the planner logged the clock
    "due in 37s" when it was 337 s away -- the 300 s early window had been
    subtracted -- and it then stood 288 s at the machine."""
    if ready_at and read_at >= last:
        return max(0.0, ready_at - now)
    if hours > 0 and now - last < hours * 3600:
        return hours * 3600 - (now - last)
    if hours <= 0 and last > 0:
        return float("inf")
    return 0.0


# B5: THE ERRAND PLANNER (ROADMAP B5 METHOD, work Claude 2026-10-15). Every
# second away from gathering costs `rate` honey; an errand's profit is
# p*V - rate*(wait + seconds). At each decision every order of the next
# PLAN_DEPTH ready-or-nearly-ready errands is tried, the best profit a second
# wins, only its FIRST is done, then it replans. No errand may overlap a
# `windows` appointment (start, end), seconds from now. Unpriced errands keep
# today's order, after the priced ones.
NEARLY_READY_S = 120.0
PLAN_DEPTH = 4
NEAR_HIVE_S = 60.0          # an errand this short counts as "near the hive"


def profit(r: Scored, rate: float, wait: float = 0.0,
           home_saved_s: float = 0.0) -> float | None:
    """p*V - rate*(wait + seconds); a near-hive errand is credited the walk
    home that happens anyway (`home_saved_s`). None when unpriced."""
    if r.v is None:
        return None
    credit = home_saved_s if r.seconds <= NEAR_HIVE_S else 0.0
    return r.p * r.v - rate * (wait + r.seconds - credit)


def plan(rows: list[Scored], rate: float, *, windows=(), home_saved_s: float = 0.0,
         depth: int = PLAN_DEPTH, keep=()):
    """(first, sequence, skipped). `skipped` are the priced errands that lose
    to gathering even with no wait (never one named in `keep`); `first` is the
    best sequence's first, else the first ready unpriced errand, else None."""
    def fits(t, end):
        return not any(t < b and a < end for a, b in windows)

    priced = [r for r in rows if r.v is not None and r.ready_in <= NEARLY_READY_S]
    skipped = [r for r in priced
               if r.name not in keep and profit(r, rate, 0.0, home_saved_s) <= 0]
    go = sorted((r for r in priced if r not in skipped),
                key=lambda r: profit(r, rate, r.ready_in, home_saved_s)
                / max(r.ready_in + r.seconds, 1.0), reverse=True)[:depth]
    best, best_rate = (), float("-inf")
    # ponytail: all orders of all subsets, sum_n 4!/(4-n)! = 64 at depth 4
    for n in range(1, len(go) + 1):
        for seq in itertools.permutations(go, n):
            t = gain = 0.0
            for i, r in enumerate(seq):
                wait = max(0.0, r.ready_in - t)
                end = t + wait + r.seconds
                if not fits(t, end):
                    break
                gain += profit(r, rate, wait, home_saved_s if i == 0 else 0.0)
                t = end
            else:
                if gain / max(t, 1.0) > best_rate:
                    best, best_rate = seq, gain / max(t, 1.0)
    unpriced = [r for r in rows if r.v is None and r.ready_in <= 0 and fits(0.0, r.seconds)]
    first = best[0] if best else (unpriced[0] if unpriced else None)
    return first, list(best), skipped


# B6b: VALUE OF INFORMATION for a recon (reading a panel or giver). Zero once
# the answer is already known, since then reading it changes nothing -- that
# is p_useful = 0, so the formula needs no separate "already known" branch.
def recon_value(p_useful: float, q_unlocked: float, uses_horizon: float) -> float:
    """What a recon is worth: the chance it still tells us something new,
    times the Q of the action it would unlock (never negative -- a recon
    isn't charged for an action we wouldn't take anyway), times how many
    times that answer gets used before the horizon."""
    return p_useful * max(0.0, q_unlocked) * uses_horizon


# B6c: room for the local-LLM price advisor (research pass 3 S6) -- it only
# ever proposes a price inside this band; no call to it lives here.
def bounded_price_proposal(current: float, proposed: float) -> float:
    """Clamp a proposed price to 0.5x-2x of the current one."""
    return min(2.0 * current, max(0.5 * current, proposed))


def say(rows: list[Scored], rho: float) -> str:
    """One line: what it would run, what it would skip, and why."""
    if not rows:
        return "nothing due"
    go = [r for r in rows if r.q is None or r.q > 0]
    skip = [r for r in rows if r.q is not None and r.q <= 0]

    def one(r):
        if r.q is None:
            return f"{r.name.replace('_', ' ')} (unpriced)"
        return f"{r.name.replace('_', ' ')} (Q {r.q / 1000:+,.0f}k, {r.p:.0%} lands)"
    out = "would run " + (", ".join(map(one, go)) or "nothing")
    if skip:
        out += "; would skip " + ", ".join(map(one, skip))
    return out + f" -- gathering pays {rho:,.0f} honey/s"


if __name__ == "__main__":
    # the research's worked check (pass 3 section 3): 41 bees, rho 8k/s
    hd = score("honey_dispenser", bees=41, p=0.22, seconds=8, rho=8000)
    assert hd.v == math.floor(41 ** 1.7 + 0.5) * 100
    clock = score("wealth_clock", bees=41, p=0.93, seconds=49, rho=8000,
                  cooldown_s=3600, trip_s=600)
    assert clock.q > 0 and hd.q < clock.q
    ranked = order([score("ant_pass", bees=41, p=0.8, seconds=34, rho=8000), hd, clock])
    assert ranked[0].name == "wealth_clock" and ranked[-1].name == "ant_pass"
    print(say(ranked, 8000))
    # B2: a measured treat dispenser (treats unpriced) is priced by its honey
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "payouts.jsonl"
        assert measured_honey(log, "treat_dispenser") is None
        for h in (20_000, 20_000, 40_000):
            record_payout(log, "treat_dispenser", h, 0.0)
        m = measured_honey(log, "treat_dispenser")
        assert 26_000 < m < 40_000                   # the newest weighs most
        assert payout("treat_dispenser", 41, m) == m
        assert payout("treat_dispenser", 41) is None
        assert payout("wealth_clock", 41, 0.0) == 5 * PRICES["ticket"]
        assert payout("ant_pass", 41, 0.0) is None        # pays only unpriced goods

    # B6a: rng=None (the default) is untouched -- still today's p, or 0.5
    import random
    assert score("x", bees=1, p=None, seconds=1, rho=1).p == 0.5
    assert score("x", bees=1, p=0.9, seconds=1, rho=1).p == 0.9     # no rng: untouched
    # measured place: an rng is given, but it's ignored once there's a mean to trust
    measured = score("x", bees=1, p=0.9, seconds=1, rho=1,
                      measured_honey=100.0, rng=random.Random(2), landed=0, failed=0)
    assert measured.p == 0.9
    # unmeasured place with an rng: p is drawn, not the given point estimate
    draws = {score("x", bees=1, p=0.9, seconds=1, rho=1, rng=random.Random(i),
                    landed=0, failed=0).p for i in range(20)}
    assert len(draws) > 1                                 # it varies -- a real draw
    hi = score("x", bees=1, p=None, seconds=1, rho=1, rng=random.Random(3),
               landed=50, failed=0).p
    lo = score("x", bees=1, p=None, seconds=1, rho=1, rng=random.Random(3),
               landed=0, failed=50).p
    assert hi > lo                                         # landed/failed steer the draw

    # B6b: value of information for a recon -- zero once the answer is known
    assert recon_value(0.0, 100, 10) == 0
    assert recon_value(0.5, -5, 10) == 0                   # never paid for a bad unlock
    assert recon_value(0.5, 100, 4) == 200

    # B6c: a proposed price is clamped to 0.5x-2x of today's
    assert bounded_price_proposal(100, 40) == 50
    assert bounded_price_proposal(100, 300) == 200
    assert bounded_price_proposal(100, 150) == 150
    print("ok")

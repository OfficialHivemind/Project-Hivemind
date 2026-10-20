"""Shadow prices: what one unit of a resource is worth, in honey.

A shadow price is the honey you would gain from having one more of something. It
is simultaneously the objective function, the explanation, the planter scorer and
the spend oracle -- and it is the number no human player has, because nobody
knows what a Glitter is worth this particular afternoon.

HOW THIS ONE STAYS HONEST

The tempting version hardcodes a table: royal jelly 47,300, glitter 212,000, and
so on. Those numbers would be invented, they would look authoritative in a GUI,
and every planner decision would inherit the invention.

So nothing is hardcoded. Honey is the numeraire at 1.0 by definition, and every
other price has to be DERIVED from something the bot actually observed:

    an exchange      a shop price, a crafting recipe, a quest reward -- any
                     place the game itself states a rate between two things
    the clock        the bot measures its own honey per hour, so time has a
                     price and anything that costs time can be valued

A resource with no observed path to honey has NO price, and `price()` returns
None rather than a plausible-looking number. The Economy panel shows it as
unknown. That is the correct state for an account the bot has not explored yet,
and it fills in as the bot reads shop windows and completes recipes.

Prices are found by best-path search over the exchange graph: the value of a
resource is the most honey any observed chain of exchanges can turn it into.
Exchanges carry an observation time and decay in confidence like any other
belief, because a shop price seen two days ago is weaker evidence than one seen
a minute ago.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

HONEY = "Honey"
DEFAULT_HALF_LIFE = 6 * 3600.0     # an observed rate halves in weight over 6h
MIN_CONFIDENCE = 0.05              # below this an exchange is ignored entirely


@dataclass(frozen=True)
class Exchange:
    """An observed rate: `count` of `gives` per one of `takes`.

    Example: the bot reads a shop offering 1 Treat for 200 honey, which is an
    Exchange(takes="Honey", gives="Treat", count=1/200). The reverse is not
    assumed -- shops rarely buy back, and assuming symmetry is how a valuation
    model invents money.
    """
    takes: str
    gives: str
    count: float
    observed_at: float
    source: str = ""
    half_life: float = DEFAULT_HALF_LIFE

    def confidence(self, now: float | None = None) -> float:
        age = max(0.0, (time.time() if now is None else now) - self.observed_at)
        if self.half_life <= 0:
            return 1.0
        return math.pow(0.5, age / self.half_life)


@dataclass
class Price:
    resource: str
    honey: float
    confidence: float
    path: tuple[str, ...]
    basis: str

    def __str__(self) -> str:
        return f"{self.resource}: {self.honey:,.0f} honey ({self.basis})"


class PriceGraph:
    """Derives shadow prices from observed exchanges only."""

    def __init__(self):
        # ONE PER (takes, gives, source), the newest. A list grew without end:
        # Dashboard.refresh re-observes the same static exchanges every 60 s
        # (~2,500 an hour) and price() rescanned them all every minute.
        self._exchanges: dict[tuple[str, str, str], Exchange] = {}
        self.honey_per_hour: float | None = None

    # ---- observation ------------------------------------------------------
    def observe_exchange(self, takes: str, gives: str, count: float,
                         source: str = "", at: float | None = None) -> Exchange:
        exchange = Exchange(takes=takes, gives=gives, count=float(count),
                            observed_at=time.time() if at is None else at,
                            source=source)
        self._exchanges[(takes, gives, source)] = exchange
        return exchange

    def observe_shop_price(self, item: str, honey_cost: float,
                           source: str = "shop", at: float | None = None) -> None:
        """A shop selling `item` for honey gives a rate in both useful senses.

        Buying tells you honey -> item. It also bounds item -> honey from below:
        if you can buy one for 200 honey then having one is worth AT LEAST the
        200 you did not have to spend, provided you wanted one. That is the
        standard replacement-cost argument and it is the only reverse direction
        taken, deliberately.
        """
        if honey_cost <= 0:
            return
        self.observe_exchange(HONEY, item, 1.0 / honey_cost, source, at)
        self.observe_exchange(item, HONEY, honey_cost, f"{source} (replacement)", at)

    def set_honey_rate(self, honey_per_hour: float) -> None:
        """The measured gather rate, which is what gives TIME a price."""
        self.honey_per_hour = max(0.0, honey_per_hour)

    def price_of_time(self, seconds: float) -> float | None:
        if self.honey_per_hour is None:
            return None
        return self.honey_per_hour * seconds / 3600.0

    # ---- valuation --------------------------------------------------------
    def price(self, resource: str, now: float | None = None) -> Price | None:
        """Best honey value reachable from `resource`, or None if unknown."""
        if resource == HONEY:
            return Price(HONEY, 1.0, 1.0, (HONEY,), "numeraire")

        # Maximise the product of rates along a chain, in log space.
        #
        # NOT Dijkstra. An exchange rate above 1 gives a POSITIVE log weight,
        # and longest-path with positive weights is not a Dijkstra problem:
        # popping a node does not mean its value is final, because a longer
        # chain through a cheaper first hop can still be worth far more. The
        # old code marked nodes `seen` on pop and skipped them afterwards, so
        # a later improvement was written but never propagated onward.
        # Measured: R->A at 3x and R->B at 2x with B->A at 100x priced R at 3
        # honey instead of 200, because A was finalised at 3x before B was
        # ever popped. Every resource whose best chain runs through a
        # shorter-but-worse hop was under-priced -- and this price is the
        # objective function for planter scoring, the spend oracle and the
        # blender planner, so it was wrong everywhere at once.
        #
        # So: relax to a fixed point, Bellman-Ford style. The exchange list is
        # small (tens of entries), and rates are all finite and positive, so
        # there are no profitable cycles to diverge on -- but the pass counter
        # bounds it regardless.
        best: dict[str, float] = {resource: 0.0}       # log(value), start at 1x
        conf: dict[str, float] = {resource: 1.0}
        via: dict[str, tuple[str, ...]] = {resource: (resource,)}
        source_of: dict[str, str] = {resource: ""}

        usable = [e for e in self._exchanges.values()
                  if e.confidence(now) >= MIN_CONFIDENCE and e.count > 0]
        nodes = {e.takes for e in usable} | {e.gives for e in usable} | {resource}

        for _ in range(len(nodes)):
            changed = False
            for exchange in usable:
                if exchange.takes not in best:
                    continue
                candidate = best[exchange.takes] + math.log(exchange.count)
                if candidate > best.get(exchange.gives, -math.inf) + 1e-12:
                    # A cycle would loop back through `resource` and inflate it
                    # forever; refuse to route a chain through its own start.
                    if exchange.gives in via[exchange.takes]:
                        continue
                    best[exchange.gives] = candidate
                    conf[exchange.gives] = min(conf[exchange.takes],
                                               exchange.confidence(now))
                    via[exchange.gives] = via[exchange.takes] + (exchange.gives,)
                    source_of[exchange.gives] = exchange.source
                    changed = True
            if not changed:
                break

        if HONEY not in best:
            return None
        value = math.exp(best[HONEY])
        path = via[HONEY]
        basis = (source_of[HONEY] or "observed exchange") if len(path) == 2 else \
            f"via {' -> '.join(path[1:-1])}"
        return Price(resource, value, conf[HONEY], path, basis)

    def known_resources(self, now: float | None = None) -> list[str]:
        names = {e.takes for e in self._exchanges.values()} | \
            {e.gives for e in self._exchanges.values()}
        return sorted(n for n in names
                      if n != HONEY and self.price(n, now) is not None)

    def unpriced(self, candidates: list[str], now: float | None = None) -> list[str]:
        """Resources we have heard of but cannot value. Honest gaps, listed."""
        return [c for c in candidates
                if c != HONEY and self.price(c, now) is None]

    def __len__(self) -> int:
        return len(self._exchanges)

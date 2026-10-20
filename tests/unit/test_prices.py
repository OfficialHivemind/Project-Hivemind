"""Shadow prices.

The tests that matter are the ones about NOT having a price. A valuation model
that always returns a number looks authoritative and is frequently inventing
money; this one must return None for anything it has not observed a path to
honey for, and the Economy panel must be able to show that honestly.
"""
import pytest

from hivemind.economy.prices import HONEY, PriceGraph

HOUR = 3600.0


def test_honey_is_the_numeraire():
    p = PriceGraph().price(HONEY)
    assert p.honey == 1.0
    assert p.basis == "numeraire"


def test_an_unobserved_resource_has_no_price():
    """The whole point: no invented numbers."""
    assert PriceGraph().price("Royal Jelly") is None


def test_a_single_observed_exchange_prices_a_resource():
    g = PriceGraph()
    g.observe_exchange("Ticket", HONEY, 5_000, source="ticket shop", at=0.0)
    p = g.price("Ticket", now=0.0)
    assert p.honey == pytest.approx(5_000)
    assert p.path == ("Ticket", HONEY)


def test_a_chain_of_exchanges_is_followed():
    g = PriceGraph()
    g.observe_exchange("Glitter", "Star Jelly", 2.0, at=0.0)
    g.observe_exchange("Star Jelly", HONEY, 100_000, at=0.0)
    p = g.price("Glitter", now=0.0)
    assert p.honey == pytest.approx(200_000)
    assert "Star Jelly" in p.path
    assert "via" in p.basis


def test_the_best_path_wins_not_the_first():
    g = PriceGraph()
    g.observe_exchange("Ticket", HONEY, 5_000, at=0.0)
    g.observe_exchange("Ticket", "Gumdrops", 10.0, at=0.0)
    g.observe_exchange("Gumdrops", HONEY, 900, at=0.0)      # 9,000 total
    assert g.price("Ticket", now=0.0).honey == pytest.approx(9_000)


def test_shop_price_gives_a_replacement_value():
    g = PriceGraph()
    g.observe_shop_price("Treat", 200, at=0.0)
    assert g.price("Treat", now=0.0).honey == pytest.approx(200)


def test_a_free_item_is_ignored_rather_than_dividing_by_zero():
    g = PriceGraph()
    g.observe_shop_price("Freebie", 0, at=0.0)
    assert g.price("Freebie") is None
    assert len(g) == 0


def test_confidence_decays_with_the_age_of_the_observation():
    g = PriceGraph()
    g.observe_exchange("Ticket", HONEY, 5_000, at=0.0)
    fresh = g.price("Ticket", now=0.0).confidence
    stale = g.price("Ticket", now=6 * HOUR).confidence
    assert fresh == pytest.approx(1.0)
    assert stale == pytest.approx(0.5, abs=0.01)


def test_an_ancient_observation_stops_counting_entirely():
    g = PriceGraph()
    g.observe_exchange("Ticket", HONEY, 5_000, at=0.0)
    assert g.price("Ticket", now=100 * HOUR) is None


def test_time_has_no_price_until_the_rate_is_measured():
    g = PriceGraph()
    assert g.price_of_time(3600) is None
    g.set_honey_rate(431_000)
    assert g.price_of_time(3600) == pytest.approx(431_000)
    assert g.price_of_time(1800) == pytest.approx(215_500)


def test_reverse_direction_is_not_invented():
    """Observing honey -> item must not on its own price item -> honey."""
    g = PriceGraph()
    g.observe_exchange(HONEY, "Ticket", 1 / 5_000, at=0.0)
    assert g.price("Ticket", now=0.0) is None


def test_unpriced_lists_the_honest_gaps():
    g = PriceGraph()
    g.observe_exchange("Ticket", HONEY, 5_000, at=0.0)
    gaps = g.unpriced(["Ticket", "Glitter", "Royal Jelly"], now=0.0)
    assert gaps == ["Glitter", "Royal Jelly"]


def test_known_resources_only_lists_priceable_ones():
    g = PriceGraph()
    g.observe_exchange("Ticket", HONEY, 5_000, at=0.0)
    g.observe_exchange("Mystery", "Nothing", 1.0, at=0.0)
    assert g.known_resources(now=0.0) == ["Ticket"]


def test_a_cycle_does_not_hang():
    g = PriceGraph()
    g.observe_exchange("A", "B", 2.0, at=0.0)
    g.observe_exchange("B", "A", 2.0, at=0.0)
    g.observe_exchange("B", HONEY, 10.0, at=0.0)
    assert g.price("A", now=0.0).honey == pytest.approx(20.0)


# --- the search must not finalise a node too early --------------------------
# Rates above 1 are POSITIVE log-weights, so this is a longest-path problem and
# Dijkstra's "popped means final" invariant does not hold. The old code marked
# nodes seen on pop, so a better chain discovered later was written but never
# propagated. Shadow prices are the planner's objective function, so an
# under-priced resource is wrong everywhere at once.

def test_a_cheap_first_hop_to_a_far_better_chain_is_not_discarded():
    g = PriceGraph()
    g.observe_exchange("R", "A", 3.0)       # tempting: 3x in one hop
    g.observe_exchange("R", "B", 2.0)       # worse first hop...
    g.observe_exchange("B", "A", 100.0)     # ...but 200x in total
    g.observe_exchange("A", "Honey", 1.0)
    price = g.price("R")
    assert price.honey == pytest.approx(200.0)
    assert price.path == ("R", "B", "A", "Honey")


def test_improvements_propagate_through_a_long_chain():
    g = PriceGraph()
    for takes, gives, rate in [("X", "Y", 1.5), ("X", "Z", 1.1),
                               ("Z", "Y", 50.0), ("Y", "W", 2.0),
                               ("W", "Honey", 1.0)]:
        g.observe_exchange(takes, gives, rate)
    price = g.price("X")
    assert price.honey == pytest.approx(110.0)
    assert price.path == ("X", "Z", "Y", "W", "Honey")


def test_a_cycle_does_not_inflate_a_price_forever():
    """Relaxing to a fixed point must terminate even with a round trip."""
    g = PriceGraph()
    g.observe_exchange("P", "Q", 2.0)
    g.observe_exchange("Q", "P", 2.0)        # P -> Q -> P doubles twice
    g.observe_exchange("Q", "Honey", 1.0)
    price = g.price("P")
    assert price is not None
    assert price.honey == pytest.approx(2.0)
    assert price.path == ("P", "Q", "Honey")

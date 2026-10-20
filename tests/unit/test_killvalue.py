"""A kill's worth: the measured ticket and honey rates, the wiki as the prior
(brain/mobtable.blend; the counts are mobs.yaml `measured:`, docs/pending/mobs-k7.md)."""
from __future__ import annotations

from hivemind.brain import mobtable


def test_the_blend_is_the_wiki_until_kills_come_in_then_the_measured_rate():
    k = mobtable.PRIOR_KILLS
    assert mobtable.blend(0.25, 0, 0) == (0.25, "wiki")
    rate, src = mobtable.blend(0.25, 0, 1)              # one unlucky kill: not 0
    assert 0.2 < rate < 0.25 and src == "wiki + 1 kills"
    rate, src = mobtable.blend(0.25, 8, 283)            # Spider, 8 of 283
    assert rate == (k * 0.25 + 8) / (k + 283) and src == "measured, 283 kills"
    assert abs(mobtable.blend(0.25, 280, 10_000)[0] - 0.028) < 0.002


def test_the_measured_ticket_rates_price_spider_and_mantis_far_below_the_wiki():
    got = {m: mobtable.ticket_rate(m)[0] for m in
           ("ladybug", "rhino_beetle", "spider", "mantis", "scorpion", "werewolf")}
    for m, rate in got.items():
        assert 0 < rate < mobtable.mob(m)["ticket_chance"], m      # floor and below wiki
    assert got["spider"] < 0.25 / 2.5 and got["mantis"] < 0.20 / 4
    assert got["werewolf"] > 0.30                          # 54 of 171: still the ticket mob
    assert mobtable.ticket_rate("spider")[1] == "measured, 283 kills"
    # live counts override mobs.yaml's
    assert mobtable.ticket_rate("spider", kills=0) == (0.25, "wiki")
    assert mobtable.ticket_rate("nobody") == (0.0, "unknown")


def test_honey_a_kill_is_measured_too():
    # the feed's honey holds the account's multipliers: Mantis 2,988 vs wiki 250
    assert 2000 < mobtable.kill_honey("mantis")[0] < 2988
    assert 416 < mobtable.kill_honey("spider")[0] < 1000   # the one mob under the wiki
    assert mobtable.kill_honey("mantis", kills=10, honey_total=0)[0] < 250

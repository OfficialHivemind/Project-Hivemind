"""brain/waxcalc (H4b): the RQValue port and the wax odds, on hand-made pools.
No wiki data here (CC BY-SA); fetch() is tested against a tiny cached table."""
from __future__ import annotations

import json
import random
import time

import pytest

from hivemind.brain import waxcalc as W

WAXES = {"soft": {"power": 1, "success": 1.0}, "hard": {"power": 2, "success": 0.6},
         "caustic": {"power": 4, "success": 0.25}}


# ---- resolve (Module:RQValue) ------------------------------------------------------
def test_a_constant_and_a_linear_chance_resolve_as_the_module_does():
    assert W.resolve(0.33, 0.7) == 0.33
    lin = {"Linear": True, "Value": [0.1, 0.25]}
    assert W.resolve(lin, 0.0) == pytest.approx(0.1)
    assert W.resolve(lin, 1.0) == pytest.approx(0.25)
    assert W.resolve(lin, 0.5) == pytest.approx(0.175)
    # ScalingPower without Bias is linear on quality ** power
    assert W.resolve({"ScalingPower": 2, "Value": [0.1, 1]}, 0.5) == pytest.approx(0.1 + 0.9 * 0.25)


def test_a_bare_range_a_nested_value_and_resolution():
    rng = random.Random(3).random
    v = W.resolve([1, 2], 0.5, rng)                 # a bare {lo, hi}: RandomBias between them
    assert 1 <= v <= 2
    assert W.resolve({"Value": {"Value": 0.01}}, 0.4) == 0.01
    r = W.resolve({"Value": [1, 2], "Resolution": 1, "Bias": [3, 1]}, 0.9, rng)
    assert r in (1, 2)


def test_random_bias_stays_between_its_limits_and_leans_to_the_bias():
    rng = random.Random(7).random
    vals = [W.random_bias(0, 10, 9, 1, rng) for _ in range(4000)]
    assert min(vals) >= 0 and max(vals) <= 10
    assert sum(vals) / len(vals) > 6          # pulled toward 9 (uniform alone would be ~5)


def test_a_failed_own_chance_roll_is_none():
    assert W.resolve({"Chance": 0.0, "Value": 5}, 1.0, lambda: 0.5) is None
    assert W.resolve({"Chance": 1.0, "Value": 5}, 1.0, lambda: 0.5) == 5


# ---- odds ------------------------------------------------------------------------
def pool(*rows):
    return [W.Upgrade(*r) for r in rows]


def test_one_stat_and_a_soft_wax_is_certain():
    got = W.odds(pool(("A", 1.0)), ["soft"], "A", quality=0.6, trials=500, table=WAXES)
    assert got["p"] == 1.0 and got["destroyed"] == 0.0
    assert got["method"] == "seeded Monte Carlo" and "UNCONFIRMED" in got["note"]


def test_equal_weights_split_a_point_evenly():
    got = W.odds(pool(("A", 1.0), ("B", 1.0)), ["soft"], "A", quality=0.6,
                 trials=20_000, table=WAXES)
    assert got["p"] == pytest.approx(0.5, abs=0.02)


def test_a_maxed_stat_leaves_the_pool():
    # A can take 1 point; three Softs on A + B: A never reaches 2, so B always
    # gets at least 2 of the 3 points (exactly 1.0, not a sample).
    p = pool(("A", 1.0, 1), ("B", 1.0))
    assert W.odds(p, ["soft"] * 3, "A", 2, quality=0.5, trials=2000, table=WAXES)["p"] == 0.0
    assert W.odds(p, ["soft"] * 3, "B", 2, quality=0.5, trials=2000, table=WAXES)["p"] == 1.0


def test_a_caustic_only_stat_needs_a_caustic_and_a_failed_one_destroys():
    p = pool(("Gold", 1.0, 1, True), ("Plain", 1.0))
    assert W.odds(p, ["soft"] * 5, "Gold", quality=0.5, trials=500, table=WAXES)["p"] == 0.0
    got = W.odds(p, ["caustic"], "Gold", quality=0.5, trials=20_000, table=WAXES)
    assert got["destroyed"] == pytest.approx(0.75, abs=0.02)
    assert 0 < got["p"] <= 0.25


def test_the_same_seed_gives_the_same_answer_and_unknowns_say_so():
    p = pool(("A", 1.0), ("B", {"Linear": True, "Value": [0.5, 2]}))
    a = W.odds(p, ["hard", "soft"], "A", quality=0.8, trials=3000, seed=5, table=WAXES)
    b = W.odds(p, ["hard", "soft"], "A", quality=0.8, trials=3000, seed=5, table=WAXES)
    assert a == b
    with pytest.raises(KeyError):
        W.odds(p, ["turbo"], "A", quality=0.5, table=WAXES)
    with pytest.raises(KeyError):
        W.odds(p, ["soft"], "C", quality=0.5, table=WAXES)


def test_the_repos_wax_table_has_the_three_upgrade_waxes():
    table = W.wax_table()
    assert {"soft", "hard", "caustic"} <= set(table)
    assert table["caustic"]["power"] == 4 and table["hard"]["success"] == 0.6


# ---- the wiki table, read from a cache -------------------------------------------
TINY = '''-- files are taken directly from the game
local data = {}

data["Tiny Hat"] = {
    Description = "A hat\\'s [[note]]",
    Check = function(x) if x then return 1 end end,
    Upgrades = {
        { BeeStat = "GatherAdd", Max = 20, Value = { 1, 2 }, Chance = 0.33 },
        { HiveBonusStat = "PollenBonus", Op = "Add", Params = { Zone = "Rose Field" },
          Max = 10, Chance = { Linear = true, Value = { 0.02, 0.1 } } },
        { BeeAbilityPoolId = "Boost", CausticOnly = true, Max = 1, Chance = 0.01 },
    }
}

return data
'''


def test_fetch_reads_the_cached_table_and_names_every_upgrade(tmp_path, monkeypatch):
    cache = tmp_path / "beequip_stats.json"
    cache.write_text(json.dumps({"at": time.time(), "revid": 1, "wikitext": TINY}))
    monkeypatch.setattr(W, "CACHE", cache)
    got = W.fetch("tiny_hat", offline=True)
    assert [u.name for u in got] == ["GatherAdd", "[HB] PollenBonus (Add) [Rose Field]", "Boost"]
    assert got[2].caustic_only and got[0].max == 20
    with pytest.raises(KeyError):
        W.fetch("no such hat", offline=True)


def test_offline_with_no_cache_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "CACHE", tmp_path / "none.json")
    with pytest.raises(RuntimeError, match="offline"):
        W.fetch("Lei", offline=True)


def test_a_stale_cache_is_used_when_the_wiki_cannot_be_reached(tmp_path, monkeypatch):
    # review 2026-10-22: a week-old table was thrown away and the fetch failed
    cache = tmp_path / "beequip_stats.json"
    cache.write_text(json.dumps({"at": 0, "revid": 1, "wikitext": TINY}))
    monkeypatch.setattr(W, "CACHE", cache)

    def down(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(W.urllib.request, "urlopen", down)
    assert [u.name for u in W.fetch("tiny_hat")][0] == "GatherAdd"


def test_swirled_wax_is_refused_until_its_reroll_is_modelled():
    pool = [W.Upgrade("A", 1.0)]
    table = {"soft": {"power": 1, "success": 1.0}, "swirled": {"power": 0, "success": 1.0}}
    with pytest.raises(ValueError, match="not modelled"):
        W.odds(pool, ["soft", "swirled"], "A", quality=1.0, table=table)

"""Measuring field degradation from ordinary play.

The tests that matter most are the ones about NOT concluding: an underpowered
study that reports "no effect" is as wrong as one that invents an effect, and
this module's whole justification is that it refuses to answer until it can.
"""
import random

import pytest

from hivemind.economy.degradation import MIN_FIELDS, Harvest, HarvestLog, analyse

HOUR = 3600.0


def make(field, recent, normalised_yield, growth=1.0, at=0.0):
    return Harvest(field=field, seed="Paper", growth=growth,
                   yield_honey=normalised_yield * growth, at=at,
                   recent_harvests=recent)


def test_no_verdict_below_the_sample_floor():
    few = [make("Sunflower", i % 4, 100_000 - i * 5_000) for i in range(6)]
    result = analyse(few)
    assert result.verdict == "not enough data"
    assert not result.decisive


def test_no_verdict_from_a_single_field():
    """One field could be confounded by anything; require breadth."""
    many = [make("Sunflower", i % 6, 100_000 - i * 3_000) for i in range(40)]
    assert analyse(many).verdict == "not enough data"
    assert analyse(many).fields < MIN_FIELDS


def test_detects_a_real_decline():
    rng = random.Random(7)
    data = []
    for field in ("Sunflower", "Pine Tree", "Rose"):
        for i in range(16):
            recent = i % 8
            # a genuine 8% drop per recent harvest, plus modest noise
            value = 100_000 * (1 - 0.08 * recent) + rng.gauss(0, 1_200)
            data.append(make(field, recent, value))
    result = analyse(data)
    assert result.verdict == "degrades"
    assert result.slope < 0
    assert result.t_statistic <= -2.5
    assert "degrades" in result.summary()


def test_reports_no_effect_when_yield_is_flat():
    rng = random.Random(11)
    data = []
    for field in ("Sunflower", "Pine Tree", "Rose"):
        for i in range(16):
            data.append(make(field, i % 8, 100_000 + rng.gauss(0, 1_200)))
    result = analyse(data)
    assert result.verdict == "no effect"
    assert result.decisive


def test_a_positive_slope_is_not_dressed_up_as_a_result():
    """Yield RISING with recent harvests contradicts the hypothesis."""
    rng = random.Random(3)
    data = []
    for field in ("Sunflower", "Pine Tree", "Rose"):
        for i in range(16):
            recent = i % 8
            data.append(make(field, recent,
                             100_000 * (1 + 0.08 * recent) + rng.gauss(0, 1_000)))
    assert analyse(data).verdict == "not enough data"


def test_normalisation_makes_partial_harvests_comparable():
    full = Harvest("F", "Paper", 1.0, 100_000, 0.0, 0)
    half = Harvest("F", "Paper", 0.5, 50_000, 0.0, 0)
    assert full.normalised == pytest.approx(half.normalised)


def test_no_variation_in_x_yields_no_verdict():
    """Every harvest at the same recent-count fits nothing."""
    data = [make(f, 3, 100_000) for f in ("A", "B") for _ in range(20)]
    assert analyse(data).verdict == "not enough data"


def test_zero_growth_records_are_ignored():
    data = [Harvest("A", "Paper", 0.0, 0.0, 0.0, 1) for _ in range(50)]
    assert analyse(data).samples == 0


# ---- the log -------------------------------------------------------------

def test_recent_harvest_count_uses_the_48h_window(tmp_path):
    log = HarvestLog(tmp_path / "h.jsonl")
    log.record("Pine Tree", "Paper", 1.0, 100_000, at=0.0)
    log.record("Pine Tree", "Paper", 1.0, 100_000, at=10 * HOUR)
    assert log.recent_harvests("Pine Tree", now=12 * HOUR) == 2
    # both fall outside a 48h window measured from much later
    assert log.recent_harvests("Pine Tree", now=100 * HOUR) == 0


def test_recent_count_is_per_field(tmp_path):
    log = HarvestLog(tmp_path / "h.jsonl")
    log.record("Pine Tree", "Paper", 1.0, 100_000, at=0.0)
    assert log.recent_harvests("Rose", now=1 * HOUR) == 0


def test_log_survives_a_restart(tmp_path):
    path = tmp_path / "h.jsonl"
    first = HarvestLog(path)
    first.record("Pine Tree", "Paper", 1.0, 100_000, at=0.0)
    assert len(HarvestLog(path)) == 1


def test_a_corrupt_line_does_not_lose_the_log(tmp_path):
    path = tmp_path / "h.jsonl"
    log = HarvestLog(path)
    log.record("Pine Tree", "Paper", 1.0, 100_000, at=0.0)
    with path.open("a") as handle:
        handle.write("{ this is not json\n")
    log.record("Rose", "Paper", 1.0, 90_000, at=1 * HOUR)
    assert len(HarvestLog(path)) == 2


# --- the two ways the regression used to reach the wrong verdict ------------

def test_a_perfect_linear_fit_is_the_strongest_evidence_not_the_weakest():
    """Zero residual with a real slope used to emit t = 0 -> "no effect".

    Yields are quantised game numbers, so a noiseless sample is not exotic --
    and this is the module that licenses early harvesting, so reporting a
    clean 5%-per-harvest loss as "no degradation" is the expensive direction.
    """
    harvests = [Harvest(field, "seed", 1.0, 100_000 - 5_000 * (i % 6),
                        i * 3600.0, i % 6)
                for field in ("Pineapple", "Dandelion") for i in range(12)]
    evidence = analyse(harvests)
    assert evidence.verdict == "degrades"
    assert evidence.slope == pytest.approx(-5_000.0)


def test_different_base_yields_do_not_manufacture_a_degrades_verdict():
    """The confound the pooled regression was measuring instead of degradation.

    Two fields an order of magnitude apart in base yield, harvested at
    different cadences, NEITHER degrading. Pooled, `recent_harvests` is really
    a proxy for which field the sample came from, and the fit reported
    "degrades" at t = -21.9.
    """
    rng = random.Random(1)
    harvests = (
        [Harvest("Pineapple", "seed", 1.0, 1_000_000 + rng.gauss(0, 5_000),
                 i * 3600.0, i % 2) for i in range(14)]
        + [Harvest("Dandelion", "seed", 1.0, 100_000 + rng.gauss(0, 5_000),
                   i * 3600.0, 4 + i % 2) for i in range(14)])
    evidence = analyse(harvests)
    assert evidence.verdict != "degrades", (
        f"between-field difference read as degradation: {evidence.summary()}")


def test_real_within_field_degradation_is_still_detected():
    """The fix must not make the test so conservative it can never conclude."""
    rng = random.Random(2)
    harvests = []
    for field, base in (("Pineapple", 1_000_000), ("Dandelion", 100_000)):
        for i in range(14):
            recent = i % 5
            harvests.append(Harvest(field, "seed", 1.0,
                                    base * (1 - 0.05 * recent)
                                    + rng.gauss(0, base * 0.01),
                                    i * 3600.0, recent))
    evidence = analyse(harvests)
    assert evidence.verdict == "degrades", evidence.summary()
    assert evidence.slope < 0


def test_a_field_with_one_harvest_contributes_no_false_precision():
    """Singletons de-mean to exactly (0, 0); they must not inflate the dof."""
    rng = random.Random(3)
    harvests = [Harvest("Pineapple", "seed", 1.0,
                        1_000_000 + rng.gauss(0, 5_000), i * 3600.0, i % 4)
                for i in range(26)]
    harvests.append(Harvest("Dandelion", "seed", 1.0, 50.0, 1.0, 9))
    evidence = analyse(harvests)
    # one real field plus a singleton is not two fields' worth of evidence
    assert evidence.verdict == "not enough data", evidence.summary()

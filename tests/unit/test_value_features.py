"""brain/value.feature_values (P11): each errand's time away against its pay."""
from hivemind.brain import value


def walk(target, seconds, outcome="landed"):
    return {"kind": "errand", "target": target, "outcome": outcome, "seconds": seconds}


def test_uses_come_from_trip_outcomes_not_payout_rows(tmp_path):
    # the payouts log starts later than the trips log (different spans) and
    # holds a row only when the HUD was read both sides: ONE row here, against
    # three landed walks -- uses must still be 3 of 4
    log = tmp_path / "payouts.jsonl"
    value.record_payout(log, "honey_dispenser", 25_400, 0.0)
    rows = [{"routes": [walk("honey_dispenser", 60), walk("wealth_clock", 40)]},
            {"routes": [walk("honey_dispenser", 80),
                        {"kind": "home", "target": "clover", "seconds": 99}]},
            {"routes": [walk("honey_dispenser", 100), walk("honey_dispenser", 80, "elsewhere")]},
            "junk", {}]
    by = {f.name: f for f in value.feature_values(rows, log, bees=26, rate=100.0)}
    hd = by["honey_dispenser"]
    assert (hd.walks, hd.uses, hd.seconds) == (4, 3, 80)
    assert hd.v == 25_400                      # formula: under MIN_PAYOUTS rows
    assert hd.net == 0.75 * 25_400 - 100.0 * 80
    clock = by["wealth_clock"]
    assert (clock.walks, clock.uses) == (1, 1) and clock.v == 500_000


def test_booster_with_small_hud_payout_stays_unpriced(tmp_path):
    log = tmp_path / "payouts.jsonl"
    for _ in range(3):                         # the walk's trickle, not its pay
        value.record_payout(log, "blue_field_booster", 2004, 0.0)
        value.record_payout(log, "blueberry_dispenser", 3000, 0.0)
    rows = [{"routes": [walk("blue_field_booster", 75), walk("blueberry_dispenser", 60),
                        walk("honey_dispenser", 300)]}]
    got = value.feature_values(rows, log, bees=26, rate=1e6)
    by = {f.name: f for f in got}
    for name in ("blue_field_booster", "blueberry_dispenser"):
        assert by[name].v is None and by[name].net is None
    assert [f.name for f in got][1:] == ["blue_field_booster", "blueberry_dispenser"]
    # a big minus on lower bounds both sides is printed, never called a loss
    assert by["honey_dispenser"].net < 0
    text = value.features_text(got, 1e6)
    assert "LOSES" not in text and "unpriced" in text and "not proof" in text


def test_nothing_measured(tmp_path):
    assert value.feature_values([], tmp_path / "none.jsonl", bees=10, rate=1.0) == []
    assert value.features_text([], 1.0) == "no errand walks measured"

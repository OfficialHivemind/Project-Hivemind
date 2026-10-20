"""R10 (nav.journey.HOME_FROM_FIX): a gather credited a neighbour last but its
aim this trip too walks home from the field the feed named LAST -- MEASURED
29 of 46 landed against the aim's 13 of 55 -- in odd hours ("ab"; even hours
keep run_farm's border rule, and HOME_UNSTICK / HOME_ALIGN). "on"/"off" pin it."""
from pathlib import Path

import hivemind
from hivemind.nav import journey


def test_switch_is_on_in_odd_hours_and_pins():
    old = journey.HOME_FROM_FIX
    try:
        journey.HOME_FROM_FIX = "ab"
        assert [journey.home_from_fix(h) for h in (0, 1, 2, 13, 22, 23)] == [
            False, True, False, True, False, True]
        journey.HOME_FROM_FIX = "on"
        assert journey.home_from_fix(0) and journey.home_from_fix(1)
        journey.HOME_FROM_FIX = "off"
        assert not journey.home_from_fix(0) and not journey.home_from_fix(1)
    finally:
        journey.HOME_FROM_FIX = old


def test_the_last_credited_field_keeps_its_own_route_home():
    # with the switch on, run_farm leaves home_from = credited, and route_home
    # walks that field's recorded route rather than the aim's planned one
    out = journey.route_home("mushroom", "sunflower", ["natro_home_mushroom"],
                             {"sunflower": ["natro_home_sunflower"]}.get)
    assert out.routes == ["natro_home_sunflower"] and not out.doubtful


def test_run_farm_gates_the_border_rule_on_the_switch():
    src = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text(
        encoding="utf-8")
    on = src.index("if border and home_from_fix():")
    rule = src.index("elif border:", on)
    assert "home_from = aimed" in src[rule:src.index("homeward = route_home(", rule)]
    assert "home_from = aimed" not in src[on:rule]


def test_an_off_field_or_teleported_walk_home_keeps_the_claim_sweep():
    # runs 1067/1087/1167: "began in None" skipped the sweep after an off-field gather
    src = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text(
        encoding="utf-8")
    clear = src.index("from_field = from_field and not off_field and not teleported")
    assert src.index("teleported = True") < clear < src.index("found = by_sight(sweep=not from_field)")

"""W5 (act/chase.STAND_STILL): no token chase while the gather's pattern stands
still. MEASURED runs 800-915: Stationary-pattern trips that chased ended with
the pollen counter flat off every field 13 of 28, those that did not 0 of 4
(corner snakes: 7 of 128 / 1 of 135). "on"; "ab" = odd hours; "off" = as before."""
from hivemind.act import chase
from hivemind.nav.router import Router

PAUSE = {"op": "pause", "seconds": 10.0}


def test_only_the_stationary_patterns_stand_still():
    router = Router(measurements=None)        # the real graph: paths + Natro's
    still = sorted(name for name, routine in router.routines.items()
                   if name.startswith("natro_pattern_")
                   and chase.stand_still(routine.steps, hour=0))
    assert still == ["natro_pattern_cactus_as_natro", "natro_pattern_clover_as_natro",
                     "natro_pattern_stump", "natro_pattern_stump_as_natro"]
    assert not chase.stand_still(router.routines["farm_snake"].steps, hour=0)


def test_unknown_or_moving_steps_do_not_stop_the_chase():
    assert not chase.stand_still(None, hour=0) and not chase.stand_still([], hour=0)
    assert not chase.stand_still([PAUSE, {"op": "key_down", "keys": "w"}], hour=0)
    assert chase.stand_still([PAUSE, {"op": "camera", "direction": "left"}], hour=0)


def test_switch_is_on_and_ab_takes_odd_hours():
    old = chase.STAND_STILL
    assert old == "on" and chase.stand_still([PAUSE], hour=0)
    try:
        chase.STAND_STILL = "ab"
        assert [chase.stand_still([PAUSE], hour=h) for h in (0, 1, 2, 13, 22, 23)] == [
            False, True, False, True, False, True]
        chase.STAND_STILL = "off"
        assert not chase.stand_still([PAUSE], hour=1)
    finally:
        chase.STAND_STILL = old

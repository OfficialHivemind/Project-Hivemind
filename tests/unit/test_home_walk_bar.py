"""A1 (ROADMAP A22): brain/decide.home_walk_bar shuts a field whose judged walk
home is under the floor while no Whirligig can rescue a miss."""
from hivemind.brain.decide import home_walk_bar


def test_blue_flower_5_of_10_without_whirligig_is_shut():
    why = home_walk_bar(5, 5, 0.50, 0)
    assert why and "no Whirligig" in why and "5 of its last 10" in why


def test_uncounted_whirligigs_count_as_none():
    assert home_walk_bar(5, 5, 0.50, None)


def test_a_whirligig_reopens_it():
    assert home_walk_bar(5, 5, 0.50, 1) is None


def test_unjudged_and_good_walks_stay_open():
    assert home_walk_bar(0, 0, 0.50, 0) is None      # the prior, not a record
    assert home_walk_bar(2, 2, 0.50, 0) is None      # too few verdicts
    assert home_walk_bar(4, 2, 0.62, 0) is None      # sunflower today: over the floor
    assert home_walk_bar(7, 3, 0.67, 0) is None


def test_a_micro_converter_rescues_a_miss_too():
    # 19 Oct 01:00-08:01 (run-1067): Pine Tree shut at 6 of 10 with no
    # Whirligig while 9 Micro-Converters were held; two of its misses that
    # night were rescued by one (00:36:43, 00:46:35) -- no rejoin
    assert home_walk_bar(6, 4, 0.58, 0, 9) is None
    assert home_walk_bar(6, 4, 0.58, None, None)          # neither counted: shut
    assert "Micro-Converter" in home_walk_bar(6, 4, 0.58, 0, 0)


def test_the_old_whirligig_only_bar_is_one_constant_away():
    from hivemind.brain import decide
    old = decide.HOME_BAR_COUNTS_MICRO
    try:
        decide.HOME_BAR_COUNTS_MICRO = False
        assert home_walk_bar(6, 4, 0.58, 0, 9)
    finally:
        decide.HOME_BAR_COUNTS_MICRO = old

"""Walking home from where the game says it is, not from where it aimed.

MEASURED 2026-09-22 04:48: a trip aimed at Sunflower, farmed DANDELION for
1,209 s over 91 passes, filled the backpack to 965,753 pollen, then walked
home along `natro_home_sunflower` from a field that was not Sunflower. It
arrived at the ticket shop, the box search could not close the gap, and the
trip banked +227 honey.
"""
from __future__ import annotations

from hivemind.nav.journey import route_home

HOME = {"dandelion": ["natro_home_dandelion"],
        "sunflower": ["natro_home_sunflower"],
        "rose_field": ["natro_home_rose_field"]}


def recorded(field):
    return HOME.get(field)


def test_the_feed_beats_the_aim_when_there_is_a_route():
    """The exact trip that cost a full backpack."""
    out = route_home("sunflower", "dandelion", ["natro_home_sunflower"],
                     recorded)

    assert out.routes == ["natro_home_dandelion"]
    assert not out.doubtful
    assert "dandelion" in out.why


def test_agreeing_with_the_aim_changes_nothing():
    out = route_home("dandelion", "dandelion", ["natro_home_dandelion"],
                     recorded)

    assert out.routes == ["natro_home_dandelion"]
    assert not out.doubtful


def test_a_guessed_walk_is_worse_than_the_wrong_recorded_one():
    """There is no route home from the pumpkin patch.

    The aim's route at least ends somewhere known, and the box search is the
    closer either way -- so it is walked, and the caller is told to doubt it
    rather than being left to assume it starts here.
    """
    out = route_home("sunflower", "pumpkin", ["natro_home_sunflower"],
                     recorded)

    assert out.routes == ["natro_home_sunflower"]
    assert out.doubtful, "the caller must know this route does not start here"
    assert "no recorded route home from pumpkin" in out.why


def test_no_credit_at_all_keeps_the_plan():
    """A field has no landmark prompt, so the feed is sometimes simply silent.

    That is not evidence the aim was wrong, so nothing changes.
    """
    out = route_home("sunflower", None, ["natro_home_sunflower"], recorded)

    assert out.routes == ["natro_home_sunflower"]
    assert not out.doubtful
    assert "never named a field" in out.why


def test_it_does_not_hand_back_the_list_it_was_given():
    """The caller's planned list is reused across cycles; mutating the
    returned list must not quietly rewrite the plan."""
    planned = ["natro_home_sunflower"]

    out = route_home("sunflower", None, planned, recorded)
    out.routes.append("something_else")

    assert planned == ["natro_home_sunflower"]


def test_a_credited_field_with_an_empty_recorded_route_is_not_a_route():
    """`recorded` returning [] means "nothing recorded", not "walk nothing"."""
    out = route_home("sunflower", "bamboo", ["natro_home_sunflower"],
                     lambda f: [])

    assert out.routes == ["natro_home_sunflower"]
    assert out.doubtful

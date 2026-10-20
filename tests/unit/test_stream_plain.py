"""The broadcast reads as English (stream/show.plain): lines the 2026-10-14
renders showed on the stream, as the bot wrote them and as viewers now see them."""
from __future__ import annotations

from hivemind.stream.show import Feed, plain, toast
from hivemind.telemetry.events import Log


def test_route_and_pattern_ids_become_places():
    assert plain("between two steps of natro_pattern_pine_tree_as_natro") == \
        "between two steps of the pine tree pattern"
    assert plain("natro_out_pine_tree_via_red_cannon landed") == "the walk to pine tree landed"
    assert plain("natro_home_bamboo missed") == "the walk home from bamboo missed"
    assert plain("to_the_blender leg 3") == "the walk to the blender leg 3"


def test_code_notes_go_numbers_stay():
    assert plain("the pass ends here (brain/farm FULL_MID_PASS)") == "the pass ends here"
    assert plain("the pass ends here ([hidden] FULL_MID_PASS)") == "the pass ends here"
    assert plain("a small target (vision/buffs HASTE_GAIN) now") == "a small target now"
    # a fraction and a percentage in brackets are the bot's own reading: kept
    assert plain("the bag read 5,023,825/5,045,625 (100%)") == "the bag read 5,023,825/5,045,625 (100%)"


def test_seconds_read_as_minutes_and_hours():
    assert plain("died here 27 times in 334084s") == "died here 27 times in 93 h"
    assert plain("(2745s of gathering)") == "(46 min of gathering)"
    assert plain("about 16s left") == "about 16s left"
    assert plain("+13/sec") == "+13/sec"


def test_the_feed_shows_it_and_chat_keeps_its_names():
    feed = Feed()
    item, new = feed.add(Log(message="the trip aimed at pine_tree", source="journey"))
    assert new and item.text == "the trip aimed at pine tree"
    assert toast("chat", "Chat's pick", "ExamplePlayer says go").body == "ExamplePlayer says go"
    assert toast("quest", "Quest step done", "natro_out_rose").body == "the walk to rose"


def test_diagnostic_asides_go_clock_times_stay():
    line = ("to hive: arrived — on our own hive pad (98% sure, panel, 0s ago) "
            "(pushed against something for 2s: the walk home from pine tree: w for 124 studs)")
    assert plain(line) == "to hive: arrived — on our own hive pad (98% sure, panel, 0s ago)"
    assert plain("the Wealth Clock (at 13:56) is next") == "the Wealth Clock (at 13:56) is next"


def test_an_aside_inside_an_aside():
    line = ("to hive: arrived — on our own hive pad (98% sure, panel, 0s ago) (pushed against something "
            "for 2s: glide: coasted 432 studs at base speed (move.home_glide_at_base); row search: ok)")
    assert plain(line) == "to hive: arrived — on our own hive pad (98% sure, panel, 0s ago)"
    assert plain("1.13 honey a pollen") == "1.13 honey a pollen"

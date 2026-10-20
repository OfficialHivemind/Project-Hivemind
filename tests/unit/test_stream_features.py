"""Each feature's result line gets its toast on the stream (stream/show.feature_toast),
the run logs' own words (var/night/run-9xx.log, 2026-10-13..14)."""
from __future__ import annotations

from hivemind.stream.show import feature_toast, highlight_of
from hivemind.telemetry.events import Log


def _t(text):
    t = feature_toast(text)
    return (t.kind, t.title, t.body) if t else None


def test_each_feature_line_has_its_toast():
    assert _t("Commando Chick: CAPTURED after 10.7 min of fighting (its HP 40,386 -> 1,910)") == \
        ("fight", "Commando Chick captured!", "after 10.7 min of fighting")
    assert _t("the Blender: collected the finished 10 Oil") == ("craft", "Blender crafted", "10 Oil")
    assert _t("planter: harvested the Paper Planter in the mushroom — its loot is round it") == \
        ("planter", "Harvested the Paper Planter", "in the mushroom field")
    assert _t("planter: the Blue Clay Planter in the stump — used one: answered Yes") == \
        ("planter", "Planted a Blue Clay Planter", "in the stump field")
    assert _t("buying gumdrops: bought it — '300 Gumdrops | 100 Tickets | Buy for 100 Tickets'") == \
        ("shop", "Bought it", "300 Gumdrops")
    assert _t("royal jelly: 6 rolled on the cell at (955, 243) — rolled the wanted Diamond Bee; "
              "it now holds the Diamond Bee") == \
        ("hive", "Royal Jelly: Diamond Bee!", "6 rolled — the one it wanted")
    assert _t("reward feed: a Werewolf was defeated in the pine tree") == ("fight", "Defeated a Werewolf", "")


def test_lines_that_are_not_results_stay_quiet():
    assert _t("the Blender: collected (frames in var/shoplook: 4)") is None
    assert _t("royal jelly: 0 rolled on the cell at None — no cell's card names the Rascal Bee") is None
    assert _t("buying 2: Plastic Planter at the Dapper Bear's Shop for 750,000 honey — buying it") is None


def test_the_stream_raises_them():
    t = highlight_of(Log(message="the Blender: collected the finished 10 Glue", source="blender"))
    assert t is not None and t.kind == "craft"

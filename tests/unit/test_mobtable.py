"""ROADMAP K7: the mob table (data/knowledge/mobs.yaml via brain/mobtable)."""
from __future__ import annotations

from pathlib import Path

import yaml

import hivemind
from hivemind.brain import mobtable

ROOT = Path(hivemind.__file__).resolve().parents[2]
SRC_KEYS = ("fields", "respawn_seconds", "hp", "drops", "danger", "night")


def _sourced(text) -> bool:
    t = str(text)
    return ("measured" in t or "[assumed:" in t
            or t.startswith(("none", "unknown")))


def test_every_mob_is_complete_and_every_value_sourced():
    table = mobtable.table()
    assert len(table) == 14
    for slug, row in table.items():
        for key in ("name", "kind", "fields", "respawn_seconds", "danger", "night",
                    "drops", "src"):
            assert key in row, (slug, key)
        assert row["danger"] in (0, 1, 2, 3), slug
        assert row["night"] in ("day", "night", "both"), slug
        if row["kind"] == "field_mob":     # HP and level per field, wiki table
            assert all("hp" in f and "levels" in f for f in row["fields"].values()), slug
        else:
            assert "hp" in row, slug
        for key in SRC_KEYS:
            assert _sourced(row["src"].get(key)), (slug, key)
        for key, text in row["src"].items():
            assert _sourced(text), (slug, key)
        if row["respawn_seconds"] is None:
            assert str(row["src"]["respawn_seconds"]).startswith("none"), slug


def test_bugrun_book_still_holds_only_the_six():
    from hivemind.act import bugrun
    book = bugrun.load(ROOT / "data/knowledge/mobs.yaml")
    assert sorted(book.mobs) == sorted(["ladybug", "rhino_beetle", "spider", "mantis",
                                        "scorpion", "werewolf"])


def test_the_api():
    assert mobtable.mob("mantis")["name"] == "Mantis"
    assert mobtable.mob("nope") is None
    assert mobtable.respawn("werewolf") == 3630.0
    assert mobtable.respawn("sprout") is None and mobtable.respawn("nope") is None
    assert mobtable.mobs_in("pine_tree") == ("mantis", "werewolf")
    assert mobtable.mobs_in("cactus") == ("werewolf",)            # also_defends
    assert mobtable.mobs_in("sunflower") == () and mobtable.danger("sunflower") == 0
    assert "ladybug" in mobtable.mobs_in("pine_tree", night=True)  # also_seen
    assert "rogue_vicious_bee" not in mobtable.mobs_in("clover")    # night only
    assert "rogue_vicious_bee" in mobtable.mobs_in("clover", night=True)
    assert mobtable.danger("clover") == 2 and mobtable.danger("clover", night=True) == 3
    assert mobtable.danger("dandelion") == 0 and mobtable.danger("dandelion", night=True) == 2
    assert mobtable.mobs_in("coconut") == ("coconut_crab",)


def test_wired_call_sites_keep_their_old_values():
    from hivemind.act import beetle, commando, crab, stumpsnail, tunnelbear
    from hivemind.brain import calendar
    assert calendar.RESPAWN_SECONDS == {"ladybug": 330, "rhino_beetle": 330, "mantis": 1230,
                                        "scorpion": 1230, "spider": 1830, "werewolf": 3630}
    # the wiki's figures stay in mobs.yaml as the prior; the calendar prices a
    # kill by the measured blend (tests/unit/test_killvalue.py)
    assert {m: mobtable.mob(m)["honey"] for m in calendar.MOB_HONEY} == {
        "ladybug": 75, "rhino_beetle": 75, "mantis": 250,
        "scorpion": 1000, "spider": 1000, "werewolf": 5000}
    assert {m: mobtable.mob(m)["ticket_chance"] for m in calendar.MOB_TICKET_CHANCE} == {
        "ladybug": 0.02, "rhino_beetle": 0.02, "mantis": 0.20, "scorpion": 0.133,
        "spider": 0.25, "werewolf": 0.50}
    assert calendar.MOB_HONEY == {m: mobtable.kill_honey(m)[0] for m in calendar.MOB_HONEY}
    assert calendar.MOB_TICKET_CHANCE == {m: mobtable.ticket_rate(m)[0]
                                          for m in calendar.MOB_TICKET_CHANCE}
    assert calendar.FIELD_MOBS == {
        "mushroom": ("ladybug",), "clover": ("ladybug", "rhino_beetle"),
        "strawberry": ("ladybug",), "blue_flower": ("rhino_beetle",),
        "bamboo": ("rhino_beetle",), "pineapple": ("rhino_beetle", "mantis"),
        "spider": ("spider",), "pine_tree": ("mantis", "werewolf"),
        "rose": ("scorpion",), "pumpkin": ("werewolf",), "cactus": ("werewolf",)}
    assert (beetle.COOLDOWN_S, tunnelbear.COOLDOWN_S, crab.COOLDOWN_S,
            commando.COOLDOWN_S, stumpsnail.COOLDOWN_S) == (
        86400.0, 172800.0, 129600.0, 1800.0, 345600.0)


def test_world_yaml_names_no_mob_the_table_does_not_place_there():
    world = yaml.safe_load((ROOT / "data/knowledge/world.yaml").read_text())
    for field, row in world["fields"].items():
        for m in row.get("mobs") or ():
            assert m in mobtable.mobs_in(field), (field, m)

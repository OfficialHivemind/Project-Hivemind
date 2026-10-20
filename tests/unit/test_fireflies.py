"""M8b: the fireflies' Moon Charms -- the ledger and the night nudge (act/fireflies)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

import hivemind
from hivemind.act import bugrun, fireflies

ROOT = Path(hivemind.__file__).resolve().parents[2]


class NoBook:
    def slug_for(self, name):
        return None


def test_the_feeds_firefly_lines_are_drops_of_their_own():
    # the lines as var/vlm_cache read them, 23-30 Sep 2026
    drops = bugrun.FeedDrops(NoBook(), clock=lambda: 0.0,
                             extras={"sprout": "sprout", **fireflies.SOURCES})
    got = drops.seen("+1 Moon Charm (from Fireflies)\n+2,982 Honey (from Sparkles)\n"
                     "+5 Moon Charms (from Fireflies)")
    assert got == [("fireflies", "moon charm", 1), ("fireflies", "moon charms", 5)]
    assert drops.seen("+1 Moon Charm (from Fireflies)") == []      # the same line read again


def test_the_ledger_and_when_it_pays(tmp_path):
    path = tmp_path / "fireflies.jsonl"
    assert fireflies.load(path) == [] and not fireflies.pays([])
    import json
    rows = [fireflies.row(1, "strawberry", 1.0), fireflies.row(5, None, 2.0),
            fireflies.row(0, "rose", 3.0)]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    got = fireflies.load(path)
    assert len(got) == 3 and not fireflies.pays(got)     # a charmless credit is not pay
    assert fireflies.pays(got + [fireflies.row(10, "bamboo", 4.0)])


def test_off_by_default():
    assert not fireflies.wanted(NS(bool=lambda k: (_ for _ in ()).throw(KeyError(k))))
    from hivemind.world.settings import defaults
    assert defaults()[fireflies.SETTING] is False


def test_a_goal_short_of_moon_charms():
    need = NS(material="moon_charm")
    assert fireflies.goal_wants(NS(rows=[NS(owned=False, missing=[need])]))
    assert not fireflies.goal_wants(NS(rows=[NS(owned=True, missing=[need])]))
    assert not fireflies.goal_wants(NS(rows=[NS(owned=False, missing=[NS(material="glue")])]))
    assert not fireflies.goal_wants(None)


def _alt(field, score, reachable=True):
    return NS(field=field, score=score, reachable=reachable)


def test_the_nudge_goes_to_the_best_firefly_field_that_is_close_enough():
    alts = [_alt("pine_tree", 100), _alt("bamboo", 70), _alt("rose", 80, reachable=False),
            _alt("spider", 50)]
    field, why = fireflies.nudge(alts, "pine_tree")
    assert field == "bamboo" and "70%" in why
    assert fireflies.nudge(alts, "bamboo") is None              # already there
    assert fireflies.nudge([_alt("pine_tree", 100), _alt("bamboo", 59)], "pine_tree") is None
    assert fireflies.nudge(alts, None) is None
    assert fireflies.nudge([_alt("bamboo", 70)], "pine_tree") is None   # its pick unranked


def test_the_fields_are_the_goals_yaml_ones():
    text = (ROOT / "data" / "knowledge" / "goals.yaml").read_text()
    assert "fireflies land in Rose, Cactus, Pineapple, Spider, Strawberry or Bamboo" in text
    world = (ROOT / "data" / "knowledge" / "world.yaml").read_text()
    assert all(f"\n  {f}:\n" in world for f in fireflies.FIELDS)

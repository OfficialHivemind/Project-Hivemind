"""questneeds.load_priority: only the Polar Bear's quests."""
import json

from hivemind.brain import questneeds as q


def test_only_the_priority_givers_quests_are_read(tmp_path):
    path = tmp_path / "quests.json"
    path.write_text(json.dumps({"quests": [
        {"name": "Polar Bear: Ladybug Poppers", "requirements": ["Defeat 30 Ladybugs. 24/30"]},
        {"name": "Eager Exterminator", "requirements": ["Defeat 5 Spiders. 4/5"]}]}))
    assert q.load_priority(path).mobs_wanted() == {"ladybug": 6}
    assert q.load_priority(tmp_path / "missing.json").mobs_wanted() == {}

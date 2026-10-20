"""A quest handed in to "Gifted Bucko Bee" is the `bucko_bee` route's (brain/questneeds
GIVER_ALIASES). The lines are the whole-list read of 2026-09-30 23:39 onwards."""
from __future__ import annotations

import json

from hivemind.brain import questneeds

SCAVENGE = ("Bucko Bee: Scavenge\n"
            "Collect 5,000,000 Blue Pollen. Complete! Talk to Gifted Bucko Bee.\n"
            "Collect 505 Blue Ability Tokens. Complete! Talk to Gifted Bucko Bee.\n"
            "Collect 25 Blueberry Tokens. Complete! Talk to Gifted Bucko Bee.\n")


def _load(tmp_path, data):
    path = tmp_path / "quests.json"
    path.write_text(json.dumps(data))
    return questneeds.load(path)


def test_the_gifted_name_hands_in_at_the_route_it_names():
    needs = _load(tmp_path=__import__("pathlib").Path(__import__("tempfile").mkdtemp()),
                  data={"read_at": 1.0, "transcript": SCAVENGE, "transcripts": [SCAVENGE]})
    assert needs.ready_to_hand_in == ("bucko_bee",)


def test_a_file_that_kept_the_gifted_name_is_read_under_the_route(tmp_path):
    needs = _load(tmp_path, {
        "read_at": 2.0, "transcript": SCAVENGE, "transcripts": [SCAVENGE],
        "ready_since": {"gifted_bucko_bee": {"quest": "Bucko Bee: Scavenge", "at": 100.0},
                        "bucko_bee": {"quest": "Bucko Bee: Scavenge", "at": 900.0}}})
    assert needs.ready_to_hand_in == ("bucko_bee",)
    assert needs.ready_since["bucko_bee"]["at"] == 100.0
    assert "gifted_bucko_bee" not in needs.ready_since


def test_riley_too_and_other_names_unchanged():
    assert questneeds.GIVER_ALIASES["gifted_riley_bee"] == "riley_bee"
    assert questneeds._giver_of("Defeat 15 Ants. Complete! Talk to Panda Bear.") == "panda_bear"
    assert questneeds._giver_of("Collect 2 Things. Complete! Talk to Gifted Riley Bee.") == "riley_bee"

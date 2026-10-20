"""Q8 step 2: an owed bloom-petal colour tilts the field choice toward the
fields its blooms spawn in (data/knowledge/blooms.yaml)."""
from hivemind.brain import questneeds
from hivemind.brain.decide import BLOOM_FIELD_VALUE, Planner
from hivemind.brain.fieldnotes import FieldNotes

FIELDS = {n: {"flowers": 700, "safe": True, "bees_required": 0}
          for n in ("strawberry", "pine_tree", "spider", "clover")}


def _planner(lines):
    return Planner(FIELDS, FieldNotes(), quest_needs=questneeds.from_lines(lines))


def test_pink_petals_tilt_strawberry_only():
    p = _planner(["Catch 10 Pink Bloom Petals.", "2/10"])
    value, why = p._quest_value("strawberry")
    assert value == BLOOM_FIELD_VALUE and "8 more pink bloom petals" in why
    assert p._quest_value("pine_tree")[0] == 0.0


def test_a_named_field_counts_in_full():
    p = _planner(["Catch 10 Red Bloom Petals in the Spider Field. 0/10"])
    assert p._quest_value("spider")[0] == 1.0
    assert p._quest_value("clover")[0] == 0.0     # the step names spider only


def test_finished_bloom_step_tilts_nothing():
    p = _planner(["Catch 50 Green Bloom Petals. Complete!"])
    assert p._quest_value("clover")[0] == 0.0

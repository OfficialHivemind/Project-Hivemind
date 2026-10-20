"""Bloom Petals quest steps are read, not dropped as unread (look-only)."""
from hivemind.brain import questneeds


def test_polar_bear_pink_blooms_with_progress():
    n = questneeds.from_lines(["Catch 10 Pink Bloom Petals.", "2/10"])
    assert [(b.colour, b.target, b.done, b.field) for b in n.blooms] == [("pink", 10, 2, "")]
    assert n.blooms[0].remaining == 8 and not n.unread


def test_finished_bloom_step_is_not_owed():
    n = questneeds.from_lines(["Catch 50 Green Bloom Petals. Complete!"])
    assert n.blooms == [] and not n.unread


def test_bloom_step_naming_a_field():
    n = questneeds.from_lines(["Catch 10 Red Bloom Petals in the Spider Field. 0/10"])
    b = n.blooms[0]
    assert (b.colour, b.target, b.field) == ("red", 10, "spider")
    assert "in spider" in b.describe()


def test_merge_keeps_the_furthest_and_describe_says_it():
    a = questneeds.from_lines(["Catch 10 Pink Bloom Petals.", "0/10"])
    b = questneeds.from_lines(["Catch 10 Pink Bloom Petals.", "2/10"])
    assert [x.done for x in a.merged_with(b).blooms] == [2]
    assert "8 more pink bloom petal(s)" in b.describe()

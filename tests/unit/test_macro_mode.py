"""Macro mode's field choice (brain/macro, ROADMAP U16): the user's list, in
order, rotating; AI mode untouched. No game, no run_farm."""
from hivemind.brain import macro
from hivemind.brain.decide import from_settings
from hivemind.world.settings import MACRO_ENTRY


class Fake:
    def __init__(self, **values):
        self.values = values

    def get(self, key, fallback=None):
        return self.values.get(key, fallback)

    def bool(self, key):
        return bool(self.values.get(key))


LIST = [{"field": "Pine Tree", "minutes": 15, "pattern": "farm_snake"},
        {"field": "Rose", "minutes": 0},
        {"field": "Blue Flower", "sprinklers": 3}]


def rotate(entries, trips, usable=lambda field: True):
    """The fields `trips` trips go to, the way run_farm's `macro_choice`
    carries the next index from trip to trip."""
    went, start = [], 0
    for _ in range(trips):
        got = macro.pick(entries, start, usable)
        if got is None:
            went.append(None)
            continue
        index, entry = got
        went.append(entry["field"])
        start = index + 1
    return went


def test_ai_mode_is_an_empty_list():
    """[] is what leaves run_farm's plan exactly as it was."""
    assert macro.active(Fake()) == []
    assert macro.active(Fake(**{"mode.macro": False, "macro.fields": LIST})) == []
    assert macro.active(Fake(**{"mode.macro": True, "macro.fields": []})) == []
    assert macro.active(Fake(**{"mode.macro": True, "macro.fields": "junk"})) == []


def test_macro_mode_gives_the_checked_list():
    got = macro.active(Fake(**{"mode.macro": True, "macro.fields": LIST}))
    assert [e["field"] for e in got] == ["Pine Tree", "Rose", "Blue Flower"]
    assert got[1] == {"field": "Rose", **MACRO_ENTRY, "minutes": 0}


def test_the_trips_follow_the_list_and_rotate():
    entries = macro.active(Fake(**{"mode.macro": True, "macro.fields": LIST}))
    assert rotate(entries, 7) == ["Pine Tree", "Rose", "Blue Flower",
                                  "Pine Tree", "Rose", "Blue Flower", "Pine Tree"]


def test_a_guarded_field_is_passed_to_the_next():
    entries = macro.active(Fake(**{"mode.macro": True, "macro.fields": LIST}))
    assert rotate(entries, 4, usable=lambda f: f != "rose") == [
        "Pine Tree", "Blue Flower", "Pine Tree", "Blue Flower"]
    assert macro.pick(entries, 0, lambda f: False) is None    # none: the AI picks


def test_the_slug_is_the_planners_field_name():
    assert macro.slug("Pine Tree") == "pine_tree" and macro.slug("Blue Flower") == "blue_flower"


def test_the_log_line_says_which_mode_chose():
    entries = macro.active(Fake(**{"mode.macro": True, "macro.fields": LIST}))
    assert macro.describe(0, 3, entries[0]) == (
        "macro: field 1 of 3, Pine Tree, 15 min, pattern Snake, wide (232 studs)")
    assert macro.describe(1, 3, entries[1]) == (
        # 95%: MACRO_ENTRY's convert_at since the pro tester's round 1 (19 Oct 2026)
        "macro: field 2 of 3, Rose, until the bag is 95% full, pattern The field's own")


def test_ai_modes_own_choice_is_unchanged_by_the_macro_settings():
    """THE AI PATH, PINNED: brain/decide.from_settings decides the AI's pin and
    threshold from gather.* alone, whatever mode.macro and macro.fields say."""
    base = {"gather.auto_field": False, "gather.field": "Pine Tree",
            "gather.convert_at": 80, "quests.first": False}
    for extra in ({}, {"mode.macro": True, "macro.fields": LIST}):
        planner, forced = from_settings(Fake(**base, **extra), {}, reachable={"pine_tree"})
        assert forced == "pine_tree" and planner.convert_at == 0.8

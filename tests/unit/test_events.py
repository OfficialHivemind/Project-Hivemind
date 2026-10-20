"""The event protocol.

The registration test earns its place: the type table was a hand-written tuple
and it drifted the same day six new event types were added, so `from_json`
returned None for all of them and the GUI silently dropped a third of the
protocol. Registration is now automatic, and this makes sure it stays that way.
"""
import pytest

from hivemind.telemetry import events as E
from hivemind.telemetry.events import Event, Option, from_json


def _event_classes():
    return [c for c in vars(E).values()
            if isinstance(c, type) and issubclass(c, Event) and c is not Event]


@pytest.mark.parametrize("cls", _event_classes(), ids=lambda c: c.__name__)
def test_every_event_class_is_registered_and_roundtrips(cls):
    original = cls()
    restored = from_json(original.to_json())
    assert restored is not None, f"{cls.__name__} is not in the type table"
    assert restored.kind == original.kind


def test_kinds_are_unique():
    kinds = [c.kind for c in _event_classes()]
    assert len(kinds) == len(set(kinds)), "two event classes share a kind"


def test_nested_options_survive_a_roundtrip():
    original = E.Considered(question="q", chosen="a",
                            options=[Option("a", 2.0, "why", "honey/hr"),
                                     Option("b", 1.0)])
    restored = from_json(original.to_json())
    assert [o.label for o in restored.options] == ["a", "b"]
    assert restored.options[0].unit == "honey/hr"


@pytest.mark.parametrize("line", ["", "not json", "[]", '{"kind":"nope"}',
                                  '{"no_kind":1}'])
def test_bad_lines_return_none_rather_than_raising(line):
    """A malformed line on a telemetry socket must never take down the GUI."""
    assert from_json(line) is None


def test_a_field_this_build_has_never_heard_of_keeps_the_EVENT():
    """CHANGED DELIBERATELY, and this used to assert None.

    An unknown key raised TypeError and the whole event was binned. The bot
    and the GUI are separate processes and only one of them restarts when the
    code changes, so the moment the bot gained a field the GUI lacked, every
    event of that type vanished on the way in -- silently, because None is
    also what a corrupt line returns. It happened for real on 2026-09-21:
    `QuestStep` gained `complete` and the already-running GUI dropped every
    quest the bot read, which looks exactly like the quest reader being broken.

    A field nobody has a home for is dropped; the event is not.
    """
    got = from_json('{"kind":"thought","text":"hello","bogus":1}')
    assert isinstance(got, E.Thought)
    assert got.text == "hello"
    assert "bogus" in E.unknown_fields()


def test_a_missing_field_still_falls_back_to_its_default():
    """The other direction: an older bot talking to a newer GUI."""
    got = from_json('{"kind":"quest","step":"Collect 10 Bees"}')
    assert got.step == "Collect 10 Bees" and got.complete is False


def test_autonomy_survives_a_roundtrip():
    restored = from_json(E.StatusUpdate(autonomy=E.Autonomy.ASK_NOTABLE).to_json())
    assert restored.autonomy == E.Autonomy.ASK_NOTABLE

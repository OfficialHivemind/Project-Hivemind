"""The Expiry Sentinel.

The rule this exists to enforce: an UNVERIFIED deadline may warn you and may ask
you, but it may never authorise the bot to consume something on its own. Warning
someone about a possible loss costs nothing if the timing is off by an hour;
consuming a resource on a guessed deadline does not have that property.
"""
import pytest

from hivemind.economy.sentinel import ExpiryKind, Sentinel, Tracked, load_kinds

HOUR = 3600.0


def kind(verified=True, duration=HOUR, lead=600.0):
    return ExpiryKind(id="thing", what="Thing", detail="d",
                      duration_s=duration, verified=verified, lead_s=lead)


def test_loads_the_shipped_file():
    kinds = load_kinds()
    assert "beequip_inbox" in kinds
    assert kinds["beequip_inbox"].duration_s == 172800


def test_every_shipped_duration_is_marked():
    for k in load_kinds().values():
        assert isinstance(k.verified, bool)


def test_nothing_shipped_is_verified_yet():
    """If one of these flips, it must be because it was measured."""
    assert not any(k.verified for k in load_kinds().values())


def test_remaining_counts_down():
    t = Tracked(kind=kind(), started_at=0.0)
    assert t.remaining(now=0.0) == pytest.approx(HOUR)
    assert t.remaining(now=HOUR) == pytest.approx(0.0)
    assert t.lapsed(now=HOUR + 1)


def test_due_only_inside_the_lead_window():
    t = Tracked(kind=kind(lead=600.0), started_at=0.0)
    assert not t.due(now=HOUR - 900)
    assert t.due(now=HOUR - 300)


def test_verified_and_due_is_actionable():
    t = Tracked(kind=kind(verified=True), started_at=0.0)
    assert t.actionable(now=HOUR - 60) is True


def test_unverified_is_never_actionable_however_urgent():
    """The core safety rule."""
    t = Tracked(kind=kind(verified=False), started_at=0.0)
    assert t.due(now=HOUR - 60) is True          # still worth showing
    assert t.actionable(now=HOUR - 60) is False  # but never acted on alone
    assert t.actionable(now=HOUR + 9999) is False


def test_unverified_items_are_described_with_a_hedge():
    t = Tracked(kind=kind(verified=False), started_at=0.0)
    assert "not sure" in t.describe(now=0.0)        # plain words (UI panel 2026-10-22)
    verified = Tracked(kind=kind(verified=True), started_at=0.0)
    assert "not sure" not in verified.describe(now=0.0)


def test_sentinel_separates_acting_from_asking():
    s = Sentinel()
    s.kinds["sure"] = ExpiryKind(id="sure", what="Sure", detail="",
                                 duration_s=HOUR, verified=True, lead_s=600)
    s.kinds["unsure"] = ExpiryKind(id="unsure", what="Unsure", detail="",
                                   duration_s=HOUR, verified=False, lead_s=600)
    s.start("sure", at=0.0)
    s.start("unsure", at=0.0)
    now = HOUR - 60
    assert [t.kind.id for t in s.actionable(now)] == ["sure"]
    assert [t.kind.id for t in s.needs_asking(now)] == ["unsure"]
    assert len(s.due(now)) == 2


def test_unknown_kind_returns_none_rather_than_raising():
    assert Sentinel().start("no_such_thing") is None


def test_instances_are_tracked_separately():
    s = Sentinel()
    s.start("field_booster", at=0.0, instance="Pepper")
    s.start("field_booster", at=0.0, instance="Rose")
    assert len(s) == 2
    s.clear("field_booster:Pepper")
    assert len(s) == 1


def test_due_items_are_sorted_soonest_first():
    s = Sentinel()
    s.start("beequip_inbox", at=0.0)      # 48h
    s.start("wealth_clock", at=0.0)       # 1h
    assert s.all()[0].kind.id == "wealth_clock"


def test_at_risk_value_sums_only_what_is_due():
    s = Sentinel()
    s.start("wealth_clock", at=0.0, value=85_000)
    s.start("beequip_inbox", at=0.0, value=11_400_000)
    assert s.at_risk_value(now=HOUR - 60) == pytest.approx(85_000)


def test_a_malformed_row_does_not_lose_the_file(tmp_path):
    path = tmp_path / "e.yaml"
    path.write_text(
        "expiries:\n"
        "  - {id: good, what: Good, duration_s: 60, verified: true}\n"
        "  - {id: bad, what: Bad}\n")
    kinds = load_kinds(path)
    assert "good" in kinds and "bad" not in kinds


def test_missing_file_gives_no_kinds(tmp_path):
    assert load_kinds(tmp_path / "nope.yaml") == {}

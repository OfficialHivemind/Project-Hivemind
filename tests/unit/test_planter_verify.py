"""A planter is booked out only when seen (act/planter: unverified,
placement_seen, reconcile). The cases are the measured ones of 2026-10-12:
the Paper in Stump 22:23:42 (92 -> 91, its prompt read 2 s later), the Ticket
in Bamboo 22:24:53 (still 1 at the 23:25 read), the Blue Clay in Pine Tree
16:43:18 (still 1/1 at 20:00)."""
from pathlib import Path
from hivemind.act import planter as P

T0 = 1_000_000.0


def test_its_own_prompt_is_the_proof():
    assert P.placement_seen("E | Harvest the Paper | Planter (It's still growing)")
    assert P.placement_seen("harves n ïr tizirue clay")
    assert not P.placement_seen("")
    assert not P.placement_seen("fire the red cannon")


def test_unseen_is_held_and_retried_not_out():
    st = P.unverified({}, "ticket_planter", "bamboo", T0, held=1)
    assert "ticket_planter" not in (st.get("out") or {})
    assert st["failed"]["ticket_planter"] == T0
    assert st["pending"]["ticket_planter"] == {"field": "bamboo", "at": T0, "held": 1}


def test_single_use_out_still_counted_goes_back():
    # the Ticket booked out with 1 held; the read after still counts 1
    st = P.placed({}, "ticket_planter", "bamboo", T0, held=1)
    st = P.placed(st, "paper_planter", "stump", T0, held=92)
    got = P.reconcile(st, {"ticket_planter": 1, "paper_planter": 91}, T0 + 3600)
    assert "ticket_planter" not in got["out"]
    assert got["out"]["paper_planter"]["field"] == "stump"      # 92 -> 91: it went


def test_single_use_without_its_count_is_left_alone():
    st = P.placed({}, "paper_planter", "stump", T0)
    assert P.reconcile(st, {"paper_planter": 91}, T0 + 3600) == st


def test_read_before_the_placing_settles_nothing():
    st = P.placed({}, "ticket_planter", "bamboo", T0, held=1)
    assert P.reconcile(st, {"ticket_planter": 1}, T0 - 1) == st
    st = P.unverified({}, "blue_clay_planter", "pine_tree", T0, held=1)
    assert P.reconcile(st, {}, T0 - 1) == st


def test_reusable_still_counted_goes_back_as_before():
    st = P.placed({}, "blue_clay_planter", "pine_tree", T0)
    assert "blue_clay_planter" not in P.reconcile(st, {"blue_clay_planter": 1}, T0 + 1)["out"]


def test_pending_still_in_bag_is_dropped():
    st = P.unverified({}, "blue_clay_planter", "pine_tree", T0, held=1)
    got = P.reconcile(st, {"blue_clay_planter": 1}, T0 + 3600)
    assert not got["pending"] and not got.get("out")
    assert got["failed"]["blue_clay_planter"] == T0           # still a failed try


def test_pending_gone_from_bag_is_booked_out_after_all():
    st = P.unverified({}, "blue_clay_planter", "pine_tree", T0, held=1)
    got = P.reconcile(st, {}, T0 + 3600)                       # no row: it is out
    assert got["out"]["blue_clay_planter"]["field"] == "pine_tree"
    assert got["out"]["blue_clay_planter"]["at"] == T0
    assert not got["pending"] and not got["failed"] and not got["fails"]

    st = P.unverified({}, "paper_planter", "stump", T0, held=92)
    got = P.reconcile(st, {"paper_planter": 91}, T0 + 3600)
    assert got["out"]["paper_planter"]["held"] == 92
    got = P.reconcile(st, {"paper_planter": 92}, T0 + 3600)
    assert "paper_planter" not in (got.get("out") or {}) and not got["pending"]


def test_a_seen_placing_clears_its_pending():
    st = P.unverified({}, "ticket_planter", "bamboo", T0, held=1)
    st = P.placed(st, "ticket_planter", "dandelion", T0 + 3600, held=1)
    assert not st["pending"] and st["out"]["ticket_planter"]["field"] == "dandelion"


def test_lost_single_use_without_its_count_comes_back_while_some_are_held():
    # the live 22:24 Ticket: booked out with no count, three missed harvests
    st = P.placed({}, "ticket_planter", "bamboo", T0)
    for i in range(P.MISSES_TO_GIVE_UP):
        st = P.missed(st, "ticket_planter", T0 + 7200 + i)
    assert "ticket_planter" in st["lost"]
    assert "ticket_planter" not in P.reconcile(st, {"ticket_planter": 1}, T0 + 9000)["lost"]
    assert "ticket_planter" in P.reconcile(st, {}, T0 + 9000)["lost"]


def test_a_planters_own_bar_names_it():
    # 2026-10-13 00:39:52: the camera faced a wall, the bar read this
    from hivemind.act import planter
    assert planter.banner_names("Blue Clay Planter (0.0%)", "Blue Clay Planter")
    assert not planter.banner_names("Blue Clay Planter (0.0%)", "Paper Planter")
    assert not planter.banner_names("", "Paper Planter")


def test_the_ticket_planters_name_is_not_a_ticket_veto():
    # run_farm tend_the_planter: only the name "ticket planter" is exempt
    import re
    from hivemind.act.bearvisit import never_press_word
    veto = lambda said: never_press_word(re.sub(r"(?i)ticket\s+planter", "planter", said))
    assert veto("E Harvest the Ticket Planter") == ""
    assert veto("E Spend 10 Tickets") == "spend"
    assert veto("Harvest the Ticket Planter for 5 tickets") == "ticket"


def test_planter_bar_bands_on_real_frames():
    # 2026-10-13: two real placings (bar at two heights) and one refused one
    import os
    import pytest
    cv2 = pytest.importorskip("cv2")
    from hivemind.act import planter, shoplook
    base = str(Path.home() / "Hivemind/var/planters") + "/"
    cases = [("place-20261013-014712-unseen.jpg", "Ticket Planter", True),
             ("place-20261013-003952-unseen.jpg", "Blue Clay Planter", True),
             ("place-20261013-004056-unseen.jpg", "Ticket Planter", False)]
    if not all(os.path.exists(base + f) for f, _l, _w in cases):
        pytest.skip("the saved placing frames have rotated out")
    for f, label, want in cases:
        frame = cv2.imread(base + f)
        got = any(planter.banner_names(shoplook.white_banner_text(frame, box=b), label)
                  for b in shoplook.PLANTER_BANNER_BANDS)
        assert got is want, f


def test_ticket_planter_name_read_loosely_never_a_price():
    """05:41:02 2026-10-13 read 'Ticket Diantar'; a price must still veto."""
    for read in ("n Harvest the Ticket Diantar", "E Harvest the Ticket Planter"):
        assert P.TICKET_PLANTER.search(read)
    for read in ("Spend 1 Ticket", "Buy Ticket Eggs", "Ticket"):
        assert not P.TICKET_PLANTER.search(read)


def test_a_lost_planter_booked_with_a_misread_count_comes_back():
    # the live Paper (var/planters.json, 2026-10-21): lost since ~14 Oct with
    # held 72100 while the bag held 64, so it never came back
    st = {"lost": {"paper_planter": {"field": "pine_tree", "at": T0, "misses": 3,
                                     "grow": 3600.0, "held": 72100, "lost_at": T0 + 10}}}
    assert "paper_planter" not in P.reconcile(st, {"paper_planter": 64}, T0 + 9000)["lost"]
    assert "paper_planter" in P.reconcile(st, {}, T0 + 9000)["lost"]       # none in the bag: still lost
    ok = {"lost": {"paper_planter": dict(st["lost"]["paper_planter"], held=92)}}
    assert "paper_planter" in P.reconcile(ok, {"paper_planter": 64}, T0 + 9000)["lost"]   # a real count holds

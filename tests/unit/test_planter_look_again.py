"""A planter written off as lost is looked at again after LOOK_AGAIN_S
(act/planter.look_again): one more harvest try, then lost again if missed."""
from hivemind.act import planter as p

H = 3600.0


def _lost(field="pepper", lost_at=0.0):
    return {"field": field, "misses": p.MISSES_TO_GIVE_UP, "at": lost_at - 10 * H,
            "lost_at": lost_at, "held": 1}


def test_a_lost_planter_goes_out_again_after_the_wait_with_one_try():
    state = {"out": {}, "lost": {"blue_clay_planter": _lost(lost_at=0.0)}}
    same, moved = p.look_again(state, p.LOOK_AGAIN_S - 1)
    assert moved == [] and same is state                    # too soon: unchanged
    out, moved = p.look_again(state, p.LOOK_AGAIN_S)
    assert moved == ["blue_clay_planter"] and "blue_clay_planter" not in out["lost"]
    body = out["out"]["blue_clay_planter"]
    assert body["field"] == "pepper" and body["misses"] == p.MISSES_TO_GIVE_UP - 1
    assert "lost_at" not in body and body["looked_again_at"] == p.LOOK_AGAIN_S
    # missed once more: written off again, and the wait starts over
    again = p.missed(out, "blue_clay_planter", p.LOOK_AGAIN_S + H)
    assert "blue_clay_planter" in again["lost"] and "blue_clay_planter" not in again["out"]
    assert p.look_again(again, p.LOOK_AGAIN_S + 2 * H)[1] == []


def test_found_again_it_is_harvested_and_frees_the_slot():
    out, _ = p.look_again({"lost": {"paper_planter": _lost("pine_tree")}}, p.LOOK_AGAIN_S)
    done = p.harvested(out, "paper_planter", p.LOOK_AGAIN_S + 60)
    assert "paper_planter" not in (done.get("out") or {})
    assert "paper_planter" not in (done.get("lost") or {})


def test_rows_without_a_field_or_unknown_kinds_stay_lost():
    state = {"lost": {"blue_clay_planter": {"misses": 3, "lost_at": 0.0},
                      "no_such_planter": _lost()}}
    assert p.look_again(state, 10 * p.LOOK_AGAIN_S)[1] == []

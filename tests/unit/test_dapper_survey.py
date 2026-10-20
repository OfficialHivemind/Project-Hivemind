"""The way up to Dapper Bear's planter counter (run_farm DAPPER_SHOP_*, 2026-10-12):
natro_out_stump to its turn north in the Stump Field, then Natro's own climb
from gtc-samovar.ahk (the Samovar stands next to the shop's door), then along
the shop's front -- and the purchase walks the survey's way, no other.

run_farm.py is a script, so its constants are read from the source found
beside the imported `hivemind` package (the tree on PYTHONPATH)."""
from __future__ import annotations

import ast
import pathlib

import hivemind
from hivemind.nav.router import Router

RUN_FARM = pathlib.Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"
TREE = ast.parse(RUN_FARM.read_text())


def _consts(*names) -> dict:
    """The module-level assignments of `names`, run in file order."""
    ns: dict = {}
    for node in TREE.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in names for t in node.targets):
            exec(compile(ast.Module([node], []), str(RUN_FARM), "exec"), ns)
    return ns


C = _consts("DAPPER_JUMP", "DAPPER_SHOP_LEGS", "DAPPER_CLIMB_LEGS", "DAPPER_SHOP_UPTO",
             "DAPPER_SHOP_VIA")
EDGES = {e.name: e for e in Router().edges}


def _flat(legs):
    return [dict(s) for leg in legs for s in (leg if isinstance(leg, tuple) else (leg,))]


def _merged(steps):
    """Back-to-back walks on the same keys as one (a walk cut into legs)."""
    out: list = []
    for s in steps:
        s = dict(s)
        if out and s.get("op") == "walk" == out[-1].get("op") and s["keys"] == out[-1]["keys"]:
            out[-1] = dict(out[-1], studs=out[-1]["studs"] + s["studs"])
        else:
            out.append(s)
    return out


def _turns(steps) -> int:
    return sum({"right": 1, "left": -1}.get(s.get("direction"), 0)
               for s in steps if s.get("op") == "camera")


def _climb_start(steps) -> int:
    """gtc-samovar's nm_Walk(27, FwdKey): the walk a jump follows."""
    return next(i for i, s in enumerate(steps)
                if s.get("op") == "walk" and steps[i + 1].get("op") == "jump_hold")


def test_the_climb_is_natros_own():
    legs = C["DAPPER_SHOP_LEGS"]
    last_jump = max(i for i, leg in enumerate(legs)
                    if isinstance(leg, tuple) and {"op": "jump_hold"} in leg)
    samovar = EDGES["natro_out_samovar"].steps
    natro = samovar[_climb_start(samovar):]
    assert _merged(_flat(legs[:last_jump + 1])) == _merged(natro)
    # each jump is one leg with the walks Natro runs after it, ending only where
    # his next jump starts (or his path ends): no read with the character in the air
    jumps = [leg for leg in legs if isinstance(leg, tuple)]
    assert [leg[:3] for leg in jumps] == [C["DAPPER_JUMP"]] * 3
    assert [leg[-1]["keys"] for leg in jumps] == ["wa", "w", "w"]


def test_the_survey_starts_where_natros_walk_turns_north():
    stump = EDGES[C["DAPPER_SHOP_VIA"]].steps
    upto = C["DAPPER_SHOP_UPTO"]
    assert stump[upto] == {"op": "walk", "keys": "d", "studs": 96.0}
    samovar = EDGES["natro_out_samovar"].steps
    # both facing north: four taps right of the spawn heading (south)
    assert _turns(stump[:upto + 1]) == _turns(samovar[:_climb_start(samovar)]) == 4


def test_the_purchase_walks_the_surveys_way():
    calls = [n for n in ast.walk(TREE) if isinstance(n, ast.Call)
             and any(isinstance(a, ast.Name) and a.id == "DAPPER_SHOP_SURVEY"
                     for a in list(n.args) + [k.value for k in n.keywords])]
    names = {getattr(n.func, "id", None): {a.id for a in ast.walk(n) if isinstance(a, ast.Name)}
             for n in calls}
    assert {"survey_by_walk", "buy_at_a_surveyed_counter", "plan_buy_due"} <= set(names)
    assert "DAPPER_SHOP_LEGS" in names["plan_buy_due"]        # its "Open Shop" cut
    for fn in ("survey_by_walk", "buy_at_a_surveyed_counter"):
        used = names[fn]
        assert {"DAPPER_SHOP_VIA", "DAPPER_SHOP_UPTO", "DAPPER_SHOP_LEGS"} <= used, fn
        assert not {"DAPPER_VIA", "DAPPER_UPTO"} & used, fn

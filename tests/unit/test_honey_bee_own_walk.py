"""The Honey Bee is walked to by her own route, not the Sticker Stack's.

MEASURED 2026-10-13 (run_farm GIVER_ROUTE_OVERRIDE): the stack's walk stood on
her pad at leg 34 and then climbed away from her; natro_out_honey_bee is that
same walk to leg 34 and then s34, where her prompt read on 2026-10-09 13:28."""
import ast
from pathlib import Path

from hivemind.nav.router import Router

RUN_FARM = Path(__file__).resolve().parents[2] / "scripts" / "run_farm.py"


def _steps(name):
    edge = next(e for e in Router().edges if e.name == name)
    return [{k: v for k, v in s.items() if k != "why"} for s in edge.steps]


def test_her_walk_is_the_stacks_walk_to_her_pad_then_back_34():
    hers, stack = _steps("natro_out_honey_bee"), _steps("natro_out_sticker_stack")
    assert hers[:-1] == stack[:len(hers) - 1]
    assert hers[-2] == {"op": "walk", "keys": "w", "studs": 128.0}
    assert hers[-1] == {"op": "walk", "keys": "s", "studs": 34.0}
    assert stack[len(hers) - 1] == {"op": "walk", "keys": "s", "studs": 16.0}


def test_no_override_sends_her_hand_in_elsewhere():
    tree = ast.parse(RUN_FARM.read_text())
    value = next(n.value for n in tree.body
                 if isinstance(n, (ast.Assign, ast.AnnAssign))
                 and "GIVER_ROUTE_OVERRIDE" in ast.unparse(n.targets[0] if isinstance(n, ast.Assign) else n.target))
    assert "honey_bee" not in ast.literal_eval(value)

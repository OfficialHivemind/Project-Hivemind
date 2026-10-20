"""FEED_OVERRIDE_LOOK: the walk home the feed moved off a death's spawn point
is looked at first, look-only (scripts/run_farm.feed_override_look)."""
import ast
from pathlib import Path

import hivemind

RUN_FARM = Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"


def test_look_only_and_wired_into_the_feed_override():
    src = RUN_FARM.read_text(encoding="utf-8")
    tree = ast.parse(src)
    flag = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == "FEED_OVERRIDE_LOOK_LIVE")
    assert flag.value is False
    at = src.index("but the feed has named ")
    assert "feed_override_look(since)" in src[at:at + 1500]
    helper = src[src.index("def feed_override_look"):src.index("def narrate(event)")]
    assert "would: " in helper
    assert "vin." not in helper and "runner." not in helper     # says, walks nothing

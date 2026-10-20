"""natro_out_pepper's second jump by the coconut (research 2026-10-21): only 1
trip in 6 cleared that lip with Natro's 0.2 s press, so Space is held 0.8 s (a
fall back jumps again), the coast after it is cut to match, and a look-only
check reads whether it landed atop the ledge (run_farm PEPPER_LEDGE_*)."""
from __future__ import annotations

import pathlib

import yaml

import hivemind

ROOT = pathlib.Path(hivemind.__file__).resolve().parents[2]


def test_the_second_jump_is_held_and_the_coast_checks_the_ledge():
    rows = yaml.safe_load((ROOT / "data/world/natro_paths.yaml").read_text())["edges"]
    steps = next(r for r in rows if r["name"] == "natro_out_pepper")["steps"]
    at = next(i for i in range(len(steps) - 4)
              if steps[i] == {"op": "pause", "seconds": 1.1} and steps[i + 1]["op"] == "jump_hold")
    assert steps[at + 2]["seconds"] == 0.8
    coast = steps[at + 4]
    assert coast["op"] == "coast" and coast["studs"] == 56.0
    assert coast["check"] == "atop_the_pepper_ledge"
    farm = (ROOT / "scripts/run_farm.py").read_text()
    assert '"atop_the_pepper_ledge": routes_atop_the_pepper_ledge' in farm
    assert "PEPPER_LEDGE_CHECK_LIVE = False" in farm          # look-only until its frames are judged

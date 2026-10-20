"""Q8: a colour-pollen quest step (Bucko blue, Riley red) sends its trips to the
field with the most MEASURED pollen/s of that colour (brain/decide
COLOUR_STEP_FIRST), and run_farm's weak_quest_best alternation weighs honey."""
from __future__ import annotations

import re
from pathlib import Path

import hivemind
from hivemind.brain import questneeds
from hivemind.brain.decide import Planner, Situation
from hivemind.brain.fieldnotes import FieldNotes, Note

ROOT = Path(hivemind.__file__).resolve().parents[2]

# The planner's own rates on the 2026-10-20 08:23 trip (var/trips.jsonl,
# attempt 1105) and the petal shares in var/field_notes.json (blue, red, white %).
LIVE = {"pine_tree": (36_234, (68, 7, 25)),
        "rose": (7_255, (16, 57, 27)),
        "mountain_top": (3_158, (56, 28, 16)),
        "pumpkin": (13_298, (30, 20, 50))}
FIELDS = {f: {"bees_required": 0, "flowers": 700, "mobs": [], "safe": True} for f in LIVE}


def _planner(lines):
    notes = FieldNotes()
    for name, (rate, (b, r, w)) in LIVE.items():
        notes.notes[name] = Note(field=name, pollen=rate * 600, seconds=600.0,
                                 paid_pollen=rate * 600, paid_seconds=600.0,
                                 petals={"blue": b, "red": r, "white": w})
    p = Planner(FIELDS, notes, quest_needs=questneeds.from_lines(lines))
    p.quest_first = True
    return p


def _top(p):
    return p.rank(Situation(pollen=0))[0]


def test_a_red_step_goes_to_the_most_red_per_second_not_pine_tree():
    # before Q8: Pine Tree (x1.04 tilt) beat Rose (x1.29) -- red at 2,536/s
    top = _top(_planner(["Collect 120,000,000 Red Pollen. 30/120,000,000"]))
    assert top.field == "rose" and top.quest_first            # 7,255 x 57% = 4,135 red/s
    assert "most red pollen/s" in top.why


def test_a_blue_step_stays_on_pine_tree():
    top = _top(_planner(["Collect 55,000,000 Blue Pollen. 34,207,253/55,000,000"]))
    assert top.field == "pine_tree" and top.quest_first        # 36,234 x 68% = 24,639


def test_no_colour_step_or_quests_first_off_changes_nothing():
    assert not _top(_planner(["Collect 20,000,000 Red Pollen. Complete!"])).quest_first
    p = _planner(["Collect 120,000,000 Red Pollen. 30/120,000,000"])
    p.quest_first = False
    assert _top(p).field == "pine_tree"


def test_honey_still_gets_every_other_trip():
    farm = (ROOT / "scripts" / "run_farm.py").read_text()
    share = re.search(r"^QUEST_WEAK_SHARE = ([0-9.]+)$", farm, re.M).group(1)
    start = farm.index("def weak_quest_best(")
    ns = {"QUEST_WEAK_SHARE": float(share)}
    exec(farm[start:farm.index("\ndef ", start + 1)], ns)
    alts = _planner(["Collect 120,000,000 Red Pollen. 30/120,000,000"]).rank(Situation(pollen=0))
    assert ns["weak_quest_best"](alts, "rose").field == "pine_tree"   # 7,255 < 0.33 x 36,234

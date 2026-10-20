"""tools/death_predictors.py: scores logged signals against real deaths."""
import importlib.util
from pathlib import Path

import hivemind

ROOT = Path(hivemind.__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("death_predictors", ROOT / "tools/death_predictors.py")
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)

RETREAT = "retreat would:"
DISC = "threat eye: not counting a red attack disc 774x617 covering 16% of the world: no mob"

LOG = f"""\
    23:58:00  I am in the pumpkin field (80% sure, feed, 3s ago) · facing spawn heading
    {DISC}
    23:59:40  {RETREAT} end the gather -- the health bar reads 0.45 then 0.27
    23:59:45  {RETREAT} end the gather -- the health bar reads 0.20 then 0.21
    00:00:00  died: pollen fell 541,202 -> 292 (540,910 lost)
    00:00:05  died: pollen fell 541,202 -> 292 (540,910 lost) with no convert; ending this trip
    00:10:00  {RETREAT} end the gather -- the health bar reads 0.20 then 0.21
    00:20:00  died: pollen fell 50,000 -> 0 (50,000 lost)
"""


def test_scores_precision_recall_and_lead():
    total = dp.score([LOG.splitlines()])
    retreat = total["retreat would (own health bar low+falling)"]
    # the two lines 5 s apart fold into one event; the midnight roll is the next day
    assert (retreat["events"], retreat["right"]) == (2, 1)
    # the repeated died line and the 50k loss are not extra deaths
    assert (retreat["deaths"], retreat["caught"], retreat["leads"]) == (1, 1, [20])
    # the disc came 120 s before: outside the 90 s window
    disc = total["attack disc ignored, 15-30%"]
    assert (disc["events"], disc["right"], disc["caught"]) == (1, 0, 0)
    assert total["in pumpkin/pepper (field only)"]["events"] == 1
    assert "| retreat would (own health bar low+falling) | 2 | 1 | 50% | 1/1 | 100% | 20 s |" in dp.table(total)

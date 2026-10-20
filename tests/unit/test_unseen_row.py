"""UNSEEN_ROW_RESCUE (run_farm): a field's walk home that left the hive row out
of view skips the search by sight (0 landings in 16, runs 1067-1169)."""
from pathlib import Path

import hivemind

REPO = Path(hivemind.__file__).resolve().parents[2]


def test_unseen_row_skips_the_search_by_sight_look_only_first():
    src = (REPO / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert "\nUNSEEN_ROW_RESCUE_LIVE = False\n" in src
    row = src[src.index("            def along_the_row():"):src.index("            def by_sight(")]
    # the row search records what it read, before it returns "not in view"
    assert row.index('row_unseen["px"] = (') < row.index("the hive row is not in view")
    sight = src[src.index("            def by_sight("):src.index("found = home_by_sight(")]
    assert 'from_field and not teleported and row_unseen["px"] is not None' in sight
    assert "if UNSEEN_ROW_RESCUE_LIVE:" in sight and "(UNSEEN_ROW_RESCUE look)" in sight
    # a skipped search by sight is not counted as one that failed
    assert 'if not skip_sight and not row_unseen["skipped"]:' in src

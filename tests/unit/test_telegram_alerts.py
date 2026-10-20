"""scripts/telegram_alerts: the total-honey line on every Discord alert."""
import importlib.util
import json
from pathlib import Path

import hivemind

_spec = importlib.util.spec_from_file_location(
    "telegram_alerts_honey", Path(hivemind.__file__).resolve().parents[2] / "scripts" / "telegram_alerts.py")
ta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ta)


def test_the_honey_line_says_the_total_and_how_old_it_is(tmp_path):
    """The owner, 2026-10-22: the alerts channel shows the total honey every time."""
    f = tmp_path / "balance.json"
    f.write_text(json.dumps({"at": 1000.0, "honey": 1234567890}), encoding="utf-8")
    assert ta.honey_line(now=1000.0 + 300, path=f) == "🍯 Total honey: 1,234,567,890 (read 5 min ago)"
    assert ta.honey_line(now=1000.0, path=f).endswith("(read just now)")
    assert ta.honey_line(path=tmp_path / "none.json") == ""

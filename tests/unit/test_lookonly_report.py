"""tools/lookonly_report.py: finds each look-only flag, its logged text and
its comment, and counts that text in run logs only after the flag's time."""
import importlib.util
import os
from pathlib import Path

import hivemind

ROOT = Path(hivemind.__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("lookonly_report", ROOT / "tools/lookonly_report.py")
lr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lr)

SRC = '''"""A module. FOO_LIVE is said here too."""
# THE FOO WALK, LOOK-ONLY: it logs "foo would: walk ..." until a night of
# those lines is checked; True walks.
FOO_STEP = 3
FOO_LIVE = False
BAR_LIVE = False                # set True once seen


def foo(say):
    if not FOO_LIVE:
        say(f"foo would: walk {FOO_STEP} steps -- look-only (FOO_LIVE off)")
'''


def test_flags_texts_and_counts(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text(SRC)
    found = {f["name"]: f for f in lr.flags(tmp_path)}
    assert set(found) == {"FOO_LIVE", "BAR_LIVE"}
    # the comment above, past the sibling constant; an inline one is its own
    assert "until a night of those lines is checked" in found["FOO_LIVE"]["comment"]
    assert found["BAR_LIVE"]["comment"] == "set True once seen"
    assert "True walks" in lr.flip_rule(found["FOO_LIVE"]["comment"])
    texts = lr.texts("FOO_LIVE", found["FOO_LIVE"]["comment"], tmp_path)
    assert "foo would: walk" in texts and "FOO_LIVE" in texts
    assert lr.texts("BAR_LIVE", found["BAR_LIVE"]["comment"], tmp_path) == []

    old, new = tmp_path / "run-1.log", tmp_path / "run-2.log"
    old.write_text("10:00  foo would: walk 3 steps\n")
    new.write_text("11:00  foo would: walk 3 steps\nnothing\n12:00  bar would: fly away\n")
    os.utime(old, (100, 100))
    os.utime(new, (300, 300))
    seen, others = lr.scan([old, new], {"FOO_LIVE": (200, texts), "BAR_LIVE": (None, [])})
    assert seen["FOO_LIVE"][0] == 1 and seen["FOO_LIVE"][1][0][0] == new
    assert seen["BAR_LIVE"] == (0, [])
    assert others == {"bar": 1}

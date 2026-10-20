"""scripts/shoot_gui.py makes the public screenshots: it must use the demo's
own folders before anything reads settings (docs/pending/launch-plan.md)."""
from pathlib import Path

import hivemind

SHOOT = Path(hivemind.__file__).resolve().parents[2] / "scripts" / "shoot_gui.py"


def test_the_renderer_switches_to_the_demo_folders_before_the_gui_loads():
    text = SHOOT.read_text(encoding="utf-8")
    assert "use_demo_dirs()" in text
    assert text.index("use_demo_dirs()") < text.index("from hivemind.gui")

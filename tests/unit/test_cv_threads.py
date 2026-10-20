"""S4: the bot caps OpenCV's thread pool, and low power is opt-in.

MEASURED 2026-10-26 (docs/pending/s4-cpu.md): the pool's 15 idle-spinning
workers were 1.5-1.8 of the live bot's 2.3-2.7 cores. The cap must be set
before the first frame is read. Low power is the Eco AI mode since AI-N4
(world/aimode): auto by default, chosen from the measured PC.
"""
from __future__ import annotations

from pathlib import Path

import hivemind
from hivemind.world.settings import SECTIONS, takes_effect

RUN_FARM = Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"


def test_ai_mode_is_a_choice_and_auto_by_default():
    entry = next(e for _, entries in SECTIONS for e in entries
                 if e[0] == "perf.ai_mode")
    assert entry[2] == "choice" and entry[3] == "auto"
    assert entry[5] == ["auto", "eco", "standard", "max"]
    assert takes_effect("perf.ai_mode") == "from the next attempt"


def test_run_farm_caps_the_pool_right_after_loading_settings():
    text = RUN_FARM.read_text(encoding="utf-8")
    assert "\nCV_THREADS = 4\n" in text
    main = text[text.index("def main() -> int:"):]
    loaded = main.index("settings = Settings()")
    probed = main.index("hw = hardware.probe()")
    capped = main.index("cv2.setNumThreads(1 if eco else CV_THREADS)")
    # before the join, the live view or any look can start the default pool;
    # the PC is measured first (AI-N4: the probe times 1 thread itself)
    assert loaded < probed < capped < main.index("LiveView(")
    assert main[loaded:capped].count("\n") < 40

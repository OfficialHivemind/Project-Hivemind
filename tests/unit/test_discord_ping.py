"""Discord pings only the alerts that need the owner (2026-10-19)."""
import importlib.util
from pathlib import Path

import hivemind

SPEC = importlib.util.spec_from_file_location(
    "telegram_alerts_ping", Path(hivemind.__file__).resolve().parents[2] / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tg)


def test_needs_him_pings_the_rest_is_silent():
    assert tg.PING_IF.search("A question for you in the Decision Inbox (open Hivemind to answer): x")
    assert tg.PING_IF.search("MYTHIC BEE! A Royal Jelly roll just made a Tadpole Bee.")
    assert tg.PING_IF.search("Not enough free memory to start the game (1.2 GB free).")
    assert not tg.PING_IF.search("Quest handed in at the Polar Bear.")
    assert not tg.PING_IF.search("The Blender crafted 1 Enzymes.")
    assert not tg.PING_IF.search("Hourly self-review: fine")

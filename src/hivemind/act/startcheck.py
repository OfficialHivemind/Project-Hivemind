"""Whether an unattended start may press Play now (U13 start on boot).

Here, not in gui/, because the GUI may not import platform (test_layering)."""
from __future__ import annotations


def blocker(settings, playing=None, memory_check=None) -> str:
    """Why not to press Play now, or '' to go: the game guard, then memory."""
    from ..platform.current import gameguard, memory
    playing = playing or gameguard.playing
    memory_check = memory_check or memory.check
    game = playing(gameguard.games_of(settings.get("guard.games")))
    if game:
        return f"you are playing {game} (the game guard never starts beside a game)"
    ok, said = memory_check("the bot")
    return "" if ok else said

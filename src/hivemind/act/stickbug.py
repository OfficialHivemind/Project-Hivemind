"""X5 THE STICK BUG CHALLENGE (owner 2026-10-15). LOOK-ONLY scaffolding.

Everything about the challenge here is the BSS wiki's [assumed]: no run log
(var/night run-*.log), frame or jsonl in var/ mentions a Stick Bug, and
Natro does not play the challenge (it only takes the Stick Bug Amulet's
-Monster Respawn % into its mob timers). Sources and the plan:
data/knowledge/stickbug.yaml, docs/pending/stickbug-x5.md.

What the wiki says (Stick_Bug rev 445590, Stick_Bug_Challenge rev 448447):
Stick Bug stands on the tallest mushroom in the Mushroom Field, needs a
Translator given to him once, and starts the 10-minute server-wide challenge
for free every 36 h or for 50 tickets ("The option to pay 50 tickets will be
unavailable if the challenge can be started for free" -- so his panel itself
says whether the free start is due). The fight begins in the Sunflower Field.

With `challenges.stick_bug` on, `would` says once per reason what a start
would do; nothing walks, flies, talks or clicks until STICK_BUG_LIVE is True,
and that waits on the live measurements in the plan.
"""
from __future__ import annotations

SETTING = "challenges.stick_bug"
# LOOK-ONLY until his panel, the start prompt and the challenge HUD are measured.
STICK_BUG_LIVE = False
FREE_EVERY_S = 36 * 3600        # wiki: "for free once every 36 hours" [assumed]
TICKET_PRICE = 50               # never paid: the free entry only
CHALLENGE_S = 600               # "lasts 10 minutes" [assumed]
START_FIELD = "sunflower"
NPC_FIELD = "mushroom"
# THE MONDO CHICK holds Mountain Top from :00 to :15 UTC every hour
# (data/world/timers.yaml mondo_chick) and Mountain Top is one of Stick Bug's
# fields; the wiki's first tip is to start with no Mondo Chick up. A 10-minute
# challenge started from :15 to :50 ends before the next chick.
CLEAR_FROM_MINUTE = 15
CLEAR_UNTIL_MINUTE = 50


def wanted(settings) -> bool:
    try:
        return bool(settings.bool(SETTING))
    except Exception:
        return False                # optional features are off by default


def would(settings, utc_minute: int):
    """(live, message) for this errand chain, or None when switched off.
    `live` is always False while STICK_BUG_LIVE is False."""
    if not wanted(settings):
        return None
    if not CLEAR_FROM_MINUTE <= utc_minute < CLEAR_UNTIL_MINUTE:
        return False, (f"stick bug: not now — a start is only from :{CLEAR_FROM_MINUTE} "
                       f"to :{CLEAR_UNTIL_MINUTE} UTC, clear of the Mondo Chick")
    plan = ("go to Stick Bug on the tallest mushroom (Mushroom Field), open his panel, "
            "press only '[Free Entry]' (never the 50-ticket start), then fight him from "
            "the Sunflower Field for 10 minutes; an amulet box gets only 'Keep Old'")
    if not STICK_BUG_LIVE:
        return False, (f"stick bug would: {plan}; look-only (act/stickbug "
                       f"STICK_BUG_LIVE is False)")
    return True, f"stick bug: {plan}"

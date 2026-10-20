"""M2b AUTO MONDO COLLECT: after a Mondo Chick dies, its loot by sight.

WHAT HAPPENS TODAY (MEASURED, docs/pending/bosses-and-quests.md "M2b"): the
bot never fights the chick. It killed the character 10 s after a landing on
Mountain Top (27 Sep 14:09:37 -> 14:09:47 local, run-503), and since then the
field guard (world/timers, data/world/timers.yaml) keeps every trip off
Mountain Top from :00 to :15 UTC. No "Defeated Mondo Chick!" line and no
"(from Mondo Chick)" drop is in any run log (run-1..1085), var/mob_kills.jsonl
or var/mob_drops.jsonl.

WHAT THIS ADDS: the feed's word that the chick is down, once per kill, and
what its loot pickup is -- the field-kill loot burst that already runs live
(run_farm `chase_a_token` -> bugrun.loot_by_sight, 700 bursts in the run logs,
1,519 coins walked to, 956 reached), only longer: Natro nm_Mondo loots for 45 s
after its kill (natro_macro.ahk 16259). The drops are found by the coin
detector, never at invented positions. It ships LOOK-ONLY: with the setting on
it logs "mondo loot would: ..." until MONDO_LOOT_LIVE is set True, because no
kill line has ever been read, so the words below are the wiki's [assumed].
"""
from __future__ import annotations

import re

SETTING = "combat.mondo_loot"
# LOOK-ONLY until a live kill line has been read and its log line checked.
MONDO_LOOT_LIVE = False
FIELD = "mountain_top"          # the chick's field (data/knowledge/world.yaml)
# Natro nm_Mondo's loot timeout, "45 seconds loot timeout" (natro_macro.ahk
# 16259), and its 12 loot passes (A_Index <= 12) taken as 12 chases.
LOOT_SECONDS = 45.0
LOOT_CHASES = 12
# ONE CHICK AN HOUR, there for 15 minutes (world/timers): a kill line read
# again within this is the same kill (a feed line lives ~10 s and is read
# several times, bugrun.FEED_LINE_SECONDS).
SAME_KILL_S = 900.0
# "Defeated Mondo Chick!" / "Captured Mondo Chick!" -- the chick prints both
# (wiki Mondo_Chick rev 448404, via act/commando) [assumed: never measured].
# Spaces dropped first: tesseract runs words together (act/commando._said).
KILLED = re.compile(r"(defeated|captured).{0,3}mondo|mondo.{0,14}captured")


def killed(feed_text: str) -> bool:
    return bool(KILLED.search("".join(str(feed_text or "").lower().split())))


def wanted(settings) -> bool:
    try:
        return bool(settings.bool(SETTING))
    except Exception:
        return False                # optional features are off by default


class Watch:
    """Says once per kill what the loot pickup does; `live` is whether it acts."""

    def __init__(self):
        self.last = None

    def heard(self, text: str, where, settings, now: float, quest_wants=None):
        """(live, message) for a new kill line, else None. `quest_wants`: the
        Mondo Chicks a quest step still wants (questneeds.mobs_wanted), 0 for
        none; None leaves the pro tester's cadence (brain/protips rule 16)
        unasked."""
        if not killed(text):
            return None
        if self.last is not None and now - self.last < SAME_KILL_S:
            return None
        self.last = now
        said = "the feed says the Mondo Chick was defeated"
        if not wanted(settings):
            return False, f"mondo loot: {said} ({SETTING} is off)"
        if where != FIELD:
            here = where.replace("_", " ") if where else "a field the feed has not named"
            return False, (f"mondo loot: {said}, but the character is in {here}, "
                           f"not Mountain Top — its loot lies there; no walk")
        if quest_wants is not None:
            from ..brain import protips
            go, why_not = protips.mondo_this_hour(quest_wants)
            if not go:
                return False, f"mondo loot: {said}, skipped — {why_not}"
        plan = (f"chase the coins in view on Mountain Top by sight for up to "
                f"{LOOT_SECONDS:.0f}s, at most {LOOT_CHASES} chases, each walking "
                f"back where it began (bugrun.loot_by_sight, the field-kill loot burst)")
        if not MONDO_LOOT_LIVE:
            return False, (f"mondo loot would: {plan} — {said}; look-only "
                           f"(act/mondo MONDO_LOOT_LIVE is False)")
        return True, f"mondo loot: {said} — {plan}"

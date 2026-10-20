"""M8b FIREFLIES: the Moon Charms they leave at night, measured, and the night
field choice nudged toward them when a goal wants charms.

THE GAME (data/knowledge/goals.yaml `moon_charm`, wiki Fireflies rev
2026-02-04): at night fireflies land in Rose, Cactus, Pineapple, Spider,
Strawberry or Bamboo and usually leave 1, 5 or 10 Moon Charms; the feed says
"+1 Moon Charm (from Fireflies)".

MEASURED 2026-10-19 on the test account (var/, read only):
  * the feed. 19 cached feed reads (var/vlm_cache, 23-30 Sep, the VLM era)
    carry "(from Fireflies)": about 10 credits once a line read twice is
    counted once (+1 x8, +5 x2, ~18 charms in 8 days), every one while
    gathering, never chased. Since the feed went to tesseract (Oct) nothing
    logged them: act/bugrun.FeedDrops kept only the book's mobs and the
    Sprout, so var/mob_drops.jsonl has 26 Moon Charm rows, all "(from
    Sprout)", and none from fireflies.
  * the quest. Riley's "Chase 256 Fireflies." read 0/256 (17 Oct 02:19),
    18 (17 Oct 23:13), 62, 86, 99, 131, 147/256 (19 Oct 21:48): about 50
    fireflies a day touched by plain gathering, again never chased.
  * the time. var/trips.jsonl, 6-19 Oct: 19-454 gather minutes a day in
    the six fields (median ~170); night is ~10% of the clock (vision/night),
    so about 17 night minutes a day there (2-47). A night lasts 2:35 and a
    trip ~9 min, so a nudged trip gathers 2 min of night at most.
  * the look. Night frames in those fields exist (var/incidents/042916- and
    042955-mob-sighting, Strawberry, 23 Sep 04:29, 49 s before a "+1 Moon
    Charm (from Fireflies)"; var/routes/attempt-540 174731-174737, Pineapple,
    30 Sep, 23 s before three credits), but none shows a firefly the eye can
    pick out from the sparkles, bubbles and yellow "+N" pop-ups -- every one
    of which a "glowing yellow-green blob" rule would fire on. So there is
    no detector and no chase (ROADMAP M8b (c)).

WHAT THIS DOES:
  (a) PASSIVE, always: every "(from Fireflies)" credit -> var/fireflies.jsonl
      (`row`), with the field the feed or the locator names.
  (b) with `combat.fireflies` on, LIVE: a trip planned at night (the hive
      pad's view, vision/night) while a goal is short of Moon Charms and the
      ledger shows fireflies pay (`pays`) goes to the best firefly field the
      planner ranked, if it scores at least NUDGE_SHARE of its own pick
      (`nudge`).
  (c) with `combat.fireflies` on: each credit keeps the 10 s of frames before
      it (var/incidents/*-firefly, at most FRAME_WINDOWS on disk) -- the
      frames a detector is to be built from. WHAT TO CAPTURE: those windows
      (the touch is the last frame, so the firefly is in the ones before),
      at least 10 of them from 3+ fields; mark the firefly's box in 30+
      frames, and as many frames with sparkles / "+N" pop-ups / bubbles
      and no firefly as negatives. Then a blob rule (or the coin detector
      retrained) can be scored against them before any walk is LIVE.
"""
from __future__ import annotations

import json

SETTING = "combat.fireflies"
# goals.yaml `moon_charm` (the wiki's Fireflies page): where they land
FIELDS = frozenset({"rose", "cactus", "pineapple", "spider", "strawberry", "bamboo"})
# "(from Fireflies)" as act/bugrun.FeedDrops' extras: a source, not a mob
SOURCES = {"fireflies": "fireflies", "firefly": "fireflies"}
SLUG = "fireflies"
# the ledger "pays" once this many credits are in it: 3 is a third of the
# Sept count, enough to say it was no misread, too few to rank fields by
PAYS_MIN_CREDITS = 3
# ponytail: a flat share of the planner's own score, not charms priced in
# honey -- a Moon Charm has no honey price (act/memorymatch); price it when
# the ledger can say charms per night-minute per field
NUDGE_SHARE = 0.6
FRAME_WINDOWS = 12              # one window is ~150 frames, ~50 MB


def wanted(settings) -> bool:
    try:
        return bool(settings.bool(SETTING))
    except Exception:
        return False                # optional features are off by default


def row(amount: int, field, now: float) -> dict:
    return {"at": now, "charms": int(amount), "field": field}


def load(path) -> list:
    """The ledger's rows; a missing file or a broken line is skipped."""
    out = []
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            got = json.loads(line)
        except ValueError:
            continue
        if isinstance(got, dict):
            out.append(got)
    return out


def pays(rows) -> bool:
    return sum(1 for r in rows if int(r.get("charms") or 0) > 0) >= PAYS_MIN_CREDITS


def goal_wants(plan) -> bool:
    """A goal not owned yet that is short of Moon Charms (brain/goals plan),
    as brain/hop.goal_wants_stingers."""
    try:
        return any(n.material == "moon_charm" for r in plan.rows if not r.owned
                   for n in r.missing)
    except Exception:
        return False


def nudge(alternatives, chosen):
    """(field, why) for the best-scored reachable firefly field the planner
    ranked, when `chosen` is not one and it scores NUDGE_SHARE of it; else
    None."""
    if not chosen or chosen in FIELDS:
        return None
    alts = list(alternatives or ())
    own = next((a for a in alts if a.field == chosen), None)
    if own is None or not own.score or own.score <= 0:
        return None
    best = max((a for a in alts if a.field in FIELDS and a.reachable and a.score > 0),
               key=lambda a: a.score, default=None)
    if best is None or best.score < NUDGE_SHARE * own.score:
        return None
    return best.field, (f"night, a goal is short of Moon Charms and the fireflies "
                        f"have paid them (var/fireflies.jsonl): "
                        f"{best.field.replace('_', ' ')} scores "
                        f"{best.score / own.score:.0%} of {chosen.replace('_', ' ')}")

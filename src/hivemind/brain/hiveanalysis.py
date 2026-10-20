"""Hive analysis: which held bees MEASURABLY bring tokens in (ROADMAP H3).

A viewer asked for "which bees to add / drop" from what the hive really
brings in. The bee menu gives the bees by type (act/beemenu); the token
school's lessons (var/school-coins/lessons.jsonl) say which token KINDS were
picked up ("collected"). This joins them through the one table below: which
bee type makes which token. Nothing here acts; run_farm only logs the lines
after a bee-menu read, beside hivejudge's guide verdict.

WHAT IT DOES NOT CLAIM. Honey per convert (trips.jsonl) is the whole hive's
and cannot be split by bee, so it is left out. A bee whose token was never
picked up is not proof it is bad: most bees earn by gathering and converting,
which no token shows, and the kind table is unconfirmed in game
(tokens.yaml). So a zero is said as "no measured token", never as "drop it".
Who sits next to whom is left out too: nothing measured says it matters.
"""
from __future__ import annotations

import json
import pathlib

# WHICH BEE MAKES WHICH TOKEN, only kinds tokens.yaml can name and whose maker
# is written down: wiki Module:Ability_Tokens/data (docs/pending/
# brain-research-2.md section 1, read 2026-10-11) and the Tabby Bee page
# (bees.yaml, 2026-09-21). bomb_sync is the BLUE one (its icon hue 112).
MAKERS = {
    "baby_love": ("baby",),
    "blue_boost": ("diamond",),
    "bomb_sync": ("cobalt",),
    "focus": ("looker", "music"),
    "haste": ("hasty", "ninja"),
    "puppy_love": ("puppy",),
    "scratch": ("tabby",),
    "tabby_love": ("tabby",),
    "token_link": ("music",),
}
# THE LAST N JUDGED CHASES: lesson `at` is time.monotonic (school.snapshot),
# so it cannot give a per-hour rate across restarts; a lesson count can.
WINDOW = 2000


def pickups(lessons_path, window: int = WINDOW) -> tuple:
    """({kind: collected}, judged) over the last `window` judged lessons."""
    try:
        text = pathlib.Path(lessons_path).read_text()
    except OSError:
        return {}, 0
    judged = []
    for line in text.splitlines():
        try:
            body = json.loads(line)
        except ValueError:
            continue
        if body.get("outcome") in ("collected", "nothing"):
            judged.append(body)
    judged = judged[-window:]
    got: dict = {}
    for body in judged:
        if body["outcome"] == "collected":
            got[body.get("kind")] = got.get(body.get("kind"), 0) + 1
    return got, len(judged)


def analyse(counts: dict, got: dict) -> list:
    """[(bee, held, {kind: pickups credited})], most pickups per bee first.
    A kind two held types make is split by how many of each are held
    (ESTIMATED: the wiki gives no per-bee share in a mixed hive)."""
    out = {}
    for kind, bees in MAKERS.items():
        held = {b: int(counts.get(b) or 0) for b in bees if counts.get(b)}
        total = sum(held.values())
        for bee, n in held.items():
            out.setdefault(bee, {})[kind] = got.get(kind, 0) * n / total
    rows = [(bee, int(counts[bee]), kinds) for bee, kinds in out.items()]
    rows.sort(key=lambda r: -sum(r[2].values()) / r[1])
    return rows


def would_lines(counts: dict, got: dict, judged: int, labels: dict | None = None) -> list:
    """The log lines: one per held token-making bee type."""
    if not judged:
        return ["hive analysis: no judged token chases yet -- nothing measured to say"]
    labels = labels or {}
    lines = []
    for bee, held, kinds in analyse(counts, got):
        name = labels.get(bee, bee)
        said = ", ".join(f"{v:.0f} {k.replace('_', ' ')}" for k, v in kinds.items())
        if sum(kinds.values()):
            lines.append(f"hive analysis: {held} {name} -> {said} picked up in the "
                         f"last {judged} judged chases ({sum(kinds.values()) / held:.1f} a bee)")
        else:
            lines.append(f"hive analysis: {held} {name} -> no measured token in the last "
                         f"{judged} judged chases (it may still earn by gathering)")
    return lines

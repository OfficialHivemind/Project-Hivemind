#!/usr/bin/env python3
"""Walks home: how many landed on the pad, per day and per field, and how the
rest failed (ROADMAP A6: 98%+, measured daily). Read-only over the run logs.

    nice -n 19 ./scripts/landing_rate.py [--days 7] [--today] [--var DIR]

WHY NOT THE LEDGER'S "landing". benchmark's landing % and the daily card's
"walks home landed" tile count the walk-home ROUTES the ledger judged
(trips.jsonl `routes`), and a walk home that began where the feed did not
place the character has no verdict there: a gather that ended off its field
(the pollen stopped rising), a death, a walk that never ran its route. Those
are the walks that strand. MEASURED runs 1150-1246 (21-26 Oct): the ledger
judged 9 walks home from Pepper and 8 of them landed; the run logs show 30
Pepper trips home, 6 landed and 22 were rescued, 21 of them after a gather
that ended off the field. So this reads the run logs instead.

ONE WALK HOME A GATHER TRIP: from the trip's "the trip aimed at X and the game
credited Y" line (Y is the field it is filed under) to its "cycle N:" line.
Its verdict, the worst thing in between:
  rejoin    "asking for a rejoin"
  rescued   a Whirligig rescue, or a respawn because it was stranded (the bag
            converted by a Micro-Converter first, or lost under the respawn)
  died      a death read on the way (A28: some are conversions read as one)
  sight     "to hive: arrived" after the search by sight looked round
  landed    "to hive: arrived" with no looking round
  whirligig the planned Whirligig home (no walk; not in the rate)
  none      no verdict line (a stop, a convert that read nothing)
rate = (landed + sight) / (landed + sight + rescued + rejoin). Died and none
are shown and left out, as the ledger leaves "unknown" out.
"off" marks a gather that ended off its field ("the gather ended because the
pollen stopped rising"). A miss's "why" is its "to hive: did not get there"
reason, numbers stripped.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import benchmark as bm  # noqa: E402  (runs + run_lines: the logs on a clock)

VAR = ROOT / "var"
_TEXT = re.compile(r"^\s+\d\d:\d\d:\d\d  (.*)$")
_AIM = re.compile(r"^the trip aimed at (.+?) and the game credited (.+?) while it was out")
_CYCLE = re.compile(r"^cycle \d+:")
OFF_FIELD = "the gather ended because the pollen stopped rising"
WORST_FIRST = ("rejoin", "rescued", "died", "sight", "landed", "whirligig")
COUNTED = ("landed", "sight", "rescued", "rejoin")


def _verdict(text: str, looked: bool) -> str | None:
    if text.startswith("to hive: arrived"):
        return "sight" if looked else "landed"
    if text.startswith("whirligig home: on our pad"):
        return "whirligig"
    if text.startswith("whirligig rescue: on our pad") or (
            text.startswith("respawned") and "stranded" in text):
        return "rescued"
    if "asking for a rejoin" in text:
        return "rejoin"
    if text.startswith("died:"):
        return "died"
    return None


def walks(lines) -> list:
    """[{at, field, verdict, off, why}] from one run's [(unix time, raw line)]."""
    out, cur = [], None
    for t, raw in lines:
        m = _TEXT.match(raw)
        text = m.group(1) if m else raw.strip()
        aim = _AIM.match(text)
        if aim:
            cur = {"at": t, "field": aim.group(2).replace(" ", "_"), "tags": set(),
                   "off": False, "why": "", "looked": False}
            continue
        if cur is None:
            continue
        if _CYCLE.match(text):
            out.append(cur)
            cur = None
            continue
        if text.startswith("look 0:"):
            cur["looked"] = True
        elif text.startswith(OFF_FIELD):
            cur["off"] = True
        elif text.startswith("to hive: did not get there"):
            cur["why"] = re.sub(r"\d[\d,.]*", "N", text[len("to hive: did not get there — "):]
                                ).split(" (")[0].split(" — ")[0]
        v = _verdict(text, cur["looked"])
        if v:
            cur["tags"].add(v)
    for w in out:
        tags = w.pop("tags")
        w["verdict"] = next((v for v in WORST_FIRST if v in tags), "none")
        del w["looked"]
    return out


def load(var: Path, since: float, until: float) -> list:
    out = []
    for _s, _e, lines in bm.run_lines(var, bm.runs(var, until), since, until):
        out += [w for w in walks(lines) if since <= w["at"] <= until]
    return sorted(out, key=lambda w: w["at"])


def rate(ws: list) -> tuple:
    """(landed incl. by sight, counted walks, percent or None)."""
    c = collections.Counter(w["verdict"] for w in ws)
    good, n = c["landed"] + c["sight"], sum(c[k] for k in COUNTED)
    return good, n, (100.0 * good / n if n else None)


def report(ws: list) -> str:
    rows = ["day          walks  landed  sight  rescued  rejoin  died  whirl  off   rate"]
    by_day = collections.defaultdict(list)
    for w in ws:
        by_day[time.strftime("%a %d %b", time.localtime(w["at"]))].append(w)
    for day, d in by_day.items():
        c = collections.Counter(w["verdict"] for w in d)
        _g, n, p = rate(d)
        rows.append(f"{day:<12} {n:>5}  {c['landed']:>6}  {c['sight']:>5}  {c['rescued']:>7}  "
                    f"{c['rejoin']:>6}  {c['died']:>4}  {c['whirligig']:>5}  "
                    f"{sum(w['off'] for w in d):>3}  " + (f"{p:5.1f}%" if p is not None else "   --"))
    rows += ["", "field          walks  landed   rate  off-field  (worst first)"]
    by_field = collections.defaultdict(list)
    for w in ws:
        by_field[w["field"]].append(w)
    for field, d in sorted(by_field.items(), key=lambda kv: rate(kv[1])[2] or 101.0):
        g, n, p = rate(d)
        if n:
            rows.append(f"{field:<14} {n:>5}  {g:>6}  {p:4.0f}%  {sum(w['off'] for w in d):>9}")
    misses = collections.Counter(
        (w["verdict"], "off-field start" if w["off"] else "from the field", w["why"] or "-")
        for w in ws if w["verdict"] in ("rescued", "rejoin"))
    rows += ["", "how the misses failed"]
    rows += [f"{n:>4} x {v} ({start}): {why}" for (v, start, why), n in misses.most_common()]
    return "\n".join(rows)


def today_line(ws: list) -> str:
    """'Walks home today: 91% landed (40 of 44) · worst pepper 2 of 8, 6 began
    off the field' -- the day since local midnight."""
    g, n, p = rate(ws)
    if not n:
        return "Walks home today: none judged yet"
    out = f"Walks home today: {p:.0f}% landed ({g} of {n})"
    fields = collections.defaultdict(list)
    for w in ws:
        fields[w["field"]].append(w)
    worst = min((kv for kv in fields.items() if rate(kv[1])[1]),
                key=lambda kv: rate(kv[1])[2])
    wg, wn, wp = rate(worst[1])
    if wp < 100:
        off = sum(w["off"] and w["verdict"] in ("rescued", "rejoin") for w in worst[1])
        out += (f" · worst {worst[0].replace('_', ' ')} {wg} of {wn}"
                + (f", {off} began off the field" if off else ""))
    return out


def today(var: Path = VAR, now: float | None = None) -> str:
    """today_line for the walks since local midnight (the daily card's caption)."""
    now = time.time() if now is None else now
    midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    return today_line(load(var, midnight, now))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=float, default=7.0)
    p.add_argument("--today", action="store_true")
    p.add_argument("--var", type=Path, default=VAR)
    a = p.parse_args()
    if a.today:
        print(today(a.var))
        return
    now = time.time()
    print(report(load(a.var, now - a.days * 86400, now)))


if __name__ == "__main__":
    main()

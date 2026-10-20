#!/usr/bin/env python3
"""Which logged signal predicts a real death (T-DEATH): every candidate
scored by precision and recall against the deaths in the run logs.

    death_predictors.py                          var/night of this checkout
    death_predictors.py --night DIR --runs 1240-1289

A REAL DEATH is a `died: pollen fell A -> B (N lost)` line (brain/alive)
with N over --min-lost (100,000), repeats within 60 s folded (the trip-end
line says the same death again). A SIGNAL EVENT is a log line matching one
candidate, repeats of the same candidate within REFRACTORY s folded, so a
chatty line is not scored per tick. An event is RIGHT when a real death
follows within --window s (90); a death is CAUGHT when an event of that
candidate came in the --window s before it. LEAD = seconds from the first
event in that window to the died line (the died line comes a few seconds
after the bar empties: alive confirms a fall on two looks).

Lines without a clock carry the last clock seen; a clock that goes back more
than 6 h is the next day. Read-only.

ponytail: one regex per candidate over plain lines; a candidate that needs
frames (health reads below the RETREAT gate, every own-health read) is not
here because the logs only carry the reads `retreat would:` says.
"""
from __future__ import annotations

import argparse
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOCK = re.compile(r"^\s*(\d\d):(\d\d):(\d\d)\s+(.*)")
DIED = re.compile(r"died: pollen fell [\d,]+ -> [\d,]+ \(([\d,]+) lost\)")
FIELD = re.compile(r"I am in the ([a-z ]+?) field\b")
DISC = re.compile(r"not counting a red attack disc \S+ covering (\d+)% of the world")
MOB_BAR = re.compile(r"(?:THREAT: mob health bar|MOB: a threat is on screen: mob health bar"
                     r"|would: count hurt bar mob health bar)")
DANGER_FIELDS = ("pumpkin", "pepper")
REFRACTORY = 10.0
SAME_DEATH = 60.0


def _disc(lo, hi):
    def match(text, field):
        m = DISC.search(text)
        return bool(m) and lo <= int(m.group(1)) < hi
    return match


# name -> match(text, field the last 'I am in the ...' line named)
CANDIDATES = {
    "retreat would (own health bar low+falling)": lambda t, f: "retreat would:" in t or "retreat: health" in t,
    "attack disc ignored, <15% of world": _disc(0, 15),
    "attack disc ignored, 15-30%": _disc(15, 30),
    "attack disc ignored, 30%+": _disc(30, 101),
    "mob health bar seen": lambda t, f: bool(MOB_BAR.search(t)),
    "mob health bar seen in pumpkin/pepper": lambda t, f: bool(MOB_BAR.search(t)) and f in DANGER_FIELDS,
    "reward feed names a mob": lambda t, f: "reward feed: the " in t and " dropped " in t
                                            or "reward feed: a" in t and " was defeated" in t,
    "bug run: own health fell": lambda t, f: "own health fell" in t,
    "buff bar: haste with no count": lambda t, f: "buff bar: haste no count on the icon" in t,
    "in pumpkin/pepper (field only)": lambda t, f: bool(FIELD.search(t)) and f in DANGER_FIELDS,
}


def timeline(lines):
    """[(seconds, text)] from run-log lines, the clock carried forward."""
    out, day, last = [], 0, None
    for line in lines:
        m = CLOCK.match(line)
        if m:
            t = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + day
            if last is not None and t < last - 6 * 3600:
                day += 86400
                t += 86400
            last, text = t, m[4]
        elif last is None:
            continue
        else:
            t, text = last, line.strip()
        out.append((t, text))
    return out


def deaths(tl, min_lost=100_000):
    found = []
    for t, text in tl:
        m = DIED.search(text)
        if m and int(m[1].replace(",", "")) > min_lost and (not found or t - found[-1] > SAME_DEATH):
            found.append(t)
    return found


def events(tl):
    """{candidate: [seconds]} with repeats inside REFRACTORY folded."""
    out = {name: [] for name in CANDIDATES}
    field = None
    for t, text in tl:
        m = FIELD.search(text)
        if m:
            field = m.group(1)
        for name, match in CANDIDATES.items():
            if match(text, field) and (not out[name] or t - out[name][-1] > REFRACTORY):
                out[name].append(t)
    return out


def score(logs, window=90.0, min_lost=100_000):
    """{candidate: dict(events, right, deaths, caught, leads)} over `logs`
    (an iterable of line lists, one per run)."""
    total = {name: dict(events=0, right=0, deaths=0, caught=0, leads=[]) for name in CANDIDATES}
    for lines in logs:
        tl = timeline(lines)
        died = deaths(tl, min_lost)
        for name, ts in events(tl).items():
            s = total[name]
            s["events"] += len(ts)
            s["right"] += sum(any(0 < d - t <= window for d in died) for t in ts)
            s["deaths"] += len(died)
            for d in died:
                before = [t for t in ts if 0 < d - t <= window]
                if before:
                    s["caught"] += 1
                    s["leads"].append(d - before[0])
    return total


def table(total) -> str:
    rows = ["| candidate | events | right | precision | deaths caught | recall | median lead |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    order = sorted(total.items(), key=lambda kv: -(kv[1]["right"] / kv[1]["events"] if kv[1]["events"] else 0))
    for name, s in order:
        p = s["right"] / s["events"] if s["events"] else 0.0
        r = s["caught"] / s["deaths"] if s["deaths"] else 0.0
        lead = f"{statistics.median(s['leads']):.0f} s" if s["leads"] else "-"
        rows.append(f"| {name} | {s['events']:,} | {s['right']:,} | {p:.0%} | "
                    f"{s['caught']}/{s['deaths']} | {r:.0%} | {lead} |")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--night", type=Path, default=ROOT / "var" / "night")
    ap.add_argument("--runs", default="1240-1289", help="run numbers, FIRST-LAST")
    ap.add_argument("--window", type=float, default=90.0)
    ap.add_argument("--min-lost", type=int, default=100_000)
    a = ap.parse_args(argv)
    lo, hi = (int(x) for x in a.runs.split("-"))
    paths = [p for n in range(lo, hi + 1) if (p := a.night / f"run-{n}.log").exists()]
    total = score((p.read_text(encoding="utf-8", errors="replace").splitlines() for p in paths),
                  a.window, a.min_lost)
    print(f"{len(paths)} run logs, runs {a.runs}, death = over {a.min_lost:,} pollen lost, "
          f"window {a.window:.0f} s\n")
    print(table(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""What token chasing earns and costs on this account, from the run logs.

THE QUESTION (2026-10-14): token gathering is where a macro wins or loses,
and `brain/tokenbrain` starts from SEED numbers. Before tuning a seed, measure what a chase does here. This reads
the farm's own narration -- "token brain: chase KIND#N at (x, y) ... scores
S", "chased a token — N step(s), walked onto it", "school: ... — collected:",
"buff bar: haste x3 ... walking 1.3x", "the gather ended off ... flowers",
"cycle N:" -- and joins every chase to its trip in var/trips.jsonl by
(attempt = run number, cycle).

    nice -n 19 ./scripts/token_payoff.py [--since RUN]

It prints: how often it chases, at what, how far and for how long; how often
a chase reaches its token by distance and movespeed (the source of
tokenbrain.REACH_BY_SPEED, and what that table would hold back today); the
HUD-confirmed share (brain/school); the pollen rate against the chase rate
within a field and day; and the walk home against the chases before it.
Light on purpose: text logs and one JSON-lines file, no frames.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import re
import statistics as st
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hivemind.brain import tokenbrain as tb       # noqa: E402

TS = re.compile(r"^\s+(\d\d):(\d\d):(\d\d)  (.*)$")
DECIDE = re.compile(r"token brain(?: \(second look\))?: (chase|hold|return)"
                    r"(?: (\w+)#\d+ at \((\d+), (\d+)\) — .*?scores (\d+))?")
DONE = re.compile(r"chased (?:a token|an? [\w ]+ token) — (\d+) step\(s\), (.*?) \(confidence")
NOSTART = re.compile(r"chase: did not start for")
SCHOOL = re.compile(r"school: \w+ at \((\d+), (\d+)\) — (\w[\w ]*?):")
WALKING = re.compile(r"walking ([\d.]+)x")
IN_ALL = re.compile(r"([\d.]+)x in all")
CYCLE = re.compile(r"cycle (\d+): ")
ANCHOR = (960, 669)                       # act/chase.anchor_of on 1920x1080
ON_FIELDS = {"pine_tree", "blue_flower", "rose", "sunflower", "pineapple",
             "dandelion", "spider", "strawberry", "coconut"}
PX_BINS = (130, 250, 350, 450, 550, 650, 800, 2200)
SPEED_BANDS = ((1.25, "<1.25x"), (1.5, "1.25-1.5x"), (math.inf, ">=1.5x"))


def parse(path: pathlib.Path) -> tuple[list, dict]:
    """Every chase decision of one run, and per cycle (holds, ended off)."""
    run = int(re.search(r"run-(\d+)", path.name).group(1))
    rows, pending, cur, speed = [], [], None, 1.0
    holds, off, per_cycle = 0, False, {}
    for line in path.open(errors="replace"):
        m = TS.match(line)
        if not m:
            continue
        t, msg = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]), m[4]
        if msg.startswith("buff bar:"):
            # the movespeed factor run_farm walks by (haste_seen["factor"])
            b = IN_ALL.search(msg) or WALKING.search(msg)
            speed = float(b[1]) if b else 1.0
        elif "the gather ended off" in msg:
            off = True
        elif (d := DECIDE.search(msg)):
            if d[1] != "chase":
                holds += 1
                continue
            x, y = int(d[3]), int(d[4])
            cur = {"run": run, "t": t, "kind": d[2], "x": x, "y": y, "score": int(d[5]),
                   "speed": speed, "px": math.hypot(x - ANCHOR[0], y - ANCHOR[1])}
            pending.append(cur)
        elif cur is not None and (s := SCHOOL.search(msg)) \
                and (int(s[1]), int(s[2])) == (cur["x"], cur["y"]):
            cur["school"] = s[3]
        elif cur is not None and NOSTART.search(msg):
            cur["outcome"], cur = "nostart", None
        elif cur is not None and (dn := DONE.search(msg)):
            cur["outcome"] = "arrived" if dn[2].startswith("walked onto") else "missed"
            cur["seconds"] = (t - cur["t"]) % 86400
            cur = None
        elif (c := CYCLE.match(msg)):
            for r in pending:
                r["cycle"] = int(c[1])
            per_cycle[(run, int(c[1]))] = {"holds": holds, "off": off}
            rows.extend(pending)
            pending, cur, holds, off = [], None, 0, False
    return rows, per_cycle


def band(speed: float) -> str:
    return next(name for below, name in SPEED_BANDS if speed < below)


def share(xs, test) -> str:
    return f"{sum(map(test, xs)) / len(xs):.0%}" if xs else "-"


def within_slope(groups: dict) -> tuple[float, float, int]:
    """OLS slope of y on x after removing each group's means, and its SE."""
    pts = []
    for g in groups.values():
        if len(g) < 3:
            continue
        mx, my = st.mean(a for a, _ in g), st.mean(b for _, b in g)
        pts += [(a - mx, b - my) for a, b in g]
    sxx = sum(a * a for a, _ in pts)
    if len(pts) < 5 or sxx == 0:
        return 0.0, math.inf, len(pts)
    slope = sum(a * b for a, b in pts) / sxx
    rss = sum((b - slope * a) ** 2 for a, b in pts)
    dof = max(1, len(pts) - 1 - sum(1 for g in groups.values() if len(g) >= 3))
    return slope, math.sqrt(rss / dof / sxx), len(pts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", type=int, default=820,
                    help="first run (attempt) to read; 820 is after the walkspeed fix of 2026-10-09")
    ap.add_argument("--var", default=str(pathlib.Path.home() / "Hivemind" / "var"))
    a = ap.parse_args()
    var = pathlib.Path(a.var)

    chases, cycles = [], {}
    for p in sorted((var / "night").glob("run-*.log")):
        if int(re.search(r"run-(\d+)", p.name).group(1)) >= a.since:
            rows, per = parse(p)
            chases += rows
            cycles.update(per)
    walked = [c for c in chases if c.get("outcome") in ("arrived", "missed")]
    if not walked:
        print("no chases in these runs")
        return 1

    trips = {}
    for line in (var / "trips.jsonl").open():
        r = json.loads(line) if line.strip() else {}
        if (r.get("attempt") or 0) >= a.since:
            trips[(r["attempt"], r["cycle"])] = r
    by_trip = collections.defaultdict(list)
    for c in walked:
        by_trip[(c["run"], c.get("cycle"))].append(c)

    print(f"== CHASES, runs {a.since}+: {len(walked)} walked, "
          f"{sum(c.get('outcome') == 'nostart' for c in chases)} never started")
    print(f"   kinds: {dict(collections.Counter(c['kind'] for c in walked).most_common())}")
    print(f"   px from the character: median {st.median(c['px'] for c in walked):.0f}; "
          f"seconds a detour: median {st.median(c['seconds'] for c in walked):.0f}, "
          f"mean {st.mean(c['seconds'] for c in walked):.1f}; reached {share(walked, lambda c: c['outcome'] == 'arrived')}")
    on = [(k, r) for k, r in trips.items() if r.get("credited") in ON_FIELDS
          and r.get("credited") == r.get("aimed_at") and (r.get("gather_seconds") or 0) >= 90]
    g = sum(r["gather_seconds"] for _, r in on)
    n = sum(len(by_trip.get(k, ())) for k, _ in on)
    held = sum(cycles.get(k, {}).get("holds", 0) for k, _ in on)
    secs = sum(c["seconds"] for k, _ in on for c in by_trip.get(k, ()))
    print(f"   chase fields ({len(on)} trips, {g / 3600:.1f} h gathering): {n / g * 60:.2f} chases a minute, "
          f"{held / g * 60:.2f} holds a minute, {secs / g:.0%} of the gather spent chasing")

    print("\n== HOW OFTEN A CHASE GETS THERE (reached share / mean seconds / n), by px and movespeed")
    for lo, hi in zip(PX_BINS, PX_BINS[1:]):
        cells = []
        for _, name in SPEED_BANDS:
            s = [c for c in walked if lo <= c["px"] < hi and band(c["speed"]) == name]
            cells.append(f"{name} {share(s, lambda c: c['outcome'] == 'arrived'):>4} "
                         f"{st.mean(c['seconds'] for c in s) if s else 0:4.1f}s n{len(s):<4d}")
        print(f"   {lo:4d}-{hi:<4d}px  " + "   ".join(cells))
    held_back = [c for c in walked if c["kind"] in ("honey", "unknown")
                 and c["score"] * tb.reach_multiplier(c["px"], c["speed"]) < tb.MOVEMENT_THRESHOLD]
    rest = [c for c in walked if c not in held_back]
    for name, s in (("tokenbrain.REACH would hold", held_back), ("and keep", rest)):
        if s:
            ar, sec = sum(c["outcome"] == "arrived" for c in s), sum(c["seconds"] for c in s)
            print(f"   {name}: {len(s)} chases, {sec} s, reached {ar} ({ar / len(s):.0%}), "
                  f"{ar / max(1, sec):.3f} reached a second")

    print("\n== HUD-CONFIRMED (brain/school 'collected'), by kind")
    for kind in sorted({c["kind"] for c in walked}):
        s = [c for c in walked if c["kind"] == kind]
        print(f"   {kind}: {share(s, lambda c: c.get('school') == 'collected')} of {len(s)}")

    print("\n== POLLEN RATE AGAINST CHASE RATE, within a field and day (log pollen/s per chase/min)")
    groups = collections.defaultdict(list)
    for k, r in on:
        if (r.get("pollen") or 0) > 0 and not r.get("deaths"):
            day = int(r["at"] // 86400)
            groups[(r["credited"], day)].append(
                (len(by_trip.get(k, ())) / r["gather_seconds"] * 60, math.log(r["pollen"] / r["gather_seconds"])))
    slope, se, npts = within_slope(groups)
    print(f"   {npts} trips: {100 * slope:+.1f}% per extra chase a minute (SE {100 * se:.1f})")

    print("\n== THE WALK HOME, chase fields, by the trip's chases")
    homes = []
    for k, r in on:
        home = [s for s in r.get("routes") or () if isinstance(s, dict) and s.get("kind") == "home"]
        if home and home[0].get("outcome") in ("landed", "elsewhere", "missed"):
            homes.append((len(by_trip.get(k, ())), home[0]["outcome"] == "landed",
                          cycles.get(k, {}).get("off", False), r["credited"]))
    for lo, hi in ((0, 0), (1, 10), (11, 25), (26, 10_000)):
        s = [h for h in homes if lo <= h[0] <= hi]
        print(f"   {lo}-{hi} chases: landed {sum(h[1] for h in s)} of {len(s)}")
    for flag, name in ((True, "ended off the flowers (steered back)"), (False, "ended on them")):
        s = [h for h in homes if h[2] is flag]
        print(f"   {name}: landed {sum(h[1] for h in s)} of {len(s)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

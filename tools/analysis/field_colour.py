#!/usr/bin/env python3
"""What token chases cost and gave, by the field they were in and the kind
chased -- the numbers behind tokenbrain COLOUR_LIVE (docs/pending/fieldcolour.md).

    ./tools/analysis/field_colour.py [--var DIR] [--runs 1254-1258]

Per chase decision in the run logs ("token brain: chase KIND#ID at (x, y)"):
the field of the trip ("to <field>: left the hive"), the
seconds to the school's verdict line (the detour, 1 s log resolution), the
verdict, and from var/school-coins/lessons.jsonl (joined on run, kind, x, y)
the pollen/s before the chase (30 s window) and over it. Then what
tokenbrain.colour_factor says each chase was worth there, and how many the
colour rule would have dropped under the bar. Read-only.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import re
import statistics as st
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))
from hivemind.brain import tokenbrain  # noqa: E402

CLOCK = re.compile(r"^\s+(\d\d):(\d\d):(\d\d)\s+(.*)$")
FIELD = re.compile(r"  to ([a-z ]+): left the hive|gathering with \S*?pattern_([a-z_]+?)_as_natro")
DECISION = re.compile(r"token brain(?: \(second look\))?: chase ([a-z_]+)#(\d+) at "
                      r"\((\d+), (\d+)\) — .*?scores (\d+)")
SCHOOL = re.compile(r"school: ([a-z_]+) at \((\d+), (\d+)\) — (\w+)(.*)")


def runs_arg(text: str) -> list[int]:
    a, _, b = text.partition("-")
    return list(range(int(a), int(b or a) + 1))


def chases(var: pathlib.Path, runs: list[int]) -> list[dict]:
    lessons = collections.defaultdict(list)
    for line in (var / "school-coins" / "lessons.jsonl").open(encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("attempt") in runs:
            lessons[(d["attempt"], d["kind"], d["x"], d["y"])].append(d)
    rows = []
    for run in runs:
        path = var / "night" / f"run-{run}.log"
        if not path.exists():
            continue
        field, pend = None, None
        for line in path.open(encoding="utf-8", errors="replace"):
            if m := FIELD.search(line):
                field = (m.group(1) or m.group(2)).replace(" ", "_")
            if not (t := CLOCK.match(line)):
                continue
            sec = int(t.group(1)) * 3600 + int(t.group(2)) * 60 + int(t.group(3))
            if m := DECISION.search(t.group(4)):
                pend = dict(run=run, field=field, kind=m.group(1), x=int(m.group(3)),
                            y=int(m.group(4)), score=int(m.group(5)), t0=sec)
            elif (m := SCHOOL.match(t.group(4))) and pend and m.group(1) == pend["kind"] \
                    and (int(m.group(2)), int(m.group(3))) == (pend["x"], pend["y"]):
                pend.update(seconds=max(1, (sec - pend["t0"]) % 86400), verdict=m.group(4),
                            haste=m.group(4) == "collected" and "aste" in m.group(5))
                if got := lessons.get((run, pend["kind"], pend["x"], pend["y"])):
                    d = got.pop(0)
                    pend.update(before=d.get("rate_before"), during=d.get("rate_during"))
                rows.append(pend)
                pend = None
    return rows


def mean_ci(xs: list[float], n: int = 2000) -> tuple[float, float, float]:
    """The mean and its 95% bootstrap range (seeded, so reruns agree)."""
    if not xs:
        return (float("nan"),) * 3
    rng = random.Random(1)
    means = sorted(st.mean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return st.mean(xs), means[int(0.025 * n)], means[int(0.975 * n)]


def report(rows: list[dict], hive: str) -> None:
    """Per field and kind. "lost a chase" = (pollen/s of the 30 s window -
    pollen/s over the detour) x its seconds: what staying would have made
    more, negative when the detour gathered faster."""
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["field"], r["kind"])].append(r)
    print(f"{'field':13}{'kind':19}{'chases':>7}{'detour s':>9}{'before/s':>10}{'during/s':>10}"
          f"{'lost a chase (95% CI)':>27}{'collected':>10}{'haste':>6}{'x colour':>9}{'dropped':>8}")
    for (f, k), rs in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), -len(kv[1]))):
        both = [r for r in rs if r.get("before") is not None and r.get("during") is not None]
        lost = mean_ci([(r["before"] - r["during"]) * r["seconds"] for r in both])
        colour = tokenbrain.colour_factor(k, f, hive)
        dropped = sum(r["score"] * colour < tokenbrain.MOVEMENT_THRESHOLD for r in rs)
        print(f"{str(f):13}{k:19}{len(rs):7d}{st.mean(r['seconds'] for r in rs):9.2f}"
              f"{mean_ci([r['before'] for r in both])[0]:10,.0f}"
              f"{mean_ci([r['during'] for r in both])[0]:10,.0f}"
              f"{lost[0]:>9,.0f} ({lost[1]:,.0f}..{lost[2]:,.0f})".rjust(27)
              + f"{sum(r['verdict'] == 'collected' for r in rs):10d}"
              f"{sum(r['haste'] for r in rs):6d}{colour:9.2f}{dropped:8d}")


def trips_report(var: pathlib.Path, runs: list[int], rows: list[dict], hive: str) -> None:
    """Per trip (var/trips.jsonl, gathers over 60 s): pollen/s against the
    chases a minute at kinds x colour calls worthless there. A run whose
    trips and "left the hive" lines do not pair up one to one is skipped."""
    starts = collections.defaultdict(list)          # run -> [(field, t0)]
    for run in runs:
        path = var / "night" / f"run-{run}.log"
        if path.exists():
            for line in path.open(encoding="utf-8", errors="replace"):
                if (m := FIELD.search(line)) and m.group(1) and (t := CLOCK.match(line)):
                    sec = int(t.group(1)) * 3600 + int(t.group(2)) * 60 + int(t.group(3))
                    starts[run].append((m.group(1).replace(" ", "_"), sec))
    trips = collections.defaultdict(list)
    for line in (var / "trips.jsonl").open(encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("attempt") in runs and r.get("credited"):
            trips[r["attempt"]].append(r)
    points = collections.defaultdict(list)           # field -> [(x0/min, other/min, pollen/s)]
    for run, rs in trips.items():
        if len(rs) != len(starts[run]):
            continue
        bounds = [t0 for _, t0 in starts[run]] + [10 ** 9]
        for i, r in enumerate(rs):
            g = float(r.get("gather_seconds") or 0)
            if g < 60 or r["credited"] != starts[run][i][0]:
                continue
            mine = [c for c in rows if c["run"] == run and bounds[i] <= c["t0"] < bounds[i + 1]]
            zero = sum(tokenbrain.colour_factor(c["kind"], c["field"], hive) <= 0.0 for c in mine)
            points[r["credited"]].append((zero / g * 60, (len(mine) - zero) / g * 60,
                                          float(r.get("pollen") or 0) / g))
    print("\nper trip, by field: pollen/s against chases a minute (one slope each; "
          "the two kinds of chase rise together, so compare them)")
    for field, pts in sorted(points.items()):
        for name, j in (("x0-colour", 0), ("other", 1)):
            xy = [(p[j], p[2]) for p in pts]
            if len({x for x, _ in xy}) < 3:
                print(f"  {field:13}{name:10} {len(pts)} trip(s), no spread")
                continue
            rng, slopes = random.Random(1), []
            while len(slopes) < 2000:
                xs, ys = zip(*rng.choices(xy, k=len(xy)))
                if len(set(xs)) > 1:              # a resample of one x has no slope
                    slopes.append(st.linear_regression(xs, ys).slope)
            slopes.sort()
            fit = st.linear_regression(*zip(*xy))
            print(f"  {field:13}{name:10} {len(pts)} trips: {fit.intercept:,.0f} "
                  f"{fit.slope:+,.0f} a chase/min (95% CI {slopes[50]:+,.0f}..{slopes[1950]:+,.0f})")

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--var", type=pathlib.Path, default=pathlib.Path.home() / "Hivemind" / "var")
    ap.add_argument("--runs", type=runs_arg, default=runs_arg("1254-1258"))
    ap.add_argument("--hive", default="blue")
    args = ap.parse_args()
    rows = chases(args.var, args.runs)
    report(rows, args.hive)
    trips_report(args.var, args.runs, rows, args.hive)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Why token chases end "the chase never reached it", from the token school's
own lessons -- the numbers behind docs/pending/chase-analysis-2026-10-21.md.

    ./tools/analysis/chase_lessons.py [--var DIR] [--recent RUN]
    ./tools/analysis/chase_lessons.py --phantom       # school.phantom, replayed
    ./tools/analysis/chase_lessons.py --detour-cost   # tokenbrain LOSS_FRACTION
    ./tools/analysis/chase_lessons.py --value         # the shadow's skips, priced

--phantom replays brain/school.phantom over the lessons in time order: what
act/chase.PHANTOM_SUPPRESS_LIVE would have skipped, and how many of those
were reached and collected -- the data for turning it on.

Reads only var/school-coins/lessons.jsonl and var/trips.jsonl (no frames, no
run logs), so it runs anywhere the two files are copied. Read-only.

"Reached" is the school's own `arrived` (brain/school.judge writes NEVER when
it is false). Distance is from where the target was when the chase began to
ANCHOR, the same anchor scripts/token_payoff.py uses. token_payoff.py, which
reads the run logs, is the one that can split by Haste and by field.
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

# brain/school and brain/tokenbrain, from this checkout, for any --mode
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

ANCHOR = (960, 669)                      # act/chase.anchor_of on 1920x1080 (token_payoff.py)
NEVER = "the chase never reached it"     # brain/school.judge, arrived False
TRICKLE = "reached it, but a trickle"    # brain/school.judge, a honey lump the trickle hides
PX_BINS = (130, 250, 350, 450, 550, 650, 800, 2200)   # token_payoff.PX_BINS


def load(path: pathlib.Path) -> list[dict]:
    out = []
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "-"


def px_bucket(px: float) -> str:
    for b in PX_BINS:
        if px < b:
            return f"<{b}px"
    return f">={PX_BINS[-1]}px"


def table(title: str, rows: list[dict], key, order=None) -> None:
    groups = collections.defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    print(f"\n== {title}")
    print(f"{'bucket':>18} {'chases':>7} {'reached':>8} {'collected':>10} {'coll/reached':>12}")
    for k in (order or sorted(groups)):
        rs = groups.get(k, [])
        if not rs:
            continue
        n, reached = len(rs), sum(r["reached"] for r in rs)
        got = sum(r["outcome"] == "collected" for r in rs)
        print(f"{str(k):>18} {n:7d} {pct(reached, n):>8} {pct(got, n):>10} {pct(got, reached):>12}")


def phantom_report(lessons: list[dict]) -> None:
    """The time-ordered replay of brain/school.phantom (its own window and
    thresholds), then the fixed learn-before / apply-after split."""
    from hivemind.brain import school as sch
    win, cells = collections.deque(), collections.defaultdict(lambda: [0, 0])
    per = collections.defaultdict(lambda: [0, 0, 0, 0])     # era: chases, skipped, reached, collected
    for r in lessons:
        cell = (r["x"] // sch.PHANTOM_CELL_PX, r["y"] // sch.PHANTOM_CELL_PX)
        n, got = cells.get(cell, (0, 0))
        det = r.get("detector_confidence")
        flagged = (n >= sch.PHANTOM_MIN_CHASES and got / n < sch.PHANTOM_MAX_REACH
                   and not (det is not None and det >= sch.PHANTOM_CONFIDENCE))
        e = per[r["attempt"] // 50 * 50]
        e[0] += 1
        if flagged:
            e[1] += 1
            e[2] += r["reached"]
            e[3] += r["outcome"] == "collected"
        if r.get("confidence") != 1.0 or not sch.counts_for_phantom(
                r.get("evidence"), r.get("outcome")):
            continue
        win.append((cell, r["reached"]))
        cells[cell][0] += 1
        cells[cell][1] += r["reached"]
        if len(win) > sch.PHANTOM_WINDOW:
            old, was = win.popleft()
            cells[old][0] -= 1
            cells[old][1] -= was
    print(f"\n== phantom replay (school.phantom: window {sch.PHANTOM_WINDOW}, "
          f">= {sch.PHANTOM_MIN_CHASES} chases, < {sch.PHANTOM_MAX_REACH:.0%} reached)")
    print(f"{'runs':>8} {'chases':>7} {'skipped':>8} {'reached':>8} {'collected':>10}")
    for era, (n, k, rr, got) in sorted(per.items()):
        print(f"{era:>8} {n:7d} {k:8d} {rr:8d} {got:10d}")
    print("\n== a table learned on runs before T, applied from T (all-time cells)")
    px = sch.PHANTOM_CELL_PX
    for t in (900, 1000, 1050, 1100):
        table_ = collections.defaultdict(lambda: [0, 0])
        for r in lessons:
            if (r["attempt"] < t and r.get("confidence") == 1.0
                    and sch.counts_for_phantom(r.get("evidence"), r.get("outcome"))):
                c = table_[(r["x"] // px, r["y"] // px)]
                c[0] += 1
                c[1] += r["reached"]
        bad = {k for k, (n, g) in table_.items()
               if n >= sch.PHANTOM_MIN_CHASES and g / n < sch.PHANTOM_MAX_REACH}
        hit = [r for r in lessons if r["attempt"] >= t and (r["x"] // px, r["y"] // px) in bad]
        print(f"  T={t}: {len(bad)} cells, skips {len(hit)}, reached "
              f"{sum(r['reached'] for r in hit)}, collected "
              f"{sum(r['outcome'] == 'collected' for r in hit)}")
def detour_cost(lessons: list[dict]) -> int:
    """tokenbrain LOSS_FRACTION: 1 - median(rate_during / rate_before) over
    the chases that collected nothing (a token's lump would read as gathering),
    leaving out a chase that began within RATE_WINDOW_S of the one before."""
    from hivemind.brain import school as sch
    # rate_before is school's RATE_WINDOW_S window; a chase starting inside
    # that window after the last one has the last detour and pickup in it
    clean, prev = [], None
    for r in lessons:
        at = r.get("at")
        if not (prev is not None and at is not None and 0 <= at - prev < sch.RATE_WINDOW_S):
            clean.append(r)
        prev = at
    ratios = sorted(r["rate_during"] / r["rate_before"] for r in clean
                    if r.get("outcome") != "collected" and r.get("rate_during") is not None
                    and (r.get("rate_before") or 0) > 0 and r["rate_during"] >= 0)
    print(f"== detour cost: {len(ratios)} chases with both rates and nothing collected")
    if not ratios:
        print("  none yet: the lessons keep rate_before / rate_during since 2026-10-21")
        return 1
    q = lambda f: ratios[min(len(ratios) - 1, int(f * len(ratios)))]   # noqa: E731
    print(f"  during/before p25 {q(.25):.2f}  median {st.median(ratios):.2f}  p75 {q(.75):.2f}")
    print(f"  LOSS_FRACTION = {1 - st.median(ratios):.2f}  (tokenbrain seed 1.0)")
    return 0


WOULD = re.compile(r"token brain value would: (chase|skip) .*?gather ([\d,]+)/s")
CHASED = re.compile(r"token brain(?: \(second look\))?: chase \w+#\d+ at \((\d+), (\d+)\)")
EARNED = re.compile(r"(honey|pollen) rose ([\d,]+) in [\d.]+s against ([\d,]+) expected")


def value(lessons: list[dict], var: pathlib.Path) -> int:
    """What the chases the shadow would skip actually earned, against their
    seconds: each 'token brain value would:' line joined, through the chase line
    before it, to that chase's lesson (run, x, y)."""
    from hivemind.brain import tokenbrain as tb
    verdict = {}
    for run in sorted({r["attempt"] for r in lessons if isinstance(r.get("attempt"), int)}):
        log = var / "night" / f"run-{run}.log"
        if not log.exists():
            continue
        last = None
        for line in log.open(encoding="utf-8", errors="replace"):
            m = CHASED.search(line)
            if m:
                last = (run, int(m.group(1)), int(m.group(2)))
                continue
            w = WOULD.search(line)
            if w and last is not None:
                verdict[last] = (w.group(1), float(w.group(2).replace(",", "")))
            if "token brain" in line and "would:" not in line:
                last = None
    rows = collections.defaultdict(lambda: [0, 0, 0.0, 0.0, []])
    for r in lessons:
        v = verdict.get((r.get("attempt"), r["x"], r["y"]))
        if v is None:
            continue
        e = EARNED.search(str(r.get("evidence", "")))
        got = 0.0
        if e:
            got = max(0.0, float(e.group(2).replace(",", "")) - float(e.group(3).replace(",", "")))
            if e.group(1) == "pollen":
                got *= tb.HONEY_PER_POLLEN_SEED
        row = rows[v[0]]
        row[0] += 1
        row[1] += r.get("outcome") == "collected"
        row[2] += got
        row[3] += tb.detour_s(r["px"])
        row[4].append(v[1])
    print(f"== the shadow's verdicts on chases taken ({sum(r[0] for r in rows.values())} joined)")
    print(f"  {'would':>6} {'chases':>7} {'collected':>10} {'honey/s earned':>15} {'gather/s':>9}")
    for k, (n, got, honey, secs, gathers) in sorted(rows.items()):
        print(f"  {k:>6} {n:7d} {pct(got, n):>10} {honey / max(secs, 1e-9):15,.0f} "
              f"{st.median(gathers):9,.0f}")
    print("  a skip is right where honey/s earned < gather/s x LOSS_FRACTION (--detour-cost);"
          " honey hidden under the trickle and ability tokens earn 0 here")
    return 0 if rows else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--var", default=str(pathlib.Path.home() / "Hivemind" / "var"))
    ap.add_argument("--recent", type=int, default=1050,
                    help="first run of the 'recent' window (default 1050)")
    ap.add_argument("--phantom", action="store_true",
                    help="only the phantom-spot replay (brain/school.phantom)")
    ap.add_argument("--detour-cost", action="store_true",
                    help="only the pollen a detour costs (tokenbrain LOSS_FRACTION)")
    ap.add_argument("--value", action="store_true",
                    help="only the shadow value chooser's verdicts, priced from the lessons")
    args = ap.parse_args()
    var = pathlib.Path(args.var)

    lessons = load(var / "school-coins" / "lessons.jsonl")
    for r in lessons:
        r["px"] = math.hypot(r["x"] - ANCHOR[0], r["y"] - ANCHOR[1])
        r["reached"] = r.get("evidence") != NEVER
    if not lessons:
        print("no lessons")
        return 1
    if args.phantom:
        phantom_report(lessons)
        return 0
    if args.detour_cost:
        return detour_cost(lessons)
    if args.value:
        return value(lessons, var)
    n = len(lessons)
    missed = sum(not r["reached"] for r in lessons)
    print(f"lessons {n}, runs {min(r['attempt'] for r in lessons)}-"
          f"{max(r['attempt'] for r in lessons)}; never reached {missed} ({pct(missed, n)})")

    order = [f"<{b}px" for b in PX_BINS] + [f">={PX_BINS[-1]}px"]
    table("by distance at the start of the chase", lessons, lambda r: px_bucket(r["px"]), order)
    table("over time (runs, 50 at a time)", lessons,
          lambda r: r["attempt"] // 50 * 50)
    table("by kind", lessons, lambda r: r["kind"])

    mid = st.median(r["attempt"] for r in lessons)
    print(f"\n== reached by distance, runs before / from the median run {mid:.0f}")
    for name, rs in (("early", [r for r in lessons if r["attempt"] < mid]),
                     ("late", [r for r in lessons if r["attempt"] >= mid])):
        cells = []
        for lo, hi in zip((0,) + PX_BINS[:-1], PX_BINS):
            b = [r for r in rs if lo <= r["px"] < hi]
            cells.append(f"<{hi}:{pct(sum(r['reached'] for r in b), len(b))}({len(b)})")
        print(f"  {name:>5}: " + "  ".join(cells))

    print("\n== phantom spots: 40 px cells with the most never-reached starts")
    cells = collections.defaultdict(list)
    for r in lessons:
        cells[(r["x"] // 40 * 40, r["y"] // 40 * 40)].append(r)
    worst = sorted(cells.items(), key=lambda kv: -sum(not r["reached"] for r in kv[1]))[:10]
    for (cx, cy), rs in worst:
        m = sum(not r["reached"] for r in rs)
        runs = sorted({r["attempt"] for r in rs})
        print(f"  x{cx:4d} y{cy:4d}: {len(rs):5d} chases, {m:5d} missed, reached "
              f"{pct(len(rs) - m, len(rs))}, runs {runs[0]}-{runs[-1]} ({len(runs)} runs)")

    recent = [r for r in lessons if r["attempt"] >= args.recent]
    rmiss = [r for r in recent if not r["reached"]]
    print(f"\n== runs >= {args.recent}: {len(recent)} chases, never reached {len(rmiss)} "
          f"({pct(len(rmiss), len(recent))})")
    for lo, hi in ((0, 350), (350, 450), (450, 550), (550, 650), (650, 800), (800, 2200)):
        b = [r for r in recent if lo <= r["px"] < hi]
        print(f"  {lo:>4}-{hi}px: {len(b):5d} chases, reached "
              f"{pct(sum(r['reached'] for r in b), len(b))}, "
              f"share of the misses {pct(sum(not r['reached'] for r in b), len(rmiss))}")
    print("  after reaching, (kind, outcome):")
    for k, v in collections.Counter((r["kind"], r["outcome"])
                                    for r in recent if r["reached"]).most_common():
        print(f"  {v:6d} {k}")
    hidden = sum(str(r.get("evidence", "")).startswith(TRICKLE) for r in lessons)
    print(f"  all runs: {hidden} reached chases ended '{TRICKLE} ...'")

    trips = [t for t in load(var / "trips.jsonl") if isinstance(t.get("attempt"), int)]
    per = collections.defaultdict(lambda: [0, 0.0, 0, 0])
    for t in trips:
        if t["attempt"] < args.recent:
            continue
        s = per[t.get("credited") or "?"]
        s[0] += 1
        s[1] += t.get("gather_seconds") or 0
        s[2] += t.get("tokens") or 0
        s[3] += t.get("blind_looks") or 0
    print(f"\n== trips, runs >= {args.recent}: blind token looks (screenstate.world_blind) by field")
    print(f"  {'field':>14} {'trips':>6} {'gather h':>9} {'tok/min':>8} {'blind':>7} {'blind/min':>10}")
    for f, (k, sec, tok, blind) in sorted(per.items(), key=lambda kv: -kv[1][1])[:10]:
        mins = max(sec / 60, 1e-9)
        print(f"  {str(f):>14} {k:6d} {sec / 3600:9.1f} {tok / mins:8.2f} {blind:7d} {blind / mins:10.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

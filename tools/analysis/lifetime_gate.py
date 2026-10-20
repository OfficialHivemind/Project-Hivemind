#!/usr/bin/env python3
"""Would tokenbrain's LIFETIME_GATE_LIVE drop real pickups? Re-scored from the
run logs' own "token brain would: skip" lines.

    ./tools/analysis/lifetime_gate.py var/night/run-1249.log ... [--factor F ...]

Each skip line is followed in the log by what the live chase did anyway:
"chased a ... walked onto it" (it reached the spot) and "school: ... —
collected" (the HUD confirmed a pickup). A skip of a chase that did either is
a real pickup the gate would have dropped. The "gone before we get there"
skips are re-scored at each --factor x the kind's `life_s` (the line carries
the track age, the walk and the life); "honey leash" skips (a rule removed
2026-10-27) count as dropped by nothing. Read-only.
"""
from __future__ import annotations

import argparse
import re

SKIP = re.compile(r"token brain would: skip (\w+)#\d+ at \(\d+, \d+\) — (.*)")
# old lines "... walk > 4s on the field)", new ones "... walk > 8s, 2 x 4s on the field)"
GONE = re.compile(r"\(([\d.]+)s old \+ ([\d.]+)s walk > (\d+)s(?:, [\d.]+ x (\d+)s)? on the field")
DECISION = ("token brain: ", "token brain (second look): ")
CHASED = re.compile(r"chased a .* — \d+ step\(s\), (.*)")
COLLECTED = re.compile(r"  school: \w+ at \(\d+, \d+\) — collected")


def skips(paths):
    """One dict per would-skip line: kind, rule, age/walk/life, walked, hud."""
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        for i, line in enumerate(lines):
            m = SKIP.search(line)
            if not m:
                continue
            g = GONE.search(m.group(2))
            row = {"kind": m.group(1), "rule": "gone" if g else "leash" if "leash" in m.group(2) else "?",
                   "walked": False, "hud": False, "missed": False}
            if g:
                row.update(age=float(g.group(1)), walk=float(g.group(2)),
                           life=float(g.group(4) or g.group(3)))
            said = False
            for after in lines[i + 1:i + 40]:
                if any(d in after for d in DECISION):
                    break
                c = CHASED.search(after)
                if c and not said:
                    said = True
                    row["walked"] = "walked onto it" in c.group(1)
                    row["missed"] = not row["walked"]
                if COLLECTED.search(after):
                    row["hud"] = True
            yield row


def tally(rows) -> str:
    rows = list(rows)
    return (f"{len(rows):4d} skips: walked onto {sum(r['walked'] for r in rows):4d}, "
            f"HUD-confirmed {sum(r['hud'] for r in rows):3d}, missed {sum(r['missed'] for r in rows):3d}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--factor", type=float, action="append",
                    help="x life_s to re-score at (default: 1 and 2, tokenbrain.TRACK_LIFE_FACTOR)")
    args = ap.parse_args()
    rows = list(skips(args.logs))
    gone = [r for r in rows if r["rule"] == "gone"]
    print(f"as logged, every rule: {tally(rows)}")
    print(f"  honey leash (removed): {tally(r for r in rows if r['rule'] == 'leash')}")
    print(f"  gone before we get there: {tally(gone)}")
    for f in args.factor or [1.0, 2.0]:
        print(f"  gone, re-scored at {f:g} x life_s: "
              f"{tally(r for r in gone if r['age'] + r['walk'] > f * r['life'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

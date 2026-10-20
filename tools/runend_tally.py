#!/usr/bin/env python3
"""How the runs ended, per day: the `RUN END: <category>: <detail>` lines
(telemetry/runend) counted by category for each day a run log ended.

    runend_tally.py                  var/night of this checkout, every day
    runend_tally.py --days 7         the last 7 days
    runend_tally.py --night DIR      another night folder (the live one)

A run log's day is the day it was last written (when the run ended). Logs
from before the RUN END line existed are counted as "(no RUN END line)".
Read-only.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hivemind.telemetry.runend import PREFIX  # noqa: E402

NONE = "(no RUN END line)"


def category(log: Path) -> str:
    """The category of the last RUN END line in a log, or NONE."""
    found = NONE
    with open(log, encoding="utf-8", errors="replace") as fh:
        for text in fh:
            if text.startswith(PREFIX):
                found = text[len(PREFIX):].split(": ", 1)[0].strip()
    return found


def tally(logs, day=lambda p: time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))):
    """{day: Counter(category)} over run logs."""
    days: dict[str, Counter] = defaultdict(Counter)
    for log in logs:
        days[day(log)][category(log)] += 1
    return dict(days)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--night", type=Path, default=ROOT / "var" / "night")
    ap.add_argument("--days", type=int, default=0, help="only the last N days (0: all)")
    args = ap.parse_args(argv)
    since = time.time() - args.days * 86400 if args.days else 0
    logs = [p for p in args.night.glob("run-*.log")
            if re.fullmatch(r"run-\d+\.log", p.name) and p.stat().st_mtime >= since]
    days = tally(logs)
    if not days:
        print(f"no run logs in {args.night}")
        return 0
    for d in sorted(days):
        counts = days[d]
        print(f"{d}  {sum(counts.values()):3d} run(s): "
              + ", ".join(f"{n} {c}" for c, n in counts.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

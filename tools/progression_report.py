#!/usr/bin/env python3
"""The progression proof as a markdown report, frames linked
(docs/pending/progression-proof.md).

    progression_report.py                       var/progression/milestones.jsonl, printed
    progression_report.py --var ~/Hivemind/var --out proof.md
    progression_report.py --backfill --var ~/Hivemind/var --out audit.md

The default reads the rows the bot keeps (telemetry/milestones): per day,
each milestone with how the bot knows it, PROVEN/LIKELY, and its frame.

--backfill rebuilds the same rows from the OLD run logs (var/night/run-*.log)
with the same patterns, for the time before the recorder existed. Each row
is a line the bot itself printed, so the bot was running and said it did
it; its frame is one the line names, else the nearest kept frame in the
folders the act kept them in (FRAME_DIRS) within FRAME_WINDOW_S. A row with
no frame is LIKELY. Purchases var/purchases.json says the owner made by hand
are listed apart: they are not the bot's. Honey per day is the ledger's
(var/trips.jsonl).

Read-only: it writes only --out.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hivemind.telemetry import milestones as ms  # noqa: E402

# WHERE EACH KIND'S ACT KEPT ITS FRAMES, named <YYYYmmdd-HHMMSS>... (MEASURED
# 2026-10-26 in ~/Hivemind/var: shoplook 7,495 files -- buys, hatches, jelly
# rolls, Blender crafts; beemenu page folders; badges page folders;
# quest_reads "scroll-<stamp>" folders).
FRAME_DIRS = {"bought": ("shoplook",), "hatched": ("shoplook",), "jelly": ("shoplook",),
              "crafted": ("shoplook",), "badge": ("badges",), "bees": ("beemenu",),
              "quest": ("quest_reads", "bear")}
# ponytail: 10 min either side, preferring the frames after the line; a busy
# shoplook folder can hand a neighbouring act's frame -- the report prints the
# frame's name so a person sees which act it was
FRAME_WINDOW_S = 600.0
STAMP = re.compile(r"(\d{8})-(\d{6})")
HIVE_LINE = re.compile(r"^the hive: (\d+) bees")


def stamps(var_root: Path, sub: str) -> list:
    """[(timestamp, path)] for every file or folder in var/<sub> named by a stamp."""
    out = []
    try:
        names = os.listdir(var_root / sub)
    except OSError:
        return out
    for name in names:
        m = STAMP.search(name)
        if m:
            try:
                at = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").timestamp()
            except ValueError:
                continue
            out.append((at, str(var_root / sub / name)))
    return sorted(out)


def nearest(index: list, at: float) -> str:
    """The frame closest after `at` (or before, when none after) within the window."""
    after = [p for t, p in index if 0 <= t - at <= FRAME_WINDOW_S]
    if after:
        return after[0]
    before = [p for t, p in index if 0 <= at - t <= FRAME_WINDOW_S]
    return before[-1] if before else ""


def backfill(var_root: Path) -> list:
    """Rows rebuilt from the run logs, oldest first."""
    index = {sub: stamps(var_root, sub) for subs in FRAME_DIRS.values() for sub in subs}
    out, bees_max, once = [], 0, set()
    logs = sorted((var_root / "night").glob("run-*.log"), key=lambda p: p.stat().st_mtime)
    lines = sorted((at, text, log.name) for log in logs for at, text in ms.dated_lines(log))
    for at, text, log in lines:
        got = ms.match(text)
        if got is None:
            hive = HIVE_LINE.match(text)
            if not hive or int(hive.group(1)) <= bees_max:
                continue
            before, bees_max = bees_max, int(hive.group(1))
            got = ("bees", f"{before} -> {bees_max} bees" if before else f"{bees_max} bees "
                   "(first count in the logs)", "the hive's count, read by the bot")
        kind, what, how = got
        if kind in ms.ONCE_KINDS:
            if what in once:
                continue
            once.add(what)
        frame = ms.frame_in(text)
        if not frame:
            for sub in FRAME_DIRS.get(kind, ()):
                frame = nearest(index[sub], at)
                if frame:
                    break
        proof = "proven" if frame and kind not in ms.LIKELY_KINDS else "likely"
        out.append({"at": at, "kind": kind, "what": what, "how": how, "line": text,
                    "frame": frame, "proof": proof, "log": log})
    return out


def by_hand(var_root: Path) -> list:
    """var/purchases.json rows the owner made himself (its reason says so)."""
    try:
        got = json.loads((var_root / "purchases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in got if isinstance(r, dict) and r.get("ok")
            and "by the owner" in str(r.get("reason") or "")]


def honey_by_day(var_root: Path) -> dict:
    """{day: [trips, running hours, honey/h, ledger honey]} from var/trips.jsonl.
    honey/h is the benchmark's (scripts/benchmark.units: the HUD balance's
    rise between trusted readings of one run, spends left out) -- the number
    the owner's scorecard uses. The ledger's per-trip honey is a FLOOR only:
    MEASURED 2026-10-26, 1,889 of its 3,752 trips have no honey read."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("hivemind_benchmark",
                                                  ROOT / "scripts" / "benchmark.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    trips = bench.load_trips(var_root, 0.0, 1e12)
    out = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0])
    for row, unit in zip(trips, bench.units(trips)):
        d = out[ms.day_of(unit["at"])]
        d[0] += 1
        d[1] += unit["wall"] / 3600.0
        d[2] += unit["hgain"]
        d[3] += unit["hdt"]
        d[4] += int(row.get("honey") or 0)
    return {day: [n, hours, (gain * 3600.0 / dt if dt > 0 else None), floor]
            for day, (n, hours, gain, dt, floor) in out.items()}


def link(path: str) -> str:
    return f"[{Path(path).name}](file://{path})" if path else "no frame"


def report(rows: list, var_root: Path, title: str) -> str:
    out = [f"# {title}", "", f"From `{var_root}`, {datetime.now():%Y-%m-%d %H:%M}. "
           "PROVEN = the bot's own result line and a frame; LIKELY = the line alone, "
           "or an inference (a quest hand-in is a dialogue read).", ""]
    kinds = defaultdict(lambda: [0, 0])
    for r in rows:
        kinds[r["kind"]][0] += 1
        kinds[r["kind"]][1] += r.get("proof") == "proven"
    out += ["| kind | rows | proven |", "|---|---|---|"]
    out += [f"| {k} | {n} | {p} |" for k, (n, p) in sorted(kinds.items())]
    days = honey_by_day(var_root)
    if days:
        out += ["", "## Honey per day (var/trips.jsonl)", "",
                "honey/h is the benchmark's (the HUD's rise, spends left out); honey/day "
                "is that rate times the hours the bot ran; the ledger's own sum is a "
                "floor (half its trips carry no honey read).", "",
                "| day | trips | hours running | honey/h | honey/day (rate x hours) | ledger floor |",
                "|---|---|---|---|---|---|"]
        for day, (trips, hours, rate, floor) in sorted(days.items()):
            out.append(f"| {day} | {trips} | {hours:.1f} | "
                       + (f"{rate / 1e6:.1f}M | {rate * hours / 1e6:,.0f}M" if rate
                          else "? | ?") + f" | {floor / 1e6:,.0f}M |")
    hand = by_hand(var_root)
    if hand:
        out += ["", "## Not the bot's (bought by the owner by hand, var/purchases.json)", ""]
        out += [f"- {datetime.fromtimestamp(r['at']):%Y-%m-%d %H:%M} {r.get('item')}: "
                f"{r.get('reason')}" for r in hand]
    by_day = defaultdict(list)
    for r in rows:
        by_day[ms.day_of(r["at"])].append(r)
    for day in sorted(by_day):
        out += ["", f"## {day}", "", "| time | kind | what | proof | frame | how / line |",
                "|---|---|---|---|---|---|"]
        for r in by_day[day]:
            line = str(r.get("line") or "").replace("|", "/")[:160]
            where = f" ({r['log']})" if r.get("log") else ""
            out.append(f"| {datetime.fromtimestamp(r['at']):%H:%M:%S} | {r['kind']} | "
                       f"{str(r['what']).replace('|', '/')} | {r.get('proof', '?').upper()} | "
                       f"{link(r.get('frame') or '')} | {r.get('how', '')}{where}: `{line}` |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--var", default=str(ROOT / "var"))
    ap.add_argument("--backfill", action="store_true",
                    help="rebuild the rows from the run logs instead")
    ap.add_argument("--kinds", default="", help="comma-separated kinds to keep (default all)")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    var_root = Path(os.path.expanduser(args.var))
    rows = backfill(var_root) if args.backfill else ms.rows(var_root)
    if args.kinds:
        keep = set(args.kinds.split(","))
        rows = [r for r in rows if r["kind"] in keep]
    text = report(rows, var_root, "Progression audit (from the run logs)" if args.backfill
                  else "Progression proof")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

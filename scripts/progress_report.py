#!/usr/bin/env python3
"""The day's progress in plain English: what was earned, bought, handed in,
what went wrong, and what I'd buy next and why.

THE OWNER, 2026-10-20: progress felt slow. This says what the
progress was, from what the bot recorded, read-only over var/ -- it clicks,
buys and sends nothing (--telegram-text only PRINTS the short version):

  * honey earned: every rise of the confirmed balance (goals.balance_readings,
    the rule brain/goals and night_report use); a fall -- a purchase, the
    owner's or the bot's -- is spent, not lost, and never subtracted;
  * honey/h against the 7 days before (scripts/benchmark: its units/summary);
  * purchases (var/purchases.json, var/owned.json), quest hand-ins and
    finished quests (the run logs), the quest menu now (var/quests.json), the
    hive (var/bees.json), the field mix, rejoins/deaths/crashes;
  * the payback ranking's top 3 (brain/roi).

    ~/Hivemind/.venv/bin/python scripts/progress_report.py [--hours 24] [--telegram-text] [--var DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import benchmark as bm  # noqa: E402
from hivemind.brain import goals as goals_mod  # noqa: E402

WEEK = 7 * 86400.0
GIVER = re.compile(r"a dialogue was read at the ([A-Z][A-Za-z ]*?)(?:,| so|$)")
FINISHED = re.compile(r"hand-in queue: [^:]+: '([^']+)' shows finished")
CRASH = re.compile(r"^Traceback")


def _json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _hm(t: float) -> str:
    return time.strftime("%d %b %H:%M", time.localtime(t))


short = bm._short


def honey_moves(rows, since: float, until: float) -> dict:
    """{earned, spent, first, last, readings} from the confirmed converts in
    the window, plus the one before it so the first rise counts."""
    got = goals_mod.balance_readings(rows)
    inside = [r for r in got if since <= r[0] <= until]
    before = [r for r in got if r[0] < since][-1:]
    seq = before + inside
    earned = sum(max(0, b - a) for (_x, a), (_y, b) in zip(seq, seq[1:]))
    spent = sum(max(0, a - b) for (_x, a), (_y, b) in zip(seq, seq[1:]))
    return {"earned": earned, "spent": spent, "readings": len(inside),
            "first": seq[0][1] if seq else None, "last": seq[-1][1] if seq else None}


def log_lines(var: Path, all_runs, since: float, until: float):
    for _s, _e, lines in bm.run_lines(var, all_runs, since, until):
        for t, raw in lines:
            if since <= t < until:
                yield t, raw


def report(var: Path, now: float, hours: float = 24.0, ranking=None) -> dict:
    """Everything the text says, as data. `ranking`: brain/roi's Ranking."""
    since = now - hours * 3600
    rows = bm.load_trips(var, since - WEEK, now)
    all_runs = bm.runs(var, now)
    events = bm.log_events(var, all_runs, since - WEEK, now)
    us = bm.units(rows, events)
    pick = lambda a, b: [u for u in us if a <= u["at"] < b]  # noqa: E731
    mine = pick(since, now)
    day = bm.summary(mine, since, now, all_runs, events)
    week = bm.summary(pick(since - WEEK, since), since - WEEK, since, all_runs, events)
    out = {"since": since, "now": now, "hours": hours, "day": day,
           "week_rate": week.get("honey_per_hour"),
           "honey": honey_moves(rows, since, now),
           "deaths": int(sum(u["deaths"] for u in mine))}
    # PURCHASES: the bot's own (purchases.json) and what owned.json recorded
    buys = [b for b in _json(var / "purchases.json", []) if isinstance(b, dict)
            and since <= float(b.get("at") or 0) < now]
    out["bought"] = [f"{b.get('item')} ({b.get('price'):,} {str(b.get('currency') or '').lower()})"
                     for b in buys if b.get("ok")]
    out["buy_fails"] = sum(1 for b in buys if not b.get("ok"))
    owned = _json(var / "owned.json", {})
    out["owned_new"] = [f"{k.replace('_', ' ')} ({v.get('state')})"
                        for k, v in (owned.get("items") or {}).items()
                        if isinstance(v, dict) and since <= float(v.get("at") or 0) < now]
    drops = [d for d in owned.get("drops") or [] if since <= float(d.get("after_at") or 0) < now]
    out["unexplained"] = [int(d.get("amount") or 0) for d in drops if d.get("verdict") == "no match"]
    # QUESTS, from the run logs and the last menu read
    givers, finished, crashes = [], [], 0
    for _t, raw in log_lines(var, all_runs, since, now):
        m = GIVER.search(raw)
        if m:
            givers.append(m.group(1).strip())
        m = FINISHED.search(raw)
        if m and m.group(1) not in finished:
            finished.append(m.group(1))
        crashes += bool(CRASH.match(raw.strip()))
    out["handins"], out["finished"], out["crashes"] = givers, finished, crashes
    q = _json(var / "quests.json", {})
    out["quests_now"] = [x.get("name") for x in q.get("quests") or [] if isinstance(x, dict)]
    out["quests_read"] = float(q.get("read_at") or 0) or None
    bees = _json(var / "bees.json", {})
    out["bees"] = bees.get("total")
    out["gifted"] = len(bees.get("gifted") or [])
    out["bees_read"] = float(bees.get("read_at") or 0) or None
    out["attempts"] = sum(1 for s, _e, _n in all_runs if since <= s < now)
    out["ranking"] = ranking
    return out


def text(d: dict, telegram: bool = False) -> str:
    day, h = d["day"], d["honey"]
    lines = [f"Progress, last {d['hours']:g} h (to {_hm(d['now'])})"]
    if h["readings"]:
        lines.append(f"• Honey earned: +{short(h['earned'])}"
                     + (f" ({short(h['spent'])} spent (purchases), not counted as a loss)"
                        if h["spent"] else "")
                     + f"; balance now {short(h['last'])}")
    else:
        lines.append("• Honey earned: no confirmed convert in this window")
    rate, wk = day.get("honey_per_hour"), d["week_rate"]
    if rate is not None:
        vs = (f" vs {short(wk)}/h the 7 days before ({100 * (rate / wk - 1):+.0f}%)"
              if wk else " (no 7-day figure to compare)")
        lines.append(f"• Honey/h: {short(rate)}{vs}; running {day['running_hours']:.1f} h"
                     + (f" ({day['uptime_pct']:.0f}% uptime)" if day.get("uptime_pct") is not None else ""))
    bought = d["bought"] + [f"{o} — owned" for o in d["owned_new"]]
    lines.append("• Bought: " + (", ".join(bought) if bought else "nothing")
                 + (f" ({d['buy_fails']} tries that did not go through)" if d["buy_fails"] else "")
                 + (f"; {len(d['unexplained'])} honey drop(s) nothing explains "
                    f"({short(sum(d['unexplained']))})" if d["unexplained"] else ""))
    if d["handins"]:
        counts: dict = {}
        for g in d["handins"]:
            counts[g] = counts.get(g, 0) + 1
        lines.append(f"• Quests: {len(d['handins'])} hand-ins ("
                     + ", ".join(f"{g} x{n}" for g, n in counts.items()) + ")"
                     + (f"; finished: {', '.join(d['finished'])}" if d["finished"] else ""))
    else:
        lines.append("• Quests: no hand-ins" + (f"; finished: {', '.join(d['finished'])}"
                                                 if d["finished"] else ""))
    if d["quests_now"]:
        shown = d["quests_now"][:4 if telegram else 20]
        more = len(d["quests_now"]) - len(shown)
        lines.append(f"• Quest menu ({_hm(d['quests_read'])}): " + ", ".join(shown)
                     + (f" and {more} more" if more > 0 else ""))
    if d["bees"]:
        lines.append(f"• Hive: {d['bees']} bees, {d['gifted']} gifted types in it"
                     + (f" (read {_hm(d['bees_read'])})" if d["bees_read"] else ""))
    fields = day.get("fields") or {}
    total = sum(f["gather_min"] for f in fields.values()) or 0
    if total:
        lines.append("• Fields: " + ", ".join(f"{k.replace('_', ' ')} {100 * v['gather_min'] / total:.0f}%"
                                              for k, v in list(fields.items())[:4]))
    lines.append(f"• Trouble: {day.get('rejoins', 0)} rejoins, {d['deaths']} deaths, "
                 f"{d['crashes']} crashes; {d['attempts']} runs started")
    r = d.get("ranking")
    if r is not None:
        lines.append("What I'd buy next and why (payback = cost ÷ honey/h it adds):")
        lines += [f"  {i}. {o.brief()}" for i, o in enumerate(r.known[:3], 1)] \
            if telegram else [f"  {x}" for x in r.lines(3)]
        if not r.known:
            lines.append("  (nothing open has a gain estimate)")
        if r.why_differ:
            lines.append("  " + r.why_differ)
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--var", type=Path, default=ROOT / "var")
    ap.add_argument("--now", type=float)
    ap.add_argument("--telegram-text", action="store_true",
                    help="print the short version (sends nothing)")
    a = ap.parse_args(argv)
    try:
        from hivemind.brain import roi
        ranking = roi.from_files(a.var)
    except Exception as exc:                          # noqa: BLE001
        print(f"(no payback ranking: {exc})", file=sys.stderr)
        ranking = None
    print(text(report(a.var, a.now or time.time(), a.hours, ranking), a.telegram_text))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The week-long live test in one table: per feature, how many lines prove it
ran, pass/fail where a number can judge it, the top problems, and the frames
a person should eye-check for the look-only lines. Read-only.

    week_check.py                                  the last 24 h of var/
    week_check.py --var ~/Hivemind/var --hours 72
    week_check.py --var ~/Hivemind/var --since "2026-10-27"

Reads var/night/attempts.log (which run log covers which time), streams each
run log line by line, and streams var/trips.jsonl (honey/h, as
scripts/benchmark.py measures it). Landing uses scripts/landing_rate.py's own
walk verdicts; look-only flags and their log text come from
tools/lookonly_report.py. The checklist this backs (log lines, criteria,
status) is kept outside the repo.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("src", "scripts", "tools"):
    sys.path.insert(0, str(ROOT / sub))
import benchmark as bm  # noqa: E402
import landing_rate as lr  # noqa: E402
import lookonly_report as lo  # noqa: E402

# Pass criteria (each from the ROADMAP / docs/pending item named).
LANDING_TARGET = 98.0        # A6: walks home landed
REJOINS_PER_DAY = 1.0        # A7: under 1 a day
DEATHS_PER_DAY = 5.0         # A9 audit 5-19 Oct: 77 real deaths in 14 days (5.5/day)
HANDINS_PER_DAY = 3.0        # test window 20 Oct: 3 quests a day
HONEY_BASELINE = 132e6       # test window 20 Oct: 132M honey/h
ANT_ROUND = 10               # q2-ants: median last round > 10 with ANT_KITE live

# (group, feature, regex on the line's text). The live lines each feature's
# docs/pending "live check" names, as they appear in the run logs.
FEATURES = [
    ("gathering", "trips (cycle N:)", r"^cycle \d+:"),
    ("gathering", "convert pressed E", r"^convert: pressed E on the pad"),
    ("gathering", "sprinkler placed", r"^sprinkler: placed"),
    ("gathering", "off-field gather end", r"^the gather ended because the pollen stopped rising"),
    ("gathering", "self-review", r"^self-review: "),
    ("tokens/AI", "ai mode line", r"^ai mode: This PC"),
    ("tokens/AI", "OpenCV threads", r"^cpu: screen reads on \d+ OpenCV"),
    ("tokens/AI", "coin net on cv2.dnn", r"^coin network: on cv2\.dnn"),
    ("tokens/AI", "live view fps", r"^live view: \d+ frames"),
    ("tokens/AI", "token chases", r"^(token brain: chase|chasing a )"),
    ("tokens/AI", "typed tokens (school)", r"^school: \w+ at"),
    ("tokens/AI", "own token table", r"YOUR token table"),
    ("walk home", "arrived", r"^to hive: arrived"),
    ("walk home", "did not get there", r"^to hive: did not get there"),
    ("walk home", "whirligig rescue", r"^whirligig rescue: on our pad"),
    ("walk home", "unseen-row skip (live)", r"skipped the search by sight: the gather ended off"),
    ("walk home", "pine lean", r"home align: leaning"),
    ("hive claim", "claim confirmed by E", r"claimed — confirmed by pressing E"),
    ("hive claim", "kept-session pad", r"^hive: ours from the kept session"),
    ("hive claim", "claim-miss backoff", r"before the next start: the claim missed"),
    ("quests", "quest menu read", r"^quest menu says:"),
    ("quests", "quests want", r"^quests want:"),
    ("quests", "hand-in (dialogue read)", r"a dialogue was read at the"),
    ("quests", "finished, waiting hand-in", r"^hand-in queue: .* still shows finished"),
    ("quests", "resume kept state", r"^resume: "),
    ("quests", "progress proof", r"^progress proof: "),
    ("planters", "planter used/placed", r"^planter: .* used one"),
    ("planters", "planter errand", r"^planter errand: "),
    ("planters", "planters shut-time", r"^planters: the game was shut"),
    ("bosses/mobs", "mob defeated (feed)", r"was defeated"),
    ("bosses/mobs", "Ant Challenge rounds", r"^Ant Challenge: round \d+"),
    ("bosses/mobs", "Ant Challenge games", r"^Ant Challenge: .*last read round"),
    ("bosses/mobs", "Ant kite step ended early", r"^Ant Challenge: the side-step ended"),
    ("bosses/mobs", "Vicious Bee", r"^Vicious Bee: "),
    ("economy", "payouts", r"^payout: "),
    ("economy", "Memory Match played", r"^Memory Match: the .* pair\(s\)"),
    ("economy", "buying", r"^buying \d+: "),
    ("economy", "rare drop", r"^rare drop: "),
    ("economy", "owned: decided", r"^owned: decided"),
    ("join/Sober", "in game", r"^in game after \d+s"),
    ("join/Sober", "rejoin asked", r"asking for a rejoin"),
    ("join/Sober", "disconnect", r"^disconnect: "),
    ("join/Sober", "network down/back", r"^network: (no internet|the internet is back)"),
    ("join/Sober", "Sober crashed", r"FAILED: Sober crashed"),
    ("join/Sober", "compositor lost", r"the nested compositor the game ran in has exited"),
    ("join/Sober", "stall watch", r"^stall watch: "),
    ("join/Sober", "died", r"^died: pollen fell(?!.*ending this)"),
    ("GUI/Telegram", "setting from Telegram", r"^setting from Telegram"),
    ("GUI/Telegram", "settings re-read", r"settings re-read"),
    ("GUI/Telegram", "GUI socket", r"^GUI socket: "),
    ("safety", "panic key armed", r"^panic key: watching"),
    ("safety", "memory check", r"^memory: [\d.]+ GB available"),
    ("safety", "stop requested", r"STOPPED: stop requested"),
]
_FEAT = [(g, n, re.compile(rx)) for g, n, rx in FEATURES]
_STAMP = re.compile(r"^\s+(\d\d):(\d\d):(\d\d)  (.*)$")
_FRAME = re.compile(r"\[kept ([^\]]+)\]|((?:/|\bvar/)[\w./-]+\.(?:png|jpe?g))")
_PROBLEM = re.compile(r"FAILED|did not get there|could not|refused|ERROR|stall watch:")
_EXC = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Interrupt|Exit)\b")
_AT = re.compile(r'"at":\s*([\d.]+)')
_SHORT = re.compile(r"\d[\d,.]*")
_ANT_END = re.compile(r"^Ant Challenge: .*last read round (\d+)")


def stream(path: Path, start: float):
    """(unix time, raw line) of one run log, read a line at a time; a line
    with no clock takes the last one seen. ponytail: a log reused by several
    attempts (Sept's run-001..) is timed from the first start only."""
    day = time.mktime(time.localtime(start)[:3] + (0, 0, 0, 0, 0, -1))
    last = start
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.rstrip("\n")
            m = _STAMP.match(raw)
            if m:
                t = day + int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                if t < last - 12 * 3600:                # past midnight
                    day += 86400
                    t += 86400
                last = t
            yield last, raw


class Tally:
    def __init__(self, looks: list, since: float, until: float):
        self.looks, self.since, self.until = looks, since, until
        self.hits, self.when = collections.Counter(), {}
        self.look_hits, self.look_when = collections.Counter(), {}
        self.frames = collections.defaultdict(lambda: collections.deque(maxlen=3))
        self.other, self.problems = collections.Counter(), collections.Counter()
        self.ends, self.tracebacks, self._tb = collections.Counter(), 0, False
        self.ant_rounds = []

    def tap(self, lines):
        """Pass lines through, counting the ones inside the window."""
        for t, raw in lines:
            if self.since <= t <= self.until:
                self.line(t, raw)
            yield t, raw

    def line(self, t: float, raw: str) -> None:
        m = _STAMP.match(raw)
        text = m.group(4) if m else raw.strip()
        for _g, name, rx in _FEAT:
            if rx.search(text):
                self.hits[name] += 1
                self.when[name] = t
        a = _ANT_END.match(text)
        if a:
            self.ant_rounds.append(int(a.group(1)))
        if text.startswith("RUN END: "):
            self.ends[text[9:].split(":", 1)[0]] += 1
        if "would" in text or "_LIVE" in text or "look-only" in text:
            seen = False
            for flag, texts in self.looks:
                if any(x in text for x in texts):
                    seen = True
                    self.look_hits[flag] += 1
                    self.look_when[flag] = t
                    for f in _FRAME.finditer(text):
                        self.frames[flag].append(f.group(1) or f.group(2))
            o = None if seen else lo.OTHER.search(text)
            if o:
                self.other[o.group(1)] += 1
        if "Traceback (most recent call last)" in text:
            self.tracebacks += 1
            self._tb = True
        elif self._tb and _EXC.match(text):
            self.problems["traceback: " + _SHORT.sub("N", text)[:90]] += 1
            self._tb = False
        elif _PROBLEM.search(text):
            self.problems[_SHORT.sub("N", text).split(" (")[0][:90]] += 1


def trips(var: Path, since: float, until: float) -> list:
    """trips.jsonl rows from 2 h before the window (honey readings pair up
    across it, as benchmark.load_trips), streamed."""
    out = []
    try:
        fh = open(var / "trips.jsonl", encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            m = _AT.search(line[:200])
            if not m or not since - 2 * bm.SAME_RUN_GAP <= float(m.group(1)) <= until:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return sorted(out, key=lambda r: r["at"])


def _frame_path(var: Path, ref: str) -> str:
    """A '[kept X]' name made a path: X itself, var/X or var/*/X."""
    p = Path(ref)
    if p.is_absolute():
        return str(p)
    for c in [var / ref, var.parent / ref, *var.glob(f"*/{ref}")]:
        if c.exists():
            return str(c)
    return ref + " (not found)"


def check(var: Path, since: float, until: float, looks: list | None = None) -> str:
    if looks is None:
        looks = [(f["name"], lo.texts(f["name"], f["comment"])) for f in lo.flags()]
    all_runs = bm.runs(var, until)
    tally, ws, names, first = Tally(looks, since, until), [], [], {}
    for start, end, name in all_runs:
        if end >= since and start <= until and name not in first:
            first[name] = start
    for name, start in first.items():
        names.append(name)
        path = var / "night" / name
        if path.exists():
            ws += [w for w in lr.walks(tally.tap(stream(path, start))) if since <= w["at"] <= until]
    us = [u for u in bm.units(trips(var, since, until)) if u["at"] >= since]
    s = bm.summary(us, since, until, all_runs)
    run_h = s["running_hours"] or 0.0
    per_day = lambda n: n * 24 / run_h if run_h else None         # noqa: E731

    def verdict(ok):
        return "  --" if ok is None else (" PASS" if ok else " FAIL")

    fmt = "%d %b %H:%M"
    out = [f"week check {time.strftime(fmt, time.localtime(since))} -> "
           f"{time.strftime(fmt, time.localtime(until))}: {len(names)} run log(s) "
           f"({', '.join(n[4:-4] for n in names[:1] + names[-1:]) if names else '-'}), "
           f"running {run_h:.1f} h, {s['trips']} trips", "",
           "AUTO CHECKS                    value                      target   verdict"]
    good, n, pct = lr.rate(ws)
    worst = sorted(((lr.rate([w for w in ws if w["field"] == f]), f)
                    for f in {w["field"] for w in ws}), key=lambda x: x[0][2] or 101.0)
    worst = [f"{f} {g}/{k}" for (g, k, p), f in worst if k and p is not None and p < 100][:2]
    out.append(f"  walk-home landing           {f'{good}/{n} = {pct:.1f}%' if n else 'no walks':<26} "
               f">={LANDING_TARGET:.0f}%  {verdict(None if not n else pct >= LANDING_TARGET)}"
               + (f"   worst: {', '.join(worst)}" if worst else ""))
    for label, count, limit, more in (
            ("rejoins", tally.hits["rejoin asked"], REJOINS_PER_DAY, False),
            ("deaths", tally.hits["died"], DEATHS_PER_DAY, False),
            ("quest hand-ins", tally.hits["hand-in (dialogue read)"], HANDINS_PER_DAY, True)):
        d = per_day(count)
        val = f"{count} ({d:.1f}/day run)" if d is not None else f"{count}"
        ok = None if d is None else (d >= limit if more else d < limit)
        out.append(f"  {label:<27} {val:<26} {'>=' if more else '<'}{limit:g}/day "
                   f"{verdict(ok)}")
    rs = sorted(tally.ant_rounds)
    med = rs[len(rs) // 2] if rs else None
    out.append(f"  {'Ant Challenge median round':<27} "
               f"{f'{med} over {len(rs)} game(s)' if rs else 'no games':<26} >{ANT_ROUND}     "
               f"{verdict(None if med is None else med > ANT_ROUND)}")
    hh = s.get("honey_per_hour")
    out.append(f"  {'honey/h (trips.jsonl)':<27} {f'{hh / 1e6:.1f}M' if hh else 'not measured':<26} "
               f">={HONEY_BASELINE / 1e6:.0f}M  {verdict(None if not hh else hh >= HONEY_BASELINE)}")
    if tally.ends:
        out.append("  RUN END: " + ", ".join(f"{k} {v}" for k, v in tally.ends.most_common()))
    out += ["", "FEATURES (lines seen in the window; -- = none)"]
    group = None
    for g, name, _rx in FEATURES:
        c = tally.hits[name]
        last = time.strftime("%a %H:%M", time.localtime(tally.when[name])) if c else ""
        out.append(f"  {g if g != group else '':<13} {name:<27} {c if c else '--':>6}  {last}")
        group = g
    seen = sorted(tally.look_hits, key=lambda f: -tally.look_hits[f])
    out += ["", f"LOOK-ONLY FLAGS: {len(seen)} of {len(looks)} logged in the window"]
    for f in seen:
        out.append(f"  {f:<36} {tally.look_hits[f]:>6}  "
                   f"{time.strftime('%a %H:%M', time.localtime(tally.look_when[f]))}")
    never = [f for f, _t in looks if f not in tally.look_hits]
    if never:
        out.append("  not seen: " + ", ".join(never))
    if tally.other:
        out.append("  other 'would:' lines: " + ", ".join(
            f"{k} {v}" for k, v in tally.other.most_common(5)))
    out += ["", f"TOP PROBLEMS ({tally.tracebacks} traceback(s))"]
    out += [f"  {v:>5} x {k}" for k, v in tally.problems.most_common(3)] or ["  none"]
    out += ["", "FRAMES TO EYE-CHECK (latest 3 per look-only flag)"]
    rows = [f"  {f}: {_frame_path(var, r)}" for f in seen for r in tally.frames[f]]
    out += rows or ["  none named in the window"]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--var", type=Path, default=ROOT / "var")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--since", help='"YYYY-MM-DD HH:MM" (overrides --hours)')
    a = ap.parse_args()
    until = time.time()
    since = (time.mktime(time.strptime(a.since, "%Y-%m-%d %H:%M")) if a.since
             else until - a.hours * 3600)
    print(check(a.var.expanduser(), since, until))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""The benchmark scorecard: does a change make the bot better, worse, or
nothing we can see? (master plan Part 4)

Read-only over var/: the trip ledger (trips.jsonl), the run logs and
attempts.log (uptime, rejoins, quest hand-ins), commando.json (captures),
blender.json (crafts), experiments.json, and the deploy history (the deploy
logs' "installing integ (SHA)" + their backup's timestamp; the repo's integ
reflog for a backup whose log was overwritten).

    nice -n 19 ./scripts/benchmark.py [--hours 72] [--before X] [--after Y]
                                      [--telegram-text | --time | --today] [--var DIR] [--out DIR]

X / Y: a deploy SHA (the first deploy that contained it), "YYYY-MM-DD HH:MM"
or a unix time. --before X alone splits at X; --after Y alone too. With
neither, every deploy in the baseline window is judged twice: ISOLATED (the
stretch since the deploy before vs the stretch to the deploy after) and
LOCAL (the same, each side stretched to its nearest MIN_TRIPS trips and
MIN_BLOCKS clock hours when it has fewer -- deploys 40 min apart leave the isolated sides a few trips each;
the local row says how many other deploys it mixes in).

WHAT EACH NUMBER IS. Per trip, summed per clock hour (the bootstrap unit):
  honey/h   the HUD balance's RISE between two trusted readings of the same
            run (the trip's context.honey at its decision and the convert's
            "honey settled at"), over those readings' time. A fall of more
            than owned.MATCH_TOLERANCE is a spend: that interval is left out,
            time and all. Readings no neighbour backs up are dropped
            (owned._trusted).
  pollen/h  pollen over running time (the time since the run's previous
            trip ended; the trip's own seconds for a run's first).
  success   a gather trip that was credited to the field it aimed at,
            converted, and did not die.
  landing   walk-home routes that landed, of those judged (unknown left out).
  deaths/h, rejoins/h ("asking for a rejoin" in the run log, joined to the
            next trip).
  mix pollen/s  the AFTER side's per-field pollen/s weighted by the BEFORE
            side's gather time per field (fields both sides gathered): the
            same field mix, so a better field choice does not pass for a
            better gather or the other way round.
Window-level counts (no interval): uptime % (attempts.log), quest hand-ins
("a dialogue was read at the"), Commando captures, Blender crafts.
TIME (--time, the card's "time" block): where every second of the baseline's
running time went -- gather, walks, convert, each kind of errand, waits,
recovery, restarts -- see time_account; "unknown" is its own slice.

THE VERDICT. 95% bootstrap interval of after - before (whole clock hours
of trips resampled with replacement on each side). It excludes zero ->
better/worse by the metric's direction; else "no detectable change". Fewer
than MIN_TRIPS trips or MIN_BLOCKS hours a side -> "too few trips", never a
verdict. A deploy whose after-window is worse on honey/h or landing at p < REGRESSION_P (stricter than the verdict's 5%: some
70 deploys x 2 metrics would give ~7 false alarms a run at 5%) is a
REGRESSION and printed loudly; neighbouring deploys whose local windows
overlap are ONE alarm (their effects cannot be told apart).

regression_check (ROADMAP P2, used by tools/rollback_watch.py) is the
stricter question "is the code since this deploy worse?": the same block
bootstrap on like-with-like trips only (no warm-up, no quest-forced field,
no trip a stop cut), with a minimum of data; see its comment block.
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hivemind.brain.owned import (MATCH_TOLERANCE, SETTLED, _ATTEMPT,  # noqa: E402
                                  _STAMP, _trusted)

WORK = Path.home() / ".cache" / "hivemind-work"
MIN_TRIPS = 15            # below this on either side: "too few trips"
BOOT = 1000
SAME_RUN_GAP = 3600.0     # a trip more than this after the run's last one starts its own clock
_EXITED = re.compile(r"attempt (\d+) exited -?\d+ after (\d+)s")
# any ref: "installing integ (SHA)", a branch, or a rollback's "installing <sha> (SHA)"
_INSTALL = re.compile(r"installing \S+ \(([0-9a-f]+)\)")
_BACKUP = re.compile(r"live-(\d{8}-\d{6})\.tgz")
EVENTS = {"rejoins": "asking for a rejoin", "handins": "a dialogue was read at the"}
# metric -> (higher is better, unit); the ones a regression is judged on
METRICS = {"honey_per_hour": (True, "/h"), "pollen_per_hour": (True, "/h"),
           "success_pct": (True, "%"), "landing_pct": (True, "%"),
           "deaths_per_hour": (False, "/h"), "rejoins_per_hour": (False, "/h")}
REGRESSION_ON = ("honey_per_hour", "landing_pct")
REGRESSION_P = 0.01
# The bootstrap resamples whole clock hours (_blocks), not trips. MEASURED on
# the 72 h to 14 Oct 20:30, local windows split every 30 min whether or not
# anything was deployed: the old trip bootstrap called honey/h worse or
# better at p < 0.01 on 18% of them (1% expected); hour blocks with 3 hours a
# side 23%, 6 hours 24%, 8 hours 13% -- but "worse" on 1 split of 116; the
# rest is "better", the account's own growth over the days.
# ponytail: hours next to each other are still alike (buffs, boosts, the
# owner's progress), so "better" over-fires; a placebo-calibrated threshold
# (the deploy's change against the same window's no-deploy splits) is the
# upgrade if a "better" verdict is ever acted on.
BLOCK_S = 3600.0
MIN_BLOCKS = 8            # fewer distinct hours a side: "too few trips" too
COLS = ("wall", "hgain", "hdt", "pollen", "gather_s", "deaths", "gather", "success",
        "home_landed", "home_judged", "rejoins")


# ---- loading ---------------------------------------------------------------
def load_trips(var: Path, since: float, until: float) -> list:
    out = []
    try:
        lines = (var / "trips.jsonl").read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
            if since - 2 * SAME_RUN_GAP <= float(row["at"]) <= until:
                out.append(row)
        except (ValueError, KeyError, TypeError):
            continue
    out.sort(key=lambda r: r["at"])
    return out


def runs(var: Path, now: float) -> list:
    """[(start, end, log name)] from attempts.log, oldest first."""
    out, open_ = [], {}
    try:
        lines = (var / "night" / "attempts.log").read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        m = _ATTEMPT.search(line)
        if m:
            t = time.mktime(time.strptime(m.group(2), "%Y-%m-%d %H:%M:%S"))
            open_[m.group(1)] = len(out)
            out.append([t, None, Path(m.group(3)).name])
            continue
        m = _EXITED.search(line)
        if m and m.group(1) in open_:
            run = out[open_.pop(m.group(1))]
            run[1] = run[0] + float(m.group(2))
    for i, run in enumerate(out):       # still going, or never logged its exit
        if run[1] is None:
            try:
                end = (var / "night" / run[2]).stat().st_mtime
            except OSError:
                end = run[0]
            nxt = out[i + 1][0] if i + 1 < len(out) else now
            run[1] = max(run[0], min(end, nxt, now))
    return out


def run_lines(var: Path, all_runs: list, since: float, until: float):
    """Yield (start, end, [(unix time, line)]) for each run overlapping the
    window. A log reused by a later attempt holds one "=== bootstrap ==="
    segment per start (the same pairing owned.history makes); a line with
    no clock of its own takes the last one seen."""
    by_log: dict = {}
    for start, end, name in all_runs:
        by_log.setdefault(name, []).append((start, end))
    for name, spans in by_log.items():
        if not any(s <= until and e >= since for s, e in spans):
            continue
        try:
            text = (var / "night" / name).read_text(errors="replace")
        except OSError:
            continue
        segs = text.split("=== bootstrap ===")
        if len(segs) > 1:
            segs = [segs[0] + segs[1]] + segs[2:]
        for (start, end), seg in zip(spans[-len(segs):], segs):
            if end < since or start > until:
                continue
            t0 = dt.datetime.fromtimestamp(start)
            day, last, lines = t0.replace(hour=0, minute=0, second=0, microsecond=0), start, []
            for raw in seg.splitlines():
                m = _STAMP.match(raw)
                if m:
                    t = (day + dt.timedelta(hours=int(m.group(1)), minutes=int(m.group(2)),
                                            seconds=int(m.group(3)))).timestamp()
                    if t < last - 12 * 3600:          # past midnight
                        day += dt.timedelta(days=1)
                        t += 86400
                    last = t
                lines.append((last, raw))
            yield start, end, lines


def log_events(var: Path, all_runs: list, since: float, until: float) -> dict:
    """{event: [unix times]} from the run logs of runs overlapping the window."""
    out = {k: [] for k in EVENTS}
    for _s, _e, lines in run_lines(var, all_runs, since, until):
        for t, raw in lines:
            for key, needle in EVENTS.items():
                if needle in raw:
                    out[key].append(t)
    return out


def _json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def captures(var: Path) -> list:
    return [float(t["at"]) for t in _json(var / "commando.json", {}).get("tries", [])
            if t.get("result") == "killed"]


def crafts(var: Path) -> list:
    """[(at, item, qty)]"""
    return [tuple(m) for m in _json(var / "blender.json", {}).get("made", [])]


# ---- deploys ---------------------------------------------------------------
def _git(*args, repo: Path = WORK / "repo") -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def deploys(var: Path, work: Path = WORK) -> list:
    """[(unix time, short sha)] oldest first. The backup the installer makes
    is the moment of the install; its log names the SHA. A backup whose log
    was overwritten (the logs are named by HHMM) takes integ at that time
    from the reflog."""
    stamp = {}
    for log in (var / "night").glob("deploy-*.log"):
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        sha, bak = _INSTALL.search(text), _BACKUP.search(text)
        if sha and bak:
            stamp[bak.group(1)] = sha.group(1)
    reflog = []
    for line in _git("reflog", "show", "integ", "--date=unix", "--format=%h %gd",
                     repo=work / "repo").splitlines():
        m = re.match(r"(\w+) integ@\{(\d+)\}", line)
        if m:
            reflog.append((int(m.group(2)), m.group(1)))
    reflog.sort()
    out = []
    for tgz in (work / "backups").glob("live-*.tgz"):
        key = _BACKUP.search(tgz.name).group(1)
        t = time.mktime(time.strptime(key, "%Y%m%d-%H%M%S"))
        sha = stamp.get(key)
        if sha is None:
            i = bisect.bisect_right(reflog, (t, "~")) - 1
            sha = reflog[i][1] if i >= 0 else None
        if sha:
            out.append((t, sha))
    return sorted(out)


def resolve(text: str, deps: list, work: Path = WORK) -> float:
    """A unix time, a local "YYYY-MM-DD HH:MM", or a SHA: the first deploy
    that was it or contained it."""
    if re.fullmatch(r"\d{9,}(\.\d*)?", text):      # not float(): "10179e8" is a SHA, not 1e12
        return float(text)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return time.mktime(time.strptime(text, fmt))
        except ValueError:
            pass
    for t, sha in deps:
        if sha.startswith(text) or text.startswith(sha):
            return t
    for t, sha in deps:
        r = subprocess.run(["git", "-C", str(work / "repo"), "merge-base", "--is-ancestor",
                            text, sha], capture_output=True)
        if r.returncode == 0:
            return t
    raise SystemExit(f"benchmark: {text!r} is no time and no deployed commit")


# ---- per-trip units --------------------------------------------------------
def units(trips: list, events: dict | None = None) -> list:
    """One dict of COLS (+ at, field) per trip; see the module doc."""
    events = events or {}
    readings, last_at, out = [], {}, []
    for r in trips:
        at, att = float(r["at"]), r.get("attempt")
        ctx = (r.get("context") or {}).get("honey")
        if isinstance(ctx, int) and ctx > 0:
            try:
                t0 = int(str(r.get("decision_id")).split("-")[1]) / 1000.0
            except (IndexError, ValueError):
                t0 = at - float(r.get("seconds") or 0)
            readings.append((t0, ctx, "goals", att))
        m = SETTLED.search(str(r.get("convert_note") or ""))
        if m:
            readings.append((at, int(m.group(1).replace(",", "")), "settled", att))
        prev = last_at.get(att)
        wall = at - prev if prev is not None and 0 < at - prev < SAME_RUN_GAP \
            else float(r.get("seconds") or 0)
        last_at[att] = at
        homes = [x.get("outcome") for x in r.get("routes") or [] if x.get("kind") == "home"]
        gather = r.get("action", "gather") == "gather"
        deaths = int(r.get("deaths") or 0)
        out.append({
            "at": at, "field": r.get("credited") if gather else None,
            "wall": wall, "hgain": 0.0, "hdt": 0.0,
            "pollen": float(r.get("pollen") or 0), "gather_s": float(r.get("gather_seconds") or 0),
            "deaths": deaths, "gather": int(gather),
            "success": int(gather and bool(r.get("converted")) and deaths == 0
                           and r.get("credited") is not None
                           and r.get("credited") == r.get("aimed_at")),
            "home_landed": sum(o == "landed" for o in homes),
            "home_judged": sum(o not in (None, "unknown") for o in homes),
            "rejoins": 0,
            # for regression_check's like-with-like (see steady)
            "since_join": (r.get("context") or {}).get("since_join_s")
            if isinstance(r.get("context"), dict) else None,
            "cut": "stop requested" in f"{r.get('reason') or ''} {r.get('gather_ended') or ''}",
            "quest_forced": _quest_forced(r)})
    ats = [u["at"] for u in out]
    readings.sort(key=lambda x: (x[0], x[2] != "settled"))
    good = _trusted(readings)
    for a, b in zip(good, good[1:]):
        if a[3] != b[3] or b[1] - a[1] < -MATCH_TOLERANCE:
            continue                          # another run, or a spend
        i = bisect.bisect_left(ats, b[0] - 1e-6)
        if i < len(out):
            out[i]["hgain"] += max(0, b[1] - a[1])
            out[i]["hdt"] += b[0] - a[0]
    for t in events.get("rejoins", []):
        i = bisect.bisect_left(ats, t)
        if i < len(out):
            out[i]["rejoins"] += 1
    return out


def _quest_forced(r: dict) -> bool:
    """The planner took a quest's field ahead of a field it scored higher
    (quests.first): the field mix was the quest's, not the code's."""
    cs = r.get("candidates") if isinstance(r.get("candidates"), list) else []
    mine = [c for c in cs if isinstance(c, dict) and c.get("field") == r.get("chosen")]
    if not mine or "quests first" not in str(mine[0].get("why") or ""):
        return False
    return any((c.get("score") or 0) > (mine[0].get("score") or 0)
               for c in cs if isinstance(c, dict))


# ---- statistics ------------------------------------------------------------
def _ratio(num, den, scale=1.0):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / np.where(den > 0, den, 1) * scale, np.nan)


def _metrics(cols: dict, idx: np.ndarray) -> dict:
    s = {k: cols[k][idx].sum(axis=-1) for k in COLS}
    return {"honey_per_hour": _ratio(s["hgain"], s["hdt"], 3600),
            "pollen_per_hour": _ratio(s["pollen"], s["wall"], 3600),
            "success_pct": _ratio(s["success"], s["gather"], 100),
            "landing_pct": _ratio(s["home_landed"], s["home_judged"], 100),
            "deaths_per_hour": _ratio(s["deaths"], s["wall"], 3600),
            "rejoins_per_hour": _ratio(s["rejoins"], s["wall"], 3600)}


def _cols(us: list) -> dict:
    return {k: np.array([u[k] for u in us], dtype=float) for k in COLS}


def _blocks(us: list) -> list:
    """The trips summed per clock hour: the bootstrap's unit. Honey arrives
    in lumps (a dispenser's payout, a convert that settles after the next
    trip began) and neighbouring trips share the hour's buffs and server, so
    single trips are not independent draws; whole hours nearly are."""
    out: dict = {}
    for u in us:
        b = out.setdefault(int(u["at"] // BLOCK_S), {k: 0.0 for k in COLS} | {"fields": {}})
        for k in COLS:
            b[k] += u[k]
        if u["field"] and u["gather_s"] > 0:
            p, g = b["fields"].get(u["field"], (0.0, 0.0))
            b["fields"][u["field"]] = (p + u["pollen"], g + u["gather_s"])
    return [out[k] for k in sorted(out)]


def _field_rates(bs: list, fields: list, idx: np.ndarray) -> np.ndarray:
    """(..., F) pollen/s per field over the blocks `idx` picks."""
    pol = np.array([[b["fields"].get(f, (0.0, 0.0))[0] for f in fields] for b in bs])
    gs = np.array([[b["fields"].get(f, (0.0, 0.0))[1] for f in fields] for b in bs])
    return _ratio(pol[idx].sum(-2), gs[idx].sum(-2))


def summary(us: list, since: float, until: float, all_runs=(), events=None,
            caps=(), made=()) -> dict:
    """The point numbers of one window."""
    events = events or {}
    out = {"since": since, "until": until, "trips": len(us)}
    if us:
        point = _metrics(_cols(us), np.arange(len(us)))
        out.update({k: (None if np.isnan(v) else round(float(v), 3)) for k, v in point.items()})
    up = sum(max(0.0, min(e, until) - max(s, since)) for s, e, _ in all_runs)
    hours = max(1e-9, (until - since) / 3600)
    out["running_hours"] = round(up / 3600, 2)
    out["uptime_pct"] = round(100 * up / 3600 / hours, 1) if all_runs else None
    inside = lambda ts: [t for t in ts if since <= t < until]          # noqa: E731
    out["handins"] = len(inside(events.get("handins", [])))
    out["handins_per_day"] = round(out["handins"] / (up / 86400), 1) if up > 0 else None
    out["rejoins"] = len(inside(events.get("rejoins", [])))
    out["captures"] = len(inside(caps))
    made = [m for m in made if since <= m[0] < until]
    out["crafts"], out["crafted_items"] = len(made), int(sum(m[2] for m in made))
    rates = {}
    for u in us:
        if u["field"] and u["gather_s"] > 0:
            p, g = rates.get(u["field"], (0.0, 0.0))
            rates[u["field"]] = (p + u["pollen"], g + u["gather_s"])
    out["fields"] = {f: {"pollen_per_s": round(p / g, 1), "gather_min": round(g / 60, 1)}
                     for f, (p, g) in sorted(rates.items(), key=lambda kv: -kv[1][1])}
    return out


def compare(before: list, after: list, boot: int = BOOT, seed: int = 0) -> dict:
    """{metric: {before, after, diff, lo, hi, verdict}} + mix-adjusted pollen/s."""
    kb, ka = _blocks(before), _blocks(after)
    if min(len(before), len(after)) < MIN_TRIPS or min(len(kb), len(ka)) < MIN_BLOCKS:
        return {"verdict": "too few trips", "n_before": len(before), "n_after": len(after),
                "hours_before": len(kb), "hours_after": len(ka)}
    rng = np.random.default_rng(seed)
    ib = rng.integers(0, len(kb), (boot, len(kb)))      # whole hours, with replacement
    ia = rng.integers(0, len(ka), (boot, len(ka)))
    cb, ca = _cols(kb), _cols(ka)
    pb, pa = _metrics(cb, np.arange(len(kb))), _metrics(ca, np.arange(len(ka)))
    bb, ba = _metrics(cb, ib), _metrics(ca, ia)
    # COUNTS ARE DRAWN FROM THEIR POSTERIOR, not resampled: 27 landings of 27
    # resample to 100% every time and would beat 90% "for certain" (Fisher:
    # p ~ 0.07). Shares: Beta(k+1, n-k+1); events per hour: Gamma(k+0.5)/T.
    for side, c in ((bb, cb), (ba, ca)):
        for k, num, den in (("success_pct", "success", "gather"),
                            ("landing_pct", "home_landed", "home_judged")):
            n, x = c[den].sum(), c[num].sum()
            side[k] = rng.beta(x + 1, n - x + 1, boot) * 100 if n else np.full(boot, np.nan)
        for k, num in (("deaths_per_hour", "deaths"), ("rejoins_per_hour", "rejoins")):
            hours = c["wall"].sum() / 3600
            side[k] = rng.gamma(c[num].sum() + 0.5, 1.0, boot) / hours if hours else np.full(boot, np.nan)
    out = {"n_before": len(before), "n_after": len(after),
           "hours_before": len(kb), "hours_after": len(ka)}
    for k, (higher, _unit) in METRICS.items():
        out[k] = _judge(float(pb[k]), float(pa[k]), ba[k] - bb[k], higher)
    # the same field mix: BEFORE's gather time per field, both sides' rates
    gt: dict = {}
    for u in before:
        if u["field"] and u["gather_s"] > 0:
            gt[u["field"]] = gt.get(u["field"], 0.0) + u["gather_s"]
    common = [f for f in gt if any(u["field"] == f and u["gather_s"] > 0 for u in after)]
    if common:
        w = np.array([gt[f] for f in common])
        w = w / w.sum()
        def mix(bs, idx):   # a field a resample never drew drops out, the rest re-weighted
            r = _field_rates(bs, common, idx)
            ok = ~np.isnan(r)
            return _ratio(np.where(ok, r * w, 0).sum(-1), (ok * w).sum(-1))
        out["mix_pollen_per_s"] = _judge(
            float(mix(kb, np.arange(len(kb)))), float(mix(ka, np.arange(len(ka)))),
            mix(ka, ia) - mix(kb, ib), True)
        out["mix_pollen_per_s"]["fields"] = common
    return out


def _judge(a: float, b: float, diffs: np.ndarray, higher: bool) -> dict:
    diffs = diffs[~np.isnan(diffs)]
    if np.isnan(a) or np.isnan(b) or len(diffs) < 10:
        return {"before": None if np.isnan(a) else a, "after": None if np.isnan(b) else b,
                "verdict": "not measured"}
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p = min(1.0, 2 * min((diffs <= 0).mean(), (diffs >= 0).mean()))
    if lo > 0:
        verdict = "better" if higher else "worse"
    elif hi < 0:
        verdict = "worse" if higher else "better"
    else:
        verdict = "no detectable change"
    return {"before": round(a, 3), "after": round(b, 3), "diff": round(b - a, 3),
            "lo": round(float(lo), 3), "hi": round(float(hi), 3),
            "pct": round(100 * (b - a) / a, 1) if a else None, "p": round(float(p), 4),
            "verdict": verdict}


def regression(cmp: dict) -> list:
    return [k for k in REGRESSION_ON if (cmp.get(k) or {}).get("verdict") == "worse"
            and cmp[k]["p"] < REGRESSION_P]


# ---- time accounting -------------------------------------------------------
# Where the running time goes. The trip ledger is the authority inside a
# trip: from its start to its convert's press it is gather_seconds, the walk
# out (routes "out" + "flight") and the walk home; what is left there is
# "trip overhead" (respawns before a walk, the cannon, turning, a death's
# respawn) unless the log names it recovery or a buff wait. From the press
# to the trip's end, between trips and around them, the run log says what
# happens: each marker below switches the label until the next one, and a
# stretch no marker names is "unknown" -- never folded into a neighbour.
RESTART_GAP = 900.0       # an exit and the next start closer than this: one session restarting
# slice -> the group the one-line summary adds it to
SLICES = {"gather": "gather", "walk out": "walking", "walk home": "walking",
          "convert": "converting", **{k: "errands" for k in (
              "quests", "dispensers", "memory match", "blender", "shops", "planters",
              "bosses & mobs", "menus & items")},
          "buff waits": "overhead", "trip overhead": "overhead", "recovery": "overhead",
          "rejoin/startup": "rejoin/startup", "paused/idle": "paused/idle",
          "unknown": "unknown"}
_QUEST_GIVER = r"(?:\w+_bear|bucko_bee|riley_bee|honey_bee|gifted_bucko_bee|gifted_riley_bee)"
_PLACE = r"(\w+_dispenser|\w+_booster|wealth_clock|sticker_stack|ant_pass|samovar|stockings" \
         r"|honey_wreath|\w*memory_match|blender)"
# A marker STARTS its slice (the time after it is that slice) -- or, with a
# "!", it SUMS ONE UP: a line written at the end of the thing it names ("read
# 6 page(s) of the inventory in 64s"), so the time since the last stamped line
# is that slice and the time after it goes back to the region's own label. A
# line without a clock of its own carries the last one, so only a stamped
# summary or END ends anything.
END = "_end"              # an errand is over: back to the region's own label
MARKERS = [(re.compile(p), label) for p, label in (
    # notes and progress lines inside something already labelled: no switch
    (r"not now|not yet|not walked|not read —|never pressed|^threat eye|: leg \d+ "
     r"|respawning to get home after the errand|^quest: |^quests want", None),
    (r"respawned (onto our own pad|at the spawn point)[^(]* after the errand"
     r"|(quest menu|badge menu|bee menu|inventory) closed after", END),
    (r"going to the |before natro_out_" + _PLACE + r"\b", "dispensers"),
    (r"^bee menu: read \d+ page", None),     # its rows are read while the bot gets on
    (r"^buff wait over", "buff waits!"),
    (r"^inventory: read \d+ page|^royal jelly: \d+ rolled|^badges: ", "menus & items!"),
    (r"^quests: read |: \d+ page\(s\) over", "quests!"),
    (r"^Commando Chick: its health|BEATEN after|DEFEATED in|: not beaten", "bosses & mobs!"),
    (r"convert: pressed E|^balloon: stayed", "convert"),
    (r"^waiting out ", "buff waits"),
    (r"asking for a rejoin|^rejoining|in game after", "rejoin/startup"),
    (r"Memory Match|memory_match", "memory match"),
    (r"[Bb]lender", "blender"),
    (r"quest menu|reading the quest|hand-in|a finished quest|dialogue"
     r"|(Black|Brown|Polar|Panda|Science|Mother|Spirit|Dapper|Gummy) Bear"
     r"|(Bucko|Riley|Honey) Bee\b|natro_out_" + _QUEST_GIVER + r"\b", "quests"),
    (r"Commando|Ant Challenge|Vicious Bee|King Beetle|Tunnel Bear|Coconut Crab"
     r"|Stump Snail|^bug run:|loot walk", "bosses & mobs"),
    (r"^planter( errand)?: |^planters: (?!the bot has never)", "planters"),
    (r"^buying |^shop look|Shop's (window|catalogue)|ticket tent", "shops"),
    (r"^(opening the badge menu|opening the inventory|reading the inventory|inventory: "
     r"|bee menu|royal jelly)"
     r"|hatch", "menus & items"),
    (r"[Ss]ticker [Ss]tack", "dispensers"),
    (r"^sweep: |^look \d+: no hive|could not reach the hive|^died: |respawned after the"
     r"|the HUD did not|lost the HUD|turned a full circle", "recovery"),
)]


def _label(raw: str) -> str | None:
    """The slice a log line starts ("...!": sums up; END: is over), or None."""
    text = _STAMP.sub("", raw, count=1).strip() if _STAMP.match(raw) else raw.strip()
    for rx, label in MARKERS:
        if rx.search(text):
            if label == "dispensers":       # the place it is going to says which errand
                m = re.search(r"going to the (\w+(?: \w+)*?) to |before natro_out_(\w+)", text)
                where = (m.group(1) or m.group(2)).replace(" ", "_") if m else ""
                if where.endswith("memory_match"):
                    return "memory match"
                if where == "blender":
                    return "blender"
                if re.fullmatch(_QUEST_GIVER, where):
                    return "quests"
            return label
    return None


def _span(lines: list, a: float, b: float, default: str, out: dict, rest: str = "unknown",
          keep=None, times=None) -> None:
    """Add [a, b) to `out` by the log's labels, starting as `default`; after
    an END or a summary it is `rest`. With `keep` (a set) only those labels
    are taken, the rest of the time staying `default`. A buff wait lasts its
    "(about Ns)" and then hands back to what it interrupted.
    # ponytail: a wait without its "buff wait over" line (most of them) is
    # booked at its announced length, not the one it took."""
    if b <= a:
        return
    label, at, back, until, seen = default, a, default, None, a

    def add(lbl, t0, t1):
        out[lbl] = out.get(lbl, 0.0) + max(0.0, t1 - t0)
    i = bisect.bisect_left(times if times is not None else [t for t, _ in lines], a)
    for t, raw in lines[i:]:
        if t >= b:
            break
        if until is not None and t >= until:
            add(label, at, until)
            label, at, until = back, until, None
        new, stamped = _label(raw), bool(_STAMP.match(raw))
        last, seen = seen, (t if stamped else seen)
        if new is None:
            continue
        summary = new.endswith("!")
        if (summary or new == END) and not stamped:
            continue                          # its clock is the last line's: it ends nothing
        new = rest if new == END else new.rstrip("!")
        if keep is not None and new not in keep:
            new = default
        if summary:                           # since the last stamped line: this
            add(label, at, max(at, last))
            at = max(at, last)
        add(new if summary else label, at, t)
        if summary:
            new = back if label == "buff waits" and new == "buff waits" else rest
            until = None
        elif new == "buff waits":
            m = re.search(r"\(about (\d+)s\)", raw)
            back = back if label == "buff waits" else label
            until = t + float(m.group(1)) + 1 if m else None
        else:
            until = None
        label, at = new, max(at, t)
    if until is not None and until < b:
        add(label, at, until)
        label, at = back, until
    add(label, at, b)


def time_account(var: Path, all_runs: list, trips: list, since: float, until: float) -> dict:
    """Where the running time of [since, until) went: {slices, groups: {name:
    {s: seconds, pct: of running}}, running_h, off_h (not running at all),
    biggest_non_gather}. Running = the runs plus the restarts between them."""
    sl: dict = {}
    clip = lambda a, b: (max(a, since), min(b, until))                    # noqa: E731
    bylog = {}
    for start, end, lines in run_lines(var, all_runs, since, until):
        bylog[start] = lines
    waits = memory_waits(var)
    for i, (start, end, name) in enumerate(all_runs):
        if end < since or start >= until:
            continue
        lines = bylog.get(start, [])
        times = [t for t, _ in lines]
        num = re.sub(r"\D", "", name)
        mine = [r for r in trips if start - 60 <= float(r["at"]) - float(r.get("seconds") or 0)
                and float(r["at"]) <= end + 60 and str(r.get("attempt", num)) == num]
        cursor, default = start, "rejoin/startup"
        for r in mine:
            at = min(float(r["at"]), end)
            s0 = max(cursor, at - float(r.get("seconds") or 0))
            a, b = clip(cursor, s0)
            _span(lines, a, b, default, sl, default, times=times)
            j = bisect.bisect_left(times, s0)
            press = next((t for t, raw in lines[j:] if t >= at or "convert: pressed E" in raw), at)
            press = min(press, at)
            a, b = clip(s0, press)
            if b > a:
                share = (b - a) / max(1e-9, press - s0)
                legs = {"gather": float(r.get("gather_seconds") or 0),
                        "walk out": sum(float(x.get("seconds") or 0) for x in r.get("routes") or []
                                        if x.get("kind") in ("out", "flight")),
                        "walk home": sum(float(x.get("seconds") or 0) for x in r.get("routes") or []
                                         if x.get("kind") == "home")}
                core = {}
                _span(lines, a, b, "trip overhead", core, "trip overhead",
                      keep={"recovery", "buff waits"}, times=times)
                room = (b - a)
                scale = min(1.0, room / max(1e-9, sum(legs.values()) * share))
                for k, v in legs.items():
                    sl[k] = sl.get(k, 0.0) + v * share * scale
                room -= sum(legs.values()) * share * scale
                core.pop("trip overhead", None)       # what is left of the room, below
                named = sum(core.values())
                for k, v in core.items():
                    sl[k] = sl.get(k, 0.0) + (v * min(1.0, room / named) if named else 0.0)
                sl["trip overhead"] = sl.get("trip overhead", 0.0) + max(0.0, room - named)
            a, b = clip(press, at)
            _span(lines, a, b, "convert", sl, times=times)
            cursor, default = max(cursor, at), "unknown"
        a, b = clip(cursor, end)
        _span(lines, a, b, default, sl, default, times=times)
        nxt = all_runs[i + 1][0] if i + 1 < len(all_runs) else None
        if nxt is not None and 0 < nxt - end < RESTART_GAP:
            a, b = clip(end, nxt)
            if b > a:
                k = "paused/idle" if nxt in waits else "rejoin/startup"
                sl[k] = sl.get(k, 0.0) + b - a
    running = sum(sl.values())
    cell = lambda v: {"s": round(v, 1),                                   # noqa: E731
                      "pct": round(100 * v / running, 1) if running else None}
    groups: dict = {}
    for k, g in SLICES.items():
        groups[g] = groups.get(g, 0.0) + sl.get(k, 0.0)
    return {"since": since, "until": until, "running_h": round(running / 3600, 2),
            "off_h": round(max(0.0, until - since - running) / 3600, 2),
            "slices": {k: cell(sl.get(k, 0.0)) for k in SLICES},
            "groups": {g: cell(v) for g, v in sorted(groups.items(), key=lambda kv: -kv[1])},
            "biggest_non_gather": max((k for k in SLICES if k != "gather"),
                                      key=lambda k: sl.get(k, 0.0))}


def memory_waits(var: Path) -> set:
    """Start times of attempts overnight.sh held back waiting for memory."""
    out, waited = set(), False
    try:
        lines = (var / "night" / "attempts.log").read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        if "waiting for memory" in line:
            waited = True
            continue
        m = _ATTEMPT.search(line)
        if m:
            if waited:
                out.add(time.mktime(time.strptime(m.group(2), "%Y-%m-%d %H:%M:%S")))
            waited = False
    return out


# ---- the whole card --------------------------------------------------------
def build(var: Path, now: float, hours: float = 72.0, before: str | None = None,
          after: str | None = None, work: Path = WORK, boot: int = BOOT) -> dict:
    since = now - hours * 3600
    deps = deploys(var, work)
    split_points = [resolve(x, deps, work) for x in (before, after) if x]
    earliest = min([since] + [t - 24 * 3600 for t in split_points]
                   + [t - 24 * 3600 for t, _ in deps if t >= since])
    trips = load_trips(var, earliest, now)
    all_runs = runs(var, now)
    events = log_events(var, all_runs, earliest, now)
    us = units(trips, events)
    caps, made = captures(var), crafts(var)
    pick = lambda a, b: [u for u in us if a <= u["at"] < b]                   # noqa: E731
    win = lambda a, b: summary(pick(a, b), a, b, all_runs, events, caps, made)  # noqa: E731
    card = {"generated_at": now, "hours": hours, "min_trips": MIN_TRIPS,
            "baseline": win(since, now), "deploys": [], "regressions": [],
            "experiments": _experiments(var),
            "time": time_account(var, all_runs, trips, since, now)}
    if split_points:
        b_end, a_start = split_points[0], split_points[-1]
        b0, a1 = b_end - 24 * 3600, min(now, a_start + 24 * 3600)
        card["comparison"] = {"before": win(b0, b_end), "after": win(a_start, a1),
                              "args": {"before": before, "after": after},
                              "result": compare(pick(b0, b_end), pick(a_start, a1), boot)}
    for i, (t, sha) in enumerate(deps):
        if t < since:
            continue
        prev = max(deps[i - 1][0] if i else 0, t - 24 * 3600)
        nxt = min(deps[i + 1][0] if i + 1 < len(deps) else now, t + 24 * 3600)
        bef, aft = pick(prev, t), pick(t, nxt)
        lb = _nearest(pick(t - 24 * 3600, t), max(MIN_TRIPS, len(bef)), last=True)
        la = _nearest(pick(t, min(now, t + 24 * 3600)), max(MIN_TRIPS, len(aft)), last=False)
        span = (lb[0]["at"] - 1 if lb else t, la[-1]["at"] + 1 if la else t)
        local = compare(lb, la, boot)
        local["mixes_deploys"] = [s for tt, s in deps if span[0] < tt < span[1] and s != sha]
        row = {"at": t, "sha": sha, "subject": _git("log", "-1", "--format=%s", sha,
                                                     repo=work / "repo")[:90],
               "isolated": compare(bef, aft, boot), "local": local}
        flag = regression(row["isolated"] if "honey_per_hour" in row["isolated"] else local)
        if flag:
            last = card["regressions"][-1] if card["regressions"] else None
            if last and last["until"] >= span[0] and last["worse_on"] == flag:
                last["shas"].append(sha)          # overlapping windows: one alarm
                last["until"] = span[1]
            else:
                card["regressions"].append({"shas": [sha], "at": t, "until": span[1],
                                            "worse_on": flag})
        card["deploys"].append(row)
    return card


def _nearest(us: list, n: int, last: bool) -> list:
    """The `n` trips nearest a split (the last ones, or the first), more
    while they cover fewer than MIN_BLOCKS clock hours."""
    out, hours = [], set()
    for u in (us[::-1] if last else us):
        if len(out) >= n and len(hours) >= MIN_BLOCKS:
            break
        out.append(u)
        hours.add(int(u["at"] // BLOCK_S))
    return out[::-1] if last else out


# ---- the day's one number (ROADMAP P4: the stats card, /report) -------------
# Honey/h exactly as the card's (summary over units), for today since local
# midnight, yesterday, and the 7 whole days before today. A window with fewer
# than MIN_TODAY_READINGS trips that carry a measured honey interval (two
# trusted balance readings of one run, no spend between) has no number:
# early in the day a single lucky payout would be the headline.
MIN_TODAY_READINGS = 6


def _midnight(t: float) -> float:
    return dt.datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0,
                                                microsecond=0).timestamp()


def today(var: Path, now: float | None = None) -> dict:
    """{today, yesterday, week: honey/h or None, readings (today's), running_hours,
    uptime_pct (today's), vs_week_pct}. Read-only."""
    now = time.time() if now is None else now
    m = _midnight(now)
    y, w = _midnight(m - 1), _midnight(m - 7 * 86400 + 7200)      # +2 h: a DST week
    us, all_runs = units(load_trips(var, w, now)), runs(var, now)

    def rate(a, b):
        mine = [u for u in us if a <= u["at"] < b]
        n = sum(1 for u in mine if u["hdt"] > 0)
        s = summary(mine, a, b, all_runs)
        return (s.get("honey_per_hour") if n >= MIN_TODAY_READINGS else None), n, s
    t, n, s = rate(m, now)
    out = {"since": m, "today": t, "readings": n, "min_readings": MIN_TODAY_READINGS,
           "yesterday": rate(y, m)[0], "week": rate(w, m)[0],
           "running_hours": s["running_hours"], "uptime_pct": s["uptime_pct"]}
    out["vs_week_pct"] = (round(100 * (t / out["week"] - 1), 1)
                          if t is not None and out["week"] else None)
    return out


def _short(v) -> str:
    if v is None:
        return "-"
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= size:
            return f"{v / size:.3g}{unit}"
    return f"{v:.0f}"


def today_line(d: dict, emoji: bool = True) -> str:
    """'Honey/hr today: 98.2M (yesterday 92.5M · 7-day 103M) 🔴▼ 5% vs 7-day ·
    running 14.2 h, uptime 89%'. `emoji` False: no colour dot (the card draws
    the arrow in colour itself)."""
    head = (f"Honey/hr today: {_short(d['today'])}" if d["today"] is not None else
            f"Honey/hr today: not enough data yet today ({d['readings']} of "
            f"{d['min_readings']} readings)")
    out = f"{head} (yesterday {_short(d['yesterday'])} · 7-day {_short(d['week'])})"
    p = d.get("vs_week_pct")
    if p is not None:
        out += (f" {('🟢' if p >= 0 else '🔴') if emoji else ''}{'▲' if p >= 0 else '▼'} "
                f"{abs(p):.0f}% vs 7-day")
    if d.get("running_hours") is not None:
        out += f" · running {d['running_hours']:.1f} h" + (
            f", uptime {d['uptime_pct']:.0f}%" if d.get("uptime_pct") is not None else "")
    return out


# ---- did the last deploy make it worse? (ROADMAP P2, tools/rollback_watch.py) ----
# The card above judges every deploy at p < REGRESSION_P on everything; on
# 12 Oct and 15 Oct it alarmed on drops the code did not cause
# (docs/pending/reliability-2026-10-19b.md). regression_check judges the
# same block bootstrap (compare) on LIKE-WITH-LIKE trips only -- `steady`:
#   * running time, not restarts: honey/h is already timed between readings
#     of ONE run (rejoins, memory-gate waits and the time Sober is down are
#     never in it); on top, a run's first WARMUP_S (its start-up errands:
#     quests, dispensers, inventory reads) and trips a stop or a deploy cut
#     ("stop requested") are left out. 12 Oct's "after" was 7 runs of 12-22
#     minutes each -- mostly warm-up and cut trips.
#   * the field mix the code chose, not a quest's: a trip where quests.first
#     put a quest's field ahead of a field the planner scored higher is left
#     out (15 Oct: a new quest set sent 30 trips to Rose/Pineapple/Blue Flower).
#   * enough data: CHECK_MIN_TRIPS steady trips and MIN_BLOCKS clock hours a
#     side, or NOT_ENOUGH_DATA -- never a verdict on a few trips.
# REGRESSED = honey/h or landing % worse at p < REGRESSION_P; the same-mix
# pollen/s is reported beside it to say whether the gathering itself fell.
WARMUP_S = 1200.0
CHECK_MIN_TRIPS = 30
CHECK_MAX_AFTER_S = 24 * 3600.0     # the after side stops here: days apart, the account has grown
REGRESSED, OK, NOT_ENOUGH_DATA = "REGRESSED", "OK", "NOT_ENOUGH_DATA"


def steady(us: list) -> tuple:
    """(the trips regression_check compares, {reason: how many left out})."""
    out, left = [], {"warm-up": 0, "quest-forced": 0, "cut by a stop": 0}
    for u in us:
        if u.get("cut"):
            left["cut by a stop"] += 1
        elif u.get("quest_forced"):
            left["quest-forced"] += 1
        elif u.get("since_join") is not None and u["since_join"] < WARMUP_S:
            left["warm-up"] += 1
        else:
            out.append(u)
    return out, left


def regression_check(var: Path, after_deploy, now: float | None = None, work: Path = WORK,
                     boot: int = BOOT, deps: list | None = None) -> dict:
    """Is what runs since `after_deploy` (a SHA, a time, a unix time) worse
    than what ran before it? {verdict: REGRESSED | OK | NOT_ENOUGH_DATA,
    reason (plain words, with the numbers), at, compare, left_out}. The
    after side is [deploy, min(now, deploy + 24 h)) and so holds every later
    deploy too; the before side the CHECK_MIN_TRIPS steady trips (and
    MIN_BLOCKS hours) nearest the deploy, within 24 h."""
    now = time.time() if now is None else now
    deps = deploys(var, work) if deps is None else deps
    t = after_deploy if isinstance(after_deploy, (int, float)) else resolve(after_deploy, deps, work)
    end = min(now, t + CHECK_MAX_AFTER_S)
    us = units(load_trips(var, t - 24 * 3600, end))
    bef, left_b = steady([u for u in us if t - 24 * 3600 <= u["at"] < t])
    aft, left_a = steady([u for u in us if t <= u["at"] < end])
    bef = _nearest(bef, CHECK_MIN_TRIPS, last=True)
    cmp = compare(bef, aft, boot)
    later = [s for tt, s in deps if t < tt <= end]
    out = {"at": t, "until": end, "compare": cmp, "later_deploys": later,
           "left_out": {"before": left_b, "after": left_a}}
    skipped = ", ".join(f"{n} {k}" for k, n in left_a.items() if n) or "none"
    if len(aft) < CHECK_MIN_TRIPS or "honey_per_hour" not in cmp:
        hours = len({int(u["at"] // BLOCK_S) for u in aft})
        out.update(verdict=NOT_ENOUGH_DATA, reason=(
            f"{len(aft)} steady trips in {hours} h since the deploy (needs {CHECK_MIN_TRIPS} "
            f"and {MIN_BLOCKS} h; {len(bef)} before); left out after it: {skipped}"))
        return out
    h, mix, land = cmp["honey_per_hour"], cmp.get("mix_pollen_per_s"), cmp["landing_pct"]
    worse = regression(cmp)

    def say(name, c, unit=""):
        if not c or "p" not in c:
            return f"{name} not measured"
        return (f"{name} {_n(c['before'], unit)} -> {_n(c['after'], unit)}"
                + (f" ({c['pct']:+.0f}%)" if c.get("pct") is not None and unit != "%" else "")
                + f", {c['verdict']} (p {c['p']:.3f})")
    out.update(verdict=REGRESSED if worse else OK, worse_on=worse, reason="; ".join([
        say("honey/h", h), say("landing", land, "%"), say("pollen/s on the same fields", mix),
        f"{cmp['n_before']} vs {cmp['n_after']} steady trips ({cmp['hours_before']} vs "
        f"{cmp['hours_after']} h)" + (f", the after side also holds {len(later)} later "
                                     f"deploy(s)" if later else ""),
        f"left out after it: {skipped}"]))
    return out


def _experiments(var: Path) -> dict:
    out = {}
    for name, arms in _json(var / "experiments.json", {}).items():
        out[name] = {a: {"tries": round(v["tries"], 1),
                         "rate": round(v["reward"] / v["tries"], 3) if v["tries"] else None}
                     for a, v in arms.items() if not a.startswith("_") and isinstance(v, dict)}
    return out


# ---- text ------------------------------------------------------------------
def _h(t: float) -> str:
    return time.strftime("%d %b %H:%M", time.localtime(t))


def _n(v, unit="") -> str:
    if v is None:
        return "-"
    if unit == "%":
        return f"{v:.1f}%"
    return f"{v / 1e6:.1f}M" if abs(v) >= 1e5 else f"{v:.2f}"


def _row(name: str, c: dict, unit: str) -> str:
    if "lo" not in c:
        return f"| {name} | {_n(c.get('before'), unit)} | {_n(c.get('after'), unit)} | | {c['verdict']} |"
    return (f"| {name} | {_n(c['before'], unit)} | {_n(c['after'], unit)} | "
            f"{_n(c['diff'], unit)} [{_n(c['lo'], unit)}, {_n(c['hi'], unit)}] | "
            f"**{c['verdict']}** (p {c['p']:.3f}) |")


def _cmp_md(cmp: dict) -> list:
    if "n_before" in cmp and "honey_per_hour" not in cmp:
        return [f"_too few trips_ ({cmp['n_before']} before in {cmp.get('hours_before', '?')} h, "
                f"{cmp['n_after']} after in {cmp.get('hours_after', '?')} h; needs {MIN_TRIPS} "
                f"trips and {MIN_BLOCKS} clock hours a side)"]
    out = [f"{cmp['n_before']} trips before, {cmp['n_after']} after.", "",
           "| metric | before | after | after - before [95% CI] | verdict |", "|---|---|---|---|---|"]
    for k, (_h_, unit) in METRICS.items():
        out.append(_row(k, cmp[k], unit))
    if "mix_pollen_per_s" in cmp:
        out.append(_row("pollen/s, same field mix", cmp["mix_pollen_per_s"], ""))
    return out


def _alarm(r: dict) -> str:
    who = r["shas"][0] if len(r["shas"]) == 1 else \
        f"{r['shas'][0]}..{r['shas'][-1]} ({len(r['shas'])} deploys, not separable)"
    return f"REGRESSION: {who} from {_h(r['at'])} -- worse on {', '.join(r['worse_on'])}"


def markdown(card: dict) -> str:
    b = card["baseline"]
    out = [f"# Benchmark scorecard -- {_h(card['generated_at'])}", ""]
    for r in card["regressions"]:
        out.append(f"**{_alarm(r)}**")
    out += ["", f"## Baseline: the last {card['hours']:g} h ({b['trips']} trips, "
            f"{b['running_hours']} h running, uptime {_n(b['uptime_pct'], '%')})", "",
            "| metric | value |", "|---|---|"]
    for k, (_h_, unit) in METRICS.items():
        out.append(f"| {k} | {_n(b.get(k), unit)} |")
    out += [f"| quest hand-ins | {b['handins']} ({b['handins_per_day']}/day running) |",
            f"| rejoins | {b['rejoins']} |",
            f"| Commando captures | {b['captures']} |",
            f"| Blender crafts | {b['crafts']} ({b['crafted_items']} items) |", "",
            "Per field (pollen/s, minutes gathered): " + ", ".join(
                f"{f} {v['pollen_per_s']:,.0f} ({v['gather_min']:.0f} min)"
                for f, v in list(b["fields"].items())[:10]), ""]
    if "comparison" in card:
        c = card["comparison"]
        out += [f"## Requested: before {c['args']['before']} vs after {c['args']['after']}", ""]
        out += _cmp_md(c["result"]) + [""]
    out += ["## Deploys", ""]
    for d in reversed(card["deploys"]):
        out += [f"### {d['sha']} at {_h(d['at'])} -- {d['subject']}", "",
                "Isolated (since the deploy before, to the deploy after):", ""]
        out += _cmp_md(d["isolated"]) + ["", "Local (each side stretched to its nearest "
                                          f"{MIN_TRIPS} trips and {MIN_BLOCKS} hours; mixes in: "
                                          f"{', '.join(d['local']['mixes_deploys']) or 'nothing'}):", ""]
        out += _cmp_md(d["local"]) + [""]
    if card.get("time"):
        out += time_md(card["time"]) + [""]
    if card["experiments"]:
        out += ["## Experiments (var/experiments.json)", ""]
        for name, arms in card["experiments"].items():
            out.append(f"- {name}: " + ", ".join(
                f"{a} {v['rate']} of {v['tries']}" for a, v in arms.items()))
    return "\n".join(out) + "\n"


def time_md(t: dict) -> list:
    out = [f"## Time: where {t['running_h']:g} h of running went "
           f"({t['off_h']:g} h of the window not running)", "",
           "| slice | group | hours | % of running |", "|---|---|---|---|"]
    for k, v in sorted(t["slices"].items(), key=lambda kv: -kv[1]["s"]):
        out.append(f"| {k} | {SLICES[k]} | {v['s'] / 3600:.2f} | {_n(v['pct'], '%')} |")
    big = t["biggest_non_gather"]
    return out + ["", f"Biggest slice after gathering: **{big}** "
                      f"({_n(t['slices'][big]['pct'], '%')})."]


def time_line(t: dict) -> str:
    big = t["biggest_non_gather"]
    return ("time: " + ", ".join(f"{g} {v['pct']:.0f}%" for g, v in t["groups"].items()
                                 if v["pct"] and v["pct"] >= 0.5)
            + f" (biggest after gather: {big} {_n(t['slices'][big]['pct'], '%')})")


def telegram_text(card: dict) -> str:
    b = card["baseline"]
    lines = [f"Benchmark {card['hours']:g}h: honey {_n(b.get('honey_per_hour'))}/h, "
             f"pollen {_n(b.get('pollen_per_hour'))}/h, landing {_n(b.get('landing_pct'), '%')}, "
             f"success {_n(b.get('success_pct'), '%')}, {b['trips']} trips, "
             f"uptime {_n(b['uptime_pct'], '%')}"]
    if (card.get("time") or {}).get("running_h"):
        lines.append(time_line(card["time"]))
    for r in card["regressions"]:
        lines.append(_alarm(r))
    for d in card["deploys"][-3:][::-1]:
        c = d["isolated"] if "honey_per_hour" in d["isolated"] else d["local"]
        if "honey_per_hour" not in c:
            lines.append(f"{d['sha']}: too few trips yet")
        else:
            lines.append(f"{d['sha']}: honey/h {c['honey_per_hour']['verdict']}, "
                         f"landing {c['landing_pct']['verdict']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hours", type=float, default=72.0)
    ap.add_argument("--before")
    ap.add_argument("--after")
    ap.add_argument("--var", type=Path, default=ROOT / "var")
    ap.add_argument("--out", type=Path, help="where benchmark.json/.md go (default: --var)")
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--now", type=float)
    ap.add_argument("--telegram-text", action="store_true")
    ap.add_argument("--time", action="store_true", help="print only where the running time went")
    ap.add_argument("--today", action="store_true",
                    help="print only today's honey/h line (ROADMAP P4); writes nothing")
    a = ap.parse_args(argv)
    if a.today:
        print(today_line(today(a.var, a.now)))
        return 0
    card = build(a.var, a.now or time.time(), a.hours, a.before, a.after, a.work)
    out = a.out or a.var
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(json.dumps(card, indent=1))
    (out / "benchmark.md").write_text(markdown(card))
    for r in card["regressions"]:
        print(f"!!! {_alarm(r)} !!!", file=sys.stderr)
    if a.time:
        print("\n".join(time_md(card["time"])) + "\n\n" + time_line(card["time"]))
    else:
        print(telegram_text(card) if a.telegram_text else markdown(card))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Read health (ROADMAP S3): is the game still drawn the way the bot reads it?

A GAME UPDATE BREAKS MANY READS AT ONCE; NOISE BREAKS ONE. Each read site
calls `note(kind, ok, score)` -- one line, its own logic untouched -- and this
keeps the last WINDOW_S of each kind in memory. `broken()` names the kinds
failing far more than they normally do; KINDS_TO_BREAK of them at once is the
"the game may have updated" verdict run_farm acts on (safe mode, frames, a
needs-you alert). `drift()` compares each kind's daily median score over the
last few days with its own fortnight before, to warn before a template breaks.

MEASURED (read-only, docs/pending/readhealth-s3.md), 3 weeks to 2026-10-19:
  * pollen counter: unreadable on 0.9-4.9% of gather passes a day (run logs'
    "unreadable Nx ... over P passes", 1,951 trips); 7 trips of 1,951 at 50%+
    and one SINGLE-KIND episode, 10-07 (28/44, 35/45 passes: one capacity
    glyph the templates lacked) while honey, hotbar and respawns read fine;
  * respawn landing (pad prompt or hive row): 0-13% a day unlanded
    (var/respawn, 5,265 frames); 11 of 1,142 ten-minute windows at 60%+;
  * no ten-minute window had both at 60%+, so two kinds is the bar;
  * frames sampled from var/routes (~40 a day): honey digits read 85-100% a
    day, pollen 83-100%, a hotbar slot identified on 99%; the feed's pill
    names a source on only 34% of strips (most frames are walks), so the feed
    is never "normally succeeding" and cannot vote for a break.

In memory only (a deque per kind, a score histogram per day); written by
`flush` as rows of var/readhealth.jsonl that `daily` merges per day and kind.
Never raises into a read site.
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter, deque
from pathlib import Path

WINDOW_S = 600.0          # one gather trip is 6-12 min; the measurements above are per ~10 min
MIN_ATTEMPTS = 5          # fewer reads in the window say nothing (the window analysis used n >= 5)
FAIL_RATE = 0.6           # failing kind: above this in the window (normal days: <= 13%)
KINDS_TO_BREAK = 2        # 10-07 was one kind for hours and was not an update
NORMAL_SUCCESS = 0.8      # only a kind that normally reads this well can vote
CHECK_S = 30.0            # run_farm's watcher looks this often
FLUSH_S = 3600.0          # and writes the day's rows this often (and at exit)
# THE MEASURED BASELINE, used until var/readhealth.jsonl has a day of its own
# for the kind (`baseline`). A kind in neither cannot vote yet.
BASELINE = {"pollen digits": 0.95, "honey digits": 0.96, "hotbar tile": 0.99,
            "respawn landing": 0.91, "feed line": 0.34}
# READS THE GATHER AND THE WALK HOME NEED: one of these broken and safe mode
# is not enough -- the run pauses (as the Pause button does) for the owner.
GATHER_KINDS = ("pollen digits", "respawn landing")

# DRIFT. The digits' score is the WORST glyph's, so it moves with the number
# itself: the honey median sat at 0.66-0.69 to 10-12 and at 0.57 since 10-13
# with every read still parsing (the number's digits changed, not the
# templates) -- a 0.12 step from content alone. The hotbar's best-slot score
# moved 0.992-0.996 (spread 0.004). So 0.15 for digits, 0.05 for the rest.
DRIFT_RECENT_DAYS = 3
DRIFT_BASE_DAYS = 14
DRIFT_MIN_RECENT = 50
DRIFT_MIN_BASE = 200
DRIFT_MIN_BASE_DAYS = 3
DRIFT_DROP = {"honey digits": 0.15, "pollen digits": 0.15}
DRIFT_DROP_DEFAULT = 0.05

BREAK_LINE = "game update?"          # scripts/telegram_alerts: a needs-you ping, with a frame
DRIFT_LINE = "read drift:"           # scripts/telegram_alerts: a quiet daily alert


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _quantile(hist: Counter, q: float) -> float | None:
    """The q-quantile of a {score rounded to 0.01: count} histogram."""
    n = sum(hist.values())
    if not n:
        return None
    at, seen = q * (n - 1), 0
    for score in sorted(hist):
        seen += hist[score]
        if seen > at:
            return float(score)
    return float(max(hist))


class ReadHealth:
    def __init__(self, clock=time.time, window_s: float = WINDOW_S):
        self.clock = clock
        self.window_s = float(window_s)
        self.recent: dict[str, deque] = {}
        self.pending: dict[tuple, list] = {}      # (day, kind) -> [n, ok, Counter]
        self._lock = threading.Lock()

    def note(self, kind: str, ok: bool, score: float | None = None) -> None:
        try:
            now = self.clock()
            with self._lock:
                d = self.recent.setdefault(kind, deque(maxlen=20000))
                d.append((now, bool(ok)))
                while d and d[0][0] < now - self.window_s:
                    d.popleft()
                row = self.pending.setdefault((_day(now), kind), [0, 0, Counter()])
                row[0] += 1
                row[1] += bool(ok)
                if score is not None:
                    row[2][round(max(-1.0, min(1.0, float(score))), 2)] += 1
        except Exception:
            pass

    def failing(self, baseline: dict) -> dict:
        """{kind: (fails, attempts)} for each kind that normally reads well
        (`baseline` >= NORMAL_SUCCESS) and failed more than FAIL_RATE of at
        least MIN_ATTEMPTS reads over the last window."""
        since = self.clock() - self.window_s
        out = {}
        with self._lock:
            for kind, d in self.recent.items():
                if baseline.get(kind, 0.0) < NORMAL_SUCCESS:
                    continue
                got = [ok for t, ok in d if t >= since]
                fails = got.count(False)
                if len(got) >= MIN_ATTEMPTS and fails > FAIL_RATE * len(got):
                    out[kind] = (fails, len(got))
        return out

    def broken(self, baseline: dict) -> dict:
        """`failing`, when KINDS_TO_BREAK or more kinds fail at once, else {}."""
        bad = self.failing(baseline)
        return bad if len(bad) >= KINDS_TO_BREAK else {}

    def flush(self, path) -> int:
        """Append the reads since the last flush as rows; returns how many."""
        with self._lock:
            rows, self.pending = self.pending, {}
        lines = []
        for (day, kind), (n, ok, hist) in sorted(rows.items()):
            med, p10 = _quantile(hist, 0.5), _quantile(hist, 0.1)
            lines.append(json.dumps({"day": day, "kind": kind, "n": n, "ok": ok,
                                     "rate": round(ok / n, 4), "median": med, "p10": p10,
                                     "hist": {f"{k:.2f}": v for k, v in sorted(hist.items())}}))
        if lines:
            try:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")
            except OSError:
                return 0
        return len(lines)


def daily(path) -> dict:
    """{day: {kind: {n, ok, rate, median, p10, hist}}}, every flush of a day
    and kind merged (a day is many runs)."""
    out: dict = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            r = json.loads(line)
            cell = out.setdefault(r["day"], {}).setdefault(
                r["kind"], {"n": 0, "ok": 0, "hist": Counter()})
            cell["n"] += int(r["n"])
            cell["ok"] += int(r["ok"])
            cell["hist"].update({float(k): int(v) for k, v in (r.get("hist") or {}).items()})
        except (ValueError, KeyError, TypeError):
            continue
    for kinds in out.values():
        for cell in kinds.values():
            cell["rate"] = cell["ok"] / cell["n"] if cell["n"] else None
            cell["median"] = _quantile(cell["hist"], 0.5)
            cell["p10"] = _quantile(cell["hist"], 0.1)
    return out


def baseline(path, today: str | None = None, days: int = DRIFT_BASE_DAYS) -> dict:
    """{kind: success rate} over the `days` before `today` from the file,
    over BASELINE for kinds with no day of their own."""
    today = today or _day(time.time())
    n, ok = Counter(), Counter()
    for day, kinds in sorted(daily(path).items()):
        if day >= today:
            continue
        for kind, cell in kinds.items():
            n[kind] += cell["n"]
            ok[kind] += cell["ok"]
    out = dict(BASELINE)
    out.update({k: ok[k] / n[k] for k in n if n[k]})
    return out


def drift(path, today: str | None = None) -> list[str]:
    """One phrase per kind whose median score over the last DRIFT_RECENT_DAYS
    days (today included) fell more than its DRIFT_DROP below the median of
    the DRIFT_BASE_DAYS before them, each with enough samples."""
    from datetime import date, timedelta
    today = today or _day(time.time())
    t = date.fromisoformat(today)
    recent = {(t - timedelta(days=i)).isoformat() for i in range(DRIFT_RECENT_DAYS)}
    base = {(t - timedelta(days=i)).isoformat()
            for i in range(DRIFT_RECENT_DAYS, DRIFT_RECENT_DAYS + DRIFT_BASE_DAYS)}
    pools: dict = {}
    for day, kinds in daily(path).items():
        which = "recent" if day in recent else "base" if day in base else None
        if which is None:
            continue
        for kind, cell in kinds.items():
            p = pools.setdefault(kind, {"recent": Counter(), "base": Counter(), "days": set()})
            p[which].update(cell["hist"])
            if which == "base" and cell["hist"]:
                p["days"].add(day)
    out = []
    for kind, p in sorted(pools.items()):
        nr, nb = sum(p["recent"].values()), sum(p["base"].values())
        if nr < DRIFT_MIN_RECENT or nb < DRIFT_MIN_BASE or len(p["days"]) < DRIFT_MIN_BASE_DAYS:
            continue
        now_med, was_med = _quantile(p["recent"], 0.5), _quantile(p["base"], 0.5)
        drop = DRIFT_DROP.get(kind, DRIFT_DROP_DEFAULT)
        if was_med - now_med > drop:
            out.append(f"{kind} median score {now_med:.2f} over the last {DRIFT_RECENT_DAYS} "
                       f"days against {was_med:.2f} over the {DRIFT_BASE_DAYS} before "
                       f"({nr:,} and {nb:,} reads; warns past {drop:.2f})")
    return out


def describe(bad: dict) -> str:
    return ", ".join(f"{k} {f}/{n} failed" for k, (f, n) in sorted(bad.items()))


def enter_safe_mode(bad: dict, keep_frame, pause, sleep=time.sleep,
                    stamp: str | None = None) -> tuple[str, str]:
    """The break, acted on: three newest frames 2 s apart into
    incidents/update-<stamp> (`keep_frame(folder, label, note)`), `pause(reason)`
    -- the caller's existing Pause -- when a GATHER_KINDS read is among the
    broken, and (safe mode's why, the log line) back for the caller to latch
    and say."""
    folder = f"update-{stamp or time.strftime('%Y%m%d-%H%M%S')}"
    said = describe(bad)
    for i in range(3):
        if i:
            sleep(2.0)
        try:
            keep_frame(folder, f"frame{i}", f"{BREAK_LINE} {said}")
        except Exception:
            pass
    why = f"the game may have updated ({said})"
    gather = sorted(set(bad) & set(GATHER_KINDS))
    if gather:
        pause(why)
    line = (f"{BREAK_LINE} the game may have updated: {said} in {WINDOW_S / 60:.0f} min — "
            + (f"{', '.join(gather)} broken too, so paused (press Resume after a look)"
               if gather else "safe mode: gathering and the walk home only, no errands")
            + f"; frames in var/incidents/{folder}")
    return why, line


HEALTH = ReadHealth()


def note(kind: str, ok: bool, score: float | None = None) -> None:
    """The one-line record a read site makes. Never raises."""
    HEALTH.note(kind, ok, score)

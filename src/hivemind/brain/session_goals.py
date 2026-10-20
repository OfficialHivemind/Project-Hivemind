"""Session goals with a feasibility check (ROADMAP G9, a viewer's idea).

They set a horizon and a few goals -- {"hours": 8, "goals": [{"kind": "honey",
"amount": 500e6}, {"kind": "item", "name": "Honeycomb Belt"}, {"kind":
"quest", "giver": "polar bear"}]} -- and `feasibility` says, per goal, YES /
LIKELY / NO with an ETA and the reason, from MEASURED rates only:

  honey  var/benchmark.json's honey/h (scripts/benchmark.py), else the
         ledger's balance rate (goals.balance_rate). Earned = rate x hours.
  item   the goals plan's row (brain/goals): honey short / rate; a material
         short is a NO naming it -- no material has a measured rate yet.
  quest  the last quest read (var/quests.json): steps left; only gathering
         steps -> LIKELY, ETA from the benchmark's per-field pollen/s.

No rate -> "not enough data", never a guess. A rate past STALE_H says its
age in the answer ("rates from 3 days ago"); past TOO_OLD_H it is dropped,
as if never measured (ROADMAP P20). Saved to var/session_goals.json
with the time it was set; while the horizon lasts its items go first in the
goals order (goals.from_files -> `first_keys`).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

YES, LIKELY, NO, UNKNOWN = "yes", "likely", "no", "not enough data"
LIKELY_SHARE = 0.8      # within 80 % of the target in the time: LIKELY, not NO
# HOW OLD A RATE MAY BE (ROADMAP P20: var/benchmark.json was last written by
# hand on 16 Oct and read days later as if new). MEASURED 2026-10-26 on the
# trip ledger 22 Sep - 21 Oct (scripts/benchmark.py's 72 h honey/h, one
# window a day): the ratio of a day's rate to the rate N days before it was
#   2 days  median 1.23, off by more than 20 % in 17 of 26 pairs
#   7 days  median 1.87, off by more than 20 % in 17 of 21 (0.95 .. 6.4)
#  14 days  median 2.86, off by more than 20 % in 14 of 14 (1.76 .. 7.7)
# 20 % is LIKELY_SHARE's band, so past 2 days the answer has to say how old
# its rate is, and past 7 days a YES / NO from it is mostly the wrong side of
# the band: not enough data. 48 h is also two missed nightly re-scores
# (tools/systemd/hivemind-benchmark.timer runs every 24 h).
# ponytail: measured on a young hive growing fast (5M/h -> 117M/h in a
# month); a grown one drifts slower -- re-measure before loosening these.
STALE_H = 48.0
TOO_OLD_H = 7 * 24.0
FILE = "session_goals.json"


def _var(var_root) -> Path:
    if var_root is None:
        from ..datapaths import VAR_ROOT
        var_root = VAR_ROOT
    return Path(var_root)


def short_number(x: float) -> str:
    for size, tag in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= size:
            return f"{x / size:.3g}{tag}"
    return f"{x:,.0f}"


def _hours(h: float) -> str:
    from .goals import hours_text
    return hours_text(h)


@dataclass
class Verdict:
    goal: str
    verdict: str
    reason: str
    eta_h: float | None = None

    def text(self) -> str:
        return f"{self.goal}: {self.verdict.upper()}, {self.reason}"


# ---- the file --------------------------------------------------------------
def load(var_root=None) -> dict:
    try:
        got = json.loads((_var(var_root) / FILE).read_text())
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def save(session: dict, var_root=None, now: float | None = None) -> dict:
    session = dict(session, at=time.time() if now is None else now)
    path = _var(var_root) / FILE
    path.write_text(json.dumps(session, indent=1))
    return session


def active(session: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    try:
        return now < float(session["at"]) + float(session["hours"]) * 3600.0
    except (KeyError, TypeError, ValueError):
        return False


def first_keys(data: dict, var_root=None, now: float | None = None) -> list:
    """The goals.yaml keys of the session's item goals, while it lasts."""
    from .goals import goal_key
    session = load(var_root)
    if not active(session, now):
        return []
    keys = [goal_key(g.get("name", ""), data) for g in session.get("goals") or ()
            if g.get("kind") == "item"]
    return [k for k in dict.fromkeys(keys) if k]


# ---- the rates -------------------------------------------------------------
@dataclass
class Rates:
    honey_h: float | None = None
    honey_from: str = ""
    field_s: dict | None = None        # field slug -> pollen/s while gathering
    gather_share: float | None = None  # share of running time spent gathering
    honey_age_h: float | None = None   # how old honey_h is (None: not known)
    field_age_h: float | None = None   # how old field_s / gather_share are
    dropped: str = ""                  # a rate left out as too old, said in the answer


def ago(age_h: float | None) -> str:
    """'' while a rate is fresh (STALE_H), else 'rates from 3 days ago'."""
    if age_h is None or age_h <= STALE_H:
        return ""
    return f"rates from {age_h / 24:.0f} days ago"


def _with_age(text: str, age_h: float | None) -> str:
    note = ago(age_h)
    return f"{text}, {note}" if note else text


def bench_age_h(bench: dict, path: Path, now: float) -> float | None:
    """Hours since the card's data ends: its generated_at (the --now it was
    built for), else the file's modified time; None when neither is there."""
    try:
        at = float(bench.get("generated_at") or path.stat().st_mtime)
    except (OSError, TypeError, ValueError):
        return None
    return max(0.0, (now - at) / 3600.0)


def rates_from_files(var_root=None, now: float | None = None) -> Rates:
    var = _var(var_root)
    now = time.time() if now is None else now
    out = Rates(field_s={})
    path = var / "benchmark.json"
    try:
        bench = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bench = {}
    if not isinstance(bench, dict):
        bench = {}
    age = bench_age_h(bench, path, now) if bench else None
    if age is not None and age > TOO_OLD_H:
        out.dropped = (f"the benchmark's rates are {age / 24:.0f} days old, over "
                       f"{TOO_OLD_H / 24:.0f}; re-run scripts/benchmark.py --nightly")
        bench = {}
    base = bench.get("baseline") or {}
    if base.get("honey_per_hour"):
        out.honey_h, out.honey_age_h = float(base["honey_per_hour"]), age
        out.honey_from = (f"the benchmark's {base.get('running_hours', '?')} "
                          "running hours")
    out.field_s = {k: float(v.get("pollen_per_s") or 0)
                   for k, v in (base.get("fields") or {}).items()
                   if (v or {}).get("pollen_per_s")}
    pct = ((bench.get("time") or {}).get("slices") or {}).get("gather", {}).get("pct")
    out.gather_share = float(pct) / 100.0 if pct else None
    if out.field_s or out.gather_share:
        out.field_age_h = age
    if out.honey_h is None:
        try:
            from .goals import balance_rate
            from .ledger import Ledger
            rate = balance_rate(Ledger(var / "trips.jsonl").trips())
        except Exception:
            rate = None
        if rate is not None:
            # the same age rule: the trips' rate ends at its newest reading
            r_age = max(0.0, (now - float(rate.until)) / 3600.0)
            if r_age > TOO_OLD_H:
                out.dropped = out.dropped or (f"the trips' honey rate is {r_age / 24:.0f} "
                                              f"days old, over {TOO_OLD_H / 24:.0f}")
            else:
                out.honey_h, out.honey_age_h = rate.per_hour, r_age
                out.honey_from = f"{rate.hours:.1f} h of trips"
    return out


def _no_rate(text: str, rates: Rates) -> str:
    return f"{text} ({rates.dropped})" if rates.dropped else text


# ---- the judges ------------------------------------------------------------
def judge_honey(amount: float, hours: float, rates: Rates) -> Verdict:
    name = f"{short_number(amount)} honey"
    if not rates.honey_h:
        return Verdict(name, UNKNOWN, _no_rate("no honey rate measured yet", rates))
    made = rates.honey_h * hours
    eta = amount / rates.honey_h
    verdict = YES if made >= amount else LIKELY if made >= LIKELY_SHARE * amount else NO
    source = _with_age(rates.honey_from, rates.honey_age_h)
    return Verdict(name, verdict,
                   f"about {short_number(rates.honey_h)}/h ({source}) "
                   f"means about {short_number(made)} in {hours:g} h"
                   + ("" if verdict == YES else f"; needs about {_hours(eta)}"), eta)


def judge_item(row, hours: float, rates: Rates) -> Verdict:
    """`row` is a goals.Row (or None when the name is not a goal)."""
    from .goals import BLOCKED
    if row is None:
        return Verdict("item", UNKNOWN, "not a goal in goals.yaml")
    name = row.label
    if row.owned:
        return Verdict(name, YES, "already owned", 0.0)
    if row.state == BLOCKED:
        return Verdict(name, NO, row.next_step or row.gate or "the shop's gate is not passed")
    parts, eta, verdict = [], None, YES
    if row.short is None:
        verdict, parts = UNKNOWN, ["the honey balance has not been read"]
    elif row.short > 0:
        if rates.honey_h:
            eta = row.short / rates.honey_h
            parts.append(_with_age(f"{short_number(row.short)} honey short, about "
                                   f"{_hours(eta)}", rates.honey_age_h))
            verdict = YES if eta <= hours else LIKELY if eta * LIKELY_SHARE <= hours else NO
        else:
            verdict = UNKNOWN
            parts.append(_no_rate(f"{short_number(row.short)} honey short, no honey "
                                  "rate measured", rates))
    for need in row.missing:
        # ponytail: no material has a measured drop/craft rate yet, so a short
        # one is a NO; give it an ETA when such a rate is measured.
        if need.short is None:
            parts.append(f"{need.label} count unknown")
            verdict = UNKNOWN if verdict != NO else NO
        else:
            parts.append(f"{need.short:,} {need.label} short, no measured rate for it")
            verdict = NO
    if not parts:
        parts = ["the honey and every material are there"]
        eta = 0.0
    return Verdict(name, verdict, "; ".join(parts), eta)


_PAIR = re.compile(r"([\d,]+)\s*/\s*([\d,]+)\s*$")
_FIELD = re.compile(r"from the (.+?)(?: field| forest| patch)?\.", re.I)
_GATHER = re.compile(r"^collect [\d,]+ .*\b(pollen|goo)\b", re.I)


def quests_from_text(text: str) -> list:
    """[(heading, [step lines not yet complete])] from a quest-menu transcript:
    a line with no progress (no x/y, no Complete, no %) is a heading."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        done = "complete" in line.lower()
        progress = done or _PAIR.search(line) or "%" in line
        if not progress:
            out.append((line, []))
        elif out and not done:
            pair = _PAIR.search(line)
            if not (pair and int(pair[1].replace(",", "")) >= int(pair[2].replace(",", ""))):
                out[-1][1].append(line)
    return out


def judge_quest(giver: str, hours: float, text: str, rates: Rates) -> Verdict:
    from .questneeds import giver_name
    giver = str(giver or "").replace("_", " ").strip()
    name = f"{giver.title()} quest"
    want = giver_name(giver)
    found = [(h, steps) for h, steps in quests_from_text(text)
             if giver_name(h.split(":", 1)[0]) == want or giver.lower() in h.lower()]
    if not found:
        return Verdict(name, UNKNOWN, f"no {giver.title()} quest in the last quest read")
    head, steps = found[0]
    if not steps:
        return Verdict(name, YES, f"'{head}' is done; hand it in", 0.0)
    other = [s for s in steps if not _GATHER.match(s)]
    if other:
        return Verdict(name, UNKNOWN, f"{len(steps)} step(s) left; no measured rate for: "
                       + "; ".join(other[:2]))
    gather_s, unrated = 0.0, []
    for step in steps:
        pair, where = _PAIR.search(step), _FIELD.search(step)
        slug = "_".join(where[1].lower().split()) if where else ""
        per_s = (rates.field_s or {}).get(slug)
        if pair and per_s and "goo" not in step.lower():
            left = int(pair[2].replace(",", "")) - int(pair[1].replace(",", ""))
            gather_s += left / per_s
        else:
            unrated.append(step)
    if unrated or not rates.gather_share:
        return Verdict(name, LIKELY, _no_rate(
            f"{len(steps)} gathering step(s) left; no measured rate for "
            + ("; ".join(unrated[:2]) if unrated else "the time share"), rates))
    eta = gather_s / 3600.0 / rates.gather_share
    return Verdict(name, LIKELY if eta <= hours else NO, _with_age(
        f"{len(steps)} gathering step(s) left, about {_hours(eta)} at the measured "
        f"field rates ({rates.gather_share:.0%} of the time gathering)", rates.field_age_h),
        eta)


def _quest_text(var: Path) -> str:
    try:
        got = json.loads((var / "quests.json").read_text())
    except (OSError, ValueError):
        return ""
    return got.get("transcript") or (got.get("transcripts") or [""])[0]


def feasibility(goals, hours: float, var_root=None, settings=None,
                rates: Rates | None = None, now: float | None = None) -> list:
    """A Verdict per goal, in order. Reads var, never writes."""
    var = _var(var_root)
    rates = rates_from_files(var, now) if rates is None else rates
    items = [g for g in goals if g.get("kind") == "item"]
    plan = data = None
    if items:
        from . import goals as goals_mod
        data = goals_mod.load()
        keys = [goals_mod.goal_key(g.get("name", ""), data) for g in items]
        plan = goals_mod.from_files(var_root=var, settings=settings,
                                    first=[k for k in keys if k])
    out = []
    for g in goals:
        kind = g.get("kind")
        if kind == "honey":
            out.append(judge_honey(float(g.get("amount") or 0), hours, rates))
        elif kind == "item":
            from .goals import goal_key
            key = goal_key(g.get("name", ""), data)
            v = judge_item(plan.row(key) if key else None, hours, rates)
            if key is None:
                v.goal = g.get("name", "item")
            out.append(v)
        elif kind == "quest":
            out.append(judge_quest(g.get("giver", ""), hours, _quest_text(var), rates))
    return out


def report(var_root=None, settings=None) -> str:
    """The saved session's verdicts as plain lines (Telegram's /goals)."""
    session = load(var_root)
    if not session.get("goals"):
        return "No session goals set. Add them on Hivemind's Goals tab."
    hours = float(session.get("hours") or 8)
    left = ""
    if session.get("at"):
        end = float(session["at"]) + hours * 3600
        left = (f", ends {time.strftime('%H:%M', time.localtime(end))}"
                if active(session) else ", horizon over")
    return "\n".join([f"Session goals ({hours:g} h{left}):"]
                     + [v.text() for v in feasibility(session["goals"], hours,
                                                      var_root, settings)])

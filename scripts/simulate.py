#!/usr/bin/env python3
"""Replay simulator (ROADMAP P12): the last N days of recorded trips, replayed
offline through the planner's and the token brain's decisions, priced in honey.

    nice -n 19 ./scripts/simulate.py [--days 7] [--var DIR] [--json OUT] [--quest-honey 0,2e6,...]

Read-only over var/: trips.jsonl (each planner decision with its scored
candidates), night/run-N.log (each token-brain decision and its two shadows:
"token brain value would:" and "token brain would: skip"), and
school-coins/lessons.jsonl (what each chase actually earned). No frames, no
game, no keys. Seconds on a laptop.

THREE QUESTIONS, each with '% same decision vs live' and a honey/h effect:

1. PLANNER. Can the logged candidates reproduce the live pick (the rank's sort:
   quest-first fields ahead, then score)? And what would other pick rules have
   earned: top score with quests not first, the v2 shadow's pick, the best
   MEASURED field with a quest worth Q honey a trip added to the fields a quest
   names? Each field's value is the window's own measured honey/h on trips that
   credited it (pollen x the window's honey-per-pollen over trip seconds plus
   its share of the convert time) -- a direct-method estimate, in-sample, so
   it ranks rules; it is not a promise. 90% intervals: seeded bootstrap that
   resamples the decisions and each field's trips.

2. CONVERT TIMING. honey/h at convert_at p, per field, from its measured
   gather rate, trip overhead (travel and the convert, as measured) and
   death rate.
   ASSUMES the gather rate is flat while the bag fills (nothing in the ledger
   measures it within a trip) -- so, death aside, a fuller bag always wins;
   the table says by how much, and how many trips the threshold even ended.

3. TOKEN BRAIN. Every live chase in the window's run logs, joined (run, x, y)
   to its school lesson. Each chase is priced: honey earned (the lesson's
   lump over the trickle; a lump the trickle hides counts 0 in the LOW column
   and its "under N" bound in the HIGH one) less the gathering a detour costs
   (the value line's gather honey/s x the measured loss fraction x
   tokenbrain.detour_s). Rules replayed: the honey-token weight at 0 (no honey
   chases), the value chooser live (drop its skips), the lifetime/leash gate
   live (drop its skips), each kind's weight at 0. A dropped chase is valued
   as staying on the flowers (no replacement chase) -- the bound that holds.
   Ability tokens' worth is a buff, not honey: an unknown-kind chase earns
   only the honey or pollen lump the lesson saw, so their rows UNDERSTATE.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import random
import re
import statistics as st
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hivemind.brain import tokenbrain as tb      # noqa: E402

ANCHOR = (960, 669)              # act/chase.anchor_of at 1920x1080 (tools/analysis/chase_lessons)
MIN_FIELD_TRIPS = 3              # a field with fewer trips in the window is unmeasured
BOOT = 300
DEFAULT_QUEST_HONEY = (0.0, 1e6, 2e6, 5e6, 10e6, 20e6)
QUEST_FIRST = "quests first"     # decide.rank's words for a quest-first field
QUEST_WEAK_SHARE = 0.33          # scripts/run_farm.QUEST_WEAK_SHARE


def load_jsonl(path: pathlib.Path) -> list[dict]:
    out = []
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def window(trips: list[dict], days: float) -> list[dict]:
    trips = [t for t in trips if isinstance(t.get("at"), (int, float))]
    if not trips:
        return []
    end = max(t["at"] for t in trips)
    return [t for t in trips if t["at"] > end - days * 86400]


def q(xs: list[float], f: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(f * (len(xs) - 1)))))]


# ---- 1. planner ---------------------------------------------------------------
GAIN = re.compile(r"honey settled at [\d,]+ \(\+([\d,]+)\)")


def hpp_of(trips: list[dict]) -> float:
    """Honey a pollen: the converts whose note read the gain ("honey settled
    at N (+G)") over that trip's pollen. Not every trip's `honey` over every
    pollen: MEASURED 2026-10-26, 268 of 409 converts in 7 days logged "the
    backpack emptied" with no gain, so that ratio read 0.60 against 1.77 here."""
    honey = pollen = 0.0
    for t in trips:
        g = GAIN.search(t.get("convert_note") or "")
        if g and t.get("converted") and (t.get("pollen") or 0) > 0:
            honey += num(g.group(1))
            pollen += t["pollen"]
    if not pollen:          # no gain read: every trip's honey over its pollen
        honey = sum(t.get("honey") or 0 for t in trips)
        pollen = sum(t.get("pollen") or 0 for t in trips)
    return honey / pollen if pollen else 0.0


def convert_s_per_pollen(trips: list[dict]) -> float:
    """Seconds of convert-only rows (no field credited) per pollen gathered."""
    conv = sum(t.get("seconds") or 0 for t in trips if not t.get("credited") and t.get("converted"))
    pollen = sum(t.get("pollen") or 0 for t in trips)
    return conv / pollen if pollen else 0.0


def field_trips(trips: list[dict]) -> dict[str, list[tuple[float, float]]]:
    """{field: [(pollen banked, trip seconds)]}; a death banks nothing."""
    per = collections.defaultdict(list)
    for t in trips:
        f, s = t.get("credited"), t.get("seconds") or 0
        if not f or s <= 0:
            continue
        per[f].append((0.0 if t.get("deaths") else float(t.get("pollen") or 0), float(s)))
    return per


def field_values(per: dict, hpp: float, conv: float) -> dict[str, float]:
    """{field: honey/h} for fields with MIN_FIELD_TRIPS trips."""
    out = {}
    for f, rows in per.items():
        if len(rows) < MIN_FIELD_TRIPS:
            continue
        p = sum(r[0] for r in rows)
        s = sum(r[1] for r in rows)
        out[f] = hpp * p / (s + conv * p) * 3600 if s else 0.0
    return out


def trip_hours(per: dict) -> dict[str, float]:
    return {f: st.median(r[1] for r in rows) / 3600 for f, rows in per.items() if rows}


def quest_named(c: dict) -> bool:
    return QUEST_FIRST in (c.get("why") or "")


def rank_top(r: dict) -> str | None:
    """The rank's own pick: candidates are logged in `rank`'s order (its
    quest-first, colour-first and Pine-Tree-first sorts included), so the
    first reachable one scored above 0."""
    return next((c["field"] for c in r.get("candidates") or []
                 if c.get("reachable") and (c.get("score") or 0) > 0), None)


def weak_quest_best(cands: list[dict], field: str) -> str | None:
    """run_farm.weak_quest_best on logged candidates: the fastest field a weak
    quest trip gives way to, or None."""
    pick = next((c for c in cands if c["field"] == field), None)
    if pick is None or not quest_named(pick) or not (pick.get("rate") or 0) > 0:
        return None
    best = max((c for c in cands if c.get("reachable") and (c.get("score") or 0) > 0
                and (c.get("rate") or 0) > 0), key=lambda c: c["rate"], default=None)
    if best is None or best["field"] == field or pick["rate"] >= QUEST_WEAK_SHARE * best["rate"]:
        return None
    return best["field"]


def live_replay(rows: list[dict]) -> list[str | None]:
    """The live pick replayed: the rank's top, then run_farm's weak-quest
    alternation (a weak quest field every other trip; its memory, last_plan,
    lives as long as the process, so a new run forgets it)."""
    out, last, run = [], None, None
    for r in rows:
        if r.get("attempt") != run:
            last, run = None, r.get("attempt")
        top = rank_top(r)
        best = weak_quest_best(r.get("candidates") or [], top) if top else None
        if best is not None and last == top:
            out.append(best)
            last = None
        else:
            out.append(top)
            last = top if best is not None else None
    return out


def top_score(r: dict) -> str | None:
    ok = [c for c in r.get("candidates") or [] if c.get("reachable") and (c.get("score") or 0) > 0]
    return max(ok, key=lambda c: c["score"])["field"] if ok else None


def priced(values: dict, hours: dict, quest_honey: float):
    """Best measured field, a quest-named one worth `quest_honey` more a trip."""
    def rule(r: dict) -> str | None:
        best, val = None, -1.0
        for c in r.get("candidates") or []:
            f = c["field"]
            if not c.get("reachable") or (c.get("score") or 0) <= 0 or f not in values:
                continue
            v = values[f] + (quest_honey / max(hours.get(f, 0.1), 1e-3) if quest_named(c) else 0.0)
            if v > val:
                best, val = f, v
        return best
    return rule


def planner(trips: list[dict], quest_honeys, seed: int = 7) -> dict:
    rows = [t for t in trips if t.get("chosen_by") == "planner" and t.get("action") == "gather"
            and t.get("chosen") and t.get("candidates")]
    hpp, conv = hpp_of(trips), convert_s_per_pollen(trips)
    per = field_trips(trips)
    values, hours = field_values(per, hpp, conv), trip_hours(per)
    replayed = dict(zip((id(r) for r in rows), live_replay(rows)))
    rules = {"live (logged pick)": lambda r: r["chosen"],
             "live, replayed (rank + weak-quest alternation)": lambda r: replayed[id(r)],
             "rank's top only (no alternation)": rank_top,
             "top score, quests not first": top_score,
             "v2 shadow pick": lambda r: (r.get("v2") or {}).get("chosen")}
    for qh in quest_honeys:
        rules[f"best measured, quest worth {qh / 1e6:g}M/trip"] = priced(values, hours, qh)
    picks = {name: [rule(r) for r in rows] for name, rule in rules.items()}
    quest = [{c["field"] for c in r["candidates"] if quest_named(c)} for r in rows]
    live = picks["live (logged pick)"]

    def score(pk: list, idx, vals: dict, base: list | None = None):
        """(field honey/h, quest trips/h, decisions priced): a ratio over the
        decisions -- each pick's measured honey/h x its median trip, over the
        trips' hours -- restricted to decisions `base` prices too (paired)."""
        honey = hrs = qt = 0.0
        n = 0
        for i in idx:
            f = pk[i]
            if f not in vals or (base is not None and base[i] not in vals):
                continue
            h = hours[f]
            honey += vals[f] * h
            hrs += h
            qt += f in quest[i]
            n += 1
        return (honey / hrs, qt / hrs, n) if hrs else (None, None, 0)

    everything = range(len(rows))
    rng = random.Random(seed)
    boots = collections.defaultdict(list)
    for _ in range(BOOT):
        per_b = {f: [rng.choice(rs) for _ in rs] for f, rs in per.items()}
        vals_b = field_values(per_b, hpp, conv)
        idx = [rng.choice(everything) for _ in everything]
        for name, pk in picks.items():
            v, _, _ = score(pk, idx, vals_b, live)
            lv, _, _ = score(live, idx, vals_b, pk)
            if v is not None and lv:
                boots[name].append(v / lv - 1)
    out = []
    for name, pk in picks.items():
        judged = [(x, y) for x, y in zip(live, pk) if y is not None]
        v, qrate, n = score(pk, everything, values)
        pv, _, _ = score(pk, everything, values, live)
        lv, lq, _ = score(live, everything, values, pk)
        out.append({"rule": name, "decisions": len(judged),
                    "same_as_live": (sum(x == y for x, y in judged) / len(judged)) if judged else None,
                    "priced": n, "honey_h": v, "quest_trips_h": qrate,
                    "vs_live": (pv / lv - 1) if pv is not None and lv else None,
                    "lo": q(boots[name], 0.05) if boots[name] else None,
                    "hi": q(boots[name], 0.95) if boots[name] else None,
                    # the quest worth (honey a trip) at which this rule and live earn the same
                    "break_even_quest": ((pv - lv) / (lq - qrate)) if pv is not None and lv
                    and lq is not None and qrate is not None and abs(lq - qrate) > 1e-9 else None})
    return {"rows": len(rows), "hpp": hpp, "convert_s_per_pollen": conv,
            "fields": {f: {"honey_h": values[f], "trips": len(per[f]),
                           "trip_min": hours[f] * 60} for f in sorted(values, key=lambda f: -values[f])},
            "rules": out}


# ---- 2. convert timing --------------------------------------------------------
def convert_timing(trips: list[dict], points=(0.6, 0.7, 0.8, 0.9, 0.95, 1.0)) -> dict:
    hpp = hpp_of(trips)
    per = collections.defaultdict(lambda: {"pollen": 0.0, "gather": 0.0, "over": [], "deaths": 0,
                                           "cap": [], "n": 0})
    for t in trips:
        f, g = t.get("credited"), t.get("gather_seconds") or 0
        if not f or g <= 0:
            continue
        d = per[f]
        d["n"] += 1
        d["pollen"] += t.get("pollen") or 0
        d["gather"] += g
        d["deaths"] += t.get("deaths") or 0
        d["over"].append((t.get("seconds") or 0) - g)
        cap = (t.get("context") or {}).get("capacity")
        if cap:
            d["cap"].append(cap)
    # how often the bag is what ended a trip: the trip's pollen reached 85%
    # of the backpack (the live threshold is 90%; the HUD reads lag a little)
    full = sum(1 for t in trips if t.get("credited") and (t.get("context") or {}).get("capacity")
               and (t.get("pollen") or 0) >= 0.85 * t["context"]["capacity"])
    out = {}
    for f, d in per.items():
        if d["n"] < MIN_FIELD_TRIPS or not d["cap"] or d["pollen"] <= 0:
            continue
        rate, cap = d["pollen"] / d["gather"], st.median(d["cap"])
        lam, over = d["deaths"] / d["gather"], st.median(d["over"])
        row = {}
        for p in points:
            bag = p * cap
            gt = bag / rate
            # ponytail: the overhead is measured at the live ~90%, convert
            # included; the convert itself took 6-23 s after the press
            # (MEASURED 2026-10-26, 141 read converts), so its change with p
            # is left out
            row[p] = hpp * bag * math.exp(-lam * gt) / (gt + over) * 3600
        out[f] = {"trips": d["n"], "rate": rate, "capacity": cap, "overhead_s": over,
                  "deaths_per_h": lam * 3600, "honey_h": row}
    return {"fields": out, "threshold_ended": full, "trips": len(trips)}


# ---- 3. token brain -----------------------------------------------------------
DECISION = re.compile(r"token brain(?: \(second look\))?: (chase|return|hold)\b(?: (\w+)#\d+ at \((\d+), (\d+)\))?")
VALUE = re.compile(r"token brain value would: (chase|skip) (\w+) at \((\d+), (\d+)\) \(([+-][\d,]+)/s: "
                   r"worth ([\d,]+), detour ([\d.]+)s, gather ([\d,]+)/s, risk ([\d.]+)\)")
GATE = re.compile(r"token brain would: skip (\w+)#\d+ at \((\d+), (\d+)\) — (.*)$")
EARNED = re.compile(r"(honey|pollen) rose ([\d,]+) in [\d.]+s against ([\d,]+) expected")
HIDDEN = re.compile(r"hides a honey token under ([\d,]+)")


def num(s: str) -> float:
    return float(s.replace(",", "").replace("+", ""))


def parse_log(path: pathlib.Path) -> list[dict]:
    """Every live token-brain decision with the two shadows that follow it."""
    out, cur = [], None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        m = DECISION.search(line)
        if m:
            cur = {"action": m.group(1), "kind": m.group(2),
                   "xy": (int(m.group(3)), int(m.group(4))) if m.group(3) else None}
            out.append(cur)
            continue
        if cur is None:
            continue
        v = VALUE.search(line)
        if v:
            cur["value"] = {"verdict": v.group(1), "kind": v.group(2),
                            "xy": (int(v.group(3)), int(v.group(4))), "vps": num(v.group(5)),
                            "worth": num(v.group(6)), "detour": float(v.group(7)),
                            "gather": num(v.group(8)), "risk": float(v.group(9))}
            continue
        g = GATE.search(line)
        if g:
            cur["gate"] = g.group(4)
    return out


def replay_value(v: dict) -> str:
    """The value chooser's verdict recomputed from its logged inputs with this
    checkout's tokenbrain constants (fidelity check: should match the log)."""
    left = tb.CHASES_LOST_TO_A_REVERSAL * max(0.0, tb.MEAN_CHASE_NET_SEED)
    vps = (v["worth"] - v["gather"] * tb.LOSS_FRACTION * v["detour"] - v["risk"] * left) / v["detour"]
    return "chase" if vps > 0 else "skip"


def loss_fraction(lessons: list[dict]) -> float:
    """1 - median(rate_during / rate_before) over chases that collected
    nothing (tools/analysis/chase_lessons --detour-cost, without its window
    filter); the tokenbrain seed when there is nothing to measure."""
    ratios = [r["rate_during"] / r["rate_before"] for r in lessons
              if r.get("outcome") != "collected" and r.get("rate_during") is not None
              and (r.get("rate_before") or 0) > 0 and r["rate_during"] >= 0]
    return max(0.0, 1 - st.median(ratios)) if ratios else tb.LOSS_FRACTION


def earned(lesson: dict, hpp: float) -> tuple[float, float]:
    """(low, high) honey a chase earned over the trickle."""
    ev = str(lesson.get("evidence") or "")
    e = EARNED.search(ev)
    if e:
        got = max(0.0, num(e.group(2)) - num(e.group(3)))
        got *= hpp if e.group(1) == "pollen" else 1.0
        return got, got
    h = HIDDEN.search(ev)
    if h:
        return 0.0, num(h.group(1))
    return 0.0, 0.0


def tokens(var: pathlib.Path, trips: list[dict]) -> dict:
    runs = sorted({t["attempt"] for t in trips if isinstance(t.get("attempt"), int)})
    hpp = hpp_of(trips) or tb.HONEY_PER_POLLEN_SEED
    lessons = [r for r in load_jsonl(var / "school-coins" / "lessons.jsonl")
               if r.get("attempt") in set(runs)]
    loss = loss_fraction(lessons)
    by_key = {}
    for r in lessons:
        by_key.setdefault((r["attempt"], r["x"], r["y"]), r)
    decisions = []
    hours = 0.0
    for run in runs:
        d = parse_log(var / "night" / f"run-{run}.log")
        if d:
            hours += sum(t.get("seconds") or 0 for t in trips if t.get("attempt") == run) / 3600
        for x in d:
            x["run"] = run
        decisions += d
    acts = collections.Counter(d["action"] for d in decisions)
    chases = [d for d in decisions if d["action"] == "chase" and d["xy"]]
    vals = [d for d in decisions if "value" in d]
    fidelity = sum(replay_value(d["value"]) == d["value"]["verdict"] for d in vals)
    gathers = [d["value"]["gather"] for d in vals]
    g_med = st.median(gathers) if gathers else 0.0
    priced_rows = []
    for d in chases:
        lesson = by_key.get((d["run"], d["xy"][0], d["xy"][1]))
        if lesson is None:
            continue
        px = math.hypot(lesson["x"] - ANCHOR[0], lesson["y"] - ANCHOR[1])
        gather = d.get("value", {}).get("gather", g_med)
        cost = gather * loss * tb.detour_s(px)
        lo, hi = earned(lesson, hpp)
        v = d.get("value")
        value_keeps = v is not None and v["verdict"] == "chase" and v["xy"] == d["xy"]
        priced_rows.append({"kind": lesson["kind"], "lo": lo - cost, "hi": hi - cost, "cost": cost,
                            "value_keeps": value_keeps if v is not None else None,
                            "gate_keeps": "gate" not in d})
    # rules: which priced chases each drops
    rules = {"honey-token weight 0 (no honey chases)": lambda r: r["kind"] == "honey",
             "value chooser live (drop its skips)": lambda r: r["value_keeps"] is False,
             "lifetime/leash gate live (drop its skips)": lambda r: not r["gate_keeps"],
             "chase nothing": lambda r: True}
    for k in sorted({r["kind"] for r in priced_rows}):
        rules[f"weight 0 for {k}"] = (lambda kk: lambda r: r["kind"] == kk)(k)
    out_rules = []
    for name, drops in rules.items():
        dropped = [r for r in priced_rows if drops(r)]
        lo = -sum(r["lo"] for r in dropped)
        hi = -sum(r["hi"] for r in dropped)
        out_rules.append({"rule": name, "dropped": len(dropped),
                          "same_as_live": 1 - len(dropped) / len(priced_rows) if priced_rows else None,
                          "delta_h_low": lo / hours if hours else None,     # hidden lumps = 0
                          "delta_h_high": hi / hours if hours else None})   # hidden lumps at their bound
    by_kind = collections.defaultdict(list)
    for r in priced_rows:
        by_kind[r["kind"]].append(r)
    return {"runs": len(runs), "hours": hours, "decisions": dict(acts), "chases": len(chases),
            "priced": len(priced_rows), "loss_fraction": loss, "gather_median": g_med,
            "value_lines": len(vals), "value_replay_same": fidelity / len(vals) if vals else None,
            "value_same_as_live": (sum(1 for d in chases if d.get("value", {}).get("verdict") == "chase"
                                       and d["value"]["xy"] == d["xy"]) /
                                   max(1, sum(1 for d in chases if "value" in d))),
            "gate_same_as_live": 1 - sum("gate" in d for d in chases) / max(1, len(chases)),
            "per_chase": {k: {"n": len(v), "net_low": st.mean(r["lo"] for r in v),
                              "net_high": st.mean(r["hi"] for r in v),
                              "cost": st.mean(r["cost"] for r in v)} for k, v in by_kind.items()},
            "rules": out_rules}


# ---- report -------------------------------------------------------------------
def m(x, d=1) -> str:
    return "-" if x is None else f"{x / 1e6:,.{d}f}M"


def sg(x) -> str:
    return "-" if x is None else f"{100 * x:+.1f}%"


def pc(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def report(res: dict) -> str:
    p, c, t = res["planner"], res["convert"], res["tokens"]
    L = [f"# Simulator: last {res['days']:g} days ({res['trips']} trips, runs {res['first_run']}-{res['last_run']})", "",
         f"## 1. Planner ({p['rows']} planner gather decisions; honey/pollen {p['hpp']:.2f}, "
         f"convert {p['convert_s_per_pollen'] * 1e6:.1f} s per M pollen)", "",
         "| rule | % same as live | priced | field honey/h | vs live (paired) | 90% CI | quest trips/h | "
         "break-even quest honey/trip |", "|---|---|---|---|---|---|---|---|"]
    for r in p["rules"]:
        be = r["break_even_quest"]
        L.append(f"| {r['rule']} | {pc(r['same_as_live'])} | {r['priced']}/{r['decisions']} | "
                 f"{m(r['honey_h'])} | {sg(r['vs_live'])} | {sg(r['lo'])} to {sg(r['hi'])} | "
                 f"{'-' if r['quest_trips_h'] is None else f'{r[chr(113) + "uest_trips_h"]:.2f}'} | "
                 f"{'-' if be is None or be < 0 else m(be)} |")
    L += ["", "| field | trips | median trip min | measured honey/h |", "|---|---|---|---|"]
    for f, v in p["fields"].items():
        L.append(f"| {f} | {v['trips']} | {v['trip_min']:.1f} | {m(v['honey_h'])} |")
    pts = sorted({k for v in c["fields"].values() for k in v["honey_h"]})
    L += ["", f"## 2. Convert timing ({c['threshold_ended']} of {c['trips']} trips gathered 85%+ of the backpack)", "",
          "| field | trips | pollen/s | overhead s | deaths/h | " + " | ".join(f"{int(k * 100)}%" for k in pts) + " |",
          "|---|---|---|---|---|" + "---|" * len(pts)]
    for f, v in sorted(c["fields"].items(), key=lambda kv: -kv[1]["trips"]):
        L.append(f"| {f} | {v['trips']} | {v['rate']:,.0f} | {v['overhead_s']:.0f} | {v['deaths_per_h']:.2f} | "
                 + " | ".join(m(v["honey_h"][k]) for k in pts) + " |")
    L += ["", f"## 3. Token brain ({t['chases']} live chases in {t['runs']} runs, {t['hours']:.1f} trip hours; "
          f"{t['priced']} joined to a lesson; loss fraction measured {t['loss_fraction']:.2f})", "",
          f"- decisions: {t['decisions']}",
          f"- value chooser replayed from its logged inputs: {pc(t['value_replay_same'])} same verdict as logged "
          f"({t['value_lines']} lines)",
          f"- value chooser agrees with the live chase: {pc(t['value_same_as_live'])}; "
          f"lifetime/leash gate keeps {pc(t['gate_same_as_live'])} of live chases", "",
          "| rule | chases dropped | % same as live | honey/h change, hidden lumps 0 | at their bound |",
          "|---|---|---|---|---|"]
    for r in t["rules"]:
        L.append(f"| {r['rule']} | {r['dropped']} | {pc(r['same_as_live'])} | "
                 f"{m(r['delta_h_low'], 2)} | {m(r['delta_h_high'], 2)} |")
    L += ["", "| kind | chases | net honey/chase low | high | detour cost/chase |", "|---|---|---|---|---|"]
    for k, v in t["per_chase"].items():
        L.append(f"| {k} | {v['n']} | {v['net_low']:,.0f} | {v['net_high']:,.0f} | {v['cost']:,.0f} |")
    return "\n".join(L) + "\n"


def simulate(var: pathlib.Path, days: float, quest_honeys=DEFAULT_QUEST_HONEY) -> dict:
    trips = window(load_jsonl(var / "trips.jsonl"), days)
    runs = [t["attempt"] for t in trips if isinstance(t.get("attempt"), int)]
    return {"days": days, "trips": len(trips), "first_run": min(runs, default=None),
            "last_run": max(runs, default=None), "planner": planner(trips, quest_honeys),
            "convert": convert_timing(trips), "tokens": tokens(var, trips)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--var", default=str(pathlib.Path.home() / "Hivemind" / "var"))
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--quest-honey", default=",".join(f"{x:g}" for x in DEFAULT_QUEST_HONEY),
                    help="quest worths (honey a trip) to price, comma-separated")
    ap.add_argument("--json", help="also write the full result here")
    a = ap.parse_args()
    res = simulate(pathlib.Path(a.var), a.days, [float(x) for x in a.quest_honey.split(",")])
    if not res["trips"]:
        print("no trips in the window")
        return 1
    print(report(res), end="")
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

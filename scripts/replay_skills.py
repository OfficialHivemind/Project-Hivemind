#!/usr/bin/env python3
"""Rebuild var/skill_stats.json from the trip ledger and print every route's
record, so the owner can see which routes are bad (DESIGN 8dy).

The live bot folds each trip into var/skill_stats.json as the trip ends
(brain/skills). This rebuilds the same book from nothing: every row of
var/trips.jsonl, settled by the rows' own `routes` where they carry them and,
for the rows written before they did, by the route frames saved under
var/routes/attempt-N, the search-by-sight frames under var/homing/attempt-N
and the run log var/night/run-N.log. Nothing here touches the game.

    ./scripts/replay_skills.py                 # print, and write the book
    ./scripts/replay_skills.py --dry-run       # print only
    ./scripts/replay_skills.py --rows 337      # the ledger as the plan read it
    ./scripts/replay_skills.py --windows       # every ten-verdict window
    ./scripts/replay_skills.py --var DIR --out FILE

Run it while the bot is running and the two write the same file: use --out
somewhere else, or --dry-run.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hivemind.brain import skills                               # noqa: E402
from hivemind.nav.router import Router                          # noqa: E402


def farm_constant(name: str, default: float) -> float:
    """A number from scripts/run_farm.py, read without running it -- the
    measured recovery a failed route pays is run_farm's, and lives there."""
    try:
        tree = ast.parse((ROOT / "scripts" / "run_farm.py").read_text())
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and getattr(node.targets[0], "id", "") == name):
                return float(ast.literal_eval(node.value))
    except (OSError, SyntaxError, ValueError):
        pass
    return default


def walkspeed() -> float:
    try:
        from hivemind.world.settings import Settings
        return float(Settings().float("move.walkspeed"))
    except Exception:                                # noqa: BLE001
        return 28.0


def pct(a: int, b: int) -> str:
    return f"{a / b:.0%}" if b else "—"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--var", type=pathlib.Path, default=ROOT / "var",
                    help="the var/ folder to read (default: this checkout's)")
    ap.add_argument("--out", type=pathlib.Path, default=None,
                    help="where to write the book (default: <var>/skill_stats.json)")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    ap.add_argument("--rows", type=int, default=None,
                    help="only the first N ledger rows (the plan read 337)")
    ap.add_argument("--windows", action="store_true",
                    help="each route's ten-verdict windows, lowest and highest")
    args = ap.parse_args()

    router = Router()
    fields = skills.field_nodes(router)
    rows = skills.ledger_rows(args.var / "trips.jsonl")
    if args.rows is not None:
        rows = rows[:args.rows]
    if not rows:
        print(f"no ledger rows in {args.var / 'trips.jsonl'}")
        return 1
    began = time.monotonic()
    settled = skills.trips_with_routes(args.var, fields, rows=rows)
    out_path = None if args.dry_run else (args.out or args.var / "skill_stats.json")
    book = skills.SkillBook(out_path)
    for row, items in settled:
        book.fold_items(items, at=float(row.get("at") or 0.0))
        book.folded_to = max(book.folded_to, float(row.get("at") or 0.0))
    book.built = (f"rebuilt {time.strftime('%Y-%m-%d %H:%M')} by "
                  f"scripts/replay_skills.py from {len(rows)} ledger row(s)")
    book.watch_steps(router)
    speed = walkspeed()
    recovery = farm_constant("RESPAWN_TO_TRIP_SECONDS", 9.0)
    first, last = rows[0]["at"], rows[-1]["at"]
    print(f"{len(rows)} ledger rows, {time.strftime('%Y-%m-%d %H:%M', time.localtime(first))}"
          f" to {time.strftime('%Y-%m-%d %H:%M', time.localtime(last))}; settled in "
          f"{time.monotonic() - began:.1f}s")
    carried = sum(1 for row, _ in settled if isinstance(row.get("routes"), list))
    print(f"{carried} row(s) carried their own routes; the rest were settled from "
          f"var/routes, var/homing and var/night")
    print()

    # ---- the plan's table, by the field aimed at ------------------------
    raw = skills.aimed_table(rows, raw=True)
    fixed = skills.aimed_table(rows)
    gathering = sum(sum(v) for v in raw.values())
    named = sum(v[0] + v[1] for v in raw.values())
    wrong = sum(v[1] for v in raw.values())
    wrong_fixed = sum(v[1] for v in fixed.values())
    print("BY THE FIELD AIMED AT (gathering trips, over 30 s of gathering) — "
          "the game-AI plan's table")
    print(f"  {gathering} gathering trips; the feed named a field on {named}, and "
          f"{wrong} ({pct(wrong, named)}) were somewhere other than the aim "
          f"({wrong_fixed} once 'rose_field' and 'rose' are the same field)")
    print(f"  {'aimed at':<14}{'landed':>8}{'elsewhere':>11}{'never named':>13}")
    for aim, (good, bad, none) in sorted(raw.items(), key=lambda kv: str(kv[0])):
        print(f"  {str(aim):<14}{good:>8}{bad:>11}{none:>13}")
    print()

    # ---- every route -----------------------------------------------------
    print(f"EVERY ROUTE — all time, then the last {skills.SKILL_WINDOW} verdicts the "
          f"posterior is over (Beta(1,1) prior); quarantined when "
          f"{skills.QUARANTINE_SURE:.0%} sure it lands under "
          f"{skills.QUARANTINE_BELOW:.0%}")
    print(f"  {'route':<40}{'kind':<7}{'land':>5}{'else':>5}{'unk':>5}{'miss':>5}"
          f"{'  last':>7}{'P':>6}{'P<.5':>6}{'land s':>7}{'fail s':>7}  status")
    for r in book.table():
        good, bad = r["window"]
        status = ("QUARANTINED" if r["quarantined"] else
                  "no verdict yet" if not good + bad else "")
        med = f"{r['median_s']:.0f}" if r["median_s"] else "—"
        fail = f"{r['fail_s']:.0f}" if r["fail_s"] else "—"
        print(f"  {r['route']:<40}{r['kind']:<7}{r['landed']:>5}{r['elsewhere']:>5}"
              f"{r['unknown']:>5}{r['missed']:>5}{f'{good}/{good + bad}':>7}"
              f"{r['p_land']:>6.2f}{r['sure_below']:>6.2f}{med:>7}{fail:>7}  {status}")
    print()

    # ---- walk against flight, where a field has both ---------------------
    names = {e.name: e for e in router.edges}
    both = sorted(t for t in fields
                  if f"natro_out_{t}" in names and f"natro_out_{t}_via_red_cannon" in names
                  and (book.get(f"natro_out_{t}") or book.get(f"natro_out_{t}_via_red_cannon")))
    print(f"WALK OR FLIGHT, as the farm's route choice prices them now: "
          f"length / P + (1 - P) x (failure s + {recovery:.0f} s recovery) x "
          f"{speed:g} studs/s, the length being its landed runs' median seconds "
          f"x {speed:g} (its recorded studs until it has any); the cannon "
          f"record's grounding after a miss still comes first")
    for target in both:
        walk, flight = f"natro_out_{target}", f"natro_out_{target}_via_red_cannon"
        choice = book.choose([(walk, names[walk].studs), (flight, names[flight].studs)],
                             walkspeed=speed, recovery_seconds=recovery,
                             labels={walk: "the walk", flight: "the flight"})
        pick = "flight" if choice.route == flight else "walk"
        print(f"  {target:<14} -> {pick:<7} {choice.why}")
    print()

    # ---- the router's shortest path, by studs and by measured cost --------
    print("THE ROUTER'S PATH FROM THE HIVE, by studs (as before) and by measured "
          "cost (nav/router edge_price) — only where the two differ")
    priced = Router()
    priced.edge_price = lambda edge: book.edge_cost(
        edge.name, edge.studs, walkspeed=speed, recovery_seconds=recovery)
    changed = 0
    for target in sorted(fields):
        old, new = router.route("hive", target), priced.route("hive", target)
        old_names = [leg.name for leg in old.legs] if old else []
        new_names = [leg.name for leg in new.legs] if new else []
        if old_names != new_names:
            changed += 1
            print(f"  {target:<14} {' + '.join(old_names) or '—'}  ->  "
                  f"{' + '.join(new_names) or '—'}")
    if not changed:
        print("  none")
    print()

    quarantined = book.quarantine_list()
    print("QUARANTINED — a field's walk or flight is not taken while the other is "
          "allowed; a walk home or an errand has no other route and is still "
          "walked; the morning report lists them all for the owner")
    for s in quarantined:
        print(f"  {s.route} ({s.kind} to {s.target.replace('_', ' ')}): {s.record()}")
    if not quarantined:
        print("  none")

    # ---- the live verdicts against the history's, on the same trips ------
    if carried:
        print()
        print("LIVE AGAINST HISTORY — each row that carries its own routes, "
              "settled again from its frames and run log as the history is")
        pairs = skills.live_against_history(args.var, fields, rows=rows)
        tally: dict = {}
        differ = []
        for row, item, inferred in pairs:
            if item.get("outcome") not in skills.VERDICTS and inferred not in skills.VERDICTS:
                continue                  # neither judged it
            got = tally.setdefault(item.get("kind") or "?", [0, 0])
            same = item.get("outcome") == inferred
            got[0 if same else 1] += 1
            if not same:
                differ.append((row, item, inferred))
        for kind, (same, other) in sorted(tally.items()):
            print(f"  {kind:<7} {same} verdict(s) agree, {other} differ")
        for row, item, inferred in differ[:30]:
            print(f"  attempt {row.get('attempt')} "
                  f"{time.strftime('%m-%d %H:%M', time.localtime(float(row['at'])))} "
                  f"{item.get('route')}: live {item.get('outcome')}, "
                  f"history {inferred or 'no such run'}")
        if not tally:
            print("  no verdict on either side yet")

    if args.windows:
        print()
        print(f"EVERY {skills.SKILL_WINDOW}-VERDICT WINDOW, per route (landings in "
              f"the window: lowest-highest, and the sequence)")
        seq: dict = {}
        for row, items in settled:
            for item in items:
                if item.get("outcome") in skills.VERDICTS:
                    seq.setdefault(item["route"], []).append(
                        (row.get("attempt"), item["outcome"]))
        for route, got in sorted(seq.items()):
            marks = [1 if o == "landed" else 0 for _a, o in got]
            wins = [sum(marks[i:i + skills.SKILL_WINDOW])
                    for i in range(0, max(1, len(marks) - skills.SKILL_WINDOW + 1))]
            span = (f"{min(wins)}-{max(wins)}" if len(marks) >= skills.SKILL_WINDOW
                    else f"only {len(marks)} verdict(s)")
            print(f"  {route:<40} {span:<18} "
                  + " ".join(f"{a}{'L' if o == 'landed' else 'e'}" for a, o in got))

    if out_path is not None:
        book.save()
        print()
        print(f"written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""N1-N3 before/after: three days of planters played out three ways on the
same start (brain/nectarplan.simulate, the same nectar and growth model for all):

  today  -- the errand as it runs live: act/planter.errand_target picks the
            field (the nectar furthest under its minimum), next_step the
            planter (the first held, in table order)
  greedy -- each free slot to the best nectar gained per slot-hour
  plan   -- brain/nectarplan.plan re-run whenever a slot is free (as the
            errand re-runs it), its placements made on that round

Prints each nectar's mean level, the value a day (nectarplan.day_value
summed) and the slot-hours used a day. Offline, reads nothing live.

  PYTHONPATH=src python tools/planter_plan_sim.py
"""
from __future__ import annotations

import time

from hivemind.act import planter as p
from hivemind.brain import nectarplan as npl

DAYS = 3                     # played out 3 days: the plan's own 24 h look-ahead is rolled
REACH = {f for fs in p.NECTAR_FIELDS.values() for f in fs}
TITLE = {k: row[0] for k, row in p.PLANTERS.items()}


def today(owned):
    def choose(st, left, lv, t):
        have = {TITLE[k] for k, c in left.items() if c > 0} & owned
        target = p.errand_target(st, have, lv, REACH - {b.get("field") for b in
                                                      (st.get("out") or {}).values()}, t)
        if target is None:
            return None
        step = p.next_step(st, target[0], have, t, levels=lv)
        return (step[1], target[0]) if step and step[0] == "place" else None
    return choose


def planned(owned, held):
    queue = {}                   # the plan's placements of this round (the errand's batch)

    def choose(st, left, lv, t):
        if queue.get("t") != t or not queue.get("place"):
            have = {TITLE[k] for k, c in left.items() if c > 0} & owned
            got = npl.plan(st, have, held, lv, REACH, t)
            queue.update(t=t, place=list(got["place"]) if got else [])
        return queue["place"].pop(0) if queue["place"] else None
    return choose


def run(name, owned, held, levels, degradation=None):
    keys = [k for k in p.PLANTERS if TITLE[k] in owned]
    counts = {k: (held.get(k, 1) if k in p.SINGLE_USE else 1) for k in keys}
    state = {"degradation": degradation or {}}
    print(f"\n== {name}: {', '.join(sorted(owned))}; start "
          + " ".join(f"{n[:4]} {levels[n]:.0f}" for n in p.NECTAR_ORDER))
    for label, choose in (("today", today(owned)), ("greedy", None),
                          ("plan", planned(owned, held))):
        t0 = time.process_time()
        means = dict.fromkeys(p.NECTAR_ORDER, 0.0)
        steps = int(DAYS * 24 * 3600 / npl.PLAN_STEP_S)

        score, tracks = npl.simulate(state, counts, levels, REACH, 0.0, choose=choose,
                                     hours=DAYS * 24)
        cpu = time.process_time() - t0
        lv = dict(levels)
        for i in range(steps):
            t = i * npl.PLAN_STEP_S
            for k, f, at, done in tracks:
                if done is not None and t <= done < t + npl.PLAN_STEP_S:
                    lv[p.NECTAR[f]] = min(100.0, lv[p.NECTAR[f]] + p.nectar_added(k, f))
            for n in means:
                means[n] += lv[n] / steps
            lv = {n: max(0.0, v - 100.0 * npl.PLAN_STEP_S / 86400) for n, v in lv.items()}
        used = sum(((done if done is not None else steps * npl.PLAN_STEP_S) - at)
                   for _k, _f, at, done in tracks) / 3600
        # FIELD WEAR GROWN THROUGH: a harvest's hours past its table time, lag and
        # the sim's 15-min clock (plantdeg, 2026-10-27)
        wear = sum(max(0.0, done - at - npl.HARVEST_LAG_S - npl.PLAN_STEP_S - p.grow_s(k, f))
                   for k, f, at, done in tracks if done is not None) / 3600
        firsts = ", ".join(f"{k.split('_')[0]}>{f}" for k, f, *_r in tracks[:3])
        print(f"  {label:6s} value/day {score / DAYS:7.0f}  mean% "
              + " ".join(f"{means[n]:5.1f}" for n in p.NECTAR_ORDER)
              + f"  slot-h/day {used / DAYS:4.1f}/72  harvests {sum(1 for t in tracks if t[3] is not None):2d}"
              f"  wear-h/day {wear / DAYS:3.1f}  cpu {cpu:5.2f}s  first: {firsts}")


if __name__ == "__main__":
    zero = dict.fromkeys(p.NECTAR_ORDER, 0.0)
    # THE ACCOUNT TODAY (var/inventory.json 2026-10-26: Paper 58; Blue Clay owned)
    run("today's bag, nectar empty (the norm: var/trips.jsonl 23-26 Oct)",
        {"Blue Clay Planter", "Paper Planter"}, {"paper_planter": 58}, zero)
    run("+ the Plastic Planter it is buying (brain/buyer)",
        {"Blue Clay Planter", "Paper Planter", "Plastic Planter"}, {"paper_planter": 58}, zero)
    run("+ a Ticket Planter, Comforting already 60%",
        {"Blue Clay Planter", "Paper Planter", "Ticket Planter"},
        {"paper_planter": 58, "ticket_planter": 1}, dict(zero, comforting=60.0))
    run("mid-game: Blue Clay, Red Clay, Tacky, nectar half",
        {"Blue Clay Planter", "Red Clay Planter", "Tacky Planter"}, {},
        dict.fromkeys(p.NECTAR_ORDER, 50.0))
    run("end-game: Hydroponic, Petal, Planter Of Plenty",
        {"Hydroponic Planter", "Petal Planter", "The Planter Of Plenty"}, {}, zero)

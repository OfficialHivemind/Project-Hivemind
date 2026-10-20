"""Minimal off-policy check on trips.jsonl: SNIPS + DR for a new field rule.

Reward = honey per wall second of the trip. r_hat (the direct-method model) is
the planner's own logged per-field pollen/s x a global honey-per-pollen ratio x
the share of the trip spent gathering. `p_key` (default "p_field", logged since 2026-10-11 P3) names the FIELD pick's
logged probability; until one is logged it falls back to 1 (deterministic), and
then only the matched rows carry information.
"""
import json, sys

def rows(path):
    for line in open(path):
        try: r = json.loads(line)
        except ValueError: continue
        if (r.get("chosen_by") == "planner" and r.get("chosen") and r.get("honey") is not None
                and r.get("pollen") and r.get("seconds")):
            yield r

def evaluate(path, new_rule, p_key="p_field", clip=20.0):
    data = list(rows(path))
    hpp = sum(r["honey"] for r in data) / sum(r["pollen"] for r in data)
    est = []
    for r in data:
        cands = {c["field"]: c for c in r["candidates"]}
        share = r.get("gather_seconds", 0) / r["seconds"]
        rhat = lambda f: (cands[f]["rate"] or 0) * hpp * share if f in cands else 0.0
        a, b, y = r["chosen"], new_rule(r), r["honey"] / r["seconds"]
        w = min((a == b) / (r.get(p_key) or 1.0), clip)
        est.append((w, y, rhat(b), rhat(a)))
    sw = sum(e[0] for e in est); sw2 = sum(e[0] ** 2 for e in est)
    return {"n": len(est), "match": sum(e[0] > 0 for e in est), "ess": round(sw * sw / sw2, 1) if sw2 else 0,
            "logged": round(sum(e[1] for e in est) / len(est)),
            "snips": round(sum(w * y for w, y, *_ in est) / sw) if sw else None,
            "dm": round(sum(e[2] for e in est) / len(est)),
            "dr": round(sum(rb + w * (y - ra) for w, y, rb, ra in est) / len(est))}

if __name__ == "__main__":
    path = sys.argv[1]
    same = evaluate(path, lambda r: r["chosen"])
    assert same["snips"] == same["logged"], same            # the logged rule must score as logged
    best_rate = lambda r: max((c for c in r["candidates"] if c.get("reachable")), key=lambda c: c["rate"] or 0)["field"]
    print("logged rule  ", same)
    print("argmax(rate) ", evaluate(path, best_rate))

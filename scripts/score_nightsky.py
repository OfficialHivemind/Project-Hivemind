#!/usr/bin/env python3
"""Night by the sky against night by the floor, on our own frames (vision/night).

    ./.venv/bin/python scripts/score_nightsky.py [--var ~/Hivemind/var] [--json out.json]

Reads only; writes nothing unless --json. Four counts (docs/pending/nightsky.md):
  1. FLIGHTS: every natro_out_*cannon* route with a `00-start` frame -- the
     floor's verdict on that pad frame (the rule before this change) against
     the sky's on the route's own frames up to 25 s later (the cannon flight
     shows open sky). One moment per route; a route whose flight saw both a
     night and a day frame is the switch itself, counted apart.
  2. PAD: the same start frames through the old rule and the new is_night --
     how many verdicts the change moves where the bot decides today.
  3. ELSEWHERE: every kept frame in shops, menus, hive looks, hunts, fields
     (var/<dir>/**.jpg): how often the sky speaks at all, by folder.
  4. HUNTS: each Vicious hunt (var/vicious/<stamp>/) frame by frame -- when
     the sky first reads day, and how long the hunt went on after.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import sys

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.vision import night     # noqa: E402

ELSEWHERE = ("shoplook", "homing", "places", "planters", "memorymatch", "commando",
             "bears", "beetle", "crab", "tunnelbear", "antchallenge", "respawn")
STAMP = re.compile(r"^(\d{6})-")


def floor_only(frame) -> bool:
    got = night.shares(frame)
    return got is not None and got[0] >= night.NIGHT_MIN and got[1] < night.DAY_MAX


def secs(name: str) -> int:
    s = STAMP.match(name).group(1)
    return int(s[:2]) * 3600 + int(s[2:4]) * 60 + int(s[4:6])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--var", default=os.path.expanduser("~/Hivemind/var"))
    ap.add_argument("--json")
    a = ap.parse_args()
    var = pathlib.Path(a.var)
    cv2.setNumThreads(1)
    out: dict = {}

    flights, pad, routes = collections.Counter(), collections.Counter(), 0
    for d in sorted(var.glob("routes/attempt-*")):
        names = sorted(os.listdir(d))
        for start in (f for f in names if "-natro_out_" in f and f.endswith("-00-start.jpg")):
            frame = cv2.imread(str(d / start))
            if frame is None:
                continue
            old, new = floor_only(frame), night.is_night(frame)
            pad[(old, new)] += 1
            if "cannon" not in start:
                continue
            routes += 1
            route, t0 = start.split("-")[1], secs(start)
            seen = set()
            for f in names:
                if f <= start or f"-{route}-" not in f or not STAMP.match(f):
                    continue
                if not 0 <= secs(f) - t0 <= 25:
                    continue
                s = night.sky(cv2.imread(str(d / f)))
                if s:
                    seen.add(s)
            truth = "switch" if len(seen) == 2 else (seen.pop() if seen else "no sky")
            flights[(truth, "floor night" if old else "floor day")] += 1
    out["flights"] = {f"{k[0]} / {k[1]}": v for k, v in sorted(flights.items())}
    out["flight_routes"] = routes
    out["pad"] = {f"old {k[0]} -> new {k[1]}": v for k, v in sorted(pad.items())}

    where = {}
    for sub in ELSEWHERE:
        c = collections.Counter()
        for p in var.glob(f"{sub}/**/*.jpg"):
            frame = cv2.imread(str(p))
            if frame is not None:
                c[night.sky(frame) or "none"] += 1
        where[sub] = dict(c)
    out["elsewhere"] = where

    hunts = []
    for d in sorted(var.glob("vicious/*/")):
        frames = sorted(d.glob("*.jpg"))
        if not frames:
            continue
        t = [float(p.name.split("-")[0]) for p in frames]
        said = [night.sky(cv2.imread(str(p))) for p in frames]
        day_at = next((t[i] for i, s in enumerate(said) if s == "day"), None)
        hunts.append({"hunt": d.name, "frames": len(frames), "night": said.count("night"),
                      "day": said.count("day"), "first_day_s": day_at, "last_s": t[-1],
                      "after_day_s": None if day_at is None else round(t[-1] - day_at, 1)})
    out["hunts"] = hunts
    print(json.dumps(out, indent=1))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

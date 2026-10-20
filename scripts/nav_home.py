#!/usr/bin/env python3
"""Can the model walk home better than the recorded route can?

The recorded return leg fails the same way every time -- up a ramp, a glide
into the ground, into a wall, into the trophy store. A script cannot notice
any of that. This asks the model instead: look, pick a direction, walk a
couple of seconds, look again.

Arrival is NOT the model's call. `vision.banner` reading "Make Honey" is what
says we are at the hive, because that has been measured on real frames.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                              # noqa: E402
from hivemind.act.hive import TRANSCRIBE, sweep_and_claim       # noqa: E402
from hivemind.act.routes import RouteRunner                     # noqa: E402
from hivemind.brain.navigator import Navigator                  # noqa: E402
from hivemind.brain.vlm import VisionModel                      # noqa: E402
from hivemind.nav.router import Router                          # noqa: E402
from hivemind.vision import banner                              # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "var" / "navhome"
GOAL = ("walk back to your own beehive in the hive area so you can deposit "
        "your pollen. The hive area is a row of hives with yellow honeycomb "
        "walls around it.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=25)
    ap.add_argument("--skip-outbound", action="store_true",
                    help="navigate home from wherever we spawn")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    model = VisionModel()
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture

    def panel_text(frame):
        found = banner.find(frame)
        if found is None:
            return None
        ok, buf = cv2.imencode(".png", found.crop(frame)[:, :, :3])
        if not ok or not model.available():
            return None
        answer = model.ask(buf.tobytes(), TRANSCRIBE)
        text = getattr(answer, "text", answer)
        return text if isinstance(text, str) else None

    def at_hive() -> bool:
        try:
            text = panel_text(cap.capture())
        except Exception:
            return False
        return bool(text and "make honey" in " ".join(text.lower().split()))

    step = {"n": 0}

    def note(event):
        text = getattr(event, "text", "")
        if text:
            step["n"] += 1
            print(f"    {step['n']:2d}. {text}", flush=True)
            try:
                cv2.imwrite(str(OUT / f"{step['n']:02d}.png"),
                            cap.capture()[:, :, :3])
            except Exception:
                pass

    try:
        print("\n  claiming a hive...", flush=True)
        claimed = sweep_and_claim(inp, cap.capture, panel_text,
                                  on_note=lambda t: print(f"    {t}", flush=True))
        print(f"  -> {claimed.describe()}", flush=True)
        if not claimed.ok:
            return 2

        if not args.skip_outbound:
            print("\n  riding the cannon out to Pine Tree...", flush=True)
            runner = RouteRunner(inp, Router(), walkspeed=28.0)
            out = runner.run("from_hive_to_pine_tree_with_red_cannon")
            print(f"  -> {out.describe()}", flush=True)

        print(f"\n  asking the model to walk home ({args.steps} steps max):",
              flush=True)
        started = time.monotonic()
        nav = Navigator(inp, cap.capture, model, arrived=at_hive, emit=note)
        ok = nav.go(GOAL, max_steps=args.steps)
        took = time.monotonic() - started

        print(f"\n  {'HOME' if ok else 'did not get home'} after "
              f"{nav.steps} decisions in {took:.0f}s "
              f"({nav.unknowns} unknowns)", flush=True)
        return 0 if ok else 3
    finally:
        try:
            model.unload()
        except Exception:
            pass
        ready.close()
        print(f"  frames in {OUT}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

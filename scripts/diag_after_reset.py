#!/usr/bin/env python3
"""How long after a reset can the character actually move?

The forager measured 0.0 px of flow in every direction after resetting, while
an earlier diagnostic that did NOT reset first measured w 0.22, s 2.20, a 10.99,
d 11.35 on the same spot. Zero in every direction is not "blocked" -- it is not
moving at all.

So this times it: reset, then probe forward repeatedly and report when the
scene starts moving. If movement resumes at some delay, RESET_SETTLE is simply
too short and the fix is a number. If it never resumes, the reset leaves the
character in a state that needs something else -- claiming a hive, most likely,
since a reset kills the character and "your bees must recover at the hive".
"""
import pathlib
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                          # noqa: E402
from hivemind.act.routes import RouteResult, RouteRunner    # noqa: E402
from hivemind.brain.vlm import VisionModel                  # noqa: E402
from hivemind.nav.router import Router                      # noqa: E402
from hivemind.platform.current import memory                        # noqa: E402
from hivemind.vision import screenstate as ss               # noqa: E402
from hivemind.vision.flow import FlowTracker                # noqa: E402

OUT = pathlib.Path("/tmp/hivemind-diag/afterreset")


def flow_for(inp, cap, key, seconds=1.5):
    tracker = FlowTracker()
    tracker.update(cap.capture())
    seen = []
    try:
        inp.press(key)
        end = time.monotonic() + seconds
        while True:
            s = tracker.update(cap.capture())
            if s is not None and s.pairs is not None and len(s.pairs):
                d = s.pairs[:, 1, :] - s.pairs[:, 0, :]
                seen.append(float(np.median(np.linalg.norm(d, axis=1))))
            if time.monotonic() >= end:
                break
            time.sleep(0.03)
    finally:
        inp.release(key)
    time.sleep(0.3)
    return float(np.median(seen)) if seen else 0.0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    VisionModel().unload()
    safe, note = memory.check("the game")
    print(f"  memory: {note}", flush=True)
    if not safe:
        return 2

    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    try:
        runner = RouteRunner(
            inp, Router(), walkspeed=28.0,
            confirm_menu=lambda: ss.reset_dialog_present(cap.capture()))

        print("\n  BEFORE any reset:", flush=True)
        for key in "wasd":
            print(f"    {key}: {flow_for(inp, cap, key):6.2f} px/frame",
                  flush=True)
        cv2.imwrite(str(OUT / "before_reset.png"), cap.capture()[:, :, :3])

        print("\n  resetting…", flush=True)
        result = RouteResult("reset")
        runner._run_step({"op": "reset"}, result, 0)
        print(f"    {result.reason or 'respawned'}", flush=True)

        print("\n  probing forward every few seconds after the reset:",
              flush=True)
        started = time.monotonic()
        for round_number in range(12):
            elapsed = time.monotonic() - started
            w = flow_for(inp, cap, "w", seconds=1.2)
            d = flow_for(inp, cap, "d", seconds=1.2)
            print(f"    +{elapsed:5.1f}s   w {w:6.2f}   d {d:6.2f}"
                  f"   {'MOVING' if max(w, d) > 2.5 else 'still stuck'}",
                  flush=True)
            cv2.imwrite(str(OUT / f"after_{round_number:02d}.png"),
                        cap.capture()[:, :, :3])
            if max(w, d) > 2.5:
                print(f"\n  => movement resumed {elapsed:.1f}s after the reset",
                      flush=True)
                break
            time.sleep(2.0)
        else:
            print("\n  => never moved within the window", flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

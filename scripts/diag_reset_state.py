#!/usr/bin/env python3
"""Does a respawn restore the camera, or does the old rotation survive it?

This is the crux of whether the recorded routes can EVER be replayed. They are
camera-relative timed holds, so they only work from the orientation they were
recorded at. `from_hive_to_pine_tree_with_red_cannon` fired the cannon
perfectly on one run and walked into the sand on every run after, and the only
thing that differed was how much the camera had been turned beforehand.

If a respawn restores the camera, the routes are deterministic and something
else broke them -- the prime suspect then being `shift_lock_toggle`, which is a
TOGGLE: left on by one run, the next run's toggle turns it OFF and inverts the
movement semantics for the whole route.

So: photograph the view after a reset, disturb it, reset again, and compare.
Same view means the camera is restored. Different means it is not, and no
amount of care with the replay will make those routes reproducible.
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

OUT = pathlib.Path("/tmp/hivemind-diag/resetstate")
BAND = (200, 260, 1520, 560)          # world only, skipping the HUD strips


def world(frame):
    x, y, w, h = BAND
    return cv2.cvtColor(frame[y:y + h, x:x + w, :3], cv2.COLOR_BGR2GRAY)


def similarity(a, b) -> float:
    fa, fb = np.float32(world(a)).ravel(), np.float32(world(b)).ravel()
    fa, fb = fa - fa.mean(), fb - fb.mean()
    denom = float(np.linalg.norm(fa) * np.linalg.norm(fb))
    return float(fa @ fb / denom) if denom else 0.0


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

        def reset(tag):
            runner._run_step({"op": "reset"}, RouteResult("reset"), 0)
            time.sleep(1.5)
            frame = cap.capture()
            cv2.imwrite(str(OUT / f"{tag}.png"), frame[:, :, :3])
            return frame

        first = reset("1_first_reset")
        print("\n  turning the camera 3 taps and walking a little…", flush=True)
        inp.camera_right(3)
        time.sleep(0.6)
        with inp.held("d"):
            time.sleep(1.5)
        time.sleep(0.6)
        disturbed = cap.capture()
        cv2.imwrite(str(OUT / "2_disturbed.png"), disturbed[:, :, :3])
        print(f"    view now differs from the first reset by "
              f"{1 - similarity(first, disturbed):.2f}", flush=True)

        second = reset("3_second_reset")
        same = similarity(first, second)
        print(f"\n  similarity between the two post-reset views: {same:.3f}",
              flush=True)
        if same > 0.85:
            print("  => THE RESPAWN RESTORES THE CAMERA. Routes can be "
                  "deterministic; suspect the shift-lock toggle instead.",
                  flush=True)
        else:
            print("  => THE CAMERA SURVIVES THE RESPAWN. Recorded routes "
                  "cannot be replayed reliably from a reset alone.",
                  flush=True)

        # and a third, to see whether it is at least repeatable
        third = reset("4_third_reset")
        print(f"  second vs third reset: {similarity(second, third):.3f}",
              flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

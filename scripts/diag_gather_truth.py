#!/usr/bin/env python3
"""Does gathering work at all, and where?

Four foraging runs found no field, but a frame from the cannon clearly shows
flower fields a short walk to the right. Either the probes never reach the
flowers, or gathering needs something the loop is not doing.

One suspect worth naming: a reset KILLS the character ("You died! Your bees
must recover at the hive"). If the bees take time to come back, then a loop
that resets before every search is destroying the very thing that collects the
pollen, and probing for twenty seconds immediately afterwards would measure
nothing whatever the bot was standing on.

So this tests the two things separately, with no loop in the way:

    A  reset, go to the cannon, walk RIGHT toward the visible flowers, and
       gather for two minutes without resetting again
    B  the same gather, but starting immediately after a reset

If A pays and B does not, the reset is the problem. If neither pays, gathering
needs something else entirely and the loop was never the issue.
"""
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                          # noqa: E402
from hivemind.act.routes import RouteResult, RouteRunner    # noqa: E402
from hivemind.brain.farm import HudReader                   # noqa: E402
from hivemind.brain.vlm import VisionModel                  # noqa: E402
from hivemind.nav.router import Router                      # noqa: E402
from hivemind.platform.current import memory                        # noqa: E402
from hivemind.vision import screenstate as ss               # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path("/tmp/hivemind-diag/gathertruth")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    VisionModel().unload()
    safe, note = memory.check("the game")
    print(f"  memory: {note}", flush=True)
    if not safe:
        return 2

    templates = ss.load_templates(ROOT / "data/templates/digits")
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
        hud = HudReader(cap.capture, templates)

        def shot(tag):
            cv2.imwrite(str(OUT / f"{tag}.png"), cap.capture()[:, :, :3])

        def gather(label, seconds):
            before = hud.pollen()
            print(f"    {label}: pollen before {before.describe()}", flush=True)
            end = time.monotonic() + seconds
            passes = 0
            while time.monotonic() < end:
                runner.run("farm_better_snake")
                passes += 1
            time.sleep(1.0)
            after = hud.pollen()
            gained = (after.value - before.value
                      if before.ok and after.ok else None)
            print(f"    {label}: pollen after  {after.describe()}"
                  f"   ({passes} passes)", flush=True)
            print(f"    {label}: GAINED {gained if gained is not None else '?'}"
                  f" in {seconds:.0f}s", flush=True)
            return gained

        print("\n  === A: go to the cannon, walk toward the flowers, gather ===",
              flush=True)
        runner._run_step({"op": "reset"}, RouteResult("reset"), 0)
        runner.run("from_hive_to_red_cannon")
        time.sleep(1.0)
        shot("A0_at_cannon")
        # the frame from the cannon shows fields to the RIGHT
        for seconds in (4.0, 4.0):
            with inp.held("d"):
                time.sleep(seconds)
            inp.tap("space")
            time.sleep(0.4)
        time.sleep(1.0)
        shot("A1_after_walking_right")
        a_gained = gather("A", 120.0)
        shot("A2_after_gathering")

        print("\n  === B: straight after a reset, same gather ===", flush=True)
        runner._run_step({"op": "reset"}, RouteResult("reset"), 0)
        shot("B0_after_reset")
        b_gained = gather("B", 120.0)
        shot("B1_after_gathering")

        print("\n  === verdict ===", flush=True)
        print(f"    at the fields after travelling : {a_gained}", flush=True)
        print(f"    at the hive straight off a reset: {b_gained}", flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Do the bees still collect, and did the resets kill them?

MEASURED: gathering paid 0 pollen in 120 s both at the fields and at the hive,
and the frame shows NO BEES around the character. In Bee Swarm the bees do the
collecting, so no bees means no pollen wherever you stand.

A reset kills the character -- the game says so: "You died! Your bees must
recover at the hive." Tonight's runs reset about twenty times. The suspicion is
that the loop was destroying the very thing that gathers, then measuring the
absence and concluding there were no fields.

This makes NO reset at all. It joins, waits at the hive for the bees to come
back, and watches whether the pollen counter moves while standing still.
"""
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                  # noqa: E402
from hivemind.brain.farm import HudReader           # noqa: E402
from hivemind.brain.vlm import VisionModel          # noqa: E402
from hivemind.platform.current import memory                # noqa: E402
from hivemind.vision import screenstate as ss       # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path("/tmp/hivemind-diag/bees")
ASK = ("This is Bee Swarm Simulator. How many BEES can you see flying around "
       "the player character? Answer with just a number, or 0 if none.")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    model = VisionModel()
    templates = ss.load_templates(ROOT / "data/templates/digits")
    safe, note = memory.check("the game")
    print(f"  memory: {note}", flush=True)

    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    cap = ready.capture
    try:
        hud = HudReader(cap.capture, templates)
        print("\n  NO RESET. Standing still at the spawn point.\n", flush=True)
        for minute in range(5):
            frame = cap.capture()
            cv2.imwrite(str(OUT / f"t{minute}.png"), frame[:, :, :3])
            pollen = hud.pollen()
            ok, buf = cv2.imencode(".png", frame[:, :, :3])
            answer = model.ask(buf.tobytes(), ASK)
            bees = answer.text.strip()[:20] if answer else "(no model)"
            print(f"    +{minute}min   pollen {pollen.describe():<26} "
                  f"bees visible: {bees}", flush=True)
            if minute < 4:
                time.sleep(60)
        print("\n  If pollen never moved and no bees are visible, the account's "
              "bees are down and need time at the hive to recover.", flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

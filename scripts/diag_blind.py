#!/usr/bin/env python3
"""The view goes black after the cannon. Can it be recovered?

`scripts/test_navigate.py` ran hive -> Pine Tree successfully: 21 steps, 346
studs, the cannon fired, and the HUD showed pollen climbing at +4/sec, so the
character landed in a field and started gathering. But the world went dark:

    step 18 (after the 8s flight)   luma 135   fine
    step 19 camera left             luma   8.8
    step 20 shift_lock              luma  83.4
    step 21 walk a                  luma  27.0
    final                           luma   0.0   fully black

Oscillating, then black. That is the signature of the camera clipping inside
geometry rather than a renderer failure -- and it matters because a blind bot
cannot read a single thing on screen.

This reproduces the end state and then tries each recovery in turn, reporting
the luminance after each, so the recovery ladder is built on what actually
works rather than on what sounds plausible.
"""
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                          # noqa: E402
from hivemind.act.routes import RouteResult, RouteRunner    # noqa: E402
from hivemind.nav.router import Router                      # noqa: E402
from hivemind.vision import screenstate as ss               # noqa: E402

OUT = pathlib.Path("/tmp/hivemind-diag/blind")
ROUTE = "from_hive_to_pine_tree_with_red_cannon"


def luma(frame) -> float:
    """Mean brightness of the WORLD area, excluding the HUD strips."""
    return float(cv2.cvtColor(frame[200:900, :, :3], cv2.COLOR_BGR2GRAY).mean())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    try:
        router = Router()
        runner = RouteRunner(
            inp, router, walkspeed=28.0,
            confirm_menu=lambda: ss.reset_dialog_present(cap.capture()))

        print("\n  getting to the end state (reset, then the route)...", flush=True)
        runner._run_step({"op": "reset"}, RouteResult("reset"), 0)
        result = runner.run(ROUTE)
        print(f"  {result.describe()}", flush=True)

        frame = cap.capture()
        start = luma(frame)
        cv2.imwrite(str(OUT / "00_landed.png"), frame[:, :, :3])
        print(f"\n  world luma after the route: {start:.1f}"
              f"  {'(BLIND)' if start < 15 else '(visible)'}\n", flush=True)
        print("  recovery attempt        luma   recovered?", flush=True)
        print("  " + "-" * 48, flush=True)

        attempts = [
            ("zoom out (o x3)", lambda: [inp.tap("o") or time.sleep(0.15)
                                         for _ in range(3)]),
            ("camera up x2", lambda: inp.camera_up(2)),
            ("camera right x2", lambda: inp.camera_right(2)),
            ("camera right x2 more", lambda: inp.camera_right(2)),
            ("jump", lambda: inp.tap("space")),
            ("walk back 1s", lambda: (inp.press("s"), time.sleep(1.0),
                                      inp.release("s"))),
            ("camera down x2", lambda: inp.camera_down(2)),
        ]
        for index, (label, action) in enumerate(attempts, 1):
            action()
            time.sleep(0.7)
            frame = cap.capture()
            level = luma(frame)
            cv2.imwrite(str(OUT / f"{index:02d}_{label.replace(' ', '_')}.png"),
                        frame[:, :, :3])
            print(f"  {label:<22} {level:6.1f}   "
                  f"{'YES' if level > 40 else 'still dark'}", flush=True)
            if level > 40:
                print(f"\n  => recovered by: {label}", flush=True)
                break

        # is the HUD still readable while blind? that decides how much the bot
        # can still do in this state
        frame = cap.capture()
        print(f"\n  HUD still present while the world is dark: "
              f"{ss.hud_present(frame)}", flush=True)
        x, y, w, h = ss.POLLEN_REGION
        from hivemind.vision import digits
        templates = ss.load_templates(
            pathlib.Path(__file__).resolve().parents[1] / "data/templates/digits")
        text, score = digits.read(frame[y:y + h, x:x + w], templates)
        print(f"  pollen still readable: {text!r} at {score:.3f}", flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

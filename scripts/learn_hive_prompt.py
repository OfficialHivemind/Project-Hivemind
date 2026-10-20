#!/usr/bin/env python3
"""Find the hive prompt on a real screen, and cut a template from it.

`act/hive.py` refuses to claim anything until it can SEE whether a slot is
empty, and that detector needs templates for Roblox's proximity prompts:

    "Claim Hive [C]"    an empty slot
    "Make Honey [H]"    the slot we already own

An earlier attempt to find them by counting bright pixels in a guessed rectangle
found the LEADERBOARD instead. So this does not guess a rectangle. It walks the
slots, and at each one ASKS THE LOCAL VISION MODEL what the prompt says and
roughly where it is -- which is exactly the kind of rare, open-ended question
the model exists for, and the answer is checked against the picture rather than
trusted.

Nothing here claims anything. It presses no C, no Enter. It walks and looks.
"""
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                          # noqa: E402
from hivemind.act.routes import RouteResult, RouteRunner    # noqa: E402
from hivemind.brain.vlm import VisionModel                  # noqa: E402
from hivemind.nav.router import Router                      # noqa: E402
from hivemind.vision import screenstate as ss               # noqa: E402

OUT = pathlib.Path("/tmp/hivemind-diag/hiveprompt")
QUESTION = (
    "This is a screenshot of the game Bee Swarm Simulator. Roblox shows a "
    "proximity prompt as a small rounded box with a key letter in it, near the "
    "middle or lower middle of the screen, over the world. Is such a prompt "
    "visible? If yes, reply exactly: YES | <the text of the prompt> | <one of "
    "top/middle/bottom> | <one of left/centre/right>. If no prompt is visible, "
    "reply exactly: NO")


def encode(frame):
    ok, buf = cv2.imencode(".png", frame[:, :, :3])
    return buf.tobytes()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    model = VisionModel()
    if not model.available():
        print(f"  vision model unavailable: {model.reason}")
        return 1
    print(f"  vision model ready: {model.model}", flush=True)

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

        print("\n  resetting for a known start...", flush=True)
        runner._run_step({"op": "reset"}, RouteResult("reset"), 0)

        print("  walking to the corner...", flush=True)
        for step in ({"op": "walk", "keys": "a", "studs": 16.1},
                     {"op": "camera", "direction": "left"},
                     {"op": "camera", "direction": "left"},
                     {"op": "shift_lock"},
                     {"op": "shift_lock"}):
            runner._run_step(step, RouteResult("corner"), 0)
        time.sleep(0.8)

        print("\n  asking the model at each slot:\n", flush=True)
        for hops in range(6):
            frame = cap.capture()
            path = OUT / f"hop{hops}.png"
            cv2.imwrite(str(path), frame[:, :, :3])
            answer = model.ask(encode(frame), QUESTION)
            said = answer.text.replace("\n", " ")[:150] if answer else \
                f"(no answer: {model.reason})"
            print(f"    hop {hops}: {said}", flush=True)
            if hops < 5:
                inp.tap("space")
                time.sleep(0.56)
                inp.tap("space")
                time.sleep(1.0)

        print(f"\n  frames saved in {OUT}", flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

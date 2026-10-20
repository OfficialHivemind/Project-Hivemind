#!/usr/bin/env python3
"""Which camera heading do the recorded routes assume?

THE PROBLEM, measured. Every movement key in Roblox is relative to the camera,
so a recorded route only replays correctly from the heading it was recorded at.
A reset fixes the character's POSITION but not the camera's rotation, and the
rotation persists across resets -- so `from_hive_to_pine_tree_with_red_cannon`
fired the cannon perfectly on one run and, after an unrelated diagnostic left
the camera 12 taps around, walked into the sand beside hive slot 5 instead.
Same code, same route, same reset. Only the heading differed.

THE FIX has to start from a heading the bot can FIND, not one it remembers. At
the hive the honeycomb wall is a hard boundary: walking into it gives ~1 px of
flow per frame against ~11 px in the open (measured three times). So "the
heading where forward is blocked" is a landmark the bot can locate from
anywhere, and every route can be expressed as an offset from it.

This finds that offset, by experiment rather than by reasoning: park on the
blocked heading, then for each of the eight headings run the first leg of the
route and ask the vision model whether the character reached the cannon.
"""
import pathlib
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                          # noqa: E402
from hivemind.act.orient import TAPS_PER_FULL_TURN         # noqa: E402
from hivemind.act.routes import RouteResult, RouteRunner    # noqa: E402
from hivemind.brain.vlm import VisionModel                  # noqa: E402
from hivemind.nav.router import Router                      # noqa: E402
from hivemind.platform.current import memory                        # noqa: E402
from hivemind.vision import screenstate as ss               # noqa: E402
from hivemind.vision.flow import FlowTracker                # noqa: E402

OUT = pathlib.Path("/tmp/hivemind-diag/heading")
LEG = "from_hive_to_red_cannon"
ASK = ("This is Bee Swarm Simulator. Is the player standing on or right next "
       "to a large CANNON (a big tube pointing up into the sky)? Answer with "
       "one word: yes or no.")


def encode(frame):
    ok, buf = cv2.imencode(".png", frame[:, :, :3])
    return buf.tobytes()


def forward_flow(inp, cap, seconds=0.7):
    tracker = FlowTracker()
    tracker.update(cap.capture())
    seen = []
    try:
        inp.press("w")
        deadline = time.monotonic() + seconds
        while True:
            sample = tracker.update(cap.capture())
            if sample is not None and sample.pairs is not None:
                d = sample.pairs[:, 1, :] - sample.pairs[:, 0, :]
                seen.append(float(np.median(np.linalg.norm(d, axis=1))))
            if time.monotonic() >= deadline:
                break
            time.sleep(0.03)
    finally:
        inp.release("w")
    with inp.held("s"):
        time.sleep(seconds)
    time.sleep(0.4)
    return float(np.median(seen)) if seen else 0.0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    model = VisionModel()
    model.unload()
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
        router = Router()
        runner = RouteRunner(
            inp, router, walkspeed=28.0,
            confirm_menu=lambda: ss.reset_dialog_present(cap.capture()))

        def reset():
            runner._run_step({"op": "reset"}, RouteResult("reset"), 0)

        print("\n  === finding the blocked heading (facing the hive wall) ===",
              flush=True)
        reset()
        flows = []
        for tap in range(TAPS_PER_FULL_TURN):
            flow = forward_flow(inp, cap)
            flows.append(flow)
            print(f"    heading {tap}: forward flow {flow:5.2f} px/frame",
                  flush=True)
            inp.camera_right(1)
            time.sleep(0.4)
        blocked = int(np.argmin(flows))
        print(f"\n    most blocked heading is {blocked} "
              f"({flows[blocked]:.2f} px) — the hive wall", flush=True)

        print(f"\n  === running {LEG} from each offset ===", flush=True)
        results = {}
        for offset in range(TAPS_PER_FULL_TURN):
            reset()
            # park on the blocked heading, then step round by `offset`
            for tap in range(TAPS_PER_FULL_TURN):
                if forward_flow(inp, cap, seconds=0.4) < 2.0:
                    break
                inp.camera_right(1)
                time.sleep(0.3)
            inp.camera_right(offset)
            time.sleep(0.5)

            runner.run(LEG)
            time.sleep(1.0)
            frame = cap.capture()
            cv2.imwrite(str(OUT / f"offset{offset}.png"), frame[:, :, :3])
            answer = model.ask(encode(frame), ASK)
            said = (answer.text.strip().lower()[:12] if answer
                    else f"(no model: {model.reason[:40]})")
            results[offset] = said
            print(f"    offset {offset}: at a cannon? {said}", flush=True)

        winners = [o for o, s in results.items() if s.startswith("yes")]
        print(f"\n  OFFSETS THAT REACH THE CANNON: {winners or 'none'}",
              flush=True)
        print(f"  frames in {OUT}", flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Which of the six hive slots is the owner's?

EVERY recorded route out of the hive assumes the character starts at its own
slot. BeeTuxMacro reaches it by walking to a corner and then hopping
`5 - slot` times, and it verifies arrival by checking a single pixel where the
"Claim Hive [C]" / "Make Honey [H]" prompt appears.

The slot number cannot be derived from anything in the repo -- it is a fact
about the account -- so rather than guess it, this walks the hop sequence and
photographs each position. Whichever one shows the hive prompt is the slot.

Nothing here is irreversible: it walks, it hops, it takes pictures.
"""
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                          # noqa: E402
from hivemind.act.routes import RouteResult, RouteRunner    # noqa: E402
from hivemind.nav.router import Router                      # noqa: E402
from hivemind.act.hive import banner_reader                  # noqa: E402
from hivemind.brain.vlm import VisionModel                   # noqa: E402
from hivemind.vision import screenstate as ss               # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "var" / "hiveslot"
# The prompt sits low-centre, above the hotbar. Generous: we are looking, not
# yet deciding.
PROMPT_REGION = (560, 700, 800, 220)


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

        print("\n  resetting to a known start...", flush=True)
        reset = RouteResult("reset")
        runner._run_step({"op": "reset"}, reset, 0)
        print(f"  reset: {reset.reason or 'respawned'}", flush=True)
        cv2.imwrite(str(OUT / "00_after_reset.png"), cap.capture()[:, :, :3])

        # the opening of from_corner_to_hive, up to but not including the hop
        print("\n  walking to the corner...", flush=True)
        for step in ({"op": "walk", "keys": "a", "studs": 16.1},
                     {"op": "camera", "direction": "left"},
                     {"op": "camera", "direction": "left"},
                     {"op": "shift_lock"},
                     {"op": "shift_lock"}):
            runner._run_step(step, RouteResult("corner"), 0)
        time.sleep(0.6)
        cv2.imwrite(str(OUT / "01_at_corner.png"), cap.capture()[:, :, :3])

        print("\n  hopping along the slots, READING each panel...", flush=True)
        # READ THE PANEL, DO NOT COUNT BRIGHT PIXELS. The first version of
        # this script reported "bright pixels in the prompt area 3.21%" for
        # each of the six positions, which needed a human to open six images
        # and decide. The farm already reads this panel with the vision model
        # and the answer it gives -- "Make Honey" on the owner's own pad,
        # "Claim Hive" on a free one, nothing at all off a pad -- is the exact
        # fact this script exists to establish. MEASURED 2026-09-20: six reads
        # over fifteen seconds on an owned hive, all "Make Honey".
        model = VisionModel()
        read = banner_reader(model) if model.available() else None
        if read is None:
            print("  the vision model is not available, so the panel cannot "
                  "be read — falling back to photographs only", flush=True)
        found = []
        x, y, w, h = PROMPT_REGION
        for hops in range(0, 6):
            frame = cap.capture()
            slot = 5 - hops
            cv2.imwrite(str(OUT / f"slot_{slot}_after_{hops}_hops.png"),
                        frame[:, :, :3])
            said = None
            if read is not None:
                try:
                    said = read(frame)
                except Exception as exc:
                    said = f"<read failed: {exc}>"
            prompt = frame[y:y + h, x:x + w, :3]
            bright = float((cv2.cvtColor(prompt, cv2.COLOR_BGR2GRAY) > 200).mean())
            mine = bool(said) and "make honey" in str(said).lower()
            if mine:
                found.append((slot, hops))
            print(f"    slot {slot} (after {hops} hops): panel {said!r}"
                  f"{'   <-- THIS IS THE OWNER''S HIVE' if mine else ''}"
                  f"   [bright {bright:.2%}]", flush=True)
            if hops < 5:
                inp.tap("space")
                time.sleep(0.56)
                inp.tap("space")
                time.sleep(1.0)

        print("", flush=True)
        if len(found) == 1:
            slot, hops = found[0]
            print(f"  ANSWER: the owner's hive is slot {slot}, {hops} hops "
                  f"from the corner.", flush=True)
            print(f"  Put it in the Movement panel as move.hive_slot = {slot}",
                  flush=True)
        elif not found:
            print("  NO position read 'Make Honey'. Either the walk to the "
                  "corner did not land, or the panel could not be read. The "
                  "photographs are the record; do not guess from them.",
                  flush=True)
        else:
            print(f"  {len(found)} positions read 'Make Honey', which cannot "
                  f"all be true: {found}. Something moved between reads.",
                  flush=True)
        print(f"  frames in {OUT}", flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Does the bot actually EARN? Claim a hive, walk to a field, watch the number.

This is the end-to-end proof the project has never had. Every previous run
either collected nothing (no hive, so no bees) or could not say whether what it
collected came from walking somewhere sensible.

The test is deliberately blunt: after claiming, go out to a field and sample
the pollen counter. Pollen RISING is the only evidence that accepts no
substitute -- not arriving somewhere, not a route completing, not a timer
elapsing. If the number goes up, bees exist, they are following, and the
character is standing somewhere worth standing.

NO RESETS. A reset is a death, death sends every bee home to rest for ~30 s,
and doing that repeatedly is what kept the swarm down all night.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                              # noqa: E402
from hivemind.act.clicker import Clicker                        # noqa: E402
from hivemind.act.hive import TRANSCRIBE, sweep_and_claim       # noqa: E402
from hivemind.act.routes import RouteRunner                     # noqa: E402
from hivemind.brain.bees import Swarm                           # noqa: E402
from hivemind.brain.vlm import VisionModel                      # noqa: E402
from hivemind.nav.router import Router                          # noqa: E402
from hivemind.platform.current import memory                            # noqa: E402
from hivemind.vision import banner                              # noqa: E402
from hivemind.brain.farm import HudReader                       # noqa: E402
from hivemind.vision import screenstate as ss                   # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "var" / "prove"
OUTBOUND = "from_hive_to_pine_tree_with_red_cannon"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gather-seconds", type=float, default=120.0)
    ap.add_argument("--no-click", action="store_true",
                    help="gather without swinging the tool, for comparison")
    ap.add_argument("--walkspeed", type=float, default=28.0)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    safe, why = memory.check("a live farming proof")
    print(f"\n  memory: {why}", flush=True)
    if not safe:
        return 2

    model = VisionModel()
    if model.available():
        model.unload()

    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}", flush=True)
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    swarm = Swarm()

    def read_text(frame):
        panel = banner.find(frame)
        if panel is None:
            return None
        ok, buf = cv2.imencode(".png", panel.crop(frame)[:, :, :3])
        if not ok or not model.available():
            return None
        answer = model.ask(buf.tobytes(), TRANSCRIBE)
        text = getattr(answer, "text", answer)
        return text if isinstance(text, str) else None

    def red(frame):
        from claim_hive import red_bearing            # same measurement
        return red_bearing(frame)

    try:
        print("\n  1. claiming a hive (bees only exist once one is claimed)",
              flush=True)
        claimed = sweep_and_claim(inp, cap.capture, read_text,
                                  bearing_hint=red,
                                  on_note=lambda t: print(f"     {t}", flush=True))
        print(f"     -> {claimed.describe()}", flush=True)
        if not claimed.ok:
            return 3
        swarm.claimed()
        model.unload()                # free 6 GB before the long part

        print(f"\n  2. walking out: {OUTBOUND}", flush=True)
        runner = RouteRunner(inp, Router(), walkspeed=args.walkspeed)
        out = runner.run(OUTBOUND)
        print(f"     -> {out.describe()}", flush=True)

        print(f"\n  3. gathering for {args.gather_seconds:.0f}s, "
              f"sampling the pollen counter", flush=True)
        templates = ss.load_templates(
            pathlib.Path(__file__).resolve().parents[1] / "data/templates/digits")
        hud = HudReader(cap.capture, templates)
        started = time.monotonic()
        first = None
        best = 0
        samples = 0

        # Swing the collecting tool while the bees work. The gate is asked
        # before every click: a click lands wherever the pointer is, and on a
        # menu that is the Leave button.
        def world_on_screen() -> bool:
            frame = cap.capture()
            return frame is not None and ss.hud_present(frame)

        clicker = Clicker(inp, can_click=world_on_screen)
        if not args.no_click:
            clicker.start()
            print("     swinging the tool (jittered, gated on the HUD)",
                  flush=True)
        while time.monotonic() - started < args.gather_seconds:
            # walk a small figure so the bees pass over flowers
            for key in ("w", "a", "s", "d"):
                with inp.held(key):
                    time.sleep(1.2)
            reading = hud.pollen()
            samples += 1
            if getattr(reading, "ok", False) and reading.value is not None:
                if first is None:
                    first = reading.value
                best = max(best, int(reading.value))
                print(f"     {time.monotonic() - started:5.0f}s  "
                      f"pollen {reading.describe()}", flush=True)
                if first is not None and reading.value > first:
                    swarm.saw_pollen_rise()
        clicker.stop()
        cv2.imwrite(str(OUT / "end.png"), cap.capture()[:, :, :3])
        print(f"     clicker: {clicker.describe()}", flush=True)

        print("\n  ================ RESULT ================", flush=True)
        if first is None:
            print("  the pollen counter was never readable — inconclusive",
                  flush=True)
            return 4
        gained = best - first
        print(f"  pollen {first:,} -> {best:,}   ({gained:+,} over "
              f"{args.gather_seconds:.0f}s, {samples} samples)", flush=True)
        print(f"  swarm: {swarm.describe()}", flush=True)
        rate = gained / max(1.0, args.gather_seconds)
        print(f"  rate:  {rate:,.0f} pollen/sec"
              f"{' (tool NOT used)' if args.no_click else ' (with the tool)'}",
              flush=True)
        if gained > 0:
            print("  IT IS EARNING. Bees exist, they are following, and the "
                  "field is real.", flush=True)
            return 0
        print("  still zero — the hive was claimed, so this is NOT the "
              "no-bees cause any more. Next suspects: the bees are asleep "
              "(out of energy), or the route did not reach a field.",
              flush=True)
        return 5
    finally:
        held = getattr(inp, "held_keys", set())
        try:
            model.unload()
        except Exception:
            pass
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Where does the travel route actually put the character?

The farm loop ran two clean cycles and gathered 54 and 27 pollen against a
660,000 backpack -- so it travelled, gathered and returned without error, but
was not standing anywhere with flowers. An earlier navigate run ended on sand
beside a mushroom rather than in Pine Tree Forest.

So this stops guessing and asks. It runs the travel leg, photographs the
destination, and asks the local vision model which field it is looking at --
exactly the open-ended question the model exists for. It then gathers for a
while and reports the pollen delta, which is the only honest measure of whether
the spot is worth standing in.

Nothing irreversible: it walks, it gathers, it photographs.
"""
import argparse
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                          # noqa: E402
from hivemind.platform.current import memory                    # noqa: E402
from hivemind.act.routes import RouteResult, RouteRunner    # noqa: E402
from hivemind.brain.farm import HudReader                   # noqa: E402
from hivemind.brain.vlm import VisionModel                  # noqa: E402
from hivemind.nav.router import Router                      # noqa: E402
from hivemind.vision import screenstate as ss               # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path("/tmp/hivemind-diag/arrival")

WHERE = ("This is a screenshot of Bee Swarm Simulator. Describe in one short "
         "sentence what the player is standing on or next to, and say whether "
         "there are FLOWERS visible on the ground near the player. Start your "
         "answer with FLOWERS: yes or FLOWERS: no")


def encode(frame):
    ok, buf = cv2.imencode(".png", frame[:, :, :3])
    return buf.tobytes()


def main() -> int:
    parser = argparse.ArgumentParser(prog="diag_arrival")
    parser.add_argument("--route", default="from_hive_to_pine_tree_with_red_cannon")
    parser.add_argument("--gather", type=float, default=45.0,
                        help="seconds to gather at the destination")
    parser.add_argument("--pattern", default="farm_better_snake")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    model = VisionModel()
    templates = ss.load_templates(ROOT / "data/templates/digits")

    # Free the model's weights and check there is room BEFORE the game
    # launches. The OOM killer ended two runs that started without this.
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
        router = Router()
        runner = RouteRunner(
            inp, router, walkspeed=28.0,
            confirm_menu=lambda: ss.reset_dialog_present(cap.capture()))
        hud = HudReader(cap.capture, templates)

        def look(tag: str) -> None:
            frame = cap.capture()
            cv2.imwrite(str(OUT / f"{tag}.png"), frame[:, :, :3])
            answer = model.ask(encode(frame), WHERE)
            said = answer.text.replace("\n", " ")[:200] if answer else \
                f"(model unavailable: {model.reason})"
            print(f"    {tag}: {said}", flush=True)

        print("\n  reset to a known start…", flush=True)
        runner._run_step({"op": "reset"}, RouteResult("reset"), 0)
        print(f"    pollen {hud.pollen().describe()}", flush=True)
        look("0_at_hive")

        print(f"\n  travelling: {args.route}", flush=True)
        result = runner.run(args.route)
        print(f"    {result.describe()}", flush=True)
        time.sleep(1.0)
        look("1_arrived")

        before = hud.pollen()
        print(f"\n  gathering {args.gather:.0f}s with {args.pattern}…", flush=True)
        print(f"    pollen before: {before.describe()}", flush=True)
        deadline = time.monotonic() + args.gather
        passes = 0
        while time.monotonic() < deadline:
            runner.run(args.pattern)
            passes += 1
        time.sleep(1.0)
        after = hud.pollen()
        look("2_after_gathering")
        print(f"    pollen after:  {after.describe()}  ({passes} passes)",
              flush=True)

        if before.value and after.value:
            gained = after.value[0] - before.value[0]
            rate = gained / args.gather * 60.0
            print(f"\n  GAINED {gained:,} pollen in {args.gather:.0f}s "
                  f"= {rate:,.0f}/min", flush=True)
            print("  VERDICT:", "worth farming" if rate > 500 else
                  "NOT a flower field — the route lands somewhere barren",
                  flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

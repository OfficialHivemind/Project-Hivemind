#!/usr/bin/env python3
"""Walk a recorded route somewhere and LOOK, without touching anything.

WHY THIS EXISTS. The owner asked for upgraded gear. The next tool
worth buying is the Bubble Wand -- 3,500,000 honey, 240 pollen/sec on blue
flowers against the Golden Rake's ~167, and the colour-matched tool for the
blue hive they asked for. `data/knowledge/progression.yaml` says it is sold at
`blue_hq`, and the router has no node called that. It does have a recorded
route to `blue_field_booster`, and no route back.

So the question "where is the shop" is answerable by going and looking, and
that is all this does.

WHAT IT WILL NOT DO, and these are the point of the file:

  * It never presses the interact key. `E` opens shops, starts NPC
    conversations and has already opened a Polar Bear quest dialogue by
    accident. Finding a shop and entering one are different jobs, and this is
    only the first.
  * It never clicks. Nothing is bought, sold, accepted or confirmed.
  * It refuses to travel with a loaded backpack. There is no recorded route
    home from most of these places, so the way back is a rejoin -- which is
    safe for pollen (MEASURED) but the trip out is not: it crosses guarded
    ground. Scouting is done empty, when a death costs nothing.

It writes frames and every distinct line of text it saw to `var/scout/<name>/`
so the shop's actual interface can be read afterwards, by a human, before
anything is built against it.

    ./.venv/bin/python scripts/scout.py --to blue_field_booster
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                      # noqa: E402
from hivemind.act.hive import TRANSCRIBE                # noqa: E402
from hivemind.act.routes import RouteRunner             # noqa: E402
from hivemind.brain.farm import HudReader               # noqa: E402
from hivemind.brain.vlm import VisionModel              # noqa: E402
from hivemind.nav.router import Router                  # noqa: E402
from hivemind.platform.current import memory                    # noqa: E402
from hivemind.vision import banner                      # noqa: E402
from hivemind.vision import screenstate as ss           # noqa: E402
from hivemind.world.settings import Settings            # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "var" / "scout"

# Refuse to scout carrying more than this. A scouting trip crosses guarded
# ground with no recorded way home, so it is done with an empty backpack --
# then a death costs nothing at all and the rejoin home is free.
MAX_CARRY = 20_000


def main() -> int:
    ap = argparse.ArgumentParser(prog="scout")
    ap.add_argument("--to", required=True, help="a router node to walk to")
    ap.add_argument("--look-seconds", type=float, default=45.0)
    ap.add_argument("--every", type=float, default=3.0)
    ap.add_argument("--carry-anyway", action="store_true",
                    help="scout even with a loaded backpack (it can be lost)")
    args = ap.parse_args()

    router = Router()
    route = router.route("hive", args.to)
    if route is None:
        print(f"  no recorded route from the hive to {args.to}")
        print("  known nodes: "
              + ", ".join(sorted({e.end for e in router.edges})))
        return 1
    legs = [leg.name for leg in route.legs]
    print(f"\n  === scouting {args.to} ===")
    print(f"  route: {' -> '.join(legs)}")
    if router.route(args.to, "hive") is None:
        print("  NOTE: no recorded route back; the way home is a rejoin")

    safe, note = memory.check("the game")
    print(f"  memory: {note}", flush=True)
    if not safe:
        return 2

    VisionModel().unload()
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  FAILED: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    print(f"  in game in {ready.seconds:.0f}s", flush=True)

    where = OUT / args.to
    where.mkdir(parents=True, exist_ok=True)
    seen: list[str] = []
    model = VisionModel()

    def transcribe(frame, whole: bool) -> str | None:
        if frame is None or not model.available():
            return None
        if whole:
            crop = cv2.resize(frame[:, :, :3], (960, 540),
                              interpolation=cv2.INTER_AREA)
        else:
            panel = banner.find(frame)
            if panel is None:
                return None
            crop = panel.crop(frame)[:, :, :3]
        ok, buf = cv2.imencode(".png", crop)
        if not ok:
            return None
        answer = model.ask(buf.tobytes(), TRANSCRIBE)
        text = getattr(answer, "text", answer)
        return text if isinstance(text, str) else None

    try:
        templates = ss.load_templates(ROOT / "data/templates/digits")
        hud = HudReader(cap.capture, templates)
        pollen = hud.pollen()
        honey = hud.honey()
        print(f"  honey  {honey.describe()}")
        print(f"  pollen {pollen.describe()}")
        if (pollen.ok and pollen.value and pollen.value > MAX_CARRY
                and not args.carry_anyway):
            print(f"  REFUSING: carrying {pollen.value:,} pollen. Scouting "
                  f"crosses guarded ground with no route home, so it is done "
                  f"empty. Convert first, or pass --carry-anyway.")
            return 3

        walkspeed = Settings().float("move.walkspeed")
        runner = RouteRunner(inp, router, walkspeed=walkspeed)
        print(f"  walking {len(legs)} leg(s)…", flush=True)
        for name in legs:
            result = runner.run(name)
            print(f"    {name}: {'ok' if result.ok else 'FAILED'}", flush=True)

        print(f"  looking for {args.look_seconds:.0f}s…", flush=True)
        started = time.monotonic()
        index = 0
        while time.monotonic() - started < args.look_seconds:
            frame = cap.capture()
            if frame is not None:
                cv2.imwrite(str(where / f"{index:03d}.jpg"), frame)
                index += 1
                for whole in (False, True):
                    text = transcribe(frame, whole)
                    if text:
                        line = " ".join(text.split())
                        if line and line not in seen:
                            seen.append(line)
                            print(f"    saw: {line[:120]}", flush=True)
            time.sleep(args.every)

        (where / "seen.json").write_text(json.dumps({
            "node": args.to, "route": legs, "at": time.time(),
            "text": seen}, indent=1))
        print(f"\n  {index} frames and {len(seen)} distinct lines "
              f"written to {where}")
        if not seen:
            print("  nothing readable — the panel may need standing closer")
    finally:
        # NO KEY IS EVER LEFT DOWN, on any path, including a crash.
        try:
            inp.release_all()
        except Exception:
            pass
        ready.close()
        print("  torn down", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Walk to the errand places and write down what their panels actually say.

WHY A SEPARATE SCRIPT. `data/knowledge/errands.yaml` ships with every `expect`
list EMPTY, and `act/errands.Errand.matches` returns False on an empty list, so
none of those places can be used yet -- by design. Filling those lists in from
what a wiki says a prompt "should" read is exactly the guess this project does
not make. So the bot goes and looks.

It presses NOTHING. `run_errand` defaults to `press=False` and this script never
overrides it. The only keys used are movement.

ONE REJOIN PER PLACE, and that is not laziness. `data/world/paths.yaml` has
routes from the HIVE to each of these and no routes between them, so the only
way to start the next walk from the hive is to go back to the hive -- and a
rejoin does that reliably in about 40 s while a walk home has a measured 0%
success rate on this build. Pollen survives a rejoin (MEASURED), so nothing is
lost.

    ./.venv/bin/python scripts/learn_errands.py --places wealth_clock,blue_field_booster
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
from hivemind.act.errands import load, run_errand       # noqa: E402
from hivemind.act.hive import TRANSCRIBE                # noqa: E402
from hivemind.act.routes import RouteRunner, walkspeed_from   # noqa: E402
from hivemind.brain.vlm import VisionModel              # noqa: E402
from hivemind.nav.router import Router                  # noqa: E402
from hivemind.platform.current import memory                    # noqa: E402
from hivemind.vision import banner                      # noqa: E402
from hivemind.world.settings import Settings            # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "var" / "errand_panels.json"


def main() -> int:
    ap = argparse.ArgumentParser(prog="learn_errands")
    ap.add_argument("--places", required=True,
                    help="comma-separated router nodes to visit")
    ap.add_argument("--dwell", type=float, default=6.0,
                    help="seconds to keep reading the panel after arriving")
    args = ap.parse_args()

    wanted = [name.strip() for name in args.places.split(",") if name.strip()]
    errands = load(ROOT / "data/knowledge/errands.yaml")
    router = Router()
    learned = {}
    if OUT.exists():
        try:
            learned = json.loads(OUT.read_text())
        except ValueError:
            learned = {}

    for place in wanted:
        route = router.route("hive", place)
        if route is None:
            print(f"  {place}: no recorded route from the hive", flush=True)
            continue

        safe, note = memory.check("the game")
        if not safe:
            print(f"  {note}")
            return 2
        VisionModel().unload()
        ready = bootstrap.start(private=True)
        if not ready.ok:
            print(f"  {place}: could not start ({ready.reason})", flush=True)
            ready.close()
            continue
        inp, cap = ready.input, ready.capture
        model = VisionModel()

        def read_panel(frame):
            panel = banner.find(frame)
            if panel is None or not model.available():
                return None
            ok, buf = cv2.imencode(".png", panel.crop(frame)[:, :, :3])
            if not ok:
                return None
            answer = model.ask(buf.tobytes(), TRANSCRIBE)
            text = getattr(answer, "text", answer)
            return text if isinstance(text, str) else None

        try:
            runner = RouteRunner(inp, router, walkspeed=walkspeed_from(Settings()))

            def walk():
                ok = True
                for leg in route.legs:
                    ok = bool(runner.run(leg.name).ok) and ok
                return ok

            errand = errands.get(place)
            if errand is None:
                from hivemind.act.errands import Errand
                errand = Errand(name=place)
            out = run_errand(errand, walk=walk, frames=cap.capture,
                             read_text=read_panel,
                             on_note=lambda t: print(f"    {t}", flush=True))
            print(f"  {out.describe()}", flush=True)

            # SAVE WHAT IT IS LOOKING AT. The first run of this script
            # reported "arrived, no panel" at all three places, and that is
            # ambiguous in a way that matters: it could mean the route landed
            # short, landed somewhere else entirely, or landed correctly and
            # the prompt needs the character closer. A frame says which, and
            # without one the next person repeats the whole trip to find out.
            shots = ROOT / "var" / "errand_frames" / place
            shots.mkdir(parents=True, exist_ok=True)
            frame = cap.capture()
            if frame is not None:
                cv2.imwrite(str(shots / "arrived.jpg"), frame)

            # Keep looking for a few seconds: the prompt only appears when the
            # character is close enough, and a route lands where it lands.
            seen = [out.saw] if out.saw else []
            started = time.monotonic()
            while time.monotonic() - started < args.dwell:
                text = read_panel(cap.capture())
                line = " ".join((text or "").split())
                if line and line not in seen:
                    seen.append(line)
                    print(f"    also read: {line[:100]}", flush=True)
                shot = cap.capture()
                if shot is not None:
                    cv2.imwrite(str(shots / f"look{len(seen):02d}.jpg"), shot)
                time.sleep(1.5)
            learned[place] = seen
        finally:
            try:
                inp.release_all()
            except Exception:
                pass
            ready.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(learned, indent=1))
    print(f"\n  wrote {OUT}")
    for place, seen in learned.items():
        print(f"    {place}: {seen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

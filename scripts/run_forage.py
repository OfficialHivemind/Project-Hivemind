#!/usr/bin/env python3
"""Farm by consequence: reset, find pollen, gather, reset, convert.

    ./.venv/bin/python scripts/run_forage.py [--cycles N]

Needs no map, no heading and no calibration -- see hivemind.brain.forage for
why the route-driven version could not work. Every figure printed is a HUD
reading; a search that finds nothing says so rather than counting as a cycle.

Ctrl-C stops at the next safe boundary. F12 is the hardware panic key.
"""
from __future__ import annotations

import argparse
import pathlib
import signal
import sys
import threading
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                      # noqa: E402
from hivemind.act.clicker import Clicker                # noqa: E402
from hivemind.act.hive import TRANSCRIBE, sweep_and_claim  # noqa: E402
from hivemind.act.routes import RouteRunner             # noqa: E402
from hivemind.vision import banner                      # noqa: E402
from hivemind.brain.farm import HudReader               # noqa: E402
from hivemind.brain.forage import Forager               # noqa: E402
from hivemind.brain.vlm import VisionModel              # noqa: E402
from hivemind.ipc.bus import EventServer                 # noqa: E402
from hivemind.telemetry.events import Thought           # noqa: E402
from hivemind.telemetry.liveview import LiveView         # noqa: E402
from hivemind.vision.notice import notice                # noqa: E402
from hivemind.nav.router import Router                  # noqa: E402
from hivemind.platform.current import memory                    # noqa: E402
from hivemind.vision import screenstate as ss           # noqa: E402
from hivemind.vision.flow import FlowTracker            # noqa: E402
from hivemind.world.settings import Settings            # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(prog="run_forage")
    parser.add_argument("--cycles", type=int, default=None)
    parser.add_argument("--pattern", default="farm_better_snake")
    # NO CANNON BY DEFAULT, and this is the whole point of running this
    # instead of run_farm.
    #
    # Every failure measured today was the TRIP, not the farming. The cannon
    # route lands somewhere unpredictable, the glide home misses, and Pine
    # Tree is guarded by two mantises and a werewolf -- and a death empties
    # the entire backpack. The five starter fields sit beside the hive with
    # no gate between, and the wiki says outright that Sunflower and
    # Dandelion have no mobs at all.
    #
    # So: walk out from the hive and probe until the pollen counter actually
    # rises. No route to get wrong, no cannon, no glide, nothing that can
    # kill the character. Fewer flowers per pass than Pine Tree, and a cycle
    # that banks beats a richer one that dies holding everything.
    parser.add_argument("--outbound", default=None,
                        help="a route out of the hive; the default is to "
                             "walk and look instead")
    parser.add_argument("--gather-seconds", type=float, default=None)
    parser.add_argument("--probe-seconds", type=float, default=None)
    args = parser.parse_args()

    settings = Settings()
    templates = ss.load_templates(ROOT / "data/templates/digits")

    VisionModel().unload()
    safe, note = memory.check("the game")
    print(f"  memory: {note}", flush=True)
    if not safe:
        return 2

    print("\n  === bootstrap ===", flush=True)
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  FAILED: {ready.reason}")
        ready.close()
        return 1
    print(f"  in game in {ready.seconds:.0f}s", flush=True)
    inp, cap = ready.input, ready.capture

    stop = threading.Event()

    def ask_stop(*_):
        if stop.is_set():
            raise KeyboardInterrupt
        print("\n  stop requested — finishing this step…", flush=True)
        stop.set()

    signal.signal(signal.SIGINT, ask_stop)
    signal.signal(signal.SIGTERM, ask_stop)

    # Serve the GUI, same as run_farm does. Without this the app sits blank
    # while the bot works, which is exactly what the owner saw: an empty
    # window.
    server = EventServer().start()
    print(f"  GUI socket: {server.path}", flush=True)

    def narrate(event) -> None:
        # The forager emits a lightweight `_Note`, not a telemetry Event, so
        # it has no `to_json` and the bus cannot carry it. Wrap anything that
        # is not a real event rather than dropping it: the GUI's reasoning
        # pane is the whole reason this socket exists.
        if hasattr(event, "to_json"):
            server.send(event)
        else:
            text = getattr(event, "text", "") or str(event)
            if text:
                server.send(Thought(topic="forage", text=str(text)))
        text = (getattr(event, "text", "") or getattr(event, "note", "")
                or getattr(event, "message", ""))
        if text:
            print(f"    {time.strftime('%H:%M:%S')}  {text}", flush=True)

    model = VisionModel()

    try:
        router = Router()
        runner = RouteRunner(
            inp, router, walkspeed=settings.float("move.walkspeed"),
            confirm_menu=lambda: ss.reset_dialog_present(cap.capture()))
        hud = HudReader(cap.capture, templates)

        print(f"  starting pollen: {hud.pollen().describe()}", flush=True)
        print(f"  starting honey:  {hud.honey().describe()}", flush=True)

        extra = {}
        if args.gather_seconds is not None:
            extra["gather_seconds"] = args.gather_seconds
        if args.probe_seconds is not None:
            extra["probe_seconds"] = args.probe_seconds

        shots = pathlib.Path("/tmp/hivemind-diag/forage")
        shots.mkdir(parents=True, exist_ok=True)

        def debug_shot(tag: str) -> None:
            frame = cap.capture()
            if frame is not None:
                cv2.imwrite(str(shots / f"{tag}.png"), frame[:, :, :3])

        # CLAIM FIRST. Bees only exist once a hive is claimed, and it has to
        # be claimed again on every join. Without this the forager walks
        # perfectly good ground and collects nothing, which is exactly what a
        # whole night of runs measured.
        def read_panel(frame):
            found = banner.find(frame)
            if found is None or not model.available():
                return None
            ok, buf = cv2.imencode(".png", found.crop(frame)[:, :, :3])
            if not ok:
                return None
            answer = model.ask(buf.tobytes(), TRANSCRIBE)
            text = getattr(answer, "text", answer)
            return text if isinstance(text, str) else None

        print("\n  claiming a hive...", flush=True)
        claimed = sweep_and_claim(inp, cap.capture, read_panel,
                                  on_note=lambda t: print(f"    {t}",
                                                          flush=True))
        print(f"  -> {claimed.describe()}", flush=True)
        if not claimed.ok:
            return 3
        model.unload()

        # And swing the tool: MEASURED at roughly 2.8x the bees alone.
        clicker = Clicker(inp, can_click=lambda: ss.hud_present(cap.capture()))
        clicker.start()

        live = LiveView(cap.capture, narrate, detect=notice,
                        screen_of=lambda f: ss.classify(f).value).start()
        print(f"  live view: {live.path}", flush=True)

        def at_hive() -> bool:
            """Standing on our own hive right now? The panel is the proof."""
            try:
                text = read_panel(cap.capture())
            except Exception:
                return False
            return bool(text
                        and "make honey" in " ".join(text.lower().split()))

        forager = Forager(runner, hud, stop=stop, emit=narrate,
                          pattern=args.pattern, outbound_route=args.outbound,
                          at_home=at_hive,
                          frames=cap.capture, tracker_factory=FlowTracker,
                          debug_shot=debug_shot, **extra)
        print(f"\n  === foraging: {args.cycles or 'unlimited'} cycles ===",
              flush=True)
        session = forager.run(cycles=args.cycles)
        print(f"\n  === report ===\n  {session.describe()}", flush=True)
        for cycle in session.cycles:
            print(f"    {cycle.describe()}", flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        for stoppable, label in ((locals().get("clicker"), "clicker"),
                                 (locals().get("live"), "live view")):
            try:
                if stoppable is not None:
                    stoppable.stop()
                    print(f"  {label}: {stoppable.describe()}", flush=True)
            except Exception:
                pass
        server.stop()
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

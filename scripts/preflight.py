#!/usr/bin/env python3
"""Is the farm ready to be restarted? Says what is wrong, presses nothing.

Written for the restarts after an evening of building with the farm stopped
(the owner was playing): every subsystem touched has a file, a template or a
setting it depends on, and a restart that finds one missing costs a join
(~45 s) and a trip before the log says why. This checks them in a second:

    ./scripts/preflight.py

Exit 0 when everything is in place; the restart line is printed last.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    problems: list[str] = []
    notes: list[str] = []

    def check(ok: bool, good: str, bad: str) -> None:
        (notes if ok else problems).append(good if ok else bad)

    # processes and the stop flag
    # anchored to the start of the command line, so a shell whose text merely
    # mentions run_farm (this script's own heredoc, a grep) does not count
    running = subprocess.run(["pgrep", "-f", r"^[^ ]*python[^ ]* scripts/run_farm\.py"],
                             capture_output=True, text=True).stdout.split()
    check(not running, "no run_farm running", f"run_farm is already running (pid {running})")
    # A WATCHDOG BETWEEN ATTEMPTS HAS NO run_farm (DESIGN 8du): it sleeps in
    # its gap, its long gap or the memory gate, so the pgrep above found
    # nothing and this said "ready" -- and the restart line printed below
    # deletes STOP, which silently cancelled a `touch var/night/STOP` the
    # watchdog had not yet read. Same pidfile test as the GUI's.
    try:
        from hivemind.files import pid_running
        watchdog = pid_running(ROOT / "var/night/watchdog.pid", "overnight.sh",
                               start_path=ROOT / "var/night/watchdog.start")
    except Exception:
        watchdog = None
    check(watchdog is None, "no watchdog running",
          f"a watchdog is alive (pid {watchdog}); stop it with kill -TERM "
          f"{watchdog} and wait for it to exit")
    stop = ROOT / "var/night/STOP"
    notes.append("STOP flag present — the restart line below removes it" if stop.exists()
                 else "no STOP flag")

    # the private-server link and the settings the runs read
    from hivemind.datapaths import config_dir
    link = config_dir() / "server.yaml"
    check(link.exists(), "private-server link file present",
          f"{link} is missing — the join has nowhere to go")
    try:
        from hivemind.world.settings import Settings
        settings = Settings.load() if hasattr(Settings, "load") else Settings()
        name = str(settings.get("account.username") if hasattr(settings, "get") else "") or ""
        check(bool(name), f"account.username set ({name})",
              "account.username is empty — homing cannot pick the pad by name")
        tilt = int(settings.int("gather.camera_tilt")) if hasattr(settings, "int") else 0
        notes.append(f"gather.camera_tilt = {tilt}" + (" (the common blue-hive view)" if tilt else " (camera left alone)"))
    except Exception as exc:
        problems.append(f"settings could not be read: {exc}")

    # templates the new code depends on
    for rel, why in (("data/templates/ui/bss_tile.png", "the join finds Bee Swarm's tile by it"),
                     ("data/templates/ui/servers_label.png", "the join finds the Servers row by it"),
                     ("data/templates/buffs/haste.png", "the buff reader finds Haste by it"),
                     ("data/templates/buffs/digits/2.png", "stack counts are read by these")):
        check((ROOT / rel).exists(), f"{rel} present", f"{rel} is missing — {why}")

    # the route graph: the cannon flights must load
    try:
        from hivemind.nav.router import Router
        router = Router()
        flights = [e.name for e in router.edges if e.name.endswith("_via_red_cannon")]
        check(len(flights) >= 12, f"{len(flights)} cannon flights in the graph",
              f"only {len(flights)} cannon flights loaded — regenerate data/world/natro_paths.yaml")
        pine = router.route("hive", "pine_tree")
        check(pine is not None and any("cannon" in leg.name for leg in pine.legs),
              "the router flies to Pine Tree", "the router does not fly to Pine Tree")
    except Exception as exc:
        problems.append(f"the route graph did not load: {exc}")

    # the ledger and the school directories are writable
    from hivemind.brain.school import SCHOOL_DIR
    for rel in ("var/trips.jsonl", f"var/{SCHOOL_DIR}", "var/homing", "var/routes"):
        path = ROOT / rel
        try:
            (path if path.suffix == "" else path.parent).mkdir(parents=True, exist_ok=True)
            probe = (path if path.suffix == "" else path.parent) / ".preflight"
            probe.write_text("ok")
            probe.unlink()
            notes.append(f"{rel} writable")
        except OSError as exc:
            problems.append(f"{rel} is not writable: {exc}")

    # the school's state, for the record
    try:
        from hivemind.brain.school import School
        notes.append("school: " + School(ROOT / "var" / SCHOOL_DIR).describe())
    except Exception as exc:
        problems.append(f"the school did not load: {exc}")

    for n in notes:
        print(f"  ok   {n}")
    for p in problems:
        print(f"  FIX  {p}")
    if problems:
        print(f"\n{len(problems)} problem(s); not ready.")
        return 1
    print("\nready. Restart in test mode with:\n  rm -f var/night/STOP; nohup ./scripts/overnight.sh --farm-seconds 90 > /dev/null 2>&1 &")
    print("(run scripts/diag_camera_view.py first if the camera view is to be measured — it needs the farm stopped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

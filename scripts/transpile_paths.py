#!/usr/bin/env python3
"""Convert BeeTuxMacro's recorded paths into distances.

The inherited macro stores 25 routes as blind timed holds:

    down_d
    wait 6.6
    up_d

That is open-loop and useless on its own -- it assumes a walkspeed. But its
`wait()` scales every hold by `BASE_SPEED / WALKSPEED` with BASE_SPEED = 32.2,
which means a recorded hold covers `seconds x 32.2` STUDS regardless of what
walkspeed the recorder had. So the recordings are walkspeed-independent distance
data, and the conversion is mechanical rather than a re-recording job.

What this buys, and what it does not:

  it DOES give a starting graph of 25 real routes with named endpoints, walked
  by a person, which is far better than coordinates invented from memory

  it does NOT give accurate distances. The recordings are someone else's, at an
  unknown moment, with unknown obstacles. Every edge is written out with
  `verified: false`.

That inaccuracy is tolerable precisely because the walker is closed-loop: it
measures actual displacement and stops at the right distance regardless of what
the edge claimed, and arrival is confirmed by landmark rather than by the clock.
A wrong edge length costs a slightly wrong route estimate, not a lost character.

TWO SOURCE FILES, NOT ONE

The travel routes are in `stuff/paths.sh`, which is all this ever read. But the
FIELD PATTERNS -- the little back-and-forth the character walks while it is
actually collecting pollen -- are in `stuff/utils.sh` instead, so they were
never transpiled at all. They are the same form: down_X / wait N / up_X. The
macro picks one by name in `config.sh:40` (`farm_pattern()`) and `farm.sh:11`
loops it forever while in a field; the owner's copy selects `farm_better_snake`
(`config.sh:47`). Whether THIS bot should walk one of them instead of its own
`collect_around` is an open question nobody has measured -- but a pattern that
is not in the graph cannot even be tried, so all three are transpiled.

    python3 scripts/transpile_paths.py [paths.sh] [utils.sh]
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

BASE_SPEED = 32.2          # studs per recorded second (BeeTuxMacro stuff/utils.sh)
# BeeTuxMacro's movement primitives, read from its stuff/utils.sh rather than
# guessed. Each maps to one op the executor implements.
#
#   jump               wtype -P space -s 40 -p space
#   jump_hold          wtype -P space              (press, no release)
#   jump_release       wtype -p space
#   shift_lock_toggle  sleep 0.3; wtype -P Shift_L -s 40 -p Shift_L; sleep 0.1
#   zoom_out           wtype -P O -p O
#   reset              Escape, R, Return, sleep 7.5   -> respawn at the hive
PRIMITIVES = {
    "jump": {"op": "jump"},
    "jump_hold": {"op": "jump_hold"},
    "jump_release": {"op": "jump_release"},
    "shift_lock_toggle": {"op": "shift_lock"},
    "zoom_out": {"op": "zoom", "direction": "out"},
    "zoom_in": {"op": "zoom", "direction": "in"},
    "reset": {"op": "reset"},
    "unhold_keys": {"op": "release_all"},
}

# Lines that are shell control flow, not instructions to the character.
SHELL_NOISE = {"done", "else", "fi", "esac", "then", "do"}

# The field patterns, read from stuff/utils.sh. These are the three names
# config.sh offers under `farm_pattern()` (config.sh:42-44); the owner's copy
# selects farm_better_snake at config.sh:47.
#
# ONLY these three are taken from utils.sh, on purpose. The rest of that file
# is shell machinery -- pixel probes, `bc` arithmetic, git update checks --
# with no distance in it, and importing it wholesale would ALSO start
# resolving `call` steps that currently resolve to nothing, quietly changing
# the length of edges that nobody has re-measured.
FARM_PATTERNS = ("farm_square", "farm_snake", "farm_better_snake")

DEFAULT_SOURCE = pathlib.Path.home() / "BeeTuxMacro/stuff/paths.sh"
OUT = pathlib.Path(__file__).resolve().parents[1] / "data/world/paths.yaml"

# The trailing "(?:\s*#.*)?" matters: five of the 25 routes carry a comment
# after the paren, and requiring end-of-line silently dropped ALL of them --
# including every return-to-hive path, which are the ones most needed.
FUNCTION = re.compile(r"^function\s+([a-z0-9_]+)\s*\((?:\s*#.*)?$")
DOWN = re.compile(r"^down_([wasd]+)$")
UP = re.compile(r"^up_([wasd]+)$")
WAIT = re.compile(r"^wait\s+([0-9.]+)$")
SLEEP = re.compile(r"^sleep\s+([0-9.]+)$")
# the hive-slot hop: `for ((i=0; i<5-$1; i++)); do`
SLOT_LOOP = re.compile(r"^for\s*\(\(i=0;\s*i<(\d+)-\$1;\s*i\+\+\)\);\s*do$")

# from_X_to_Y, and the two variants that carry a qualifier
ROUTE = re.compile(r"^from_(.+?)_to_(.+?)(?:_with_(.+)|_no_(.+))?$")


def dropped_hold(keys: str, between: list[str],
                 converted: bool = False,
                 superseded_by: str | None = None) -> dict | None:
    """The `raw` step for hold time no `wait` priced, or None when there is none.

    `down_w / sleep 4 / up_w` holds W down for four seconds of real time, and
    that is real movement -- but `sleep` is not `wait`. Only `wait` is scaled
    by BASE_SPEED/WALKSPEED (utils.sh:506), so only `wait` carries a distance
    that transfers between players; a `sleep` hold covers whatever the
    recorder's own walkspeed covered, which is not recoverable from the script.

    RE-MEASURED by walking every down_/up_ pair in both shell files. There are
    THREE shapes, not one, and the first version of this caught only the first:

      NOT PRICED AT ALL -- a `down_` that closes with no `wait` between.
      Two in paths.sh: `from_rose_field_to_hive` (paths.sh:699-701, sleep 0.1)
      and `from_pine_tree_to_hive` (paths.sh:761-763, sleep 4). Both used to
      vanish completely: the `down_w` produced no step, so the executor stood
      still through a four-second walk and carried on as though it arrived.

      PRICED, THEN HELD LONGER -- a `wait` gave a distance but the key stayed
      down across further `sleep`s. One in paths.sh:
      `from_hive_to_pumpkin_with_red_cannon` holds D across `wait 5 ; jump ;
      sleep 1 ; jump ; sleep 1 ; jump ; wait 5` (paths.sh:675-683). The two
      `wait`s are converted; the two `sleep`s are two more seconds of walking
      that used to disappear with nothing to point at.

      NEVER RELEASED -- a `down_` replaced by another `down_` with no `up_`
      between, so the recording keeps BOTH key sets down. One in paths.sh:
      `down_ds ; wait 1.3 ; down_d` (paths.sh:673-675), after which the macro
      is holding S and D while this graph walks D alone, and the macro never
      releases that S at all. We deliberately do NOT reproduce the stuck key
      (see the module docstring on `held()`), so the divergence is recorded.

    Only `sleep` counts as unpriced time. `jump` is `wtype -P space -s 40 -p
    space` (utils.sh) -- about 40 ms, below the 0.1 s resolution of anything
    else here -- and `camera_*` hides its own `sleep 0.1` inside the function,
    which this cannot see; neither occurs under a hold in paths.sh except the
    jumps above.

    This is the same silent-drop failure that lost 54 jumps and 22 shift-locks,
    and it is why an unconvertible hold becomes a `raw` step instead of nothing
    -- RouteRunner reports `raw` in `result.skipped`, so it shows up rather
    than being lost.
    """
    unpriced = [line for line in between if SLEEP.match(line)]
    if not converted:
        # NO `wait`, SO NO DISTANCE -- BUT THERE IS STILL A TIME.
        #
        # This used to emit a `raw` note, which RouteRunner reported as
        # skipped. That was honest and it was also useless: the step never
        # ran. `from_pine_tree_to_hive` holds W across `sleep 4` and that is
        # the GLIDE off the pine tree, so dropping it left the character
        # jumping off the edge and falling short every single cycle -- which
        # is precisely what the owner reported watching.
        #
        # Seconds are the right unit here and studs are not. Every other hold
        # is priced through `wait`, which scales by walkspeed so the same
        # recording works for any player. A fall does not: descent is not
        # affected by walkspeed, so re-pricing four seconds of gliding into a
        # distance and back would introduce an error that is not in the
        # recording. Emitting the time reproduces what was recorded.
        seconds = 0.0
        for line in between:
            match = SLEEP.match(line)
            if match:
                try:
                    seconds += float(match.group(1))
                except (TypeError, ValueError):
                    pass
        if seconds > 0:
            return {"op": "hold", "keys": keys, "seconds": round(seconds, 4)}
        detail = " ; ".join(between) if between else "nothing"
        return {"op": "raw",
                "text": f"down_{keys} held over [{detail}] then released -- "
                        "no `wait` and no `sleep`, so neither a distance nor "
                        "a time can be derived"}
    tail = (f" and across [{' ; '.join(unpriced)}], which no `wait` priced"
            if unpriced else "")
    if superseded_by is not None:
        return {"op": "raw",
                "text": f"down_{keys} was never released -- down_{superseded_by}"
                        f" replaced it{tail}; the recording keeps the earlier "
                        "keys down and this graph does not"}
    if unpriced:
        return {"op": "raw",
                "text": f"down_{keys} stayed down after its `wait`, across "
                        f"[{' ; '.join(unpriced)}] -- absolute time under a "
                        "held key, so no distance can be derived for it"}
    return None


def parse(text: str) -> dict[str, list[dict]]:
    """Split into named routes, each a list of steps."""
    routes: dict[str, list[dict]] = {}
    name: str | None = None
    steps: list[dict] = []
    pending: str | None = None          # keys currently held
    converted = False                   # ...and whether a `wait` priced it
    held_over: list[str] = []           # what happened while it was held
    in_slot_loop = False

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith(
            "function") else raw.strip()
        if not line or line.startswith("#"):
            continue

        opened = FUNCTION.match(line)
        if opened:
            name, steps, pending = opened.group(1), [], None
            converted, held_over = False, []
            continue
        if name is None:
            continue
        if line == ")":
            if pending:
                note = dropped_hold(pending, held_over, converted)
                if note:
                    steps.append(note)
            routes[name] = steps
            name, steps, pending = None, [], None
            converted, held_over = False, []
            continue

        # THE HIVE-SLOT HOP. `from_corner_to_hive` ends with a shell loop that
        # hops sideways along the hive slots:
        #
        #     for ((i=0; i<5-$1; i++)); do
        #         jump; sleep 0.56; jump; sleep 1
        #     done
        #
        # It is the reason the recorded routes work at all: they every one
        # assume the character starts AT ITS OWN HIVE SLOT, and this is how
        # BeeTuxMacro gets there. Transpiled as an opaque `raw` line, the hop
        # vanished and every hive route began from the wrong place -- which is
        # exactly what the first live run showed, landing on sand by slot 5
        # instead of at Pine Tree.
        #
        # The count depends on which slot the player owns, so it becomes a
        # parameterised op rather than a fixed number of jumps.
        hop = SLOT_LOOP.match(line)
        if hop:
            steps.append({"op": "hop_to_slot", "from_slot": int(hop.group(1))})
            in_slot_loop = True
            continue
        if in_slot_loop:
            if line == "done":
                in_slot_loop = False
            continue                     # the loop body is inside the op now

        down = DOWN.match(line)
        if down:
            if pending:
                # `superseded_by` because there was no `up_`: the recording is
                # still holding `pending` when the new keys go down.
                note = dropped_hold(pending, held_over, converted,
                                    superseded_by=down.group(1))
                if note:
                    steps.append(note)
            pending, converted, held_over = down.group(1), False, []
            continue
        up = UP.match(line)
        if up:
            if pending:
                note = dropped_hold(pending, held_over, converted)
                if note:
                    steps.append(note)
            pending, converted, held_over = None, False, []
            continue
        if pending:
            held = WAIT.match(line)
            if held:
                seconds = float(held.group(1))
                steps.append({"op": "walk", "keys": pending,
                              "studs": round(seconds * BASE_SPEED, 1)})
                converted = True
                continue
            # A down_ with something other than a wait between it and the up_
            # is not a distance we can convert. Whatever the line is still gets
            # its own step below; remember it here so the HOLD itself can be
            # reported when it closes, instead of disappearing. See
            # dropped_hold().
            held_over.append(line)

        naps = SLEEP.match(line)
        if naps:
            steps.append({"op": "pause", "seconds": float(naps.group(1))})
            continue
        if line == "e":
            steps.append({"op": "interact"})
            continue
        if line.startswith("camera_"):
            steps.append({"op": "camera", "direction": line[len("camera_"):]})
            continue

        # PRIMITIVES, not routes. These are BeeTuxMacro's own helper functions,
        # and treating them as calls to other paths made them silently vanish:
        # a bare name that matches no route contributes nothing and executes
        # nothing. 54 jumps, 22 shift-lock toggles and 4 resets disappeared
        # that way -- and they are not decoration. Jumps clear obstacles, shift
        # lock is what makes movement deterministic (it locks the character to
        # face the camera), and reset is the known-position anchor the whole
        # open-loop scheme depends on.
        if line in PRIMITIVES:
            steps.append(dict(PRIMITIVES[line]))
            continue
        # shell syntax, not instructions
        if line in SHELL_NOISE:
            continue
        if re.fullmatch(r"[a-z0-9_]+", line):
            steps.append({"op": "call", "route": line})
            continue
        steps.append({"op": "raw", "text": line})
    return routes


def distance(steps: list[dict], routes: dict[str, list[dict]],
             seen: frozenset[str] = frozenset()) -> float:
    """Total studs, FOLLOWING `call` steps into the routes they delegate to.

    Without this, a route that delegates its travel to another one reports zero.
    `from_hive_to_rose_field` is exactly that: it calls `from_hive_to_red_cannon`
    and then fires the cannon, so all 570 studs of walking live in the callee.
    A zero-length edge is not merely inaccurate -- Dijkstra reads it as FREE and
    routes everything through it.

    `seen` guards against a route that calls itself, directly or in a cycle.
    """
    total = 0.0
    for step in steps:
        if step["op"] == "walk":
            total += step["studs"]
        elif step["op"] == "call":
            target = step["route"]
            if target in routes and target not in seen:
                total += distance(routes[target], routes, seen | {target})
    return round(total, 1)


def endpoints(name: str) -> tuple[str, str, str] | None:
    m = ROUTE.match(name)
    if not m:
        return None
    src, dst = m.group(1), m.group(2)
    qualifier = m.group(3) or m.group(4) or ""
    # "..._and_back" is a round trip, not an edge to a place called "back"
    if dst.endswith("_and_back"):
        dst = dst[: -len("_and_back")]
        qualifier = (qualifier + " round-trip").strip()
    elif "_and_" in dst:
        # A route that visits two places. The edge ENDS at the last one and the
        # earlier stop is recorded as a waypoint.
        #
        # Without this, `from_hive_to_wealth_clock_and_stockings` transpiled to
        # a destination called "wealth_clock_and_stockings" -- a place that
        # exists nowhere in the game or the rest of the graph. It showed up in
        # Router().places, could be routed to, and Router().dead_ends() duly
        # listed it as somewhere reachable that you can never leave.
        stops = dst.split("_and_")
        dst = stops[-1]
        qualifier = (qualifier + " via " + ", ".join(stops[:-1])).strip()
    return src, dst, qualifier


def farm_patterns(utils: pathlib.Path, routes: dict[str, list[dict]],
                  source_name: str) -> list[str]:
    """Merge the named field patterns from utils.sh into `routes`.

    Returns the names it could NOT find, because a missing pattern has to be
    said out loud: the bot walks the pattern for the whole time it is in a
    field, so a graph that quietly lacks it is a graph that collects nothing.
    """
    if not utils.exists():
        print(f"  WARNING: no {utils} -- no field patterns in this graph")
        return list(FARM_PATTERNS)

    found = parse(utils.read_text())
    missing = []
    for pattern in FARM_PATTERNS:
        steps = found.get(pattern)
        if steps is None:
            missing.append(pattern)
        elif pattern in routes:
            # Which file a name came from decides what the bot does when it
            # runs it, so a collision is reported rather than resolved silently.
            print(f"  WARNING: {pattern} is defined in BOTH files; "
                  f"keeping {source_name}'s")
        else:
            routes[pattern] = steps
    for pattern in missing:
        print(f"  WARNING: {pattern} is not in {utils}")
    return missing


def main() -> int:
    source = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.exists():
        print(f"  no path file at {source}")
        return 2
    # The field patterns live beside paths.sh in utils.sh; see FARM_PATTERNS.
    utils = (pathlib.Path(sys.argv[2]) if len(sys.argv) > 2
             else source.parent / "utils.sh")

    routes = parse(source.read_text())
    missing = farm_patterns(utils, routes, source.name)
    edges, other = [], []
    for name, steps in sorted(routes.items()):
        record = {
            "name": name,
            "studs": distance(steps, routes),
            "steps": steps,
            "verified": False,
        }
        pair = endpoints(name)
        if pair:
            record["from"], record["to"], qualifier = pair[0], pair[1], pair[2]
            if qualifier:
                record["via"] = qualifier
            edges.append(record)
        else:
            other.append(record)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# Routes transpiled from BeeTuxMacro's recorded timed holds by\n"
        "# scripts/transpile_paths.py, using studs = seconds x 32.2.\n"
        "#\n"
        "# Travel routes come from stuff/paths.sh; the farm_* field patterns\n"
        "# come from stuff/utils.sh, which is where BeeTuxMacro keeps them.\n"
        "#\n"
        "# EVERY EDGE IS `verified: false`. These are someone else's recordings\n"
        "# at an unknown moment, so the distances are approximate. That is\n"
        "# tolerable because the walker is closed-loop: it measures real\n"
        "# displacement and arrival is confirmed by landmark, not by the clock.\n"
        "# An edge length that is wrong costs a slightly wrong route estimate,\n"
        "# not a lost character. Edges are re-measured and marked verified as\n"
        "# the bot actually walks them.\n"
        "#\n"
        "# Do not hand-edit: re-run the transpiler.\n"
        + yaml.safe_dump({"schema": 1, "base_speed": BASE_SPEED,
                          "edges": edges, "routines": other},
                         sort_keys=False, default_flow_style=False))

    total = sum(e["studs"] for e in edges)
    print(f"  {len(routes)} routes parsed from {source}")
    print(f"  {len(edges)} are point-to-point edges, {len(other)} are routines")
    print(f"  {total:,.0f} studs of recorded travel")
    print(f"  places: {sorted({e['from'] for e in edges} | {e['to'] for e in edges})}")
    for pattern in FARM_PATTERNS:
        if pattern in routes:
            steps = routes[pattern]
            walks = sum(1 for s in steps if s["op"] == "walk")
            raws = sum(1 for s in steps if s["op"] == "raw")
            print(f"  {pattern}: {distance(steps, routes):,.1f} studs over "
                  f"{walks} holds" + (f", {raws} unconvertible" if raws else ""))
    print(f"  wrote {OUT}")
    # Non-zero when a field pattern is missing: the file is still written (the
    # travel graph is fine and useful), but the output is incomplete and a
    # regeneration script must not treat that as success.
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Natro Macro's own gather patterns, per field, as routines this bot can walk.

WHY THE PATTERN MATTERS AS MUCH AS THE FIELD. `farm_snake`, the pattern every
trip has used, walks twelve 16-stud legs 3 studs apart: 232 studs inside a
box about 16 by 38 studs. A Bee Swarm field is roughly 200 studs across, so
the bot has been farming a corner of it and re-walking flowers it has already
emptied. The owner saw the consequence from the other side -- "im walking in
small radius so it jumps on me and when i die i loose all pollen".

Natro Macro ships the community's patterns and, per field, which one to use
with what size and width (`nm_importFieldDefaults` in submacros/natro_macro.ahk,
GPLv3, read 2026-09-22). Dandelion, for instance, is CornerXSnake at size M
and width 6 -- about 609 studs a pass over the whole field. Those numbers are
thousands of players' tuning and they are free to take.

HOW A PATTERN FILE IS READ. Each `patterns/*.ahk` is an imperative list of
key-down/up sends and `Walk(n)` calls, where n is TILES (4 studs, lib/Walk.ahk)
and may be an expression in `size` and `reps`:

    send "{" TCLRKey " down}"        toward-centre left/right key goes down
    Walk(4 * size)                   hold it for 4*size tiles
    send "{" TCLRKey " up}{" TCFBKey " down}"
    Walk( Sqrt( ( ( 8 * size ) ** 2 ) + ( ( 8 * size ) ** 2 ) ) )   a diagonal

So this walks the file with a set of held keys, and every `Walk` becomes one
`walk` step with those keys and that distance. `loop reps { ... }` repeats its
block. `Sleep n` becomes a `pause`. The toward/away keys resolve per field
from its `invertFB`/`invertLR` flags exactly as `natro_macro.ahk` does:

    TCFB = w, AFCFB = s      (swapped when invertFB)
    TCLR = a, AFCLR = d      (swapped when invertLR)

WHAT IS LEFT OUT, and it is not an oversight: the camera rotation between
passes (`turns`), the sprinkler placement, and the drift check. Rotating the
camera mid-gather would invalidate every pixel threshold the vision layer was
measured at, sprinklers need a UI this bot has never seen, and the drift check
is Natro's own image search. The WALK is what this takes.

    ./scripts/transpile_natro_patterns.py <natro-checkout>/patterns
"""
from __future__ import annotations

import argparse
import math
import pathlib
import re

STUDS_PER_TILE = 4.0
SIZES = {"XS": 0.25, "S": 0.5, "M": 1.0, "L": 1.5, "XL": 2.0}

# From nm_importFieldDefaults (natro_macro.ahk), verbatim: the pattern, its
# size letter, its width (which is `reps` when the pattern uses it) and the
# invert flags that decide which key is "toward the centre". Fields Natro has
# no default for keep whatever the settings say.
# WHERE WE DISAGREE WITH NATRO, and why. Natro gives Cactus, Clover and Stump
# "Stationary" -- stand still for ten seconds a pass and let a wide collector
# do the work. That assumes you START where its own route puts you, next to
# the sprinkler. This bot arrives by cannon and lands wherever the flight
# ends. MEASURED 2026-09-23:
#
#     stump    Stationary  453,791 pollen in 968 s = 469/s   (landed in flowers)
#     cactus   Stationary        0 pollen in 227 s over 22 passes
#
# Standing still off the flowers collects nothing, and the trip reported it
# honestly ("collected no pollen and the feed never named a field"). So
# Stationary is kept only where it has been measured to pay, and the others
# walk Natro's CornerXSnake at the width its community chose for them.
FIELD_DEFAULTS = {
    "bamboo": ("CornerXSnake", "M", 3, 0, 1),
    "cactus": ("CornerXSnake", "M", 1, 0, 0),
    "clover": ("CornerXSnake", "M", 1, 0, 0),
    "coconut": ("CornerXSnake", "M", 3, 0, 1),
    "dandelion": ("CornerXSnake", "M", 6, 0, 1),
    "mushroom": ("CornerXSnake", "M", 2, 0, 1),
    "pepper": ("CornerXSnake", "M", 5, 0, 0),
    "pineapple": ("CornerXSnake", "M", 1, 0, 1),
    "pumpkin": ("CornerXSnake", "M", 5, 0, 1),
    "rose_field": ("CornerXSnake", "M", 1, 0, 1),
    "spider": ("CornerXSnake", "M", 1, 0, 1),
    "strawberry": ("CornerXSnake", "M", 1, 0, 1),
    "stump": ("Stationary", "S", 1, 0, 0),      # measured at 469 pollen/s; kept
    "sunflower": ("CornerXSnake", "M", 4, 0, 1),
    # Natro has no default for these two; they are CornerXSnake at its own
    # default width, which is what its GUI starts every field at.
    "blue_flower": ("CornerXSnake", "M", 3, 0, 1),
    "pine_tree": ("CornerXSnake", "M", 3, 0, 1),
    "mountain_top": ("CornerXSnake", "M", 1, 0, 1),
}

# NATRO'S OWN FIELD START, read from its source rather than copied by hand.
# MEASURED 2026-09-26: FIELD_DEFAULTS above says "Natro has no default for
# these two" of Blue Flower and Pine Tree, and has Mountain Top at width 1 --
# but natro_macro.ahk:1622, 1757 and 1787 give all three (Blue Flower width
# 7, Pine Tree 3, Mountain Top 3, invertLR 0 for each, against 1 here). And
# Natro never starts a pattern where the route ends: nm_gather's caller runs
# nm_setSprinkler(field, loc, dist) first (natro_macro.ahk:16612), which walks
# forward or back `flen` and left or right `fwid` to the field's sprinkler
# spot (17259-17341), then turns the camera `turns` taps (16614-16617), and
# only then walks the pattern. So besides FIELD_DEFAULTS' routines this also
# writes, for every field Natro has a default for, `natro_start_<field>` (the
# walk to its spot and the camera turn) and `natro_pattern_<field>_as_natro`
# (the pattern with Natro's own size, width and invert flags). run_farm uses
# the pair only with `gather.natro_field_start` on; the routines above are
# unchanged, byte for byte.
NATRO_NAMES = {"rose": "rose_field"}


def natro_defaults(macro: str) -> dict[str, dict]:
    """FieldDefault[...] := Map(...) from natro_macro.ahk, by our field name."""
    out = {}
    for m in re.finditer(r'FieldDefault\["([^"]+)"\] := Map\((.*?)\)\s*\n', macro, re.S):
        kv = dict(re.findall(r'"(\w+)",\s*"?([^",\n]+?)"?\s*(?:,|$)', m.group(2)))
        name = m.group(1).lower().replace(" ", "_")
        out[NATRO_NAMES.get(name, name)] = kv
    return out


def natro_dimensions(macro: str) -> dict[str, tuple[int, int]]:
    """nm_setSprinkler's `flen` and `fwid` per field, in Natro's move units
    (milliseconds at movespeed 18), before the `dist/10` scaling."""
    start = macro.index("nm_setSprinkler(field, loc, dist){")
    body = macro[start:macro.index("MoveSpeedFactor:=", start)]
    out = {}
    for m in re.finditer(r'case\s+((?:"[^"]+"\s*,?\s*)+):\s*flen:=(\d+)\*dist/10\s*'
                         r'fwid:=(\d+)\*dist/10', body):
        for name in re.findall(r'"([^"]+)"', m.group(1)):
            key = name.lower().replace(" ", "_")
            out[NATRO_NAMES.get(key, key)] = (int(m.group(2)), int(m.group(3)))
    return out


# nm_Move holds a key MoveTime ms with MoveTime = units * 18 / MoveSpeedNum,
# so at any movespeed the distance is units / 1000 * 18 studs.
STUDS_PER_NATRO_UNIT = 18.0 / 1000.0


def start_steps(dims: tuple[int, int], loc: str, dist: int,
                camera: str, turns: int) -> list[dict]:
    """nm_setSprinkler's walk to the spot, then the camera turn."""
    flen, fwid = (dims[0] * dist / 10.0, dims[1] * dist / 10.0)
    steps: list[dict] = []
    low = loc.lower()
    if "upper" in low:
        steps.append({"op": "walk", "keys": "w", "studs": round(flen * STUDS_PER_NATRO_UNIT, 2)})
    elif "lower" in low:
        steps.append({"op": "walk", "keys": "s", "studs": round(flen * STUDS_PER_NATRO_UNIT, 2)})
    if "left" in low:
        steps.append({"op": "walk", "keys": "a", "studs": round(fwid * STUDS_PER_NATRO_UNIT, 2)})
    elif "right" in low:
        steps.append({"op": "walk", "keys": "d", "studs": round(fwid * STUDS_PER_NATRO_UNIT, 2)})
    if low == "center":
        steps.append({"op": "pause", "seconds": 1.0})        # Natro's Sleep 1000
    direction = camera.lower()
    if direction in ("left", "right"):
        steps += [{"op": "camera", "direction": direction} for _ in range(max(0, int(turns)))]
    return steps


SEND = re.compile(r'send\s+"(.*)"', re.IGNORECASE)
TOKEN = re.compile(r'\{\s*"?\s*(\w+)\s*"?\s*(up|down)?\s*\}', re.IGNORECASE)
WALK = re.compile(r"Walk\(\s*(.+?)\s*\)\s*$", re.IGNORECASE)
SLEEP = re.compile(r"Sleep\s+(\d+)", re.IGNORECASE)
LOOP = re.compile(r"loop\s+(\w+)\s*\{", re.IGNORECASE)
KEYNAMES = ("TCFBKey", "AFCFBKey", "TCLRKey", "AFCLRKey",
            "FwdKey", "BackKey", "LeftKey", "RightKey")


def keymap(invert_fb: int, invert_lr: int) -> dict[str, str]:
    """Natro's own assignment (nm_gather, "set direction keys")."""
    fb = ("s", "w") if invert_fb else ("w", "s")
    lr = ("d", "a") if invert_lr else ("a", "d")
    return {"TCFBKey": fb[0], "AFCFBKey": fb[1],
            "TCLRKey": lr[0], "AFCLRKey": lr[1],
            "FwdKey": "w", "BackKey": "s", "LeftKey": "a", "RightKey": "d"}


def tiles(expression: str, size: float, reps: int) -> float:
    """Evaluate a Walk() argument. Arithmetic only, and `Sqrt`."""
    text = expression.replace("Sqrt", "sqrt")
    allowed = {"sqrt": math.sqrt, "size": size, "reps": reps}
    if re.search(r"[A-Za-z_]+", text.replace("sqrt", "").replace("size", "").replace("reps", "")):
        raise ValueError(f"unknown name in Walk({expression})")
    return float(eval(text, {"__builtins__": {}}, allowed))     # noqa: S307 - arithmetic only


def steps_of(text: str, size: float, reps: int, keys: dict[str, str]) -> list[dict]:
    """The pattern as walk/pause steps, in order."""
    held: list[str] = []
    steps: list[dict] = []

    def emit(distance_tiles: float) -> None:
        if distance_tiles <= 0:
            return
        studs = round(distance_tiles * STUDS_PER_TILE, 2)
        if held:
            steps.append({"op": "walk", "keys": "".join(held), "studs": studs})
        else:
            # A Walk with nothing held covers no ground; Natro uses it to wait
            # for the walk thread. Recorded as a pause of the same time at
            # base speed rather than dropped.
            steps.append({"op": "pause", "seconds": round(studs / 32.2, 2)})

    def run(lines: list[str]) -> None:
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            if not line or line.startswith(";"):
                continue
            loop = LOOP.search(line)
            if loop:
                depth, body = 1, []
                while i < len(lines) and depth:
                    inner = lines[i]
                    i += 1
                    depth += inner.count("{") - inner.count("}")
                    if depth:
                        body.append(inner)
                count = reps if loop.group(1).lower() == "reps" else int(loop.group(1))
                for _ in range(max(0, int(count))):
                    run(body)
                continue
            send = SEND.search(line)
            if send:
                for name, updown in TOKEN.findall(send.group(1)):
                    if name not in KEYNAMES:
                        continue            # a rotation or a space: not a walk key
                    key = keys[name]
                    if (updown or "").lower() == "down":
                        if key not in held:
                            held.append(key)
                    elif (updown or "").lower() == "up" and key in held:
                        held.remove(key)
                continue
            walk = WALK.search(line)
            if walk:
                emit(tiles(walk.group(1), size, reps))
                continue
            nap = SLEEP.search(line)
            if nap:
                steps.append({"op": "pause", "seconds": round(int(nap.group(1)) / 1000.0, 2)})
                continue
    run(text.splitlines())
    if held:
        steps.append({"op": "release_all"})
    return steps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("patterns", help="Natro Macro's patterns/ directory")
    ap.add_argument("-o", "--out", default="data/world/natro_patterns.yaml")
    ap.add_argument("--macro", help="natro_macro.ahk (default: ../submacros/ "
                                    "beside the patterns directory)")
    args = ap.parse_args()
    folder = pathlib.Path(args.patterns)
    macro_path = pathlib.Path(args.macro) if args.macro else \
        folder.parent / "submacros" / "natro_macro.ahk"

    routines = []
    skipped = []
    for field, (pattern, size_letter, width, invert_fb, invert_lr) in sorted(FIELD_DEFAULTS.items()):
        path = folder / f"{pattern}.ahk"
        if not path.exists():
            skipped.append(f"{field}: no pattern file {pattern}.ahk")
            continue
        size = SIZES[size_letter]
        keys = keymap(invert_fb, invert_lr)
        try:
            steps = steps_of(path.read_text(encoding="utf-8-sig", errors="replace"),
                             size, width, keys)
        except ValueError as exc:
            skipped.append(f"{field}: {exc}")
            continue
        walks = [s for s in steps if s["op"] == "walk"]
        if not walks and pattern != "Stationary":
            skipped.append(f"{field}: {pattern} produced no walks")
            continue
        routines.append({
            "name": f"natro_pattern_{field}",
            "studs": round(sum(s["studs"] for s in walks), 1),
            "verified": False,
            "source": f"NatroMacro patterns/{pattern}.ahk, field defaults for {field}",
            "pattern": pattern, "size": size_letter, "width": width,
            "invert_fb": invert_fb, "invert_lr": invert_lr,
            "steps": steps,
        })

    # NATRO'S OWN START AND PATTERN, per field (see NATRO_NAMES above).
    if macro_path.exists():
        macro = macro_path.read_text(encoding="utf-8-sig", errors="replace")
        defaults, dims = natro_defaults(macro), natro_dimensions(macro)
        for field in sorted(defaults):
            kv = defaults[field]
            pattern = kv.get("pattern", "")
            path = folder / f"{pattern}.ahk"
            if field not in dims or not path.exists():
                skipped.append(f"{field}: no Natro start (dimensions or {pattern}.ahk missing)")
                continue
            try:
                width = int(kv.get("width", 1))
                invert_fb, invert_lr = int(kv.get("invertFB", 0)), int(kv.get("invertLR", 0))
                size_letter = kv.get("size", "M")
                steps = steps_of(path.read_text(encoding="utf-8-sig", errors="replace"),
                                 SIZES[size_letter], width, keymap(invert_fb, invert_lr))
                start = start_steps(dims[field], kv.get("sprinkler", "Center"),
                                    int(kv.get("distance", 10)), kv.get("camera", "None"),
                                    int(kv.get("turns", 0)))
            except (ValueError, KeyError) as exc:
                skipped.append(f"{field}: Natro start: {exc}")
                continue
            walks = [x for x in steps if x["op"] == "walk"]
            routines.append({
                "name": f"natro_pattern_{field}_as_natro",
                "studs": round(sum(x["studs"] for x in walks), 1),
                "verified": False,
                "source": f"NatroMacro patterns/{pattern}.ahk with natro_macro.ahk's own FieldDefault[{field}]",
                "pattern": pattern, "size": size_letter, "width": width,
                "invert_fb": invert_fb, "invert_lr": invert_lr,
                "steps": steps,
            })
            routines.append({
                "name": f"natro_start_{field}",
                "studs": round(sum(x.get("studs", 0.0) for x in start), 1),
                "verified": False,
                "source": (f"natro_macro.ahk nm_setSprinkler({field}, "
                           f"{kv.get('sprinkler', 'Center')}, {kv.get('distance', 10)}) and the "
                           f"camera turn ({kv.get('camera', 'None')} x{kv.get('turns', 0)})"),
                "steps": start,
            })
    else:
        skipped.append(f"no {macro_path}: Natro's own starts not written")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# Natro Macro's gather patterns, per field, transpiled to routines.",
        "#",
        "# GENERATED by scripts/transpile_natro_patterns.py -- do not hand-edit;",
        "# edit the transpiler, which explains what is taken and what is left.",
        "#",
        "# SOURCE: NatroTeam/NatroMacro, patterns/*.ahk and the per-field defaults",
        "# in submacros/natro_macro.ahk, licensed GPLv3. Running and deriving from",
        "# it privately carries no obligation; publishing this project with these",
        "# patterns in it would mean publishing under the GPL too.",
        "#",
        "# `Walk(n)` is n TILES and a tile is 4 studs, so every distance is studs.",
        "# The camera turns, sprinkler placement and drift check of Natro's gather",
        "# are NOT here: see the transpiler's docstring for why.",
        "schema: 1",
        "routines:",
    ]
    import yaml
    body = yaml.safe_dump({"routines": routines}, sort_keys=False,
                          default_flow_style=False, width=100)
    body = body.split("routines:\n", 1)[1]
    out.write_text("\n".join(header) + "\n" + body)

    print(f"{len(routines)} pattern(s) -> {out}")
    for r in routines:
        walks = sum(1 for s in r["steps"] if s["op"] == "walk")
        if "pattern" not in r:              # a natro_start_<field>
            turns = sum(1 for s in r["steps"] if s["op"] == "camera")
            print(f"  {r['name']:40s} {r['studs']:7.1f} studs to the spot, "
                  f"{turns} camera tap(s)")
            continue
        print(f"  {r['name']:40s} {r['pattern']:14s} size {r['size']} width {r['width']:>2d} "
              f"{r['studs']:7.1f} studs, {walks:3d} walks")
    for line in skipped:
        print(f"  skipped {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

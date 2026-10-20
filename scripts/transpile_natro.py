#!/usr/bin/env python3
"""Turn Natro Macro's field paths into this project's route graph.

THE OWNER'S IDEA: teach it using samples of Natro Macro's movements. They
is right, and the reason is measured rather than aesthetic.
Every route this bot had came from BeeTuxMacro, and on their account they do not
work: across a whole night of watching, 31% to 83% of every walk was spent
pressed against a wall, in both directions, and the character finished wedged
between two hive bases (`var/incidents/234206-refused/149_t+12.7s.jpg`). The bot
itself ruled out the camera heading as the cause by trying all four quarters and
arriving nowhere (docs/DESIGN.md 8k).

WHY NATRO'S ARE DIFFERENT, and it is not that they are newer:

  1. THEY SAY WHERE THEY START FROM. Every path opens with `nm_gotoRamp()`,
     which is `nm_Walk(5, Fwd)` then `nm_Walk(9.2*HiveSlot-4, Right)` -- the
     hive slot appears as a NUMBER in a linear formula, so a path can be run
     from any slot by supplying it. BeeTuxMacro's routes bake the recorder's
     own slot in and there is no way to correct for it. This is the exact
     parameter `docs/GAPS.md` has been asking the owner for, and Natro shows
     both the spacing (9.2 tiles, so 36.8 studs) and the offset (-4 tiles).

  2. MOST FIELDS HAVE A PATH THAT NEEDS NO CANNON. Each `gtf-*.ahk` has a
     `MoveMethod = "Cannon"` branch and an `else` branch that simply walks, and
     five fields have no cannon branch at all. The walking branch presses no
     `e`, boards nothing, jumps over nothing and glides nowhere -- so none of
     the machinery that has been failing is involved. Mushroom is two walks
     and a camera turn.

  3. THEY COVER EVERYTHING. 17 fields out, 17 walks back, 6 quest givers and
     the three field boosters (first taken for the shops; see BOOSTERS) --
     which is most of the "needs the owner" list in docs/GAPS.md.

WHAT IS TAKEN AND WHAT IS NOT. Only the walking branch: distances, directions
and camera turns. The cannon branches are deliberately left behind, and so is
every `Gdip_ImageSearch`, buff-reading and window-poking line -- this project
has its own vision and its own input layer and does not want a second one.

    nm_Walk(n, KeyA[, KeyB])   ->  walk n*4 studs holding those keys
    send "{RotRight 4}"        ->  four camera taps right
    HyperSleep(200) / Sleep 1  ->  a pause

THE UNIT IS MEASURED, NOT ASSUMED. `lib/Walk.ahk` reads
`l := n * freq * 4 ; 4 studs in a tile`, so `nm_Walk`'s argument is tiles and a
tile is four studs. Natro then walks until the accumulated distance reaches the
target, reading the haste icons as it goes; this project's runner holds the key
for `studs / walkspeed`, which is the same distance under the same assumption
about a clean run.

LICENCE, AND IT MATTERS IF THIS REPO IS EVER PUBLISHED. Natro Macro is
GPLv3 (NatroTeam/NatroMacro, LICENSE.md). Running it and deriving from it
privately carries no obligation -- copyleft attaches to distribution -- but
publishing Hivemind with these paths in it would mean publishing Hivemind under
the GPL too. The generated file records this at the top so the decision is never
made by accident. Individual paths credit their authors the way Natro does, in
trailing `;path <date> <name>` comments, and those are carried across.

    ./scripts/transpile_natro.py <natro-checkout>/paths -o data/world/natro_paths.yaml
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

# Natro's key variables, and the letters this project's input layer wants.
# `RotLeft:="sc033" ; ,` and `RotRight:="sc034" ; .` in natro_macro.ahk -- the
# same comma and period `act.routes.CAMERA_KEYS` already uses.
KEYS = {"FwdKey": "w", "BackKey": "s", "LeftKey": "a", "RightKey": "d"}
# Natro's authors spell them `Backkey`, `rightkey` and `nm_walk` as often as
# not, and a reader that matched only the canonical spelling dropped the walk
# -- wf-pineapple's `nm_walk(30, FwdKey)` and wf-coconut's `Backkey` among
# them. Every lookup goes through this.
KEYS_LOWER = {k.lower(): v for k, v in KEYS.items()}


def key_of(name: str) -> str | None:
    """The letter for a Natro key variable, whatever its capitalisation."""
    return KEYS_LOWER.get(str(name or "").lower())
STUDS_PER_TILE = 4.0            # lib/Walk.ahk: "4 studs in a tile"

# nm_gotoRamp(), expanded. See the module docstring, point 1.
RAMP_FORWARD_TILES = 5.0
RAMP_SLOT_TILES = 9.2
RAMP_SLOT_OFFSET = -4.0

WALK = re.compile(r"nm_Walk\(\s*([-\d.]+)\s*,\s*([A-Za-z]+Key)\s*(?:,\s*([A-Za-z]+Key)\s*)?\)",
                  re.IGNORECASE)

# A WALK WHOSE LENGTH DEPENDS ON THE HIVE SLOT. Exactly two shapes appear
# anywhere in Natro, checked across every path file and the main script:
#
#     nm_Walk(9.2*HiveSlot-4, RightKey)            the ramp, in nm_gotoRamp
#     nm_Walk(9.2*(7-HiveSlot) + 10, LeftKey)      the honey dispenser
#
# Both are linear in the slot, so both become one `hive_offset` step with its
# own slope and intercept. Anything else is left alone rather than guessed at.
HIVE_PLAIN = re.compile(
    r"nm_Walk\(\s*([\d.]+)\s*\*\s*HiveSlot\s*([-+]\s*[\d.]+)?\s*,"
    r"\s*([A-Za-z]+Key)\s*\)", re.IGNORECASE)
HIVE_FLIPPED = re.compile(
    r"nm_Walk\(\s*([\d.]+)\s*\*\s*\(\s*([\d.]+)\s*-\s*HiveSlot\s*\)"
    r"\s*([-+]\s*[\d.]+)?\s*,\s*([A-Za-z]+Key)\s*\)", re.IGNORECASE)
ROT = re.compile(r'send\s+"\{"\s*(RotLeft|RotRight)\s*"\s*(\d+)\}"', re.IGNORECASE)
SLEEP = re.compile(r"(?:HyperSleep\(\s*(\d+)\s*\)|Sleep\s*\(\s*(\d+)\s*\)|Sleep\s+(\d+))",
                   re.IGNORECASE)
# `Walk(n)` with keys already held down: cover n tiles without touching the
# keys. Distinct from `nm_Walk`, which presses its own.
COAST = re.compile(r"(?<![A-Za-z_])Walk\(\s*([\d.]+)\s*\)", re.IGNORECASE)
CREDIT = re.compile(r";\s*(path\s+\d+.*|\[\d{4}-\d{2}-\d{2}.*)", re.IGNORECASE)
# One `{...}` token inside a `send` line once AutoHotkey's string pieces are
# joined: `{e up}`, `{RightKey down}`, `{space 2}`, `{RotLeft 4}`. A name that
# came from a variable between the quotes carries VARIABLE_MARK (send_tokens).
SEND_TOKEN = re.compile(r"\{\s*(\x00?)([A-Za-z_][A-Za-z0-9_]*)\x00?\s*([A-Za-z0-9]*)\s*\}")
# A `send` line's pieces: a quoted string, or a bare name between them.
SEND_PIECE = re.compile(r'"([^"]*)"|([A-Za-z_][A-Za-z0-9_]*)')
# A KEY VARIABLE WRITTEN INSIDE THE QUOTES IS NOT THE KEY. AutoHotkey builds
# `"{" FwdKey " down}"` by concatenation, so there the variable's value is the
# key; `"{FwdKey down}"` asks for a key named "FwdKey", which does not exist,
# and SendKeys skips an unrecognised brace sequence whole -- "it's safest not
# to send the contents literally" (AutoHotkey's source/keyboard_mouse.cpp,
# RESEARCHED 2026-09-27). gtc-blueberrydis.ahk's cannon branch ends `send
# "{FwdKey down}{space down}"`, the only such line in paths/, so Natro jumps in
# place there; read as a W held to the end of the route, the flight ran on
# past the dispenser (attempt 493: landed 0 of 3, twice in the Blue Flower
# Field).
VARIABLE_MARK = "\x00"

# THE CANNON. The owner, 2026-09-22: use the cannon for far places.
# Natro's cannon branches are the experienced players' flight timings -- hold
# these keys, wait this long, fire, wait this long, release -- and this is the
# walking distance above which a field counts as far enough to fly to. Below
# it the walk is kept: the cannon costs a ramp walk, a hop and a hold to find
# it (act/routes, DESIGN 8dl), and a flight, and a near field is reached
# sooner on foot.
CANNON_FROM_WALK_STUDS = 400.0
# How the cannon's own steps are costed against a walk, in studs-equivalent
# at Natro's base speed: the approach was about three hops of 3.5 tiles, and
# every wait during the flight is time that could have been walking. The
# approach is now one hop and a hold that ends on sight; each live approach
# logs "~N studs" of hold ("at the red cannon after 1 hop and ..."), and this
# is re-derived from those, not before.
CANNON_APPROACH_STUDS = 42.0
BASE_MOVESPEED = 28.0


# THE CONDITION A PATH BRANCHES ON. Two shapes: `MoveMethod = "walk"` /
# `"Cannon"`, and the walks home's `HiveBees < 12` (walk when the hive is
# small, else the yellow cannon). `group("way")` names the FIRST branch.
#
# AND `HiveBees > 25`, which this did not match until 2026-09-26, so the
# whole file was treated as one path and BOTH branches were emitted back to
# back. `gtc-strawberrydis.ahk:1` is the only one: 33 steps of hops and a
# glide for a hive of more than 25 bees, `else` a 1,943-stud walk round.
# MEASURED on the only two walks of it (attempts 347 and 349): the frame after
# the first branch's last leg reads "Use the Strawberry Dispenser" both times
# (`022630-...-33-walk-sd30.jpg`, `030750-...-33-walk-sd30.jpg`) -- and the
# route then walked the `else` branch away from it and ended on a free pad
# ("Claim Hive", run-349 03:09:18). The first branch is the one taken with
# a 26-bee hive (as on the test account then), and run_farm's
# ROUTES_PLACE_BEES refuses the place for a hive that does not meet the
# condition rather than walking a route it cannot.
BRANCH = re.compile(
    r'if\s*\(.*?(?:MoveMethod\s*=\s*"(?P<method>\w+)"|HiveBees\s*[<>]=?\s*\d+).*?\)\s*\{?',
    re.IGNORECASE)
# The `HiveBees > n` shape on its own, so the route's `source` can say which
# branch it is.
BIG_HIVE = re.compile(r"if\s*\(\s*HiveBees\s*(>=?)\s*(\d+)\s*\)", re.IGNORECASE)
# THE METHOD, WHEREVER ON THE CONDITION'S LINE IT IS. BRANCH stops at the
# first shape it knows, and with `>=` known it stops at the bee count in
# `If (HiveBees >= 25) && (MoveMethod = "cannon")` (gtp-pineapple.ahk:1,
# gtp-stump.ahk:1), which would have made the cannon block the walk. No gtp-
# path is transpiled today; this keeps it right if one ever is.
METHOD = re.compile(r'MoveMethod\s*=\s*"(\w+)"', re.IGNORECASE)
# A CONDITION LEFT IN THE BODY IS ONE THIS DID NOT UNDERSTAND. The chosen
# branch of a path that branched on a shape BRANCH did not know was the whole
# file, both branches back to back -- natro_out_strawberry_dispenser walked
# 2,029 studs that way (audit, motion slice). Over every file in Natro's
# paths/ (commit 094f9c7b) no chosen body keeps an `if (` or `else` now, so a
# path that does is refused and named, never concatenated.
LEFTOVER = re.compile(r"^\s*(?:if\s*\(|else\b)", re.IGNORECASE | re.MULTILINE)
ELSE = re.compile(r"else\s*\{|else\s*\n\s*\{", re.IGNORECASE)


def block_end(text: str, opened: int) -> int:
    """The index of the `}` closing the `{` at `opened`, or -1.

    BRACES INSIDE STRINGS ARE NOT BLOCKS. `send "{" RotLeft " 2}"` and
    `send "{space down}"` are full of them, and the first version of the
    branch splitter used `rfind("}")` -- so a path's trailing walks (the ones
    after the if/else, shared by both branches) were handed to the cannon
    branch and the walking route lost them. MEASURED 2026-09-23: Natro's
    `gtq-bucko.ahk` ends its if/else with a jump and nine walks up onto the
    Bucko Bee's platform; the transpiled `natro_out_bucko_bee` had one of the
    nine, and every recon ended in the Blue HQ looking at a wall.
    """
    depth = 0
    quoted = False
    i = opened
    while i < len(text):
        c = text[i]
        if quoted:
            if c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c == ";":
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline
            continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _branches(text: str):
    """`(preamble, first, second, trailing, first_is_walk)` for a branching
    path, or None when it does not branch. `preamble` is what comes BEFORE
    the `if` and `trailing` what follows the whole if/else; both belong to
    both branches.

    THE PREAMBLE WAS DROPPED for an hour on 2026-09-23: the field paths out
    all begin with their `if`, so nothing noticed until the walks home were
    put through the same selector -- `wf-pineapple.ahk` walks nine
    statements and turns the camera a half turn before its `if (HiveBees <
    12)`, and the route came out starting inside the branch, a half turn
    wrong. Caught by `test_every_walk_home_undoes_its_own_walk_out`.
    """
    condition = BRANCH.search(text)
    if condition is None:
        return None
    said = METHOD.search(text[condition.start():].split("\n", 1)[0])
    method = (said.group(1) if said else "").lower()
    # `HiveBees < n` (no MoveMethod) walks first; `MoveMethod = "walk"` walks
    # first; `MoveMethod = "Cannon"` flies first. `HiveBees > n` has no cannon
    # in either branch, and its first is the one taken (see BRANCH).
    first_is_walk = method != "cannon"
    preamble = text[:condition.start()]
    opened = text.find("{", condition.start())
    if opened < 0:
        return None
    close = block_end(text, opened)
    if close < 0:
        return None
    first = text[opened + 1:close]
    after = text[close + 1:]
    split = ELSE.match(after.lstrip())
    if split is None:
        return preamble, first, "", after, first_is_walk
    opened2 = after.find("{", len(after) - len(after.lstrip()))
    close2 = block_end(after, opened2)
    if close2 < 0:
        return None
    second = after[opened2 + 1:close2]
    trailing = after[close2 + 1:]
    return preamble, first, second, trailing, first_is_walk


# A LEAN, IN NATRO'S OWN WORDS. Natro's walks home open by walking INTO a
# wall or a corner on purpose -- "walk back against wall", "move to corner",
# "ensure against vicious bee platform", "walk to edge of field" -- so that
# whatever the pattern left the character's position at, the route continues
# from a known point. Recorded as timed walks they reach the wall only from
# within the recorded distance of it. MEASURED 2026-09-23 (DESIGN 8co, 8cq):
# from Strawberry, three walks home with identical legs landed once and
# missed twice, and the frames put the difference in exactly this -- the
# rear-wall lean (12 tiles) fell short from a start deep in the field, the
# next leg did not clear the platform, and the long walk pushed into it. So
# a walk whose comment says it is a lean is marked, and the runner holds it
# until the flow says blocked (act/routes._lean). "align with SpawnLocation"
# and "back out of corner" are fixed offsets, not leans, and do not match.
LEAN_WORDS = re.compile(r"\bagainst\b|\bto (?:the )?(?:corner|edge|wall|ramp)\b",
                        re.IGNORECASE)

# The labels inside `switch HiveSlot { ... }`: `case 3:` and `default:`.
CASE_LABEL = re.compile(r"^\s*(?:case\s+(\d+)|(default))\s*:\s*$", re.IGNORECASE)
SWITCH = "switch HiveSlot"


def slot_switch(text: str):
    """Split `text` at its first `switch HiveSlot {...}`, or None if it has none.

    Returns `(before, op, after)` where `op` is

        {"op": "slot_switch", "cases": {"3": [...]}, "default": [...]}

    with every branch body transpiled by `steps_of`, so the runner can take
    the branch for the slot the account actually owns (act/routes).

    WHY BOTH BRANCHES ARE KEPT, AND WHY THIS REPLACED "TAKE THE DEFAULT".
    Ten of the seventeen walks home end like this:

        switch HiveSlot
            {
            case 3:
            nm_Walk(2.7, BackKey) ;center on hive pad 3

            default:
            nm_Walk(1.5, BackKey) ;walk backwards to avoid thicker hives
            nm_Walk(35, RightKey) ;walk to ramp
            nm_Walk(2.7, BackKey) ;center with hive pads
            }

    The first version of this transpiler resolved the switch to its `default`
    body on the reasoning that the ramp is "the same destination, a little
    further". It is not. `default` ends at the RAMP CORNER, and Natro then
    runs `nm_findHiveSlot()` -- hold left along the row until the hive's own
    prompt appears -- to get from the corner to the pad. `case 3` ends ON pad
    3 because the paths were recorded aligned with the default spawn. MEASURED
    2026-09-23 on this account, which owns slot 3, from the frames the runner
    saves per leg (var/routes/attempt-296, natro_home_spider): after leg 09
    the character stood on its own pad, the "Make Honey" prompt matched its
    template at 0.839 on the next frame, and the transpiled `default` legs
    then walked it 140 studs right to the ramp, where the prompt was gone.
    114 of the last 170 trips ended in a rejoin for that reason.

    So the branch is kept as data and the runner chooses -- `case` for a
    known slot that has one, `default` otherwise -- and the row search
    (act/hiverow) does what `nm_findHiveSlot` does after the general path.
    """
    at = text.find(SWITCH)
    if at < 0:
        return None
    opened = text.find("{", at)
    if opened < 0:
        return None
    depth, i = 0, opened
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        return None                          # unbalanced; leave it alone
    block = text[opened + 1:i]
    cases: dict[str, list[dict]] = {}
    default: list[dict] = []
    label: str | None = None
    body: list[str] = []

    def flush() -> None:
        if label is None:
            return
        steps, _credits = steps_of("\n".join(body))
        if label == "default":
            default.extend(steps)
        else:
            cases[label] = steps

    for line in block.splitlines():
        found = CASE_LABEL.match(line)
        if found:
            flush()
            label = found.group(1) or "default"
            body = []
        else:
            body.append(line)
    flush()
    op = {"op": "slot_switch", "cases": cases, "default": default}
    return text[:at], op, text[i + 1:]


def _flat(steps: list[dict]) -> list[dict]:
    """Every step, the branches of a slot switch opened out."""
    out: list[dict] = []
    for step in steps:
        out.append(step)
        if step.get("op") == "slot_switch":
            for body in list((step.get("cases") or {}).values()) + [step.get("default") or []]:
                out.extend(_flat(body or []))
    return out


def presses_e(steps: list[dict]) -> bool:
    """Does this route press the interact key, as a tap or a held key?

    A walking route must not: the journey refuses an `interact` whose panel
    does not name the place, and a `key_down` of `e` is the same press spelt
    differently (`send "{" SC_E " down}"` at the blue portal). Refused at
    transpile time rather than at the moment of pressing."""
    for step in _flat(steps):
        if step.get("op") == "interact":
            return True
        if step.get("op") in ("key_down", "key_up") and "e" in str(step.get("keys", "")):
            return True
    return False


# THE ONE PRESS OF E THIS TRANSPILER WILL EMIT, and what makes it different
# from every other one.
#
# Natro's walks home from Bamboo and the Blue Flower Field do not walk home.
# Both cross the map to a portal, press E, and finish with the SAME seven
# legs on the far side -- so the two files converge on one door, and the
# legs after it are a route from wherever that door leads. `presses_e`
# refused both files whole, which is why those two fields are the only ones
# with no walk home at all, and why every trip to either ends in a rejoin:
# "rejoining is slow and also it resets wealth clock which is so important".
# Bamboo is also this account's biggest quest (1,525,325 more pollen at
# attempt 335), so it is the field the bot most needs to leave properly.
#
# The press is emitted as `interact_when`, which READS the panel and presses
# only if it says what it should (act/routes). MEASURED 2026-09-23: the
# portal's panel says "Enter the Portal" -- read by the local model off the
# frames attempts 275, 276 and 277 each saved AT the portal, back when the
# press was silently dropped and the route walked past it. Five readable
# frames, three attempts, the same four words.
#
# The gate stays narrow on purpose:
#   * the file has to have a comment naming the portal (Natro's own
#     "; blue portal" section header), and
#   * the steps have to be exactly one `e` down and one `e` up, adjacent
#     bar a pause -- the shape both files have.
# Anything else falls through to `presses_e` and is refused as before, so a
# new path that presses E at something unknown does not inherit this.
PORTAL_COMMENT = re.compile(r"^\s*;.*\bportal\b", re.IGNORECASE | re.MULTILINE)
PORTAL_EXPECT = ("portal",)


def portal_press(steps: list[dict], text: str) -> list[dict]:
    """`steps` with the portal's E press turned into a verified one.

    Returns the list unchanged when this is not the shape described above,
    which leaves the route to be refused rather than guessed at."""
    if not PORTAL_COMMENT.search(text or ""):
        return steps
    downs = [i for i, step in enumerate(steps)
             if step.get("op") == "key_down" and step.get("keys") == "e"]
    ups = [i for i, step in enumerate(steps)
           if step.get("op") == "key_up" and step.get("keys") == "e"]
    if len(downs) != 1 or len(ups) != 1 or ups[0] < downs[0]:
        return steps
    between = steps[downs[0] + 1:ups[0]]
    if any(step.get("op") != "pause" for step in between):
        return steps
    return steps[:downs[0]] + [{
        "op": "interact_when",
        "expect": list(PORTAL_EXPECT),
        "why": "the blue portal home",
        "wait": PORTAL_WAIT_SECONDS,
    }] + steps[ups[0] + 1:]


# How long `interact_when` waits for the portal's panel; act/routes has the
# same number as its default and the reason for it.
PORTAL_WAIT_SECONDS = 6.0


# CALIBRATIONS OF NATRO'S NUMBERS, each one measured on this bot and kept
# here -- the generated YAML is regenerated and must not be hand-edited.
#
# Strawberry, "move forward past vicious bee platform" (wf-strawberry.ahk's
# nm_Walk(15, FwdKey), 60 studs). MEASURED 2026-09-24 over fourteen walks
# home (the strawberry-walk-home-diff workflow, re-checked by its judge):
# every one of the five that failed -- attempts 328, 331, 343, 347 and 349 --
# held this leg for 2.34-2.35 s, exactly its recorded length, and stopped
# with the giant strawberry's bottom edge at y 406-410 in the leg's frame;
# the four that landed dead centre stopped 2-3.5 studs further on (bottom
# 417-433), from a longer hold or an unread Haste. Stopping short puts the
# next leg, a 24-stud strafe, against the front of the slab, and the 380-stud
# walk that follows goes face-first into the strawberry or wide of the hive.
# One tile more (16 instead of 15) clears it with margin; ahead of the leg is
# open yellow path.
#
# NOT the Blender's "d100" (tried 2026-10-06 as 96, reverted): after the turn
# that follows it, "d" is forward and back, and the misses' leg-28 frames shift
# near and far alike (about -90 and -75 px against the one success,
# var/routes/attempt-663/-665/-667/-670): a camera ~4 degrees right of the
# success's, not a step sideways -- no distance here can mend it.
STEP_CALIBRATIONS = {
    # (file short name, the step before, the step): new studs
    ("strawberry", ("a", 72.0), ("w", 60.0)): 64.0,
}


# WHERE A FLIGHT LANDS SHORT ON THIS ACCOUNT, and the steps that finish it,
# appended to the cannon branch's route. MEASURED: Cactus's flight (gtf-cactus
# .ahk, "calibrated cannon path") came down on the grass strip at the foot of
# the field's front ledge on every flight whose frames were kept -- 2026-09-23
# (var/routes/attempt-283..285: "credited no field", "collected no pollen")
# and 2026-10-06 01:55 and 01:59 (attempt-664, the sprinkler refused "You must
# be standing in a field") -- with the field straight ahead past a ledge too
# tall to walk up. So a running jump: forward held, a jump, let go (about 20
# studs at base speed, into a field deeper than that).
LANDINGS = {
    ("gtf", "cactus"): ({"op": "key_down", "keys": "w"}, {"op": "pause", "seconds": 0.1},
                        {"op": "jump"}, {"op": "pause", "seconds": 0.6},
                        {"op": "key_up", "keys": "w"}),
}


# AND WHERE A WALK DOES, the steps appended to the walk's own route. MEASURED
# 2026-10-06 12:57 (run-685, var/routes/attempt-685/125749-natro_out_coconut-*): the
# bot's first Coconut walk (gtf-coconut.ahk, "path 230212") ended on the sand at the
# field's front edge with the field straight ahead, and the sprinkler was refused
# "You must be standing in a field" there and at every step back -- 0 pollen in
# 249 s. A shorter running jump than Cactus's (about 10 studs), so Natro's start
# walk across the field (24 studs right) still begins inside it.
WALK_LANDINGS = {
    ("gtf", "coconut"): ({"op": "key_down", "keys": "w"}, {"op": "pause", "seconds": 0.1},
                         {"op": "jump"}, {"op": "pause", "seconds": 0.3},
                         {"op": "key_up", "keys": "w"}),
}


# CHECKS A STEP ASKS FOR, by name (act/routes `checkpoints`), measured on this
# bot. (prefix, file short name, the step): check name.
#
# The walk out to Strawberry's 270-stud diagonal. MEASURED 2026-09-24 on
# every walk out of attempts 331-359: right after it, the share of yellow
# path under the character reads 0.70-0.94 on every walk that arrived and
# 0.00-0.01 on three that ended in the starter fields (attempts 346, 353,
# 359) -- the legs after it only carry a wide walk further off.
#
# The walk to the Treat Dispenser (DESIGN 8dr) opens with the same diagonal
# and crosses the Spider Field's corner on its 80-stud diagonal. MEASURED
# 2026-09-26 over all fourteen of its walks (var/routes/attempt-351..393, the
# same band and colour test): six reached the dispenser's prompt (351 twice,
# 359, 364, 385, 393) and eight did not. After the 270-stud diagonal the share
# reads 0.75-0.93 on the six and 0.00 on 392, standing on the grass by the
# Blue Flower Field; after the 80-stud one 0.58-0.91 on the six, and 0.13,
# 0.01, 0.07 and 0.00 on 379, 380, 381 and 384, out in the Spider Field.
#
# And the jump onto the ledge the dispenser stands on, which the other three
# misses (356, 357, 382) failed. Right after the `key_up` that ends it, the
# share of the slate stone of the building over the ledge (run_farm
# ROUTES_LEDGE_*) reads 0.69-0.79 on all six arrivals and 0.00-0.12 on all
# eight misses. The pollen counter on each miss's stopping frame reads
# 316-1,955 of 1.2-1.35 million, so the respawn home stays allowed (its 1%).
#
# The walk to the Blueberry Dispenser, at the end of its 46-stud diagonal into
# the Blue HQ: the share of the headquarters' floor (run_farm ROUTES_HQ_*)
# reads 0.47-0.93 on the ten of its twelve walks that stood by the dispenser
# and 0.01 on the two that met a Rhino Beetle on leg 03 (attempts 407, 408).
STEP_CHECKS = {
    ("gtc", "blueberrydis", ("wd", 46.0)): "inside_the_blue_hq",
    ("gtc", "treatdis", ("sa", 270.0)): "on_the_path",
    ("gtc", "treatdis", ("wd", 80.0)): "on_the_path",
    ("gtc", "treatdis", ("key_up", "w")): "atop_the_ledge",
    ("gtf", "strawberry", ("sa", 270.0)): "on_the_path",
    # The same first diagonal, on the Panda Bear's route (a DERIVED_ROUTES
    # entry, keyed ("derived", node)). MEASURED 2026-09-25 over all fourteen
    # saved treat-dispenser walks (var/routes/attempt-351..393, leg 03, the
    # run_farm on_the_path band and colour test): 0.75-0.93 on thirteen, and
    # 0.00 on attempt 392, whose leg-11 frame has it wedged against a wall.
    ("derived", "panda_bear", ("sa", 270.0)): "on_the_path",
    # The walk home from Mushroom, at the end of its 288-stud walk into the
    # hive face (DESIGN 8dx). MEASURED 2026-09-26 on all fourteen walks of its
    # present shape (attempts 366-449, the leg-08 frame, act/hive
    # .hive_bearing): the eight that landed face a honeycomb wall at 146,152-
    # 403,170 px of it, and the six that missed face the white fence short of
    # the hives at 8,972-71,934 px, the hive 337-659 px right of centre on
    # five of them. Its one leg left on this account's slot is 10.8 studs
    # back onto the pad, so a miss here goes straight to homing by sight
    # instead of that step and the row search (45 s of holding along a fence).
    ("wf", "mushroom", ("w", 288.0)): "at_the_hive_face",
}


def add_checks(prefix: str, short: str, steps: list[dict]) -> list[dict]:
    """`steps` with the STEP_CHECKS that apply, on the first matching step.

    A target is `(keys, studs)` for a walk, or `(op, keys)` -- a string where
    the studs would be -- for any other step, such as the `key_up` that ends
    a jump."""
    out = [dict(step) for step in steps]
    # EVERY ROUTE THAT OPENS WITH THE 270-STUD DIAGONAL, not only the three
    # in the table. MEASURED 2026-10-08: right after it, a start that went on
    # to land reads 0.86-0.91 of yellow path under the character on every
    # route that shares it (Pine Tree, Honey Bee, Panda, Treat, the boosters,
    # attempts 655-710), and the night's wide starts read 0.00-0.50 -- the
    # Bucko Bee walk among them, pressed into a wall at leg 03 and in the
    # Mushroom Field by leg 15 (attempt-774). Caught there, the walk ends at
    # once and its retry starts from a fresh respawn (run_farm before_route).
    for step in out[:4]:                      # w20, the hive offset, then the diagonal
        if (step.get("op") == "walk" and (step.get("keys"), float(step.get("studs", 0))) == ("sa", 270.0)
                and "check" not in step):
            step["check"] = "on_the_path"
            break
    for (pre, name, target), check in STEP_CHECKS.items():
        if pre != prefix or name != short:
            continue
        for step in out:
            if isinstance(target[1], str):
                if (step.get("op"), step.get("keys")) == target:
                    step["check"] = check
                    break
                continue
            if (step.get("op") == "walk"
                    and (step.get("keys"), float(step.get("studs", 0))) == target):
                step["check"] = check
                break
    return out


def calibrate(short: str, steps: list[dict]) -> list[dict]:
    """`steps` with this bot's measured corrections to Natro's distances.

    A correction applies only where the step AND the walk before it (pauses
    between skipped) match, so a change to Natro's file that moves or alters
    the leg leaves it alone rather than stretching some other walk."""
    out = [dict(step) for step in steps]
    for (name, before, target), studs in STEP_CALIBRATIONS.items():
        if name != short:
            continue
        for i in range(1, len(out)):
            j = i - 1
            while j > 0 and out[j].get("op") == "pause":
                j -= 1
            prev, step = out[j], out[i]
            if (prev.get("op") == "walk" and step.get("op") == "walk"
                    and (prev.get("keys"), float(prev.get("studs", 0))) == before
                    and (step.get("keys"), float(step.get("studs", 0))) == target):
                step["studs"] = float(studs)
                step["calibrated"] = f"Natro {target[1]:g} studs; see STEP_CALIBRATIONS"
    return out


def walks_in(steps: list[dict]) -> list[dict]:
    """Every walk these steps take, a slot switch standing for its `default`
    branch -- the general path, which is the one whose length is worth
    quoting as the route's."""
    out: list[dict] = []
    for step in steps:
        if step.get("op") == "walk":
            out.append(step)
        elif step.get("op") == "slot_switch":
            out.extend(walks_in(step.get("default") or []))
    return out


# LINES THAT MOVE THE CHARACTER IN A WAY `steps_of` STILL DOES NOT EXPRESS.
# Jumps, held keys, coasting and presses are expressed now (see steps_of);
# what is left is Natro's own movement helpers with computed arguments and
# its window-poking calls, none of which belong in a route.
UNEXPRESSED = re.compile(r"nm_Move\(|Gdip_|MouseMove|Click\b|nm_gotoCannon"
                         # a path's own helper, e.g. gtc-nightmm's `Jump([5, FwdKey])`:
                         # a jump, walks and a wait this does not express
                         r"|(?<![A-Za-z_.])Jump\(", re.IGNORECASE)


def unexpressed_lines(text: str) -> list[str]:
    """The lines of `text` that move the character in a way `steps_of` does
    not express. Empty means the transpile is faithful."""
    out: list[str] = []
    for line in text.splitlines():
        bare = line.split(";", 1)[0].strip()
        if not bare:
            continue
        if UNEXPRESSED.search(bare):
            out.append(bare)
    return out


def unknown_sends(text: str) -> list[str]:
    """The `send` keystrokes of `text` this transpiler has no op for. `steps_of`
    skips such a token, which is a different route, so a path with any is
    refused (see main)."""
    out: list[str] = []
    for line in text.splitlines():
        bare = line.split(";", 1)[0].strip()
        for part in statements(bare):
            if not part.lower().startswith("send"):
                continue
            for name, arg in send_tokens(part):
                if ops_of_token(name, arg) is None:
                    out.append(f"{name} {arg}".strip())
    return out


def walking_branch(text: str) -> str:
    """The part of a path that walks, without the cannon alternative.

    BOTH SHAPES APPEAR, and the condition says which branch is which:

        if (MoveMethod = "Cannon") { cannon } else { walking }   the fields
        if (MoveMethod = "walk")   { walking } else { cannon }   the bears, HQs
        if (HiveBees < 12)         { walking } else { yellow cannon }  walks home
        if (HiveBees > 25)         { walking } else { walking }   strawberry dis.

    In the last the first is taken: it is the one this account's hive (26
    bees) is for, and run_farm.ROUTES_PLACE_BEES keeps a smaller hive away.

    Anything after the whole if/else belongs to both and is kept -- several
    quest-giver paths finish with a jump and a run of walks that carry the
    character up onto the giver's platform whichever way it arrived. See
    block_end for why that part used to go missing.
    """
    parts = _branches(text)
    if parts is None:
        return text                    # no alternative: it all walks
    preamble, first, second, trailing, first_is_walk = parts
    if not second:
        return preamble + "\n" + (first if first_is_walk else "") + "\n" + trailing
    return preamble + "\n" + (first if first_is_walk else second) + "\n" + trailing


def cannon_branch(text: str) -> str:
    """The part of a path that flies, or "" when the path has no cannon branch.

    The mirror of `walking_branch`, kept separate so that function's contract
    ("the part that walks") stays exactly what it says. A `HiveBees` branch
    has no cannon flight in it -- its alternative is the yellow cannon, which
    this project does not board -- so it returns "".

    WHAT FOLLOWS THE IF/ELSE FLIES TOO -- Natro runs it after either branch.
    Until 2026-10-12 this returned the branch alone, so the flights of
    gtq-bucko (17 lines), gtc-megamm (12), gtb-blue (11) and gtq-polar (2)
    stopped where Natro's shared walk to the NPC or machine begins, and
    gtc-normalmm's lost its closing `Sleep 1000`.
    """
    parts = _branches(text)
    if parts is None:
        return ""
    preamble, first, second, trailing, first_is_walk = parts
    condition = BRANCH.search(text)
    if not (condition.group("method") or ""):
        return ""
    return preamble + "\n" + (second if first_is_walk else first) + "\n" + trailing


def send_tokens(line: str) -> list[tuple[str, str]]:
    """`send "{e up}{" RightKey " down}{" BackKey " down}"` ->
    [("e", "up"), ("RightKey", "down"), ("BackKey", "down")].

    AutoHotkey builds the string by concatenation, so the quotes and the
    spaces between the pieces are syntax, not content; dropping the quotes
    leaves one brace token per key action.
    """
    at = line.lower().find("send")
    body = line[at + 4:] if at >= 0 else line
    body = body.split(";", 1)[0]                 # a trailing comment
    sent = "".join(piece.group(1) if piece.group(1) is not None
                   else VARIABLE_MARK + piece.group(2) + VARIABLE_MARK
                   for piece in SEND_PIECE.finditer(body))
    return [(m.group(2), m.group(3)) for m in SEND_TOKEN.finditer(sent)
            if m.group(1) or not _natro_variable(m.group(2))]


def _natro_variable(name: str) -> bool:
    """One of Natro's key variables, which AutoHotkey does not know as a key
    name when it is written inside the quotes. See VARIABLE_MARK."""
    low = str(name or "").lower()
    return key_of(name) is not None or low in ("rotleft", "rotright") or low.startswith("sc_")


def ops_of_token(name: str, arg: str) -> list[dict] | None:
    """The runner's ops for one send token, or None for a token this
    transpiler does not know -- which skips the whole path rather than
    guessing at a keystroke."""
    low = name.lower()
    count = int(arg) if arg.isdigit() else 1
    if low in ("rotleft", "rotright"):
        return [{"op": "camera", "direction": "left" if low == "rotleft" else "right"}] * count
    if low == "sc_space":
        low = "space"                  # the scan-code spelling of the same key
    if low == "sc_e":
        low = "e"
    if low == "space":
        if arg == "down":
            return [{"op": "jump_hold"}]
        if arg == "up":
            return [{"op": "jump_release"}]
        return [{"op": "jump"}] * count
    if key_of(name) is not None:
        if arg == "down":
            return [{"op": "key_down", "keys": key_of(name)}]
        if arg == "up":
            return [{"op": "key_up", "keys": key_of(name)}]
        return None
    if low == "e":
        if arg == "down":
            return [{"op": "key_down", "keys": "e"}]
        if arg == "up":
            return [{"op": "key_up", "keys": "e"}]
        return [{"op": "interact"}]
    return None


def _merge_key_ops(steps: list[dict]) -> list[dict]:
    """`{RightKey down}{BackKey down}` is one press of two keys, not two."""
    out: list[dict] = []
    for step in steps:
        if (out and step["op"] in ("key_down", "key_up") and out[-1]["op"] == step["op"]):
            out[-1] = {"op": step["op"], "keys": out[-1]["keys"] + step["keys"]}
        else:
            out.append(dict(step))
    return out


def cannon_steps_of(text: str) -> tuple[list[dict], list[str], list[str]]:
    """The cannon branch as runner ops: `(steps, credits, unknown_tokens)`.

    `nm_gotocannon()` becomes one `cannon_approach` op -- Natro's hop-and-
    hold for the cannon lives in `act/routes`, where it can read the
    panel -- and every `send` token becomes the key action it names. A token
    this does not know is reported in `unknown` and the caller drops the
    path: a cannon sequence with a keystroke missing is not a shorter
    sequence, it is a different flight.
    """
    steps: list[dict] = []
    credits: list[str] = []
    unknown: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        found = CREDIT.search(line)
        if found and line.startswith(";"):
            credits.append(found.group(1).strip())
            continue
        if line.startswith(";"):
            continue
        low = line.lower()
        if "nm_gotoramp()" in low:
            steps.append({"op": "walk", "keys": "w",
                          "studs": round(RAMP_FORWARD_TILES * STUDS_PER_TILE, 2)})
            steps.append({"op": "hive_offset", "keys": "d",
                          "tiles_per_slot": RAMP_SLOT_TILES,
                          "tiles_offset": RAMP_SLOT_OFFSET,
                          "studs_per_tile": STUDS_PER_TILE})
            continue
        if "nm_gotocannon()" in low:
            steps.append({"op": "cannon_approach"})
            continue
        walk = WALK.search(line)
        if walk:
            tiles = float(walk.group(1))
            keys = "".join(key_of(k) or "" for k in (walk.group(2), walk.group(3)) if k)
            if tiles > 0 and keys:
                steps.append({"op": "walk", "keys": keys,
                              "studs": round(tiles * STUDS_PER_TILE, 2)})
            continue
        if low.startswith("send"):
            for name, arg in send_tokens(line):
                ops = ops_of_token(name, arg)
                if ops is None:
                    unknown.append(f"{name} {arg}".strip())
                else:
                    steps.extend(ops)
            continue
        nap = SLEEP.search(line)
        if nap:
            ms = int(nap.group(1) or nap.group(2) or nap.group(3))
            steps.append({"op": "pause", "seconds": round(ms / 1000.0, 3)})
            continue
    return _merge_key_ops(steps), credits, unknown


# WHICH OPS CAN BE WALKED BACKWARDS. A reversal is only honest for a route
# made of walks and the hive-slot offset: a jump cannot be un-jumped, a
# `pause` in a flight is not symmetric, and an `interact` is a press. Camera
# turns reverse as their opposite, so they are allowed.
REVERSIBLE_OPS = {"walk", "hive_offset", "camera"}
OPPOSITE = {"w": "s", "s": "w", "a": "d", "d": "a"}
# Above this the reversal is not offered. A recorded route leans into walls to
# square itself up (Natro's own comments say so), and a lean reverses into an
# overshoot that grows with the distance. 250 studs covers the things standing
# beside the hive -- the dispensers, the wreath -- which are the ones worth
# walking back from.
REVERSIBLE_MAX_STUDS = 250.0


def reversed_steps(steps: list[dict]) -> list[dict] | None:
    """The same route walked backwards, or None when it cannot be.

    MEASURED 2026-09-22 22:54 (attempt 253): the walk home from Dandelion
    failed, homing by sight walked the hive row, and the panel said "I am at
    the honey dispenser (98% sure)". Natro's route from the owned pad to that
    dispenser is four walks and a slot offset -- 187 studs left of the pad at
    slot 3 -- so walked backwards it is a measured way home from a place the
    game itself names. That is what this makes.
    """
    out: list[dict] = []
    for step in reversed(steps):
        op = step.get("op")
        if op not in REVERSIBLE_OPS:
            return None
        if op == "walk":
            keys = "".join(OPPOSITE[k] for k in str(step.get("keys", "")))
            if not keys:
                return None
            out.append({"op": "walk", "keys": keys, "studs": step["studs"]})
        elif op == "hive_offset":
            keys = "".join(OPPOSITE[k] for k in str(step.get("keys", "d")))
            out.append({**step, "keys": keys})
        else:                              # camera
            way = str(step.get("direction", ""))
            out.append({"op": "camera",
                        "direction": "left" if way == "right" else "right"})
    return out


def cannon_cost_studs(steps: list[dict]) -> float:
    """What the flight costs against a walk, in studs at Natro's base speed:
    its own walks, the approach, and every second waited on the way."""
    walks = sum(float(s.get("studs", 0.0)) for s in steps if s["op"] == "walk")
    waits = sum(float(s.get("seconds", 0.0)) for s in steps if s["op"] == "pause")
    return round(walks + CANNON_APPROACH_STUDS + waits * BASE_MOVESPEED, 1)


LOOP = re.compile(r"^\s*Loop\s+(\d+)\s*$", re.IGNORECASE | re.MULTILINE)


def expand_loops(text: str) -> str:
    """`Loop 15 { body }` becomes the body written out fifteen times.

    `wf-mountaintop.ahk` descends the mountain with `Loop 15 { nm_Walk(3,
    BackKey) nm_Walk(1, LeftKey) }`; a line-at-a-time reader saw the two
    walks once and the route came out fourteen steps short of the bottom.
    Found by the 2026-09-23 audit of statements that produce no op; the
    only loop in any path this project transpiles.
    """
    while True:
        m = LOOP.search(text)
        if m is None:
            return text
        opened = text.find("{", m.end())
        if opened < 0:
            return text
        close = block_end(text, opened)
        if close < 0:
            return text
        body = text[opened + 1:close]
        count = max(0, int(m.group(1)))
        text = text[:m.start()] + ("\n" + body + "\n") * count + text[close + 1:]


def statements(line: str) -> list[str]:
    """One AutoHotkey line as its statements, split on top-level commas.

    Natro writes several statements to a line -- `send("{" SC_Space " down}"),
    HyperSleep(300)` and `send("{" SC_Space " up}"), nm_Walk(6, FwdKey)` in
    `gtq-riley.ahk` -- and a line-at-a-time reader that stops at its first
    match dropped the rest. MEASURED 2026-09-23: Riley's route came out with
    every `{space up}` and none of the `{space down}` they belonged to. A
    comma inside parentheses or quotes is an argument, not a separator.
    """
    out: list[str] = []
    depth = 0
    quoted = False
    current: list[str] = []
    for c in line:
        if quoted:
            current.append(c)
            if c == '"':
                quoted = False
            continue
        if c == '"':
            quoted = True
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            out.append("".join(current).strip())
            current = []
            continue
        current.append(c)
    out.append("".join(current).strip())
    return [s for s in out if s]


def steps_of(text: str) -> tuple[list[dict], list[str]]:
    """Walks, camera turns and pauses, in order, plus the credits.

    A `switch HiveSlot` becomes one `slot_switch` step in place, with the
    text before and after it transpiled around it. See slot_switch.
    """
    text = expand_loops(text)
    split = slot_switch(text)
    if split is not None:
        before, branch, after = split
        head, credits = steps_of(before)
        tail, more = steps_of(after)
        return head + [branch] + tail, credits + more
    steps: list[dict] = []
    credits: list[str] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        found = CREDIT.search(raw)
        if found and raw.startswith(";"):
            credits.append(found.group(1).strip())
            continue
        if raw.startswith(";"):
            continue
        # a trailing comment is not a statement -- but it may say what the
        # statement is FOR, which is how a lean is recognised
        comment = ""
        head = raw.split(";", 1)[0]
        if ";" in raw and head.count('"') % 2 == 0:
            comment = raw.split(";", 1)[1].strip()
            raw = head.strip()
        try:
            for line in statements(raw):
                _emit_statement(line, steps, comment)
        except _CannonOnly:
            # Left behind on purpose: the cannon is the machinery that has
            # been failing, and the walking paths do not need it.
            return [], credits
    return _merge_key_ops(steps), credits


class _CannonOnly(Exception):
    """Raised by `_emit_statement` at `nm_gotocannon()`: this is not a walk."""


def _emit_statement(line: str, steps: list[dict], comment: str = "") -> None:
    """The runner's ops for one AutoHotkey statement, appended to `steps`.
    `comment` is the line's trailing comment; see LEAN_WORDS."""
    low = line.lower()
    if "nm_gotoramp()" in low:
        steps.append({"op": "walk", "keys": "w",
                      "studs": round(RAMP_FORWARD_TILES * STUDS_PER_TILE, 2)})
        # THE HIVE SLOT, AS A NUMBER. `hive_offset` is this project's own
        # op for it: the runner turns it into studs once it knows which
        # slot the account owns, and refuses rather than guessing when it
        # does not. See act/routes.
        steps.append({"op": "hive_offset", "keys": "d",
                      "tiles_per_slot": RAMP_SLOT_TILES,
                      "tiles_offset": RAMP_SLOT_OFFSET,
                      "studs_per_tile": STUDS_PER_TILE})
        return
    if "nm_gotocannon()" in low:
        # A walking path that boards the cannon is not a walking path; the
        # caller drops the whole route (see steps_of).
        raise _CannonOnly()
    slotted = HIVE_FLIPPED.search(line)
    if slotted:
        # `a*(c - slot) + d`  ->  slope -a, intercept a*c + d
        a = float(slotted.group(1))
        c = float(slotted.group(2))
        d = float((slotted.group(3) or "0").replace(" ", ""))
        steps.append({"op": "hive_offset",
                      "keys": key_of(slotted.group(4)),
                      "tiles_per_slot": round(-a, 4),
                      "tiles_offset": round(a * c + d, 4),
                      "studs_per_tile": STUDS_PER_TILE})
        return
    slotted = HIVE_PLAIN.search(line)
    if slotted:
        steps.append({"op": "hive_offset",
                      "keys": key_of(slotted.group(3)),
                      "tiles_per_slot": float(slotted.group(1)),
                      "tiles_offset": float(
                          (slotted.group(2) or "0").replace(" ", "")),
                      "studs_per_tile": STUDS_PER_TILE})
        return
    walk = WALK.search(line)
    if walk:
        tiles = float(walk.group(1))
        keys = "".join(key_of(k) or "" for k in (walk.group(2), walk.group(3)) if k)
        if tiles > 0 and keys:
            step = {"op": "walk", "keys": keys,
                    "studs": round(tiles * STUDS_PER_TILE, 2)}
            if comment and LEAN_WORDS.search(comment):
                step["lean"] = True
                step["why"] = comment[:60]
            steps.append(step)
        return
    rot = ROT.search(line)
    if rot:
        way = "left" if rot.group(1).lower() == "rotleft" else "right"
        for _ in range(int(rot.group(2))):
            steps.append({"op": "camera", "direction": way})
        return
    nap = SLEEP.search(line)
    if nap and "nm_Walk" not in line:
        ms = int(nap.group(1) or nap.group(2) or nap.group(3))
        steps.append({"op": "pause", "seconds": round(ms / 1000.0, 3)})
        return
    # A JUMP, A HELD KEY, A PRESS -- the same tokens the cannon emitter
    # reads, because the quest givers' paths finish with a jump up onto
    # a platform and the walks home from Pineapple and Stump hop a ledge.
    # Until 2026-09-23 these lines were skipped and the walks either
    # side of them emitted, which is a different route (DESIGN 8cd).
    if low.startswith("send"):
        for name, arg in send_tokens(line):
            ops = ops_of_token(name, arg)
            if ops is not None:
                steps.extend(ops)
        return
    coast = COAST.search(line)
    if coast:
        steps.append({"op": "coast",
                      "studs": round(float(coast.group(1)) * STUDS_PER_TILE, 2)})
        return


# The six quest givers. `black_bear` is already a landmark this project can
# recognise from its panel prompt (data/knowledge/landmarks.yaml); the rest are
# new nodes, which is all a graph needs.
GIVERS = {
    "black": "black_bear", "brown": "brown_bear", "bucko": "bucko_bee",
    "honey": "honey_bee", "polar": "polar_bear", "riley": "riley_bee",
}

# WHAT THE FINISHED-BUT-IDLE ENGINES NEED SOMEWHERE TO STAND. docs/GAPS.md #7:
# the wealth clock, the dispensers and the blender are working, tested code
# with no route to their door. These are Natro's `gtc-*` paths, named in this
# project's own vocabulary where it already has one.
COLLECTIBLES = {
    "clock": "wealth_clock", "honeydis": "honey_dispenser",
    "blueberrydis": "blueberry_dispenser",
    "strawberrydis": "strawberry_dispenser",
    "royaljellydis": "royal_jelly_dispenser",
    "treatdis": "treat_dispenser", "gluedis": "glue_dispenser",
    "coconutdis": "coconut_dispenser", "blender": "blender",
    "stockings": "stockings", "wreath": "honey_wreath",
    "samovar": "samovar", "WindShrine": "wind_shrine", "antpass": "ant_pass",
    # THE MEMORY MATCH MACHINES (the owner asked for Memory Match, 2026-09-28).
    # Natro's nm_MemoryMatch walks these (natro_macro.ahk
    # 12796-12830) and presses E at the machine. The BSS wiki: the Memory Match
    # in front of the Pro Shop (25,000 honey, 2 h), the Mega inside the Badge
    # Bearer's Guild (500,000 honey, 4 h), the Night near Bubble Bee Man in the
    # Bear Gate (5,000,000, 8 h, at night), the Extreme near the Pepper Patch
    # (25,000,000, 8 h). Winter's is Beesmas-only and left out.
    "normalmm": "memory_match", "megamm": "mega_memory_match",
    "nightmm": "night_memory_match", "extrememm": "extreme_memory_match",
    # THE STICKER STACK (the owner asked for it, 2026-10-07). Natro's nm_StickerStack walks this and presses
    # E at the podium (natro_macro.ahk 13272-13400).
    "stickerstack": "sticker_stack",
    # X3/X4 (act/errands HONEYSTORM_LIVE, STICKER_PRINTER_LIVE: LOOK-ONLY, not
    # in run_farm's PLACE_ROUTES, so nothing walks them yet). The Honeystorm
    # pad "between the Clover Field and Blue HQ" and the Sticker Printer "to
    # the right of the Instant Converter next to the Mountain Top Field" (wiki
    # Honeystorm, Sticker_Printer, read through api.php 2026-10-27).
    "honeystorm": "honeystorm", "stickerPrinter": "sticker_printer",
}

# THE THREE FIELD BOOSTERS, NOT THE THREE HEADQUARTERS. Natro's own path
# table calls `gtb` "go to (field) booster" (natro_macro.ahk:310), presses E at
# the end of each in nm_toBooster (13599-13616) and names the third "Mountain
# Top Booster". These were emitted as `blue_hq`, `red_hq` and `mountain_hq`,
# so the recon queued three shops it would only read, and the boosters had no
# route at all. The node names are the route graph's own (data/world/
# paths.yaml: blue_field_booster, red_field_booster, white_field_booster for
# the one BeeTuxMacro reached by the cannon), and act/errands knows them.
BOOSTERS = {"blue": "blue_field_booster", "red": "red_field_booster",
            "mountain": "white_field_booster"}

# ROUTES CUT FROM ANOTHER PATH, for a giver Natro has no path to. Each is the
# first steps of one Natro path, matched step for step, then a few steps
# measured on this bot. If Natro's file stops walking those steps the route
# is skipped and said to be, rather than cut somewhere else.
#
# THE PANDA BEAR (DESIGN 8dm). Natro has no path, quest check or bitmap for
# him: 'Panda' appears only as a movespeed buff (lib/Walk.ahk:28 and 108,
# submacros/StatMonitor.ahk:447). gtc-treatdis.ahk walks past him. Its lines
# 3-8 are the ramp, 67.5 tiles back-left, RotRight 4, 30 tiles forward, 20
# tiles forward-right, RotRight 2 -- the eleven steps below. MEASURED
# 2026-09-25 on the fourteen saved frames of that stop
# (var/routes/attempt-351..393, *-natro_out_treat_dispenser-11-camera-right):
# six show the Bamboo Field ahead, the Gumdrop Shop on the right and the Panda
# on his tall yellow block above it (attempts 351 twice, 356, 357, 359, 385);
# three stand a few studs on, at the field's front edge (364, 382, 393); three
# ran on into the field (379, 380, 384); two are wedged against a wall (381,
# 392). In the first six his legs are 29-38 degrees right of the camera and
# the '!' over him 35-42; the shop's body begins at 37-45 and its middle is
# at 42-46 (pinhole: Roblox's default 70-degree vertical field of view, the
# investigation's measured 22.7-degree tilt; the salvage investigation read
# him at 40-45). One camera tap is 45 degrees (act/bearvisit
# .TAPS_PER_FULL_TURN, measured by act/homing), and the nearest heading to
# him that the keys and taps can make. So one more RotRight faces the shop
# standing in front of his block, with him 3-16 degrees to the left: the
# search's forward hold is expected to meet the shop, and its left hold
# slides toward him. No timed walk after the turn: the 65-70 studs to the
# block rest on a field of view nobody has measured in this game, so the last
# stretch is run_farm's walk-and-watch prompt search (`hunt_for_prompt`),
# which stops on a panel, reads it, and walks on past one that does not name
# him.
DERIVED_ROUTES = {
    # THE BROWN BEAR, from the Wealth Clock's walk. Natro's own gtq-brown.ahk
    # walk landed 1 of its 49 judged runs here (var/skill_stats.json, 2026-09-27:
    # the last ten all "elsewhere", ending on the grass by a picket fence and a
    # wooden ladder, var/routes/attempt-458..469 leg 11), while the Wealth
    # Clock's walk has landed at the clock every hour today. And that walk goes
    # past him: MEASURED 2026-09-27 13:03:33 (var/routes/attempt-497,
    # natro_out_wealth_clock-24-walk-w20), after its 24th step the frame shows
    # the Brown Bear on the left and the "Top Brown Bear Helpers" leaderboard
    # on the right -- the same board as beside him on the one visit that read
    # "Talk to Brown Bear" (var/bears/brown_bear-192455.jpg); the wiki puts
    # him "next to the Wealth Clock and the Top Brown Bear Helpers leaderboard".
    # So his walk is the clock's first 24 steps, and the last few studs are
    # run_farm's prompt search (`hunt_for_prompt`), as the Panda Bear's are.
    "brown_bear": {
        "path": ("gtc", "clock"),
        "through": ("walk w 20", "hive_offset d", "walk sa 179", "walk a 112",
                    "walk s 40", "walk a 24", "walk sa 48", "pause", "walk d 6",
                    "walk w 48.8", "walk a 56", "walk ds 6", "walk s 60",
                    "walk a 30", "pause", "walk d 7", "walk w 16", "walk a 90",
                    "camera left", "camera left", "walk w 160", "walk s 4",
                    "walk d 80", "walk w 20"),
        "then": (),
        "why": ("cut after the Wealth Clock walk's 24th step, where the saved "
                "frames stand beside the Brown Bear and his leaderboard; see "
                "transpile_natro.DERIVED_ROUTES"),
    },
    # THE CLOVER FIELD, from the same walk, sooner. Natro's gtf-clover.ahk walk
    # ran its 52.5-tile left leg into the log fence by the Dandelion Field
    # twice running (2026-09-27 13:17 and 13:23, attempt 499: "a for 210 studs:
    # pushed against something for 2.5 of 7.5s", then 231 s and 22 passes
    # gathered 0 pollen), with a quest wanting 6,221 more from Clover. The
    # clock's walk crosses the field: MEASURED 13:03:23 (attempt 497,
    # natro_out_wealth_clock-18-walk-a90) the frame after its 18th step stands
    # in its red, white and blue flowers, and at 13:03:30 the reward feed put
    # the character "in the clover field" (a Rhino Beetle defeated "in the
    # clover"). Natro's own start for Clover is 0 studs and 0 turns, and the
    # clock's first 18 steps turn no camera, so the pattern starts as Natro's
    # would, from where this ends.
    "clover": {
        "path": ("gtc", "clock"),
        "through": ("walk w 20", "hive_offset d", "walk sa 179", "walk a 112",
                    "walk s 40", "walk a 24", "walk sa 48", "pause", "walk d 6",
                    "walk w 48.8", "walk a 56", "walk ds 6", "walk s 60",
                    "walk a 30", "pause", "walk d 7", "walk w 16", "walk a 90"),
        "then": (),
        "why": ("cut after the Wealth Clock walk's 18th step, which stands in the "
                "Clover Field (frame and reward feed); see "
                "transpile_natro.DERIVED_ROUTES"),
    },
    # MEASURED on the survey of 2026-10-06 02:43 (run_farm MOTHER_SURVEY_SHOP,
    # var/shoplook/20261006-0243*-mother_bear_survey-*.jpg): from the end of
    # the Sunflower walk, two camera taps right put her straight ahead under
    # the red-and-white awning, and after five (wd 6, w 6) pairs the character
    # stands on her stage with "Talk to Mother Bear" up -- read on legs 12, 13
    # and 14, gone by 15. The route stops on leg 13, the middle of that window.
    "mother_bear": {
        "path": ("gtf", "sunflower"),
        "through": ("walk w 20", "hive_offset d", "walk s 36", "walk sd 27",
                    "camera right", "camera right", "walk d 116"),
        "then": (({"op": "camera", "direction": "right"},) * 2
                 + ({"op": "walk", "keys": "wd", "studs": 6.0},
                    {"op": "walk", "keys": "w", "studs": 6.0}) * 5
                 + ({"op": "walk", "keys": "wd", "studs": 6.0},)),
        "why": ("the whole Sunflower walk, then the survey's two taps right and "
                "its first 11 legs, to the middle of the three that read her "
                "prompt; see transpile_natro.DERIVED_ROUTES"),
    },
    # THE SPIRIT BEAR, from the Coconut walk. MEASURED 2026-10-06 (var/routes/
    # attempt-685/125749-natro_out_coconut-35-coast-72.jpg, var/shoplook/20261006-
    # 134729-spirit_bear_survey_coconut-arrived.jpg): during and just after the
    # walk's 72-stud forward coast she stands on a green ledge ahead and to the
    # right, a grey bear with a green-tipped staff, her orange "!" in view. Cut
    # there; the giver search's first hold walks toward a "!" on screen
    # (run_farm, act/beacon), the rest of it spirals and holds.
    "spirit_bear": {
        "path": ("gtf", "coconut"),
        "through": ("walk w 20", "hive_offset d", "jump_hold", "key_down d", "pause",
                    "jump_release", "coast 8", "key_down w", "coast 7.2", "key_up w",
                    "coast 120", "key_up d", "jump_hold", "pause", "jump_release",
                    "walk d 16", "walk w 20", "walk d 12", "jump_hold", "pause",
                    "jump_release", "walk w 24", "walk aw 8", "walk w 32", "key_down wd",
                    "coast 44", "jump_hold", "key_up d", "pause", "jump_release", "pause",
                    "jump_hold", "pause", "jump_release", "coast 72", "key_up w"),
        "then": (),
        "why": ("cut after its 72-stud forward coast, with her quest marker on the "
                "ledge ahead and to the right; see transpile_natro.DERIVED_ROUTES"),
    },
    "panda_bear": {
        "path": ("gtc", "treatdis"),
        "through": ("walk w 20", "hive_offset d", "walk sa 270",
                    "camera right", "camera right", "camera right", "camera right",
                    "walk w 120", "walk wd 80", "camera right", "camera right"),
        "then": ({"op": "camera", "direction": "right"},),
        "why": ("cut after its 80-stud diagonal and the two camera turns "
                "after it, then one more measured turn right, toward the "
                "Gumdrop Shop in front of the Panda Bear's block; see "
                "transpile_natro.DERIVED_ROUTES"),
    },
}


def step_signature(step: dict) -> str:
    """`walk sa 270`, `camera right`, `hive_offset d`: what a step does, for
    matching a derived route's cut against the path it is cut from."""
    op = str(step.get("op", ""))
    what = str(step.get("keys", step.get("direction", "")))
    studs = step.get("studs")
    return " ".join(p for p in (op, what, f"{float(studs):g}" if studs else "") if p)


def derived_steps(steps: list[dict], through, then) -> list[dict] | None:
    """The first steps of `steps` when they are exactly `through`, then
    `then`; None when the path no longer starts that way."""
    through = list(through)
    if [step_signature(s) for s in steps[:len(through)]] != through:
        return None
    return [dict(s) for s in steps[:len(through)]] + [dict(s) for s in then]

# Natro's file names to this project's node names (data/knowledge/fields.yaml).
FIELDS = {
    "bamboo": "bamboo", "blueflower": "blue_flower", "cactus": "cactus",
    "clover": "clover", "coconut": "coconut", "dandelion": "dandelion",
    "mountaintop": "mountain_top", "mushroom": "mushroom", "pepper": "pepper",
    "pineapple": "pineapple", "pinetree": "pine_tree", "pumpkin": "pumpkin",
    "rose": "rose_field", "spider": "spider", "strawberry": "strawberry",
    "stump": "stump", "sunflower": "sunflower",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", help="Natro Macro's paths/ directory")
    ap.add_argument("-o", "--out", default="data/world/natro_paths.yaml")
    args = ap.parse_args()

    folder = pathlib.Path(args.paths)
    edges = []
    skipped = []

    jobs = [(short, node, prefix, start, end, kind)
            for short, node in sorted(FIELDS.items())
            for prefix, start, end, kind in (("gtf", "hive", node, "out"),
                                             ("wf", node, "hive", "home"))]
    # THE BEARS AND THE BOOSTERS. docs/GAPS.md #6 is a finished quest sitting
    # unclaimed because the bot cannot walk to a bear; the `gtb` paths were
    # taken for the shops (#3) and are the field boosters (see BOOSTERS).
    # There is no walk BACK from either in Natro, so these are one-way; the
    # respawn is the way back, as Natro's nm_Reset is.
    jobs += [(short, node, "gtq", "hive", node, "out")
             for short, node in sorted(GIVERS.items())]
    jobs += [(short, node, "gtb", "hive", node, "out")
             for short, node in sorted(BOOSTERS.items())]
    jobs += [(short, node, "gtc", "hive", node, "out")
             for short, node in sorted(COLLECTIBLES.items())]

    for short, node, prefix, start, end, kind in jobs:
        if True:
            path = folder / f"{prefix}-{short}.ahk"
            if not path.exists():
                skipped.append(f"{prefix}-{short}: no such file")
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            # EVERY "GO TO" PATH HAS THE CHOICE; only the walks BACK do not.
            # This used to test `prefix == "gtf"`, so the quest givers and the
            # shops were handed their raw text -- cannon branch and all -- and
            # were dropped as "cannon only" when `steps_of` reached
            # `nm_gotocannon()`. Five of the nine were lost that way.
            body = walking_branch(text)
            if LEFTOVER.search(body):
                skipped.append(f"{prefix}-{short}: branches on a condition this "
                               f"transpiler does not know — refused rather than "
                               f"walking both branches (see LEFTOVER)")
                continue
            # ANY PATH WITH A LINE THIS DOES NOT EXPRESS IS REFUSED, not only
            # the walks home: gtc-nightmm's moon jumps (its own `Jump()`)
            # were dropped and the walks either side emitted, 2026-09-28.
            if prefix != "wf":
                missing = unexpressed_lines(body) + [
                    f"send {t}" for t in unknown_sends(body)]
                if missing:
                    skipped.append(f"{prefix}-{short}: {len(missing)} line(s) this "
                                   f"transpiler does not express, e.g. "
                                   f"{missing[0]!r} — refused rather than emitted "
                                   f"without them")
                    continue
            if prefix == "wf":
                # A WALK HOME IS REFUSED RATHER THAN APPROXIMATED. Seven of
                # Natro's seventeen glide off a ledge, hold keys through a
                # jump, or press E at the blue portal, none of which this
                # emits; the walks either side of a dropped jump are a route
                # off the wrong side of the ledge. With no route the journey
                # goes straight to its closers, which is cheaper than
                # walking a wrong one first. See UNEXPRESSED.
                missing = unexpressed_lines(body)
                # THE PORTAL FIRST, so a press this transpiler can express
                # is not counted as one it cannot. See portal_press.
                if presses_e(portal_press(steps_of(body)[0], body)):
                    missing = ["a press of E at something unnamed"] + missing
                if missing:
                    skipped.append(f"{prefix}-{short}: {len(missing)} line(s) this "
                                   f"transpiler does not express, e.g. "
                                   f"{missing[0]!r} — refused rather than emitted "
                                   f"with the jump missing")
                    continue
            steps, credits = steps_of(body)
            if prefix == "wf":
                steps = calibrate(short, portal_press(steps, body))
            elif prefix == "gtc":
                steps = calibrate(short, steps)
            steps = steps + [dict(st) for st in WALK_LANDINGS.get((prefix, short), ())]
            steps = add_checks(prefix, short, steps)
            walks = walks_in(steps)
            if not walks:
                skipped.append(f"{prefix}-{short}: no walking path (cannon only)")
                continue
            # `from`/`to`, which is what `nav.router.load` reads. They are
            # the graph's own words for it and the generated file has to speak
            # the same schema as data/world/paths.yaml.
            walk_studs = round(sum(s["studs"] for s in walks), 1)
            # WHICH BRANCH, when the path branches on a big hive (BRANCH).
            bigger = BIG_HIVE.search(text)
            # A GIVER WHOSE WALK IS CUT FROM ANOTHER PATH (DERIVED_ROUTES) keeps
            # this file's flight, not its walk.
            replaced = (kind == "out" and prefix in ("gtq", "gtf")
                        and node in DERIVED_ROUTES)
            if replaced:
                skipped.append(f"{prefix}-{short}: its walk is replaced by the "
                               f"derived natro_out_{node} (DERIVED_ROUTES); its flight is kept")
            walk_edge = {
                "name": f"natro_{kind}_{node}",
                "from": start,
                "to": end,
                "studs": walk_studs,
                "verified": False,
                "source": f"NatroMacro paths/{path.name}"
                          + (f" (its HiveBees {bigger.group(1)} {bigger.group(2)} branch)"
                             if bigger else ""),
                "credits": credits,
                "steps": steps,
            }
            if not replaced:
                edges.append(walk_edge)
            # THE WAY BACK FROM A PLACE THE PANEL NAMES. Only for the
            # one-way routes (the bears, shops and collectibles have no `wf`
            # path) and only when every op reverses. See reversed_steps.
            if (not replaced and kind == "out" and prefix != "gtf"
                    and walk_studs <= REVERSIBLE_MAX_STUDS):
                back = reversed_steps(steps)
                if back is not None:
                    edges.append({
                        "name": f"natro_back_{node}",
                        "from": end,
                        "to": start,
                        "studs": walk_studs,
                        "verified": False,
                        "source": f"NatroMacro paths/{path.name}, walked backwards",
                        "credits": credits,
                        "steps": back,
                    })

            # THE CANNON, for the fields far enough to fly to (see
            # CANNON_FROM_WALK_STUDS), AND FOR EVERY ERRAND NATRO FLIES TO.
            # Only the fields had it, so the bears, dispensers and boosters
            # were always walked, and MEASURED in var/skill_stats.json on
            # 2026-09-27 those walks arrive least of anything: the Brown Bear
            # 1 of 49, the Blueberry Dispenser 0 of its last 10, the Treat
            # Dispenser 2 of its last 10, the Wealth Clock 2 of 4 -- while the
            # Pine Tree flight lands 9 of 10. Natro's own default for all of
            # them is the cannon (`MoveMethod`). The flight joins the walk as
            # a second route to the same place, and `choose_out` picks
            # between them by their measured landings, as it does for a field.
            errand = prefix in ("gtq", "gtc", "gtb")
            if (prefix == "gtf" and walk_studs >= CANNON_FROM_WALK_STUDS) or errand:
                flight = cannon_branch(text)
                if not flight.strip():
                    if not errand:      # most errands have no flight at all
                        skipped.append(f"{prefix}-{short}: far, but Natro has no cannon branch")
                    continue
                fsteps, fcredits, unknown = cannon_steps_of(flight)
                if unknown:
                    skipped.append(f"{prefix}-{short}: cannon branch sends "
                                   f"{sorted(set(unknown))}, which this transpiler "
                                   f"does not know")
                    continue
                if not any(st["op"] == "cannon_approach" for st in fsteps):
                    skipped.append(f"{prefix}-{short}: cannon branch never goes to the cannon")
                    continue
                fsteps = fsteps + [dict(st) for st in LANDINGS.get((prefix, short), ())]
                edges.append({
                    "name": f"natro_out_{node}_via_red_cannon",
                    "from": start,
                    "to": end,
                    "via": "red_cannon",
                    "studs": cannon_cost_studs(fsteps),
                    "walk_studs": walk_studs,
                    "verified": False,
                    "source": f"NatroMacro paths/{path.name} (cannon branch)",
                    "credits": fcredits or credits,
                    "steps": fsteps,
                })

    # THE DERIVED ROUTES, last, so a regeneration adds them after everything
    # Natro paths directly. One way, like the other givers': the way back is
    # the respawn the errand chain already takes. See DERIVED_ROUTES.
    for node, cut in DERIVED_ROUTES.items():
        prefix, short = cut["path"]
        path = folder / f"{prefix}-{short}.ahk"
        if not path.exists():
            skipped.append(f"derived {node}: no {path.name} to cut it from")
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        source, credits = steps_of(walking_branch(text))
        steps = derived_steps(source, cut["through"], cut["then"])
        if steps is None:
            skipped.append(f"derived {node}: {path.name} no longer starts with "
                           f"the {len(cut['through'])} measured steps — not cut")
            continue
        steps = add_checks("derived", node, steps)
        edges.append({
            "name": f"natro_out_{node}",
            "from": "hive",
            "to": node,
            "studs": round(sum(s["studs"] for s in walks_in(steps)), 1),
            "verified": False,
            "source": f"NatroMacro paths/{path.name}, {cut['why']}",
            "credits": credits,
            "steps": steps,
        })

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Routes transpiled from Natro Macro's own field paths.",
        "#",
        "# GENERATED by scripts/transpile_natro.py -- do not hand-edit; edit the",
        "# transpiler, which explains what is taken and what is left behind.",
        "#",
        "# SOURCE: NatroTeam/NatroMacro, paths/*.ahk, licensed GPLv3.",
        "# Running and deriving from it privately carries no obligation, because",
        "# copyleft attaches to DISTRIBUTION -- but publishing Hivemind with these",
        "# paths in it would mean publishing Hivemind under the GPL too. Each path",
        "# carries its own authors' credits, as Natro records them.",
        "#",
        "# The WALKING branch of every path is here. The CANNON branch is here too,",
        "# as `natro_cannon_<field>` with `via: red_cannon`, for the fields whose",
        "# walk is CANNON_FROM_WALK_STUDS or longer (the owner, 2026-09-22: use",
        "# the cannon for far places). Its `studs` is a COST, not a",
        "# distance: the flight's own walks, the approach, and every wait at",
        "# Natro's base speed, so the router weighs it against the walk.",
        "#",
        "# `nm_Walk(n, ...)` is n TILES and a tile is 4 studs (lib/Walk.ahk:",
        '# "4 studs in a tile"), so every distance here is studs.',
        "#",
        "# A `slot_switch` step is Natro's `switch HiveSlot`: `cases` keyed by",
        "# slot number and a `default`. The runner takes the case for the slot",
        "# the account owns and `default` otherwise (act/routes). The walks home",
        "# end in one: `case 3` stops on pad 3, `default` walks to the ramp for",
        "# the row search (act/hiverow, Natro's nm_findHiveSlot). Walks home",
        "# with a jump, a glide or a portal press are NOT here -- see the",
        "# transpiler's `unexpressed_lines` -- because a route with its jump",
        "# left out is a different route, not a shorter one.",
        "# NO `base_speed` HERE ON PURPOSE. This file is loaded ALONGSIDE",
        "# data/world/paths.yaml and `nav.router.load` takes the last one it",
        "# reads, so declaring one would silently redefine the graph's own.",
        "# Natro's `base_movespeed` default is 28, which is what this project's",
        "# `move.walkspeed` is set to anyway.",
        "schema: 1",
        "edges:",
    ]
    import yaml
    body = yaml.safe_dump({"edges": edges}, sort_keys=False,
                          default_flow_style=False, width=100)
    # drop the top-level key yaml adds; the header already opened `edges:`
    body = body.split("edges:\n", 1)[1]
    out.write_text("\n".join(lines) + "\n" + body)

    print(f"{len(edges)} route(s) -> {out}")
    for edge in edges:
        walks = sum(1 for s in edge["steps"] if s["op"] == "walk")
        slot = any(s["op"] == "hive_offset" for s in edge["steps"])
        print(f"  {edge['name']:32s} {edge['studs']:7.1f} studs, {walks:2d} walks"
              + ("  (needs the hive slot)" if slot else ""))
    for note in skipped:
        print(f"  skipped {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

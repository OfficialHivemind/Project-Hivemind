"""R4 (docs/pending/brain-backlog.md W3/R4; docs/pending/brain-research-4.md
(b).4): end a gather where its `natro_home_<field>` route assumes it starts,
instead of discovering the gap only after the route's first long leg hits a
wall (backlog W3, MEASURED 2026-10-12: "natro_home_cactus: w for 360 studs:
pushed against something for 10.6 of 10.8s").

Classic macros beat exactly this without vision, by walking into a field
wall/corner on a fixed schedule so position resets no matter where the gather
actually drifted to:

  - A corner pattern can hold a key a little PAST the recorded distance every
    loop, so drift cannot accumulate across loops.
  - Natro gathers each field around a sprinkler placed at a fixed,
    field-relative spot (`FieldDefault[field]["sprinkler"]`, e.g. "Upper
    Left", "Lower Right" -- Natro Macro submacros/natro_macro.ahk:1607
    Mushroom, 1727 Cactus, 1772 Rose), and its OWN transpiled Mushroom home
    route proves the idea: it walks forward, then LEANS into that corner --
    data/world/natro_paths.yaml:1102-1106, natro_home_mushroom step 2, "a
    108.0 lean: true why: walk to corner near fence".

Our gather does not reproduce Natro's sprinkler walk, so the character can
end a gather anywhere in the field. Replicating that walk is the expensive
fix; the cheap one taken here is to replay each field's OWN recorded early
leg(s) of `natro_home_<field>` -- already Natro-sourced, already in
data/world/natro_paths.yaml -- as LEANS (hold until the flow says blocked,
`act.routes.RouteRunner._lean`) instead of blind timed walks, right before
the real route runs. A lean that meets no wall within its cap just walks the
recorded distance, same as a plain walk -- so a field with no wall there is
no worse off than today.

ponytail: the direction for each field is read off Natro's own data, not
derived from FieldDefault's sprinkler/camera fields (Rose's camera turns 4x
during gathering, which would need simulating to trust a fresh direction
guess). Cactus has no clear single corner (sprinkler "Center") and is the
one of the three to watch most closely; a miss-rate check after both A/B
sides have run is the upgrade path if it does not help.
"""
from __future__ import annotations

import time

from ..nav.router import Router, Routine

# "ab" = on in even hours, so the landing rate can be compared against odd
# hours -- the same A/B style as act.routes.HOME_UNSTICK. "on"/"off" pin it.
HOME_ALIGN = "ab"

# Per walk home: how many of its first legs become leans. The aligned walk
# is a COPY of the whole route with those legs leaned (not an extra walk
# before it, which would walk them twice), registered as
# `<route>_aligned`: still `natro_home_*`, so W3's unstick applies, and a
# skill row of its own (brain/skills.route_kind -> "<field>_aligned"), so
# the A/B landing rates come apart in the ledger by themselves.
# natro_paths.yaml, read 2026-10-12: cactus s 32, as 40; mushroom w 54,
# a 108 (already a lean, "walk to corner near fence"); rose w 48, a 80.
ALIGN_FIRST: dict[str, int] = {
    "natro_home_cactus": 2,
    "natro_home_mushroom": 2,
    "natro_home_rose_field": 2,
    # PINE TREE (research 2026-10-21): all 28 walks home that missed in runs
    # 1100-1165 were this route (20 "never saw the hive's yellow wall"), its
    # `d 300` starting from wherever the gather drifted and stopping short of
    # the corner rock; natro_paths.yaml: w 124, d 300. Leaned, both meet the
    # field's edge and that rock wherever the gather ended.
    "natro_home_pine_tree": 2,
}


# PROMOTED OUT OF THE A/B: these walks home lean in every hour. PINE TREE
# (A32, docs/pending/pinetree.md), MEASURED 2026-10-27 on runs 739-1259:
# the step frame where natro_home_pine_tree's d300 ends shows the corner rock
# (grey filling the right half) in 430 walks, 30 missed (7%); in the other
# 19 it ends on open floor along the blue wall or on another edge, 17 missed
# (89%) -- the timed d300 walked from wherever the gather drifted, or shrunk
# by a buff factor. A lean holds until blocked, so it ends at the rock from
# any start: all 7 leaned walks that ran the route (even hours, runs
# 1173-1204) "reached the wall" at 8.9-10.2 s and landed (an 8th, run-1167
# 22:41, was cut by the screen going off, not the walk); the plain ones from
# then on landed 12 of 15. HOME_ALIGN = "off" still turns this off.
# ponytail: 7 leaned walks; drop the route from here if leaned misses show up.
ALIGN_ALWAYS = frozenset({"natro_home_pine_tree"})


def align_on() -> bool:
    """Is the A/B switch on right now? See HOME_ALIGN."""
    if HOME_ALIGN == "ab":
        return time.localtime().tm_hour % 2 == 0
    return HOME_ALIGN == "on"


def aligned_steps(steps: list[dict], first: int) -> list[dict]:
    """`steps` with the walks among the first `first` steps made leans."""
    return [dict(s, lean=True) if i < first and s.get("op") == "walk" else s
            for i, s in enumerate(steps)]


def register(router: Router) -> None:
    """Add `<route>_aligned` for every route in ALIGN_FIRST the router has."""
    for edge in list(router.edges):
        first = ALIGN_FIRST.get(edge.name)
        if first:
            name = f"{edge.name}_aligned"
            router.routines[name] = Routine(name=name, steps=aligned_steps(edge.steps, first),
                                            studs=edge.studs, verified=False)


def swap(routes: list[str], router: Router) -> list[str]:
    """`routes` with each aligned walk home swapped in, when the switch is on
    (always for ALIGN_ALWAYS, unless HOME_ALIGN is "off": still the kill switch)."""
    on, always = align_on(), HOME_ALIGN != "off"
    return [f"{r}_aligned" if (on or (always and r in ALIGN_ALWAYS))
            and f"{r}_aligned" in router.routines
            else r for r in routes]

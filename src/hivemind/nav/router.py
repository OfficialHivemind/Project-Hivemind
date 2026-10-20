"""Finding a way from one place to another.

The graph is built from `data/world/paths.yaml`, which is transpiled from real
recorded walks rather than invented from coordinates. Each edge carries a
distance in studs and a list of steps the walker can execute.

Two properties that are easy to get wrong and matter a lot here.

**The graph is DIRECTED.** `from_hive_to_rose_field` does not imply that walking
it backwards gets you home: Bee Swarm's mountain has one-way drops, and the
recorded return routes are genuinely different paths with different lengths.
Treating recorded routes as bidirectional would send the character off a ledge
and call it a shortcut. Reversal is only ever available when a return route was
actually recorded.

**A missing route is reported, not improvised.** `route()` returns None when no
path exists rather than falling back to "walk in a straight line", because a
straight line through a mountain is how a bot ends up stuck against a rock for
eight hours. The caller then decides: explore, use a different goal, or ask.

Edge lengths are approximate (they are someone else's recordings) and that is
tolerable because execution is closed-loop -- the walker measures real
displacement, so a wrong edge length costs a slightly wrong ESTIMATE, not a
wrong position. As the bot walks an edge it records the true distance, and
`observe_edge` promotes it to verified.
"""
from __future__ import annotations

import heapq
from types import SimpleNamespace
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..datapaths import data, var
from ..files import atomic_write

DEFAULT_PATH = data("world", "paths.yaml")
# NATRO MACRO'S OWN WALKING PATHS, loaded alongside the inherited ones.
#
# THE OWNER ASKED FOR THEM: learn from Natro Macro's movement paths. Every
# route in `paths.yaml` came from BeeTuxMacro and on this
# account they do not work -- 31-83% of every walk measured going nowhere, in
# both directions (docs/DESIGN.md 8k). Natro's paths reach all 17 fields and
# come back, on foot, with no cannon and no glide, and they state the hive slot
# as a number instead of baking one in. See scripts/transpile_natro.py.
#
# Loaded SECOND and ADDITIVELY: `load` appends, so both sets of routes are in
# the graph and nothing that worked before has been taken away.
NATRO_PATH = data("world", "natro_paths.yaml")
# NATRO'S GATHER PATTERNS, per field, loaded the same additive way. Every trip
# so far walked `farm_snake`: twelve 16-stud legs inside a box about 16 by 38
# studs, in a field 200 studs across. Natro ships the community's patterns and
# which one each field wants; see scripts/transpile_natro_patterns.py.
NATRO_PATTERNS_PATH = data("world", "natro_patterns.yaml")
# Learned distances live apart from the generated graph, so measuring a
# walk never rewrites the transpiler's output (and re-running the
# transpiler never discards what the bot measured).
MEASURED_PATH = var("measured_routes.yaml")
# BeeTuxMacro's constant: a recorded hold covers the same DISTANCE at any
# walkspeed, which is what makes those recordings transferable at all.
DEFAULT_BASE_SPEED = 32.2


@dataclass
class Edge:
    """One recorded route between two named places."""
    name: str
    start: str
    end: str
    studs: float
    steps: list[dict] = field(default_factory=list)
    verified: bool = False
    via: str = ""
    measured: list[float] = field(default_factory=list)

    def observe(self, actual_studs: float) -> None:
        """Record what the walk really cost, which is how an edge gets verified."""
        if actual_studs > 0:
            self.measured.append(float(actual_studs))
            self.studs = sum(self.measured) / len(self.measured)
            self.verified = True

    @property
    def confidence(self) -> float:
        """1.0 once measured; lower for a transpiled estimate."""
        return 1.0 if self.verified else 0.4


@dataclass
class Route:
    """A sequence of edges from one place to another."""
    legs: list[Edge]

    @property
    def start(self) -> str:
        return self.legs[0].start if self.legs else ""

    @property
    def end(self) -> str:
        return self.legs[-1].end if self.legs else ""

    @property
    def studs(self) -> float:
        return sum(e.studs for e in self.legs)

    @property
    def verified(self) -> bool:
        return all(e.verified for e in self.legs)

    @property
    def places(self) -> list[str]:
        return [self.start] + [e.end for e in self.legs]

    def describe(self) -> str:
        arrow = " -> ".join(self.places)
        mark = "" if self.verified else "  (estimated)"
        return f"{arrow}  {self.studs:,.0f} studs{mark}"

    def __len__(self) -> int:
        return len(self.legs)


@dataclass
class Routine:
    """A recorded sequence that is not a point-to-point move.

    Kept as its own type rather than a bare step list, because `studs` and
    `verified` are the two things a scheduler needs from it and a plain
    dict[str, list] silently discarded both on every save.
    """
    name: str
    steps: list[dict] = field(default_factory=list)
    studs: float = 0.0
    verified: bool = False


class Router:
    """A directed graph of recorded routes.

    The shipped `data/world/paths.yaml` is the transpiler's OUTPUT and carries
    a header saying not to hand-edit it. Measured distances are therefore kept
    separately, in var/, and overlaid at load time -- so learning from a walk
    never rewrites generated content, and re-running the transpiler never
    discards what the bot measured.
    """

    def __init__(self, path: Path | str = DEFAULT_PATH,
                 measurements: Path | str | None = MEASURED_PATH,
                 natro: Path | str | None = None):
        self.edges: list[Edge] = []
        self.routines: dict[str, Routine] = {}
        self.base_speed: float = DEFAULT_BASE_SPEED
        self._out: dict[str, list[Edge]] = {}
        # WHAT AN EDGE COSTS BY ITS MEASURED LANDINGS (brain/skills, DESIGN
        # 8dy): `edge_price(edge)` returns studs / P(land) + (1 - P(land)) x
        # the measured failure cost, or None to leave that edge to this
        # graph's own pricing. None here -- the default, and every test's
        # graph -- prices by studs alone, as before.
        self.edge_price = None
        self.load(path)
        # See NATRO_PATH. Added only for the PROJECT'S OWN graph: a caller who
        # names a file means that file and nothing else, which is what
        # `tests/nav/test_router.py` builds its fixtures on. `Router()` is the
        # real graph and gets both.
        extra = natro
        if extra is None and Path(path) == Path(DEFAULT_PATH):
            extra = NATRO_PATH
        if extra is not None:
            self.load(extra)
        if natro is None and Path(path) == Path(DEFAULT_PATH):
            self.load(NATRO_PATTERNS_PATH)
        if measurements is not None:
            self.load_measurements(measurements)

    def load(self, path: Path | str) -> None:
        try:
            data = yaml.safe_load(Path(path).read_text())
        except (OSError, yaml.YAMLError):
            return
        data = data or {}
        try:
            self.base_speed = float(data.get("base_speed", DEFAULT_BASE_SPEED))
        except (TypeError, ValueError):
            self.base_speed = DEFAULT_BASE_SPEED
        for row in data.get("edges", []):
            try:
                edge = Edge(name=row["name"], start=row["from"], end=row["to"],
                            studs=float(row.get("studs", 0.0)),
                            steps=list(row.get("steps", [])),
                            verified=bool(row.get("verified", False)),
                            via=row.get("via", ""),
                            measured=[float(m) for m in row.get("measured", [])])
            except (KeyError, TypeError, ValueError):
                continue          # a malformed edge must not lose the graph
            self.add(edge)
        for row in data.get("routines", []):
            if "name" not in row:
                continue
            try:
                self.routines[row["name"]] = Routine(
                    name=row["name"], steps=list(row.get("steps", [])),
                    studs=float(row.get("studs", 0.0)),
                    verified=bool(row.get("verified", False)))
            except (TypeError, ValueError):
                continue

    # ---- learned distances, kept apart from the generated file -------------
    def load_measurements(self, path: Path | str = MEASURED_PATH) -> None:
        """Overlay measured walk distances onto the edges, by name."""
        try:
            data = yaml.safe_load(Path(path).read_text())
        except (OSError, yaml.YAMLError):
            return
        measured = (data or {}).get("measured", {})
        if not isinstance(measured, dict):
            return
        by_name = {e.name: e for e in self.edges}
        for name, values in measured.items():
            edge = by_name.get(name)
            if edge is None or not isinstance(values, list):
                continue
            try:
                edge.measured = [float(v) for v in values]
            except (TypeError, ValueError):
                continue
            if edge.measured:
                edge.studs = sum(edge.measured) / len(edge.measured)
                edge.verified = True

    def save_measurements(self, path: Path | str = MEASURED_PATH) -> None:
        """Persist what the bot actually walked, and nothing else.

        Only the measurements. The graph itself is generated, so writing it
        back would overwrite the transpiler's provenance header with a
        machine-ordered copy of its own output.
        """
        measured = {e.name: [round(m, 2) for m in e.measured]
                    for e in self.edges if e.measured}
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(out, yaml.safe_dump(
            {"schema": 1, "measured": measured}, sort_keys=True))

    def add(self, edge: Edge) -> None:
        self.edges.append(edge)
        self._out.setdefault(edge.start, []).append(edge)

    # ---- queries ----------------------------------------------------------
    @property
    def places(self) -> list[str]:
        return sorted({e.start for e in self.edges} | {e.end for e in self.edges})

    def edges_from(self, place: str) -> list[Edge]:
        return list(self._out.get(place, ()))

    def edge(self, start: str, end: str) -> Edge | None:
        """The shortest direct edge, or None. Direction matters."""
        direct = [e for e in self._out.get(start, ()) if e.end == end]
        return min(direct, key=lambda e: e.studs) if direct else None

    def route(self, start: str, end: str,
              prefer_verified: bool = True) -> Route | None:
        """Shortest path by studs, or None when there is no known way.

        `prefer_verified` adds a penalty to estimated edges so a measured route
        wins over a slightly shorter guess -- the shorter guess is only shorter
        according to a number nobody has checked.

        A ROUTE THAT LANDS ELSEWHERE IS NOT AS SHORT AS ITS STUDS. With
        `edge_price` set, an edge costs what that returns
        (brain/skills.SkillBook.edge_cost): studs / P(land) plus
        (1 - P(land)) x its measured failure cost. `Edge.observe` records a
        walk's distance and never a landing somewhere else, so on studs alone
        the Pine Tree walk (0 of its last 10 landed, to attempt 438) cost
        the same as when it landed ten in a row (attempts 376-390).
        """
        if start == end:
            return Route([])
        if start not in self._out:
            return None

        best: dict[str, float] = {start: 0.0}
        came: dict[str, Edge] = {}
        queue: list[tuple[float, str]] = [(0.0, start)]
        seen: set[str] = set()

        while queue:
            cost, place = heapq.heappop(queue)
            if place in seen:
                continue
            seen.add(place)
            if place == end:
                break
            for edge in self._out.get(place, ()):
                price = None
                if self.edge_price is not None:
                    try:
                        price = self.edge_price(edge)
                    except Exception:
                        price = None          # a broken price never loses the graph
                if price is None:
                    penalty = 1.25 if (prefer_verified and not edge.verified) else 1.0
                    price = edge.studs * penalty
                candidate = cost + price
                if candidate < best.get(edge.end, float("inf")):
                    best[edge.end] = candidate
                    came[edge.end] = edge
                    heapq.heappush(queue, (candidate, edge.end))

        if end not in came:
            return None
        legs: list[Edge] = []
        node = end
        while node != start:
            edge = came[node]
            legs.append(edge)
            node = edge.start
        legs.reverse()
        return Route(legs)

    def reachable(self, start: str) -> set[str]:
        """Everywhere we know how to get to from here."""
        out: set[str] = set()
        stack = [start]
        while stack:
            place = stack.pop()
            for edge in self._out.get(place, ()):
                if edge.end not in out:
                    out.add(edge.end)
                    stack.append(edge.end)
        return out

    def dead_ends(self) -> list[str]:
        """Places we can reach but never leave. Honest gaps in the graph."""
        arrivals = {e.end for e in self.edges}
        return sorted(p for p in arrivals if not self._out.get(p))

    def observe_edge(self, name: str, actual_studs: float) -> Edge | None:
        for edge in self.edges:
            if edge.name == name:
                edge.observe(actual_studs)
                return edge
        return None

    def save(self, path: Path | str) -> None:
        """Write the WHOLE graph, losslessly, to an explicit path.

        Every field survives the round trip. The previous version wrote only
        name/from/to/studs/verified/via/steps, so `measured` came back empty
        while `studs` still held the old mean -- and the next observation then
        REPLACED the average instead of extending it (300 and 340 gave 320;
        after a save and reload a third reading of 400 gave 400, not 347).
        It also dropped `base_speed` and each routine's studs and verified.

        There is no default path on purpose: the shipped paths.yaml is
        generated, and `save_measurements()` is what persists learned state.
        """
        rows = []
        for edge in self.edges:
            row = {"name": edge.name, "from": edge.start, "to": edge.end,
                   "studs": round(edge.studs, 1), "verified": edge.verified}
            if edge.via:
                row["via"] = edge.via
            if edge.measured:
                row["measured"] = [round(m, 2) for m in edge.measured]
            row["steps"] = edge.steps
            rows.append(row)
        routines = [{"name": r.name, "studs": round(r.studs, 1),
                     "verified": r.verified, "steps": r.steps}
                    for r in self.routines.values()]
        atomic_write(Path(path), yaml.safe_dump(
            {"schema": 1, "base_speed": self.base_speed,
             "edges": rows, "routines": routines}, sort_keys=False))

    def __len__(self) -> int:
        return len(self.edges)


def fly_this_time(failures: int, use_cannon: bool = True) -> bool:
    """Should this attempt at a field take the cannon, or walk?

    A FIELD ALTERNATES BETWEEN ITS TWO ROUTES OUT, so both are tried before
    it is given up on. `natro_route` falls back from the cannon to the walk
    only when the cannon route DOES NOT EXIST, never when it fails -- so a
    field with both could be barred on four failures of its cannon route
    while its walking route was never run once.

    MEASURED 2026-09-23: twelve fields have both routes, and Clover is barred
    on four failures, every one of them "never stood at the red cannon: 10
    hops toward it without its prompt staying on the panel", with an
    eight-step walking route untried. Clover is also the account's last
    outstanding quest requirement -- 3,000,000 pollen for White Clover Redux,
    whose other half is already complete.

    Attempts 1 and 3 fly, 2 and 4 walk, and
    `brain.decide.TRAVEL_FAILURES_TO_GIVE_UP` is 4, so neither route is
    barred on the other's record. `use_cannon` False is the owner's switch
    and beats all of it.

    NO LONGER THE FARM'S RULE (DESIGN 8dy). The parity flips on a failure of
    EITHER route, so a mis-delivering walk handed every other trip to it
    whatever the flight was doing; run_farm's `natro_route` now chooses by
    each route's own measured landings (brain/skills.SkillBook.choose). Kept
    because tests/nav/test_router.py and tests/unit/test_fieldnotes.py still
    exercise it.
    """
    if not use_cannon:
        return False
    return int(failures or 0) % 2 == 0


def camera_taps(steps) -> int:
    """The net camera rotation a route leaves behind, in 45-degree taps:
    right positive, left negative, a slot switch counted by its `default`
    branch (its cases carry no camera ops).

    WHY IT IS NEEDED. Natro's routes are a CHAIN: the walk out to a field
    leaves the camera turned (`natro_out_spider` +4, a half turn) and that
    field's walk home undoes exactly that (`natro_home_spider` -4). The
    chain breaks the moment the walk home is another field's -- and it is,
    whenever the feed credits a field the trip did not aim at. MEASURED
    2026-09-23 19:19 (attempt 322): out on Spider's route, drifted into
    Strawberry, home on Strawberry's (-2): "facing 90 degrees right of spawn
    heading" at the end, the route walked 90 degrees wrong, and the row
    search and both closers ran facing the wrong way. The caller squares the
    camera to the credited field's own outbound rotation before its walk
    home; see run_farm's `at_my_hive`.
    """
    total = 0
    for step in steps or ():
        op = step.get("op")
        if op == "camera":
            total += 1 if step.get("direction") == "right" else -1
        elif op == "slot_switch":
            total += camera_taps(step.get("default") or [])
    return total


def natro_route(router: "Router", way: str, field: str, use_cannon: bool = True):
    """Natro Macro's own route `way` ("out" or "home") for `field`, or None.

    PREFERRED EXPLICITLY OVER THE ROUTER'S SHORTEST PATH, because the router
    costs a path in studs and BeeTuxMacro's old cannon routes were "shorter"
    only because a flight contributes no studs -- and those were the routes
    MEASURED not to arrive, three nights running. Natro's walking paths press
    nothing and board nothing.

    THE CANNON, WHEN THE OWNER WANTS IT. 2026-09-22: use the cannon for far
    places. For every field whose walk is 400 studs or more the
    transpiler also carries Natro's own cannon branch as
    `natro_out_<field>_via_red_cannon` (docs/DESIGN.md 8ac); with
    `use_cannon` that is the route out. Natro's flights are not BeeTuxMacro's
    -- different approach, different timings, the community's -- and they
    are untested here, which is what `move.use_cannon` is for: one switch
    back to walking if they do not land. The route HOME is always the walk;
    there is no cannon back.

    Returns something with `.legs` (one edge) and `.studs`, like `Router.route`.
    """
    names = []
    if way == "out" and use_cannon:
        names.append(f"natro_out_{field}_via_red_cannon")
    names.append(f"natro_{way}_{field}")
    for name in names:
        edge = next((e for e in router.edges if e.name == name), None)
        if edge is not None:
            return SimpleNamespace(legs=[edge], studs=edge.studs)
    return None

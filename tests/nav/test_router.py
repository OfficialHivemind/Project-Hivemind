"""Route finding over the recorded path graph.

Two properties this must never get wrong:

  the graph is DIRECTED -- Bee Swarm's mountain has one-way drops, and treating
  a recorded route as reversible would walk the character off a ledge

  a missing route is REPORTED, not improvised -- "walk in a straight line" is
  how a bot ends up grinding against a rock for eight hours
"""
import importlib.util
import pathlib
import sys

import pytest

import yaml

from hivemind.nav.router import Edge, Router, Routine


def tiny() -> Router:
    """A three-edge graph, built without touching the shipped files."""
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("a_to_b", "a", "b", 100))
    r.add(Edge("b_to_c", "b", "c", 100))
    r.add(Edge("a_to_c_long", "a", "c", 500))
    return r


# ---- the shipped graph ---------------------------------------------------

def test_the_transpiled_graph_loads():
    r = Router()
    assert len(r) >= 20
    assert "hive" in r.places


def test_no_edge_has_zero_length():
    """A zero-length edge reads as FREE to Dijkstra and captures every route.

    `from_hive_to_rose_field` delegates its travel to another route via a `call`
    step, and the first transpiler counted it as 0 studs.
    """
    for edge in Router().edges:
        assert edge.studs > 0, f"{edge.name} is zero-length"


def test_nothing_shipped_is_verified():
    """They are someone else's recordings until this bot walks them."""
    assert not any(e.verified for e in Router().edges)


def test_multi_hop_routing_works_on_the_real_graph():
    route = Router().route("pineapple", "rose_field")
    assert route is not None
    assert len(route) >= 2
    assert route.start == "pineapple" and route.end == "rose_field"


# ---- direction -----------------------------------------------------------

def test_edges_are_directed():
    r = tiny()
    assert r.route("a", "b") is not None
    assert r.route("b", "a") is None, "a recorded route is not reversible"


def test_a_return_route_is_only_available_if_recorded():
    r = tiny()
    r.add(Edge("b_to_a", "b", "a", 120))
    back = r.route("b", "a")
    assert back is not None
    assert back.studs == 120, "the return leg has its own length"


# ---- missing routes ------------------------------------------------------

def test_an_unknown_destination_returns_none():
    assert tiny().route("a", "atlantis") is None


def test_an_unknown_start_returns_none():
    assert tiny().route("atlantis", "a") is None


def test_routing_to_where_you_already_are_is_an_empty_route():
    route = tiny().route("a", "a")
    assert route is not None and len(route) == 0 and route.studs == 0


# ---- costs ---------------------------------------------------------------

def test_the_shortest_path_wins():
    route = tiny().route("a", "c")
    assert route.studs == 200          # a->b->c beats the 500 direct edge
    assert route.places == ["a", "b", "c"]


def test_a_verified_route_beats_a_slightly_shorter_guess():
    """A shorter estimate is only shorter according to a number nobody checked."""
    r = tiny()
    for e in r.edges:
        if e.name in ("a_to_b", "b_to_c"):
            e.observe(100)             # measured
    direct = [e for e in r.edges if e.name == "a_to_c_long"][0]
    direct.studs = 190                 # an unverified estimate, nominally shorter
    route = r.route("a", "c", prefer_verified=True)
    assert route.places == ["a", "b", "c"]
    assert route.verified


def test_prefer_verified_can_be_switched_off():
    r = tiny()
    direct = [e for e in r.edges if e.name == "a_to_c_long"][0]
    direct.studs = 190
    assert r.route("a", "c", prefer_verified=False).places == ["a", "c"]


def test_duplicate_edges_take_the_shorter():
    r = tiny()
    r.add(Edge("a_to_b_short", "a", "b", 40))
    assert r.edge("a", "b").studs == 40


# ---- measurement ---------------------------------------------------------

def test_walking_an_edge_verifies_it():
    r = tiny()
    edge = r.observe_edge("a_to_b", 118)
    assert edge.verified and edge.studs == 118
    assert edge.confidence == 1.0


def test_repeated_measurements_average():
    r = tiny()
    r.observe_edge("a_to_b", 100)
    r.observe_edge("a_to_b", 120)
    assert r.edge("a", "b").studs == pytest.approx(110)


def test_a_zero_measurement_is_ignored():
    """A failed walk must not claim the edge is free."""
    r = tiny()
    r.observe_edge("a_to_b", 0)
    assert not r.edge("a", "b").verified
    assert r.edge("a", "b").studs == 100


def test_observing_an_unknown_edge_returns_none():
    assert tiny().observe_edge("nope", 10) is None


# ---- graph introspection -------------------------------------------------

def test_reachable_follows_the_graph():
    assert tiny().reachable("a") == {"b", "c"}
    assert tiny().reachable("c") == set()


def test_dead_ends_are_reported():
    assert "c" in tiny().dead_ends()


def test_a_malformed_edge_does_not_lose_the_graph(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text(
        "edges:\n"
        "  - {name: good, from: a, to: b, studs: 10}\n"
        "  - {name: bad, from: a}\n")
    r = Router(path)
    assert len(r) == 1


def test_a_missing_file_gives_an_empty_graph(tmp_path):
    r = Router(tmp_path / "nope.yaml")
    assert len(r) == 0 and r.route("a", "b") is None


def test_saving_preserves_measured_distances(tmp_path):
    r = tiny()
    r.observe_edge("a_to_b", 118)
    out = tmp_path / "saved.yaml"
    r.save(out)
    assert Router(out, measurements=None).edge("a", "b").verified


def test_a_save_round_trip_keeps_the_measurement_HISTORY(tmp_path):
    """Not just the mean. save() used to drop `measured` entirely, so the
    next observation replaced the average instead of extending it: 300 and
    340 gave 320, but after a reload a third reading of 400 gave 400 rather
    than ~347 -- and the edge still claimed to be verified."""
    r = tiny()
    r.observe_edge("a_to_b", 300)
    r.observe_edge("a_to_b", 340)
    assert r.edge("a", "b").studs == pytest.approx(320.0)

    out = tmp_path / "saved.yaml"
    r.save(out)
    again = Router(out, measurements=None)
    assert again.edge("a", "b").measured == [300.0, 340.0]

    again.observe_edge("a_to_b", 400)
    assert again.edge("a", "b").studs == pytest.approx(346.67, abs=0.01)


def test_a_save_round_trip_keeps_base_speed_and_routine_metadata(tmp_path):
    r = tiny()
    r.base_speed = 32.2
    r.routines["collect"] = Routine("collect", [{"op": "walk"}], 80.7, True)
    out = tmp_path / "saved.yaml"
    r.save(out)

    stored = yaml.safe_load(out.read_text())
    assert stored["base_speed"] == pytest.approx(32.2)

    again = Router(out, measurements=None)
    assert again.base_speed == pytest.approx(32.2)
    assert again.routines["collect"].studs == pytest.approx(80.7)
    assert again.routines["collect"].verified is True


def test_measurements_are_stored_apart_from_the_generated_graph(tmp_path):
    """The shipped paths.yaml is transpiler output and says not to hand-edit.

    Learned distances therefore round-trip through their own file, and the
    graph file is never rewritten.
    """
    r = tiny()
    r.observe_edge("a_to_b", 118)
    r.observe_edge("a_to_b", 122)
    store = tmp_path / "measured.yaml"
    r.save_measurements(store)

    fresh = tiny()
    assert fresh.edge("a", "b").studs == pytest.approx(100.0)
    assert not fresh.edge("a", "b").verified
    fresh.load_measurements(store)
    assert fresh.edge("a", "b").measured == [118.0, 122.0]
    assert fresh.edge("a", "b").studs == pytest.approx(120.0)
    assert fresh.edge("a", "b").verified


def test_the_shipped_graph_carries_its_base_speed():
    assert Router().base_speed == pytest.approx(32.2)


# --- the graph must not contain places that do not exist --------------------

def test_no_place_is_a_transpiler_artefact():
    """`from_hive_to_wealth_clock_and_stockings` is a route that visits TWO
    places. Naive parsing made its destination a single place called
    "wealth_clock_and_stockings", which exists nowhere in the game -- it was
    routable, it appeared in places(), and dead_ends() reported it as
    somewhere you can reach but never leave."""
    places = Router().places
    assert "wealth_clock_and_stockings" not in places
    for place in places:
        assert "_and_" not in place, f"{place!r} looks like two places joined"
        assert not place.endswith("_back"), f"{place!r} is a direction, not a place"


def test_the_two_stop_route_ends_at_its_last_stop():
    edge = next(e for e in Router().edges
                if e.name == "from_hive_to_wealth_clock_and_stockings")
    assert (edge.start, edge.end) == ("hive", "stockings")
    assert "wealth_clock" in edge.via, "the intermediate stop must be recorded"


# ---- the field patterns, transpiled from utils.sh --------------------------
#
# BeeTuxMacro keeps its TRAVEL routes in stuff/paths.sh and its FIELD PATTERNS
# in stuff/utils.sh. The transpiler only ever read paths.sh, so the pattern the
# character walks for the entire time it is standing in a field -- the thing
# that actually collects the pollen -- was absent from the graph. The owner's
# config.sh:47 selects farm_better_snake, and farm.sh loops it forever while
# farming, so this was not an optional extra.

FIELD_PATTERNS = ("farm_square", "farm_snake", "farm_better_snake")


def transpiler():
    """Load scripts/transpile_paths.py by path; `scripts/` is not a package.

    Worth the awkwardness: these tests are about what the transpiler EMITS,
    and asserting only against the checked-in paths.yaml would keep passing
    against a stale file long after the generator stopped producing it.
    """
    path = (pathlib.Path(__file__).resolve().parents[2]
            / "scripts" / "transpile_paths.py")
    spec = importlib.util.spec_from_file_location("transpile_paths", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_field_patterns_reached_the_graph():
    """Without these the bot can walk to a field and then do nothing in it.

    The router is what the runner asks for a named sequence, so a pattern that
    is not in `routines` cannot be executed at all -- `RouteRunner.run` returns
    "no route named ...".
    """
    routines = Router().routines
    for name in FIELD_PATTERNS:
        assert name in routines, f"{name} is missing from the graph"
        assert routines[name].studs > 0, f"{name} claims to cover no ground"


def test_a_field_pattern_is_a_routine_and_never_a_place():
    """A pattern is a loop, not a journey: it ends where it started.

    If `endpoints()` ever matched one, "square" or "better_snake" would join
    `places()` as somewhere the character could be routed TO -- the same
    failure as the invented `wealth_clock_and_stockings` node, which was
    routable and showed up in `dead_ends()`.
    """
    r = Router()
    assert not any(e.name in FIELD_PATTERNS for e in r.edges)
    for place in r.places:
        assert "farm" not in place and "snake" not in place, place


# The recordings themselves, hold by hold, transcribed from BeeTuxMacro's
# stuff/utils.sh. `(key, recorded_seconds)` in the order the file walks them.
RECORDED_HOLDS = {
    # utils.sh:710-723 -- one square: left, back, right, forward
    "farm_square": [("a", 0.5), ("s", 0.5), ("d", 0.5), ("w", 0.5)],
    # utils.sh:725-798 -- three back-and-forth sweeps stepping LEFT, then
    # three stepping RIGHT, which is what makes it a snake and not a line
    "farm_snake": ([("s", 0.5), ("a", 0.1), ("w", 0.5), ("a", 0.1)] * 3
                   + [("s", 0.5), ("d", 0.1), ("w", 0.5), ("d", 0.1)] * 3),
    # utils.sh:799-848 -- the same shape with shorter sweeps, three and a half
    # left-stepping cycles closed by one long 0.845 s hop back right
    "farm_better_snake": ([("s", 0.29), ("a", 0.1), ("w", 0.29), ("a", 0.1)] * 3
                          + [("s", 0.29), ("a", 0.1), ("w", 0.29), ("d", 0.845)]),
}


@pytest.mark.parametrize("name, holds, studs", [
    # utils.sh:710  4 holds of 0.5 s                          -> 4 x 16.1
    ("farm_square", 4, 64.4),
    # utils.sh:725  12 of 0.5 s (s/w) + 12 of 0.1 s (a/d)     -> 193.2 + 38.4
    ("farm_snake", 24, 231.6),
    # utils.sh:799  8 of 0.29 s + 7 of 0.1 s + 1 of 0.845 s   -> 74.4+22.4+27.2
    ("farm_better_snake", 16, 124.0),
])
def test_each_pattern_carries_every_recorded_hold(name, holds, studs):
    """Hold counts and distances derived from the recording, not read back off
    the output: studs = recorded_seconds x 32.2 (BASE_SPEED, utils.sh:8, used
    by `wait()` at utils.sh:506), each hold rounded to 0.1 stud before summing
    -- which is why better_snake is 124.0 and not the unrounded 124.5.

    This is the failure this project has already had twice: a line the
    transpiler did not understand vanishing without trace (54 jumps, 22
    shift-locks). A pattern missing one leg still looks healthy -- it just
    walks a shorter loop over less pollen, with nothing anywhere to point at.
    """
    routine = Router().routines[name]
    walks = [s for s in routine.steps if s["op"] == "walk"]
    assert len(walks) == holds, f"{name} lost or gained a hold"
    assert len(routine.steps) == holds, "a field pattern is nothing but holds"
    assert routine.studs == pytest.approx(studs, abs=0.05)


@pytest.mark.parametrize("name", FIELD_PATTERNS)
def test_each_pattern_walks_the_recorded_DIRECTIONS(name):
    """The totals above say nothing about which way the character goes.

    Verified by mutation: rewriting every `keys:` in farm_better_snake to "w"
    turns a 16-leg snake into a 124-stud sprint in one direction -- far less
    ground covered and most of it off the flower patch -- and the whole file
    still passed. A pattern is a SHAPE; the studs are the least of it.

    Expected sequence transcribed from stuff/utils.sh (see RECORDED_HOLDS),
    each hold priced the way `wait()` prices it: seconds x 32.2, rounded to
    0.1 stud, which is exactly the arithmetic the transpiler must do.
    """
    expected = [(key, round(seconds * 32.2, 1))
                for key, seconds in RECORDED_HOLDS[name]]
    actual = [(s["keys"], s["studs"]) for s in Router().routines[name].steps
              if s["op"] == "walk"]
    assert actual == expected


def test_no_shipped_routine_is_verified():
    """`test_nothing_shipped_is_verified` covers edges only, and routines load
    through a different branch of `Router.load()`. They are someone else's
    recordings until this bot walks them, so they must arrive unverified --
    a verified routine would be preferred by the router over a measured one.
    """
    assert not any(r.verified for r in Router().routines.values())


# ---- holds the transpiler cannot price must not disappear ------------------

def test_an_unconvertible_hold_becomes_a_timed_hold_not_a_distance():
    """`down_w / sleep 4 / up_w` has no derivable DISTANCE but a real TIME.

    `sleep` is not scaled by BASE_SPEED/WALKSPEED the way `wait` is
    (utils.sh:506), so the distance depends on the recorder's own walkspeed
    and is not recoverable -- inventing one is still forbidden. The seconds,
    though, are exactly what the recording says, and emitting them reproduces
    it.

    The history is worth keeping: the ORIGINAL parser emitted nothing at all
    and the key-press vanished. It was then changed to emit a `raw` note,
    which was honest but still never ran. Only the third version actually
    performs the hold -- and the one in `from_pine_tree_to_hive` is the glide
    home, so for as long as it did not run, every farm cycle fell short of the
    hive.
    """
    steps = transpiler().parse("function demo(\ndown_w\nsleep 4\nup_w\n)\n")["demo"]
    assert not any(s["op"] == "walk" for s in steps), "no distance may be invented"
    holds = [s for s in steps if s["op"] == "hold"]
    assert len(holds) == 1, "the hold has to survive as something runnable"
    assert holds[0]["keys"] == "w"
    assert abs(float(holds[0]["seconds"]) - 4.0) < 1e-6


def test_a_hold_with_no_sleep_at_all_is_still_only_recorded():
    """No `wait` AND no `sleep` leaves neither a distance nor a time, so
    there is nothing faithful to emit and it stays a `raw` note."""
    steps = transpiler().parse("function demo(\ndown_w\njump\nup_w\n)\n")["demo"]
    assert not any(s["op"] == "hold" for s in steps)
    assert any(s["op"] == "raw" for s in steps)


def test_a_hold_left_open_at_the_end_of_a_function_is_reported():
    """The same drop one line later: a `down_` that the recording never
    released before the closing paren."""
    steps = transpiler().parse("function demo(\ndown_a\njump\n)\n")["demo"]
    assert [s["op"] for s in steps] == ["jump", "raw"]


def test_an_ordinary_priced_hold_is_still_a_walk():
    """The regression the raw-step change could itself have caused: miss the
    `converted` flag and every normal hold becomes a raw step, which would
    zero all 17,599 studs of the graph while still parsing cleanly."""
    steps = transpiler().parse("function demo(\ndown_d\nwait 6.6\nup_d\n)\n")["demo"]
    assert len(steps) == 1
    assert steps[0]["op"] == "walk" and steps[0]["keys"] == "d"
    assert steps[0]["studs"] == pytest.approx(6.6 * 32.2, abs=0.05)


def test_a_hold_that_outlives_its_wait_is_reported_too():
    """Half-priced is still half-dropped.

    `down_d / wait 5 / sleep 1 / wait 5 / up_d` converts BOTH waits, so the
    hold looks fully accounted for -- but D was also down across the `sleep`,
    which is a second of walking that no `wait` priced. Checking only for a
    hold with NO wait at all (the first version of this) misses it entirely,
    and paths.sh:675-683 is a real instance.
    """
    steps = transpiler().parse(
        "function demo(\ndown_d\nwait 5\nsleep 1\nwait 5\nup_d\n)\n")["demo"]
    assert [s["op"] for s in steps] == ["walk", "pause", "walk", "raw"]
    assert sum(s["studs"] for s in steps if s["op"] == "walk") == pytest.approx(
        322.0, abs=0.05), "the priced part must still be priced"
    assert "sleep 1" in steps[-1]["text"]


def test_a_hold_replaced_without_a_release_is_reported():
    """`down_ds / wait 1.3 / down_d` (paths.sh:673-675) never releases S.

    The macro walks the REST of that route holding S and D together; this
    graph walks D alone, because reproducing the source macro's stuck key is
    forbidden. That divergence is a real difference in heading over 322 studs,
    so it is written into the route rather than left for someone to rediscover
    by watching the character end up in the wrong place.
    """
    steps = transpiler().parse(
        "function demo(\ndown_ds\nwait 1.3\ndown_d\nwait 5\nup_d\n)\n")["demo"]
    assert [s["op"] for s in steps] == ["walk", "raw", "walk"]
    assert steps[0]["keys"] == "ds" and steps[2]["keys"] == "d"
    assert "never released" in steps[1]["text"]


def test_a_fully_priced_hold_gets_no_note():
    """The other half of the two tests above: the note must be RARE.

    A `raw` step lands in `RouteRunner.run(...).skipped`, which is what the
    GUI shows as "this route did something I could not do". Emitting one for
    every ordinary hold would bury the four that matter under 200 that do not.
    """
    steps = transpiler().parse(
        "function demo(\ndown_w\nwait 2\njump\nwait 2\nup_w\n)\n")["demo"]
    assert [s["op"] for s in steps] == ["walk", "jump", "walk"]


def test_the_shipped_graph_keeps_every_unpriceable_hold():
    """MEASURED by walking every down_/up_ pair in paths.sh. Four holds carry
    time that `wait` never priced, and all four used to vanish silently:

      from_pine_tree_to_hive       W across `sleep 4`    (paths.sh:761-763)
      from_rose_field_to_hive      W across `sleep 0.1`  (paths.sh:699-701)
      from_hive_to_pumpkin_...     S+D never released    (paths.sh:673-675)
      from_hive_to_pumpkin_...     D across 2x `sleep 1` (paths.sh:675-683)

    There are no others. If a regeneration loses them again nothing else in
    the suite would notice -- the studs would not move, because the whole
    point is that these holds never contributed any.
    """
    by_name = {e.name: e for e in Router().edges}
    pumpkin = "from_hive_to_pumpkin_with_red_cannon"

    # TWO OF THE FOUR ARE NOW RUN, NOT JUST RECORDED.
    #
    # A hold with a `sleep` and no `wait` has no derivable distance, but it
    # does have a TIME, and for these two that is the honest unit: both are
    # falls, and descent does not scale with walkspeed the way `wait` does.
    # They are emitted as `hold` steps and executed.
    #
    # This matters beyond tidiness. `from_pine_tree_to_hive`'s four seconds
    # ARE the glide off the pine tree, and while it was a `raw` note the
    # executor skipped it -- so every farm cycle jumped off the edge, fell
    # short of the hive, and then pressed its interact key wherever it landed.
    # The owner watched it happen: "it jumped behind the ledge so id didnt
    # even glide down".
    runnable = {
        "from_pine_tree_to_hive": ("w", 4.0),
        "from_rose_field_to_hive": ("w", 0.1),
    }
    for name, (keys, seconds) in runnable.items():
        holds = [s for s in by_name[name].steps if s["op"] == "hold"]
        assert len(holds) == 1, f"{name} has {holds}"
        assert holds[0]["keys"] == keys
        assert abs(float(holds[0]["seconds"]) - seconds) < 1e-6

    # The other two still cannot be run and are still only recorded: one key
    # is never released at all, and the other stayed down after a `wait` that
    # already priced part of it. Reproducing either would mean inventing
    # behaviour the recording does not contain.
    recorded = {
        pumpkin: ["down_ds was never released",
                  "down_d stayed down after its `wait`, across [sleep 1 ; sleep 1]"],
    }
    for name, wanted in recorded.items():
        raw = [s["text"] for s in by_name[name].steps if s["op"] == "raw"]
        assert len(raw) == len(wanted), f"{name} has {raw}"
        for text, want in zip(raw, wanted):
            assert text.startswith(want), text

    others = [e.name for e in Router().edges
              if e.name not in recorded and e.name not in runnable
              and any("down_" in s.get("text", "") for s in e.steps
                      if s["op"] == "raw")]
    assert others == [], f"an unpriced hold appeared somewhere new: {others}"


# ---- merging the second source file ----------------------------------------

def test_a_missing_field_pattern_is_named_rather_than_shrugged_off(tmp_path):
    """A pattern that fails to transpile costs the bot every field visit, so
    the merge reports what it could not find (and `main()` then exits
    non-zero) instead of writing a quietly incomplete graph."""
    mod = transpiler()
    utils = tmp_path / "utils.sh"
    utils.write_text("function farm_square(\ndown_a\nwait 0.5\nup_a\n)\n")
    routes: dict[str, list[dict]] = {}
    missing = mod.farm_patterns(utils, routes, "paths.sh")
    assert "farm_square" in routes
    assert missing == ["farm_snake", "farm_better_snake"]


def test_a_name_defined_in_both_files_keeps_the_paths_sh_version(tmp_path):
    """One name, two source files, different steps. Letting the second file
    win would change what an existing route DOES with nothing in the output to
    say why, so the paths.sh definition is kept and the clash is printed."""
    mod = transpiler()
    utils = tmp_path / "utils.sh"
    utils.write_text("function farm_square(\ndown_a\nwait 9\nup_a\n)\n")
    original = [{"op": "walk", "keys": "d", "studs": 1.0}]
    routes = {"farm_square": list(original)}
    mod.farm_patterns(utils, routes, "paths.sh")
    assert routes["farm_square"] == original


def test_a_missing_utils_file_does_not_lose_the_travel_graph(tmp_path):
    """BeeTuxMacro may not be installed on the machine doing the regeneration.
    That must cost the field patterns and say so, not abort the 17,599 studs of
    travel routes that came from the file which IS there."""
    mod = transpiler()
    routes = {"from_hive_to_pine_tree": []}
    missing = mod.farm_patterns(tmp_path / "nope.sh", routes, "paths.sh")
    assert missing == list(mod.FARM_PATTERNS)
    assert "from_hive_to_pine_tree" in routes


def test_a_regeneration_that_lost_a_pattern_exits_non_zero(tmp_path,
                                                           monkeypatch):
    """`main()` writing a quietly incomplete graph is the failure mode here.

    The travel edges still come out fine, so the file LOOKS right and the exit
    status is the only signal a regeneration script or a Makefile ever sees. A
    zero exit with no field patterns is how the bot ends up walking to a field
    and standing in it.
    """
    mod = transpiler()
    paths = tmp_path / "paths.sh"
    paths.write_text("function from_hive_to_pine_tree(\ndown_w\nwait 2\nup_w\n)\n")
    utils = tmp_path / "utils.sh"
    utils.write_text("function farm_square(\ndown_a\nwait 0.5\nup_a\n)\n")
    out = tmp_path / "paths.yaml"
    monkeypatch.setattr(mod, "OUT", out)
    monkeypatch.setattr(sys, "argv", ["transpile", str(paths), str(utils)])

    assert mod.main() == 1, "two patterns are missing and it said all was well"

    written = yaml.safe_load(out.read_text())
    assert [e["name"] for e in written["edges"]] == ["from_hive_to_pine_tree"], (
        "the travel graph must survive a missing pattern")
    assert [r["name"] for r in written["routines"]] == ["farm_square"]


def test_a_complete_regeneration_exits_zero(tmp_path, monkeypatch):
    """The other half: a non-zero exit that never clears is a broken alarm."""
    mod = transpiler()
    paths = tmp_path / "paths.sh"
    paths.write_text("function from_hive_to_pine_tree(\ndown_w\nwait 2\nup_w\n)\n")
    utils = tmp_path / "utils.sh"
    utils.write_text("".join(
        f"function {name}(\ndown_a\nwait 0.5\nup_a\n)\n"
        for name in mod.FARM_PATTERNS))
    monkeypatch.setattr(mod, "OUT", tmp_path / "paths.yaml")
    monkeypatch.setattr(sys, "argv", ["transpile", str(paths), str(utils)])
    assert mod.main() == 0


def test_a_missing_source_file_exits_non_zero(tmp_path, monkeypatch):
    """Distinct from a missing pattern: nothing at all was transpiled."""
    mod = transpiler()
    monkeypatch.setattr(mod, "OUT", tmp_path / "paths.yaml")
    monkeypatch.setattr(sys, "argv", ["transpile", str(tmp_path / "nope.sh")])
    assert mod.main() == 2
    assert not (tmp_path / "paths.yaml").exists(), "wrote an empty graph"


# ------------------- Natro Macro's walking paths, loaded alongside ----------
# THE OWNER ASKED FOR THEM: "why dont u teach it using samples of natro macro
# movements". Every route in paths.yaml came from BeeTuxMacro and on his
# account they do not work -- 31-83% of every walk measured going nowhere, in
# both directions (docs/DESIGN.md 8k). See scripts/transpile_natro.py.

FIELD_NODES = ["bamboo", "blue_flower", "cactus", "clover", "coconut",
               "dandelion", "mountain_top", "mushroom", "pepper", "pineapple",
               "pine_tree", "pumpkin", "rose_field", "spider", "strawberry",
               "stump", "sunflower"]


def test_the_real_graph_carries_a_walking_path_out_to_every_field():
    from hivemind.nav.router import Router
    rt = Router()
    names = {e.name for e in rt.edges}
    missing = [f for f in FIELD_NODES if f"natro_out_{f}" not in names]
    assert missing == [], f"no walking path out to {missing}"


def test_the_walks_home_are_every_natro_path_but_the_portal_ones():
    """CHANGED ON 2026-09-23, twice, and it used to assert seventeen.

    Ten of the seventeen `wf-*` paths contain `switch HiveSlot`, and the
    transpiler used to resolve it to the `default:` body -- the walk to the
    ramp corner -- reasoning that the ramp was the same destination a little
    further on. The frames under var/routes/attempt-296 showed otherwise:
    `natro_home_spider` stood on the owner's own pad after leg 09 and then
    walked 140 studs to the ramp, because the `case 3` branch that stops on
    pad 3 had been thrown away. The switch is now a `slot_switch` step and
    the runner chooses (act/routes._branch_of). See docs/DESIGN.md 8cc and
    scripts/transpile_natro.slot_switch.

    Two walks home are deliberately ABSENT: bamboo and blue flower press E
    at the blue portal, and a walking route never presses E (the journey
    would refuse it at a panel that does not name the place). The five that
    hold a key through a jump -- coconut, pineapple, pine tree, pumpkin and
    stump -- were refused for an hour on 2026-09-23 while `steps_of` could
    not express a jump; it can now (key_down, jump_hold, coast, key_up), and
    the routes it used to emit for them, the walks either side of a MISSING
    jump, are how `natro_home_stump` came to spend 81% of its first leg
    against a wall.
    """
    from hivemind.nav.router import Router
    rt = Router()
    home = {e.name.split("natro_home_")[1] for e in rt.edges
            if e.name.startswith("natro_home_")}
    out = {e.name.split("natro_out_")[1] for e in rt.edges
           if e.name.startswith("natro_out_")}

    # all seventeen: the two through the blue portal (Bamboo, Blue Flower)
    # press its E only on a panel naming the portal (`interact_when`)
    assert home == {"bamboo", "blue_flower", "cactus", "clover", "coconut",
                    "dandelion", "mountain_top", "mushroom", "pepper", "pine_tree",
                    "pineapple", "pumpkin", "rose_field", "spider", "strawberry",
                    "stump", "sunflower"}, sorted(home)
    assert home <= out, f"a way back from somewhere with no way there: {home - out}"


def test_a_branched_walk_home_keeps_both_branches_for_the_runner_to_choose():
    """THE REGRESSION THE OLD SKIP WAS PROTECTING AGAINST, and the one the
    old resolution introduced.

    A path that read both branches as one sequence ended with FOUR walks and
    landed between two pads. A path that kept only `default` walked every
    slot to the ramp corner, including the slot whose branch stops on its
    own pad. The honest shape is the data as Natro wrote it: `case 3` is one
    walk (2.7 tiles back), `default` is three (1.5 back, 35 right to the
    ramp, 2.7 back to centre), and which one runs is the runner's decision
    once it knows the slot.
    """
    from hivemind.nav.router import Router
    rt = Router()
    steps = next(e for e in rt.edges if e.name == "natro_home_mushroom").steps
    switch = steps[-1]
    assert switch["op"] == "slot_switch", steps[-3:]
    assert switch["cases"] == {"3": [{"op": "walk", "keys": "s", "studs": 10.8}]}
    assert [(s["keys"], s["studs"]) for s in switch["default"]] == \
        [("s", 6.0), ("d", 140.0), ("s", 10.8)]
    # nothing before the switch is a branch step: the mixture is gone
    assert all(s["op"] != "slot_switch" for s in steps[:-1])

    # and the general path ends exactly as a path that never branched does,
    # which is what makes the row search (act/hiverow) right for both
    plain = [(s.get("keys"), s.get("studs")) for s in
             next(e for e in rt.edges if e.name == "natro_home_dandelion").steps
             if s.get("op") == "walk"][-3:]
    assert plain == [("s", 6.0), ("d", 140.0), ("s", 10.8)], plain


def _every_step(steps):
    """Steps with each `slot_switch` opened out into all of its branches."""
    for s in steps:
        yield s
        if s.get("op") == "slot_switch":
            for body in list(s.get("cases", {}).values()) + [s.get("default", [])]:
                yield from _every_step(body)


def test_the_walking_paths_press_nothing_but_movement():
    """The point of taking the walking branch: no `interact`, nothing that
    boards the cannon. Jumps ARE allowed since 2026-09-23 -- the quest
    givers' paths hop up onto platforms and five walks home hop a ledge, and
    a route with its jump left out is a different route. The cannon branches
    (`*_via_red_cannon`) fly on purpose and are held to their own rules in
    tests/unit/test_cannon.py. Every branch of a slot switch is held to this
    too."""
    from hivemind.nav.router import Router
    rt = Router()
    banned = {"interact", "reset", "hop_to_slot", "raw"}
    for edge in rt.edges:
        if not edge.name.startswith("natro_") or edge.name.endswith("_via_red_cannon"):
            continue
        steps = list(_every_step(edge.steps))
        ops = {s.get("op") for s in steps}
        assert not (ops & banned), f"{edge.name} contains {ops & banned}"
        # a held E is a press spelt differently (the blue portal)
        assert not any(s.get("op") in ("key_down", "key_up") and "e" in str(s.get("keys", ""))
                       for s in steps), f"{edge.name} holds the interact key"


def test_every_field_path_out_starts_by_going_to_the_owned_slot():
    """Natro's `nm_gotoRamp()`: forward 5 tiles, then `9.2*HiveSlot-4` tiles
    right. The slot is the one number that makes a path transferable, and
    `act.routes._hive_offset` refuses to guess it."""
    from hivemind.nav.router import Router
    rt = Router()
    out = [e for e in rt.edges if e.name.startswith("natro_out_")
           and e.name.split("natro_out_")[1] in FIELD_NODES]
    assert len(out) == len(FIELD_NODES)
    for edge in out:
        assert edge.steps[0] == {"op": "walk", "keys": "w", "studs": 20.0}
        offset = edge.steps[1]
        assert offset["op"] == "hive_offset"
        assert offset["tiles_per_slot"] == 9.2
        assert offset["tiles_offset"] == -4.0
        assert offset["studs_per_tile"] == 4.0


def test_the_other_hive_slot_formula_is_read_as_a_slope_and_an_intercept():
    """Natro has exactly two shapes and the second one runs the other way:
    `nm_Walk(9.2*(7-HiveSlot) + 10, LeftKey)` for the honey dispenser. As a
    slope and an intercept that is -9.2 per slot plus 74.4, walking left.
    """
    from hivemind.nav.router import Router
    rt = Router()
    edge = next(e for e in rt.edges if e.name == "natro_out_honey_dispenser")
    offset = next(s for s in edge.steps if s["op"] == "hive_offset")
    assert offset["keys"] == "a"
    assert offset["tiles_per_slot"] == -9.2
    assert offset["tiles_offset"] == 74.4
    # slot 1 is the longest walk and slot 6 the shortest, both positive
    for slot, tiles in ((1, 65.2), (6, 19.2)):
        assert round(-9.2 * slot + 74.4, 4) == tiles


def test_a_named_file_means_that_file_and_nothing_else(tmp_path):
    """`Router()` is the project's graph and gets both files; `Router(path)`
    is a fixture and must not have 34 extra routes appear in it. Every router
    test in this file is built on that."""
    from hivemind.nav.router import DEFAULT_PATH, Router
    assert any(e.name.startswith("natro_")
               for e in Router(DEFAULT_PATH, measurements=None).edges)
    lonely = Router(tmp_path / "nope.yaml", measurements=None)
    assert len(lonely.edges) == 0


def test_the_graph_knows_the_way_to_every_bear_and_every_shop():
    """THE REST OF WHAT THE OWNER ASKED FOR: "teach it using samples of natro
    macro movements" is not only the fields. docs/GAPS.md #6 is a finished
    quest sitting unclaimed because the bot could not walk to a bear, and #3
    is "it cannot buy anything" because there was no route to a shop."""
    from hivemind.nav.router import Router
    rt = Router()
    names = {e.name for e in rt.edges}
    # Natro's gtb-* paths are the three field boosters (named so since
    # 2026-09-26, 1bc05a3 -- they were "blue_hq", "red_hq", "mountain_hq")
    wanted = ["black_bear", "brown_bear", "bucko_bee", "honey_bee", "panda_bear",
              "polar_bear", "riley_bee", "blue_field_booster", "red_field_booster",
              "white_field_booster"]
    missing = [w for w in wanted if f"natro_out_{w}" not in names]
    assert missing == [], f"no walking path to {missing}"
    for target in wanted:
        assert rt.route("hive", target) is not None, f"cannot route to {target}"


def test_a_walk_to_a_bear_presses_nothing_but_movement_either():
    """The bears' paths have the branches the other way round -- `if
    (MoveMethod = "walk")` rather than `if (MoveMethod = "Cannon")` -- and
    reading that wrongly dropped five of the nine as "cannon only". They DO
    jump: the Bucko Bee and the Honey Bee sit on platforms, and the hop up
    is part of the path (2026-09-23). What they never do is press E -- the
    hand-in is act/bearvisit's decision, taken against a prompt it has read."""
    from hivemind.nav.router import Router
    rt = Router()
    banned = {"interact", "reset", "hop_to_slot", "raw"}
    walkers = [e for e in rt.edges
               if e.name.startswith("natro_out_")
               and e.name.split("natro_out_")[1].endswith(("_bear", "_bee", "_booster"))]
    assert len(walkers) == 12, [e.name for e in walkers]   # + the Mother Bear, the Spirit Bear (2026-10-06)
    for edge in walkers:
        ops = {s.get("op") for s in edge.steps}
        assert not (ops & banned), f"{edge.name} contains {ops & banned}"
        assert not any(s.get("op") in ("key_down", "key_up") and "e" in str(s.get("keys", ""))
                       for s in edge.steps), f"{edge.name} holds the interact key"
    # and the Bucko Bee's platform hop -- the nine walks after the if/else
    # that `rfind("}")` used to hand to the cannon branch -- is there
    bucko = next(e for e in walkers if e.name == "natro_out_bucko_bee")
    tail = [(s.get("op"), s.get("keys"), s.get("studs")) for s in bucko.steps[-4:]]
    assert tail[-1] == ("walk", "w", 20.0) and tail[-2][0] == "jump_release", tail
    assert len(bucko.steps) >= 24, len(bucko.steps)


def test_natro_route_flies_out_to_a_far_field_and_walks_home():
    from hivemind.nav.router import Router, natro_route
    rt = Router()
    out = natro_route(rt, "out", "spider")
    assert out is not None and out.legs[0].name == "natro_out_spider_via_red_cannon"
    home = natro_route(rt, "home", "spider")
    assert home is not None and home.legs[0].name == "natro_home_spider"
    assert natro_route(rt, "out", "spider", use_cannon=False).legs[0].name == "natro_out_spider"


def test_a_walk_home_that_glides_off_a_ledge_carries_its_jump():
    """Natro's wf-pinetree holds Forward, jumps, and coasts 108 tiles down
    to the hive lawn. The route is that hop, as data, and not the walks
    either side of it."""
    from hivemind.nav.router import Router, natro_route
    rt = Router()
    assert natro_route(rt, "out", "pine_tree").legs[0].name == "natro_out_pine_tree_via_red_cannon"
    steps = natro_route(rt, "home", "pine_tree").legs[0].steps
    ops = [s["op"] for s in steps]
    hop = ops.index("jump_hold")
    assert ops[hop - 2:hop + 5] == ["key_down", "coast", "jump_hold", "pause", "jump_release",
                                    "coast", "key_up"], ops
    assert steps[hop + 3] == {"op": "coast", "studs": 432.0}       # Walk(108)
    assert steps[-1]["op"] == "slot_switch"


def test_natro_route_walks_to_a_near_field_whatever_the_switch_says():
    from hivemind.nav.router import Router, natro_route
    rt = Router()
    assert natro_route(rt, "out", "dandelion").legs[0].name == "natro_out_dandelion"
    assert natro_route(rt, "out", "nowhere") is None


def test_the_way_back_from_a_place_beside_the_hive_is_in_the_graph():
    """MEASURED 2026-09-22 22:54: homing walked the row and the panel said
    "at the honey dispenser". Natro's pad->dispenser route reversed is a
    measured way home from a place the game names."""
    from hivemind.nav.router import Router
    rt = Router()
    by_name = {e.name: e for e in rt.edges}
    back = by_name.get("natro_back_honey_dispenser")
    assert back is not None
    assert (back.start, back.end) == ("honey_dispenser", "hive")
    ops = [s["op"] for s in back.steps]
    assert set(ops) <= {"walk", "hive_offset", "camera"}, ops
    out = by_name["natro_out_honey_dispenser"]
    assert len(back.steps) == len(out.steps)
    # every walk is the opposite of the outward one, in reverse order
    opposite = {"w": "s", "s": "w", "a": "d", "d": "a"}
    for there, home in zip(out.steps, reversed(back.steps)):
        if there["op"] == "walk":
            assert home["keys"] == "".join(opposite[k] for k in there["keys"])
            assert home["studs"] == there["studs"]


def test_no_reversal_is_offered_for_a_route_that_jumps_or_presses():
    """A jump cannot be un-jumped and a press is not a walk."""
    from hivemind.nav.router import Router
    rt = Router()
    reversible = {"walk", "hive_offset", "camera"}
    for edge in rt.edges:
        if not edge.name.startswith("natro_back_"):
            continue
        assert {s["op"] for s in edge.steps} <= reversible, edge.name
        assert edge.studs <= 250.0, f"{edge.name} is {edge.studs} studs; a lean reverses into an overshoot"


# ---- a field alternates between its two routes out ------------------------
# `natro_route` falls back from the cannon to the walk only when the cannon
# route DOES NOT EXIST, never when it fails. So a field with both could be
# barred on four failures of its cannon route while its walking route was
# never run once. MEASURED 2026-09-23: twelve fields have both, and Clover is
# barred on four failures -- every one "never stood at the red cannon: 10 hops
# toward it without its prompt staying on the panel" -- with an eight-step
# walking route untried. Clover is also the account's last outstanding quest
# requirement, 3,000,000 pollen for White Clover Redux.

def test_the_first_attempt_flies():
    from hivemind.nav.router import fly_this_time
    assert fly_this_time(0) is True


def test_it_walks_after_a_failure():
    from hivemind.nav.router import fly_this_time
    assert fly_this_time(1) is False


def test_both_routes_are_tried_before_the_field_is_given_up_on():
    from hivemind.nav.router import fly_this_time
    from hivemind.brain.decide import TRAVEL_FAILURES_TO_GIVE_UP
    tries = [fly_this_time(n) for n in range(TRAVEL_FAILURES_TO_GIVE_UP)]
    assert any(tries), f"the cannon never got a turn: {tries}"
    assert not all(tries), f"the walk never got a turn: {tries}"


def test_the_owners_switch_beats_the_alternation():
    from hivemind.nav.router import fly_this_time
    assert fly_this_time(0, use_cannon=False) is False
    assert fly_this_time(2, use_cannon=False) is False


def test_rubbish_counts_as_no_failures():
    from hivemind.nav.router import fly_this_time
    assert fly_this_time(None) is True


def test_the_walking_route_is_what_it_falls_back_to():
    """The point of alternating: the SAME field, asked twice, gives two
    different routes out."""
    import pathlib
    from hivemind.nav.router import Router, natro_route, fly_this_time
    root = pathlib.Path(__file__).resolve().parents[2]
    paths = root / "data/world/natro_paths.yaml"
    if not paths.exists():
        pytest.skip("the route graph is not in the repo")
    r = Router()
    r.load(paths)
    flown = natro_route(r, "out", "clover", use_cannon=fly_this_time(0))
    walked = natro_route(r, "out", "clover", use_cannon=fly_this_time(1))
    assert flown and walked
    assert flown.legs[0].name == "natro_out_clover_via_red_cannon"
    assert walked.legs[0].name == "natro_out_clover"


# ---- the camera rotation a route leaves behind --------------------------------
# A walk home undoes its own field's walk out. MEASURED 2026-09-23 19:19: out on
# Spider's route (+4 taps), credited Strawberry, home on Strawberry's (-2), and
# the character finished "facing 90° right of spawn heading". run_farm squares
# the camera to the credited field's outbound rotation first; this is the sum
# it uses.

def test_camera_taps_counts_right_as_positive_and_left_as_negative():
    from hivemind.nav.router import camera_taps
    steps = [{"op": "walk", "keys": "w", "studs": 10},
             {"op": "camera", "direction": "right"}, {"op": "camera", "direction": "right"},
             {"op": "camera", "direction": "left"},
             {"op": "slot_switch", "cases": {"3": [{"op": "walk", "keys": "s", "studs": 10.8}]},
              "default": [{"op": "camera", "direction": "left"}]}]
    assert camera_taps(steps) == 0
    assert camera_taps(steps[:-1]) == 1
    assert camera_taps([]) == 0


def test_every_walk_home_undoes_its_own_walk_out():
    """The chain Natro relies on, checked over the real graph: each field's
    walk home turns the camera back by what its walking route out turned it,
    modulo a full turn."""
    from hivemind.nav.router import Router, camera_taps
    rt = Router()
    edges = {e.name: e for e in rt.edges}
    checked = 0
    for name, edge in edges.items():
        if not name.startswith("natro_home_"):
            continue
        field = name.split("natro_home_")[1]
        out = edges.get(f"natro_out_{field}")
        if out is None:
            continue
        assert (camera_taps(out.steps) + camera_taps(edge.steps)) % 8 == 0, \
            (field, camera_taps(out.steps), camera_taps(edge.steps))
        checked += 1
    assert checked >= 10, checked

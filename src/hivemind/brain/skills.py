"""Every route and errand as a skill with a measured landing rate (DESIGN 8dy).

WHY. Arriving at the right field is the biggest measured loss: of the 150
gathering trips in var/trips.jsonl (to 2026-09-25 23:45, 337 rows) whose field
the reward feed named, 45 landed somewhere other than the field aimed at --
Cactus 1 of 13, Spider 6 of 12, Pine Tree 32 of 46 (the game-AI plan, #1). And
nothing knew which ROUTE did it: `Edge.observe` never records a failed
landing, the planner counts failures per field, and the choice between a
field's walk and its flight was a parity that flipped on every failure of
either (`nav.router.fly_this_time`). Measured here, per route, over the saved
route frames (scripts/replay_skills.py, 441 ledger rows to 2026-09-26 16:27):
the Pine Tree walk landed 31 of its 45 trips to attempt 406 and 0 of its 32
from 407, while the Pine Tree flight landed 13 of the 14 it was judged on.

WHAT A SKILL IS. A route name (`natro_out_<field>`, its `_via_red_cannon`
flight, `natro_home_<field>`, an errand's `natro_out_<place>`) with a count of
what its runs did:

  * landed     -- the route delivered: the feed credited its field, the pad's
                  prompt showed at the end of a walk home (the route or its row
                  closer, not the search by sight), an errand read the place's
                  own prompt;
  * elsewhere  -- it ran and delivered somewhere else;
  * unknown    -- no verdict (a stop, a death, a counter that never read, no
                  field named);
  * missed     -- flights only: the cannon approach missed, so the flight
                  never flew (the trip then walked, and the walk is judged).

Voyager keeps only the skills that pass a check, and removing the check cut
what it found by 73% (arXiv 2305.16291); SIMA names every behaviour and checks
it (arXiv 2404.10179).

THE LEDGER IS THE SOURCE, THIS IS A CACHE OF IT. Each trip row in
var/trips.jsonl now carries `routes`: one entry per route the trip ran, with
its outcome and seconds, decided by `settle_trip` from the same evidence the
farm loop already has. var/skill_stats.json is those rows folded together
(`SkillBook.fold`), so it can be rebuilt at any time from the ledger -- and a
row written before the ledger carried `routes` is settled the same way from
its saved route frames and its run log (`rebuild`). scripts/replay_skills.py
does that and prints the table.

WHAT IS PRICED. The chance a route lands is a Beta posterior over its last
SKILL_WINDOW verdicts (landed against elsewhere), and a route is priced in
studs as `length / P(land) + (1 - P(land)) x failure cost` (`edge_cost`, the
plan's formula): its length the measured seconds its landed runs take,
walked at the caller's walkspeed (its recorded studs until it has any), and
the failure cost the measured seconds of its failed runs plus the caller's
measured recovery, walked the same way.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..datapaths import var
from ..files import atomic_write
from .decide import ROUTER_ALIASES

SKILL_FILE = var("skill_stats.json")
# THE FOLD'S RULES. A stored book made under other rules is rebuilt from the
# ledger rather than trusted: its counts mean something else. Bump it when
# `settle_trip`, `infer_trip` or `SkillBook.fold` changes what a count means.
# 2: a route out landed when the feed named its field at all after it ended,
# not only last; a walk home is judged only from a start the feed placed; a
# check-stopped run that the journey retried has no verdict (DESIGN 8dy's
# review).
RULES = 2

# THE PRIOR, Beta(1, 1): a route never judged is even odds, the uniform prior
# the Thompson sampling tutorial's Bernoulli bandit starts from (Russo et al.,
# arXiv 1707.02038, section 3). With integer counts the posterior's tail is a
# binomial sum (`_at_least`), so nothing here needs scipy.
PRIOR_LANDED = 1
PRIOR_ELSEWHERE = 1

# HOW MANY OF A ROUTE'S VERDICTS THE POSTERIOR IS OVER: the last ten, the same
# window and for the same measured reason as run_farm's
# WRONG_FIELD_RECENT_TRIPS -- a route's landing rate changes under it. MEASURED
# 2026-09-26 over the saved route frames (scripts/replay_skills.py, 441 rows):
# the Pine Tree walk landed 31 of 45 to attempt 406 and 0 of 32 from 407; over
# all its history it reads 31 of 77, 0.40, while it was landing nowhere. Ten
# covers that change within two sessions of trips, and at p = 0.5 a ten-trip
# share is good to one binomial standard deviation of 0.16. The all-time counts
# are kept too, for the table.
SKILL_WINDOW = 10

# A ROUTE IS QUARANTINED -- not taken while another route goes the same way,
# and named for the owner in the morning report -- when its posterior is at
# least QUARANTINE_SURE sure that it lands where it is named less often than
# QUARANTINE_BELOW. MEASURED over every ten-verdict window of the saved route
# frames (scripts/replay_skills.py --windows --rows 441, 2026-09-26 16:27,
# RULES 2): while they worked, the routes never had a window under 5 landings
# of 10 (the Pine Tree walk to attempt 406: 5-10; Strawberry's walk to 431:
# 7-10; the Spider walk 6-9; Dandelion's walk 10; the Pine Tree flight 9-10;
# the Strawberry walk home from 324: 7-10; Pine Tree's 6-7); the broken ones
# sit at 0-2 (the Pine Tree walk from 407 and the Coconut Dispenser: 0 in
# every window; the Brown Bear and the Dandelion walk home 0-1; the Blue
# Flower walk home 0 of 8, the Riley Bee 0 of 9, the Black Bear 1 of 9).
# Between them are the routes that land now and then (the Mushroom walk home
# 4-7, the Treat Dispenser 3-4, the Blueberry Dispenser 2-6, quarantined at
# its current 2 of 10). 0.5 is the middle of the gap. With a full window 0.95
# quarantines at 2 landings of 10 or fewer (P(p >= 0.5) is 0.033 at 2 of 10 and
# 0.113 at 3), so one bad trip in a good route's window cannot do it; a route
# needs at least four verdicts, all elsewhere, before it can be (0 of 3 gives
# 0.063, 0 of 4 0.031).
QUARANTINE_BELOW = 0.5
QUARANTINE_SURE = 0.95

# Q4: A ROUTE THAT HAS NEVER LANDED is not worth another try until it changes.
# MEASURED 2026-10-19 (var/skill_stats.json): natro_out_riley_bee 0 of 33 ever,
# natro_out_spirit_bear 0 of 19, natro_out_panda_bear 0 of 26 -- each walked
# again after every giver rest (run_farm `_giver_route_rests`, GIVER_MISS_FILE)
# for a prompt read that never came. Quarantined now AND no landing in at least
# NEVER_LANDED_AFTER verdicts of its whole history: a re-recorded route, a new
# timing or a ROUTE_REVISIONS label empties the window (`watch_steps`), which
# lifts the quarantine and so this, and the changed route gets its trials.
NEVER_LANDED_AFTER = 10

# THE ROUTE BOARD (var/route_board.json, the GUI's Fields tab): every route's
# last SKILL_WINDOW verdicts against the window before them, worst first,
# rewritten with the book after each trip (`SkillBook.save`). The plan's target
# is 98% landed; a ten-verdict window cannot tell 98% from 100%, so a route is
# FLAGGED -- named for a look, not quarantined -- under BOARD_FLAG_BELOW with at
# least BOARD_MIN_VERDICTS verdicts: two misses in ten, or one in five.
# ponytail: chosen, not measured; the choice itself is priced by `p_land`.
BOARD_FILE = "route_board.json"
BOARD_FLAG_BELOW = 0.9
BOARD_MIN_VERDICTS = 5

# HOW MANY THOMPSON DRAWS ESTIMATE THE CHANCE THAT AN EXPLORING CHOICE MADE
# THE CHOICE IT MADE (`p_chosen`, for judging a new rule from the ledger later:
# the game-AI plan #2, and https://vowpalwabbit.org/docs/vowpal_wabbit/python/
# latest/tutorials/off_policy_evaluation.html). 1,000 puts the estimate within
# one standard error of 0.016 at worst (sqrt(0.25 / 1000)).
EXPLORE_DRAWS = 1000

# THE OUTCOMES, and which of them the posterior counts. `unknown` is no
# verdict; `missed` is the cannon's, not the flight's (see `settle_trip`), and
# stays with run_farm's cannon record, whose grounding decides after a miss.
OUTCOMES = ("landed", "elsewhere", "unknown", "missed")
VERDICTS = ("landed", "elsewhere")

# WHAT A WALK HOME'S OUTCOME SAYS, in nav/journey.Journey.home's own words: the
# route landed on the pad, or it stopped short and Natro's closer along the
# row (act/hiverow, part of Natro's walk home) found it. "found by searching"
# is the search by sight, which is not the route's doing.
HOME_ROUTE_LANDED = ("the route home landed on the pad",
                     "the route home stopped short of the pad")
# A MISSED CANNON APPROACH, in act/routes.CANNON_MISS's words (spelled out
# here so the morning report can import this module without the vision
# stack), as a trip's reason carries them.
CANNON_MISS_WORDS = "never stood at the red cannon"
# A GATHER THAT ENDED OFF ITS FIELD, as a ledger row records it: the farm
# loop's go-home rung (brain/farm Rung.GO_HOME) on a pollen counter that had
# stopped rising (brain/farm FLAT_COUNTER) -- run_farm `ended_off_the_field`,
# after which the field's route home is not walked, because the character
# had wandered off it (DESIGN 8dx: from there it landed 0 times in 11).
# Spelled out for the same reason as CANNON_MISS_WORDS.
GO_HOME_RUNG = "go_home"
FLAT_COUNTER_WORDS = "the pollen counter has not risen"
# A TRIP THE OWNER TOOK THE CONTROLS FROM, in brain/farm's words as the row's
# `gather_ended` carries them; no route it ran has a verdict.
TOOK_OVER_WORDS = "did not travel: the owner took the controls"


def node(name: str | None) -> str | None:
    """A field-table name as a router node ("rose" -> "rose_field")."""
    return ROUTER_ALIASES.get(name, name) if name else name


def field_nodes(router) -> set:
    """The router nodes that are fields: every field has a Natro walk home
    (`natro_home_<field>`, 17 of them), and no errand does -- an errand's walk
    back is `natro_back_<place>`."""
    return {e.start for e in getattr(router, "edges", ())
            if str(e.name).startswith("natro_home_")}


def route_kind(name: str, fields) -> tuple[str | None, str]:
    """(kind, target) for a route name: "flight", "out", "home", "errand", or
    None for anything that is not a route this ledger judges (a gather pattern,
    an errand's walk back, BeeTuxMacro's routes)."""
    name = str(name or "")
    if name.startswith("natro_out_") and name.endswith("_via_red_cannon"):
        # AN ERRAND'S FLIGHT IS AN ERRAND, judged by the errand's own verdict
        # as its walk is. scripts/transpile_natro emits flights to the bears,
        # dispensers and boosters too, and classed as a field's flight their
        # verdicts found no run to judge: MEASURED 2026-09-27 00:33-00:35
        # (attempt 483) the Treat and Blueberry flights both ended "arrived, no
        # panel" and were booked `unknown`, which no quarantine ever counts.
        target = name[len("natro_out_"):-len("_via_red_cannon")]
        return ("flight" if target in fields else "errand"), target
    if name.startswith("natro_home_"):
        return "home", name[len("natro_home_"):]
    if name.startswith("natro_out_"):
        target = name[len("natro_out_"):]
        return ("out" if target in fields else "errand"), target
    return None, ""


def _at_least(landed: int, elsewhere: int, x: float) -> float:
    """P(p >= x) for p ~ Beta(landed + prior, elsewhere + prior). For integer
    a, b that is P(Binomial(a + b - 1, x) <= a - 1)."""
    a = int(landed) + PRIOR_LANDED
    b = int(elsewhere) + PRIOR_ELSEWHERE
    n = a + b - 1
    return float(sum(math.comb(n, k) * x ** k * (1.0 - x) ** (n - k)
                     for k in range(a)))


def _median(values) -> float | None:
    got = sorted(float(v) for v in values if v is not None)
    if not got:
        return None
    mid = len(got) // 2
    return got[mid] if len(got) % 2 else (got[mid - 1] + got[mid]) / 2.0


# HOW A TIMED WALK IS WALKED IS PART OF WHAT AN ERRAND'S VERDICTS MEASURED.
# 2: from 2026-09-27 a hold counts its studs at the movespeed factor as it is
# re-read, so a Haste taken mid-hold moves its end (act/routes
# `_odometer_deadline`); before it, an errand walk that met a Haste on the way
# overshot -- the Brown Bear walk missed its ladder 3 times of 3 that way. An
# errand is a small target (a machine, a bear), so its verdicts under the old
# timing say little about the walk now, and one quarantined under it (the
# Treat Dispenser's, 2 of its last 10) would never have been walked again:
# `watch_steps` starts an errand's window afresh once. A field is a big
# target and a walk home waited its buffs out, so theirs are kept.
ERRAND_WALK_TIMING = 2
# An errand that landed at least this share of its window keeps it across a
# change of ERRAND_WALK_TIMING (`watch_steps`).
ERRAND_KEEP_SHARE = 0.5
# AND THE WALKSPEED THE HOLDS WERE SIZED AT, for EVERY route. 2: move.walkspeed
# 28 -> 32.2 for the gifted Hasty Bee's +15% player movespeed (2026-10-09).
# From 10-07 20:05 every timed hold overshot ~15% -- errand walks 27/33 -> 7/45,
# fields' walks out and home quarantined on verdicts the speed made, not the
# route. A route that landed anyway keeps its window (ERRAND_KEEP_SHARE); the
# rest start afresh once.
WALK_GENERATION = 2


def _timing(kind: str) -> list:
    """What `steps_signature` mixes in for a route of `kind`."""
    return [ERRAND_WALK_TIMING if kind == "errand" else None, WALK_GENERATION]


def _older_timings(edge) -> set:
    """The same steps' signatures under every earlier timing."""
    old = {steps_signature(edge)} | {steps_signature(edge, t)
                                     for t in range(1, ERRAND_WALK_TIMING + 1)}
    return old | {steps_signature(edge, [t, g])
                  for t in (None, *range(1, ERRAND_WALK_TIMING + 1))
                  for g in range(1, WALK_GENERATION)}


# A FIX THAT IS NOT IN THE STEPS STILL MAKES A NEW SKILL. A route's verdict
# is "landed where it is named" -- read off the arrival panel -- so a misread
# panel books a walk that arrived as a miss. MEASURED 2026-10-12: Bucko Bee's
# walk lands (its prompt was on screen, raised over the HUD, in the misses:
# var/routes/attempt-832/833) but sat quarantined at 2 of 10 from the reader's
# misses, so the bot flew instead -- and the flight came down on sand by a wall
# (attempt-916), 0 of 3. A label here joins the signature, so the window
# starts afresh at even odds the way a re-recorded route's does.
ROUTE_REVISIONS = {
    "natro_out_bucko_bee": "two-line prompt read first (run_farm read_panel) 2026-10-12 22:40",
}


def steps_signature(edge, timing: int | None = None) -> str:
    """A short hash of a route's steps -- and, for an errand, of `timing`
    (ERRAND_WALK_TIMING) -- so a route re-recorded or re-transpiled, or walked
    a different way, starts its window afresh (`SkillBook.watch_steps`).
    ROUTE_REVISIONS joins it when the route has one."""
    steps = getattr(edge, "steps", None) or []
    body = steps if timing is None else {"steps": steps, "timing": timing}
    revision = ROUTE_REVISIONS.get(getattr(edge, "name", ""))
    if revision:
        body = {"body": body, "revision": revision}
    body = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]


@dataclass
class Skill:
    """One route's record."""
    route: str
    kind: str = ""
    target: str = ""
    landed: int = 0
    elsewhere: int = 0
    unknown: int = 0
    missed: int = 0
    # The last SKILL_WINDOW verdicts ("landed"/"elsewhere"), oldest first,
    # and the SKILL_WINDOW before them (the board's trend).
    recent: list = field(default_factory=list)
    before: list = field(default_factory=list)
    # Seconds of its last SKILL_WINDOW landed runs, and of its last failed
    # ones. A run with no verdict (a stop, a mob, a missed cannon) is not
    # timed: how long it ran says nothing about how long the route takes.
    seconds: list = field(default_factory=list)
    fail_seconds: list = field(default_factory=list)
    last_at: float = 0.0
    # The steps its window was measured under, None when not known (history
    # folded from rows that predate this ledger), and when that window began.
    steps: str | None = None
    window_since: float = 0.0

    def add(self, outcome: str, seconds=None, at: float = 0.0) -> None:
        if outcome not in OUTCOMES:
            outcome = "unknown"
        setattr(self, outcome, getattr(self, outcome) + 1)
        if outcome in VERDICTS:
            grown = self.recent + [outcome]
            self.before = (self.before + grown[:-SKILL_WINDOW])[-SKILL_WINDOW:]
            self.recent = grown[-SKILL_WINDOW:]
        if seconds is not None and float(seconds) > 0:
            if outcome == "landed":
                self.seconds = (self.seconds
                                + [round(float(seconds), 2)])[-SKILL_WINDOW:]
            elif outcome == "elsewhere":
                self.fail_seconds = (self.fail_seconds
                                     + [round(float(seconds), 2)])[-SKILL_WINDOW:]
        self.last_at = max(self.last_at, float(at or 0.0))

    @property
    def window(self) -> tuple[int, int]:
        """(landed, elsewhere) over the recent window."""
        good = sum(1 for v in self.recent if v == "landed")
        return good, len(self.recent) - good

    @property
    def p_land(self) -> float:
        """The posterior mean over the window, the prior's 0.5 with none."""
        good, bad = self.window
        return (good + PRIOR_LANDED) / (good + bad + PRIOR_LANDED + PRIOR_ELSEWHERE)

    def sure_below(self, x: float = QUARANTINE_BELOW) -> float:
        """How sure the posterior is that the route lands under `x`."""
        good, bad = self.window
        return 1.0 - _at_least(good, bad, x)

    @property
    def quarantined(self) -> bool:
        return self.sure_below() >= QUARANTINE_SURE

    @property
    def never_lands(self) -> bool:
        """Quarantined, and not one landing in NEVER_LANDED_AFTER or more
        verdicts ever (NEVER_LANDED_AFTER)."""
        return self.quarantined and self.landed == 0 and self.elsewhere >= NEVER_LANDED_AFTER

    def draw(self, rng: random.Random) -> float:
        """One Thompson draw of its landing rate."""
        good, bad = self.window
        return rng.betavariate(good + PRIOR_LANDED, bad + PRIOR_ELSEWHERE)

    @property
    def median_seconds(self) -> float | None:
        """How long a landed run takes; how long any judged run took when it
        has never landed."""
        return _median(self.seconds) or _median(self.seconds + self.fail_seconds)

    @property
    def failure_seconds(self) -> float | None:
        return _median(self.fail_seconds)

    def record(self) -> str:
        """"landed 3 of its last 10 (P 0.33)", or that nothing has been judged."""
        good, bad = self.window
        if not good + bad:
            return "never judged yet (even odds)"
        return (f"landed {good} of its last {good + bad} "
                f"(P {self.p_land:.2f}"
                + (", quarantined" if self.quarantined else "") + ")")

    def as_dict(self) -> dict:
        return {"kind": self.kind, "target": self.target,
                "landed": self.landed, "elsewhere": self.elsewhere,
                "unknown": self.unknown, "missed": self.missed,
                "recent": list(self.recent), "before": list(self.before),
                "seconds": list(self.seconds),
                "fail_seconds": list(self.fail_seconds),
                "last_at": self.last_at, "steps": self.steps,
                "window_since": self.window_since}

    @classmethod
    def from_dict(cls, route: str, body: dict) -> "Skill":
        skill = cls(route=route)
        for key in ("kind", "target", "steps"):
            if body.get(key) is not None:
                setattr(skill, key, str(body[key]))
        for key in ("landed", "elsewhere", "unknown", "missed"):
            setattr(skill, key, int(body.get(key, 0) or 0))
        skill.recent = [v for v in (body.get("recent") or []) if v in VERDICTS]
        skill.before = [v for v in (body.get("before") or []) if v in VERDICTS]
        skill.seconds = [float(v) for v in (body.get("seconds") or [])]
        skill.fail_seconds = [float(v) for v in (body.get("fail_seconds") or [])]
        skill.last_at = float(body.get("last_at", 0.0) or 0.0)
        skill.window_since = float(body.get("window_since", 0.0) or 0.0)
        return skill


@dataclass
class RouteChoice:
    """Which route out was taken, from which candidates, and how surely."""
    route: str
    p: float = 1.0                        # the chance this rule picked it
    explored: bool = False                # a Thompson draw, not the mean
    candidates: list = field(default_factory=list)
    why: str = ""

    def as_dict(self) -> dict:
        return {"chosen": self.route, "p": round(self.p, 3),
                "explored": self.explored, "candidates": self.candidates,
                "why": self.why}


class SkillBook:
    """Every route's record, folded from the trip ledger."""

    def __init__(self, path: Path | str | None = SKILL_FILE):
        self.path = Path(path) if path is not None else None
        self.routes: dict[str, Skill] = {}
        self.folded_to = 0.0          # `at` of the last ledger row folded in
        self.built = ""               # how this book came to be, for the log

    # ---- persistence -----------------------------------------------------
    def load(self) -> bool:
        """True when a book made under these RULES was read."""
        if self.path is None:
            return False
        try:
            body = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return False
        if not isinstance(body, dict) or body.get("rules") != RULES:
            return False
        self.routes = {name: Skill.from_dict(name, row)
                       for name, row in (body.get("routes") or {}).items()
                       if isinstance(row, dict)}
        self.folded_to = float(body.get("folded_to", 0.0) or 0.0)
        self.built = str(body.get("built", "") or "")
        return True

    def save(self) -> None:
        """Atomic, and never raises into the farm loop."""
        if self.path is None:
            return
        try:
            atomic_write(self.path, json.dumps(
                {"rules": RULES, "window": SKILL_WINDOW,
                 "folded_to": self.folded_to, "built": self.built,
                 "saved_at": time.time(),
                 "routes": {name: s.as_dict()
                            for name, s in sorted(self.routes.items())}},
                indent=1))
            atomic_write(self.path.with_name(BOARD_FILE), json.dumps(
                {"saved_at": time.time(), "window": SKILL_WINDOW,
                 "flag_below": BOARD_FLAG_BELOW, "min_verdicts": BOARD_MIN_VERDICTS,
                 "routes": self.board()}, indent=1))
        except OSError:
            pass

    # ---- folding ---------------------------------------------------------
    def skill(self, route: str, kind: str = "", target: str = "") -> Skill:
        got = self.routes.get(route)
        if got is None:
            got = self.routes[route] = Skill(route=route, kind=kind, target=target)
        if kind and not got.kind:
            got.kind, got.target = kind, target
        return got

    def fold_items(self, items, at: float = 0.0) -> list:
        """Add one trip's route outcomes (`settle_trip`'s list)."""
        done = []
        for item in items or ():
            if not isinstance(item, dict) or not item.get("route"):
                continue
            skill = self.skill(str(item["route"]), str(item.get("kind") or ""),
                               str(item.get("target") or ""))
            skill.add(str(item.get("outcome") or "unknown"),
                      item.get("seconds"), at)
            done.append(skill)
        return done

    def fold(self, row: dict) -> list:
        """One ledger row that carries `routes`."""
        at = float(row.get("at") or 0.0)
        done = self.fold_items(row.get("routes"), at)
        self.folded_to = max(self.folded_to, at)
        return done

    def watch_steps(self, router) -> list[str]:
        """Start a route's window afresh when its steps are not the ones the
        window was measured under -- a re-recorded or re-transpiled route is a
        different skill (the same rule as the red cannon's record, run_farm
        `_load_cannon_record`). History folded from rows that predate this
        ledger has no signature, so it is adopted as the current one: nothing
        says which steps those runs walked. Returns what changed, to be said."""
        said = []
        for edge in getattr(router, "edges", ()):
            skill = self.routes.get(edge.name)
            if skill is None:
                continue
            sig = steps_signature(edge, _timing(skill.kind))
            if skill.steps is None:
                skill.steps = sig
            elif skill.steps != sig:
                good, bad = skill.window
                timing = skill.steps in _older_timings(edge)
                # ONE THAT LANDS KEEPS ITS RECORD (ERRAND_WALK_TIMING): the new
                # timing only mends a walk that a buff threw off, so it is no
                # reason to forget a walk that was landing anyway.
                if timing and good + bad and good >= ERRAND_KEEP_SHARE * (good + bad):
                    skill.steps = sig
                    continue
                what = ("the way its timed holds are walked changed"
                        if timing else "its steps changed")
                said.append(f"{edge.name}: {what} since its last "
                            f"{good + bad} verdict(s) ({good} landed) — its "
                            f"window starts afresh at even odds")
                skill.steps, skill.recent, skill.before = sig, [], []
                skill.seconds, skill.fail_seconds = [], []
                skill.window_since = time.time()
        return said

    # ---- what is known ---------------------------------------------------
    def get(self, route: str) -> Skill | None:
        return self.routes.get(route)

    def p_land(self, route: str) -> float | None:
        """The posterior mean, or None when the window holds no verdict."""
        skill = self.routes.get(route)
        if skill is None or not skill.recent:
            return None
        return skill.p_land

    def quarantined(self, route: str) -> bool:
        skill = self.routes.get(route)
        return bool(skill is not None and skill.quarantined)

    def quarantine_list(self) -> list[Skill]:
        return sorted((s for s in self.routes.values() if s.quarantined),
                      key=lambda s: (s.kind, s.route))

    def edge_cost(self, route: str, studs: float, *, walkspeed: float,
                  recovery_seconds: float, p: float | None = None,
                  evidence_only: bool = False) -> float | None:
        """length / P(land) + (1 - P(land)) x failure cost, in studs.

        THE LENGTH IS WHAT THE ROUTE MEASURABLY TAKES, walked at `walkspeed`:
        the median seconds of its landed runs (`median_seconds`), and its
        recorded `studs` only until it has any. A flight's recorded studs leave
        the flight out -- the trap nav.router.natro_route describes in
        BeeTuxMacro's cannon routes -- and MEASURED over the saved route frames
        the Pine Tree flight's 286.7 studs take a median 18 s (504 at 28
        studs/s), the walk's 1,050 a median 45 s (1,260).

        The failure cost is the median seconds of its last failed runs (its
        length when none failed) plus `recovery_seconds` -- the caller's
        measured cost of getting back to try again -- walked the same way.
        `p` overrides the posterior mean (a Thompson draw). None with
        `evidence_only` and no verdict in the window: "no opinion"."""
        skill = self.routes.get(route)
        if evidence_only and (skill is None or not skill.recent):
            return None
        speed = max(1.0, float(walkspeed))
        if p is None:
            p = skill.p_land if skill is not None else (
                PRIOR_LANDED / (PRIOR_LANDED + PRIOR_ELSEWHERE))
        took = skill.median_seconds if skill is not None else None
        length = float(took) * speed if took else float(studs)
        fail = skill.failure_seconds if skill is not None else None
        if fail is None:
            fail = length / speed
        failure_studs = (float(fail) + float(recovery_seconds)) * speed
        return length / max(float(p), 1e-6) + (1.0 - float(p)) * failure_studs

    def choose(self, candidates, *, walkspeed: float, recovery_seconds: float,
               explore: bool = False, rng: random.Random | None = None,
               labels: dict | None = None) -> RouteChoice | None:
        """The cheapest of `candidates` [(route, studs)] by `edge_cost`.

        A quarantined route is left out while another candidate is not. With
        `explore` (the caller's empty bag) each candidate's landing rate is one
        Thompson draw from its posterior instead of the mean, and `p` is how
        often that rule picks the route it picked (EXPLORE_DRAWS draws);
        without it the choice is the mean's and `p` is 1."""
        rows = []
        for route, studs in candidates or ():
            skill = self.routes.get(route) or Skill(route=route)
            rows.append({"route": route, "studs": round(float(studs), 1),
                         "p_land": round(skill.p_land, 3),
                         "window": list(skill.window),
                         "quarantined": skill.quarantined,
                         "cost": round(self.edge_cost(
                             route, studs, walkspeed=walkspeed,
                             recovery_seconds=recovery_seconds), 1),
                         "record": skill.record()})
        if not rows:
            return None
        usable = [r for r in rows if not r["quarantined"]] or rows
        by_mean = min(usable, key=lambda r: (r["cost"], r["route"]))
        if not explore or len(usable) < 2:
            chosen, p = by_mean, 1.0
        else:
            rng = rng or random.Random()

            def one_draw(source: random.Random) -> dict:
                return min(usable, key=lambda r: (self.edge_cost(
                    r["route"], r["studs"], walkspeed=walkspeed,
                    recovery_seconds=recovery_seconds,
                    p=(self.routes.get(r["route"]) or Skill(route=r["route"]))
                    .draw(source)), r["route"]))

            chosen = one_draw(rng)
            sim = random.Random(rng.random())
            wins = sum(1 for _ in range(EXPLORE_DRAWS)
                       if one_draw(sim)["route"] == chosen["route"])
            p = wins / float(EXPLORE_DRAWS)
        names = labels or {}
        parts = [f"{names.get(r['route'], r['route'])} {r['record']}, "
                 f"{r['cost']:,.0f} stud-equivalents" for r in rows]
        why = "; ".join(parts)
        if explore and len(usable) > 1:
            why += (f" — the bag is empty, so the choice is a draw from each "
                    f"route's record: this one wins {p:.0%} of draws")
        return RouteChoice(route=chosen["route"], p=p,
                           explored=bool(explore and len(usable) > 1),
                           candidates=rows, why=why)

    def board(self) -> list[dict]:
        """Every route with a verdict in its window: its landed share now and
        over the window before (`trend`, None without one), flagged under
        BOARD_FLAG_BELOW with BOARD_MIN_VERDICTS; flagged first, then worst
        share, then the most verdicts."""
        rows = []
        for s in self.routes.values():
            good, bad = s.window
            if not good + bad:
                continue
            rate = good / float(good + bad)
            was = (s.before.count("landed") / float(len(s.before))
                   if s.before else None)
            rows.append({"route": s.route, "kind": s.kind, "target": s.target,
                         "landed": good, "verdicts": good + bad,
                         "rate": round(rate, 3),
                         "before": round(was, 3) if was is not None else None,
                         "trend": round(rate - was, 3) if was is not None else None,
                         "flagged": (good + bad >= BOARD_MIN_VERDICTS
                                     and rate < BOARD_FLAG_BELOW),
                         "quarantined": s.quarantined, "last_at": s.last_at})
        return sorted(rows, key=lambda r: (not r["flagged"], r["rate"],
                                           -r["verdicts"], r["route"]))

    def table(self) -> list[dict]:
        """Every route, worst posterior first within each kind."""
        order = {"out": 0, "flight": 1, "home": 2, "errand": 3}
        out = []
        for s in self.routes.values():
            good, bad = s.window
            out.append({"route": s.route, "kind": s.kind, "target": s.target,
                        "landed": s.landed, "elsewhere": s.elsewhere,
                        "unknown": s.unknown, "missed": s.missed,
                        "window": (good, bad), "p_land": s.p_land,
                        "sure_below": s.sure_below(),
                        "quarantined": s.quarantined,
                        "median_s": s.median_seconds,
                        "fail_s": s.failure_seconds})
        return sorted(out, key=lambda r: (order.get(r["kind"], 9), r["target"],
                                          r["route"]))


# ---- one trip's routes, judged -------------------------------------------
def landing(target: str, credited: str | None) -> str:
    """What the reward feed says a route out to `target` did."""
    if not credited:
        return "unknown"
    return "landed" if node(credited) == node(target) else "elsewhere"


def home_outcome(ok: bool, reason: str) -> str:
    """A walk home's verdict on its ROUTE, from nav/journey.Journey.home."""
    if not ok:
        return "elsewhere"
    return ("landed" if any(str(reason or "").startswith(words)
                            for words in HOME_ROUTE_LANDED) else "elsewhere")


def settle_trip(runs, *, aim: str | None, credited: str | None,
                missed_at_cannon: bool = False, homes=(),
                errands=(), fields=(), travel_runs: int | None = None,
                reached_no_field: bool = False) -> list[dict]:
    """What each route a trip ran did, one dict per run, in run order.

    `runs` [{"route", "seconds"}] is every route the trip walked (the farm's
    RouteRunner tells them as they end). The rules, the same live and for the
    history (`rebuild`):

      * the LAST run out to the aimed field is judged by the feed's credit
        (`landing`); a flight is judged only when it flew. `credited` is the
        aim whenever the feed named the aim at all after the route ended --
        run_farm's `landed_elsewhere` rule, "the edge of the field, not a
        mis-delivery" -- and otherwise the field it named last: a route that
        delivered and whose gather pattern then walked over the border
        delivered (the caller's `aim_seen`, `infer_trip`'s `aim_named`);
      * a run out that one of its own `check:` steps stopped ("failed_check",
        DESIGN 8dk/8dr: "this walk has gone wide of it") landed elsewhere,
        whatever the trip did next -- the route said so itself -- when it was
        the journey's last run of that route. MEASURED: attempts 438, 439 and
        440 each stopped the Strawberry walk at leg 3 and retried it from
        where the first run stopped ("this route starts at the hive, we are
        not at the hive"), and the retry stopped at leg 3 again; one trip, one
        verdict, as for any retry below;
      * a flight followed by a walk to the same field missed at the cannon
        (nav/journey's fall-back, DESIGN 8de), and so did a flight that was the
        last run when the trip's reason names the miss (`missed_at_cannon`);
      * an earlier run of the same route is a retry -- the journey retried it
        after a mob cut it -- and has no verdict of its own;
      * only the first `travel_runs` runs can be the trip's way out (the
        farm counts them as its journey ends); a field route walked after
        that -- a bug run's, after the convert (act/bugrun, DESIGN 8do) -- is
        not judged here. None, for the history, puts no limit;
      * a last run out whose trip REACHED NO FIELD -- the pattern walked,
        nothing collected, the feed silent (`reached_no_field`, brain
        /fieldnotes.trip_arrived False) -- landed elsewhere: it delivered the
        character nowhere a flower grows. The feed's silence alone stays
        "unknown". MEASURED 2026-09-27 13:20 (attempt 499): the Clover walk
        ended against the log fence, 231 s and 22 passes gathered 0 pollen,
        the field's travel_failures rose -- and the route stayed "never judged
        yet", so the next trip drew the same walk again over the flight;
      * a walk home by its entry in `homes` [{"routes", "outcome"}]
        (`home_outcome`) -- the caller gives one only for a walk that began
        where the feed placed it, so a walk home from a place nothing named
        has no verdict -- and an errand by its entry in `errands`
        [{"route", "outcome"}]: each entry judges the first run of its route
        not yet judged, in order. A verdict with no run to judge is dropped:
        nothing walked it (already on the pad, a route that would not start).
    """
    aim_node = node(aim)
    kinds = [route_kind(r.get("route"), fields) for r in runs or ()]
    limit = len(kinds) if travel_runs is None else int(travel_runs)
    outs = [i for i, (k, t) in enumerate(kinds)
            if k in ("out", "flight") and t == aim_node and i < limit]
    last_out = outs[-1] if outs else None
    pending = [dict(e) for e in errands or () if isinstance(e, dict)]
    home_left = [dict(e) for e in homes or () if isinstance(e, dict)]
    out = []
    for i, run in enumerate(runs or ()):
        kind, target = kinds[i]
        if kind is None:
            continue
        outcome = "unknown"
        if kind in ("out", "flight") and target == aim_node and i < limit:
            later_walk = any(kinds[j] == ("out", target)
                             for j in range(i + 1, limit))
            retried = any(kinds[j] == kinds[i] for j in range(i + 1, limit))
            if kind == "flight" and later_walk:
                outcome = "missed"
            elif run.get("failed_check") and not retried:
                outcome = "elsewhere"
            elif i == last_out:
                outcome = ("missed" if kind == "flight" and missed_at_cannon
                           else landing(target, credited))
                if outcome == "unknown" and reached_no_field:
                    outcome = "elsewhere"
        elif kind == "home":
            for entry in home_left:
                if run.get("route") in (entry.get("routes") or ()) and not entry.get("_used"):
                    entry["_used"] = True
                    outcome = str(entry.get("outcome") or "unknown")
                    break
        elif kind == "errand":
            for entry in pending:
                if entry.get("route") == run.get("route") and not entry.get("_used"):
                    entry["_used"] = True
                    outcome = str(entry.get("outcome") or "unknown")
                    break
        seconds = run.get("seconds")
        out.append({"route": str(run.get("route")), "kind": kind,
                    "target": target, "outcome": outcome,
                    "seconds": (round(float(seconds), 2)
                                if seconds is not None else None)})
    return out


# ---- the history, for rows written before the ledger carried `routes` ------
FRAME = re.compile(r"^(\d{6})-(.+?)-(\d{2})(?:\.\d{2})?-(.*)\.jpg$")
CANNON_FRAME = re.compile(r"^(\d{6})-cannon-(.+)\.jpg$")
LOG_LINE = re.compile(r"^ +(\d\d):(\d\d):(\d\d)  (.*)$")
LOG_ROUTE = re.compile(r"\b(natro_(?:out|home)_[a-z_]+?): ")
# THE ERRANDS' OWN WORDS in the run logs (run_farm's learn_a_giver,
# learn_a_place, talk_to_a_giver and act/errands `Visit.describe`), the first
# after an errand's route began being its verdict. A place panel that does not
# name the place is a miss: the route stopped somewhere else (DESIGN 8bh).
# A talk (act/bearvisit `Talk.describe`, narrated before the dialogue is
# written down) landed once E was pressed at the giver's own prompt, which is
# the live verdict (`out.pressed`) whether or not a dialogue was read.
ERRAND_LANDED = re.compile(
    r"'s panel names it|: used it|: cooling down|dialogue is written to"
    r"|'s panel says '.*written to var/bear_panels"
    r"|: pressed E and no dialogue was read|and pressed E, no dialogue read"
    r"|^[a-z_]+: dialogue says|, then the dialogue says")
ERRAND_ELSEWHERE = re.compile(
    r"'s panel was not read|'s panel does not name it|'s panel read '.*not written"
    r"|, which is the HUD, not a prompt|: did not get there|: arrived, (?:panel read|no panel)"
    r"|did not reach the .* this time|no dialogue was read at the")
HOME_CUT = re.compile(r"cut this walk home from .* short")
# THE FEED NAMING A FIELD, as the run log prints it: vision/whereami's "I am in
# the <field> field (feed)" as a fix changes field, world/bearings' "I am in
# the <field> field (95% sure, feed, 8s ago) · ..." as its line changes -- the
# fix that many seconds before the line -- and run_farm `landed_elsewhere`'s
# "the feed says <here>, but it has named <aim> this trip too".
FEED_NAMED = re.compile(
    r"^I am in the ([a-z ]+?) field \((?:\d+% sure, )?feed(?:, (\d+)s ago)?\)")
FEED_NAMED_TOO = re.compile(
    r"^the feed says [a-z ]+?, but it has named ([a-z ]+?) this trip too")
# A RESPAWN ENDS WHAT THE ROUTE DELIVERED: the go-again respawn out of a
# mis-delivered field (run_farm `go_back_out`) or one to get home, after which
# no walk home runs and the live verdict is already fixed. MEASURED, attempt
# 452: the respawn out of Pumpkin was pressed at 15:57:46 and the feed named
# Pine Tree, the aim, at 15:57:49.
RESPAWNED = re.compile(r"^respawning \(|^respawned ")


def saved_runs(folder: Path) -> list[dict]:
    """Route runs from the frames RouteRunner saved (`<HHMMSS>-<route>-<step>-
    <op>.jpg`, var/routes/attempt-N), by file time: a `-00-start` frame begins a
    run, the cannon's own frames belong to the run they fell in."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    stamped = []
    for name in names:
        try:
            stamped.append((os.stat(os.path.join(folder, name)).st_mtime, name))
        except OSError:
            continue
    runs: list[dict] = []
    for mtime, name in sorted(stamped):
        got = FRAME.match(name)
        if got:
            route, step = got.group(2), int(got.group(3))
            if step == 0 or not runs or runs[-1]["route"] != route:
                runs.append({"route": route, "start": mtime, "end": mtime,
                             "cannon": []})
            runs[-1]["end"] = mtime
            continue
        got = CANNON_FRAME.match(name)
        if got and runs:
            runs[-1]["cannon"].append(got.group(2))
            runs[-1]["end"] = mtime
    for run in runs:
        run["seconds"] = round(run["end"] - run["start"], 2)
    return runs


def _file_times(folder: Path) -> list[float]:
    try:
        return sorted(os.stat(os.path.join(folder, n)).st_mtime
                      for n in os.listdir(folder))
    except OSError:
        return []


def _log_lines(path: Path) -> list[tuple[int, str]]:
    """(second of the day, text) for every stamped line of a run log."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                got = LOG_LINE.match(line.rstrip("\n"))
                if got:
                    h, m, s = int(got.group(1)), int(got.group(2)), int(got.group(3))
                    out.append((h * 3600 + m * 60 + s, got.group(4)))
    except OSError:
        pass
    return out


def _in_window(lines, start: float, end: float) -> list[tuple[float, str]]:
    """The stamped lines between `start` and `end`, on the absolute clock. A
    log line carries only its time of day, so the day is the one that puts it
    nearest the window."""
    local = time.localtime(start)
    midnight = time.mktime((local.tm_year, local.tm_mon, local.tm_mday,
                            0, 0, 0, 0, 0, -1))
    out = []
    for sod, text in lines:
        at = midnight + sod
        if at < start - 43200:
            at += 86400
        elif at > end + 43200:
            at -= 86400
        if start <= at <= end:
            out.append((at, text))
    return out


def infer_trip(row: dict, runs: list, lines, homing_times, fields) -> dict:
    """`settle_trip`'s arguments for a ledger row that predates `routes`, from
    its saved route frames (`runs`) and its run log (`lines`). With no frames,
    the routes the log names in its per-leg notes (`natro_out_cactus: a for 240
    studs: ...`), without their seconds. A walk home is judged by the first
    "to hive:" line after it, and a landing found by the search by sight (a
    var/homing frame between the route's end and that line) is not the
    route's. An errand by the first of its verdict lines.

    THE SAME EVIDENCE AS THE LIVE RULES WHERE THE LOG HAS IT. The route out is
    judged against the aim when the feed named it after the route ended and
    before the next route began or a respawn (`aim_named`, the live
    `aim_seen`); a walk home only when it is the route home from the field
    the row was credited -- where the feed placed the walk's start -- and the
    gather did not end off that field (`ended_off`, the live `off_field`);
    nothing for a trip the owner took the controls from."""
    end = float(row.get("at") or 0.0)
    start = end - float(row.get("seconds") or 0.0) - 60.0
    said = _in_window(lines, start, end + 5.0) if lines else []
    runs = [dict(r) for r in runs]
    if not runs:
        seen = []
        for at, text in said:
            for name in LOG_ROUTE.findall(text):
                if not route_kind(name, fields)[0]:
                    continue
                if seen and seen[-1]["route"] == name:
                    seen[-1]["end"] = at          # its last leg note so far
                else:
                    seen.append({"route": name, "start": at, "end": at,
                                 "seconds": None, "cannon": []})
        runs = seen
    reason = f"{row.get('reason') or ''} {row.get('gather_ended') or ''}"
    gather_ended = str(row.get("gather_ended") or "")
    took_over = gather_ended.startswith(TOOK_OVER_WORDS)
    recoveries = list(row.get("recoveries") or [])
    ended_off = bool(recoveries and recoveries[-1] == GO_HOME_RUNG
                     and gather_ended.startswith(FLAT_COUNTER_WORDS))
    credited_node = node(row.get("credited"))
    aim_node = node(row.get("aimed_at"))
    kinds = [route_kind(r["route"], fields) for r in runs]
    outs = [i for i, (k, t) in enumerate(kinds)
            if k in ("out", "flight") and t == aim_node]
    # ONLY ON A ROW THAT WAS CREDITED A FIELD: live, `aim_seen` is read where
    # the credit is (run_farm `at_my_hive`, as the walk home begins), and a
    # trip that never got there -- a stop, a death -- has neither. MEASURED:
    # without this, 9 Strawberry walks that ended "stop requested" would have
    # landed here and been unknown live.
    aim_named = False
    if outs and aim_node and credited_node:
        last = outs[-1]
        began = runs[last]["end"]
        until = runs[last + 1]["start"] if last + 1 < len(runs) else end + 5.0
        for at, text in said:
            if at < began - 1.0 or at > until:
                continue
            if RESPAWNED.search(text):
                break
            named = None
            got = FEED_NAMED.match(text)
            if got and at - float(got.group(2) or 0) >= began - 1.0:
                named = got.group(1)
            got = FEED_NAMED_TOO.match(text)
            if got:
                named = got.group(1)
            if named and node(named.replace(" ", "_")) == aim_node:
                aim_named = True
                break
    homes = []
    errands = []
    for i, run in enumerate(runs):
        kind, target = kinds[i]
        until = runs[i + 1]["start"] if i + 1 < len(runs) else end + 5.0
        after = [(at, text) for at, text in said if run["start"] - 1.0 <= at <= until]
        if kind in ("out", "flight"):
            # ITS OWN CHECK STOPPED IT: act/routes' "<route>: leg N <check>:
            # FAILED" line, or the journey's "did not get there — <route>:
            # <route> leg N: ..." that carries the check's words.
            run["failed_check"] = any(
                (text.startswith(f"{run['route']}: leg ") and ": FAILED" in text)
                or (f"{run['route']} leg " in text and "did not get there" in text)
                for _at, text in after)
        if kind == "home":
            verdict = "unknown"
            placed = bool(credited_node and credited_node == target and not ended_off)
            for at, text in (after if placed else ()):
                if HOME_CUT.search(text):
                    break
                if text.startswith("to hive: arrived"):
                    sight = any(run["end"] < t < at for t in homing_times)
                    verdict = "elsewhere" if sight else "landed"
                    break
                if text.startswith("to hive: did not get there"):
                    verdict = "elsewhere"
                    break
            homes.append({"routes": [run["route"]], "outcome": verdict})
        elif kind == "errand":
            verdict = "unknown"
            for _at, text in after:
                if ERRAND_ELSEWHERE.search(text):
                    verdict = "elsewhere"
                    break
                if ERRAND_LANDED.search(text):
                    verdict = "landed"
                    break
            errands.append({"route": run["route"], "outcome": verdict})
    return {"runs": runs, "aim": row.get("aimed_at"),
            "credited": (None if took_over else
                         row.get("aimed_at") if aim_named else row.get("credited")),
            "missed_at_cannon": CANNON_MISS_WORDS in reason,
            "homes": homes, "errands": errands, "fields": fields}


def ledger_rows(path: Path) -> list[dict]:
    """The trip ledger's rows, oldest first; a torn line is skipped."""
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("at") is not None:
                    rows.append(row)
    except OSError:
        pass
    return sorted(rows, key=lambda r: float(r.get("at") or 0.0))


def trips_with_routes(var_root: Path, fields, rows=None) -> list[tuple[dict, list]]:
    """Every ledger row with its settled `routes`: its own when it carries
    them, else inferred from var/routes, var/homing and var/night."""
    var_root = Path(var_root)
    rows = ledger_rows(var_root / "trips.jsonl") if rows is None else list(rows)
    by_attempt: dict = {}
    for i, row in enumerate(rows):
        by_attempt.setdefault(row.get("attempt"), []).append(i)
    assigned: dict = {}
    for attempt, idxs in by_attempt.items():
        if attempt is None or all("routes" in rows[i] for i in idxs):
            continue
        order = sorted(idxs, key=lambda i: float(rows[i]["at"]))
        for run in saved_runs(var_root / "routes" / f"attempt-{attempt}"):
            # A RUN BELONGS TO THE FIRST ROW WRITTEN AFTER IT BEGAN, when it
            # began inside that row's cycle: a row is written as its cycle ends,
            # and the next cycle's route out starts after it.
            for i in order:
                row_end = float(rows[i]["at"])
                if run["start"] < row_end:
                    if run["start"] >= row_end - float(rows[i].get("seconds") or 0.0) - 60.0:
                        assigned.setdefault(i, []).append(run)
                    break
    out = []
    lines_of: dict = {}
    for i, row in enumerate(rows):
        if isinstance(row.get("routes"), list):
            out.append((row, row["routes"]))
            continue
        attempt = row.get("attempt")
        if attempt not in lines_of:
            lines_of.clear()          # one log in memory at a time
            lines_of[attempt] = (_log_lines(var_root / "night" / f"run-{int(attempt):03d}.log")
                                 if isinstance(attempt, int) else [])
            lines_of["homing"] = _file_times(var_root / "homing" / f"attempt-{attempt}")
        args = infer_trip(row, assigned.get(i, []), lines_of[attempt],
                          lines_of["homing"], fields)
        out.append((row, settle_trip(**args)))
    return out


def live_against_history(var_root: Path, fields, rows=None) -> list[tuple]:
    """For every ledger row that carries its own `routes` -- the verdicts the
    live farm settled from what it saw -- the same trip settled again from its
    frames and run log as if it did not, paired run by run: [(row, the live
    item, the history's outcome, or None when the history found no such
    run)]. The two draw on different evidence (the notes' every attributed
    sample against the feed lines the log printed, a RouteResult's checks
    against its log lines, nav/journey's reason against the var/homing
    frames), so this is what says, once live rows exist, how far the history
    folded before them can be trusted (scripts/replay_skills.py prints it)."""
    var_root = Path(var_root)
    rows = ledger_rows(var_root / "trips.jsonl") if rows is None else list(rows)
    if not any(isinstance(r.get("routes"), list) for r in rows):
        return []
    bare = [{k: v for k, v in r.items() if k != "routes"} for r in rows]
    out = []
    for row, (_bare, inferred) in zip(rows, trips_with_routes(var_root, fields, rows=bare)):
        if not isinstance(row.get("routes"), list):
            continue
        left = list(inferred)
        for item in row["routes"]:
            match = next((x for x in left if x.get("route") == item.get("route")), None)
            if match is not None:
                left.remove(match)
            out.append((row, item, match["outcome"] if match else None))
    return out


def rebuild(var_root: Path, fields, *, rows=None,
            path: Path | str | None = None) -> SkillBook:
    """A book folded from the whole ledger (or `rows`), history included."""
    book = SkillBook(path)
    count = 0
    for row, items in trips_with_routes(var_root, fields, rows=rows):
        book.fold_items(items, at=float(row.get("at") or 0.0))
        book.folded_to = max(book.folded_to, float(row.get("at") or 0.0))
        count += 1
    book.built = (f"rebuilt {time.strftime('%Y-%m-%d %H:%M')} from {count} "
                  f"ledger row(s)")
    return book


def open_book(path: Path | str, var_root: Path, fields) -> tuple[SkillBook, str]:
    """The stored book, caught up with any ledger rows it has not folded; or,
    when there is none under these RULES, one rebuilt from the whole ledger.
    Returns the book and a sentence saying which."""
    book = SkillBook(path)
    if not book.load():
        book = rebuild(var_root, fields, path=path)
        book.save()
        return book, (f"{len(book.routes)} route(s) measured from the ledger's "
                      f"history ({book.built})")
    rows = [r for r in ledger_rows(Path(var_root) / "trips.jsonl")
            if float(r.get("at") or 0.0) > book.folded_to]
    if rows:
        for row, items in trips_with_routes(var_root, fields, rows=rows):
            book.fold_items(items, at=float(row.get("at") or 0.0))
            book.folded_to = max(book.folded_to, float(row.get("at") or 0.0))
        book.save()
    return book, (f"{len(book.routes)} route(s) measured"
                  + (f", {len(rows)} ledger row(s) caught up" if rows else ""))


def aimed_table(rows, min_gather: float = 30.0, raw: bool = False) -> dict:
    """The game-AI plan's table: gathering trips (over `min_gather` s of
    gathering) by the field aimed at, as [landed, somewhere else, never named].

    The feed's name is compared through ROUTER_ALIASES, so a trip aimed at
    "rose_field" (the name the aim carried before DESIGN 8ds) and credited
    "rose" landed. `raw` compares the names as written, which is how the plan
    counted them (its 45 of 150 includes those two Rose trips)."""
    table: dict = {}
    for row in rows:
        if float(row.get("gather_seconds") or 0.0) <= min_gather:
            continue
        aim = row.get("aimed_at")
        got = table.setdefault(aim, [0, 0, 0])
        credited = row.get("credited")
        if credited is None:
            got[2] += 1
        elif (credited == aim) if raw else (node(credited) == node(aim)):
            got[0] += 1
        else:
            got[1] += 1
    return table

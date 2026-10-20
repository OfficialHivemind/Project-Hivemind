"""Which token to go for, and whether to go at all: a score, not a script.

THE OWNER'S BRIEF, 2026-09-22: the token following was weak (poor, minimal
detection), and the bot should be a macro with eyes and a brain -- one that
scores what it sees rather than following a script.

WHAT THE OLD CHASE DID. `act/chase` took the nearest token above a confidence
gate, walked up to four steps at it, then reversed each leg blindly. No memory
of tokens between looks, no age, no notion of committing to a target, and a
detour every thirteen seconds that pulled the character off the flowers --
which is the drift that leaves the walk home starting from nowhere (DESIGN
8t). Nearest-first picks easy pollen and walks past the token that matters.

WHAT THIS DOES INSTEAD, a weighted-score chain:

  base weight     per token kind, seeded from data/knowledge/tokens.yaml's
                  `priority` -- an ORDERING, not a measured value
  x confidence    the tracker's match count: 0 matches x0, 1 match x0.5,
                  2+ x1.0 -- "two vision matches" confirm a token
  x distance      a walk-distance curve: a ceiling near the
                  character, a floor past a cutoff, linear between
  x staleness     a token not seen for a while decays toward nothing
  x cluster       x1.2 per neighbour within a radius, capped at x2.5 --
                  a group of tokens is worth walking to when one is not
  x reach         OURS, MEASURED: the share of this bot's own chases that
                  got to a token that far at that movespeed (REACH_BY_SPEED)
  x urgency       a token late in its kind's life goes first; with per-hive
                  weights and balloon preempts, look-only (WEIGHTS_LIVE)
  ELIGIBILITY     a track is gated out (not scored) when it is unconfirmed
                  and no high-value kind, or older than the field's expiry,
                  or -- for the farm -- not in the latest look (IN_VIEW_S)
  PICK            the highest eligible score wins -- IF it clears the bar
  COMMITMENT      once moving toward a token, keep it unless a challenger
                  scores at least MARGIN times more (seed x1.5)
  RETURN          returning to the anchor is itself a candidate whose score
                  RISES with distance from the anchor, so a token far from
                  home has to beat the pull of going back; and when nothing
                  clears the bar the answer is "return", never "wander"

WHAT IS A SEED AND WHAT IS MEASURED. The two-match confirmation, the x1.5
margin, the cluster bonus (~x1.2/neighbour, cap x2.5) and the return curve
(x50 near, x400 at 40 studs) are SEEDS -- reasonable starting values, not
measurements -- and named as such wherever they appear. Every number here is
either a seed (and says so), derived from our own measurement (and says so),
or an ordering rather than a claim (and says so). The seeds have not been
tuned against honey rate yet -- that is what the ledger and `Decision.trace`
are for.

WHAT IT CANNOT SEE YET. Most buffs. Melody and Baby Love percentages and Focus
stacks matter to a token's value; this bot reads only Haste
and the bear morphs (vision/buffs), which come to the scorer as one number,
`buffs["speed"]` -- the movespeed factor run_farm walks by. It feeds x reach
and nothing else (2026-10-14). With `gather.buff_icons` on (vision/bufficons,
look-only) `buffs` also carries `melody_pct`, `baby_love_pct` (0-100, None
when not up) and `focus_stacks`, read off every icon; no score uses them yet.

THE ANCHOR. The sprinkler is the natural home. Our gather pattern
(`farm_snake`, 24 steps) is symmetric -- MEASURED 2026-09-22: net
displacement per pass 0.0 studs -- so the pass's START is a natural anchor.
The scorer is told where that is on screen; the walk back to it is the
caller's job and must be done by looking (as homing does), not by reversing
legs, because reversing legs is the drift.

DISTANCES ARE IN SCREEN PIXELS, and this is a stated limitation. The ground
plane has never been calibrated on this account (nav/geometry says why), so
"studs" cannot be had honestly. The chase already reasons in pixels
(ARRIVED_PIXELS = 110); the distance curve's cutoff is expressed in the same
unit, calibrated to the reach the chase already treats as walkable.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping

# ---- base weights: an ORDERING seeded from tokens.yaml's priority -----------
# tokens.yaml ranks kinds by `priority` (lower first): tabby_love 1, scratch 2,
# most named kinds 10, the default 100, unknown last. That ordering is turned
# into a weight so the arithmetic below can multiply it. The gaps between the
# numbers are NOT measured -- they are chosen so that a priority-1 token beats a
# priority-10 token at moderate distance, and a priority-10 token beats an
# unknown at any distance the curve allows. Tuning these against honey is the
# ledger's job, not this file's.
WEIGHT_BY_PRIORITY = {1: 100.0, 2: 95.0, 10: 80.0, 100: 50.0}
# AN UNNAMED TOKEN IS MOSTLY AN ABILITY TOKEN, not junk: the coin detector finds
# coins, two matches confirm one and the school gates what it has seen do
# nothing -- what is left unnamed is a token whose glyph tokens.yaml cannot read
# yet (boosts, bombs, the blue bees' own). At 30 every honey token in view beat
# it at any distance, and the owner saw exactly that, 2026-10-07: it chased
# only honey tokens. 48 is as high as it goes while the owner's own first kinds
# still win from across the field (tabby_love at 545 px over an unknown at 140)
# and still take over from one at the x1.5 margin (tests/unit/test_tokenbrain);
# and the honey token -- a few hundred honey, the least of them -- now ranks
# with it (tokens.yaml), so distance decides between the two.
UNKNOWN_WEIGHT = 48.0
# BELOW AN UNNAMED COIN: a kind tokens.yaml ranks past 100, which is the honey
# token. MEASURED 2026-10-07 in the reward feed: "+891 Honey (from Dandelion
# Field)", "+855 Honey (from Pine Tree Forest)" -- +300 to +7,000 a token,
# about a tenth of a second of the test account's honey an hour -- while an
# unnamed coin is mostly an ability token (a boost, a bomb, haste, a link).
# At the same weight run-737 chased 29 honey to 19 others, and the owner
# noticed it chased only honey. At 36 an unnamed coin 120-170 px
# further off still wins; a quest that wants honey tokens ranks them first
# all the same (vision/tokens Kinds.want).
BELOW_UNKNOWN_WEIGHT = 36.0
# Kinds whose confirmed sighting may override an ordinary pick: a High Value
# tier with its own preemption; the owner's own priorities are the list: what
# tokens.yaml ranks first.
HIGH_VALUE_PRIORITY_AT_MOST = 2

# ---- the walk-distance curve, in our unit (screen px) -----------------------
# Seed: linear, near 8 studs, cutoff 40 studs, ceiling x1.25, floor x0.25.
# Ours keeps the shape and the multipliers. The px figures are calibrated to
# what the chase already treats as its reach: ARRIVED_PIXELS (110) is "here",
# and a 45-stud chase radius at STEP_SECONDS*walkspeed ~ 10 studs a step is
# the far edge of what four steps reach -- about 800 px at the current zoom
# (MEASURED on the live view: tokens chased at 400-800 px from the anchor).
NEAR_PX = 110.0
CUTOFF_PX = 800.0
# THE CHARACTER'S OWN BODY. MEASURED 2026-09-22 19:49-19:53 (runs 238-239):
# the brain chased "fuzz_bombs#10" at (941, 636), then (964, 635), then
# (941, 633); "triangulate#6" at (953, 630); "rain_cloud#38" at (951, 633) --
# blue token kinds, all within 40 px of the anchor at (960, 669), each
# "walked onto" and each still there at the next decision. That is the
# character's blue shirt, and the own-body pin (vision/pinned) had the head
# at (967, 551), 118 px above the anchor. Anything this close is either the
# character itself or a token the pattern's own movement collects without a
# detour; the chase would declare "arrived" without a step in any case
# (act/chase.ARRIVED_PIXELS is 110). Gated, so the decision is honest about
# why it holds.
#
# vision/tokens records that A DEAD ZONE IS NOT THE ANSWER to the own-bee
# problem: on a labelled field frame real tokens sat at 38, 159 and 188 px
# from the anchor, nearer than the bee's eyes. That measurement stands, and
# this gate is a different thing: it removes what the chase could never
# have walked to anyway (inside ARRIVED_PIXELS it declares arrival without a
# step), plus a 20 px margin for the torso. The own bee, which flies 55-160
# px out, is still `vision/pinned`'s job -- a spot that does not move while
# the world does -- and that filter runs BEFORE the brain sees anything.
SELF_PX = 130.0
# THE SCHOOL'S VERDICT. brain/school labels every chased crop by what the HUD
# did afterwards and, once it has enough of both kinds, says P(token) for a
# thing's appearance. Under this the brain does not chase it.
#
# 0.2 IS WHERE THE TRADE STOPS BEING WORTH IT, and it was measured rather than
# picked. The school became ready at 03:27 on 2026-09-23 with 43 `collected`
# and 76 `nothing` lessons; scoring every one of its own crops back gives a
# kNN over k=5, so the answers are quantised to fifths and the thresholds
# cluster:
#
#     gate   real tokens it would skip   junk chases it would save
#     0.20            2/43   ( 5%)              21/76  (28%)
#     0.30           13/43   (30%)              48/76  (63%)
#     0.50           26/43   (60%)              71/76  (93%)
#
# It shipped at 0.30, in the band that throws away three real tokens in ten.
# A chase costs at most four steps; a token is worth hundreds to thousands of
# honey, so skipping a real one is much the dearer mistake and the gate
# belongs where the false negatives nearly vanish. At 0.20 only a crop all
# five neighbours call junk is refused.
#
# These scores are optimistic -- every crop scored was also in the training
# set -- which is a further reason to sit at the cautious end.
SCHOOL_GATE_BELOW = 0.2
# ONLY WHAT THE LATEST LOOK SAW, when the caller asks (`in_view_s`). MEASURED
# 2026-10-01 by replaying the 60 recorded token incidents (var/incidents/
# *token*) through the farm's own pipeline -- detect at 0.7, the pin filter,
# the tracker carried by the flow, this brain: of 4,331 chase decisions,
# 3,267 went to a track the deciding look had NOT matched (remembered for up
# to GONE_AFTER_S), and the next frame held a sighting the chase could start
# on -- within act/chase.SAME_TOKEN_PX at 0.7 -- for 219 of them (7%), against
# 765 of the 1,064 the look had matched (72%). Live the same: run-550/551
# (2026-10-01), 61 of 67 chase decisions took no step. A remembered token is
# mostly one already collected, or one the carried position lost. Deciding
# only on the tracks the look matched -- scripts/replay_brain.py --in-view,
# which counts this -- the same 4,500 looks give 2,831 chase decisions and
# 2,035 of them startable (72%), against 796 of 4,331 (18%) without it: 2.6
# times the chases begun. So the farm gates the rest out rather than walking
# at a memory.
IN_VIEW_S = 0.0
DISTANCE_CEILING = 1.25
DISTANCE_FLOOR = 0.25

# ---- confidence from the tracker's match count (seed: two matches) ----------
CONFIDENCE_BY_MATCHES = {0: 0.0, 1: 0.5}

# ---- staleness: unseen tokens decay ------------------------------------------
# Full weight while seen within STALE_AFTER_S, then linear to nothing at
# GONE_AFTER_S. Ours: the tracker forgets at 4 s, so the curve lives inside it.
STALE_AFTER_S = 0.75
GONE_AFTER_S = 4.0

# ---- cluster bonus (a seed) ---------------------------------------------------
CLUSTER_RADIUS_PX = 260.0
CLUSTER_PER_NEIGHBOUR = 1.2
CLUSTER_CAP = 2.5

# ---- reach: how often OUR chase gets there (MEASURED, not a seed) -----------
# MEASURED 2026-10-14 (scripts/token_payoff.py over runs 820-999, after the
# gifted Hasty's walkspeed fix of 10-09): 4,654 walked chases, each joined to
# the buff bar's movespeed factor at the time ("walking 1.3x", "1.24x in
# all"). Share that "walked onto it", at the median px of each band:
#
#     px        215   313   402   492   596   709   830
#     <1.25x    .98   .94   .89   .78   .61   .31   .08    n 3,121
#     1.25-1.5  .98   .91   .81   .76   .49   .26   .08    n   848
#     >=1.5x    .93   .79   .67   .66   .39   .23   .00    n   685
#
# Stable across halves (runs 820-915 and 916-999 within ~5 points a cell). The
# detour takes 1.9 s near and 3.9-4.4 s at 650-800 px, so a far chase costs
# twice the time for a third of the reach. A linear curve (x distance)
# never sees the second half of that, nor the speed: under Haste x5
# and up a step (STEP_SECONDS, not divided by the factor) carries the
# character past its target and the re-find loses it. HUD-confirmed pickups
# (brain/school "collected", unnamed coins at <1.25x, runs 880-999) fall the
# same way: 48%, 31%, 35%, 21%, 0% at 130-300, -450, -600, -800, 800+ px. The
# 1.25-1.5x band's 830 px cell (3 of 14) and near cell (20 of 20) are taken
# at the slower band's figure.
# What it changes, replayed on runs 916-999 (the logged target's score times
# x reach; a nearer token now winning instead is not counted): 235 of 1,790
# chases score under the bar -- 836 s, 18% of the chasing and 2.5% of the 9.2
# h gathered, for 60 tokens reached (26%): 0.07 a second against 0.35 for
# the 1,555 chases kept.
# NOT FOR THE OWNER'S FIRST KINDS (HIGH_VALUE_PRIORITY_AT_MOST, a quest's
# included): every chase measured was a honey token or an unnamed coin, and
# those kinds keep winning from across the field (tests/unit/test_tokenbrain).
# "on"; "off" = x reach 1.0 for every token (the chain as before).
REACH = "on"
REACH_PX = (215, 313, 402, 492, 596, 709, 830)
REACH_BY_SPEED = (            # (movespeed factor below, reached share at REACH_PX)
    (1.25, (0.98, 0.94, 0.89, 0.78, 0.61, 0.31, 0.08)),
    (1.5, (0.98, 0.91, 0.81, 0.76, 0.49, 0.26, 0.08)),
    (math.inf, (0.93, 0.79, 0.67, 0.66, 0.39, 0.23, 0.0)),
)

# ---- commitment and the return candidate (seeds) -----------------------------
# A challenger must score this many times the committed target's live score.
INTERRUPT_MARGIN = 1.5
# Returning to the anchor competes with every token. Its score is a weight
# (RETURN_BASE) times a multiplier that rises with distance from the anchor:
# x50 near the anchor to x400 at RETURN_FAR_PX -- the seed is x50 -> x400 at 40
# studs. Below RETURN_NEAR_PX the return candidate is "already home" and
# scores nothing, so it never wins over a token when standing at the anchor.
RETURN_BASE = 1.0
RETURN_NEAR_PX = 110.0
RETURN_FAR_PX = 800.0
RETURN_MULT_NEAR = 50.0
RETURN_MULT_FAR = 400.0
# The bar a token must clear to be worth leaving the anchor for at all
# (a "movement threshold", seed 10 in base-weight units).
MOVEMENT_THRESHOLD = 10.0
# GATES ONE MORE LOOK CAN LIFT: a token seen once (two matches confirm one)
# and a confirmed one the deciding look missed (IN_VIEW_S). A coin spins, a
# quarter turn in about 0.4 s (vision/coins), and edge-on the detector misses
# it -- MEASURED live 2026-10-07 20:38-20:43 (run-734): 64 holds, no chase,
# 17 of them on a token seen once or missed by the deciding look.
LOOK_AGAIN_GATES = ("seen once", "not in the latest look")


# GONE BEFORE WE GET THERE, LOOK-ONLY. A token lies on the field for its
# kind's `life_s` (tokens.yaml, wiki Module:Ability_Tokens/data: Blue Boost,
# Focus, Haste, Token Link 4 s; honey 10 s), and an unnamed one -- mostly this
# hive's Diamonds' Blue Boosts -- for `unknown_life_s`. A track already
# `age_s` old that needs the walk below to reach is gone on arrival when the
# sum passes it. MEASURED 2026-10-21 (runs 1130-1169, 1,269 chases that
# walked onto it and came home by sight, timestamps to the second): choice to
# result = 0.42 s + 0.44 s a step (least squares over outward + homeward
# steps), median 2 out / 2 home, 351 px at the choice -> outward median
# 0.9 s, 496 px/s (unknown 474, honey 518; quarter-percentile 352).
# ponytail: one median for every walkspeed and field; refit per walkspeed
# (scripts/token_payoff.py has the buff join) if the gate goes live.
# CHASE_PX_PER_S ignores Haste.
CHASE_START_S = 0.42
CHASE_PX_PER_S = 480.0
# A TRACK OUTLIVES ITS TOKEN, so the rule above waits for TRACK_LIFE_FACTOR x
# `life_s` of track age. `age` counts from the track's first_seen
# (vision/tracks), and a new token landing within MATCH_PX of a gone one inside
# FORGET_AFTER takes over its track and its age. MEASURED 2026-10-27:
#   frames: 170 saved 150-frame token bursts (var/incidents/*token*, ~14 fps),
#     tracked strictly frame to frame: an uncensored Blue Boost is in view
#     first to last p95 3.8 s, max 5.1 s (n 173, detections >= 0.6; p95
#     3.6-4.2 s, max 5.1-7.2 s at 0-0.9) -- the wiki's 4 s holds. The
#     farm's own Tracker on the same frames keeps 53 Blue Boost tracks past
#     4 s, and 44 of them hold a stretch of 1.5 s+ with nothing at their spot.
#   logs: on 26-27 Oct 11 track ids changed kind mid-life (an unknown turning
#     honey, a honey turning black_blue_burst), and at 1 x `life_s` the rule's
#     skips were picked up like any chase -- runs 1200-1257, 4 s kinds: walked
#     onto 82% (kept chases 87%), HUD-confirmed 24% (32%); HUD pickups at track
#     age + walk up to 7.3 s (4 s kinds) and 18.8 s (honey) in runs 1092-1248;
#     past 2 x there the misses rise: 3 of 10 (12% for kept chases).
# Re-scored by tools/analysis/lifetime_gate.py: at x2 runs 1249-1256 (the
# night of 26-27 Oct, not used to pick it) would skip 2 chases (1
# HUD-confirmed) where both rules skipped 259 (34).
# ponytail: one factor for every kind; a track age that restarts when its
# token is replaced (vision/tracks) is the real fix, and needs a look cadence
# that can see the gap.
TRACK_LIFE_FACTOR = 2.0
# False: the rule above only adds `would_gate` to a candidate, and run_farm
# logs "token brain would: skip ...". True: it gates it. (The honey leash that
# shared this flag is gone, 2026-10-27: 216 of the night's 259 would-skips,
# 191 of them walked onto and 23 HUD-confirmed; whether a far honey token is
# worth the detour is the value chooser's question -- VALUE_CHOOSER below --
# and the simulator found dropping those chases loses honey,
# docs/pending/simulator.md.)
LIFETIME_GATE_LIVE = False

# PER-HIVE WEIGHTS, URGENCY AND BALLOON PREEMPTS, LOOK-ONLY (ROADMAP T2; the
# owner, 2026-10-07: it chased only honey tokens). Three changes to which
# token is walked to:
#   hive weight   tokens.yaml `weight_by_hive[hive]` replaces the ordering's
#                 weight for that kind (vision/tokens Kinds.weight): a blue
#                 hive's honey token 0, ASSUMED until the honey arm
#                 (brain/arms HONEY_WEIGHT) has measured it on this account
#   x urgency     1 at first sight, rising to 1 + URGENCY_GAIN at the end of
#                 its kind's `life_s`: the token that will not be there at the
#                 next pass goes first. Only for one the walk reaches inside
#                 its life (CHASE_START_S, CHASE_PX_PER_S above); past that the
#                 track's age says nothing about the token (urgency_multiplier).
#   preempt       an eligible token of a kind with `preempt_px` (tokens.yaml:
#                 the balloon tokens) that close wins over everything, the
#                 committed target too.
# False: the decision is the old one; `Decision.would` says what these would
# have picked when that differs, and run_farm logs "token brain weights
# would: ...". True: they decide.
WEIGHTS_LIVE = False
# ASSUMED, a seed: x1 -> x2 over a kind's life. `age` counts from the track's
# first_seen (vision/tracks), not the token's spawn, so a token first seen late
# in its life looks younger than it is and gets less urgency than it should.
URGENCY_GAIN = 1.0

# A COLOUR TOKEN IS WORTH ONLY THE FLOWERS OF ITS COLOUR UNDER IT. Wiki
# Module:Ability_Tokens/data (read 2026-10-27): Blue Boost "Grants +20% pollen
# from Blue flowers for 15s", Red/White Boost the same for theirs; Blue Bomb
# "Collects 10 pollen from 13 surrounding Blue flowers" (Powers Red 0, White
# 0), Red Bomb the same for red. The typed head's black_*_burst are those
# bombs: MEASURED by eye, var/school-coins/crops-wide/142789897-2-1287-510.jpg
# (a black disc with a blue star burst, the wiki's AllBombs.png Blue Bomb,
# lying in Pepper's red flowers).
KIND_COLOUR = {"blue_boost": "blue", "red_boost": "red", "white_boost": "white",
               "black_blue_burst": "blue", "black_red_burst": "red"}
# x colour = the share of this field's pollen, for this hive, that comes off
# that colour's flowers: the wiki's flower shares (act/planter FIELD_COLOURS)
# weighted by how good the hive is at each colour (brain/decide COLOUR_WORTH
# for a blue hive, ASSUMED there; any other hive: the flower share alone).
# Pepper is 85% red, 15% white, 0 blue, so a blue boost or bomb there is x0.
# The field comes from the caller (`TokenBrain.field`); an unknown field, a
# colourless kind, or a quest's / the owner's first kinds: x1.
# SHADOW, because it did not measure better. MEASURED 2026-10-27, runs
# 1254-1258 (tools/analysis/field_colour.py, docs/pending/fieldcolour.md):
# every chase was in Pepper (Mountain Top trips do not chase), 325 of 674 at
# blue boosts / blue bombs. A detour there costs little: pollen the 30 s
# window's rate would have made over it, less what came in -- blue boost
# -1,410 a chase (95% CI -6,157..+3,515), blue bomb +5,165 (+437..+10,834),
# ~0.1 s of Pepper's ~10k/s on the mix -- because the bees keep gathering.
# Per trip (20 Pepper gathers) pollen/s does not fall with blue chases a
# minute: +240 a chase/min (CI -1,483..+1,905; other chases -605, CI
# -2,328..+1,180). And 27 of the 325 HUD verdicts were Haste (a misnamed or
# neighbouring token), which a gate would drop. The gain is the wiki's 0.
# False: x colour is only traced ("colour") and run_farm logs "token brain
# colour would: ..." for a x0 target; True: it scores ("x colour") and a x0
# kind is gated.
COLOUR_LIVE = False


def colour_why(kind: str, field: str | None) -> str:
    return (f"no {KIND_COLOUR.get(kind)} flowers in {str(field).replace('_', ' ')} "
            f"(wiki) -- a {kind} acts on nothing here")


def colour_would(decision: "Decision", field: str | None,
                 threshold: float = MOVEMENT_THRESHOLD) -> str:
    """COLOUR_LIVE off: what x colour would do with a chase whose target is
    x0 here, as the rest of a "token brain colour would: ..." line; "" when
    it changes nothing. Reads `decision.ranked` only.
    ponytail: the best other token by score x colour over the bar, with no
    commitment margin -- what a fresh decision would take."""
    t = decision.target
    if decision.action != "chase" or t is None or t.trace.get("colour", 1.0) > 0.0:
        return ""
    alt = max((c for c in decision.ranked if not c.gated and not c.is_return
               and c.track_id != t.track_id),
              key=lambda c: c.score * c.trace.get("colour", 1.0), default=None)
    s = alt.score * alt.trace.get("colour", 1.0) if alt is not None else 0.0
    instead = (f"chase {alt.kind}#{alt.track_id} at ({alt.x}, {alt.y}) ({s:.0f}) instead"
               if alt is not None and s >= threshold else "stay on the flowers")
    return f"skip {t.kind}#{t.track_id} at ({t.x}, {t.y}) -- {colour_why(t.kind, field)}; {instead}"


def colour_factor(kind: str, field: str | None, hive: str | None) -> float:
    """x colour: the share of `field`'s pollen (for `hive`) a `kind` acts on."""
    from ..act.planter import FIELD_COLOURS
    from .decide import COLOUR_WORTH
    colour, share = KIND_COLOUR.get(kind), FIELD_COLOURS.get(str(field or ""))
    if colour is None or not share:
        return 1.0
    worth = COLOUR_WORTH if hive == "blue" else {c: 1.0 for c in share}
    total = sum(s * worth.get(c, 0.0) for c, s in share.items())
    return share.get(colour, 0.0) * worth.get(colour, 0.0) / total if total > 0 else 1.0


@dataclass
class Candidate:
    """One scored option: a token track, or the return to the anchor."""
    kind: str
    score: float
    track_id: int | None = None
    x: int = 0
    y: int = 0
    gated: str = ""                  # non-empty means not eligible, and why
    would_gate: str = ""             # LIFETIME_GATE_LIVE off: the gate it would get
    trace: dict = field(default_factory=dict)

    @property
    def is_return(self) -> bool:
        return self.track_id is None

    def describe(self) -> str:
        if self.gated:
            return f"{self.kind}#{self.track_id}: GATED — {self.gated}"
        what = "return to anchor" if self.is_return else f"{self.kind}#{self.track_id}"
        parts = ", ".join(f"{k} {v}" for k, v in self.trace.items())
        return f"{what} {self.score:.1f} ({parts})"


@dataclass
class Decision:
    """What to do next, and the whole ranked list that decided it."""
    action: str                      # "chase", "return", "hold"
    target: Candidate | None
    ranked: list[Candidate]
    why: str
    would: str = ""                  # WEIGHTS_LIVE off: the pick they would make instead

    def describe(self) -> str:
        head = f"{self.action}"
        if self.target is not None and not self.target.is_return:
            head += f" {self.target.kind}#{self.target.track_id} at ({self.target.x}, {self.target.y})"
        return f"{head} — {self.why}"


def base_weight(kind: str, priority_of) -> float:
    """The starting weight for a kind, from tokens.yaml's priority ordering."""
    if kind == "unknown":
        return UNKNOWN_WEIGHT
    try:
        pri = int(priority_of(kind))
    except Exception:
        return UNKNOWN_WEIGHT
    if pri in WEIGHT_BY_PRIORITY:
        return WEIGHT_BY_PRIORITY[pri]
    # any other priority: interpolate on the ordering, never above the best
    if pri < 1:
        return WEIGHT_BY_PRIORITY[1]
    if pri > 100:
        return BELOW_UNKNOWN_WEIGHT
    lo = max(p for p in WEIGHT_BY_PRIORITY if p <= pri)
    hi = min(p for p in WEIGHT_BY_PRIORITY if p >= pri)
    if lo == hi:
        return WEIGHT_BY_PRIORITY[lo]
    f = (pri - lo) / (hi - lo)
    return WEIGHT_BY_PRIORITY[lo] + f * (WEIGHT_BY_PRIORITY[hi] - WEIGHT_BY_PRIORITY[lo])


def distance_multiplier(px: float) -> float:
    """The linear walk-distance curve, in screen pixels."""
    if px <= NEAR_PX:
        return DISTANCE_CEILING
    if px >= CUTOFF_PX:
        return DISTANCE_FLOOR
    f = (px - NEAR_PX) / (CUTOFF_PX - NEAR_PX)
    return DISTANCE_CEILING + f * (DISTANCE_FLOOR - DISTANCE_CEILING)


def staleness_multiplier(unseen_for: float) -> float:
    if unseen_for <= STALE_AFTER_S:
        return 1.0
    if unseen_for >= GONE_AFTER_S:
        return 0.0
    return 1.0 - (unseen_for - STALE_AFTER_S) / (GONE_AFTER_S - STALE_AFTER_S)


def cluster_multiplier(neighbours: int) -> float:
    return min(CLUSTER_CAP, CLUSTER_PER_NEIGHBOUR ** max(0, neighbours))


def reach_multiplier(px: float, speed: float | None = None) -> float:
    """REACH_BY_SPEED at this distance and movespeed factor, linear between
    the measured px, against the share reached near at no speed buff."""
    if REACH != "on":
        return 1.0
    s = 1.0 if speed is None else float(speed)
    shares = next(row for below, row in REACH_BY_SPEED if s < below)
    i = bisect.bisect_left(REACH_PX, px)
    if i == 0:
        v = shares[0]
    elif i == len(REACH_PX):
        v = shares[-1]
    else:
        f = (px - REACH_PX[i - 1]) / (REACH_PX[i] - REACH_PX[i - 1])
        v = shares[i - 1] + f * (shares[i] - shares[i - 1])
    return v / REACH_BY_SPEED[0][1][0]


def gone_on_arrival(age: float, life: float | None, dist: float) -> bool:
    """A track `age` old, `dist` px out, past TRACK_LIFE_FACTOR x its kind's
    `life` by the time the walk gets there. False with no life."""
    return bool(life) and age + CHASE_START_S + dist / CHASE_PX_PER_S > TRACK_LIFE_FACTOR * life


def urgency_multiplier(age: float, life: float | None, dist: float) -> float:
    """x urgency: 1 + URGENCY_GAIN x the share of its life a token has used,
    for one the walk reaches inside 1 x its life; 1 otherwise, or with no
    life.

    NOT PAST 1 x LIFE, though the gate waits for TRACK_LIFE_FACTOR: a track
    that old holds a token of unknown age, not one about to vanish. MEASURED
    2026-10-27: on our frames no token is in view longer than about its
    kind's life (tools/analysis/token_lifespans.py, docs/pending/lifespans.md:
    4 s kinds at most 2.8-4.0 s, honey 4.3 of its 10), and the chases whose
    age + walk passed 1 x life were reached and paid about like any other
    (runs 1200-1257, 4 s kinds: walked onto 82% vs 87%, HUD 24% vs 32%,
    docs/pending/lifetime.md) -- yet scored the most urgent of all, x2."""
    if not life or age + CHASE_START_S + dist / CHASE_PX_PER_S > life:
        return 1.0
    return 1.0 + URGENCY_GAIN * min(1.0, max(0.0, age) / life)


def return_score(distance_from_anchor_px: float) -> float:
    """How strongly going home pulls, rising with distance from the anchor."""
    if distance_from_anchor_px <= RETURN_NEAR_PX:
        return 0.0
    f = min(1.0, (distance_from_anchor_px - RETURN_NEAR_PX) / (RETURN_FAR_PX - RETURN_NEAR_PX))
    return RETURN_BASE * (RETURN_MULT_NEAR + f * (RETURN_MULT_FAR - RETURN_MULT_NEAR))


def worth_a_second_look(decision: Decision) -> bool:
    """A hold that one more look could turn into a chase (LOOK_AGAIN_GATES)."""
    return decision.action != "chase" and any(
        c.gated.startswith(LOOK_AGAIN_GATES) for c in decision.ranked)


class TokenBrain:
    """Scores what the tracker remembers and says what to do next."""

    def __init__(self, priority_of=None, *, life_of=None,
                 weight_of=None, preempt_of=None, own_of=None, off_of=None,
                 expiry_s: float | None = None,
                 margin: float = INTERRUPT_MARGIN,
                 threshold: float = MOVEMENT_THRESHOLD,
                 in_view_s: float | None = None, hive: str = ""):
        # `priority_of(kind) -> int`, tokens.yaml's ordering; default: everything unknown
        self.priority_of = priority_of or (lambda kind: 100)
        # `life_of(kind) -> seconds | None`, tokens.yaml's `life_s`
        # (vision/tokens Kinds.life_s); None: no lifetime rule
        self.life_of = life_of
        # `weight_of(kind) -> weight | None`: tokens.yaml `weight_by_hive` for
        # this hive (vision/tokens Kinds.weight); `preempt_of(kind) -> px |
        # None`: its `preempt_px`. Both under WEIGHTS_LIVE.
        self.weight_of = weight_of
        self.preempt_of = preempt_of
        # THE PLAYER'S OWN TABLE (setting gather.token_priority, vision/tokens
        # Kinds.own_weight / is_off): `own_of(kind) -> weight | None` beats
        # every other weight; `off_of(kind) -> bool` gates the kind out. Not
        # under WEIGHTS_LIVE: the player chose these, and with no rows (the
        # default) both say nothing and the decision is the built-in one.
        self.own_of = own_of
        self.off_of = off_of
        # {kind: weight} for this trip from an experiment arm (brain/arms
        # HONEY_WEIGHT, set only while ARMS_LIVE): beats every other weight
        # but the player's own.
        self.weights: dict = {}
        # Token lifetime on the field, if MEASURED for this account. None means
        # unknown, and no urgency or expiry gate is applied -- a guessed expiry
        # would gate out real tokens.
        self.expiry_s = expiry_s
        # Unseen longer than this before `now` is gated out (IN_VIEW_S); None
        # leaves the staleness curve to judge remembered tracks.
        self.in_view_s = in_view_s
        # x colour (COLOUR_LIVE): the hive's colour, and the field this pass
        # gathers -- the caller sets `field` each decision; None: x1
        self.hive = str(hive or "")
        self.field: str | None = None
        self.margin = float(margin)
        self.threshold = float(threshold)
        self.committed: int | None = None       # track id being walked to
        self.decisions = 0
        self.interrupts = 0

    # ---- scoring ------------------------------------------------------------
    def score(self, tracks: Iterable, anchor: tuple[int, int], here: tuple[int, int],
              now: float, buffs: Mapping | None = None) -> list[Candidate]:
        """Every track scored or gated, plus the return candidate. Sorted best first."""
        tracks = list(tracks)
        hx, hy = here
        speed = (buffs or {}).get("speed")
        out: list[Candidate] = []
        for t in tracks:
            kind = str(getattr(t, "kind", "unknown") or "unknown")
            matches = int(getattr(t, "matches", 0) or 0)
            pri = self._priority(kind)
            high_value = pri <= HIGH_VALUE_PRIORITY_AT_MOST
            unseen = float(t.unseen_for(now)) if hasattr(t, "unseen_for") else 0.0
            age = float(t.age(now)) if hasattr(t, "age") else 0.0
            dist = math.hypot(t.x - hx, t.y - hy)
            neighbours = sum(1 for o in tracks if o is not t
                             and math.hypot(o.x - t.x, o.y - t.y) <= CLUSTER_RADIUS_PX)
            # ELIGIBILITY. Block beats allow, and a gate is not a low score.
            gated = ""
            school_p = getattr(t, "school_p", None)
            if dist <= SELF_PX:
                gated = (f"{dist:.0f} px from the character — its own body, or "
                         f"already under it")
            elif self._call(self.off_of, kind):
                gated = "turned off in your token priorities"
            elif school_p is not None and school_p < SCHOOL_GATE_BELOW:
                gated = (f"the school says P(token) {school_p:.2f} from what it "
                         f"has seen collected — a bee or a number, not a token")
            elif matches < 2 and not high_value:
                gated = "seen once; two matches confirm a token"
            elif self.in_view_s is not None and unseen > self.in_view_s:
                gated = (f"not in the latest look ({unseen:.1f}s unseen) — a "
                         f"remembered token is rarely still there")
            elif self.expiry_s is not None and age > self.expiry_s:
                gated = f"older than the measured {self.expiry_s:.0f}s lifetime"
            elif staleness_multiplier(unseen) <= 0.0:
                gated = f"not seen for {unseen:.1f}s"
            would = "" if gated or high_value else self._would_gate(kind, dist, age)
            if would and LIFETIME_GATE_LIVE:
                gated, would = would, ""
            w = self.base_for(kind)
            c = CONFIDENCE_BY_MATCHES.get(matches, 1.0)
            d = distance_multiplier(dist)
            s = staleness_multiplier(unseen)
            k = cluster_multiplier(neighbours)
            r = 1.0 if high_value else reach_multiplier(dist, speed)
            f = 1.0 if high_value else colour_factor(kind, self.field, self.hive)
            if f <= 0.0 and COLOUR_LIVE and not gated:
                gated = colour_why(kind, self.field)
            r_f = r * (f if COLOUR_LIVE else 1.0)
            u = urgency_multiplier(age, self._call(self.life_of, kind), dist)
            total = w * c * d * s * k * r_f
            new = self.base_for(kind, live=True) * c * d * s * k * r_f * u
            if WEIGHTS_LIVE:
                total = new
            # EVERY FACTOR OF THE SCORE IS IN THE TRACE: `base` times each
            # "x ..." entry is the score (tests/unit/test_tokenbrain_reach),
            # the rest are the inputs -- what a "why this token" view reads.
            out.append(Candidate(
                kind=kind, score=0.0 if gated else total, track_id=int(t.id),
                x=int(t.x), y=int(t.y), gated=gated, would_gate=would,
                trace={"base": round(w, 1), "x confidence": c,
                       "x distance": round(d, 3), "x staleness": round(s, 2),
                       "x cluster": round(k, 2), "x reach": round(r, 3),
                       **({"x colour": round(f, 3)} if COLOUR_LIVE else
                          {"colour": round(f, 3)} if f < 1.0 else {}),
                       **({"x urgency": round(u, 3)} if WEIGHTS_LIVE else
                          {"would score": round(new, 1)} if abs(new - total) > 1e-6 else {}),
                       "px": round(dist), "matches": matches, "age_s": round(age, 1),
                       **({"speed": round(float(speed), 2)} if speed is not None else {}),
                       **({"school_p": round(school_p, 2)} if school_p is not None else {}),
                       # THE DETECTOR'S OWN CONFIDENCE (vision/tracks, the
                       # best sighting: max over the track), not "x confidence" (matches): the
                       # school's lessons kept only the latter, so how sure
                       # the detector was could not be compared with payoff
                       # (research 2026-10-21).
                       **({"detector": round(float(det), 3)}
                          if (det := getattr(t, "detector_confidence", None)) is not None
                          else {})}))
        far = math.hypot(hx - anchor[0], hy - anchor[1])
        out.append(Candidate(kind="return", score=return_score(far), track_id=None,
                             x=anchor[0], y=anchor[1],
                             trace={"px from anchor": round(far)}))
        out.sort(key=lambda c: (-c.score, c.gated != ""))
        return out

    # ---- deciding -----------------------------------------------------------
    def decide(self, tracks: Iterable, anchor: tuple[int, int], here: tuple[int, int],
               now: float, buffs: Mapping | None = None) -> Decision:
        """The next move: chase a token, return to the anchor, or hold.

        COMMITMENT is honoured here. If a target is already being walked to
        and is still alive and eligible, it is kept unless a challenger scores
        at least `margin` times more -- the seed x1.5. Without that
        rule a field full of near-equal tokens produces a character that turns
        toward a new one every look and reaches none.
        """
        self.decisions += 1
        ranked = self.score(tracks, anchor, here, now, buffs)
        if not WEIGHTS_LIVE:
            decision = self._decide(ranked)
            decision.would = self._would(ranked, decision)
            return decision
        pre = self._preempt(ranked)
        if pre is None:
            return self._decide(ranked)
        if self.committed not in (None, pre.track_id):
            self.interrupts += 1
        self.committed = pre.track_id
        return Decision("chase", pre, ranked,
                        f"preempt: {pre.kind}#{pre.track_id} {pre.trace['px']} px away "
                        f"(its kind's preempt_px) beats any other pick")

    def _decide(self, ranked: list[Candidate]) -> Decision:
        eligible = [c for c in ranked if not c.gated]
        best_token = next((c for c in eligible if not c.is_return), None)
        ret = next(c for c in ranked if c.is_return)

        if self.committed is not None:
            current = next((c for c in eligible if c.track_id == self.committed), None)
            if current is None:
                why = "the committed token is gone or no longer eligible"
                self.committed = None
            else:
                if best_token is not None and best_token.track_id != current.track_id \
                        and best_token.score >= self.margin * max(current.score, 1e-9):
                    self.interrupts += 1
                    self.committed = best_token.track_id
                    return Decision("chase", best_token, ranked,
                                    f"switched: {best_token.kind}#{best_token.track_id} "
                                    f"scores {best_token.score:.0f}, x{self.margin} over "
                                    f"the committed {current.score:.0f}")
                if ret.score > current.score and ret.score > self.threshold:
                    self.committed = None
                    return Decision("return", ret, ranked,
                                    f"the pull home ({ret.score:.0f}) now outweighs the "
                                    f"committed token ({current.score:.0f})")
                return Decision("chase", current, ranked,
                                f"keeping the committed {current.kind}#{current.track_id} "
                                f"({current.score:.0f}); nothing scores x{self.margin} more")
        else:
            why = ""

        if best_token is not None and best_token.score >= self.threshold \
                and best_token.score >= ret.score:
            self.committed = best_token.track_id
            return Decision("chase", best_token, ranked,
                            (why + "; " if why else "")
                            + f"{best_token.kind}#{best_token.track_id} scores "
                              f"{best_token.score:.0f} — highest eligible")
        if ret.score > 0.0 and (best_token is None or ret.score >= best_token.score):
            return Decision("return", ret, ranked,
                            (why + "; " if why else "")
                            + f"nothing clears the bar ({self.threshold:.0f}); "
                              f"{round(ret.trace['px from anchor'])}px from the anchor, going back")
        return Decision("hold", None, ranked,
                        (why + "; " if why else "")
                        + ("at the anchor and nothing worth walking to"
                           if best_token is None else
                           f"best token scores {best_token.score:.0f}"
                           + (f" (x reach {best_token.trace['x reach']:.2f} at "
                              f"{best_token.trace['px']} px)"
                              if best_token.trace.get("x reach", 1.0) < 1.0 else "")
                           + f", under the bar ({self.threshold:.0f}); staying on the flowers"))

    def base_for(self, kind: str, live: bool | None = None) -> float:
        """The weight a kind starts from: the player's own, else an arm's for
        this trip, else (when `live`, default WEIGHTS_LIVE) the hive's
        tokens.yaml weight, else the priority ordering's."""
        own = self._call(self.own_of, kind)
        if own is not None:
            return float(own)
        if kind in self.weights:
            return float(self.weights[kind])
        hive = self._call(self.weight_of, kind) if (WEIGHTS_LIVE if live is None else live) else None
        return float(hive) if hive is not None else base_weight(kind, self.priority_of)

    def _preempt(self, ranked: list[Candidate]) -> Candidate | None:
        """The nearest eligible token inside its kind's `preempt_px`."""
        near = [c for c in ranked if not c.gated and not c.is_return
                and (px := self._call(self.preempt_of, c.kind)) is not None
                and c.trace["px"] <= float(px)]
        return min(near, key=lambda c: c.trace["px"], default=None)

    def _would(self, ranked: list[Candidate], decision: Decision) -> str:
        """WEIGHTS_LIVE off: the chase the hive weights, urgency and preempts
        would pick, when it is not the decision's; "" when they agree.
        ponytail: the best `would score` over the bar, with no commitment
        margin, so it can name a switch the live brain would keep from."""
        pick, why = self._preempt(ranked), "preempt"
        ret = next(c for c in ranked if c.is_return)
        if pick is None:
            tokens = [c for c in ranked if not c.gated and not c.is_return]
            best = max(tokens, key=lambda c: c.trace.get("would score", c.score), default=None)
            s = best.trace.get("would score", best.score) if best is not None else 0.0
            if best is not None and s >= self.threshold and s >= ret.score:
                pick, why = best, "would score"
        now = decision.target if decision.action == "chase" else None
        if (pick.track_id if pick else None) == (now.track_id if now else None):
            return ""
        was = f"{now.kind}#{now.track_id} ({now.score:.0f})" if now else decision.action
        if pick is None:
            # as _decide: no token worth it, so home if it pulls, else stay
            return (f"{'return' if ret.score > 0.0 else 'hold'}, not {was} — "
                    f"nothing over the bar ({self.threshold:.0f})")
        return (f"chase {pick.kind}#{pick.track_id} at ({pick.x}, {pick.y}), not {was} — "
                f"{why} {pick.trace.get('would score', pick.score):.0f}, "
                f"age {pick.trace['age_s']}s, {pick.trace['px']} px")

    @staticmethod
    def _call(fn, kind):
        try:
            return None if fn is None else fn(kind)
        except Exception:
            return None

    def _would_gate(self, kind: str, dist: float, age: float) -> str:
        """LIFETIME_GATE_LIVE's rule, or "" when it does not apply."""
        life = self._call(self.life_of, kind)
        if not gone_on_arrival(age, life, dist):
            return ""
        arrive = CHASE_START_S + dist / CHASE_PX_PER_S
        return (f"gone before we get there ({age:.1f}s old + {arrive:.1f}s walk > "
                f"{TRACK_LIFE_FACTOR * float(life):.0f}s, {TRACK_LIFE_FACTOR:g} x "
                f"{float(life):.0f}s on the field)")

    def forget(self) -> None:
        """The world changed under us (camera turned, pass restarted)."""
        self.committed = None

    def _priority(self, kind: str) -> int:
        try:
            return int(self.priority_of(kind))
        except Exception:
            return 100


# ---- VALUE: what a chase is worth, in honey a second (SHADOW) ----------------
# THE SCORE ABOVE HAS NO UNIT. Weights 48 and 36 are an ordering, so a honey
# token -- MEASURED 2026-10-21 (runs 1120-1167, 1,720 chases): 54% of chases,
# 718 of 921 hidden under a ~30k/s honey trickle, the 150 big enough to show a
# median +146k -- wins with no check against what the detour costs. This
# prices each eligible token as
#     (V x pickup - gather x LOSS_FRACTION x detour - risk x chase_value_left) / detour
# honey a second, and only SAYS what it would do ("token brain value would: ...");
# `decide` and `committed` never see it. VALUE_CHOOSER "shadow" = log only.
VALUE_CHOOSER = "shadow"
# SEEDS, not measurements (honey a token gives when picked up). honey: between
# the confirmed p25 (50k) and the confirmed median (146k), which overstates
# the typical token (most hide under the trickle). unknown: the 'pollen rose'
# boost, ~56k pollen extra (n=50, 39k/s against 5.9k/s expected) at ~1.8
# honey a pollen; most unknowns are Haste stacks, which this does not price.
VALUE_HONEY = {"honey": 60_000.0, "unknown": 100_000.0}
# MEASURED 2026-10-21 (runs 1120-1167): decision to outcome line, walk home
# included, mean by px from the character (1 s log resolution):
#     px    <250  250-400  400-550  550+
#     s     1.94  2.28     2.77     3.35     n 262 / 813 / 448 / 187
DETOUR_PX = (250.0, 400.0, 550.0)
DETOUR_S = (1.9, 2.3, 2.8, 3.4)
# The share of gathering lost while detouring. 1.0 is the WORST CASE: bees
# keep gathering during a detour, so it is lower -- measured by
# tools/analysis/chase_lessons.py --detour-cost from the lessons' rate_before
# / rate_during (brain/school) once ~24 h of them exist.
LOSS_FRACTION = 1.0
# MEASURED 2026-10-21 (same runs): the share of chases whose walk home
# "reversed its legs" -- which ends chasing for the rest of the trip
# (run_farm CHASE_LOSSES_PER_TRIP) -- by the same px bands: 11/262, 44/813,
# 24/448, 19/187.
TRIP_END_RISK = (0.042, 0.054, 0.054, 0.10)
# What a trip-ending reversal costs, in chases (each priced net of its detour): trips that never stopped
# chasing are too few to measure (7 of 53), but 46 stopped trips chased a
# median 11.5 times with ~54% of their gathering unchased, so about as many
# again are lost. MEASURED 2026-10-21 (runs 1120-1167 cycle lines).
CHASES_LOST_TO_A_REVERSAL = 11.5
# SEED, not a measurement: the net honey of an AVERAGE chase, which is what a
# reversal loses (pricing the lost chases like the one at hand made every far
# token negative whatever its worth: 1 - 11.5 x 0.10 < 0). ~ an unknown's
# 75k (100k x 0.75 taken) less ~2.5 s of detour (the px-band mean, n 1,710)
# at 57k/s x a guessed 0.4 lost; replace once --detour-cost measures the loss.
MEAN_CHASE_NET_SEED = 20_000.0
# 'walked onto it' 87% against ~65% real pickups (today's research): the
# share of reached tokens actually taken.
PICKUP_GIVEN_REACHED = 0.75
# Honey a pollen when no trip has converted yet: MEASURED 2026-10-21, a cycle
# makes ~57k honey/s from ~30k pollen/s.
HONEY_PER_POLLEN_SEED = 1.9


def _band(px: float, table: tuple) -> float:
    return table[bisect.bisect_right(DETOUR_PX, px)]


def detour_s(px: float) -> float:
    return _band(px, DETOUR_S)


def trip_end_risk(px: float) -> float:
    return _band(px, TRIP_END_RISK)


def worth(cand: Candidate) -> float:
    """Expected honey from walking at `cand`: its kind's value x the share
    reached at its distance (the score's own x reach, made absolute) x the
    share of reached tokens taken."""
    reach = float(cand.trace.get("x reach", 1.0)) * REACH_BY_SPEED[0][1][0]
    return VALUE_HONEY.get(cand.kind, VALUE_HONEY["unknown"]) * reach * PICKUP_GIVEN_REACHED


def value_per_second(cand: Candidate, gather_honey_s: float,
                     chase_value_left: float | None = None) -> float:
    """Honey a second the detour at `cand` earns over staying on the flowers."""
    px = float(cand.trace.get("px", 0.0))
    # ponytail: DETOUR_S is the mean over the runs' mixed Haste, so it is not
    # divided by trace["speed"] (that would count the mean speed twice); a
    # per-speed table, once lessons carry it, would price Haste properly.
    d = detour_s(px)
    v = worth(cand)
    net = v - gather_honey_s * LOSS_FRACTION * d
    if chase_value_left is None:
        # the chases a reversal ends, each an average chase, not this one
        chase_value_left = CHASES_LOST_TO_A_REVERSAL * max(0.0, MEAN_CHASE_NET_SEED)
    return (net - trip_end_risk(px) * chase_value_left) / d


def shadow(decision: Decision, gather_honey_s: float,
           chase_value_left: float | None = None) -> str:
    """What the value chooser would do with this decision's candidates, as the
    rest of a "token brain value would: ..." line; "" with no eligible token. Reads
    `decision.ranked` only."""
    tokens = [c for c in decision.ranked if not c.gated and not c.is_return]
    if not tokens:
        return ""
    vals = [(value_per_second(c, gather_honey_s, chase_value_left), c) for c in tokens]
    v, best = max(vals, key=lambda t: t[0])
    px = float(best.trace.get("px", 0.0))
    what = (f"{best.kind} at ({best.x}, {best.y}) ({v:+,.0f}/s: worth {worth(best):,.0f}, "
            f"detour {detour_s(px):.1f}s, gather {gather_honey_s:,.0f}/s, "
            f"risk {trip_end_risk(px):.2f})")
    picked = decision.target
    if v > 0:
        if decision.action != "chase" or picked is None:
            return "chase " + what + f" -- the score says {decision.action}"
        if picked.track_id != best.track_id:
            return "chase " + what + f" over the score's {picked.kind}#{picked.track_id}"
        return "chase " + what
    return "skip " + what + (" -- the score chases" if decision.action == "chase" else "")

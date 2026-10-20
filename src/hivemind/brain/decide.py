"""Choosing what to do next, and being able to say why.

THE OWNER, AND THEY ARE RIGHT: an AI with no grasp of progression and no goal
feels as if it has no brain.

It did not have one. Everything the bot did was a constant:

    OUT_ROUTES = ("from_hive_to_pine_tree_with_red_cannon",)
    PATTERN    = "collect_around"
    convert at 90%

It went to the Pine Tree Forest every time it ran. `data/knowledge/world.yaml`
records, in English, that the Pine Tree Forest "is protected by two mantises and
the Werewolf" and carries `safe: false`. The Sunflower Field has 660 flowers to
Pine Tree's 713, needs no bees, and nothing there can hurt you. The bot had both
facts available and could not use either, because nothing in it chose anything.
A mantis killed the character on 2026-09-20 carrying 362,208 pollen -- the
owner's own backpack, gathered before the bot started -- and every part of that
was foreseeable from a file already on disk.

WHAT A CHOICE IS MADE OF HERE. Nothing invented. Every input is either measured
by this bot or quoted from the wiki:

    bees_required, flowers, mobs, safe    data/knowledge/world.yaml
    pollen per second, deaths, visits     brain/fieldnotes, measured by playing
    pollen, capacity, honey               the HUD, read from the screen
    where we are                          vision/whereami, from the game's text

WHERE PROGRESSION COMES FROM, AND IT IS NOT A SETTING. The owner asked for a bot
that works out its own progress rather than being told. Bee count gates which
fields exist, and we do know which fields have PAID US. Gathering in the
Mountain Top Field requires 25 bees, so having gathered there is proof of at
least 25. `bees_at_least` is that inference -- and, since the bee menu is
read (act/beemenu), its own count when that is more -- and it is evidence
rather than configuration.

EVERY DECISION CARRIES ITS REASONING. The owner asked to see the AI's thought
process, what it sees, its goals and its choices, so `Decision.why` is a
sentence a person can argue with, and `alternatives`
keeps what was rejected and why. A score with no explanation is not a decision,
it is a number.
"""
from __future__ import annotations

import random
import time

import math

from dataclasses import dataclass, field as dc_field
from pathlib import Path

from .fieldnotes import PAID_ENOUGH_SECONDS
from .ledger import RECENT_SECONDS
from . import protips

# Pollen worth protecting. Below this, a trip through a dangerous field risks
# little and the flowers are worth more than the backpack; above it, a death
# costs more than the trip can earn back.
#
# MEASURED, and this is where the number comes from: the best rate this account
# has recorded is 1,071 pollen/second, and a full gather runs a few minutes. A
# backpack holding more than about a minute of gathering is therefore worth more
# than the trip that would top it up. 50,000 is that, rounded down.
WORTH_PROTECTING = 50_000

# Flowers as a stand-in for a rate we have not measured. It is a RANKING only:
# more flowers is more pollen per pass, but the constant relating the two has
# never been measured on this account, so this number must never be presented
# as a rate. A field we have actually farmed always beats a field we have not.
UNMEASURED_PENALTY = 0.5

# An unmeasured field the owner has named as one of the worst for honey
# (`yield: lowest` in world.yaml) has its GUESS halved again. An ordering, not
# a rate: see Planner._guess_rate.
LOWEST_YIELD_FACTOR = 0.5

# How much a field's danger discounts it while we are carrying nothing. Mobs
# still cost time and knock the character around even when the backpack is
# empty, but they cannot take what is not there.
DANGER_DISCOUNT = 0.75

# THE HOURLY REVIEW'S LEAKS, FED TO PLANNER V2 ONLY (brain/reflect.field_minutes;
# the lead Claude, 2026-10-22: v2's shadow, not the live field choice). Until
# now reflect.review ranked what cost the hour and only narrated it (MEASURED
# 2026-10-21: nothing in decide or farm read it). In score_v2 the minutes a
# field lost in the last hour to the leaks nothing else prices -- gathering
# off the flowers, a trip that gathered nothing; not route misses (p_land) nor
# deaths (v2's own survival) -- take that share of the hour off its value.
# ponytail: 1 - minutes/60 with a 0.7 floor is a first rule, not a measured
# one; the floor keeps one bad hour from burying a good field. Judge it from
# the "planner would:" lines (it changes nothing live while v2 is shadow).
LEAK_FLOOR = 0.7

# HOW MUCH THE CURIOSITY BONUS MAY BE CUT BY WHAT WE ALREADY KNOW. A field
# with the fewest flowers and no quest interest still gets this share of the
# optimism, so exploring it stays possible; the one with the most flowers and
# a quest asking for its pollen gets all of it. The spread is deliberately
# narrow: it must order the unmeasured fields without pushing any of them
# below a measured one, because exploring is what stops the bot settling on
# its first success for ever. The bound is arithmetic, not taste --
# `test_the_real_knowledge_base_no_longer_farms_one_field_forever` has
# Pineapple measured at 252 pollen/s and guarded, so it scores 189, while an
# unmeasured guarded field scores 252 x 1.1 x 0.75 = 207.9 before the share;
# anything under 0.91 would put exploration below it. Without this the
# optimism was
# one flat number and nine fields tied on it (see the curiosity block).
EXPLORE_TIE_FLOOR = 0.95

# HOW LONG A FIELD MUST HAVE BEEN WATCHED for its rate to be evidence rather
# than one lucky interval. A token pickup lands inside a single sample, so a
# three-second visit can read at 1,875 pollen/s -- seven times anything real
# (MEASURED 2026-09-23 03:05, Cactus). A minute spans several pattern passes
# and several token chases, which is enough for the average to mean something.
MEASURED_ENOUGH_SECONDS = 60.0
# The "recent" rate source (`_rate_source`): at least this many of a field's
# latest trips, covering at least this much gathering.
RECENT_TRIPS_ENOUGH = 5
# The ledger's own window reaches back until it covers this (ledger.RECENT_SECONDS).
RECENT_SECONDS_ENOUGH = RECENT_SECONDS

# HOW FAST THE HIVE DRAINS THE BACKPACK, in pollen per second.
#
# MEASURED TWICE, and the SLOWER figure is the one used.
#
#   run-281, 02:17:09 -> 02:18:51   1,105,517 pollen in 102 s   10,838/s
#   run-290, 03:27:50 -> 03:28:41   1,073,886 pollen in  51 s   21,057/s
#
# The hive drains faster now than it did an hour earlier, which is what a
# growing hive should do, so there is no single true number here -- only a
# range. Overestimating the dwell can only make the rule below fire LESS
# often, and under-firing costs a better field while over-firing costs banked
# honey, so the slow end is the honest choice and is taken deliberately. It is
# used for ONE thing: pricing the dwell, so that "convert before leaving" can
# be weighed against the trip it delays instead of being asserted.
CONVERT_POLLEN_PER_SECOND = 10_800.0

# Even an empty backpack takes a moment to press, settle and confirm, and that
# moment is paid whether there is one pollen in the bag or a million. MEASURED
# from the same converts: about ten seconds between the press and the first
# reading that showed the counter moving.
CONVERT_FIXED_SECONDS = 10.0


# HOW MANY SECONDS THE YARDSTICK NEEDS, which is more than a field's own
# score needs, and the difference is the point.
#
# A field's own score may rest on a minute: that is its own evidence about
# itself, and being wrong about one field costs one trip. The YARDSTICK prices
# every field nobody has farmed -- `_guess_rate` scales it by flower count and
# `EXPLORE_OPTIMISM` multiplies it -- so being wrong about the yardstick moves
# the whole board at once. It has now done so twice:
#
#   Cactus       5,437 pollen in    3 s  =  1,875/s   (2026-09-23 03:05)
#   Spider      82,377 pollen in   86 s  =    959/s   (2026-09-23 04:11)
#
# Both are above MEASURED_ENOUGH_SECONDS and neither is a rate: they are one
# lucky interval and one short visit. 300 s is two or three trips' worth of
# measurement, the same figure and the same reasoning as
# `brain/fieldnotes.PAID_ENOUGH_SECONDS`.
YARDSTICK_ENOUGH_SECONDS = 300.0


def colour_worth(petals, worth=None) -> float | None:
    """How much of a field's pollen is a colour this hive is good at, 0..1.

    `petals` is `Note.petals`, the pixel counts `vision` has actually seen of
    each flower colour in that field -- real measurement, unlike the single
    `colour:` label in the knowledge base, which is None for most fields and
    was the only thing the colour preference used to read.

    MEASURED 2026-09-23 from the account's own notes:

        cactus       54% blue, 41% red,  5% white   ->  0.70
        spider       18% blue,  5% red, 76% white   ->  0.31
        blue_flower  60% blue,  8% red, 32% white   ->  0.68
        bamboo       80% blue,  4% red, 17% white   ->  0.84

    None when the field's petals have never been counted, which the caller
    must treat as "no opinion" rather than as zero.
    """
    worth = worth or COLOUR_WORTH
    if not petals:
        return None
    total = sum(float(v or 0) for v in petals.values())
    if total <= 0:
        return None
    return sum(float(petals.get(c, 0) or 0) * w
               for c, w in worth.items()) / total


def _rate_source(note, over: float = MEASURED_ENOUGH_SECONDS,
                 trips: dict | None = None) -> tuple[float | None, str]:
    """`(pollen/s, where it came from)`, best evidence first. See
    `_measured_rate`, which is this without the second half.

    THE SOURCES ARE NOT THE SAME KIND OF NUMBER, and ranking one against
    another as if they were was under-ranking whole fields (audit 2026-09-26,
    brain F6). `note.rate` falls back to pollen over EVERY second when the
    paid pair covers under PAID_ENOUGH_SECONDS, and the seconds whose counter
    could not be read add time and no pollen -- so it is a floor. MEASURED on
    var/field_notes.json and var/trips.jsonl, 2026-09-26: Rose was ranked on
    396 pollen/s (paid pair 4 s) while its trip paid 1,019/s; Stump on 27
    (paid pair 0 s) against a trip's 469; Dandelion on 222 against 312.

      "recent"   the trip ledger's last RECENT_TRIPS trips credited here,
                 reaching back until they cover ledger.RECENT_SECONDS
                 (brain/ledger.pollen_by_field), once RECENT_TRIPS_ENOUGH of them
                 cover RECENT_SECONDS_ENOUGH. MEASURED 2026-10-01 against the
                 live files: the paid pair understated every field the hive
                 had grown on since -- Pine Tree 3,332 against its last ten
                 trips' 9,481, Bamboo 3,297 against 7,189, Pumpkin 3,373
                 against 6,056, Blue Flower 487 against 1,535 -- unevenly, by
                 when each was last measured, so fields were ranked on stale
                 numbers against fresh ones.
      "paid"     the legible pair, once it covers PAID_ENOUGH_SECONDS.
      "trips"    the trip ledger: pollen over gathering seconds for every
                 trip the feed credited here (brain/ledger.pollen_by_field).
                 Against the paid pair on the six fields that have both
                 (blue flower, mushroom, pine tree, spider, strawberry,
                 sunflower) it runs 0.88-1.18x.
      "printed"  the HUD's own (+N/sec), PRINTED_ENOUGH_SAMPLES of them:
                 0.92-1.27x the paid pair on the same six.
      "floor"    pollen over all seconds: a lower bound, never proof that a
                 field is poor (see EXPLORE_POOR_SHARE's use in `rank`).
    """
    if trips and int(trips.get("recent_trips") or 0) >= RECENT_TRIPS_ENOUGH \
            and float(trips.get("recent_seconds") or 0.0) >= RECENT_SECONDS_ENOUGH \
            and float(trips.get("recent_pollen") or 0.0) > 0:
        return float(trips["recent_pollen"]) / float(trips["recent_seconds"]), "recent"
    paid_s = float(getattr(note, "paid_seconds", 0.0) or 0.0) if note is not None else 0.0
    paid_p = float(getattr(note, "paid_pollen", 0.0) or 0.0) if note is not None else 0.0
    if paid_s >= max(float(over), PAID_ENOUGH_SECONDS) and paid_p > 0:
        return paid_p / paid_s, "paid"
    if trips and float(trips.get("seconds") or 0.0) >= float(over) \
            and float(trips.get("pollen") or 0.0) > 0:
        return float(trips["pollen"]) / float(trips["seconds"]), "trips"
    if note is None:
        return None, ""
    printed = getattr(note, "printed_rate", None)
    if printed is not None and printed > 0:
        return float(printed), "printed"
    seconds = float(getattr(note, "seconds", 0.0) or 0.0)
    if getattr(note, "pays", False) and seconds >= float(over):
        return float(note.pollen) / seconds, "floor"
    return None, ""


def _measured_rate(note, over: float = MEASURED_ENOUGH_SECONDS,
                   trips: dict | None = None) -> float | None:
    """This field's pollen/s, or None when the measurement is too thin to be
    one -- which is the SAME QUESTION whether it is being asked about a
    field's own score or about the yardstick every unmeasured field's
    curiosity is a multiple of, so it is answered in one place.

    Returning None is not a demotion. A field whose rate rests on three
    seconds goes back to being an unmeasured field, gets the curiosity bonus,
    and is ranked on its flower count and what the quests want from it --
    which is exactly what it is: somewhere we have not properly been.
    """
    # THE HUD'S OWN FIGURE, when the counter never gave a pair. Exact, and on
    # the low side of the counter's own movement (fieldnotes.Note.printed_sum:
    # median ratio 0.78 over ten-second windows), which is the right kind of
    # wrong for a fallback: it under-sells a field rather than inventing one.
    # The order of the sources, and why: `_rate_source`.
    return _rate_source(note, over, trips)[0]

# The router names two places differently from the knowledge base. Kept as an
# explicit map rather than fuzzy matching, because a near-miss here would look
# like "that field is unreachable" and silently remove it from every decision.
ROUTER_ALIASES = {"rose": "rose_field"}

# HOW MUCH A MATCHING FIELD COLOUR IS WORTH, and what this number is NOT.
#
# Every flower is red, blue or white, and a red or blue bee collecting from a
# flower of its own colour gets +50% pollen from it (wiki, Fields). So a hive
# committed to one colour should camp fields leaning that way -- which is what
# the owner asked for: a blue hive.
#
# 1.25 is a RANKING PREFERENCE, not a predicted rate, and it is deliberately
# below the +50% the game actually gives. The full bonus would only apply if
# every bee were blue AND every flower in the field were blue, and neither is
# true: fields are mixed, the layout is regenerated on every server join, and
# a hive is built up one bee at a time. Scoring the full 1.5 would claim a
# precision nothing here has measured.
#
# It never applies to a field with a MEASURED rate, because a measurement
# already contains whatever the colour did.
COLOUR_BONUS = 1.25

# WHAT EACH COLOUR OF POLLEN IS WORTH TO THIS HIVE, 1.0 being "the bees are
# good at this".
#
# THE OWNER, 2026-09-23: white pollen (Spider's white flowers) gives their hive
# little, because the bees are good at blue and a little at red. These three
# numbers are that statement and
# nothing else -- blue full, red a little, white not much -- and they are theirs
# to change. They are NOT measured, because nothing on screen separates pollen
# by colour: the counter shows one total.
#
# WHAT THIS IS AND IS NOT. The measured `Note.rate` already contains whatever
# the bees actually managed in that field, white flowers included, so this is
# not a correction to the measurement. It is a PREFERENCE, applied on top,
# for the hive they are building rather than the one they have: as the hive turns
# blue, blue fields get better and white ones do not. It is deliberately
# visible in every score's reason so the trade is theirs to see.
COLOUR_WORTH = {"blue": 1.0, "red": 0.35, "white": 0.15}
# How hard the preference bites. 0 is "ignore colour", 1 is "score a field on
# its usable share alone". Half way: a field of pure usable pollen keeps its
# rate, and a field of pure white keeps 57% of it.
COLOUR_WEIGHT = 0.5

# HOW MUCH A QUEST IS ALLOWED TO MOVE THE RANKING. The owner: get quests
# working. Two of their three quests want a specific colour of pollen and
# between them are short about 1.5 million of it, so where the bot stands is
# how those quests get done -- or do not.
#
# It is a tilt and not an override, deliberately. Pollen per second is still
# what pays for everything, and a quest that sent the bot to a barren field
# would cost more honey than the quest's reward is worth. At 0.5 a field made
# entirely of the needed colour is worth half again as much, which is enough
# to break a tie between comparable fields and not enough to override a real
# difference in rate.
QUEST_BONUS = 0.5
# B5: the quest-first sort in `rank` (off = the additive goal term alone decides)
QUEST_FIRST_SORT = True
# R2 (brain-research-4): A QUEST'S MOB KILLS ARE A BUG RUN'S JOB, NOT A GATHER
# TRIP'S. MEASURED over 400 trips: 11.6 h of full gathers in Mushroom / Rose /
# Clover / Cactus (1.5-2.5M honey/h, against 16-21M/h on the blue fields) were
# taken to kill a few mobs ("4 more ladybugs") that respawn every 5 min, while
# run_farm's bugrun_for_quest already walks to a due mob for its quest. Off:
# only pollen a quest names makes a field quest-first / priority; on: the old rule.
QUEST_FIELDS_FOR_MOBS = False
# P3: an explored field must score at least this share of the best
EXPLORE_NEAR = 0.8
# A QUEST STEP ONE TRIP FINISHES GOES FIRST ANYWAY. The owner's standing ask is
# "do their quests", and a tilt never finishes a small step at a slower field:
# 2026-09-28/29 the Polar Bear's "Collect 150,000 Pollen from the Strawberry
# Field" read 0/150,000 in every read all night (var/night/run-531..536) --
# 107 s of gathering at Strawberry's measured 1,397 pollen/s -- and none of
# the night's 59 trips went there (Bamboo 36 at 3,293, Pine Tree 16 at 3,174;
# var/trips.jsonl). So pollen a quest owes from one named field
# that fits in QUICK_QUEST_SHARE of a trip at that field's MEASURED rate ranks
# it first, as `quests.first` would. Only where a walk home is recorded: a trip
# that ends in a rejoin costs the Wealth Clock streak, which is the owner's to
# spend (`quests.first`), not this rule's. The danger and reach rules still
# stand -- they zero the score, and a zero never goes first. Bigger steps
# keep the tilt alone.
QUICK_QUEST_SHARE = 0.8
# ...UNLESS THE OWNER PUTS QUESTS FIRST (`quests.first`, Planner.quest_first).
# The owner, 2026-09-27: unpin whatever testing needs; quests come first. Then
# a field a quest names outright ("Collect 420,000
# Pollen from the Mountain Top Field") or where a mob a quest wants lives is
# ranked ahead of every field no quest names, whatever the rates say: the
# quest's own field is where its step gets done, and nowhere else does it.
# ORDER, NOT A MULTIPLIER. A x20 bonus was tried first and lost: MEASURED
# 2026-09-27 13:07 on the live notes, Mountain Top's rate is a 102 pollen/s
# floor from 88 illegible seconds, so twenty times it ranked 1,390 against
# Pine Tree's 2,125 -- a quest field's score is exactly the number nobody has
# measured yet. Only fields that may be gone to are put first: a score the
# danger rules zeroed, a route given up on, or too few bees keep a field out,
# and a colour a quest wants keeps the tilt, since any field of it will do.
#
# Q8: ...EXCEPT THAT THE TILT NEVER MOVED A RED STEP. "Any field of it will
# do" left a colour step to the tilt (QUEST_BONUS x the colour's share),
# which is x1.04 on Pine Tree and x1.29 on Rose -- never enough to beat Pine
# Tree's ~5x the pollen/s. MEASURED 2026-10-05..18 (var/trips.jsonl, the
# trips' own `context.quests.pollen`): 445 trips owed red pollen and 110 went
# to Pine Tree (7% red petals), 9 % of the gathering to Rose; red was gathered
# at ~1,190/s against Rose's ~4,100-5,000 red/s, and "Rare Red Clover"
# (120M red) took 51 h, Star Journey 2's 50M red three days. Blue steps were
# fast only because the best honey field is blue anyway. So with quests.first
# on, a colour step puts first the reachable field with the most MEASURED
# pollen/s of that colour (rate x petal share, fieldnotes `colour_share`;
# red's petal-share estimate came to 1.08x the menu's measured red progress
# over 124 reads), and run_farm's weak_quest_best alternation decides how
# often honey wins, as it does for a named field.
COLOUR_STEP_FIRST = True

# BLOOM PETALS (Q8 step 2): the quest value of a field where an owed petal
# colour's blooms spawn (data/knowledge/blooms.yaml), when the step names no
# field. Half a named field's 1.0: the natural spawn rate is unmeasured, so it
# tilts the choice toward such a field without letting it take over the hour.
BLOOM_FIELD_VALUE = 0.5

# EXPLORATION, and the night it did not exist.
#
# The ranking scores a field on its MEASURED rate when it has one and on a
# discounted guess when it does not. That is the right instinct and it has a
# hole in it: a field can only be measured by visiting it, and it will never
# be visited while a measured neighbour outscores its guess. On 2026-09-20 the
# bot went to the Pineapple Patch 42 times and to nothing else, ever. It
# printed "quests want 150,000 more pollen from strawberry" on all 92 cycles
# and walked to pineapple anyway -- strawberry was reachable, and one trip
# would have finished the step. Replayed: pineapple 189.02 (measured 252/s),
# strawberry 106.84 (guessed, WITH the quest bonus). The gap only widened,
# because every trip improved pineapple's measurement and none touched
# strawberry's guess.
#
# So a reachable field that has not yet had one proper trip's worth of
# gathering is scored OPTIMISTICALLY: assumed to be at least as good as the
# best field we have measured, times EXPLORE_OPTIMISM, fading to nothing at
# EXPLORE_SECONDS. "Until proven otherwise, a new field is as good as our
# best one" -- which guarantees each reachable field one real trip, after
# which it stands on its own measurement like every other. A plain multiplier
# on the guess was tried first and could not flip the case above: the guess
# is already scaled down by flower count, so doubling it still lost.
#
# The danger rules run AFTER this and still zero a guarded field when carrying
# pollen, so curiosity never overrides the rule that cost 361,439 pollen; it
# only ever spends an empty backpack.
EXPLORE_OPTIMISM = 1.1

# A FIELD THAT HAS ALREADY SHOWN IT PAYS POORLY GETS NO BENEFIT OF THE DOUBT.
#
# The optimism fades only with the SECONDS spent in a field, so a field that
# has shown a bad rate keeps most of it. MEASURED in var/field_notes.json on
# 2026-09-23: Stump paid 27 pollen/s over 82 s and Mountain Top 36 over 85 s,
# against Strawberry's 1,071 -- and with 73% of the bonus still left at 82 s,
# Stump scored as if it were our best field and was chosen (run-321,
# "only 82s measured here, worth finishing"). Each such pick is a whole trip.
# The owner, 2026-09-23: no time wasted in small fields with barely any
# pollen.
#
# So once a field has a rate the planner itself calls measured
# (`_measured_rate`, a minute of gathering), and that rate is under this
# share of the best field's, curiosity stops and it stands on its own number.
# A quarter, not a half: a visit that landed badly reads low, and at a
# quarter even a reading off by two still loses to the best field on merit.
# A field it has never gathered in still gets its one real trip.
EXPLORE_POOR_SHARE = 0.25

# HOW MANY TRIPS IN A ROW MAY FAIL TO REACH A FIELD BEFORE IT STOPS BEING
# WORTH CHOOSING.
#
# The curiosity bonus above treats an unmeasured field as being as good as our
# best measured one, so an unmeasured field always outranks a proven one. That
# is the right instinct and it has one blind spot: if the route does not work,
# the field stays unmeasured and keeps winning for ever.
#
# MEASURED 2026-09-21: five consecutive cycles all chose the Strawberry Field,
# every one of them failed to leave the hive row, and the Rose Field -- which
# the same night measured at 930 pollen/s, the best rate this account has ever
# recorded -- was never chosen again. The night was spent trying to reach the
# one place it could not reach.
#
# Two rather than one, because a journey already retries three times inside
# itself and the one trip that DID reach the red cannon did it on its second
# attempt. One failed journey is bad luck; two is the route.
# RAISED FROM 2 TO 4 ON 2026-09-22 06:45, on measurement and on a live
# failure. The 2 was calibrated against a signal that almost never fired,
# because `run_farm._travelled` reset the counter on every trip that merely
# left the hive (DESIGN 8q). Once that was fixed the signal worked, and two
# in a row is far too little evidence against a route that works some of the
# time: Dandelion delivered 418,434 pollen at 06:12 and was banned by 06:25,
# after which the bot had no field it could reach and spent twenty minutes
# doing "0s gathering over 0 passes" and rejoining.
#
# A banned field is never chosen, so it can never earn the success that would
# clear it -- the ban is one-way, and only `_all_given_up`'s valve undoes it.
# That asymmetry is why the threshold should be generous: a wrong ban costs
# the best field on the account, a late ban costs a few trips. At the ~40%
# success rate the ledger shows for these routes, two-in-a-row happens 36% of
# the time by luck alone; four-in-a-row, 13%.
TRAVEL_FAILURES_TO_GIVE_UP = 4
# Q1: A FIELD A QUEST OWES POLLEN FROM GETS ONE MORE TRIP WHEN ITS ROUTE LANDS
# NOW. The ban above is one-way, and it counts the trips of whatever route the
# field had THEN; the route posterior (brain/skills, `route_odds`, DESIGN 8dy)
# is what the route does NOW, bug runs' trips included. MEASURED 2026-10-12:
# the Polar Bear's "Collect 150,000 Pollen from the Strawberry Field" read
# 142,592/150,000 in every read from 16:31 to 19:59 (run-905..916) -- 7,408
# pollen, about 2 s at Strawberry's measured 3,495/s -- and every trip's
# candidates scored Strawberry 0, "failed to arrive 4 trips in a row"
# (var/trips.jsonl): a ban already standing at 10-05 22:26, earned by the old
# routes of 09-22..26 (three of the four "refusing to run it from the wrong
# place"). Meanwhile the Strawberry flight landed 2 of its last 2, its walk
# home 10 of 10 (var/skill_stats.json), and bug runs reached the field
# (run-867 04:19, run-879 11:39). Dandelion, banned since 10-08 00:21 with its
# walk landing 10 of its last 10, held the Polar Bear's "80,000 Pollen from
# the Dandelion Field" at 3,276 from 10-09 to 10-11 the same way.
#
# So a field given up on, that a quest still owes pollen from, and whose route
# out lands at even odds or better (QUEST_RETRY_P_LAND, inclusive since
# 2026-10-20: Bamboo and Strawberry sat at exactly 0.50 and, under a strict
# "over", their bans could never lift -- a never-judged route at the prior's
# 0.5 now qualifies too, at most once per QUEST_RETRY_AFTER_S), may go on until
# QUEST_ROUTE_RETRIES more trips have got nowhere. An arrival clears the ban as
# it always has (fieldnotes `arrived`); a trip that gets nowhere counts a
# failure and the ban stands again; one that lands elsewhere is the route's to
# answer for (its posterior), as on any field. ponytail: a count, not a clock
# -- a retry that failed keeps the field banned for later quests too, until an
# arrival; a re-transpiled route earns its own trial (Q2, `failed_at`).
QUEST_RETRY_P_LAND = 0.5
QUEST_ROUTE_RETRIES = 1
# A GIVEN-UP FIELD WORTH A TRIP FOR ITS HONEY ALONE (_valuable_retry): its
# recent rate against the best measured field's (the yardstick).
VALUABLE_RETRY_SHARE = 0.75  # Bamboo 29,165 vs Mountain Top 34,271-36,931 recent (0.79-0.85), 2026-10-20
# Q1 (2026-10-19): AND AGAIN ONCE THE LAST TRIP THAT GOT NOWHERE IS THIS OLD.
# The count above is one-way: one retry that misses and the ban stands until
# an arrival that a banned field can never earn. MEASURED 2026-10-18/19:
# Bamboo was given up after the 17 Oct leg-3 path failures (docs/pending/
# reliability-2026-10-19.md #3, which stopped by 08:11 that day), its
# one retry at 18 Oct 01:11 flew and "arrival unconfirmed" made it 5, and for
# the next 25 h of running every trip scored Bamboo 0 ("failed to arrive 5
# trips in a row") while its flight landed 8 of its last 10 -- with QR Quest's
# 16.7M Bamboo pollen and Bucko Bee's 13M Bamboo goo waiting on it. A field a
# quest owes, whose route lands now, gets one more trip each time its last
# failure (fieldnotes `failed_at`, stamped by every trip that got nowhere) is
# QUEST_RETRY_AFTER_S old: at most one lost trip (~2 min) per field per
# window. ponytail: a fixed window; per-field backoff if a field burns them.
QUEST_RETRY_AFTER_S = 6 * 3600.0
# AND A DAILY PROBE WHEN A QUEST OWES A LOT AND THE ROUTE LANDS UNDER EVEN
# ODDS. MEASURED 2026-10-21: Pepper's walk landed 1 of 6 (P 0.33, 6 Oct; the
# last five 6-14 Oct ran one ledge behind from the jump near the coconut,
# var/routes/attempt-662 vs -986 steps 34-36) and 180M Pepper pollen held two
# quests (Pleasant Pastimes 80M, Variety Fetcher 2 100M) with no trip in 7
# days -- the 0.5 bar above can never lift it, and no trip means no frames to
# fix the route from. One trip a day while a quest owes this much: ~2 min.
QUEST_PROBE_MIN_OWED = 10_000_000
QUEST_PROBE_AFTER_S = 24 * 3600.0
# Q2: AND ONE TRIAL TRIP WHEN ITS ROUTE HAS NOT BEEN TRIED IN ITS PRESENT SHAPE.
# Q1 needs verdicts, and a route that changed after the ban has none: a change
# of steps, timing (brain/skills WALK_GENERATION) or ROUTE_REVISIONS label
# starts its window afresh (SkillBook.watch_steps, `window_since`), at the
# prior's 0.5. MEASURED 2026-10-12: the Brown Bear's "Collect 2,200,000 Pollen
# from the Coconut Field" read 82,133 (var/quests.json, 19:59); Coconut was
# given up on 10-06 17:50 (var/trips.jsonl, attempt 694) after natro_out_coconut
# was booked elsewhere 4 times that day (13:02-17:44), two of them the crab
# killing the character as it landed (data/world/timers.yaml coconut_crab); at
# 10-09 12:21 (run-811) its window started afresh for the new walkspeed, "since
# its last 4 verdict(s) (0 landed)", and it has held no verdict since
# (var/skill_stats.json, 20:18), so Q1 can never fire. Pepper the same (given
# up 10-08 02:49, afresh 10-09 12:21, nothing since).
#
# So a field given up on that a quest owes pollen from, whose route out (the
# one a trip would take now, `route_window`) holds no verdict in its window,
# and that no trip has failed to reach since that window began (fieldnotes
# `failed_at`, wall clock; a failure from before this was kept has none and
# counts as older), gets ONE trial trip, scored the normal way. An arrival
# clears the ban (fieldnotes `arrived`). A trip that got nowhere stamps
# `failed_at` past the window's start: no other trial until the route changes
# again. One that landed elsewhere puts a verdict in the window, and Q1's
# posterior rules from then on. Coconut also waits on its crab (run_farm
# `field_guarded`: shut until a kill). Off (False): Q1 alone.
QUEST_ROUTE_TRIAL = True
EXPLORE_SECONDS = 300.0

# How long one gathering stint lasts, in seconds. Only used to convert a
# measured death rate into 'chance of losing this trip'; it matches the
# farm loop's own cap so the two agree about what a trip is.
TRIP_SECONDS = 420.0

# WHAT A TRIP WITHOUT A WALK HOME COSTS AT ITS END. Seven fields have no
# recorded walk back (scripts/transpile_natro refuses the Natro paths that
# glide off a ledge or press the blue portal), so every trip there ends in a
# rejoin. MEASURED across the night logs (docs/GAPS.md): about 100 seconds an
# attempt -- 75 for the rejoin itself and the rest for the closers to give
# up. The rejoin also leaves the server, which the owner says resets the
# Wealth Clock streak; that loss is real and is NOT priced here, because its
# value in honey has not been measured. So the discount below is the time
# share alone, which understates the true cost rather than inventing it.
REJOIN_SECONDS = 100.0
# AND A WALK HOME THAT MISSES COSTS ITS OWN WALK AS WELL. MEASURED over attempts
# 307-406 (scripts/run_farm, at HOME_PROBE): a walk home that fails costs a median
# 84 s (25 of them) before the rejoin that comes anyway. Until 2026-09-29 a field
# with a recorded walk home was priced as if it always landed, and the landings
# differ by field more than the pollen does -- var/skill_stats.json that day:
# Dandelion 2 of 14, Blue Flower 2 of 11, Mushroom 11 of 21, Bamboo 53 of 61,
# Pine Tree 178 of 188.
FAILED_HOME_WALK_SECONDS = 84.0

# A1 (ROADMAP A22): A WALK HOME THAT MISSES HALF THE TIME, WITH NO WHIRLIGIG TO
# RESCUE IT, IS NOT WALKED. The pricing above takes the miss as time only, so a
# coin-flip walk home costs a field ~18% of its score -- and a Blue Field
# Booster x3 still sent the trip there. MEASURED 2026-10-15 (var/trips.jsonl,
# var/night, var/routes): natro_home_blue_flower landed 5 of its last 10; the
# misses were 3 starts off the flowers (986 04:45, 1013 04:31 after token chases
# at a full bag, 1013 04:45 on the red cannon) and 2 walks still under Haste
# x9-x10 after W5's 32 s wait (988 07:53, 1015 06:22). 1015's had no Whirligig
# left (1/100, then greyed), so the miss ended in a rejoin and the Wealth Clock
# streak the owner asked to keep. Whirligigs are not sold for honey or tickets
# (wiki), so while none is held such a field is shut, and opens again the
# moment a Whirligig is counted (a planter or mob drop) or the walk's record
# climbs back over the floor. Judged walks only: an unjudged walk's prior is
# also P 0.50.
# ponytail: a shut field earns no new verdicts while shut, so only a rescue
# item reopens it; add a timed probe (as HOME_PROBE_SECONDS) if one never comes.
#
# A MICRO-CONVERTER RESCUES A MISS TOO (docs/pending/reliability-2026-10-19.md).
# run_farm.micro_rescue converts the bag where the walk ended and respawns home
# -- no rejoin, the Wealth Clock's hour kept. MEASURED 17-19 Oct (run-1045..
# 1067): of 21 stranded walks home, 9 were rescued by a Whirligig, 10 by a
# Micro-Converter, 2 rejoined (both with the Micro-Converter greyed or slow).
# But this bar counted Whirligigs only, so with none left it shut Pine Tree --
# the best measured field, 106-205M honey/h -- from 19 Oct 01:00 to the end of
# the window (and 17 Oct 04:20-09:29, 18 Oct 01:05-06:00) while 9 of 15
# Micro-Converters were held; the bot gathered Rose at ~62M/h instead.
# HOME_BAR_COUNTS_MICRO = False puts the old Whirligig-only bar back.
HOME_P_FLOOR = 0.6
# AND THE PRICE OF A MISS FOLLOWS THE SAME COUNT: the block above measured 19 of
# 21 stranded walks rescued, no rejoin, yet every miss was priced as the failed
# walk plus REJOIN_SECONDS. With a rescue item held a miss is the failed walk
# plus the respawn's way back to a trip (run_farm RESPAWN_TO_TRIP_SECONDS, 9 s).
# LOOK-ONLY (MISS_RESCUE_PRICED_LIVE = False): the old price is kept and the
# reason says what the rescued price would be.
# ponytail: the rescue item's own worth is not charged; add it if rescues run out.
MISS_RESCUE_PRICED_LIVE = False
RESCUED_MISS_SECONDS = 9.0
HOME_FLOOR_VERDICTS = 6
HOME_BAR_COUNTS_MICRO = True


def home_walk_bar(good: int, bad: int, p_land: float,
                  whirligigs: int | None, micro_converters: int | None = 0) -> str | None:
    """Why a field is shut while its walk home is this unsure and nothing can
    rescue a miss, or None. A count of None = not counted, held as none."""
    rescues = (whirligigs or 0) + ((micro_converters or 0) if HOME_BAR_COUNTS_MICRO else 0)
    if good + bad < HOME_FLOOR_VERDICTS or p_land >= HOME_P_FLOOR or rescues:
        return None
    return (f"the walk home landed {good} of its last {good + bad} (P {p_land:.2f}, "
            f"under {HOME_P_FLOOR}) and no Whirligig or Micro-Converter is held to "
            f"rescue a miss — a miss is a rejoin and the Wealth Clock streak")


@dataclass
class Situation:
    """What is true right now. Any of it may be unknown, and unknown is not 0."""
    pollen: int | None = None
    capacity: int | None = None
    honey: int | None = None
    where: str | None = None

    @property
    def carrying(self) -> int:
        return self.pollen or 0

    @property
    def fullness(self) -> float | None:
        if self.pollen is None or not self.capacity:
            return None
        return self.pollen / self.capacity


@dataclass
class FieldScore:
    """One candidate field, scored, with the reasoning kept."""
    field: str
    score: float
    rate: float | None = None          # measured pollen/s, None if never farmed
    flowers: int = 0
    safe: bool = True
    mobs: tuple[str, ...] = ()
    bees_required: int = 0
    reachable: bool = True
    why: str = ""
    # The measured chance that the route the trip would take lands here
    # (Planner.route_odds), even odds for a route never judged; None when
    # nothing prices the route.
    p_land: float | None = None
    # A field a quest names while the owner has put quests first, or one whose
    # quest step one trip finishes: it ranks ahead of the others once it may
    # be gone to (`quests.first`, QUICK_QUEST_SHARE).
    quest_first: bool = False
    # ...and which of the two: the quick quest's trip is watched for the step
    # being gathered (run_farm `quest_step_done`), as `quests.first` trips are.
    quick_quest: bool = False
    # The pollen a quest still owes from this field fits one trip at its
    # measured rate (QUICK_QUEST_SHARE), whichever rule put it first: among
    # the fields put first, these go first (`rank`).
    one_trip: bool = False
    # A field a priority giver's quest names (questneeds.PRIORITY_GIVERS, the
    # Polar Bear): among the fields put first, these go first of all (`rank`).
    priority: bool = False

    @property
    def pretty(self) -> str:
        return self.field.replace("_", " ")


@dataclass
class Decision:
    """What to do, why, and what was turned down."""
    action: str                         # "convert" | "gather" | "wait"
    field: str | None = None
    why: str = ""
    alternatives: list[FieldScore] = dc_field(default_factory=list)
    # P3: the chance this field was the one picked (1.0 for the ranking's
    # own deterministic choice), for judging a new rule from the ledger
    p_field: float = 1.0

    def describe(self) -> str:
        where = f" in the {self.field.replace('_', ' ')} field" if self.field else ""
        return f"{self.action}{where} — {self.why}"


# How long a gathering stint may last when nothing has ever killed us there.
# Not a preference: beyond the time it takes to fill the backpack, gathering
# earns literally nothing, so this only has to be generous enough that the
# BACKPACK is what ends the trip. MEASURED, a good stint gathers about 1,050
# pollen/sec into a 955,877 backpack, so ninety percent of it fills in ~820 s.
LONGEST_TRIP_SECONDS = 1_200.0


def best_trip_seconds(overhead_seconds: float, death_rate: float,
                      fill_seconds: float | None = None,
                      longest: float = LONGEST_TRIP_SECONDS) -> float:
    """How long to gather before heading home, from measured numbers only.

    WHY THIS IS NOT A CONSTANT. The inherited one is `FARM_SECONDS=420` from
    BeeTuxMacro's config, and it is the wrong shape of answer: the right trip
    length depends on how long the round trip costs and on how often this
    field kills us, and neither is the same for every field or every account.

    MEASURED here: a 423 s stint gathered 445,029 pollen, which is 47% of the
    backpack, and the round trip around it cost about 108 s. So the cap was
    ending trips less than halfway full while paying the full overhead every
    time -- the worst of both.

    THE ARITHMETIC. Banked pollen per second of wall clock is

        rate * T * exp(-lambda*T) / (T + H)

    where H is the round-trip overhead and lambda the deaths per second in
    this field. A death costs the whole backpack, which is why survival is a
    multiplier and not a subtraction. Setting the derivative to zero:

        1/T - lambda - 1/(T+H) = 0   =>   T**2 + H*T - H/lambda = 0
        T = (-H + sqrt(H**2 + 4H/lambda)) / 2

    With lambda = 0 that goes to infinity, which is correct and also useless:
    with nothing killing us the only reason to come home is a full backpack.
    So the fill time bounds it, and `longest` bounds that.

    `fill_seconds` is None when the fill rate is not known yet, in which case
    this stays conservative and returns the overhead-based figure only.
    """
    overhead = max(0.0, float(overhead_seconds))
    limit = float(longest)
    if fill_seconds is not None and fill_seconds > 0:
        limit = min(limit, float(fill_seconds))

    if death_rate <= 0:
        # Nothing has killed us here. Gather until the backpack says stop.
        return limit

    best = (-overhead + math.sqrt(overhead ** 2
                                  + 4 * overhead / death_rate)) / 2
    return max(60.0, min(limit, best))


class Planner:
    """Picks the next thing to do from measured facts, and explains it."""

    def __init__(self, fields: dict, notes=None, reachable=None,
                 worth_protecting: int = WORTH_PROTECTING,
                 convert_at: float = 0.9, prefer_colour: str | None = None,
                 trip_seconds: float = TRIP_SECONDS, quest_needs=None,
                 walk_home=None):
        self.fields = dict(fields or {})
        self.notes = notes
        # WHICH FIELDS THERE IS A WAY BACK FROM. A trip to any other field
        # ends in a rejoin (REJOIN_SECONDS). `None` means "do not know, price
        # every field the same", which is only correct in tests.
        self.walk_home = set(walk_home) if walk_home is not None else None
        # WHICH FIELDS THERE IS A WAY TO. Without this the planner happily
        # chose the Sunflower Field -- safe, 660 flowers, needs no bees, and
        # NO RECORDED ROUTE FROM THE HIVE. Choosing somewhere the bot cannot
        # walk to is not a decision, it is a wish. `None` means "do not know,
        # allow everything", which is only correct in tests.
        self.reachable = set(reachable) if reachable is not None else None
        # Which colour this hive is built around, if any. See COLOUR_BONUS.
        self.prefer_colour = prefer_colour
        self.worth_protecting = int(worth_protecting)
        self.convert_at = float(convert_at)
        self.explore = 0.0                  # P3: run_farm sets EXPLORE_FIELD
        # {field: minutes lost there last hour}, from reflect.field_minutes;
        # run_farm sets it each review and hands it to v2_rank (LEAK_FLOOR).
        self.leak_minutes: dict = {}
        self.rng = random.Random()
        # How long a gathering stint lasts, used only to turn a death RATE
        # into the chance of losing one trip. Matches the farm loop's cap.
        self.trip_seconds = float(trip_seconds)
        # What the quest menu says is still outstanding, by colour. See
        # brain/questneeds; None means the quests have not been read.
        self.quest_needs = quest_needs
        # The needs of the priority givers' quests alone (questneeds
        # .load_priority), or None: a field they name ranks first of the first.
        self.priority_needs = None
        # Whether a field the quests name outright ranks first (QUEST_BONUS,
        # `quests.first`), from the owner's setting.
        self.quest_first = False
        # THE TRIP LEDGER (brain/ledger.Ledger), for `_rate_source`'s
        # "trips". Set by the caller; None ranks on the field notes alone.
        self.ledger = None
        self._trips: dict = {}
        # WHERE THE ROUTE THERE ACTUALLY DELIVERS (brain/skills, DESIGN 8dy).
        # `route_odds(field)` returns (P(land), the words) for the route a
        # trip to `field` would take now -- even odds for one never judged --
        # or None when there is no such route to price. Set by the caller;
        # None ranks as if every route landed.
        self.route_odds = None
        # AND ITS WINDOW: `route_window(field)` returns (verdicts in it, when it
        # began -- 0.0 for one never restarted) for that same route, or None.
        # Set by the caller; None gives no trial trips (QUEST_ROUTE_TRIAL).
        self.route_window = None
        # AND HOW OFTEN THE WALK HOME LANDS: `home_odds(field)` returns
        # (P(the walk home lands), the words) for a field with a recorded walk
        # home -- the same posterior as the routes out (brain/skills) -- or None.
        # Set by the caller; None prices every walk home as landing.
        self.home_odds = None
        # A FIELD SHUT ON THE CLOCK (world/timers FieldGuard): `closed(field)`
        # returns why a trip there cannot be made now -- its guard is there,
        # or arrives too soon for a trip worth taking -- or None. Set by the
        # caller, which owns the clock; None shuts nothing.
        self.closed = None
        # THE BEE MENU'S OWN COUNT: `bees_read()` returns the hive's bee count
        # from the menu's header (act/beemenu.count_for_gates) or None. Set by
        # the caller; None leaves `bees_at_least` to the fields gathered.
        self.bees_read = None

    def _trips_for(self, name: str) -> dict | None:
        """This field's ledger totals, as read at the top of `rank`."""
        return self._trips.get(name)

    def _read_trips(self) -> None:
        if self.ledger is None:
            self._trips = {}
            return
        try:
            self._trips = dict(self.ledger.pollen_by_field() or {})
        except Exception:
            self._trips = {}

    def _best_guess(self) -> float:
        """The highest flower-and-quest guess among the fields with no
        measured rate -- the yardstick the curiosity bonus is shared out
        against, so the unmeasured fields keep their own order."""
        best = 0.0
        for name, body in self.fields.items():
            note = self.notes.known(name) if self.notes is not None else None
            if note is not None and note.pays:
                continue
            guess = self._guess_rate(int(body.get("flowers", 0) or 0), body.get("yield"))
            value, _note = self._quest_value(name)
            if value > 0:
                guess *= 1.0 + QUEST_BONUS * value
            best = max(best, guess)
        return best

    # ---- progression, derived rather than configured ----------------------
    def bees_at_least(self) -> int:
        """A lower bound on the bee count, proved by where we have gathered.

        Gathering in a field requires its bee count, so having earned pollen
        there IS the proof. Returns 0 when nothing has been farmed yet, which
        is honest: it means we have no evidence, not that the hive is empty.

        AND WHAT THE BEE MENU COUNTED (`bees_read`), whichever is more. Fields
        alone are a dead end on a NEW account (docs/pending/progression-
        proof.md, gap F1): a field is proved only by gathering there, and a
        gated field is never chosen until it is proved, so a hive grown to 5
        bees would farm the starting fields for ever.
        """
        try:
            best = int((self.bees_read() if self.bees_read else 0) or 0)
        except Exception:
            best = 0
        if self.notes is None:
            return best
        for name, note in getattr(self.notes, "notes", {}).items():
            # been_here, not pays: the reward feed naming a field proves we
            # gathered there even before any rate has been measured.
            if not getattr(note, "been_here", False):
                continue
            body = self.fields.get(name) or {}
            best = max(best, int(body.get("bees_required", 0) or 0))
        return best

    # ---- what the quests want -------------------------------------------
    def _priority_names(self, field: str) -> bool:
        """Does a priority giver's quest (Planner.priority_needs) need this
        field -- its pollen by name, or a mob that lives in it?"""
        needs = self.priority_needs
        if needs is None:
            return False
        try:
            if int(needs.field_remaining(field)) > 0:
                return True
            if not QUEST_FIELDS_FOR_MOBS:
                return False
            wanted = needs.mobs_wanted() or {}
        except Exception:
            return False
        return any(m in wanted for m in (self.fields.get(field, {}).get("mobs") or []))

    def _quest_names(self, field: str) -> bool:
        """Does an outstanding quest need THIS field -- pollen from it by
        name, or a mob that lives in it? (Not a colour: any field of that
        colour serves one of those.)"""
        needs = self.quest_needs
        if needs is None:
            return False
        try:
            if int(needs.field_remaining(field)) > 0:
                return True
            if not QUEST_FIELDS_FOR_MOBS:
                return False
            wanted = needs.mobs_wanted() or {}
        except Exception:
            return False
        return any(m in wanted for m in (self.fields.get(field, {}).get("mobs") or []))

    def _colour_first(self, scored: list) -> None:
        """COLOUR_STEP_FIRST: for each colour a quest still owes, put first
        the reachable, measured field with the most pollen/s of that colour
        (`rate` x its petal share). A field never looked at has no share and
        is skipped -- no guess."""
        needs = self.quest_needs
        if not (COLOUR_STEP_FIRST and self.quest_first and needs is not None
                and self.notes is not None):
            return
        for colour in ("blue", "red", "white"):
            try:
                owed = int(needs.remaining(colour))
            except Exception:
                owed = 0
            if owed <= 0:
                continue
            best, best_rate, best_share = None, 0.0, 0.0
            for s in scored:
                if not (s.reachable and s.score > 0 and s.rate):
                    continue
                note = self.notes.known(s.field)
                share = note.colour_share(colour) if note is not None else None
                if share and float(s.rate) * share > best_rate:
                    best, best_rate, best_share = s, float(s.rate) * share, share
            if best is None:
                continue
            best.quest_first = True
            best.why += (f"; the quests still want {owed:,} {colour} pollen and this "
                         f"is the most {colour} pollen/s measured ({best_rate:,.0f}/s: "
                         f"{best.rate:,.0f} x {best_share:.0%} {colour}), so it goes "
                         f"first (quests.first)")

    def _quest_retry(self, field: str, failures: int, note=None) -> str:
        """Why a field given up on (TRAVEL_FAILURES_TO_GIVE_UP) is tried again
        for a quest, or '' when it is not: its route lands now
        (QUEST_ROUTE_RETRIES), or it has had no trial in its present shape
        (QUEST_ROUTE_TRIAL)."""
        if self.quest_needs is None or self.route_odds is None:
            return ""
        try:
            owed = int(self.quest_needs.field_remaining(field))
            odds = self.route_odds(field) if owed > 0 else None
            p_land = float(odds[0]) if odds else 0.0
        except Exception:
            return ""
        said = (f"; given up after {failures} trips that got nowhere, but a quest "
                f"still wants {owed:,} pollen from here")
        if (p_land >= QUEST_RETRY_P_LAND
                and failures < TRAVEL_FAILURES_TO_GIVE_UP + QUEST_ROUTE_RETRIES):
            return (f"{said} and the route there lands now (P {p_land:.2f}), "
                    f"so it gets another trip")
        failed_at = float(getattr(note, "failed_at", 0.0) or 0.0)
        if p_land >= QUEST_RETRY_P_LAND and time.time() - failed_at >= QUEST_RETRY_AFTER_S:
            return (f"{said} and the route there lands now (P {p_land:.2f}); its "
                    f"last miss was over {QUEST_RETRY_AFTER_S / 3600:.0f} h ago, so it "
                    f"gets another trip")
        if (odds and owed >= QUEST_PROBE_MIN_OWED
                and time.time() - failed_at >= QUEST_PROBE_AFTER_S):
            return (f"{said}; its route lands only P {p_land:.2f}, but its last miss "
                    f"was over {QUEST_PROBE_AFTER_S / 3600:.0f} h ago and the quest owes "
                    f"this much, so one probe trip (its frames show where it goes wrong)")
        if not (odds and QUEST_ROUTE_TRIAL and self.route_window is not None):
            return ""
        try:
            verdicts, since = self.route_window(field)   # None, no route: no trial
            verdicts, since = int(verdicts), float(since or 0.0)
        except Exception:
            return ""
        if verdicts or float(getattr(note, "failed_at", 0.0) or 0.0) > since:
            return ""
        changed = (f"not been judged since it changed "
                   f"({time.strftime('%m-%d %H:%M', time.localtime(since))})"
                   if since else "never been judged")
        return (f"{said} and the route there has {changed}, so it gets one trial "
                f"trip -- landing lifts the ban, a miss keeps it until the route "
                f"changes again")

    def _bloom_value(self, needs, field: str) -> tuple[float, str]:
        """(value, why) for the bloom-petal steps this field serves, or (0, '')."""
        try:
            owed = [b for b in (getattr(needs, "blooms", None) or []) if b.remaining > 0]
        except Exception:
            return 0.0, ""
        if not owed:
            return 0.0, ""
        from . import knowledge
        where = knowledge._load("blooms.yaml").get("colour_fields") or {}
        for b in owed:
            if b.field and b.field == field:
                return 1.0, (f"; a quest wants {b.remaining:,} more {b.colour} bloom "
                             f"petals from here specifically")
        for b in owed:
            if not b.field and field in (where.get(b.colour) or []):
                return BLOOM_FIELD_VALUE, (
                    f"; a quest wants {b.remaining:,} more {b.colour} bloom petals and "
                    f"{b.colour} blooms spawn here (rarely; walk into the petals)")
        return 0.0, ""

    def _valuable_retry(self, field: str, note, rate, source) -> str:
        """Why a field given up on is tried again for its honey alone, or '':
        its RECENT measured rate is at least VALUABLE_RETRY_SHARE of the best
        measured field, and the quest retry's own odds and clock hold
        (QUEST_RETRY_P_LAND, QUEST_RETRY_AFTER_S). MEASURED 2026-10-20 22:12:
        Bamboo at 29,165/s (Pine Tree 25,573) banned after 6 misses, and no
        quest owed it pollen any more (its goo steps dropped: protips rule 7),
        so nothing ever let it back."""
        if source != "recent" or not rate or self.route_odds is None:
            return ""
        try:
            # the best RECENT rate of any field (the yardstick is lifetime figures)
            best = max((r for r, src in (
                _rate_source(self.notes.known(n), trips=self._trips_for(n))
                for n in self.fields if self.notes.known(n) is not None)
                if src == "recent" and r), default=0.0)
            odds = self.route_odds(field)
            p_land = float(odds[0]) if odds else 0.0
        except Exception:
            return ""
        if not best or float(rate) < VALUABLE_RETRY_SHARE * float(best):
            return ""
        failed_at = float(getattr(note, "failed_at", 0.0) or 0.0)
        if p_land < QUEST_RETRY_P_LAND or time.time() - failed_at < QUEST_RETRY_AFTER_S:
            return ""
        return (f"; given up on, but it measured {float(rate):,.0f} pollen/s lately -- "
                f"near our best -- and the route there lands at even odds or better "
                f"(P {p_land:.2f}); its last miss was over "
                f"{QUEST_RETRY_AFTER_S / 3600:.0f} h ago, so it gets another trip")

    def _quest_value(self, field: str) -> tuple[float, str]:
        """How well this field serves the outstanding quest colours, 0..1.

        Returns (value, a sentence saying why) so the ranking can explain
        itself. Zero and an empty string when the quests have not been read,
        when nothing is outstanding, or when nobody has measured this field's
        flowers -- an unmeasured field gets no credit and no penalty.
        """
        needs = self.quest_needs
        if needs is None or self.notes is None:
            return 0.0, ""

        # A REQUIREMENT THAT NAMES THIS FIELD counts in full, and needs no
        # flower measurement to do it -- "Collect 150,000 Pollen from the
        # Strawberry Field" is satisfied by standing in the Strawberry Field
        # and nowhere else, whatever colour its flowers are.
        owed_here = 0
        try:
            owed_here = int(needs.field_remaining(field))
        except Exception:
            owed_here = 0
        if owed_here > 0:
            # (goo is gathered here too, from what the gumdrops cover: questneeds.goo)
            what = "goo" if field in (getattr(needs, "goo", None) or {}) else "pollen"
            return 1.0, (f"; a quest wants {owed_here:,} more {what} from "
                         f"here specifically")

        # A FIGHT A QUEST WANTS IS WON BY STANDING WHERE THE MOB LIVES. The
        # bot never seeks combat and runs from what it sees, but the bees
        # fight whatever comes near, and MEASURED 2026-09-23 "Defeat 3
        # Spiders" went 0/3 -> 1/3 -> 2/3 while it farmed the Spider Field.
        # So a field whose listed mobs include a wanted one gets the quest
        # tilt -- the same tilt a named field gets, and nothing more: the
        # danger rules below still stand, and a loaded bag still never goes
        # near a mob for a quest.
        try:
            wanted = needs.mobs_wanted()
        except Exception:
            wanted = {}
        if wanted:
            here = [m for m in (self.fields.get(field, {}).get("mobs") or [])
                    if m in wanted]
            if here:
                mob = here[0]
                pretty = mob.replace("_", " ")
                return 1.0, (f"; a quest wants {wanted[mob]} more {pretty}"
                             f"{'' if wanted[mob] == 1 else 's'} defeated and "
                             f"they live here — the bees fight while it gathers")

        # BLOOM PETALS (Q8 step 2): a bloom pops when pollen is gathered on it
        # and the player catches the falling petals, so they are only caught
        # where blooms of that colour spawn (data/knowledge/blooms.yaml, the
        # wiki's table). A step naming the field counts in full; a colour
        # field gets BLOOM_FIELD_VALUE, a tilt, not a takeover: the natural
        # spawn rate is unmeasured (docs/pending/blooms.md).
        bloom = self._bloom_value(needs, field)
        if bloom[0] > 0:
            return bloom

        outstanding = {c: needs.remaining(c) for c in ("blue", "red", "white")
                       if needs.remaining(c) > 0}
        if not outstanding:
            return 0.0, ""
        note = self.notes.known(field)
        if note is None or not getattr(note, "looked_at_flowers", False):
            return 0.0, ""

        total = float(sum(outstanding.values()))
        value = 0.0
        for colour, owed in outstanding.items():
            share = note.colour_share(colour)
            if share is None:
                continue
            value += (owed / total) * share
        if value <= 0:
            return 0.0, ""
        best = max(outstanding, key=lambda c: (note.colour_share(c) or 0.0)
                   * outstanding[c])
        share = note.colour_share(best) or 0.0
        return value, (f"; {share:.0%} of its flowers are {best}, and the "
                       f"quests still want {outstanding[best]:,} {best} pollen")

    # ---- putting a guess on the same scale as a measurement ---------------
    def _yardstick(self) -> tuple[float, int] | None:
        """(pollen/s, flowers) for the best field we have actually measured.

        THROUGH `_measured_rate`, WHICH WAS THE WHOLE PROBLEM. This is the
        third reader of "our best measured rate" and the last to get the
        floor. MEASURED 2026-09-23 03:56, against the live notes: the
        yardstick was `(1874.8, 594)` -- Cactus's three-second sample -- so
        every unfarmed field's guess was scaled off a rate five times anything
        real, and the whole board looked like this:

            spider 862, mountain_top 795, cactus 703, strawberry 677
            blue_flower 326, rose 298, dandelion 219

        Four places nobody had ever farmed, above every field that pays. The
        guess formula was not wrong; it was being handed a fake rate. Checked
        the other way, against the six fields with over 300 seconds on them,
        the guess was overestimating each by 1.7x to 7.9x:

            field        flowers  guessed  measured
            dandelion        648      511       223
            pineapple        759     1198       252
            blue_flower      731      577       337
            rose             620      978       398
            pine_tree        713     1125       288
            mushroom         736     1162       148

        With a real yardstick those ratios land between 0.7 and 1.6, so
        `UNMEASURED_PENALTY` is carrying its weight and no separate
        calibration factor is needed: the formula already calibrates itself
        against measurement, as long as what it is handed IS one.
        """
        if self.notes is None:
            return None
        best = None
        for name in self.fields:
            rate, source = _rate_source(self.notes.known(name),
                                        over=YARDSTICK_ENOUGH_SECONDS,
                                        trips=self._trips_for(name))
            if rate is None or source == "floor":
                continue
            flowers = int((self.fields.get(name) or {}).get("flowers", 0) or 0)
            if flowers <= 0:
                continue
            if best is None or rate > best[0]:
                best = (float(rate), flowers)
        return best

    def _best_measured(self) -> float | None:
        """The best pollen/s any field has actually paid, over enough seconds
        to mean something, or None if nothing has.

        THE YARDSTICK HAS TO BE SOLID, because every unmeasured field's
        curiosity bonus is a multiple of it (EXPLORE_OPTIMISM) -- so one noisy
        sample raises the score of every field the bot has never visited.
        MEASURED 2026-09-23 03:05: a three-second visit to Cactus recorded
        5,625 pollen, which is 1,875 pollen/s -- seven times the best real
        rate on the account -- because a single token pickup lands in one
        sample. `MEASURED_ENOUGH_SECONDS` is the floor at which a rate stops
        being one lucky interval; below it a field is treated as unmeasured,
        which is what it is.
        """
        if self.notes is None:
            return None
        rates = [r for r, source in (_rate_source(self.notes.known(n),
                                                  over=YARDSTICK_ENOUGH_SECONDS,
                                                  trips=self._trips_for(n))
                                     for n in self.fields)
                 if r is not None and source != "floor"]
        return max(rates) if rates else None

    def _guess_rate(self, flowers: int, yield_tag: str | None = None) -> float:
        """What an unfarmed field would probably pay, in pollen per second.

        `yield_tag` is world.yaml's `yield:` for the field. The one value it
        takes today is "lowest", and it comes from the owner, 2026-09-22,
        after watching the bot farm the starter fields all day: "the blue
        flower field and dandylion are the lowest rewarding for just honey
        since they give the least amount of pollen". A flower count cannot
        say that -- Blue Flower has the MOST flowers in the starter zone --
        so the fact is recorded separately and honoured here by halving the
        guess. Halving is not a rate claim; it is an ordering: a field the
        owner says is worst ranks below any unmeasured field they did not say
        that about, and below anything measured to pay. A measured rate is
        never touched by this -- once a field is farmed, the measurement
        speaks for itself.

        WHY THIS IS NOT JUST `flowers * penalty`, which is what it used to be.
        That put measured fields and guessed ones on DIFFERENT SCALES -- one
        in pollen per second, the other in flowers -- and the guesses were
        numerically much larger, so measuring a field honestly DEMOTED it.

        MEASURED, 2026-09-20, and it nearly cost the night: the bot farmed the
        Pineapple Patch, recorded 170 pollen/s there, and immediately ranked
        it below the Pine Tree Forest on a score of 334 that was never a rate
        at all -- it was 713 wiki flowers times a half. Pine Tree is the most
        dangerous field it can reach, with two mantises and the Werewolf, and
        it died there within a minute. The bot had taught itself to always
        prefer whatever it had not measured yet.

        So a guess is now expressed in the same unit as a measurement, by
        scaling the best rate we have by relative flower count and then
        discounting it for being a guess. With nothing measured yet there is
        no yardstick, and the old flower-count ordering is kept -- every field
        is then scored the same way, so the ordering is still meaningful even
        though the number is not a rate.
        """
        yardstick = self._yardstick()
        worst = LOWEST_YIELD_FACTOR if yield_tag == "lowest" else 1.0
        if yardstick is None:
            return flowers * UNMEASURED_PENALTY * worst
        rate, reference_flowers = yardstick
        return rate * (flowers / reference_flowers) * UNMEASURED_PENALTY * worst

    # ---- scoring ----------------------------------------------------------
    def _all_given_up(self, bees: int) -> bool:
        """Has every field we could otherwise reach failed too often?

        THE SAFETY VALVE FOR TRAVEL_FAILURES_TO_GIVE_UP. Giving up on a field
        whose route does not work is right; giving up on ALL of them leaves the
        planner with nothing to choose and the bot standing at the hive doing
        nothing, which is worse than a failed trip. A failed trip costs one
        cycle; sitting still costs the night.

        So when the rule would empty the board it is set aside for that
        decision, and every score says so.
        """
        if self.notes is None:
            return False
        live = 0
        blocked = 0
        for name, body in self.fields.items():
            required = int(body.get("bees_required", 0) or 0)
            if required > bees and required != 0:
                continue
            if not (self.reachable is None
                    or ROUTER_ALIASES.get(name, name) in self.reachable):
                continue
            note = self.notes.known(name)
            failures = int(getattr(note, "travel_failures", 0) or 0) if note else 0
            if failures >= TRAVEL_FAILURES_TO_GIVE_UP:
                blocked += 1
            else:
                live += 1
        return blocked > 0 and live == 0

    def rank(self, situation: Situation) -> list[FieldScore]:
        """Every field we could go to, best first, each with its reasoning."""
        bees = self.bees_at_least()
        carrying = situation.carrying
        scored: list[FieldScore] = []
        forgive = self._all_given_up(bees)
        self._read_trips()

        for name, body in self.fields.items():
            required = int(body.get("bees_required", 0) or 0)
            safe = bool(body.get("safe", False))
            mobs = tuple(body.get("mobs") or ())
            flowers = int(body.get("flowers", 0) or 0)
            note = self.notes.known(name) if self.notes is not None else None
            # HOW OFTEN THE ROUTE HERE HAS FAILED, in a row. Read once, at the
            # top, because two separate rules need it: the bar below and the
            # curiosity discount. See TRAVEL_FAILURES_TO_GIVE_UP.
            failures = int(getattr(note, "travel_failures", 0) or 0) if note else 0
            trips = self._trips_for(name)
            rate, source = _rate_source(note, trips=trips)

            # Proven beats presumed. A field we have farmed is scored on what
            # it actually paid us; one we have not is ranked on flower count
            # and discounted for being a guess.
            if rate is not None:
                score = float(rate)
                if source == "recent":
                    # "measured ..." first, the shape stream/voice's REASONS reads
                    why = (f"measured {rate:,.0f} pollen/s over its last "
                           f"{trips.get('recent_trips', 0)} trips here "
                           f"({float(trips.get('recent_seconds') or 0):.0f}s of gathering)")
                elif source == "paid":
                    why = f"measured {rate:,.0f} pollen/s over {note.seconds:.0f}s here"
                elif source == "trips":
                    why = (f"paid {rate:,.0f} pollen/s over {trips.get('trips', 0)} "
                           f"trip(s), {float(trips.get('seconds') or 0):.0f}s of "
                           f"gathering, in the trip ledger")
                elif source == "floor":
                    why = (f"at least {rate:,.0f} pollen/s over {note.seconds:.0f}s "
                           f"here — a floor: the counter was illegible for part of it")
                else:
                    why = (f"the HUD's own counter printed {rate:,.0f} pollen/s here "
                           f"over {note.printed_samples} readings — the counter's "
                           f"own movement runs about a quarter higher (token lumps), "
                           f"and it never gave a legible pair here")
            else:
                score = self._guess_rate(flowers, body.get("yield"))
                why = f"never farmed here; {flowers} flowers on the wiki"
                if body.get("yield") == "lowest":
                    why += "; the owner says this is one of the lowest-yield fields"
                colour = body.get("colour")
                if self.prefer_colour and colour == self.prefer_colour:
                    score *= COLOUR_BONUS
                    why += f"; {colour}-leaning, which suits a {colour} hive"

            # WHAT SHARE OF THIS FIELD'S POLLEN THIS HIVE CAN USE.
            #
            # Applied to MEASURED fields too, which the block above never
            # was: it sat in the `else`, so a field the bot had farmed got no
            # colour consideration at all, and it read `body["colour"]` -- a
            # single label from the knowledge base that is None for most
            # fields -- rather than the petal counts vision has actually
            # measured.
            #
            # THE OWNER, 2026-09-23: white pollen (Spider) gives their hive
            # little; the bees are good at blue and a little at red. The
            # bot's own counts agree
            # about the field: Spider is 76% white, the highest on the board.
            #
            # This does NOT claim the measured rate is wrong. Spider really
            # did pay 944 pollen/s and that pollen really did become honey at
            # the same rate as anyone's. It is a preference for the hive they
            # is BUILDING -- see COLOUR_WORTH -- and it is said out loud in
            # every score so the trade stays visible.
            usable = colour_worth(getattr(note, "petals", None))
            if usable is not None and COLOUR_WEIGHT > 0:
                keep = (1.0 - COLOUR_WEIGHT) + COLOUR_WEIGHT * usable
                score *= keep
                why += (f"; {usable:.0%} of its pollen is a colour these bees "
                        f"are good at")

            # WHAT THE QUESTS WANT, weighted by how much is still owed and
            # by what this field is MEASURED to be made of. A field nobody has
            # looked at contributes nothing here -- not a zero, which would
            # read as "no flowers of that colour", but no opinion at all.
            quest_value, quest_note = self._quest_value(name)
            quest_first = bool(self.quest_first and self._quest_names(name))
            quick_quest = one_trip = False
            if quest_value > 0:
                score *= 1.0 + QUEST_BONUS * quest_value
                why += quest_note
            # B5 / P2: brain/goalvalue.field_quest_value prices the same wanted
            # mobs the QUEST_BONUS tilt above already weighs -- adding it here
            # counted them twice (test_a_wanted_mob_tilts_the_ranking_toward_its_field),
            # so the measured tilt stays and goalvalue serves the errands' G term.
            owed = 0
            if (rate and self.quest_needs is not None
                    and (self.walk_home is None
                         or ROUTER_ALIASES.get(name, name) in self.walk_home)):
                try:
                    owed = int(self.quest_needs.field_remaining(name))
                except Exception:
                    owed = 0
                trip = float(self.trip_seconds or TRIP_SECONDS)
                one_trip = 0 < owed <= float(rate) * trip * QUICK_QUEST_SHARE
            priority = bool(quest_first and self._priority_names(name))
            if quest_first:
                why += "; quests first (quests.first), so it ranks ahead of the rest"
                if priority:
                    why += ("; a Polar Bear quest wants it -- each one is 1.05x bee "
                            "energy for good -- so it goes before the other quest fields")
                # AND A STEP ONE TRIP FINISHES BEFORE A LONG ONE. MEASURED
                # 2026-10-06 09:05: the Polar Bear's "180,000 Pollen from the
                # Sunflower Field" owed 37,752 while Star Journey 2 owed
                # Strawberry 12.3M -- about 2.4 h at its rate -- and with both
                # put first the higher score went first, so the Polar Bear's
                # hand-in waited the hours behind it.
                if one_trip:
                    why += (f"; only {owed:,} more pollen is owed here, one trip's worth, "
                            f"so it goes before the other quest fields")
            elif one_trip:
                quest_first = quick_quest = True
                why += (f"; a quest needs only {owed:,} more pollen from here — "
                        f"about {max(1, round(owed / float(rate) / 60))} min, one trip "
                        f"finishes it, so it goes first")

            # CURIOSITY, bounded. See EXPLORE_OPTIMISM.
            #
            # IT USED TO FLATTEN EVERY UNMEASURED FIELD INTO ONE NUMBER.
            # MEASURED 2026-09-23 01:05: with an empty backpack the ranking
            # read `stump 764.6, cactus 764.6, mountain_top 764.6, spider
            # 764.6, bamboo 764.6` -- nine fields on exactly the same score,
            # because the optimistic value REPLACED the score that carried
            # the flower count and the quest bonus. The order among them was
            # then whatever the dictionary happened to give, and Clover --
            # 754 flowers, the most of any field, with a quest asking for
            # 3,000,000 pollen from it specifically -- had never been farmed
            # once all night.
            #
            # The optimism is still the same size (a field we have not
            # measured is assumed as good as our best), but the evidence we
            # DO have about it breaks the tie: its flower count, which this
            # file already calls a ranking, and what the quests want from it.
            # So `optimistic` is scaled by how this field's own guess compares
            # with the best guess among the unmeasured ones, never by more
            # than 1 and never by less than EXPLORE_TIE_FLOOR.
            gathered = float(note.seconds) if note is not None else 0.0
            best = self._best_measured()
            own = rate
            # A FLOOR PROVES NOTHING IS POOR: it is what was LEGIBLE, and the
            # best it is compared with is a real rate. See `_rate_source`.
            poor = bool(own is not None and source != "floor" and best
                        and own < EXPLORE_POOR_SHARE * best)
            if gathered < EXPLORE_SECONDS and best and poor:
                why += (f"; paid {own:.0f} pollen/s, under a quarter of our "
                        f"best field — not explored further")
            if gathered < EXPLORE_SECONDS and best and not poor:
                left = 1.0 - gathered / EXPLORE_SECONDS
                # A FIELD THE ROUTE CANNOT REACH KEEPS FULL CURIOSITY, and
                # that is the trap the time term above cannot close. `left`
                # shrinks the bonus as seconds are SPENT IN the field -- but a
                # trip that never arrives spends none there, so `gathered`
                # stays 0 and the bonus stays at maximum right up to the
                # `TRAVEL_FAILURES_TO_GIVE_UP` bar. Every trip in between is
                # a whole trip for nothing.
                #
                # MEASURED over the night's 140 recorded trips
                # (var/trips.jsonl): nine of them earned exactly zero pollen
                # between them over 2,219 seconds -- sunflower 2, clover 4,
                # mountain_top 1, spider 1, pine_tree 1 -- while the fields
                # that pay were sitting measured and ranked below them.
                #
                # So the bonus is discounted by how many times the route has
                # already failed, running linearly down to the bar it already
                # has. One failure is three attempts (a journey retries
                # inside itself), so a doubtful route keeps most of its
                # benefit of the doubt; by two it loses to a proven field.
                if failures and TRAVEL_FAILURES_TO_GIVE_UP > 0:
                    trust = max(0.0, 1.0 - failures / TRAVEL_FAILURES_TO_GIVE_UP)
                    left *= trust
                optimistic = best * EXPLORE_OPTIMISM * left
                ceiling = self._best_guess() or score or 1.0
                share = max(EXPLORE_TIE_FLOOR, min(1.0, score / ceiling)) if ceiling else 1.0
                optimistic *= share
                if optimistic > score:
                    score = optimistic
                    why += ("; never properly measured — assumed as good as "
                            "our best field until one trip says otherwise"
                            if gathered == 0 else
                            f"; only {gathered:.0f}s measured here, worth finishing")

            routed = (self.reachable is None
                      or ROUTER_ALIASES.get(name, name) in self.reachable)
            # A ROUTE IN THE GRAPH IS NOT A ROUTE THAT WORKS. `routed` asks
            # the route graph; this asks the runs -- `failures`, read at the
            # top of this loop. See TRAVEL_FAILURES_TO_GIVE_UP.
            gave_up = failures >= TRAVEL_FAILURES_TO_GIVE_UP and not forgive
            retry = self._quest_retry(name, failures, note) if gave_up and routed else ""
            if gave_up and routed and not retry:
                retry = self._valuable_retry(name, note, rate, source)
            if retry:
                gave_up = False
                why += retry
            reachable = routed and not gave_up and (required <= bees or required == 0)
            shut = None
            if self.closed is not None:
                try:
                    shut = self.closed(name)
                except Exception:
                    shut = None
            if not routed:
                score = 0.0
                why = "no recorded route from the hive to there"
            elif gave_up:
                score = 0.0
                why = (f"the recorded route to there has failed to arrive "
                       f"{failures} trips in a row, so it is not worth another "
                       f"until a working route is recorded")
            elif required > bees and required != 0:
                score = 0.0
                why = (f"needs {required} bees and we have only proved "
                       f"{bees} by gathering")
            elif shut:
                # AHEAD OF THE DANGER RULES, which price a mob that may or may
                # not come near: this one is on the field, on a timetable.
                score = 0.0
                why = shut
            elif note is not None and note.deaths:
                # WHAT ACTUALLY HAPPENS HERE beats what the wiki lists here.
                # The mob list is the same for everyone; the death rate is
                # this character's, with this walkspeed and this pattern. One
                # death costs the whole backpack, so a field that kills is
                # worth less than its rate says by exactly the chance of not
                # coming home -- which is what `survival_over` computes from
                # the deaths and the seconds actually spent there.
                lived = note.survival_over(self.trip_seconds)
                # NEVER A REWARD FOR DYING: a guarded field keeps the wiki's
                # discount until its own record is worse. `survival_over`
                # REPLACED it, so one death (spider, 1 in 8,785 s, 0.95)
                # scored 27% above a clean guarded field at 0.75 (run-406
                # 07:20:59). Monotone now: a death can only lower a score.
                factor = lived if safe else min(DANGER_DISCOUNT, lived)
                score *= factor
                why += (f"; died here {note.deaths} time"
                        f"{'' if note.deaths == 1 else 's'} in "
                        f"{note.seconds:.0f}s, so about a {1 - lived:.0%} "
                        f"chance of losing the trip")
                if factor < lived:
                    why += (f"; guarded by {', '.join(mobs) or 'mobs'}, so the "
                            f"guarded discount (x{DANGER_DISCOUNT}) still applies")
                if not safe and carrying >= self.worth_protecting:
                    score = 0.0
                    why = (f"carrying {carrying:,} pollen when this trip was "
                           f"planned, and it has already "
                           f"killed us {note.deaths} time"
                           f"{'' if note.deaths == 1 else 's'} — not worth it")
            elif not safe:
                # A LOADED BACKPACK NEVER GOES SOMEWHERE A MOB CAN TAKE IT,
                # and an expected-value rule was tried here on 2026-09-23 and
                # WITHDRAWN. The arithmetic looked convincing -- `danger_of`
                # puts a 1,200-second trip to Clover at a 3% chance of dying,
                # so 300,000 pollen risks 9,000 against a 460,000 gain -- but
                # its probability is this character's POOLED death rate, and
                # every second of that pool was spent in Dandelion and Blue
                # Flower, which no mob guards. Using it to price a mantis is
                # the optimistic reading of no information, which is the one
                # thing this file exists not to do. The measured loss that
                # put this rule here was 361,439 pollen.
                #
                # Guarded fields are still explored -- with an EMPTY bag,
                # through the branch below, which is how Stump was farmed at
                # 00:45 for 450 pollen/s. When there is a measured death rate
                # for a guarded field, that is the evidence that would let
                # this be priced rather than refused.
                if carrying >= self.worth_protecting:
                    score = 0.0
                    why = (f"carrying {carrying:,} pollen when this trip was "
                           f"planned, and it is guarded by "
                           f"{', '.join(mobs) or 'mobs'} — not worth the risk")
                else:
                    score *= DANGER_DISCOUNT
                    why += f"; guarded by {', '.join(mobs) or 'mobs'}"

            # SAID, NOT SCORED, AND NOT A BRANCH OF ITS OWN.
            #
            # This note used to be an `elif` in the chain above, which meant a
            # forgiven field skipped every rule after it -- the bee
            # requirement and, worse, the danger rules. A guarded field scored
            # full marks with a full backpack, which is the exact mistake that
            # cost 361,439 pollen on 2026-09-20 and the thing
            # `test_exploration_only_ever_spends_an_empty_backpack` exists to
            # prevent. Forgiveness is about whether a route is worth trying
            # again; it has nothing to say about mantises.
            if forgive and failures and score > 0:
                why += (f"; the route here has failed {failures} trips in a "
                        f"row, but so has every other route we could take, and "
                        f"trying is worth more than standing still")

            # A FIELD WITH NO WALK HOME PAYS FOR ITS REJOIN. The trip earns for
            # `trip_seconds` and then spends REJOIN_SECONDS getting back, so
            # its rate over the whole cycle is lower by exactly that share.
            # Priced, not refused: a field that pays three times as much is
            # still worth the rejoin. The streak the rejoin costs is said and
            # not scored -- see REJOIN_SECONDS.
            if (score > 0 and self.walk_home is not None
                    and ROUTER_ALIASES.get(name, name) not in self.walk_home):
                trip = float(self.trip_seconds or TRIP_SECONDS)
                score *= trip / (trip + REJOIN_SECONDS)
                why += (f"; no walk home is recorded from here, so the trip "
                        f"ends in a rejoin (~{REJOIN_SECONDS:.0f}s, and it drops "
                        f"the server session)")

            # A WALK HOME THAT MISSES ENDS IN A REJOIN ANYWAY. Its misses are
            # priced the way a field with no walk home is -- the trip's share of
            # its own cycle -- at the chance of a miss times what a miss costs:
            # the failed walk and the rejoin after it. Priced, not refused; the
            # Wealth Clock streak a rejoin also costs is said, not scored
            # (REJOIN_SECONDS).
            if (score > 0 and self.home_odds is not None and self.walk_home is not None
                    and ROUTER_ALIASES.get(name, name) in self.walk_home):
                try:
                    home = self.home_odds(name)
                except Exception:
                    home = None
                if home:
                    p_home, said_home, *held = home       # held: a rescue item counted
                    rescued = bool(held and held[0])
                    trip = float(self.trip_seconds or TRIP_SECONDS)
                    after = (RESCUED_MISS_SECONDS if rescued and MISS_RESCUE_PRICED_LIVE
                             else REJOIN_SECONDS)
                    miss = (1.0 - float(p_home)) * (FAILED_HOME_WALK_SECONDS + after)
                    score *= trip / (trip + miss)
                    why += said_home
                    if rescued and not MISS_RESCUE_PRICED_LIVE:
                        why += (f" (look-only: a rescue item is held, so a miss would "
                                f"be priced {FAILED_HOME_WALK_SECONDS + RESCUED_MISS_SECONDS:.0f}s,"
                                f" not {FAILED_HOME_WALK_SECONDS + REJOIN_SECONDS:.0f}s)")

            # A TRIP THAT DOES NOT LAND HERE DOES NOT GATHER HERE (DESIGN 8dy).
            # Every rate above is this field's own -- what it paid while the
            # feed was crediting it -- and none of it says how often the route
            # there delivers. MEASURED over the saved route frames (441 rows):
            # the Pine Tree walk landed 0 of its 32 trips from attempt 407 and
            # the Pine Tree flight 13 of the 14 it was judged on, while this
            # ranked both as Pine Tree's 2,342 pollen/s. So the score is scaled by the landing
            # posterior of the route the trip would take (`route_odds`). A
            # route never judged is priced at the prior's even odds, like every
            # other: were it left at x1.0, a route's first landing (1 of 1, P
            # 0.67) would cut its field's score by a third against the fields
            # never tried. What a mis-delivered trip gathers instead is not
            # credited to the aim -- the field it lands in is priced on the
            # ground (run_farm `landed_elsewhere`).
            p_land = None
            if score > 0 and self.route_odds is not None:
                try:
                    odds = self.route_odds(name)
                except Exception:
                    odds = None
                if odds:
                    p_land, said = odds
                    score *= float(p_land)
                    why += said

            scored.append(FieldScore(
                field=name, score=score, rate=rate, flowers=flowers, safe=safe,
                mobs=mobs, bees_required=required, reachable=reachable, why=why,
                p_land=p_land, quest_first=quest_first, quick_quest=quick_quest,
                one_trip=one_trip, priority=bool(quest_first and self._priority_names(name))))

        # Ties break toward somewhere we can actually go, then toward FEWER
        # MOBS, then by name. The mob count matters now that optimism can hand
        # several unmeasured fields the same score: without it the alphabet
        # sent the first exploratory trip to the Pine Tree Forest (two mantises
        # and the Werewolf) ahead of the Pumpkin Patch (one werewolf).
        # A FIELD THE QUESTS COME FIRST FOR goes ahead of them all, once it
        # may be gone to at all (QUEST_BONUS, `quests.first`, QUICK_QUEST_SHARE),
        # and among those, one whose step a trip finishes (`one_trip`).
        # AND PINE TREE AHEAD OF A CLOSE OR UNMEASURED LEADER (protips rule 1,
        # an expert prior): never past a field measured clearly better, a
        # quest-first one, or one a quest names.
        self._colour_first(scored)

        def first(s) -> bool:
            return QUEST_FIRST_SORT and s.quest_first and s.reachable and s.score > 0
        return protips.pine_tree_first(
            sorted(scored, key=lambda s: (not first(s), not (first(s) and s.priority),
                                          not (first(s) and s.one_trip),
                                          -s.score, not s.reachable,
                                          len(s.mobs), s.field)),
            quest_names=self._quest_names)

    # ---- the decision -----------------------------------------------------
    def decide(self, situation: Situation) -> Decision:
        """What to do next.

        The order is deliberate and each rule earns its place:

          1. A full backpack converts. Gathering into a full backpack earns
             nothing at all.
          2. A backpack worth protecting converts BEFORE travelling anywhere
             dangerous. This is the rule whose absence cost 361,439 pollen:
             the bot carried the owner's own backpack to a field with two
             mantises in it, to top up the remaining 62%, and lost the lot.
          3. Otherwise gather in the best field we can reach.
        """
        ranked = self.rank(situation)
        best = ranked[0] if ranked else None
        full = situation.fullness

        if full is not None and full >= self.convert_at:
            return Decision("convert", None,
                            f"the backpack is {full:.0%} full — gathering into "
                            "a full backpack earns nothing", ranked)

        if best is None or best.score <= 0:
            if situation.carrying > 0:
                return Decision("convert", None,
                                "nowhere worth gathering right now, and "
                                f"{situation.carrying:,} pollen is banked by "
                                "converting", ranked)
            return Decision("wait", None,
                            "no field is both reachable and worth the risk",
                            ranked)

        if (situation.carrying >= self.worth_protecting and not best.safe):
            return Decision("convert", None,
                            f"carrying {situation.carrying:,} pollen and the "
                            f"best field is guarded — bank it before going "
                            "anywhere a mob can take it", ranked)

        # THE BAG IS COSTING US THE FIELD, and the loss was invisible.
        #
        # The rule above catches a loaded bag being carried INTO danger. It
        # cannot catch the commoner case: the loaded bag has already struck
        # every guarded field off the board inside `rank`, so `best` is
        # whatever safe field is left, it looks fine, and nothing says what
        # was given up. MEASURED 2026-09-23 03:25 against the live notes,
        # carrying 626,837 of 1,113,750:
        #
        #     loaded    dandelion 219   (everything else scored 0, vetoed)
        #     empty     spider 862, bamboo 831, mountain_top 795, cactus 703
        #
        # One field left on the board and it was the owner's own worst one
        # ("the blue flower field and dandylion are the lowest rewarding").
        # Emptying the bag costs one dwell and buys back the whole board.
        #
        # THE COMPARISON IS ARITHMETIC, NOT A THRESHOLD. Converting spends
        # `dwell` seconds of a `trip` and then gathers at the empty-bag rate;
        # not converting gathers the whole trip at the loaded-bag rate. So it
        # is worth it exactly when
        #
        #     empty_rate * (trip - dwell) > loaded_rate * trip
        #
        # with the dwell priced from CONVERT_POLLEN_PER_SECOND. No number
        # here is chosen; every one of them is read off something.
        if situation.carrying >= self.worth_protecting:
            unloaded = self.rank(Situation(pollen=0,
                                           capacity=situation.capacity,
                                           honey=situation.honey,
                                           where=situation.where))
            free = unloaded[0] if unloaded else None
            if free is not None and free.score > best.score:
                dwell = (CONVERT_FIXED_SECONDS
                         + situation.carrying / CONVERT_POLLEN_PER_SECOND)
                trip = float(self.trip_seconds or TRIP_SECONDS)
                if trip > dwell and free.score * (trip - dwell) > best.score * trip:
                    return Decision("convert", None,
                                    f"carrying {situation.carrying:,} pollen, "
                                    f"which strikes every guarded field off "
                                    f"the board and leaves {best.pretty} at "
                                    f"{best.score:,.0f} — banking it takes "
                                    f"about {dwell:.0f}s and puts "
                                    f"{free.pretty} at {free.score:,.0f} back "
                                    "in reach", ranked)

        # P3: A SMALL, LOGGED EXPLORATION (brain-research-2 section 5): with
        # chance `explore` one of the near-best reachable, safe fields (top 3,
        # within EXPLORE_NEAR of the best) is taken instead, and the chance of
        # the field taken is recorded, so a new field rule can be judged from
        # the ledger (SNIPS / doubly robust, tools/ope.py). Never while a quest
        # puts its field first.
        if self.explore > 0 and not best.quest_first:
            near = [s for s in ranked[:3] if s.reachable and s.safe and s.score > 0
                    and s.score >= EXPLORE_NEAR * best.score]
            if len(near) > 1:
                share = self.explore / len(near)
                pick = (self.rng.choice(near) if self.rng.random() < self.explore else best)
                p = share + (1.0 - self.explore if pick is best else 0.0)
                why = pick.why + ("" if pick is best else
                                  f" (exploring: {p:.0%} chance, logged)")
                return Decision("gather", pick.field, why, ranked, p_field=round(p, 4))
        return Decision("gather", best.field, best.why, ranked)

    def explain(self, situation: Situation, top: int = 5) -> str:
        """The whole thought, for the owner to read and disagree with."""
        decision = self.decide(situation)
        lines = [f"decision: {decision.describe()}",
                 f"proved at least {self.bees_at_least()} bees by gathering"]
        for score in decision.alternatives[:top]:
            mark = "->" if score.field == decision.field else "  "
            lines.append(f"  {mark} {score.pretty:<14} {score.score:8,.0f}  "
                         f"{score.why}")
        return "\n".join(lines)


# PLANNER V2, SHADOW (think-planner 2026-10-22): HONEY AN HOUR OVER THE WHOLE
# CYCLE, quest reward as a value term instead of a sort key. MEASURED offline
# 2026-10-22 over 1,135 gather decisions in var/trips.jsonl (direct method;
# every logged p_field was 1.0, so no doubly-robust estimate yet): the
# `quests.first` sort overrode the top score on 212 trips and the alternative
# paid more on 93% of them, ~13M honey a trip gross (quest honey unlogged, so
# an upper bound); "always the top score" replayed at 93.9M/h against 84.2M/h.
# Three faults this fixes, in shadow:
#   * `rank` scores pollen/s while gathering; gathering is 42-83% of a trip,
#     so travel (routes[].seconds, per field) and the convert (per account)
#     are priced here.
#   * `min(DANGER_DISCOUNT, lived)` keeps every guarded field at x0.75 however
#     safe it has proved: MEASURED trips.jsonl, Pine Tree 12 deaths in 115.6
#     gather hours. Here a field with V2_MEASURED_S of its own gathering is
#     priced on its own recent death rate alone.
#   * fieldnotes' all-time deaths over a fixed TRIP_SECONDS (420 s, real
#     medians 219-902 s): here the last V2_DEATH_WINDOW_S of the field's own
#     gathering, over its own median gather.
# LOOK-ONLY: run_farm logs "planner would: ..."; PLANNER_V2_LIVE (False) makes
# it choose on odd wall-clock hours, so the two can be compared paired.
PLANNER_V2_LIVE = False
# P3 widened, look-only: explore among fields within V2_EXPLORE_NEAR of the v2
# best with an empty bag, safe or measured safe (V2_SAFE_SURVIVAL over
# V2_MEASURED_S), and log the real chance -- so a later rule can be judged
# off-policy. The live P3 almost never fires (guarded leaders, quests first).
PLANNER_EXPLORE_LIVE = False
V2_EXPLORE_NEAR = 0.85
V2_SAFE_SURVIVAL = 0.97
V2_DEATH_WINDOW_S = 30 * 3600.0
V2_MEASURED_S = 10 * 3600.0
# ponytail: a Gamma prior of half a death in 10 gather hours (ESTIMATE, the
# order of the pooled MEASURED 12 in 115.6 h); per-field priors if it matters
V2_PRIOR_DEATHS, V2_PRIOR_SECONDS = 0.5, 36_000.0


def trip_stats(path, last: int = 1200) -> dict:
    """{field: {gather_s, travel_s, hpp, deaths, seconds}} and "_" (the
    account's hpp, travel_s and convert_s) from the last trips in
    var/trips.jsonl. Travel is the field's own out/flight/home routes; the
    convert is what a converted trip spent outside gathering, its routes and
    its errands (median, account-wide: it is the bag's, not the field's)."""
    import json
    import statistics as st
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()[-last:]
    except OSError:
        return {}
    per: dict = {}
    hpp_all, conv_all, trav_all = [], [], []
    for ln in reversed(lines):                       # newest first
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        # MEASURED var/trips.jsonl 2026-10-22: 3 of 25 death rows have
        # credited None (nothing banked), so deaths and seconds fall back to
        # the field it aimed at; the honey figures below stay credited-only.
        f, g = d.get("credited") or d.get("aimed_at"), float(d.get("gather_seconds") or 0)
        if not f or g <= 0:
            continue
        s = per.setdefault(f, {"g": [], "t": [], "h": [], "deaths": 0, "seconds": 0.0})
        if s["seconds"] < V2_DEATH_WINDOW_S:
            s["deaths"] += int(d.get("deaths") or 0)
            s["seconds"] += g
        if not d.get("credited"):
            continue
        routes = d.get("routes") or []
        trav = sum(float(r.get("seconds") or 0) for r in routes
                   if r.get("kind") in ("out", "flight", "home") and r.get("target") == f)
        errand = sum(float(r.get("seconds") or 0) for r in routes if r.get("kind") == "errand")
        # Honey a pollen uses only the trips whose honey settled: MEASURED
        # 2026-10-22, 352 of 983 converted trips; the other 631 log honey null.
        if d.get("converted") and (d.get("pollen") or 0) > 0 and (d.get("honey") or 0) > 0:
            s["g"].append(g)
            s["h"].append(d["honey"] / d["pollen"])
            hpp_all.append(s["h"][-1])
            if routes:
                s["t"].append(trav)
                trav_all.append(trav)
                conv_all.append(max(0.0, float(d.get("seconds") or 0) - g - trav - errand))
    med = (lambda xs, n, dflt: st.median(xs) if len(xs) >= n else dflt)
    acct = {"hpp": med(hpp_all, 1, 1.5), "travel_s": med(trav_all, 1, 60.0),
            "convert_s": med(conv_all, 1, 190.0)}
    out = {"_": acct}
    for f, s in per.items():
        out[f] = {"gather_s": med(s["g"], 3, None), "travel_s": med(s["t"], 3, acct["travel_s"]),
                  "hpp": med(s["h"], 5, acct["hpp"]), "deaths": s["deaths"], "seconds": s["seconds"]}
    return out


def score_v2(alt, stats: dict, bonus: dict | None = None, capacity: float = 0.0,
             leaks: dict | None = None):
    """(honey a second over the cycle, survival, quest honey, why) for one
    `rank` candidate, or None when the planner would not go there at all.
    `bonus` is questvalue.field_bonus: {field: (quest honey a pollen, owed)}.
    `leaks` is reflect.field_minutes: {field: minutes lost there last hour}."""
    rate, score = float(alt.rate or 0), float(alt.score or 0)
    if not alt.reachable or rate <= 0 or score <= 0:
        return None
    acct = stats.get("_") or {"hpp": 1.5, "travel_s": 60.0, "convert_s": 190.0}
    s = stats.get(alt.field) or {}
    gather = s.get("gather_s") or (capacity / rate if capacity > 0 else EXPLORE_SECONDS)
    seconds = float(s.get("seconds") or 0.0)
    lam = (float(s.get("deaths") or 0) + V2_PRIOR_DEATHS) / (seconds + V2_PRIOR_SECONDS)
    lived = math.exp(-lam * gather)
    if not alt.safe and seconds < V2_MEASURED_S:
        lived = min(DANGER_DISCOUNT, lived)
    bag = rate * gather
    q_hpp, owed = (bonus or {}).get(alt.field, (0.0, 0))
    quest = q_hpp * min(bag, owed)
    cycle = gather + s.get("travel_s", acct["travel_s"]) + acct["convert_s"]
    p = float(alt.p_land) if alt.p_land is not None else 1.0
    value = p * lived * (bag * s.get("hpp", acct["hpp"]) + quest) / cycle
    why = (f"{gather:.0f}s gather + {cycle - gather:.0f}s travel/convert, "
           f"{lived:.0%} survive, p_land {p:.2f}, quest {quest / 1e6:.1f}M")
    lost = float((leaks or {}).get(alt.field) or 0.0)
    if lost > 0:
        keep = max(LEAK_FLOOR, 1.0 - lost / 60.0)
        value *= keep
        why += f", lost {lost:.0f} min here last hour x{keep:.2f}"
    return value, lived, quest, why


def v2_rank(alts, stats: dict, bonus: dict | None = None, capacity: float = 0.0,
            leaks: dict | None = None) -> list:
    """[(alt, value, survival, quest, why)] best first."""
    out = [(a, *v) for a in alts or [] if (v := score_v2(a, stats, bonus, capacity, leaks))]
    return sorted(out, key=lambda t: -t[1])


def v2_explore(ranked: list, stats: dict, eps: float, carrying: float,
               worth: float = WORTH_PROTECTING, chosen: str | None = None) -> list:
    """[(field, chance)] the widened P3 would draw from: within
    V2_EXPLORE_NEAR of the v2 best, an empty bag, safe or measured safe.
    [] when there is nothing to explore between, or when v2's best is not
    `chosen` (the field the planner picked): the draw lands on v2's best
    ~1-eps of the time, so exploring there would make v2 the chooser
    unannounced and skip the paired test."""
    if not ranked or eps <= 0 or carrying >= worth:
        return []
    if chosen is not None and ranked[0][0].field != chosen:
        return []
    top = ranked[0][1]
    near = [t for t in ranked[:3] if t[1] >= V2_EXPLORE_NEAR * top
            and (t[0].safe or (t[2] >= V2_SAFE_SURVIVAL and float(
                (stats.get(t[0].field) or {}).get("seconds") or 0) >= V2_MEASURED_S))]
    if len(near) < 2 or near[0] is not ranked[0]:
        return []
    share = eps / len(near)
    return [(t[0].field, share + (1.0 - eps if i == 0 else 0.0)) for i, t in enumerate(near)]


def load_fields(path: str | Path) -> dict:
    """The field table from the knowledge base. {} if it cannot be read."""
    import yaml
    try:
        data = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, ValueError):
        return {}
    fields = data.get("fields")
    return dict(fields) if isinstance(fields, dict) else {}


def from_settings(settings, fields: dict, notes=None, reachable=None,
                  prefer_colour: str | None = None,
                  walk_home=None) -> tuple["Planner", str | None]:
    """A Planner configured the way the owner's settings ask for.

    Returns `(planner, forced_field)`. `forced_field` is the field the settings
    insist on, or None to choose automatically, and it is already checked
    against what there is a route to -- a setting naming a field the bot cannot
    walk to is a setting that would silently do nothing.

    THIS LIVES IN THE LIBRARY, NOT IN THE SCRIPT, AND THAT IS THE POINT. A
    setting read only by `scripts/run_farm.py` is not wired into the system:
    nothing else can honour it, and `tests/unit/test_settings.py` scans `src/`
    precisely so that a control cannot look live while only one script obeys it.

      gather.auto_field   choose by expected value rather than a fixed field
      gather.field        which field to use when that choice is switched off
      gather.convert_at   how full the backpack gets before it banks
      quests.first        a field the quests name outright wins the ranking
    """
    planner = Planner(fields, notes, reachable=reachable,
                      prefer_colour=prefer_colour, walk_home=walk_home)

    # HOW FULL BEFORE BANKING. Below 100 on purpose, and the setting's own help
    # text says why: pollen gathered above capacity is discarded, so the last
    # stretch of a fill returns nothing. A bad value here would be expensive in
    # both directions -- too low and every cycle pays a round trip for half a
    # backpack, too high and the tail of each trip is thrown away -- so it is
    # clamped to a sane band rather than trusted blindly.
    try:
        percent = float(settings.get("gather.convert_at", 95) or 95)
        planner.convert_at = min(1.0, max(0.1, percent / 100.0))
    except (TypeError, ValueError):
        pass

    try:
        auto = bool(settings.bool("gather.auto_field"))
        named = str(settings.get("gather.field", "auto") or "auto")
    except Exception:
        return planner, None
    try:
        planner.quest_first = bool(settings.bool("quests.first"))
    except Exception:
        planner.quest_first = False
    if auto:
        return planner, None
    slug = named.strip().lower().replace(" ", "_")
    if slug in ("", "auto"):
        return planner, None
    if reachable is not None and ROUTER_ALIASES.get(slug, slug) not in reachable:
        return planner, None          # no route: fall back to choosing
    return planner, slug

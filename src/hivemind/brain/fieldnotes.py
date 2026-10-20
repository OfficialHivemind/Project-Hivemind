"""What the bot knows about each FIELD, kept under the field's real name.

WHAT THIS REPLACES. `brain/explore.Explorer` built a map of places called
`spot_1` to `spot_13`, identified by a colour histogram. docs/DESIGN.md 8a now
records the measurement that ends that approach: over 82 frames the game itself
labelled, across 12 fields and 3,321 pairs, the worst correlation between two
views of the SAME field was +0.108 and the best between DIFFERENT fields was
+0.972. There is no threshold. The owner's second taught session produced 13
"places" whose notes all read "standing on a hive pad" -- for Pumpkin, Bamboo
and Mountain Top.

The names were the other half of the problem. `spot_6` connects to nothing. A
field called `pumpkin` is a row in `data/knowledge/world.yaml` with a wiki
quote, a bee requirement and whether anything there will attack. That is the
difference between a map and a lookup table of screenshots, and it is what the
owner was asking for: "cus i dont know if u understand i want the ai to be
DEDICATED and JUST FOR bss so it knows everything and grows knowlage of it".

SO EVERY FACT HERE IS FILED UNDER A NAME THE GAME SAID. `vision/whereami`
supplies it, from the reward feed, and returns None rather than a guess when
the game has not spoken. A sample with no fix is DISCARDED, not attributed to
wherever we were last -- crediting pollen to a field on the strength of having
been there a minute ago is exactly how the old map smeared a million pollen
across thirteen imaginary places.

WHAT IT IS FOR. Choosing. "Which field pays best for this account, on this
server, with these bees" is not on any wiki, and it is the one thing only
playing can answer.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field as dc_field
from pathlib import Path

# Pollen jumping by more than this between two samples is a conversion, a
# quest reward or a misread, not gathering. MEASURED: the owner's best real
# rate was 1,071 pollen/second, and samples are a fifth of a second apart, so
# anything above a few thousand in one step did not come out of the ground.
IMPLAUSIBLE_JUMP = 20_000

# HOW MANY MEASURED SECONDS A PAID RATE NEEDS before it is used instead of the
# diluted one.
#
# THE PAID SUBSET IS A SAMPLE, AND A SMALL SAMPLE OF IT IS NOISE. Only the
# intervals whose ends were both legible pay into the pair, which is a
# fraction of the time in the field, and a token pickup lands inside a single
# 1.5 s interval. MEASURED 2026-09-23 03:05: Cactus held 5,625 pollen over
# 3 s and priced itself at 1,875/s, seven times anything real.
#
# 60 s WAS NOT ENOUGH EITHER. MEASURED 2026-09-23 03:33: Pine Tree had 76
# paid seconds holding 112,903 pollen and so claimed 1,491 pollen/s -- and
# that figure was RIGHT for the stint it came from (the trip itself measured
# 355,608 pollen in 242 s, 1,470/s). The trouble is that it is one stint. The
# field's whole record is 164,145 pollen over 571 s, which is 287/s, and
# every unmeasured field's curiosity bonus is a multiple of the best measured
# rate -- so one hot stint lifted Mountain Top over everything and the trip
# that followed gathered 0 pollen in 656 seconds.
#
# 300 s is two or three trips' worth of paid intervals: long enough that no
# single stint, and no single pickup, decides what a field is worth. Below it
# the field falls back to `pollen / seconds`, which is diluted by the seconds
# whose ends could not be read -- but diluted in the same direction for every
# field, so the RANKING, which is all the planner uses, survives.
PAID_ENOUGH_SECONDS = 300.0

# WHICH GENERATION OF ROUTE DATA THE HOME-FAILURE COUNTERS WERE EARNED AGAINST.
#
# `home_failures` and `sight_failures` count failures IN A ROW and, at
# HOME_TRIES, stop the recorded route home from being run at all. That is
# right while the routes are the same routes -- and wrong the moment they
# are not. MEASURED 2026-09-23: every walk home ended at the ramp corner
# because the transpiler kept only Natro's `default` branch (DESIGN 8cc), so
# every field had earned its three strikes against data that has since been
# corrected, and carrying the strikes over would have skipped the fixed
# routes for exactly the fields that needed them. A saved file whose
# version is older than this is read with those two counters at zero; the
# rest of the notes -- rates, deaths, petals -- are as trustworthy as ever
# and are kept.
#
#   1  the walks home as first transpiled: `default` branch only
#   2  `slot_switch` kept, seven unexpressible walks home refused, the row
#      search after the route (act/hiverow)
#   3  lean legs held until the wall (DESIGN 8cq) and the two portal walks
#      home, Bamboo and Blue Flower (8cs). MEASURED 2026-09-23 22:55:
#      Strawberry carried three strikes, every one earned before the lean
#      legs existed, so the walk home that fix was written for had never
#      been run -- "not walking home from strawberry: the recorded route has
#      failed 3 times" (run-333, 21:22:50), straight to a rejoin, which
#      resets the Wealth Clock streak the owner wants kept.
#   4  move.walkspeed 28 -> 32.2 (2026-10-09): a gifted Hasty Bee's +15%
#      movespeed from 10-07 20:05 overshot every timed walk home, so every
#      strike since was the speed's, not the route's -- Bamboo and Dandelion
#      latched at 3, a rejoin from Bamboo at 12:16 that reset the streak.
HOME_DATA_VERSION = 4

# AND THE STRIKES OF THREE FIELDS, GIVEN BACK ONCE (DESIGN 8dx), the way
# FALSE_DEATHS gives back deaths: only these fields, because only their
# strikes were earned by walks home that no longer count against them. The
# saved notes remember which were given back, so each happens once.
#
#   pine_tree  every walk home from it since its route took its present shape
#              (attempts 363-366) landed when the 432-stud coast after the
#              jump ran its full 15.5 s (364, twice) and missed when a mob cut
#              the coast to 1.4-4.9 s (363, 364, 365, 366), and until
#              audit-core (DESIGN 8dt) a cut coast was never finished; it has
#              not been walked since, latched from run-366 on, and both its
#              probes (429, 438) were trips the feed credited to Strawberry,
#              so its walk home was never tried by either
#   sunflower  its three strikes are attempts 351, 353 and 357, all walked
#              from beside the Black Bear after a gather whose pollen had
#              stopped rising (run_farm `ended_off_the_field`); its probe
#              (432) ended on hive 1's pad at the ramp corner, where Natro's
#              row search starts, and was walked off it (act/hiverow
#              ROW_LINE_TILES) -- but that miss stands (HOME_STRIKES_KEPT)
#   dandelion  its two strikes are attempt 359, walked from in front of the
#              hive pads after the pollen had stopped rising, and 362, cut
#              short by a stop, which since DESIGN 8ds counts for neither side
# TRIPS THAT NEVER ARRIVED, given back once when the route itself was fixed
# (`Note.travel_failures`; brain/decide TRAVEL_FAILURES_TO_GIVE_UP gives a field
# up at 4, and only an arrival resets it -- which a given-up field never gets).
TRAVEL_FAILURES_FORGIVEN = {
    "cactus": ("its flight came down short of the field's ledge on every kept flight; "
               "the route now ends with a running jump (transpile_natro LANDINGS)"),
}
HOME_STRIKES_FORGIVEN = {
    "pine_tree": ("the coast after the jump is finished now when a mob cuts it, "
                  "and neither probe reached the field to try it"),
    "sunflower": "its three walks home that began off the field",
    "dandelion": "its walks home began off the field, or were cut short by a stop",
    "mountain_top": ("its walks home began after falls into Pineapple or Stump (10 of "
                     "~33 trips), which the 2-step chase leash now prevents (the 22:52 "
                     "trip stayed on top); trips that stayed got home 5 of 7"),
    # THE CHASE CARRY (act/chase CARRY, live 2026-10-08 22:23) cancels the
    # drift these strikes were earned under: walks home landed 41 of 53 after
    # 0-10 chases and 20 of 46 after more, the leftovers summing to 526-4,267 px
    # a trip one way; Pineapple's latched trips had 90-177 chases. Its 23:05
    # trip, 133 chases with the carry, ended (-113, -675) px from its start --
    # and the latch sent it straight to a rejoin, so the fix is never measured.
    "pineapple": "its strikes were earned under the chase drift the carry now cancels",
    "stump": "its strikes were earned under the chase drift the carry now cancels",
    "bamboo": "its strikes were earned under the chase drift the carry now cancels",
}
# AND WHAT STAYS AFTER THE GIVE-BACK (a review finding): a route and a sight
# failure each, for a miss the give-back's reason does not cover. Sunflower's
# probe (432, 07:09-07:11) is the one walk of its present route from inside
# the field, and it missed; the row search from Natro's line that should land
# from where it ended has been walked only in a toy row, not from 432's own
# end (63,985 px of hive wall). So it keeps one of each, and two more misses
# latch it again, not three. A record that gave everything back before this
# existed (the live notes did, 2026-09-26 14:44:10, and no walk home from
# Sunflower has run since) has the strikes put back once, never lowering one.
HOME_STRIKES_KEPT = {
    "mountain_top": (1, "its walk home is unproven from on top since the leash"),
    "pineapple": (1, "its walk home is unproven since the chase carry"),
    "stump": (1, "its walk home is unproven since the chase carry"),
    "bamboo": (1, "its walk home is unproven since the chase carry"),
    "sunflower": (1, "attempt 432's walk home from inside the field missed"),
}

# HOW MANY HUD RATE READINGS MAKE A NUMBER. The feed fixes a field about once
# a second while gathering, so this is about a minute of standing in it --
# the same order as brain/decide.MEASURED_ENOUGH_SECONDS, and enough for the
# reading's own second-to-second wobble (712-761 within one ten-second
# window, measured) to average out.
PRINTED_ENOUGH_SAMPLES = 60

# HOW MUCH OBSERVATION THE POOLED DEATH RATE IS WORTH, in seconds, when
# planning a trip to a field with a short record of its own. See
# `FieldNotes.danger_of`, which shrinks a field's measured death rate towards
# the character's pooled rate with this much weight.
#
# One trip's worth. Chosen because a trip is the unit of evidence here -- a
# field is either survived for a trip or it is not -- and because it puts the
# crossover in the right place against the numbers actually on disk: a field
# watched for 74 s keeps the pooled rate almost exactly, one watched for
# 2,490 s is mostly its own, and the pooled rate itself rests on 25,000 s so
# it is not the uncertain half of the blend.
DEATH_PRIOR_SECONDS = 600.0

# DEATHS THAT WERE CONVERSION LINKS, by incident, and the field each was filed
# under. A Conversion Link turns part of the bag into honey where the
# character stands, and the death watch read the fall as a death (brain/alive
# DEATH_DROP, DESIGN 8ds). MEASURED on the incidents' own frames and the logs:
# 231125 (run-338, 7,917 -> 3,432; on its frames 7,941 -> 1,533 with honey
# +6,536; the feed last named Spider, and Spider's plan line gained "died
# here 1 time" between run-337 and run-339), 231129 (run-338, 5,563 -> 2,192,
# Strawberry, which gained its first death then) and 20260924-055153 (run-356,
# 50,389 -> 22,384, "+52,250 Honey (from Conversion Link)" on screen,
# Strawberry's third). Every other logged death fell to 0.089 of the bag or
# less. `load` takes each back exactly once.
FALSE_DEATHS = {"231125-death": "spider",
                "231129-death": "strawberry",
                "20260924-055153-death": "strawberry",
                # AND 24 MORE, by what they left (brain/alive DEATH_LEAVES_MAX,
                # LINK_KEEPS_SHARE): 20,565-1,898,371 pollen, 19-49% of the bag,
                # where a real death's first read is at most 15,570 and 4%. Each
                # incident's "died: ... backpack now" line in var/night/run-*.log,
                # filed under the field the feed named last before it. The
                # 2026-10-05 01:13:14 fall (12.06%) is too near the line to give back.
                "20260927-233649-death": "pine_tree",
                "20260928-000458-death": "pine_tree",
                "20260928-065715-death": "pine_tree",
                "20260928-095518-death": "pine_tree",
                "20261003-231119-death": "blue_flower",
                "20261004-011434-death": "pine_tree",
                "20261004-051324-death": "pine_tree",
                "20261004-064920-death": "pine_tree",
                "20261004-094648-death": "pine_tree",
                "20261004-235348-death": "pine_tree",
                "20261005-003023-death": "blue_flower",
                "20261005-015215-death": "pine_tree",
                "20261005-024839-death": "blue_flower",
                "20261005-033851-death": "bamboo",
                "20261005-042322-death": "pine_tree",
                "20261005-065409-death": "blue_flower",
                "20261005-074803-death": "blue_flower",
                "20261005-082741-death": "pine_tree",
                "20261005-124123-death": "pine_tree",
                "20261005-133226-death": "pine_tree",
                "20261005-143122-death": "pine_tree",
                "20261005-180706-death": "pine_tree",
                "20261005-233748-death": "rose",
                "20261006-013406-death": "mushroom",
                # AND 9 FROM 20-21 OCT WITH NO PROOF OF A DEATH (brain/alive
                # DEATH_PROOF_LIVE): each last frame shows the character alive
                # in the field, no "You died!", no health bar, the hive row
                # 0-11,366 px; the feed read "Honey (from Pine Tree Forest)" /
                # "(from Pepper Patch)". Pepper's "died here" went 1 -> 2
                # across 21:39 in run-1167; none was taken back by A9 D2
                # (no "taken back" line in run-1152/1155/1159/1164/1166/1167).
                "20261020-023021-death": "sunflower",
                # 023032, 11 s later in the same trip home from Sunflower
                # (run-1101 02:30:32 "15,163 -> 0", a convert of 320,377 at
                # 02:30:42); FieldNotes.died keeps `_seen_field`, so a second
                # death in a trip lands on the same field: sunflower.
                "20261020-023032-death": "sunflower",
                "20261021-095515-death": "pine_tree",
                "20261021-111040-death": "pine_tree",
                "20261021-111538-death": "pine_tree",
                "20261021-143237-death": "pine_tree",
                "20261021-180055-death": "pine_tree",
                "20261021-210935-death": "pepper",
                "20261021-213947-death": "pepper"}


def trip_arrived(pollen_gathered: int | None, credited: str | None,
                 passes: int) -> bool | None:
    """Did this trip actually get to a field? True, False, or None for "cannot say".

    WHY THE JOURNEY CANNOT ANSWER THIS. A field has no landmark prompt, so
    "left the hive" is the most the walk out can honestly claim (DESIGN 8b,
    8k) -- and `run_farm._travelled` was taking that weak yes as `arrived`,
    which calls `FieldNotes.arrived` and RESETS `travel_failures` to zero. So
    a route that left the hive and ended up nowhere was recorded as a success
    every single time, `travel_failures` never rose, and the planner's
    curiosity bonus kept choosing the same field for ever.

    MEASURED 2026-09-22 05:07, which is the trip that exposed it:

        05:07:38  staying up to 1200s this trip
        05:07:55  to sunflower: left the hive, arrival unconfirmed
        05:10:12  I am nowhere I can confirm
                  backpack 49,679/1,072,500 (5%) and flat

    THE EVIDENCE THAT DOES ANSWER IT is available once the gathering is over:

    * the reward feed named a field   -> we were in one, whatever its name
    * pollen went up                  -> we were in one, even unnamed
    * the pattern was walked, pollen did NOT go up, and the feed stayed
      silent                          -> we were not in a field

    The last one is the judgement that was missing. Each signal on its own is
    too weak: the feed needs a pickup AND a vision-model call, so its silence
    proves nothing by itself, and a flat counter alone could be a bad read.
    Together, with the pattern actually walked, they are conclusive -- you
    cannot walk a gathering pattern inside a flower field and collect nothing.

    None when the counter was never legible (nothing to conclude) or when no
    pattern pass ran at all (the trip never got as far as gathering), because
    a guess recorded as a failure would ban a field that may be fine.
    """
    if credited:
        return True
    if pollen_gathered is None:
        return None
    if pollen_gathered > 0:
        return True
    if passes <= 0:
        return None
    return False


def pollen_for_verdict(pollen_gathered: int | None, *, sprinkler_took: bool) -> int | None:
    """The pollen `trip_arrived` should judge by: None ("cannot say") when the
    game TOOK this trip's sprinkler and the counter shows nothing.

    A sprinkler is refused off a field ("You must be standing in a field to
    build a Sprinkler", act/hotbar), so one taken proves a field -- the counter
    after a death reads the respawn's empty bag. MEASURED 2026-10-07..14: the
    Pine Tree flight's "AT THE HIVE" misses (attempts 717 07:08, 954 09:32,
    988 06:58) each placed the sprinkler 13-63 s before a mob killed the
    character with 236-1,673 pollen in the bag -- under run_farm's
    DEATH_PROVES_FIELD -- and each was booked "elsewhere" and a travel failure:
    3 of the flight's 8 misses in ten days."""
    if sprinkler_took and not pollen_gathered:
        return None
    return pollen_gathered


def verdict_for_aim(aimed: str | None, credited: str | None,
                    pollen_gathered: int | None, passes: int) -> str | None:
    """What this trip proves about the ROUTE to `aimed`: 'failed', 'arrived',
    or None for "this trip says nothing about it".

    `travel_failures` gates whether the recorded route to a field is worth
    trying again, so the question is specifically "did it get to THAT field",
    not "did it get to a field". The distinction matters in both directions
    and getting it wrong cancels the other half of the system:

    * **Reached no field at all** -- the pattern was walked, nothing was
      collected, the feed stayed silent. The route to `aimed` failed. This is
      the signal that was missing entirely; see `trip_arrived`.
    * **Reached the field it aimed at** -- the route works. Forgive it.
    * **Reached a DIFFERENT field** -- says nothing HERE, because
      `nav.journey.wrong_place` already rules on it, and with a veto this
      must not override: a trip credited elsewhere that still PAID is not a
      failure (it earned 378,000 honey an hour once). Returning 'arrived'
      here would call `FieldNotes.arrived` and reset the failure
      `wrong_place` had just recorded; returning 'failed' would double-count
      it. Neither is this function's call to make.
    * **Gathered somewhere unnamed** -- 'arrived', and this took a second
      pass to get right. `travel_failures` counts trips that got NOWHERE in a
      row, so the question it gates is "is this recorded route worth walking
      again", not "is the label on it accurate". MEASURED 2026-09-22 05:33:
      the route named for Sunflower delivered **442,156 pollen over 76
      passes** with the feed silent throughout. Returning None there left the
      counter untouched on the route's good trips while its bad ones kept
      incrementing it, so a route that works half the time would have been
      banned outright. A route that comes back with 442,000 pollen is worth
      walking again whatever the reward feed did or did not say.
    """
    if not aimed:
        return None
    arrived = trip_arrived(pollen_gathered, credited, passes)
    if arrived is False:
        return "failed"
    if credited and credited != aimed:
        return None                 # wrong_place owns this one; see above
    if arrived is True:
        return "arrived"
    return None


@dataclass
class Note:
    """Everything learned about one field, by standing in it."""
    field: str
    seconds: float = 0.0
    pollen: int = 0
    visits: int = 0
    samples: int = 0
    last_seen: float = 0.0
    # THE SAME MOMENT ON THE WALL CLOCK, for the GUI's "last visited".
    # `last_seen` runs on `clock` (monotonic by default), and a panel that
    # subtracted it from time.time() showed ages of decades (audit
    # 2026-09-26, brain F12). This session only: 0 means "not this run".
    last_wall: float = 0.0
    # PROVEN IS NOT THE SAME AS PAYING, and conflating them cost a ranking.
    # `proven` means the game itself credited something to this field, so we
    # have certainly been here and certainly gathered -- which is what proves
    # a bee requirement. `rate` is how much per second, which needs two pollen
    # readings a known time apart. Seeding `proven` from the reward feed once
    # wrote a nominal pollen value to mark a field as paying, and every
    # genuinely good field then ranked BELOW fields never farmed at all.
    proven: bool = False
    # HOW OFTEN THIS FIELD ACTUALLY KILLS US, which is not the same question
    # as how many mobs the wiki lists in it. The wiki says Pineapple has a
    # mantis and a rhino beetle and that Pine Tree has two mantises and the
    # Werewolf; what it cannot say is how often either one lands on THIS
    # character, with this walkspeed, walking this pattern. One death costs
    # the entire backpack -- measured at 445,029 pollen on one trip -- so the
    # difference between a field that kills every third visit and one that
    # never has is worth more than any rate difference between them.
    deaths: int = 0
    # how many times in a row `act/homing.home_by_sight` failed from here
    sight_failures: int = 0
    # Of `seconds`, how many were intervals whose pollen gain could actually
    # be read at both ends -- and, AS A MATCHED PAIR, how much pollen those
    # very intervals paid. See `rate`.
    #
    # THE PAIR IS THE WHOLE POINT. `paid_seconds` shipped on its own on
    # 2026-09-23 and was divided into `pollen`, which is every gain ever
    # credited to the field including months of them from before
    # `paid_seconds` existed. MEASURED 2026-09-23 03:20, straight off
    # var/field_notes.json: Dandelion held 5,212,881 pollen and 1,005 paid
    # seconds and so priced itself at 5,186 pollen/s -- five times the best
    # rate this account has ever recorded, from a numerator covering 23,482
    # seconds and a denominator covering 1,005 of them. The planner chose
    # Dandelion, the owner's own worst field ("the blue flower field and
    # dandylion are the lowest rewarding"), over and over on that number.
    # A rate needs its top and its bottom to describe the same seconds, so
    # they are now incremented in the same branch and nowhere else.
    paid_seconds: float = 0.0
    paid_pollen: int = 0
    # HOW MANY TRIPS AIMED HERE AND WERE CREDITED SOMEWHERE ELSE.
    #
    # Separate from `travel_failures` on purpose, and it must never bar a
    # field: the field is fine, the ROUTE mis-delivers. MEASURED 2026-09-23
    # over runs 280-309, nine trips aimed at the Spider Field:
    #
    #     5 credited spider      (935 pollen/s)
    #     2 credited strawberry  (337/s)
    #     1 credited mushroom    (377/s)
    #     1 credited sunflower   (255/s)
    #
    # Four in nine landed somewhere worth a third of the target, and each
    # cost about 670,000 pollen over a 1,050-second trip. NOTHING RECORDED
    # IT. `nav.journey.wrong_place` correctly refuses to blame the pose --
    # "a field that pays is not the wrong field" -- and `verdict_for_aim`
    # correctly returns None so the two do not double-count. So a route that
    # mis-delivers half the time kept a clean sheet, `travel_failures` stayed
    # 0, and `nav.router.fly_this_time` therefore never tried the walking
    # route to Spider even once.
    #
    # This is the evidence that was missing. It feeds the alternation and
    # nothing else.
    missed: int = 0
    # HOW MANY TRIPS HAVE FAILED TO GET HERE AT ALL, in a row. Not a fact
    # about the field: a fact about whether we can reach it.
    #
    # It exists because the planner's curiosity bonus (decide.EXPLORE_OPTIMISM)
    # treats a field nobody has measured as being as good as the best one we
    # have measured, so an unmeasured field always outranks a proven one --
    # and if the route to it does not work, it stays unmeasured and keeps
    # winning. MEASURED 2026-09-21: five consecutive cycles all chose the
    # Strawberry Field, every one of them failed to leave the hive row, and
    # the Rose Field -- which the same night MEASURED at 930 pollen/s, the best
    # rate this account has ever recorded -- was never chosen again. The bot
    # spent the night trying to reach the one place it could not.
    #
    # Reset by `arrived`, so a route that starts working is forgiven at once.
    travel_failures: int = 0
    # WHEN THE LAST OF THEM WAS COUNTED (wall clock), so a route that changed
    # since is known to owe the field nothing (brain/decide QUEST_ROUTE_TRIAL).
    # 0.0 for failures counted before this was kept. Not reset by `arrived`.
    failed_at: float = 0.0
    # HOW MANY TIMES THE WALK HOME FROM HERE HAS FAILED, in a row. Separate
    # from `travel_failures`, which is about getting TO the field: a route out
    # that works says nothing about the route back, and on this account the
    # two have completely different records.
    #
    # MEASURED 2026-09-22 across runs 120-169: the walk home succeeded **0
    # times out of 52**. The cause is not the route data -- it is that
    # Natro's return paths start where NATRO's field pattern ends, and this
    # bot gathers with its own pattern and chases tokens for twenty minutes
    # first, so it begins the walk home somewhere the path was never written
    # for. The overshoot into the wall fires correctly and the step after it
    # walks into scenery.
    #
    # Ten of the seventeen return paths were only just transpiled and have
    # never been tried, so the attempt is not abandoned wholesale; this counts
    # per field, so a path that works keeps being used and one that does not
    # stops costing a minute a trip. Reset by `walked_home`.
    home_failures: int = 0
    # WHEN THE LATCHED WALK HOME WAS LAST TRIED ANYWAY (wall clock), and how
    # many of those probes have missed in a row. With `home_failures` and
    # `sight_failures` both at their limits the walk home is skipped and the
    # trip goes straight to the rejoin -- and a skip can never land, so
    # nothing ever cleared the two counters. MEASURED 2026-09-25: pine_tree
    # latched at 3/3 after run-366 and the same "not walking home from
    # pine_tree ... straight to the rejoin" closed 26 sessions (run-368 to
    # run-405), none of them an hour long, so the Wealth Clock was never due
    # (DESIGN 8ds). The probe that clears it is `run_farm.at_my_hive`'s;
    # these two are its memory, kept across rejoins. Reset by `walked_home`.
    home_probe_at: float = 0.0
    home_probes: int = 0
    # THE GAME'S OWN POLLEN-PER-SECOND, SUMMED. The HUD prints `(+N/sec)`
    # beside the pollen counter (vision/screenstate.rate_in), and unlike the
    # counter it stays a small number, so it is exact where the counter is
    # not. MEASURED 2026-09-23 over 27 ten-second incident windows: the
    # counter's own movement divided by the mean printed rate ran 0.44-1.75
    # with a median of 0.78 -- the printed figure is the bees' collection
    # rate and token pickups land in the counter as lumps. So it is kept as
    # its own channel -- exact, cheap, on the low side -- and `rate` prefers
    # the paid pair when there is one.
    printed_sum: float = 0.0
    printed_samples: int = 0
    # PETAL PIXELS SEEN HERE, by colour. Counted from real frames while
    # standing in this field, and kept as raw totals rather than as a share so
    # that more looking makes the answer better rather than overwriting it.
    #
    # This exists because quests ask for colours -- "Collect 820,020 Blue
    # Pollen", "Collect 1,500,000 Red Pollen" -- and the wiki's one-word field
    # colour cannot answer which field to stand in. It is the same measurement
    # that showed the Pineapple Patch is only 42.5% blue, which is what made
    # the Bubble Wand a sidegrade rather than the 1.43x upgrade it was sold as.
    petals: dict = dc_field(default_factory=dict)
    saw: list[str] = dc_field(default_factory=list)

    @property
    def rate(self) -> float:
        """Pollen per second, the only number that ranks fields.

        OVER THE SECONDS THE POLLEN WAS ACTUALLY MEASURED IN, not over the
        whole time spent here. MEASURED 2026-09-23 02:45: the Rose trip
        gathered 986,128 pollen in 968 s -- 1,019/s, the best this account has
        recorded -- and the field notes called Rose a 398 pollen/s field,
        because `note()` credited every sampled second to the field but could
        only credit a pollen GAIN when both ends of the interval were legible.
        The counter is illegible above a million (the HUD shrinks its own
        font, see vision/digits), so most of that trip's seconds arrived with
        no pollen attached and diluted the rate by two and a half times. The
        planner ranks fields by this number, so the dilution was choosing the
        wrong fields.

        `seconds` is still every second the game said we were here, because
        that is the right denominator for a DEATH rate; `paid_seconds` is the
        subset over which a pollen gain was measurable, which is the right
        one for a pollen rate.

        THE PAID PAIR IS USED ONLY AS A PAIR, and only once it covers
        `PAID_ENOUGH_SECONDS`. Below that a handful of intervals can carry a
        whole token pickup and price the field at thousands per second; above
        it, `paid_pollen / paid_seconds` is the honest rate over exactly the
        seconds it was measured in. `pollen / seconds` is the fallback, and it
        is not a wrong answer -- it is the same measurement diluted by the
        seconds whose ends could not be read.
        """
        if self.paid_seconds >= PAID_ENOUGH_SECONDS and self.paid_pollen > 0:
            return self.paid_pollen / self.paid_seconds
        return self.pollen / self.seconds if self.seconds > 0 else 0.0

    @property
    def rate_seconds(self) -> float:
        """How many seconds `rate` is an average over.

        The number a caller needs to ask "is that rate worth anything?", and
        it has to come from here because only `rate` knows which of the two
        denominators it used. See `brain/decide.MEASURED_ENOUGH_SECONDS`.
        """
        if self.paid_seconds >= PAID_ENOUGH_SECONDS and self.paid_pollen > 0:
            return self.paid_seconds
        return self.seconds

    @property
    def printed_rate(self) -> float | None:
        """The mean of the HUD's own `(+N/sec)` readings here, or None until
        PRINTED_ENOUGH_SAMPLES have been read. A lower bound on the field's
        pollen per second; see `printed_sum`."""
        if self.printed_samples < PRINTED_ENOUGH_SAMPLES:
            return None
        return self.printed_sum / self.printed_samples

    @property
    def pays(self) -> bool:
        return self.pollen > 0

    @property
    def death_rate(self) -> float:
        """Deaths per second spent gathering here, or 0.0 when untested.

        Zero means "no evidence", not "safe" -- a field visited once for
        thirty seconds has earned no opinion either way. Callers weigh it
        against how long they have watched, which is `seconds`.
        """
        return self.deaths / self.seconds if self.seconds > 0 else 0.0

    def colour_share(self, colour: str) -> float | None:
        """Share of petals here that are `colour`, or None if never looked.

        None is not zero. A field we have not stood in has no colour we can
        claim, and returning 0.0 would read as "no blue flowers here".
        """
        total = sum(int(v) for v in self.petals.values())
        if total <= 0:
            return None
        return int(self.petals.get(colour, 0)) / total

    @property
    def looked_at_flowers(self) -> bool:
        return sum(int(v) for v in self.petals.values()) > 0

    @property
    def likely_death_rate(self) -> float:
        """Deaths per second, allowing for how little we have watched.

        WHY NOT JUST `deaths / seconds`. Because zero deaths in a few minutes
        is not evidence that a field is safe, and the raw ratio says it is --
        exactly 0.0, with the same confidence whether we watched for ten
        seconds or ten hours. Used to decide how long to stay somewhere, that
        answer is "stay forever", and the first mantis then costs an entire
        full backpack.

        The other extreme is just as wrong. The 95% upper bound for zero
        events in time T is 3/T (the rule of three), and planning against it
        means planning for the worst case rather than the likely one: on 880
        observed seconds it demands 132-second trips against a 108-second
        round trip, so nearly half the night would be travelling.

        So this is the posterior mean under a Jeffreys prior -- half an event
        added to the count -- which starts cautious and converges on the truth
        as evidence arrives. On 880 seconds with no deaths it gives about one
        death per 1,760 s, which asks for a 385-second trip; after an hour
        clean it relaxes towards filling the backpack, and a single real death
        moves it sharply the other way.

        `seconds` here is time spent GATHERING in this field, which is the
        only time a mob could have killed us.
        """
        if self.seconds <= 0:
            return 0.0
        return (self.deaths + 0.5) / self.seconds

    def survival_over(self, seconds: float) -> float:
        """Chance of coming home with the backpack after a trip this long.

        A death is a rare, memoryless event in continuous time -- a mantis
        lands or it does not, and it does not become more likely because the
        last one missed -- so the exponential is the right shape rather than a
        convenient one. With nothing measured this returns 1.0, which is the
        honest answer: no evidence of danger is not evidence of safety, and
        the caller still has the wiki's mob list to discount by.
        """
        rate = self.death_rate
        if rate <= 0 or seconds <= 0:
            return 1.0
        return float(math.exp(-rate * seconds))

    @property
    def been_here(self) -> bool:
        """Have we gathered here at all, by measurement or by the feed?"""
        return self.proven or self.pays

    def describe(self) -> str:
        pretty = self.field.replace("_", " ")
        if not self.pays:
            return f"{pretty}: nothing gathered here yet ({self.seconds:.0f}s)"
        return (f"{pretty}: {self.pollen:,} pollen in {self.seconds:.0f}s "
                f"({self.rate:,.0f}/s over {self.visits} visit"
                f"{'' if self.visits == 1 else 's'})")


class FieldNotes:
    """Per-field records, written only when the game said where we were."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.notes: dict[str, Note] = {}
        self.unattributed = 0          # samples thrown away for lack of a fix
        self._last_field: str | None = None
        # The last field the GAME named, ever -- not cleared by a gap.
        self._seen_field: str | None = None
        self._last_pollen: int | None = None
        self._last_at: float | None = None
        # Set by `load` when a file from an older route generation had home
        # or sight failures that were NOT carried over. See HOME_DATA_VERSION.
        self.forgave_home_failures: list[str] = []
        # Which FALSE_DEATHS this record has already given back (a record
        # started from nothing never held them), and which `load` just gave
        # back, for the caller to say.
        self.false_deaths_removed: list[str] = sorted(FALSE_DEATHS)
        self.gave_back_deaths: list[str] = []
        # The same for HOME_STRIKES_FORGIVEN: which this record has already
        # given back, and "field (why)" for each that `load` just did.
        self.home_strikes_forgiven: list[str] = sorted(HOME_STRIKES_FORGIVEN)
        # And for TRAVEL_FAILURES_FORGIVEN: which this record has already given
        # back, and "field (why)" for each that `load` just did.
        self.travel_failures_forgiven: list[str] = sorted(TRAVEL_FAILURES_FORGIVEN)
        self.forgave_travel: list[str] = []
        self.forgave_home_strikes: list[str] = []
        # And for HOME_STRIKES_KEPT: which this record has already put back
        # after a give-back in full, and "field (why)" for each `load` did.
        self.home_strikes_kept: list[str] = sorted(HOME_STRIKES_KEPT)
        self.kept_home_strikes: list[str] = []

    # ---- recording --------------------------------------------------------
    def saw_rate(self, field: str | None, rate) -> Note | None:
        """One reading of the HUD's `(+N/sec)` while the game named `field`.

        Only ever with a fix, for the same reason as `saw_flowers`: a rate
        credited to the wrong field is worse than none. A None rate (the
        box was illegible) records nothing.
        """
        if field is None or rate is None:
            return None
        try:
            value = float(rate)
        except (TypeError, ValueError):
            return None
        if value < 0:
            return None
        note = self.notes.get(field) or Note(field=field)
        self.notes[field] = note
        note.printed_sum += value
        note.printed_samples += 1
        return note

    def saw_flowers(self, field: str | None, reading) -> Note | None:
        """Add one frame's petal counts to a field's running totals.

        `reading` is a `vision.flowers.Flowers`. A frame that did not show a
        flower bed is ignored rather than counted as zeroes -- walls, menus
        and the inside of a cannon are not evidence about a field's colour.
        """
        where = field or self._last_field
        if where is None or reading is None or not getattr(reading, "ok", False):
            return None
        note = self.notes.get(where) or self.notes.setdefault(where,
                                                              Note(where))
        pixels = int(getattr(reading, "pixels", 0) or 0)
        for colour in ("blue", "red", "white"):
            share = float(getattr(reading, colour, 0.0) or 0.0)
            note.petals[colour] = int(note.petals.get(colour, 0)
                                      + round(share * pixels))
        return note

    def field_since(self, when: float) -> str | None:
        """The field the game credited MOST RECENTLY, since `when`.

        WHY THIS AND NOT `credited_field`. That one reads `_seen_field`, which
        is whatever the last fix set -- and a fix costs a vision-model call on
        the reward feed, so when the model has been unloaded under memory
        pressure it is either stale or None. MEASURED 2026-09-22 03:05: the
        convert asked, got "nothing", and the pose search accepted a wrong
        hive slot because nothing contradicted it -- while `Note.last_seen`
        for the Dandelion Field had been updated during that very trip.

        `last_seen` is stamped on every sample the game attributed, so asking
        "which field was credited after this trip began" is the same question
        without the timing hazard. None means no field was credited in the
        window, which is a real answer and not an accusation.

        `when` MUST COME FROM THIS OBJECT'S OWN CLOCK -- `notes.clock()` --
        because that clock is `time.monotonic` by default and `last_seen` is
        stamped from it. A Unix timestamp is about 1.79e9 and monotonic is
        seconds since boot, so mixing them makes this return None for ever.
        It did exactly that on its first live outing.
        """
        best, newest = None, float(when)
        for name, note in self.notes.items():
            seen = float(getattr(note, "last_seen", 0.0) or 0.0)
            if seen >= newest:
                best, newest = name, seen
        return best

    @property
    def credited_field(self) -> str | None:
        """The field the game's own reward feed last named, or None.

        The reward feed is the one position signal measured to be reliable
        (DESIGN 8b), so this is how `nav.journey.wrong_place` can tell a trip
        that arrived from one that landed a field over -- a distinction `go`
        cannot make, because a field has no prompt.
        """
        return self._seen_field or self._last_field

    def travel_failed(self, field: str | None, at: float | None = None) -> Note | None:
        """A trip to `field` never arrived. See `Note.travel_failures`; `at`
        is wall-clock time, now by default (`Note.failed_at`)."""
        if not field:
            return None
        note = self.notes.get(field) or self.notes.setdefault(field,
                                                              Note(field))
        note.travel_failures += 1
        note.failed_at = time.time() if at is None else float(at)
        return note

    def sight_failed(self, field: str | None) -> Note | None:
        """Homing BY SIGHT did not find the pad from `field`.

        Counted apart from `home_failures`, which is the recorded route's
        record. MEASURED 2026-09-22 22:00-22:40: `home_by_sight` landed once
        in nine attempts, and each failure spends up to 24 looks (about 40 s)
        before the rejoin banks the bag anyway. A field whose sight homing has
        failed SIGHT_TRIES times in a row is one where those 40 s are a
        certainty, not a chance, so the caller skips straight to the rejoin.
        """
        if not field:
            return None
        note = self.notes.get(field) or self.notes.setdefault(field, Note(field))
        note.sight_failures += 1
        return note

    def sighted_home(self, field: str | None) -> Note | None:
        """It DID home by sight from `field`: forgive the failures."""
        if not field:
            return None
        note = self.notes.get(field) or self.notes.setdefault(field, Note(field))
        note.sight_failures = 0
        return note

    def home_failed(self, field: str | None) -> Note | None:
        """The walk home from `field` did not reach the hive."""
        if not field:
            return None
        note = self.notes.get(field) or self.notes.setdefault(field,
                                                              Note(field))
        note.home_failures += 1
        return note

    def walked_home(self, field: str | None) -> Note | None:
        """It DID walk home from `field`, so forgive the failures."""
        if not field:
            return None
        note = self.notes.get(field) or self.notes.setdefault(field,
                                                              Note(field))
        note.home_failures = 0
        note.home_probes = 0
        note.home_probe_at = 0.0
        return note

    def probing_home(self, field: str | None, at: float) -> Note | None:
        """Stamp when the latched walk home from `field` was tried anyway, or
        when the latch formed. `at` is wall-clock time (`time.time()`): the
        wait between probes spans rejoins, which the monotonic clock does not
        survive. See `Note.home_probe_at`."""
        if not field:
            return None
        note = self.notes.get(field) or self.notes.setdefault(field, Note(field))
        note.home_probe_at = float(at)
        return note

    def probe_missed(self, field: str | None) -> Note | None:
        """A probe of the latched walk home from `field` did not land."""
        if not field:
            return None
        note = self.notes.get(field) or self.notes.setdefault(field, Note(field))
        note.home_probes += 1
        return note

    def arrived(self, field: str | None) -> Note | None:
        """A trip to `field` DID arrive, so forgive the failures."""
        if not field:
            return None
        note = self.notes.get(field) or self.notes.setdefault(field,
                                                              Note(field))
        note.travel_failures = 0
        return note

    def died(self, field: str | None = None) -> Note | None:
        """Record that the character died in a field.

        `field` defaults to the last field the GAME named, which is the right
        answer: a death is noticed by the pollen counter collapsing, and by
        then the character has already been teleported to the hive, so asking
        where it is NOW would credit the death to the hive.

        IT USES `_seen_field`, NOT `_last_field`, AND THAT DISTINCTION IS THE
        WHOLE FEATURE. `_last_field` is interval bookkeeping: any sample the
        game did not attribute clears it, so that no pollen interval spans a
        gap. But a death is exactly the moment the feed goes quiet -- the
        character is dying, respawning, and the reward feed has nothing to say.
        MEASURED on 2026-09-21: a real death in the Pineapple Patch recorded
        `deaths: 0`, because `_last_field` had been cleared a moment earlier by
        an unattributed sample. The danger-learning that death was supposed to
        feed was therefore inert -- it would never have learned that anywhere
        was dangerous, however often it died there.
        """
        where = field or self._seen_field or self._last_field
        if where is None:
            return None
        note = self.notes.get(where) or self.notes.setdefault(where,
                                                              Note(where))
        note.deaths += 1
        # The character is not in that field any longer, so end the interval.
        # Without this the next pollen reading -- taken at the hive after the
        # respawn -- would be credited to the field it died in. `_seen_field`
        # is deliberately NOT cleared: it is what makes a SECOND death in the
        # same trip land on the same field.
        self._last_field = None
        self._last_pollen = None
        self._last_at = None
        return note

    def took_back_death(self, field: str | None) -> bool:
        """Undo one `died` for `field`: the feed has named a field since, so
        that fall was not a death (alive.field_after_death, ROADMAP A9 rule
        D2). False when there is none to take back."""
        note = self.notes.get(field) if field else None
        if note is None or note.deaths <= 0:
            return False
        note.deaths -= 1
        return True

    def note(self, field: str | None, pollen: int | None) -> Note | None:
        """One sample. `field` is None when the game has not said where we are.

        Returns the note that was credited, or None when the sample was thrown
        away. Time and pollen are credited to the field we were in DURING the
        interval, which is the previous sample's field, not this one's.
        """
        now = self.clock()
        if field is None:
            # No fix. End the interval so nothing spans the gap, and throw the
            # sample away rather than attribute it to a stale field.
            self.unattributed += 1
            self._last_field = None
            self._last_pollen = pollen
            self._last_at = now
            return None

        note = self.notes.get(field)
        if note is None:
            note = self.notes[field] = Note(field=field)
        note.samples += 1
        note.last_seen = now
        note.last_wall = time.time()
        note.proven = True      # the game named this field; we were here
        # WHERE WE LAST WERE, kept separately from `_last_field`. That one is
        # interval bookkeeping and is deliberately cleared by any sample the
        # game did not attribute, so that no pollen interval spans a gap. This
        # one is memory, and nothing clears it. See `died`.
        self._seen_field = field
        if self._last_field != field:
            note.visits += 1

        credited = None
        if self._last_field == field and self._last_at is not None:
            interval = max(0.0, now - self._last_at)
            note.seconds += interval
            if (self._last_pollen is not None and pollen is not None
                    and pollen >= self._last_pollen):
                gained = pollen - self._last_pollen
                if gained <= IMPLAUSIBLE_JUMP:
                    note.pollen += gained
                    # ONLY THESE SECONDS PRICE THE FIELD, AND ONLY THIS
                    # POLLEN GOES WITH THEM. An interval whose ends could not
                    # both be read says nothing about the rate, and counting
                    # it diluted Rose from 1,019 pollen/s to 398. The two
                    # lines move together or the rate is a ratio of two
                    # different spans of time -- see `Note.paid_pollen`.
                    note.paid_seconds += interval
                    note.paid_pollen += gained
            credited = note

        self._last_field, self._last_pollen, self._last_at = field, pollen, now
        return credited or note

    def missed_it(self, field: str, give_up: int | None = None) -> None:
        """A trip aimed at `field` and the game credited somewhere else.

        Evidence about the ROUTE, not the field, so it never bars anything.
        See `Note.missed`.

        EXCEPT ON A FIELD ALREADY GIVEN UP ON (`travel_failures` at `give_up`,
        brain/decide TRAVEL_FAILURES_TO_GIVE_UP): only a quest retry, the pin
        or the field boost sends a trip there, and one that mis-delivers has
        used that retry -- it counts as a travel failure, so `failed_at`
        restarts decide.QUEST_RETRY_AFTER_S. MEASURED 2026-10-19 run-1085: the
        Bamboo retry landed in Spider at 12:11, the miss stamped nothing, and
        the very next plan (12:11:56) sent the same retry again -- Spider and
        Mushroom for 20 min at ~5,000 pollen/s instead of Pineapple's 7,959."""
        if not field:
            return
        note = self.notes.get(field) or self.notes.setdefault(field, Note(field))
        note.missed += 1
        if give_up is not None and note.travel_failures >= give_up:
            self.travel_failed(field)

    def saw(self, field: str, what: str) -> None:
        """A sentence about a field, kept once."""
        note = self.notes.get(field) or self.notes.setdefault(field, Note(field))
        text = " ".join(str(what).split())[:160]
        if text and text not in note.saw:
            note.saw.append(text)

    # ---- asking -----------------------------------------------------------
    def best(self) -> list[Note]:
        """Fields that paid, richest first. The point of the whole exercise."""
        return sorted((n for n in self.notes.values() if n.pays),
                      key=lambda n: -n.rate)

    def known(self, field: str) -> Note | None:
        return self.notes.get(field)

    def describe(self) -> str:
        paying = self.best()
        if not self.notes:
            return "no fields recorded yet"
        head = (f"{len(self.notes)} field{'' if len(self.notes) == 1 else 's'} "
                f"seen, {len(paying)} of them paying")
        if paying:
            head += f"; best {paying[0].describe()}"
        if self.unattributed:
            head += (f" ({self.unattributed:,} samples discarded — "
                     "the game did not say where we were)")
        return head

    # ---- how dangerous is somewhere we have never been? -------------------
    def pooled_death_rate(self) -> float:
        """Deaths per gathering-second across EVERY field, smoothed.

        A field we have never gathered in has no evidence of its own, and
        `Note.likely_death_rate` correctly returns nothing for it. That leaves
        the caller deciding how long to stay somewhere entirely unknown, and
        answering "until the backpack is full" is the optimistic reading of no
        information rather than the honest one.

        What we DO know is how often this character dies while gathering,
        anywhere. That is the right prior for a new field: it is measured, it
        is about this account and this walking pattern, and it is exactly what
        an empirical-Bayes prior is. The wiki's mob list still applies on top,
        through the planner's danger discount.
        """
        seconds = sum(n.seconds for n in self.notes.values())
        deaths = sum(n.deaths for n in self.notes.values())
        if seconds <= 0:
            return 0.0
        return (deaths + 0.5) / seconds

    def danger_of(self, field: str) -> float:
        """The death rate to plan a trip to `field` around.

        Its own record SHRUNK TOWARDS the pooled rate, by how much of its own
        record there is.

        THIS USED TO SWITCH RATHER THAN SHRINK -- the pooled rate only when a
        field had never been gathered in at all, and the field's own Jeffreys
        rate the moment it had even one second. `pooled_death_rate` calls
        itself "exactly what an empirical-Bayes prior is", and it was right;
        it was just being used as a fallback instead of as a prior, and
        empirical Bayes means shrinking towards the prior, not jumping to it.

        MEASURED 2026-09-22 04:56, and it was costing most of the night:

            field       watched   own rate    trip it asked for
            rose            9 s   5.5e-02/s   60 s   (927 pollen/s measured!)
            sunflower      74 s   6.8e-03/s   83 s
            dandelion   2,490 s   2.0e-04/s   681 s
            pineapple  22,772 s   2.2e-05/s   1,200 s

        Zero deaths in every one of them, and zero deaths all night. The
        character's pooled rate is 1.96e-05/s. So the LEAST watched field got
        the SHORTEST trip -- 83 seconds against a 108-second round trip, which
        loses money outright -- and the best field in the game by measured
        rate got 60 seconds, purely for being new. The planner's curiosity
        bonus then kept choosing exactly those fields, so the bot spent the
        night on 83-second trips to places it had no reason to fear.

        With the prior worth `DEATH_PRIOR_SECONDS` of observation, a field
        needs about one trip of its own history before its record outweighs
        what this character has done everywhere else. The extremes are
        unchanged: nothing observed gives exactly the pooled rate, and a lot
        observed converges on `deaths / seconds`.

        WHAT STILL GUARDS A GENUINELY DANGEROUS FIELD, because this does
        relax a caution: not this number. The mob rules do, from the wiki's
        knowledge rather than from experience, and they are visibly working --
        "carrying 690,029 pollen and it is guarded by rhino_beetle — not worth
        the risk" appears throughout the logs. Measured death experience and
        known mob danger are two different mechanisms, and only the first one
        should need evidence to relax.
        """
        note = self.notes.get(field)
        prior = self.pooled_death_rate()
        if note is None or note.seconds <= 0:
            return prior
        tau = DEATH_PRIOR_SECONDS
        return (note.deaths + prior * tau) / (note.seconds + tau)

    # ---- remembering ------------------------------------------------------
    def save(self, path) -> Path:
        """Write the notes out, ATOMICALLY.

        These notes are the only thing that decides where the bot goes, and
        they are rebuilt from nothing if the file is unreadable. A direct
        `write_text` truncates first and fills second, so a crash or a kill
        in between leaves a half-written JSON file -- and `load` catching the
        parse error means the loss looks exactly like a fresh account. Writing
        a sibling file and renaming it makes the swap a single filesystem
        operation: either the old notes or the new ones, never neither. 249
        runs had started by 2026-09-23 and 12 of them ended in a traceback,
        so this is a 5%-of-runs hazard, not a theoretical one.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({
            "fields": {
                name: {"seconds": round(n.seconds, 1), "pollen": n.pollen,
                       "visits": n.visits, "samples": n.samples,
                       "proven": n.proven, "deaths": n.deaths,
                       "travel_failures": n.travel_failures,
                       "failed_at": round(n.failed_at, 1),
                       "missed": n.missed,
                       "home_failures": n.home_failures,
                       "sight_failures": n.sight_failures,
                       "home_probe_at": round(n.home_probe_at, 1),
                       "home_probes": n.home_probes,
                       "paid_seconds": round(n.paid_seconds, 1),
                       "paid_pollen": n.paid_pollen,
                       "printed_sum": round(n.printed_sum, 1),
                       "printed_samples": n.printed_samples,
                       "petals": n.petals, "saw": n.saw}
                for name, n in sorted(self.notes.items())
            },
            "unattributed": self.unattributed,
            "home_data_version": HOME_DATA_VERSION,
            "false_deaths_removed": list(self.false_deaths_removed),
            "home_strikes_forgiven": list(self.home_strikes_forgiven),
            "travel_failures_forgiven": list(self.travel_failures_forgiven),
            "home_strikes_kept": list(self.home_strikes_kept),
        }, indent=1)
        spare = path.with_name(path.name + ".writing")
        spare.write_text(body)
        spare.replace(path)
        return path

    def load(self, path) -> int:
        """Merge a saved file in. Returns how many fields were remembered."""
        path = Path(path)
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return 0
        before = len(self.notes)
        carry_home = int(data.get("home_data_version", 1) or 1) >= HOME_DATA_VERSION
        for name, body in (data.get("fields") or {}).items():
            note = self.notes.get(name) or Note(field=name)
            note.seconds += float(body.get("seconds", 0.0))
            note.pollen += int(body.get("pollen", 0))
            note.visits += int(body.get("visits", 0))
            note.samples += int(body.get("samples", 0))
            note.proven = note.proven or bool(body.get("proven", False))
            note.deaths += int(body.get("deaths", 0) or 0)
            # NOT ADDED UP ACROSS SESSIONS. This counts failures IN A ROW and
            # a new session is a fresh start: the game was relaunched, the
            # hive re-claimed, and the route may well work this time.
            note.travel_failures = max(note.travel_failures,
                                       int(body.get("travel_failures", 0) or 0))
            note.failed_at = max(note.failed_at, float(body.get("failed_at", 0.0) or 0.0))
            if carry_home:
                note.home_failures = max(note.home_failures,
                                         int(body.get("home_failures", 0) or 0))
                note.sight_failures = max(note.sight_failures,
                                          int(body.get("sight_failures", 0) or 0))
                note.home_probes = max(note.home_probes,
                                       int(body.get("home_probes", 0) or 0))
                note.home_probe_at = max(note.home_probe_at,
                                         float(body.get("home_probe_at", 0.0) or 0.0))
            elif (int(body.get("home_failures", 0) or 0)
                  or int(body.get("sight_failures", 0) or 0)):
                self.forgave_home_failures.append(name)
            note.missed = max(note.missed, int(body.get("missed", 0) or 0))
            # A `paid_seconds` WITH NO `paid_pollen` IS NOT A MEASUREMENT.
            # Notes written by the version that shipped `paid_seconds` alone
            # cannot say which pollen those seconds bought, and pairing them
            # with the field's whole historical `pollen` is what priced
            # Dandelion at 5,186/s. Such a file is read as having no paid
            # measurement at all, and the field falls back to
            # `pollen / seconds` until it is farmed again.
            note.printed_sum += float(body.get("printed_sum", 0.0) or 0.0)
            note.printed_samples += int(body.get("printed_samples", 0) or 0)
            paid_s = float(body.get("paid_seconds", 0.0) or 0.0)
            paid_p = int(body.get("paid_pollen", 0) or 0)
            if paid_p > 0:
                note.paid_seconds += paid_s
                note.paid_pollen += paid_p
            for colour, count in (body.get("petals") or {}).items():
                note.petals[colour] = int(note.petals.get(colour, 0)
                                          + int(count or 0))
            for text in body.get("saw", []):
                if text not in note.saw:
                    note.saw.append(text)
            self.notes[name] = note
        self.unattributed += int(data.get("unattributed", 0))
        # ONE FIELD, ONE NOTE. Rose's trips were filed under the router node
        # "rose_field" as well as under "rose" (run_farm stored the aim through
        # ROUTER_ALIASES), so var/field_notes.json holds an all-zero
        # "rose_field" beside Rose's real record -- and a strike filed there
        # was read by nothing (DESIGN 8ds). Folded in once, then gone.
        from .decide import ROUTER_ALIASES
        for name, node in ROUTER_ALIASES.items():
            stray = self.notes.pop(node, None) if node != name else None
            if stray is None:
                continue
            note = self.notes.get(name) or Note(field=name)
            for attr in ("seconds", "pollen", "visits", "samples", "deaths",
                         "paid_seconds", "paid_pollen", "printed_sum",
                         "printed_samples"):
                setattr(note, attr, getattr(note, attr) + getattr(stray, attr))
            for attr in ("travel_failures", "failed_at", "missed", "home_failures",
                         "sight_failures", "home_probes", "home_probe_at",
                         "last_seen"):
                setattr(note, attr, max(getattr(note, attr), getattr(stray, attr)))
            note.proven = note.proven or stray.proven
            for colour, count in stray.petals.items():
                note.petals[colour] = int(note.petals.get(colour, 0) + count)
            note.saw.extend(t for t in stray.saw if t not in note.saw)
            self.notes[name] = note
        # AND THE DEATHS THAT WERE CONVERSION LINKS, taken back once. See
        # FALSE_DEATHS. A file written before this list existed gets all of
        # them; a file that lists what it already gave back gets the rest.
        done = data.get("false_deaths_removed")
        done = set(done) if isinstance(done, list) else set()
        for incident, field in FALSE_DEATHS.items():
            note = self.notes.get(field)
            if incident not in done and note is not None and note.deaths > 0:
                note.deaths -= 1
                self.gave_back_deaths.append(f"{field} ({incident})")
        self.false_deaths_removed = sorted(FALSE_DEATHS)
        # AND THE WALK-HOME STRIKES OF HOME_STRIKES_FORGIVEN, given back once:
        # both counters down to what HOME_STRIKES_KEPT keeps, the probes and
        # their stamp, so the next trip from there walks home at once instead
        # of waiting for a probe.
        done = data.get("home_strikes_forgiven")
        done = set(done) if isinstance(done, list) else set()
        kept = data.get("home_strikes_kept")
        kept = set(kept) if isinstance(kept, list) else set()
        for field, why in HOME_STRIKES_FORGIVEN.items():
            note = self.notes.get(field)
            if note is None:
                continue
            keep, keep_why = HOME_STRIKES_KEPT.get(field, (0, ""))
            if field not in done:
                if (note.home_failures or note.sight_failures or note.home_probes
                        or note.home_probe_at):
                    note.home_failures = min(note.home_failures, keep)
                    note.sight_failures = min(note.sight_failures, keep)
                    note.home_probes = 0
                    note.home_probe_at = 0.0
                    self.forgave_home_strikes.append(
                        f"{field} ({why}" + (f"; {keep} kept: {keep_why})" if keep else ")"))
            elif keep and field not in kept:
                note.home_failures = max(note.home_failures, keep)
                note.sight_failures = max(note.sight_failures, keep)
                self.kept_home_strikes.append(f"{field} ({keep} route and {keep} sight "
                                              f"failure: {keep_why})")
        self.home_strikes_forgiven = sorted(HOME_STRIKES_FORGIVEN)
        # AND THE TRIPS THAT NEVER ARRIVED, for a field whose route was fixed:
        # once, so the planner tries the fixed route (TRAVEL_FAILURES_FORGIVEN).
        done = data.get("travel_failures_forgiven")
        done = set(done) if isinstance(done, list) else set()
        for field, why in TRAVEL_FAILURES_FORGIVEN.items():
            note = self.notes.get(field)
            if field not in done and note is not None and note.travel_failures:
                note.travel_failures = 0
                self.forgave_travel.append(f"{field} ({why})")
        self.travel_failures_forgiven = sorted(TRAVEL_FAILURES_FORGIVEN)
        self.home_strikes_kept = sorted(HOME_STRIKES_KEPT)
        return len(self.notes) - before

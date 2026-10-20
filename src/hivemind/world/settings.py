"""The settings schema, and the loader both sides use.

This lives in the core rather than in the GUI because both processes need it and
neither owns it. The GUI builds its controls from `SECTIONS`; the bot reads the
same keys back through `Settings`. One declaration, so a control can never exist
without something reading it, and a setting can never be read that no control
can reach.

Every entry carries an explanation, and that is a requirement rather than a
nicety. A macro with sixty cryptic toggles is worse than one with ten, because
you cannot tell which of them is quietly costing you honey.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from ..datapaths import config_dir
from ..files import atomic_write
from .userpatterns import ROUTE_PREFIX as USER_PREFIX, is_route_name

CONFIG = config_dir() / "settings.yaml"

# SETTINGS NOTHING READS YET.
#
# The schema is deliberately ahead of the engines -- it is the roadmap, and
# writing it down first is what keeps a setting from being invented later to
# match whatever the code happens to do. But a control that looks live and does
# nothing is a lie told by the interface, and the owner's rule is explicit:
# "dont add fake things for looks it needs to work and actaully be useefull".
#
# So every key here is shown DISABLED in the GUI and labelled "not built yet".
# `tests/unit/test_settings.py` scans the source and fails if this set drifts
# in either direction -- a key listed here that something now reads, or a key
# missing from here that nothing reads. It cannot rot quietly.
NOT_WIRED = {
    # Gathering: the loop exists; these parts of it do not yet
    # gather.auto_field and gather.field became real on 2026-09-20, when
    # brain/decide.Planner gave the bot something that could actually choose.
    # gather.convert_at became real on 2026-09-20: brain/decide.from_settings
    # now sets the planner's threshold from it.
    # gather.chase_tokens and gather.token_radius became real on 2026-09-21:
    # `vision/tokens.py` finds tokens by their white glyph and its black
    # outline, and `act/chase.py` walks to one between pattern passes and back.
    # The owner asked for it directly -- "i really want token vission to".
    # gather.rotate_camera became real on 2026-10-14: run_farm's between-pass
    # step sweeps the camera for bubbles (act/camsweep), off by default.
    # Economy: the engines compute, but nothing acts on them in game yet.
    #
    # The clock/booster/dispenser three are the closest to real and worth
    # describing precisely, because they LOOK finished from the code side.
    # `act/errands.py` walks a recorded route, reads the game's own prompt and
    # presses the interact key only if the prompt agrees -- written, tested and
    # safe. `data/knowledge/errands.yaml` holds the places and the switch
    # mapping. What is missing is not code: MEASURED 2026-09-21, the bot walked
    # the routes to the Wealth Clock, the Blue Field Booster and the Royal
    # Jelly Dispenser and the top-centre panel was EMPTY at all three. Those
    # routes came from BeeTuxMacro and land close enough to finish a timed walk
    # and not close enough for the game to offer a prompt. One recorded walk
    # per place fixes it; until then the switches would do nothing, so they
    # stay here.
    # economy.planters became real on 2026-10-14: act/planter.switched_off is
    # asked by run_farm's planter errand, its tend and its Paper Planter buy.
    # The nectar-vial one stays: no code condenses anything, and the 12 h
    # mechanic itself is unverified (data/economy/expiries.yaml).
    "economy.min_field_health", "economy.nectar_vials",
    # Combat. combat.retreat_health became real on 2026-09-25: act/bugrun
    # leaves a fight when vision/hurt.own_health reads the character's own
    # bar at or under it (DESIGN 8do). combat.bug_runs and the per-mob
    # switches beside it are read by act/bugrun too. combat.bosses became
    # real on 2026-10-06: run_farm fights the Coconut Crab (act/crab) only
    # with it on. combat.vicious became real on 2026-10-12: run_farm hunts the
    # Vicious Bee at night (act/vicious) only with it on. combat.stump_snail
    # was born real on 2026-10-12 (act/stumpsnail), and so was combat.commando:
    # run_farm fights the Commando Chick (act/commando) only with it on.
    "combat.mobs",
    # Quests. quests.enabled became real on 2026-09-20: act/quests reads the
    # menu, and act/quests.wanted() is what decides whether it bothers. The
    # per-bear toggles below are still nothing -- reading a quest list is not
    # the same as doing one.
    "quests.science",
    # Autonomy: the arbiter reads the rest, but nothing times questions out
    "autonomy.question_timeout_m",
    # ...AND NOTHING RUNS THE ARBITER (DESIGN 8du). brain/autonomy.Arbiter is
    # the only reader of these three, and no module in src/ or scripts/
    # imports brain.autonomy -- so "Minimum confidence for irreversible
    # acts" looked live and changed nothing (combat.vicious and
    # economy.early_harvest, the other two, are
    # run_farm's own switches now). The
    # owner's own file shows what that costs: autonomy.min_confidence 8.9 and
    # max_spend 4999997, mouse-wheel accidents nobody noticed because nothing
    # read them.
    "autonomy.mode", "autonomy.max_spend", "autonomy.min_confidence",
    # Movement. move.walkspeed became real on 2026-09-20 -- act/routes
    # .walkspeed_from reads it, and every timed hold in the project is
    # studs/walkspeed, so it was the most load-bearing unwired control here.
    "move.open_loop", "move.reset_to_start",
    # Safety. never_chat and max_session_h became real on 2026-09-20:
    # platform/input.type_text now REFUSES to type while the game has focus
    # and the flag is set -- the rule was true by construction before, and a
    # rule nothing enforces only lasts until somebody writes the code that
    # breaks it -- and brain/alive.SessionCap stops the run at the hour limit.
    # safety.jitter became real on 2026-09-20: act/clicker.interval() reads it
    # and falls back to a flat metronome when it is off.
    "safety.click_mode",
    # Performance. The note that used to sit here said "there is no vision
    # model in this project -- no Qwen, no ONNX runtime, no inference code of
    # any kind", and it has been false for some time: `brain/vlm.py` runs
    # qwen2.5vl through ollama and reads both `perf.vlm` and `perf.vlm_model`,
    # which is why neither is listed below. Left as a note rather than deleted
    # because a comment that confidently describes a thing that no longer
    # exists is worse than no comment.
    #
    # It is also the machine's largest single cost: MEASURED, llama-server
    # holds 3.9 to 8.7 GB while the reward feed is being read. Turning
    # `perf.vlm` off is the one lever that frees it, at the price of the bot
    # no longer knowing which field it is standing in.
    # perf.capture_fps became real on 2026-09-20: telemetry/liveview.fps_from
    # reads it, and it is a stability control -- concurrent screencopy clients
    # have killed the game before.
    "perf.render_unfocused", "perf.record",
}


# WHAT IS ACTUALLY STOPPING EACH ONE. "not built yet" is honest and useless:
# it tells the owner a switch is dead without telling him whether that is a
# week of work or one walk around the map. Most of these are the latter, and he
# cannot know that unless it is written down where he will see it.
#
# Every line is the real blocker, not a plan. Where the answer is "show it
# once", it says so, because those are the ones worth his five minutes.
BLOCKED_BY = {
    # Gathering
    # Economy
    "economy.min_field_health": "nothing reads a field-health number: an "
                                "early harvest (economy.early_harvest) never "
                                "checks one",
    "economy.nectar_vials": "nothing condenses nectar into a Vial: the Nectar "
                            "Condenser stands past the 35-bee Windy Bee Gate "
                            "and this hive has 34 (N4; data/knowledge/economy.yaml)",
    # Combat
    "combat.mobs": "clearing a mob that comes at the character WHILE it "
                   "gathers is not built: brain/threat still cuts the walk "
                   "short and steps on. Killing them on purpose is the bug "
                   "runs (combat.bug_runs), after a convert with the bag empty",
    # Quests
    "quests.science": "The classic macro has paths for six quest givers and the Science Bear is not one of them, so there is nowhere to walk and this switch could not change anything. The account is HOLDING a finished quest for this bear -- Ready For Infrared, all six requirements 'Complete! Talk to Science Bear' -- so what is missing is one recorded route, not code. See docs/GAPS.md",
    # Autonomy
    "autonomy.question_timeout_m": "nothing asks questions yet; the bot runs "
                                   "on autopilot",
    "autonomy.mode": "brain/autonomy.Arbiter is not wired into the farm loop, "
                     "so the bot runs on autopilot whatever this says",
    "autonomy.max_spend": "brain/autonomy.Arbiter is not wired into the farm "
                          "loop; the bot spends nothing unattended anyway",
    "autonomy.min_confidence": "brain/autonomy.Arbiter is not wired into the "
                               "farm loop",
    # Movement
    "move.open_loop": "every route is already open-loop; there is no closed-"
                      "loop alternative to switch to",
    "move.reset_to_start": "REFUSED BY DESIGN: a reset is a death, and death "
                           "empties the backpack and sends every bee home",
    # Safety
    "safety.click_mode": "event-driven clicking needs something to detect the "
                         "event; nothing does yet",
    # Performance
    "perf.render_unfocused": "set by Sober's own flags, not by this bot",
    "perf.record": "the incident recorder already saves frames when something "
                   "goes wrong, which is the useful half of this",
}


def blocked_by(key: str) -> str:
    """Why `key` does nothing yet, in one line. Empty when it works."""
    return "" if wired(key) else BLOCKED_BY.get(key, "")


def wired(key: str) -> bool:
    """Does anything actually read this setting yet?"""
    return key not in NOT_WIRED


# SETTINGS THAT CANNOT BE TURNED OFF (DESIGN 8du). safety.never_chat was
# described as "Locked on" and drawn as a live checkbox; one click wrote
# `false`, and the next run's platform/input would then have typed into a
# focused game -- AppUI.search taps '/', which opens chat, types, and Enter
# sends it. Talking to players is the one behaviour this project has ruled
# out, so the file cannot switch it: `Settings.reload` forces these values
# and says so, the panel draws them disabled, and platform/input ignores the
# setting altogether.
LOCKED = {"safety.never_chat": True}


# SETTINGS THAT ARE SECRETS (DESIGN 8ed). The YouTube Data API key is a
# credential on the owner's Google Cloud project: whoever holds it spends his
# quota. The panel draws it as a password field, and the window tells the bot
# that it changed without sending the value (the bot re-reads the file and
# has no use for it).
# NOT IN settings.yaml (master plan G, 2026-10-14): a secret lives in
# secrets.env beside it (0600, like telegram.env), one NAME=value line each,
# under the name given here. A value still in settings.yaml is read once as
# the migration source and moved by migrate_secrets (the GUI on opening and
# on each save, the bot at start); nothing writes one back there.
# server.link (ROADMAP M11): a private server's share link lets whoever holds
# it into that server, so it is kept as server.yaml's private_link is -- a
# 0600 file, never in a log -- and drawn as dots.
# account.share_link (2026-10-22, the Windows Claude's bundle review): the
# Windows/alt join's private-server link, the same kind of way in as server.link.
SECRET = {"stream.youtube_api_key": "YOUTUBE_API_KEY", "server.link": "SERVER_LINK",
          "account.share_link": "SHARE_LINK"}


def secrets_path(config: Path | str = CONFIG) -> Path:
    """secrets.env, beside the settings file it belongs to."""
    return Path(config).with_name("secrets.env")


def _secret_lines(config) -> dict[str, str]:
    """secrets.env as NAME -> value; {} when absent or unreadable."""
    out: dict[str, str] = {}
    try:
        text = secrets_path(config).read_text()
    except OSError:
        return out
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            out[name.strip()] = value.strip()
    return out


def read_secrets(config: Path | str = CONFIG) -> dict[str, str]:
    """The secrets as settings keys -> value (empty ones left out)."""
    lines = _secret_lines(config)
    return {key: lines[name] for key, name in SECRET.items() if lines.get(name)}


def write_secret(config: Path | str, key: str, value) -> None:
    """One secret into secrets.env (an empty value removes it), atomic, 0600.
    Other lines in the file are kept."""
    lines = _secret_lines(config)
    value = str(value or "").strip()
    if value:
        lines[SECRET[key]] = value
    else:
        lines.pop(SECRET[key], None)
    atomic_write(secrets_path(config),
                 "".join(f"{k}={v}\n" for k, v in lines.items()), mode=0o600)


# SWITCHES THAT BECAME CHOICES: the owner's file still holds the old bool
# (`gather.rotate_camera: true`, a switch until 2026-10-14). It reads as the
# default on purpose (the old `true` must not turn a new behaviour on), and
# without a "problems" line at every re-read (ROADMAP S11).
RETIRED_BOOLS = frozenset({"gather.rotate_camera"})


def migrate_secrets(config: Path | str = CONFIG) -> list[str]:
    """Move any secret still in settings.yaml into secrets.env and take it out
    of settings.yaml; the keys moved (never their values). A value already in
    secrets.env wins. Never raises: an unreadable file is left as it is.
    The secret is written before settings.yaml loses it, so a crash between
    the two leaves it in both, never in neither."""
    config = Path(config)
    try:
        stored = yaml.safe_load(config.read_text()) if config.exists() else None
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(stored, dict):
        return []
    moved = [key for key in SECRET if key in stored]
    if not moved:
        return []
    try:
        have = read_secrets(config)
        for key in moved:
            value = stored.pop(key)
            if str(value or "").strip() and key not in have:
                write_secret(config, key, value)
        atomic_write(config, yaml.safe_dump(stored, sort_keys=True), mode=0o600)
    except OSError:
        return []
    return moved


# THE RANGE EACH NUMBER IS ACTUALLY READ WITHIN (DESIGN 8du), as (low, high,
# step); step None keeps Qt's default. The GUI's spin boxes accepted 0 to 1e9
# and a QDoubleSpinBox steps by 1.0, so eight wheel notches over a fraction
# took autonomy.min_confidence from 0.9 to 8.9 in the owner's file (and three
# took autonomy.max_spend from 5,000,000 to 4,999,997). Inside these bounds
# every reader takes the number as it is, so the box cannot show a value the
# bot would silently change. Outside them most readers clamp to the bound --
# but not all; see UNSET_WHEN:
#   gather.convert_at        decide.from_settings clamps to 0.1..1.0 of the bag
#   gather.chase_confidence  chase.chase_confidence_from clamps to 0.30..0.95
#   move.glide_scale         act/routes._glide_scale clamps to GLIDE_SCALE_BOUNDS
#   move.glide_side_scale    act/routes._glide_scale clamps to GLIDE_SIDE_BOUNDS
#   move.hive_slot           nav/journey.slot_from: 1..HIVE_SLOTS (6), 0
#                            means unknown
#   perf.capture_fps         LiveView.fps_from clamps to 60 (an int, so 1 is
#                            the lowest the 0.5 floor can be written as)
#   perf.overlay_ms          LiveView.overlay_seconds_from clamps to 50..3000
#   gather.camera_tilt       farm.gather_tilt_from floors at 0; nothing
#                            measured a ceiling (DESIGN 8ad), so none is set
#   gather.camera_zoom_out   farm.gather_zoom_from clamps to 0..8, Natro's
#                            own most (farm.GATHER_ZOOM_MOST)
#   autonomy.min_confidence  a Belief confidence, 0..1 (telemetry/events);
#                            0.01 steps, the two decimals a QDoubleSpinBox
#                            shows by default
#   economy.min_field_health, combat.retreat_health   percentages
BOUNDS = {
    "gather.convert_at": (10, 100, None),
    "gather.chase_confidence": (30, 95, None),
    "move.hive_slot": (0, 6, None),
    "hive.grind_slot": (0, 50, None),
    "hive.grind_max_honey": (0, 2_000_000_000, 10_000_000),
    "hive.grind_max_jellies": (0, 1000, None),
    "server.hop_per_night": (0, 20, None),
    "server.hop_minutes": (1, 30, None),
    "move.glide_scale": (0.3, 1.5, 0.05),
    "move.glide_side_scale": (0.5, 4.0, 0.25),
    "perf.capture_fps": (1, 60, None),
    "perf.overlay_ms": (50, 3000, None),
    "gather.camera_tilt": (0, 1_000_000_000, None),
    "gather.camera_zoom_out": (0, 8, None),
    "stream.voice_volume": (0, 100, None),
    "autonomy.min_confidence": (0.0, 1.0, 0.01),
    "economy.min_field_health": (0, 100, None),
    "economy.tickets.keep": (0, 100_000, None),
    "combat.retreat_health": (0, 100, None),
    "storage.retention_gb": (0, 10_000, None),
}


# WHERE THE READER DOES NOT CLAMP (DESIGN 8du). These readers treat some
# numbers outside BOUNDS as "not set" and use their own default -- or
# "unknown" -- instead of the nearest bound. Clamping those to the bound
# handed the reader a real value it then acted on: hive_slot 7 became slot 6
# (the formula walks to somebody else's pad), convert_at 0 banked at 10% of
# the bag, chase_confidence 0 chased at 0.3 (bees pass that), capture_fps 0
# captured at 1 fps and overlay_every 0 drew every frame (the measured fps
# halving; perf.overlay_ms replaced it, DESIGN 8eb). So these become the
# setting's default, which is exactly what each
# reader falls back to:
#   gather.convert_at        0 -> 95: decide.from_settings reads `or 95`; a
#                            negative is not falsy and clamps to 10 there too
#   gather.chase_confidence  <= 0 -> 70: chase_confidence_from's 0.7
#   move.hive_slot           outside 0..6 -> 0: journey.slot_from, "unknown"
#   perf.capture_fps         <= 0 -> 30: LiveView.fps_from's DEFAULT_FPS
#   perf.overlay_ms          <= 0 -> 216: overlay_seconds_from's default
UNSET_WHEN = {
    "gather.convert_at": lambda value: value == 0,
    "gather.chase_confidence": lambda value: value <= 0,
    "move.hive_slot": lambda value: not 0 <= value <= 6,
    "perf.capture_fps": lambda value: value <= 0,
    "perf.overlay_ms": lambda value: value <= 0,
}


def settle(key: str, value) -> tuple[Any, str]:
    """(the value the bot acts on, why that differs from `value`, or "").

    A number outside BOUNDS becomes the setting's default where its reader
    treats it as unset (UNSET_WHEN), and the nearest bound otherwise. The
    bot's `Settings.reload` and the GUI's panel both settle a value this way,
    so neither can show or save a number the reader would not use.
    """
    if key not in BOUNDS or isinstance(value, bool) \
            or not isinstance(value, (int, float)):
        return value, ""
    low, high, _step = BOUNDS[key]
    if low <= value <= high:
        return value, ""
    if key in UNSET_WHEN and UNSET_WHEN[key](value):
        used = defaults()[key]
        return used, (f"{key}: {value} is outside {low}..{high}, which the bot "
                      f"reads as unset; using the default {used}")
    used = type(value)(min(high, max(low, value)))
    return used, f"{key}: {value} is outside {low}..{high}; using {used}"


# SETTINGS THE BOT READS AT EVERY USE, so a change reaches it as soon as the
# GUI sends it (DESIGN 8du). Everything else wired is read once, when an
# attempt starts -- copied into the loop's locals or into an object built at
# startup -- and applies from the next attempt; the panel labels those. This
# list names only what was checked to be re-read, so a setting added later is
# labelled "next attempt" until someone shows otherwise, which can be too
# modest but is never a false promise:
#   quests.enabled                 run_farm learn_a_giver, per errand
#   quests.polar .. brown_bear     bearvisit.wanted_givers, per errand
#   economy.<places>               errands.wanted_place, per errand and recon
#   gather.chase_confidence        chase.chase_confidence_from, per chase
#   account.username               homing.username_from, per homing walk
#   combat.bug_runs, bug_worth_it, bug_run_seconds, bug_loot and the six
#   per-mob switches               act/bugrun enabled/worth_it/run_seconds/
#                                  loot_wanted/wanted, in run_farm
#                                  bugrun_errand, per errand
#   combat.retreat_health          act/bugrun.retreat_at, per fight and loot
#   goals.order, goals.have,       brain/goals.from_files, every plan (each
#   goals.owned, progression.hive  heartbeat on the bot)
#   goals.read_inventory           run_farm inventory_due, per errand
#   hive.read_bees                 run_farm bees_due, per errand
#   economy.shop_look              run_farm shop_look_due, per errand
#   economy.memory_match           run_farm memorymatch_due, per errand
#   economy.planters               act/planter.switched_off, per planter
#                                  errand, tend and Paper Planter buy
#   gather.stay_in_field           run_farm stay_in_field, per pattern pass
#   gather.follow_boost            run_farm boost_to_follow, per trip plan
#   nectar.keep_up                 run_farm nectar_to_follow, per trip plan
#   boost.keeper                   run_farm keeper_says, per booster
#                                  errand, dice roll and trip start
#   eggs.hatch_mythic              brain/goals.egg_may_hatch/slot_egg_held, per hatch
#   eggs.save_diamond              brain/goals.egg_may_hatch/slot_egg_held,
#                                  per hatch, slot check and quest feed
#   hive.new_bees                  run_farm hatch_by_plan_slot, per hatch
#   hive.grind_basic, grind_slot,  run_farm grind_step, per errand
#   grind_max_honey/_max_jellies
READ_AT_EVERY_USE = {
    "gather.natro_field_start",
    "quests.enabled", "quests.polar", "quests.honey", "quests.bucko",
    "quests.riley", "quests.black_bear", "quests.brown_bear", "quests.panda",
    "quests.mother", "quests.spirit",
    "economy.wealth_clock", "economy.blender", "economy.wind_shrine",
    "economy.shop_look",
    "economy.buy", "economy.slot_rule",
    "economy.early_harvest", "economy.planters",
    "economy.use_items",
    "economy.dispensers", "economy.boosters", "economy.beesmas",
    "economy.memory_match",
    "gather.chase_confidence", "account.username",
    "combat.bug_runs", "combat.bug_worth_it", "combat.bug_run_seconds",
    "combat.ant_challenge",
    "combat.bug_loot", "combat.loot_by_sight", "combat.retreat_health",
    "learn.token_school",
    "combat.bug_ladybug", "combat.bug_rhino_beetle", "combat.bug_spider",
    "combat.bug_mantis", "combat.bug_scorpion", "combat.bug_werewolf",
    "goals.order", "goals.have", "goals.owned", "goals.read_inventory",
    "progression.hive", "gather.stay_in_field", "quests.scroll", "move.glide_scale",
    "move.glide_side_scale", "move.home_glide_at_base", "gather.leave_at_empty_bag",
    "perf.feed_by_ocr", "move.home_by_whirligig", "hive.read_bees",
    "hive.follow_plan", "hive.new_bees",
    "hive.grind_basic", "hive.grind_slot", "hive.grind_max_honey", "hive.grind_max_jellies",
    "gather.micro_convert", "gather.follow_boost", "boost.keeper", "gather.rotate_camera",
    "nectar.keep_up",             # N4: run_farm nectar_to_follow, every trip plan
    # U19: run_farm keeper_kinds / boost_ai_mode / use_a_field_consumable, per use
    "boost.boosters", "boost.glitter", "boost.dice", "boost.item_buffs", "boost.ai",
    "eggs.save_diamond", "eggs.hatch_mythic", "planner.errand_profit",
    # SETTINGS AUDIT 2026-10-19: read live, though the label said "next attempt"
    "gather.sprinklers", "economy.sticker_tickets", "economy.clock_stand_in_share",
    # Settings > Spending: run_farm tent_buy_due and brain/buyer, per errand
    "economy.tickets.diamond_eggs", "economy.tickets.magic_beans", "economy.tickets.keep",
    "combat.bosses", "combat.stump_snail", "combat.vicious", "combat.commando",
    "combat.mondo_loot",          # act/mondo.wanted, at every kill line (M2b)
    "combat.fireflies",           # act/fireflies.wanted, every trip and credit (M8b)
    "challenges.stick_bug",       # act/stickbug.wanted, per errand chain (X5)
    "guard.enabled", "guard.games",
    # run_farm `plan`, every trip (brain/macro.active)
    "mode.macro", "macro.fields",
    "hotbar.rules",               # run_farm hotbar_rules, at every hook ($11)
}


# MACRO MODE (ROADMAP U16; the owner, 2026-10-16: "this app is gonna be a macro
# aswell as a auto progress ai"). `macro.fields` is a list of fields the user
# gathers in turn, each with its own settings, like other macros' field lists.
# ONLY THE PATTERNS THE BOT
# REALLY HAS: every Natro pattern here is CornerXSnake at the width Natro set
# for that one field (scripts/transpile_natro_patterns.py), so "field" means
# that one -- what AI mode walks today -- and the other three are
# BeeTuxMacro's field-agnostic shapes in data/world/paths.yaml. farm_mobs is
# left out: it is a cannon route, not a pattern.
MACRO_PATTERNS = {
    "field": "The field's own",
    "farm_snake": "Snake, wide (232 studs)",
    "farm_better_snake": "Snake, short (124 studs)",
    "farm_square": "Square, small (64 studs)",
}
# T17: a pattern saved in the Pattern Studio is named by its routine,
# `user_pattern_<slug>` (world/userpatterns); run_farm loads them at start and
# says so, and walks the field's own, when one named here is not saved.
MACRO_RETURNS = ("walk", "respawn")
MACRO_ENTRY = {"minutes": 15, "pattern": "field", "convert_at": 95,
               "return": "walk", "sprinklers": 1}
# (low, high) of each number in an entry. 240 min: a trip longer than four
# hours is a typo, not a plan. Sprinklers: the Diamond tier places 4.
MACRO_NUMBERS = {"minutes": (0, 240), "convert_at": (10, 100), "sprinklers": (0, 4)}


def macro_pattern_label(value) -> str:
    """A pattern choice as the user reads it: a shape's label, or a saved
    Pattern Studio pattern's name ("Yours: wide zigzag")."""
    if value in MACRO_PATTERNS:
        return MACRO_PATTERNS[value]
    if is_route_name(value):
        return "Yours: " + value.removeprefix(USER_PREFIX).replace("_", " ")
    return str(value)


def macro_field_names() -> list[str]:
    """The fields an entry may name: `gather.field`'s own choices."""
    choices = next(e[5] for _, es in SECTIONS for e in es if e[0] == "gather.field")
    return [c for c in choices if c != "auto"]


def macro_fields(raw) -> tuple[list[dict], list[str]]:
    """`macro.fields` as the bot may use it: (entries, problems).

    A BAD ENTRY IS DROPPED AND SAID, NEVER GUESSED AT: an unknown field,
    pattern, return method or key, or a number out of range, would otherwise
    send the bot somewhere nobody chose. A missing key takes MACRO_ENTRY's
    value (an entry needs only its field)."""
    if raw in (None, []):
        return [], []
    if not isinstance(raw, list):
        return [], [f"macro.fields: expected a list, got {type(raw).__name__}"]
    names = macro_field_names()
    out, problems = [], []
    for n, item in enumerate(raw, 1):
        why = ""
        if not isinstance(item, dict):
            why = "not a mapping"
        elif set(item) - set(MACRO_ENTRY) - {"field"}:
            why = f"unknown keys {sorted(set(item) - set(MACRO_ENTRY) - {'field'})}"
        elif item.get("field") not in names:
            why = f"unknown field {item.get('field')!r}"
        if not why:
            entry = {"field": item["field"], **MACRO_ENTRY,
                     **{k: v for k, v in item.items() if k != "field"}}
            if entry["pattern"] not in MACRO_PATTERNS and not is_route_name(entry["pattern"]):
                why = f"unknown pattern {entry['pattern']!r}"
            elif entry["return"] not in MACRO_RETURNS:
                why = f"unknown return method {entry['return']!r}"
            for key, (low, high) in MACRO_NUMBERS.items():
                value = entry[key]
                if not why and (isinstance(value, bool) or not isinstance(value, int)
                                or not low <= value <= high):
                    why = f"{key} {value!r} is not a whole number {low}..{high}"
        if why:
            problems.append(f"macro.fields entry {n}: {why}; left out")
        else:
            out.append(entry)
    return out, problems


# HOTBAR RULES (ROADMAP $11, the owner's friend; Natro's hotbar slots):
# `hotbar.rules` is a list of up to HOTBAR_MAX rules, each one item the bot
# presses on its hotbar on a trigger, checked by run_farm at the hooks it
# already has (brain/hotbarrules). ONLY ITEMS THE BOT CAN FIND ON THE HOTBAR:
# the ones vision/hotbar_items has a picture of (data/templates/hotbar/), so a
# rule never names an item the slot reading could not place.
HOTBAR_ITEMS = {"coconut": "Coconut", "field_dice": "Field Dice", "gumdrops": "Gumdrops",
                "jelly_beans": "Jelly Beans", "micro_converter": "Micro-Converter",
                "sprinkler": "Sprinkler Builder", "whirligig": "Whirligig"}
HOTBAR_TRIGGERS = {"every": "Every N minutes", "convert": "At each convert",
                   "gathering": "While gathering (every N s)",
                   "boost": "When a field boost starts", "never": "Never (paused)"}
HOTBAR_MAX = 7
# field "" = any field; keep: use only while the count is above it; hive_level
# 0 = any; over_ai: this rule beats the boost keeper on an item both want
HOTBAR_ENTRY = {"trigger": "every", "minutes": 10, "seconds": 30, "field": "",
                "keep": 0, "hive_level": 0, "over_ai": False}
HOTBAR_NUMBERS = {"minutes": (1, 240), "seconds": (5, 600), "keep": (0, 100_000),
                  "hive_level": (0, 30)}


def hotbar_rules(raw) -> tuple[list[dict], list[str]]:
    """`hotbar.rules` as the bot may use it: (rules, problems). A bad rule is
    dropped and said, never guessed at -- as `macro_fields`."""
    if raw in (None, []):
        return [], []
    if not isinstance(raw, list):
        return [], [f"hotbar.rules: expected a list, got {type(raw).__name__}"]
    fields = macro_field_names()
    out, problems = [], []
    for n, item in enumerate(raw, 1):
        why = ""
        if not isinstance(item, dict):
            why = "not a mapping"
        elif set(item) - set(HOTBAR_ENTRY) - {"item"}:
            why = f"unknown keys {sorted(set(item) - set(HOTBAR_ENTRY) - {'item'})}"
        elif item.get("item") not in HOTBAR_ITEMS:
            why = f"unknown hotbar item {item.get('item')!r}"
        elif len(out) >= HOTBAR_MAX:
            why = f"more than {HOTBAR_MAX} rules"
        if not why:
            rule = {"item": item["item"], **HOTBAR_ENTRY,
                    **{k: v for k, v in item.items() if k != "item"}}
            if rule["trigger"] not in HOTBAR_TRIGGERS:
                why = f"unknown trigger {rule['trigger']!r}"
            elif rule["field"] not in ("", *fields):
                why = f"unknown field {rule['field']!r}"
            elif not isinstance(rule["over_ai"], bool):
                why = f"over_ai {rule['over_ai']!r} is not true/false"
            for key, (low, high) in HOTBAR_NUMBERS.items():
                value = rule[key]
                if not why and (isinstance(value, bool) or not isinstance(value, int)
                                or not low <= value <= high):
                    why = f"{key} {value!r} is not a whole number {low}..{high}"
        if why:
            problems.append(f"hotbar.rules rule {n}: {why}; left out")
        else:
            out.append(rule)
    return out, problems


# A LIST SETTING, CHECKED THE SAME WAY BY THE BOT AND THE GUI
LISTS = {"macro.fields": macro_fields, "hotbar.rules": hotbar_rules}


# U17b COMPARE BY CONFIG: each trip in var/trips.jsonl carries the setup it ran
# under (`config`, `config_id`), so Stats > Compare can set one setup against
# another. ONLY WHAT CHANGES HOW IT FARMS, never a secret: the mode; macro
# mode's own entries (field, pattern, convert %, minutes, return, sprinklers),
# else AI mode's field choice and convert %; and the boosts the keeper keeps
# up ("ai" when the boost AI acts -- 'look' changes nothing). AI mode has no
# pattern choice (each field's own), so it carries none.
BOOST_KINDS = ("boost.boosters", "boost.glitter", "boost.dice", "boost.item_buffs")


def config_fingerprint(settings) -> dict:
    """The setup a trip runs under; `settings` is a Settings or a dict of values."""
    entries = macro_fields(settings.get("mode.macro") and settings.get("macro.fields"))[0]
    if entries:
        fp: dict = {"mode": "macro", "fields": entries}
    else:
        fp = {"mode": "ai",
              "field": "auto" if settings.get("gather.auto_field") else settings.get("gather.field"),
              "convert_at": settings.get("gather.convert_at")}
    boosts = [k.split(".")[1] for k in BOOST_KINDS if settings.get(k)] \
        if settings.get("boost.keeper") else []
    fp["boosts"] = boosts + (["ai"] if settings.get("boost.ai") == "act" else [])
    return fp


def config_id(fp: dict) -> str:
    """8 hex characters, the same for the same setup on any PC (the preset's
    name is left out: a renamed preset is the same setup)."""
    body = {k: v for k, v in fp.items() if k != "preset"}
    return hashlib.sha1(json.dumps(body, sort_keys=True, separators=(",", ":"))
                        .encode()).hexdigest()[:8]


def trip_config(settings, presets: Path | None = None) -> dict:
    """{"config": the fingerprint, "config_id": its hash} for a trip row; the
    fingerprint gets "preset" when a saved preset (the shell's presets folder
    beside settings.yaml) has exactly this setup -- else none, never a guess."""
    fp = config_fingerprint(settings)
    out = {"config": fp, "config_id": config_id(fp)}
    folder = presets or Path(getattr(settings, "path", CONFIG)).parent / "presets"
    try:
        files = sorted(folder.glob("*.yaml"))
    except OSError:
        files = []
    for path in files:
        try:
            loaded = yaml.safe_load(path.read_text())
            if isinstance(loaded, dict) and config_fingerprint({**defaults(), **loaded}) == fp:
                fp["preset"] = path.stem
                break
        except (OSError, yaml.YAMLError):
            continue
    return out


def takes_effect(key: str) -> str:
    """When a change to `key` reaches the running bot, in a few words."""
    if key in LOCKED:
        return "never — it is locked"
    if not wired(key):
        return "never — nothing reads it yet"
    # THE STREAM'S SETTINGS are read by the stream window as they change, and
    # the three that reach the bot by stream/gate at every vote (DESIGN 8dv,
    # 8ec); "from the next attempt" was not true of any of them.
    # THE TELEGRAM ONES are read by scripts/telegram_alerts.py at every alert
    # and by scripts/daily_card.py at every card, never by the bot.
    # THE WINDOW'S OWN (gui.*) are the GUI's, read as they change.
    # ...EXCEPT these two, read once (SETTINGS AUDIT 2026-10-19)
    if key == "stream.layout":
        return "when the stream window next opens"
    if key == "gui.layout":
        return "when the app next starts"
    if key in READ_AT_EVERY_USE or key.startswith(("stream.", "telegram.", "gui.")):
        return "at its next use"
    return "from the next attempt"

# (key, label, kind, default, help[, choices]).  kind: bool|int|float|choice|text
SECTIONS: list[tuple[str, list[tuple]]] = [
    ("Gathering", [
        ("gather.auto_field", "Pick the field automatically", "bool", True,
         "Chooses by expected honey per hour instead of a fixed rotation."),
        ("gather.field", "Preferred field", "choice", "auto",
         "Used when automatic field choice is off.",
         ["auto", "Sunflower", "Dandelion", "Mushroom", "Blue Flower", "Clover",
          "Spider", "Bamboo", "Strawberry", "Pineapple", "Stump", "Cactus",
          "Pumpkin", "Pine Tree", "Rose", "Mountain Top", "Coconut", "Pepper"]),
        # 95: the pro tester, round 1 (19 Oct 2026), "convert at 95% or higher
        # so i dont waste time gathering with a full bag" (playbook pro_convert_at_95)
        ("gather.convert_at", "Convert at backpack %", "int", 95,
         "Below 100 on purpose. Pollen gathered above capacity is discarded, so "
         "the last stretch of a fill returns nothing. 95 is a pro player's advice."),
        ("move.use_cannon", "Fly to far fields with the red cannon", "bool", True,
         "The owner's rule: \"use cannon to go places that are far\". The classic macro "
         "Macro's own cannon flights (its timings, its walk to the cannon) are "
         "the route out to every field whose walk is 400 studs or more -- "
         "Pine Tree, Rose, Pumpkin, Pineapple, Stump, Mountain Top, Cactus, "
         "Strawberry, Clover, Bamboo, Blue Flower, Spider. Off, every field is "
         "walked to. The walk home is always on foot."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # A common pro gather view: PageUp once for a blue hive, twice for a
        # red one -- a more top-down camera that shows the field around the
        # character rather than the horizon. Applied when a gather starts and
        # undone (PageDown) when it ends, so the walk home sees the view the
        # compass was measured at. 0 leaves the camera alone. Not yet measured
        # on this bot's own detectors, so it is best left at 0 for now.
        ("gather.camera_tilt", "Tilt camera down while farming (steps)", "int", 0,
         "Looks down at the flowers, then looks back up. 0 leaves the camera alone."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # The classic macro's gather view: it presses O five times after every
        # reset and gathers zoomed out, which shows more of the field and the
        # tokens around the character. Applied when a gather starts and undone
        # (I) when it ends, so the walk home sees the view the hive compass
        # was measured at. 0 leaves the camera alone; at most 8, the classic
        # macro's own most. Not yet measured on this bot's detectors, so it is
        # best left at 0 for now.
        ("gather.camera_zoom_out", "Zoom out while farming (steps)", "int", 0,
         "Zooms out to see more, then zooms back in. 0 leaves the camera alone."),
        ("gather.chase_tokens", "Chase tokens", "bool", False,
         "Detours for tokens the vision layer can see, within a radius."),
        ("gather.token_radius", "Token chase radius (studs)", "int", 45,
         "Past this, walking to a token costs more than the token is worth."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # The token detector's confidence, 0-100. It looks for a white glyph
        # on a flat cube face, and a Roblox bee IS a flat cube with white
        # markings, so bees pass the test too — the owner watched it "chasin
        # bees thinking they are tokens" on 2026-09-22. MEASURED on labelled
        # frames: at 50 it keeps 8 of 9 real tokens and 0 of 19 flowers; at
        # 70, 5 of 9 tokens and 0 flowers. Bees were not in that set, so 70 is
        # a caution rather than a calibration: fewer chases, fewer wasted
        # walks, some real tokens missed. Lower it if the field is quiet and
        # the buffs matter to you.
        ("gather.chase_confidence", "Ignore things that may not be tokens (%)",
         "int", 70,
         "A higher number means it chases fewer bees by mistake."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # Off (the default): it only looks. Between two passes of the gather
        # pattern, when every look of the last two seconds put the flower bed
        # around the character under 8%, the run log says which way it would
        # walk, and the first 60 such moments keep a picture in
        # var/fieldsense/steers (...-would-KEYS-FIELD.jpg) to look at before
        # turning this on. On: it walks that way, one 0.35 s step at a time,
        # until the flower bed is back over 10.5% (just past the edge), for at
        # most 3.5 s (the token chase's ceiling), and does not walk back.
        # MEASURED on saved gathering frames: it fires on 2.2% of the looks
        # inside a field (Strawberry 0.2%, Dandelion 1.5%, but Sunflower 26%:
        # yellow petals are not counted as flowers) and 5.2% on trips that
        # drifted out. The direction is weak: from under the edge a step
        # towards the flowers got back over it 68% of the time, a random
        # direction 68%, sideways 77%, away 55%. The flower measure was tested
        # against hive and landmark ground (AUC 0.935), so a drift into the
        # next field's flowers is not caught. Every walk is in the run log,
        # and the first 60 keep a picture from before and after.
        ("gather.stay_in_field", "Stay on the flowers (testing)",
         "bool", False,
         "Steps back onto the flowers if it walks off them."),
        ("gather.use_sprinklers", "Place sprinklers", "bool", True,
         "Puts down your sprinklers when it starts farming a field."),
        ("gather.sprinklers", "Sprinklers you own (Basic 1, Silver 2, Golden 3, Diamond 4)",
         "int", 1,
         "How many sprinklers one press places. Above 1 the bot STACKS them on "
         "the spot (the owner, 2026-10-10): after the first is placed it jumps "
         "and presses again on the way down, so the game does not refuse it as "
         "too close to the first -- every extra sprinkler waters the same "
         "flowers."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # The classic macro never gathers where its route ends: it first walks
        # to the field's sprinkler spot (Pine Tree: 31.5 studs forward, 22
        # left), turns the camera (Pine Tree: 2 taps left) and walks its
        # pattern with its own settings. On, the bot does the same
        # (data/world/natro_patterns.yaml, natro_start_<field> and
        # natro_pattern_<field>_as_natro). MEASURED on Pine Tree 2026-09-26:
        # with the bot's own start, 5 of 25 trips were credited to the Pumpkin
        # Patch and the Pine Tree trips gathered a median 5,372 pollen/s; with
        # the classic macro's, 4 of 4 were Pine Tree at 6,115-7,361 pollen/s.
        # Off gathers from wherever the route ends, as before.
        ("gather.natro_field_start", "Start each field from its best spot", "bool", True,
         "Walks to the field's sprinkler spot and faces the right way before farming."),
        # A CHOICE, NOT THE OLD BOOL: the owner's file still holds the dead
        # bool's saved `true`, which must not switch a new behaviour on. A bool
        # in a str key is "using default" (Settings._read), so it reads NEVER.
        ("gather.rotate_camera", "Sweep the camera for bubbles", "choice", "never",
         "Between gather passes, at the spot the pattern returns to, turns the "
         "camera one tap (45 degrees) left, two right and one left again -- "
         "back exactly where it was, so the pattern and the walk home are not "
         "rotated. Pro blue-hive setups do this, because the Tide "
         "Popper's waves and the Petal Wand's petals pop bubbles where the "
         "player faces. The Porcelain Dipper collects all round the player and "
         "pops none (wiki), so with it this should gain nothing: off by "
         "default. 'every other trip (A/B)' sweeps odd trips only, and each "
         "trip's line says 'camera sweep: N' so pollen/s can be compared. "
         "Read at every pass.",
         ["never", "every pass", "every other trip (A/B)"]),
        ("gather.leave_at_empty_bag", "Leave the hive as soon as the backpack is empty", "bool", True,
         "Ends a convert when the backpack reads empty instead of waiting the "
         "4-9 s for the honey counter to stop rising. The honey arrives anyway: "
         "MEASURED 2026-10-01, three converts left at the empty bag banked 1.37 "
         "honey a pollen, as the ones that waited do. Every 4th convert still "
         "waits, so a trip's honey stays measured on those; the others say "
         "'honey not measured'. Read at every convert -- no restart."),
    ]),
    # MACRO MODE (ROADMAP U16, MACRO_PATTERNS above). Read by run_farm's
    # `plan` at every trip through brain/macro.active.
    ("Macro", [
        ("mode.macro", "Macro mode: you choose the fields", "bool", False,
         "Off (the default): the AI picks every trip's field, as it always "
         "has. On, with at least one field in the list below: each trip goes "
         "to the next field in your list, in order, with that field's own "
         "gather time, pattern, backpack % and sprinklers -- the AI's field "
         "choice, field-boost and quest redirects, the owner's pinned field "
         "and chat's vote are not used. Errands you left switched on "
         "(dispensers, the Wealth Clock, bug runs, quests...) still run "
         "between trips, and the safety rails stand: a field a boss guards is "
         "skipped to the next one in the list, and the trip still comes home "
         "before the Wealth Clock is due. Read at every trip -- no restart."),
        ("macro.fields", "Macro mode's fields, in order", "list", [],
         "Each entry: field; minutes (how long to gather there, 0 = until the "
         "backpack reaches its %); pattern ('field' = the field's own classic-macro "
         "pattern, or farm_snake, farm_better_snake, farm_square); "
         "convert_at (backpack % that ends the gather and sends it home); "
         "return ('walk', or 'respawn': a respawn is a death and a death "
         "empties the backpack, so it respawns only when the bag reads empty "
         "-- after a Micro-Converter -- and walks otherwise, saying so); "
         "sprinklers (how many to place, 0 = none). An entry with an unknown "
         "field, pattern or key, or a number out of range, is left out and "
         "said. Edited on Macro > Gather."),
    ]),
    ("Economy", [
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # Every minute away from gathering costs the honey gathering would
        # have made (the benchmark's honey/h). On: in the hours the value
        # order runs, the bot tries every order of the next few errands that
        # are due or due within 2 minutes, does the first of the best-paying
        # order and plans again, and skips an errand worth less than the
        # gathering it costs (said in the feed: 'skipping the treat dispenser:
        # worth ~0.04M, costs ~2.8M of gathering'). The Wealth Clock is never
        # skipped. Off: the older best-value-a-second order. Read at every
        # errand -- no restart.
        ("planner.errand_profit", "Do the best errands first", "bool", True,
         "Does errands in the order that loses the least honey."),
        ("economy.planters", "Manage planters", "bool", False,
         "Places the planters you hold, walks back to harvest them when grown "
         "(or when their nectar would overfill), and buys Paper Planters at the "
         "Pro Shop when economy.buy is on. Off, the bot places, harvests and "
         "buys none; a planter already out is left where it is. Also off "
         "while 'Use spare Glitter, Glue and extracts' is off. Read at every "
         "errand -- no restart."),
        ("economy.early_harvest", "Harvest early to protect field health",
         "bool", False,
         "OFF, and it stays off until field degradation has actually been "
         "measured on your account. The harvest log is collecting that evidence; "
         "see the Account tab. Harvesting early for a benefit that may not exist "
         "loses real yield chasing an imagined one. Off, a planter whose "
         "prompt says it is still growing is left to grow (only a nectar "
         "about to overfill is harvested early)."),
        ("economy.min_field_health", "Do not replant below field health %",
         "int", 50, "Only applies once early harvesting is enabled."),
        ("economy.nectar_vials", "Condense nectar into Vials (not built)", "bool", False,
         "NOT BUILT: this switch does nothing. The Nectar Condenser (wiki) takes "
         "12 h of one nectar for a Vial of 4 h, and stands past the 35-bee "
         "Windy Bee Gate; this hive has 34. Nectar is kept up by the planters "
         "(Manage planters) and 'Keep the nectars up'."),
        ("nectar.keep_up", "Keep the nectars up", "bool", False,
         "On: while a nectar reads under its minimum (Comforting 70%, Motivating, "
         "Refreshing and Satisfying 80%, Invigorating 40%) and one of your planters "
         "grows it, a trip goes to that planter's field instead -- the bees sip "
         "it there -- when that field scores at least 85% of the planned one. "
         "Never over a quest field, the pin or the Wealth Clock. Also says which "
         "spare Nectar Vial it would use (look-only: it uses none). Off: nectar "
         "changes no trip. Read at every trip plan -- no restart."),
        ("economy.blender", "Run the Blender", "bool", False,
         "The bot makes, one item a visit, the material the next gear goal is "
         "short of (Oil for the Bubble Mask, 2026-10-05) from the Royal Jelly and "
         "berries it holds -- only for a goal the Blender can finish, collecting "
         "each craft when it is done. Speed Up (tickets) and a red End Crafting "
         "are never pressed (act/blender)."),
        ("economy.shop_look", "Look at the Ticket Tent's shop once", "bool", False,
         "Once, straight after a convert with the bag empty: the bot walks the "
         "Red Cannon flight's own first steps to the cannon's pad -- and never "
         "presses its E -- steps toward the Ticket Tent until the prompt reads "
         "exactly \"Open Shop\", presses E, pictures the window, and presses "
         "E again only when the prompt reads exactly \"Leave Shop\". Nothing in "
         "the shop is clicked or bought; the pictures (var/shoplook/) are "
         "what buying will be built against. If the window will not say "
         "\"Leave Shop\" it stops for a rejoin rather than resetting with a "
         "shop open (the wiki's Shop Trap). A look that did not get in is "
         "tried again after six hours. It also lets the bot CHECK instead of "
         "ask (G13): when a gear card is open and the item's shop has a known "
         "way in (the Mountain Top Shop, the Blue HQ), one look round that "
         "shop's window a day, read-only, to see \"Equipped\" or a price."),
        ("economy.buy", "Buy what the plan says, with honey and tickets", "bool", False,
         "The owner, 2026-10-02: \"the bot is allowed to do the game purchases so "
         "long as they dont cost robux\". On, the bot buys the purchases its plan "
         "names (brain/buyer; the first: a Festive Bee Egg for 500 tickets at the "
         "Ticket Tent, for the next hive cell) -- each only on an exact read of the "
         "shop's own window: the item's name, its price in honey or tickets, the "
         "green button offering that price, and nothing anywhere saying Robux, "
         "which is never bought. Every purchase is kept in var/purchases.json. "
         "Off, nothing is bought."),
        ("economy.slot_rule", "When a hive slot is bought", "choice", "current",
         "'current': the next slot is bought as soon as its honey and an egg "
         "for it are there. 'pro': the pro tester's rule (round 2, 20 Oct "
         "2026) -- buy slots until a slot costs more than the gear being "
         "saved for, then the gear first. Yours to pick: the payback ranking "
         "(brain/roi) puts late slots far behind gear. Read at every buy.",
         ["current", "pro"]),
        ("economy.use_items", "Use spare Glitter, Glue and extracts in the field", "bool", False,
         "At a gather's start, in the field, at most one a trip: spare Glitter "
         "when no boost runs on the field (+100% for 15 minutes), spare Glue, "
         "Blue Extract or Enzymes during a boost there (x1.25 on a boosted rate); "
         "spare Tropical Drinks and Jelly Beans the same way (Jelly Beans also at "
         "their cap of 100); a spare Red Extract on a quest trip owing red pollen "
         "in a red field; and a Field Dice at the pad when no boost runs, the next "
         "trip following its boost where it pays. "
         "Spare means past what the next goals keep (the Bubble Mask's 15 "
         "Glitter and 50 Blue Extract); each is used from the inventory by one "
         "click on its own row's icon and believed used only when the count on "
         "the icon moved. Off, nothing is used."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # BSS's own Auto-Jelly (Settings, near the bottom) refuses every Jelly
        # Beans use and one-at-a-time Royal Jelly roll while it is ON. The bot
        # opens Settings by its gear button, finds the Auto-Jelly row by its
        # words and reads its switch. 'look' does all of it but the click: it
        # keeps every picture in var/autojelly and says what it would click.
        # 'act' clicks the switch once when it reads ON and checks it reads
        # OFF. Never a key; the tab is closed by the gear. At most once a
        # process, when never looked at or when the box comes back. 'off':
        # Settings is never opened for it (U12).
        ("economy.auto_jelly_off", "Game's Auto-Jelly", "choice", "off",
         "Can switch off the game's own Auto-Jelly button. "
         "'look' only checks it; 'act' turns it off.",
         ["off", "look", "act"]),
        ("economy.wind_shrine", "Use the Wind Shrine", "bool", False,
         "Offerings are irreversible, so this is off until you turn it on."),
        ("economy.boosters", "Keep field boosters running", "bool", False,
         "The blue, red and mountain field boosters, each every 45 minutes. "
         "One is pressed as the last errand before a trip to a field it can "
         "boost, and only when the odds pay for the walk: a booster picks one "
         "of its fields at random, for 15 minutes (DESIGN 8dq)."),
        ("economy.dispensers", "Collect dispensers", "bool", False,
         "The free ones: honey and treat every hour, the free ant pass every "
         "2 hours, blueberry and strawberry every 4 -- all that are due, one "
         "after another, after a convert. Not walked to: the coconut "
         "dispenser (behind the 35-bee gate) and the glue dispenser (needs the "
         "Goo Hotshot badge and a gumdrop at the door); the startup log lists "
         "why. Never the Royal Jelly dispenser by the Clover Field, which "
         "costs 6 tickets a press."),
        ("economy.memory_match", "Play Memory Match", "bool", False,
         "The Memory Match machines, for honey only -- never tickets, never "
         "Robux: a panel asking for either is refused and logged. The 25,000 "
         "honey game whenever it is due and the honey covers it; the Mega "
         "(500,000) only from the honey above what the next goal keeps; the "
         "Extreme (25,000,000) not at all, because the games kept so far paid "
         "about 10M of priced prizes for its 25M. Off, none is walked to."),
        ("economy.wealth_clock", "Collect the Wealth Clock", "bool", False,
         "Tickets every hour of play (1, 2, 3, 4, then 5 a use). Its hour "
         "starts at the join, so a rejoin restarts it."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # While the pinned field's walk home fails, trips go to another field
        # so the session lasts the clock's hour. This is the least that field
        # must gather, as a % of the pinned field's rate over a whole trip;
        # below it the bot stays on the pinned field and the clock waits.
        ("economy.clock_stand_in_share", "Keep the Wealth Clock going (min %)",
         "int", 50,
         "If walking home keeps failing, it farms a field that makes at "
         "least this much of the normal pollen."),
        ("economy.beesmas", "Beesmas is on (use the event machines)", "bool", False,
         "Turn on when the Beesmas event starts. The Samovar, Stockings, Honey "
         "Wreath and the other event machines only exist during the event, so "
         "with this off the bot never walks to them; out of season each visit "
         "is a long walk to nothing. With it on, each machine is walked to and "
         "READ, pressing nothing: what they give lands on the ground in front "
         "of them, and until the bot walks that loot up after a press, "
         "pressing would only start their cooldown."),
    ]),
    # WHAT TICKETS MAY BE SPENT ON (the owner, 2026-10-21: "make options for
    # what it can spend [tickets] on and leave it all off as default"). One
    # switch a spend, all off; brain/buyer.ticket_purchases reads them.
    ("Spending", [
        ("economy.tickets.diamond_eggs", "Buy Diamond Eggs with tickets (for the Diamond Mask)",
         "bool", False,
         "A Diamond Egg costs 400 tickets at the Ticket Tent. On, the bot buys "
         "one there (the Ticket Tent purchase it already makes for eggs) "
         "whenever your gear goals still need Diamond Eggs -- the Diamond Mask "
         "takes 5 -- and you have 400 tickets above the ones kept back below. "
         "It stops once enough are held. Eggs bought this way are NEVER "
         "hatched, fed or put in a slot while this is on, whatever else is set. "
         "Needs 'Buy what the plan says' (Economy) on too. Off, it buys none."),
        ("economy.tickets.magic_beans", "Buy Magic Beans with tickets (for planters)",
         "bool", False,
         "A Magic Bean costs 20 tickets at the Magic Bean Shop by the Stump "
         "Field. On, when the next planter on the bot's list is short of beans "
         "it works out how many to buy. LOOK-ONLY for now: the bot has never "
         "found the shop's counter, so it only says what it would buy (in the "
         "buying lines of the log) and spends nothing."),
        ("economy.sticker_tickets", "Keep the Sticker Stack going with tickets", "bool", False,
         "When every sticker type you own is already stacked, the Sticker "
         "Stack's 'Boost without a Sticker (25 Tickets)' keeps its boost going. "
         "Used only when the boost is missing or has under 10 minutes left, "
         "and Yes only to a question that names tickets. Tickets, never Robux."),
        ("economy.tickets.keep", "Tickets always kept back", "int", 100,
         "The switches above never spend your tickets below this many. Gumdrops "
         "for goo quests and the Blender (bought with 'Buy what the plan says') "
         "keep their own 100."),
    ]),
    ("Combat", [
        ("combat.mobs", "Clear mobs", "bool", False,
         "Not built yet: it does not fight mobs while farming."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # Boss HP semantics are UNVERIFIED: the Coconut Crab is believed to
        # reset when you leave and the Stump Snail to save damage. Until that
        # is measured, every boss is treated as resetting, which is the safe
        # reading.
        ("combat.bosses", "Fight bosses", "bool", False,
         "Fights the Coconut Crab, King Beetle, Tunnel Bear and Stump Snail."),
        ("combat.stump_snail", "Stump Snail: chip at it when it pays", "bool", False,
         "Its 30,000,000 HP is kept between visits, and beaten it gives a "
         "Shell Amulet, 30M honey and 1-10 Star Jelly (act/stumpsnail). With "
         "this on (and Fight bosses), it walks to the Stump Field after a "
         "convert, reads the snail's HP off its bar and stands with the tool "
         "swinging: a 15-minute session every 30 minutes while the rate it "
         "measures there beats gathering (brain/value), otherwise a 2-minute "
         "re-measure once a week. Off by default: on 2026-10-06 this hive took "
         "83 HP/s off it (about 99 hours of fighting for the rest), while "
         "gathering pays ~3,700 a second by the planner's own reading -- and "
         "Other macros and the blue hive guide leave it off."),
        ("combat.vicious", "Engage the Vicious Bee", "bool", False,
         "Hunt it at night, after a convert (act/vicious): Clover and Spider "
         "only, a death ends the hunt and each loss doubles the wait. The bag "
         "is empty, so a death costs the walk. Off by default."),
        ("combat.commando", "Fight the Commando Chick", "bool", False,
         "Every 30 minutes, after a convert with the bag empty (act/commando): "
         "the Wealth Clock's walk, the classic macro's obby, then the edge of the hideout's "
         "last stair, where the wiki says it cannot touch the character, while "
         "the bees fight it -- 15 minutes at most, and its HP is saved for the "
         "next fight. Its captures pay Glue at the 5th, a Gold Egg at the "
         "10th, a Star Jelly at the 15th, 3 Blue Extract at the 20th, 100 "
         "tickets at the 25th and a Mythic Egg at the 50th (eggs are saved, "
         "never hatched). A loss doubles the wait, a week at most. Off "
         "as shipped (U15b); the owner turned it on (2026-10-12)."),
        ("combat.mondo_loot", "Mondo Chick: collect its loot by sight", "bool", False,
         "After the reward feed says the Mondo Chick was defeated while the "
         "character is on Mountain Top, chase the dropped tokens with the coin "
         "detector -- up to 12, for at most 45 seconds (the classic macro's Mondo loot "
         "time), each walk coming back where it began, as after any mob the "
         "bees kill in a field (act/mondo). LOOK-ONLY for now: with this on it "
         "only logs 'mondo loot would: ...', because no Mondo kill has been "
         "read yet -- the bot keeps off Mountain Top while the chick is there. "
         "Off by default. Read at every kill -- no restart."),
        ("combat.fireflies", "Fireflies: night trips for Moon Charms", "bool", False,
         "At night fireflies land in Rose, Cactus, Pineapple, Spider, "
         "Strawberry and Bamboo and leave 1, 5 or 10 Moon Charms ('+1 Moon "
         "Charm (from Fireflies)'). Every such credit is written to "
         "var/fireflies.jsonl whatever this says. With this on, a trip planned "
         "at night goes to the best firefly field the planner ranked -- if a "
         "goal is short of Moon Charms, the ledger has 3+ credits and the "
         "field scores at least 60% of the planner's pick -- and each credit "
         "keeps the 10 seconds of frames before it (var/incidents/*-firefly, "
         "12 at most) to build a firefly detector from. It does not chase "
         "fireflies by sight yet (act/fireflies). Off by default. Read at "
         "every trip -- no restart."),
        ("challenges.stick_bug", "Stick Bug Challenge (look-only)", "bool", False,
         "The Stick Bug on the tallest mushroom in the Mushroom Field starts a "
         "10-minute, server-wide boss fight that begins in the Sunflower Field "
         "and pays a Stick Bug Amulet by score (wiki; he needs a Translator "
         "given to him once, and starts free every 36 hours or for 50 "
         "tickets). The bot would take the free start only, never the "
         "tickets, and only from :15 to :50 UTC so no Mondo Chick is up. "
         "LOOK-ONLY for now: with this on it only logs 'stick bug would: "
         "...' after a convert (act/stickbug), because his panel and the "
         "challenge screens have not been measured yet. Off by default. Read "
         "at every errand chain -- no restart."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # Read off the character's own health bar, which the game draws at the
        # top right only while it is hurt (vision/hurt.own_health, checked
        # against every saved death). A bug run leaves its fight, or its loot
        # walk, once the reading has stayed at or under this line for half a
        # second (the reader's false dips last 0.3 s at most): it respawns at
        # once, skipping the rest of the loot, because a death would lose the
        # same bag.
        ("combat.retreat_health", "Run away below health %", "int", 35,
         "Leaves a fight before your character is knocked out."),
        ("combat.bug_runs", "Bug runs: go and kill field mobs", "bool", False,
         "The classic macro's bug run. Right after a convert, with the bag empty, go "
         "to a field whose mob has respawned (by cannon when the cannon is "
         "flying), look around for its health bar, stand while the bees kill "
         "it (never longer than the classic macro's own longest wait there), walk over "
         "the drops, and respawn home like every errand. One field per "
         "convert, after the quest hand-ins and the Wealth Clock. A mob a "
         "quest wants goes first, before the recons; any other mob goes "
         "last, most drops per second first, and only when its drops beat "
         "the gathering it replaces (the check below). A kill is counted "
         "only when the reward feed says \"Defeated ...!\" (a bar leaving "
         "the view books a visit, which starts the respawn timer too), the "
         "timers are kept in var/bugrun.json and shown on the timers tab, "
         "and each run's line in the log says what it cost in honey. Off "
         "stops every bug run, quest ones included."),
        ("combat.ant_challenge", "Ant Challenge: play it for quests that want ants",
         "bool", False,
         "When a quest wants ants defeated (\"Defeat 10 Ants\", \"Defeat 10 "
         "Flying Ants\"), after the free Ant Pass Dispenser the bot walks to "
         "the Ant Challenge and presses E only on the exact panel \"Spend 1 "
         "Ant Pass to Play the Ant Challenge\" -- one Ant Pass, never tickets "
         "or honey. It keeps moving in the arena while the bees fight, for at "
         "most four minutes, then respawns to end it. The challenge always "
         "ends with an Ant Amulet; when you already have one the game shows "
         "Keep Old / Replace, and the bot clicks only a \"Keep Old\" it has "
         "read on screen beside \"Replace\" -- never Replace. Every frame of "
         "the run is kept in var/antchallenge. Off: it only looks at the "
         "entrance."),
        ("combat.bug_worth_it", "Bug runs: only when the drops beat the gathering",
         "bool", True,
         "For a mob no quest wants. The run goes only when the wiki's drops "
         "for the field's due mobs (honey, plus tickets at the Ticket Shop's "
         "cheapest, 100,000 honey) come to more than the honey the last "
         "measured rate would gather in the run's planned time. Battle "
         "points, bond and treats are not counted. At this account's median "
         "4.15 M honey an hour no field passes -- the Pumpkin Patch's "
         "Werewolf comes closest, about 55,000 against 146,000 -- so with "
         "this on the runs are for quests, and the timers still start when "
         "the bees kill a mob while gathering. Off hunts every mob switched "
         "on below whatever it costs. Quest runs are never priced."),
        ("combat.bug_run_seconds", "Bug runs: longest one run may take (s)",
         "int", 150,
         "The planned length of one run from leaving the pad, the respawn "
         "home included. A field whose planned run is longer is skipped and "
         "the log says so. The fight and the loot walk stop when the time "
         "is up, so a run whose way out took longer than planned stands for "
         "less, or not at all; the way out and the respawn home are not cut "
         "short, so a slow run can take longer than this. 150 s fits the "
         "longest field, the Pumpkin Patch (127 s planned, walking there), "
         "so lower it to keep the runs near the hive. At one run per "
         "convert and a median trip of 939 s (the trip ledger since attempt "
         "340), 150 s is at most about a seventh of the farming time. 0 "
         "means no limit but the classic macro's own waits."),
        ("learn.token_school", "Collect frames for the token school", "bool", True,
         "While on, every token pickup the reward feed credits keeps the "
         "10 seconds of frames before it in var/incidents/*-token-school, up "
         "to 40 windows on disk -- the frames the coin detector is retrained "
         "from, in the field the bot gathers now (the first 60 were all "
         "Pineapple Patch). Past 40 it stops by itself. Read at every pickup "
         "-- no restart."),
        ("combat.loot_by_sight", "Chase a kill's loot by sight", "bool", False,
         "After a bug run's kill, the bot looks for the dropped tokens with "
         "its coin detector and walks to each one it is sure of -- up to six, "
         "for at most 12 seconds -- before the classic macro's fixed loot walk sweeps "
         "what was out of view. A mob drops where it dies, which the fixed "
         "walk only guesses at. Every drop the feed credits to a mob ('+1 Oil "
         "(from Werewolf)') is written to var/mob_drops.jsonl. Read at every "
         "run -- no restart."),
        ("combat.bug_loot", "Walk over the drops after a kill", "bool", False,
         "The classic macro's loot walk, tile for tile: a defeated mob drops a ring of "
         "tokens (honey, treats, tickets) that is lost unless walked over "
         "(wiki, Mob). 9 to 26 seconds of walking depending on the field. "
         "The classic macro ships it off; it is on here because the drops are most of "
         "what a run brings back (the Werewolf's 50% ticket, the Spider's "
         "25%)."),
        ("combat.bug_ladybug", "Bug runs: Ladybugs", "bool", False,
         "Hunt them even when no quest asks, if the check above allows (a "
         "quest that wants them sends a run whatever this says, the classic macro's "
         "rule). Mushroom, Clover and Strawberry. Back 5 minutes after a "
         "kill, 1 battle point and about 75 honey each (wiki); the feed "
         "measured about 200 honey a kill."),
        ("combat.bug_rhino_beetle", "Bug runs: Rhino Beetles", "bool", False,
         "Hunt them even when no quest asks, if the check above allows "
         "(a quest sends a run either way). "
         "Blue Flower, Clover, Bamboo and Pineapple. Back 5 minutes after a "
         "kill, 1 battle point and about 75 honey each (wiki)."),
        ("combat.bug_spider", "Bug runs: the Spider", "bool", False,
         "Hunt it even when no quest asks, if the check above allows "
         "(a quest sends a run either way). "
         "Spider Field. Back 30 minutes after a kill, 10 battle points, "
         "1,000 honey and a 25% ticket chance (wiki)."),
        ("combat.bug_mantis", "Bug runs: Mantises", "bool", False,
         "Hunt them even when no quest asks, if the check above allows "
         "(a quest sends a run either way). "
         "Pineapple and Pine Tree. Back 20 minutes after a kill, 5 battle "
         "points and 250 honey each (wiki). The mob that kept killing the "
         "character with a full bag: here it is fought with an empty one."),
        ("combat.bug_scorpion", "Bug runs: Scorpions", "bool", False,
         "Hunt them even when no quest asks, if the check above allows "
         "(a quest sends a run either way). "
         "Rose Field, two of them. Back 20 minutes after a kill, 5 battle "
         "points and about 1,000 honey each (wiki). They hit for 25."),
        ("combat.bug_werewolf", "Bug runs: the Werewolf", "bool", False,
         "Hunt it even when no quest asks, if the check above allows "
         "(a quest sends a run either way). "
         "Fought in the Pumpkin Patch, walking the classic macro's dodge square; the same "
         "Werewolf defends Cactus and Pine Tree, so a kill there counts. Back "
         "an hour after a kill, 25 battle points and 5,000 honey (wiki); the "
         "feed measured about 7,900 honey and 1.5 tickets a kill. It hits "
         "for 35, the hardest of the six, so the retreat line matters most "
         "here."),
    ]),
    ("Quests", [
        ("quests.enabled", "Do quests", "bool", False,
         "Talks to the bears you tick and does their quests."),
        ("badges.look", "Look at the badge menu once a session", "bool", False,
         "Opens the badge menu with its HUD button (the rosette), keeps a "
         "picture of its first page in var/badges and closes it the same way "
         "-- pressing nothing else and claiming nothing yet (act/badges). On "
         "since 2026-10-06, the owner: \"make it claim achievement badges too "
         "so it can work towards super saturator\" -- the claim is built from "
         "these pictures."),
        ("quests.scroll", "Read the whole quest list", "bool", False,
         "The quest panel shows only the top of a long list -- a third to half "
         "of yours. With this on, after reading the first page the bot turns "
         "the mouse wheel over the list one notch at a time, checking every "
         "move, pictures it to the end, scrolls back to the top and closes the "
         "menu, then reads the whole list (act/questscroll). A notch the camera "
         "takes instead of the list is taken back and nothing more is turned."),
        ("quests.first", "Quest fields first", "bool", False,
         "Go to the field a quest names (\"Collect 420,000 Pollen from the "
         "Mountain Top Field\") or where a mob a quest wants lives, whatever "
         "it pays next to the best field -- the danger rules still stand. "
         "Off, a quest only tilts the choice. Needs 'Pick the field "
         "automatically' on."),
        ("quests.polar", "Polar Bear quests", "bool", False, "Does this bear's quests for you."),
        ("quests.honey", "Honey Bee quests", "bool", False, "Does this bear's quests for you."),
        ("quests.bucko", "Bucko Bee quests", "bool", False, "Does this bear's quests for you."),
        ("quests.riley", "Riley Bee quests", "bool", False, "Does this bear's quests for you."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # Gates the Translator. Mandatory for progression and automated by
        # nobody else.
        ("quests.science", "Science Bear", "bool", False,
         "Not built yet: there is no walk to the Science Bear."),
        ("quests.spirit", "Spirit Bear", "bool", False,
         "Gates Windy Bee; the other chain nobody automates. Her route is the "
         "Coconut Field walk cut at its long forward run, where her quest "
         "marker shows on a ledge ahead; the search walks toward the marker, "
         "and E is pressed only when the panel names the Spirit Bear."),
        ("quests.black_bear", "Black Bear quests", "bool", False,
         "Does this bear's quests for you."),
        ("quests.brown_bear", "Brown Bear quests", "bool", False,
         "Does this bear's quests for you."),
        ("quests.panda", "Panda Bear", "bool", False,
         "His quests are the mob ones (The REAL Final Showdown pays a Gold "
         "Egg). The route walks to the foot of his block by the Gumdrop Shop "
         "and searches for his prompt, pressing E only when the panel names "
         "the Panda Bear. Getting up onto the block is not built yet, so "
         "until his prompt has been read each try only takes pictures."),
        ("quests.mother", "Mother Bear", "bool", False,
         "Her quests are the feeding ones (Search For Sunflower Seeds). Her "
         "route is the Sunflower Field walk, then measured steps to her pad by "
         "the Treat Shop; E is pressed only when the panel names Mother Bear."),
    ]),
    ("Autonomy", [
        ("autonomy.mode", "Mode", "choice", "ask_strategy",
         "Autopilot never interrupts. Ask on strategy raises builds and big "
         "spends. Ask on notable raises anything irreversible.",
         ["autopilot", "ask_strategy", "ask_notable"]),
        ("autonomy.question_timeout_m",
         "Auto-decide unanswered questions after (min)", "int", 60,
         "0 waits indefinitely. When it lapses the bot uses its own "
         "recommendation, which is always shown on the card."),
        ("autonomy.max_spend", "Ask before big spends",
         "int", 5_000_000, "Not working yet: the bot never asks before buying."),
        ("autonomy.min_confidence", "Minimum confidence for irreversible acts",
         "float", 0.9,
         "An irreversible action refuses to run on a belief staler than this. "
         "It is what stops the bot spending royal jelly on a 40-minute-old "
         "inventory reading."),
    ]),
    # THE OWNER'S GEAR GOALS (DESIGN 8dp), read by brain/goals every time it
    # plans -- each heartbeat on the bot, each honey reading in the window --
    # so an edit here counts from the next one.
    ("Goals", [
        ("goals.order", "Gear to work towards, in order", "text", "",
         "Empty means the order you asked for: Porcelain Dipper, Porcelain "
         "Port-O-Hive, Honey Mask, then the rest of the Ace Shop -- Honeycomb "
         "Belt, Cobalt Guard, Crimson Guard (data/knowledge/goals.yaml). Type "
         "names separated by commas to change it; one left out is dropped. "
         "The bot NEVER buys any of it. When the next one is affordable in "
         "this order it puts a card in the Decision Inbox, and it visits the "
         "quest givers whose quests pay the missing materials first."),
        ("goals.have", "Materials you hold", "text", "",
         "What you type here wins over what the bot read. Otherwise the "
         "counts come from its own read of your inventory (below), and then "
         "your screenshot of 2026-09-20. Type yours like: treats=1200, oil=4, "
         "gold eggs=1, tickets=500. Anything nobody has seen is unknown, never "
         "zero, and a goal with an unknown material is never called ready."),
        ("goals.owned", "Gear you already own", "text", "",
         "Names separated by commas: goals or any other gear (\"Porcelain "
         "Dipper, Riley Guard\"). This is your word and always wins. The bot "
         "also watches your honey: when it falls by one item's price it marks "
         "that item owned as INFERRED and asks you in the Decision Inbox; "
         "answering yes, or \"I bought it\" on a ready-to-buy card, adds it "
         "here."),
        ("hive.read_bees", "Read the hive from the bee menu", "bool", False,
         "On the hive pad with the bag empty, at most every three hours, the "
         "bot clicks the bee menu's button (the smiley), pictures every page of "
         "its list, reads each bee type's count and the menu's own \"You Have "
         "N Bees\", and clicks it shut, the way it reads the inventory. Nothing "
         "inside the list is clicked or dragged. The read is believed when the "
         "counts add up to the header; then the hive is judged against the "
         "blue guide (its stage, the comp, the bees it says never to run, what "
         "Royal Jelly may go on) and the bee gates use the count. The pages "
         "are kept in var/beemenu/."),
        ("hive.follow_plan", "Royal Jelly follows the Hive Planner", "bool", False,
         "On: Royal Jelly follows the Hive Planner. Off: the planner is only a "
         "picture; the bot uses its own guide."),
        ("hive.new_bees", "Where new bees go", "choice", "any empty slot",
         "Where the bot hatches an egg when the hive has an empty slot. 'any "
         "empty slot': as it always has, into the one empty cell it sees. "
         "'follow the Hive Planner': into the empty slot your Hive Planner "
         "wants filled next (the lowest planned slot first), known from the "
         "slot-by-slot hive read; with no plan, no planned empty slot, or a "
         "read older than the last hatch, it uses any empty slot and says "
         "why. For now it only says where it WOULD hatch and still hatches "
         "as before, until the aimed drag is checked live. Read at every "
         "hatch -- no restart.",
         ["any empty slot", "follow the Hive Planner"]),
        ("hive.grind_basic", "Grind a gifted Basic Bee", "bool", False,
         "On: in the one slot you choose (below, or click a hex in the Hive "
         "Planner), the bot hatches a Basic Egg, rolls Royal Jelly on the Basic "
         "Bee it gives, puts a Basic Egg on what the jelly made, and goes round "
         "until that slot holds a GIFTED Basic Bee -- then stops and alerts you. "
         "Basic Eggs and Royal Jelly only (Star, Silver, Gold, Diamond and Mythic "
         "Eggs and Star Jelly are saved), honey only, never Robux. ANY gifted bee "
         "or Mythic in the slot stops it, so a lucky roll is kept. It acts only "
         "where that is tested: the egg bought, the hatch when the slot is the one "
         "empty cell, the jelly when the slot's Basic Bee is the hive's only one. "
         "A Basic Egg on a full slot is not measured yet, so that step only says "
         "what it would do. Read at every errand -- no restart."),
        ("hive.grind_slot", "Slot to grind in (0 = none)", "int", 0,
         "The hive slot (1-50, slot 1 bottom left from the pad, rows of 5) the "
         "gifted Basic grinder works in. 0: none."),
        ("hive.grind_max_honey", "Grinder: most honey a session", "int", 50_000_000,
         "The most honey the gifted Basic grinder spends on Basic Eggs in one run "
         "of the bot (an egg is 10,000,000 honey once you have bought a few). It "
         "stops for the session when the next egg would go over."),
        ("hive.grind_max_jellies", "Grinder: most Royal Jelly a session", "int", 10,
         "The most Royal Jelly the gifted Basic grinder uses in one run of the "
         "bot. The Blender's share is never touched."),
        ("eggs.hatch_mythic", "Hatch Mythic Eggs into new hive slots", "bool", False,
         "On, a Mythic Egg goes into the next new hive slot instead of being "
         "saved. Nothing in the game uses Mythic Eggs, and every mythic bee is "
         "better than a Basic Bee (2 in 6 are blue: Buoyant, Tadpole). Off, they "
         "are kept, as before. To put one over a weak bee instead, drag it there "
         "yourself."),
        ("eggs.save_diamond", "Save Diamond Eggs for recipes", "bool", True,
         "On, the bot never hatches a Diamond Egg, never drags one onto a bee "
         "and never puts one in a new hive slot -- they are kept for crafting "
         "(the Diamond Mask takes 5). The bot never crafts or buys gear itself, "
         "so the Mask is yours to buy with them. Off, the older rules stand: "
         "the main still hatches only Basic Eggs and event bees' eggs, so its "
         "Diamond Eggs stay saved anyway; the alt (its own settings file has "
         "this off) hatches any egg. While 'Buy Diamond Eggs with tickets' "
         "(Spending) is on they are saved whatever this says. Read at every "
         "hatch -- no restart."),
        ("goals.read_inventory", "Read the inventory once a session", "bool",
         False,
         "On the hive pad with the bag empty, at most once a session and not "
         "within an hour of the last try, whether that try read it or not, "
         "the bot clicks the inventory button, pictures every page, reads the "
         "goal materials' counts and clicks it shut again, checking the world "
         "is back before it moves. No keys are pressed. The pictures are kept "
         "in var/inventory/ so the reading can be checked. If the list's item "
         "markers are missing three tries in a row, it stops trying until its "
         "inventory code is updated, and says so in the log."),
    ]),
    # THE RESEARCHED PROGRESSION (brain/progression), read every time the
    # goals are planned: the stage the bot reads the account to be at, and
    # the next goals after his own list.
    ("Progression", [
        ("progression.hive", "Hive colour for progression", "choice", "blue",
         "Which researched plan the bot follows after your own goal list: "
         "data/knowledge/progression/<colour>.yaml, fresh account to endgame, "
         "a source on every line. It reads where your account is (bees, honey, "
         "the gear and badges it has seen) and puts that plan's next goals "
         "after yours, marked 'from the Blue progression'. It never buys one "
         "of them itself. Every guide says to play blue until the Supreme Star "
         "Amulet; red and white are endgame switches.",
         ["blue", "red", "white"]),
    ]),
    ("Movement", [
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # Bee Swarm's base walkspeed, and the one number open-loop routes
        # cannot derive. The recorded routes store DISTANCES, so a hold lasts
        # studs / walkspeed — set this wrong and every route overshoots or
        # stops short by the same ratio. 28 is the game's base and matches the
        # value in BeeTuxMacro's own config.sh.
        ("move.walkspeed", "Your walking speed", "float", 28.0,
         "Set this to your real speed so walks land in the right place."),
        ("move.open_loop", "Move by timing rather than by sight", "bool", True,
         "Holds a key for as long as the distance takes, which is how every "
         "working Bee Swarm macro moves and needs no calibration. Turn this "
         "off once the ground plane is calibrated and movement is measured "
         "instead — that self-corrects for lag, haste, slopes and knockback."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # How long the Pine Tree flight glides, as a multiple of the classic
        # macro's own 4.5 seconds. MEASURED 2026-10-01: at the classic macro's
        # 1.0 every flight came down on the grass in a corner beside the
        # field; 0.8 with the sideways finish at 2.0 landed on Pine Tree's
        # flowers. Shorter than 0.8 lands in the Pumpkin Patch, and so does
        # 1.2. Read at every flight -- no restart.
        ("move.glide_scale", "Pine Tree glide length (1 = normal)", "float", 0.8,
         "Change only if the cannon flight lands short or long."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # How long the Pine Tree flight steers sideways after its glide,
        # before it drops, as a multiple of the classic macro's half second.
        # MEASURED 2026-10-01: the classic macro's 1.0 leaves the flight on
        # the grass beside the flowers; 2.0 (a whole second) puts it on them.
        # Read at every flight -- no restart.
        ("move.glide_side_scale", "Pine Tree glide sideways (1 = normal)", "float", 2.0,
         "Change only if the flight ends too far left or right."),
        ("gather.micro_convert", "Convert a full bag in the field by Micro-Converter", "bool", False,
         "When the bag fills mid-gather and the hotbar holds a Micro-Converter "
         "(\"Instantly converts all Pollen in your bag to Honey\"), the bot "
         "converts there and gathers on instead of walking home and back -- "
         "but only when it pays: the first is used at the item's cap (15), "
         "where the next would be wasted, and measured; after that one is used "
         "only when the round trip it saves is worth more honey than "
         "converting away from the hive is measured to lose (var/micro_"
         "converter.json). Read at every full bag -- no restart."),
        ("gather.follow_boost", "Gather where a field booster's boost landed", "bool", False,
         "A booster boosts one of its fields at random, and the game says which "
         "('Activated \"Blue Flower Field Boost\" x 3'). For the boost's fifteen "
         "minutes the bot gathers there instead of its usual field when that "
         "field is a blue one worth more boosted than the usual one unboosted "
         "(Blue Flower x3 about 1.5x Pine Tree, Bamboo x1 about 1.3x, by the "
         "fields' blue flowers) -- and while a boost runs where it gathers, it "
         "runs no errands. Every press and what the game boosted goes to "
         "var/boosts.jsonl. Read at every trip -- no restart."),
        ("boost.keeper", "Keep boosts going (boost keeper)", "bool", False,
         "On: the bot keeps boosts going -- field boosters on cooldown, Glitter/"
         "Field Dice before a boost runs out. It only uses items you have. "
         "When the boost on the field it gathers would end during the next trip, "
         "it presses a field booster that can boost that field (even when the walk "
         "alone would not pay), else uses a spare Glitter there at the trip's "
         "start, else rolls a spare Field Dice at the pad. Never Robux, never "
         "during a convert or a walk home. Read at every use -- no restart."),
        # U19, THE BOOSTING TAB: which boosts the keeper keeps up, and the boost AI
        ("boost.boosters", "Boost keeper: press field boosters", "bool", False,
         "With the boost keeper on: press a field booster that can boost the "
         "field it gathers when the boost there would end during the next trip, "
         "even when the walk alone would not pay. Off, boosters are pressed only "
         "when the walk pays (Keep field boosters running). Read at every use."),
        ("boost.glitter", "Boost keeper: Glitter", "bool", False,
         "With the boost keeper on: use a spare Glitter at a trip's start when "
         "the boost on that field would end during the trip. Read at every use."),
        ("boost.dice", "Boost keeper: Field Dice", "bool", False,
         "With the boost keeper on: roll a spare Field Dice at the pad when the "
         "boost would end and no Glitter is used. Read at every use."),
        ("boost.item_buffs", "Item buffs in a boost", "bool", False,
         "Glue, Blue and Red Extract, Enzymes, Tropical Drink and Jelly Beans, "
         "used at a trip's start (spare ones only, under 'Use spare Glitter, "
         "Glue and extracts'). Off, those are kept; Glitter, Field Dice, Magic "
         "Beans and planters are not affected. Read at every use."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # Decides from MEASURED trips (var/trips.jsonl against
        # var/boosts.jsonl) whether a boost pays: a field's boosted pollen/s
        # against its own unboosted trips the same day. 'off': the keeper's
        # rules alone. 'look': it logs what it would do ('boost AI would:
        # ...') and changes nothing. 'act': the keeper spends Glitter, Field
        # Dice and a not-worth-the-walk booster press only where the boost is
        # measured to pay; an unmeasured field gets none. Where to farm and
        # when to walk to a booster stay look-only in 'act' until seen working
        # live. Never Robux. Read at every use.
        ("boost.ai", "Boost helper", "choice", "off",
         "Tells you, or decides, which boosts are worth it. 'look' only "
         "tells you; 'act' skips boosts that do not pay (testing).",
         ["off", "look", "act"]),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # Up to 7 rules, each pressing one hotbar item on a trigger, like the
        # classic macro's hotbar slots: every N minutes, at each convert (on
        # the pad), while gathering (at most every N s), or when a field boost
        # starts (once, at the first pass in the boosted field). Optional:
        # only in one field, only while more than K are held (a reserve), only
        # from hive level L. The slot is found by the item's picture, so
        # moving it on the bar is fine. A use is skipped, and said, when the
        # item is not on the hotbar, its tile is greyed, the reserve would be
        # touched, the materials rule says no (materials are for crafting
        # until hive level 16) or the boost AI vetoes it in 'act'. An item the
        # boost keeper also uses (Field Dice) is left to the keeper unless the
        # rule is ticked 'rule over AI'. Default: no rules. Read at every use.
        # Edited on Boosting > Hotbar.
        ("hotbar.rules", "Hotbar timers", "list", [],
         "Presses your hotbar items on a timer or when something happens."),
        ("move.home_by_whirligig", "Go home by Whirligig when one is spare", "bool", False,
         "At the end of a gather, presses the hotbar's Whirligig (\"Teleports you "
         "and your bees back to your hive\") instead of walking home, when the "
         "bot's item sense says one is spare: two are kept for a walk home that "
         "has gone wrong, and none is used before an inventory read has counted "
         "them. A teleport that does not land on the pad falls back to the row "
         "search and the sight homing. Read at every walk home -- no restart."),
        ("move.home_glide_at_base", "Walk home from Pine Tree under a speed buff", "bool", True,
         "Times the walk home's glide at base speed even under Haste or a bear "
         "morph, instead of standing in the field until the buff runs out. The "
         "glide is no faster under a buff (MEASURED 2026-10-01: 17 flights out "
         "under one all landed in Pine Tree; a walk home whose glide ran under a "
         "polar bear morph picked up on the way landed on the pad, 19:25), and "
         "the waits cost about 2% of the day. Off waits, as before. Read at every "
         "walk -- no restart."),
        ("move.hive_slot", "Your hive slot (1-6, 0 = unknown)", "int", 0,
         "Which of the six slots at the hive is yours, counting from the "
         "left. EVERY recorded route out of the hive assumes the character "
         "starts at its own slot, and the walk there hops (5 - slot) times — "
         "so a wrong value starts every journey from the wrong place. Left "
         "at 0 the hop is skipped and said to be skipped, rather than "
         "guessed at."),
        ("account.username", "Your Roblox username", "text", "",
         "Shown in large letters on your own hive, both above the honeycomb "
         "wall and printed on the white base plate. The walk home steers "
         "toward this name and confirms with the 'Make Honey' prompt, which "
         "is how it tells your pad from the five beside it without being told "
         "a slot number. It is READ from the screen and never typed anywhere "
         "— safety.never_chat stays locked."),
        ("account.join_last_server", "Start in the server I was just in", "bool", False,
         "Start joins the Bee Swarm server this account was last in -- a "
         "friend's, say -- read from Sober's own session log, instead of your "
         "private server. Close your game first: Sober runs once at a time. "
         "Your private server, a log over an hour old, or a server that did "
         "not let the bot in last time all get the usual private join "
         "(platform/lastserver)."),
        ("account.share_link", "Private server share link", "text", "",
         "A private server's share link (Servers -> your server -> Configure "
         "-> share link): Start opens it directly instead of clicking through "
         "the home page's Servers drawer. Set on the alt, whose home page has "
         "no Bee Swarm tile (platform/lastserver.ShareLink). Empty: the usual "
         "private join."),
        ("account.follow_user", "Follow a friend in", "text", "",
         "A friend's Roblox user id (digits): Start follows them into the "
         "server they are playing in, before any share link. Set on the alt "
         "to the main's id; the private server must allow friends "
         "(platform/lastserver.FollowUser). Empty: not used."),
        ("server.join", "Which server Start joins", "choice", "my private server",
         "my private server: the Servers drawer's own Join, as always. this "
         "share link: Sober is started with server.link (MEASURED in 2026-09 "
         "a share link landed on the app home rather than in the server, so "
         "it may not get in); if it does not reach the world, server.name's "
         "drawer row if set, else your own server. a named server: the "
         "drawer row that reads server.name (look-only for now: it says which "
         "row it would join and joins your own). follow me: the server you "
         "were last in, e.g. one you moved to during Take Over -- public "
         "servers only; a private one gets your own. Every fallback says why "
         "in the run log.",
         ["my private server", "this share link", "a named server", "follow me"]),
        ("server.link", "Share link to join", "text", "",
         "The server's share link (https://www.roblox.com/share?code=...&"
         "type=Server), for 'this share link'. A secret: kept in secrets.env "
         "(readable by you alone), shown as dots, never written to a log -- "
         "only a six-character digest of it is."),
        ("server.name", "Server name to join", "text", "",
         "The private server's name as the Servers drawer shows it (e.g. "
         "\"someone's server\"), for 'a named server'. Case, spaces and "
         "apostrophes do not matter; a name two rows share is never clicked."),
        ("server.hop", "Server hopping", "choice", "off",
         "off: the bot stays in the server it joined. vicious hunt at night: "
         "when a quest or a goal wants a Vicious Bee and the night's hunt in "
         "this server found nothing, it leaves for a PUBLIC Bee Swarm server "
         "(the game's own link, a random server), hunts there, hops again or "
         "comes home (brain/hop). COSTS: it leaves your private server, the "
         "Wealth Clock streak starts again at 1 ticket an hour (the log says "
         "about how many tickets), and other players are there. Look-only for "
         "now: it says 'hop would: ...' and stays.",
         ["off", "vicious hunt at night"]),
        ("server.hop_per_night", "Hops a night, at most", "int", 3,
         "The most public servers it hops to between noon and noon."),
        ("server.hop_minutes", "Minutes in one public server", "int", 6,
         "How long it waits in a public server for a night and a hunt before "
         "it hops again (or comes home)."),
        ("server.hop_return", "Back to my private server after", "bool", True,
         "On: home to your private server when the hunt is done, the hops are "
         "used, or 50 minutes out (before the Wealth Clock's hour there). Off: "
         "it stays in the last public server until the next restart, which "
         "always goes home."),
        ("move.reset_to_start", "Reset before a long route", "bool", False,
         "Respawns at the hive first, which fixes both position and heading. "
         "Open-loop routes are only repeatable from a known starting state. "
         "The respawn dialog is confirmed on screen before anything presses "
         "Return, because the menu underneath carries Leave."),
    ]),
    ("Safety", [
        ("safety.panic_key", "Emergency stop key", "text", "F12",
         "Stops everything and releases every held key. Read straight from "
         "evdev, so it works even if the nested compositor wedges."),
        ("safety.jitter", "Human-like timing", "bool", True,
         "Log-normal delays and slight path noise rather than perfectly "
         "periodic actions. This does not make automation undetectable and is "
         "not claimed to."),
        ("safety.click_mode", "Clicking", "choice", "event_driven",
         "Event-driven clicks only when something is there. The inherited macro "
         "clicked at a fixed 0.3s all session, which is its loudest signature.",
         ["event_driven", "periodic"]),
        ("safety.never_chat", "Never type in chat", "bool", True,
         "Locked on, and it cannot be switched off from here or from the "
         "file: platform/input refuses to type while the game has focus, "
         "whatever this says."),
        ("safety.max_session_h", "Stop after (hours)", "float", 0.0,
         "0 runs until you stop it."),
        ("guard.enabled", "Pause while you play a game", "bool", True,
         "The PC froze twice with the bot running beside your own game. On: "
         "when a Steam game, Minecraft, your own Roblox or a game named below "
         "starts, the bot finishes its step and pauses, and tells you on "
         "Telegram. It never resumes by itself: press Resume (or /resume) "
         "when you are done. It also will not start while one is running: "
         "the watchdog stops, and you press Play after your game. "
         "OBS does not count."),
        ("guard.games", "Other games to pause for", "text", "mcpelauncher-client",
         "Program names, separated by commas, that count as you playing "
         "(as `ps` or System Monitor shows them). Steam games, Minecraft "
         "Java and your own Roblox are always caught; mcpelauncher-client is "
         "Minecraft Bedrock."),
    ]),
    ("Performance", [
        ("perf.capture_fps", "Capture rate (fps)", "int", 30,
         "The live view's and the stream window's frame rate. A frame costs "
         "the bot a 10 ms capture and 3 ms of work, and each capture holds "
         "the lock the bot's own looks use, so higher costs the bot a little "
         "more waiting: the run log's \"live view:\" line says how much. 30 "
         "is what the offline replay showed the bot can spare (DESIGN 8eb); "
         "for the game at its own 60 fps on a stream, set the Stream "
         "section's game picture to key colour."),
        ("perf.overlay_ms", "Refresh the detection boxes every (ms)", "int", 216,
         "The boxes are a separate pass (62 to 110 ms of work) on their own "
         "thread, so the picture no longer waits for them. 216 is the rate "
         "they ran at before (DESIGN 8eb); lower costs the bot more CPU."),
        ("perf.vlm_model", "Vision model", "text", "qwen2.5vl:7b",
         "The ollama model used for the questions above. Pull it with "
         "`ollama pull <name>`. A different name means a different cache, so "
         "switching models never serves you the old model's answers."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # Reads the reward feed ("+5,431 Honey (from Pine Tree Forest)",
        # "Defeated Mantis!") with tesseract on the CPU instead of asking the
        # vision model every few seconds on the game's GPU. MEASURED
        # 2026-10-01 on 40 feed snapshots read both ways: the same field every
        # time both named one, the same kills, 0.16 s a read against 2.2 s.
        # Off puts the vision model back. Read at every read -- no restart.
        ("perf.feed_by_ocr", "Read rewards the fast way", "bool", True,
         "Reads the reward messages without the big vision model."),
        ("perf.vlm", "Use the local vision model", "bool", True,
         "For unknown dialogs, quest text and stuck diagnosis. Cached by "
         "screenshot hash, so it gets cheaper and more deterministic over time."),
        ("perf.render_unfocused", "Keep rendering when minimised", "bool", True,
         "Required for background operation. MEASURED: without it the game "
         "renders at about 1 fps and vision stops working."),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # hyprland: a nested Hyprland, a window on your desktop (the setup
        # every live hour so far ran on). labwc: EXPERIMENTAL, a headless
        # labwc with no window anywhere, needing no Hyprland and no Wayland
        # desktop -- not yet tested with the real game
        # (docs/pending/universal-linux.md, step 2). The labwc binary is
        # $HIVEMIND_LABWC or `labwc` on PATH. You see the game only in the
        # live view; Take over makes it clickable (the first-run window logs
        # in to Roblox there).
        ("platform.compositor", "Hidden game screen (experts)", "choice", "hyprland",
         "How the game runs out of sight; leave as is.",
         ["hyprland", "labwc"]),
        ("perf.record", "Record frames for debugging", "bool", False,
         "Writes .hmr files. Useful when something goes wrong, heavy on disk."),
    ]),
    # DISK (telemetry/storage). Off by default: deleting is the owner's call.
    ("Storage", [
        ("storage.retention_gb", "Keep debug frames up to (GB)", "int", 0,
         "Deletes the oldest debug frames beyond this size (the saved "
         "incident clips and route snapshots under var). 0 keeps everything. "
         "Never deleted: the newest 20 of each folder, the last hour, and any "
         "the notes mention. Checked when the bot starts, at most every 6 "
         "hours. Under 20 GB free on the disk, the bot stops saving them "
         "whatever this says."),
    ]),
    # STREAM MODE (DESIGN 8dv): the 1920x1080 window for a 24/7 live stream,
    # and what its chat may do. Read by gui/stream and stream/show in the GUI
    # and, for the three that can change a trip, by stream/gate in the bot --
    # fresh from this file at every vote, so a switch counts at once.
    ("Stream", [
        ("stream.twitch_channel", "Twitch channel to read chat from", "text", "",
         "Empty = no Twitch chat. Set, the stream window reads that channel's "
         "chat ANONYMOUSLY (irc.chat.twitch.tv:6697 over TLS, as justinfan "
         "plus digits): no login, no token, and nothing is ever sent to chat. "
         "It and the YouTube reader below are the stream window's only "
         "connections to the internet, and only while the window is open."),
        ("stream.chat_file", "Chat from a file (other platforms)", "text", "",
         "A text file another tool appends chat to, one 'name: message' per "
         "line (a YouTube or Kick chat logger, an OBS plugin). Read from its "
         "end, so old lines are never replayed. Empty = off."),
        # YOUTUBE (DESIGN 8ed, stream/chat.YouTubeReader). Both are read by
        # the stream window only, and it restarts its readers 1.5 s after
        # either stops changing.
        ("stream.youtube_channel", "YouTube channel to read chat from", "text", "",
         "Empty = no YouTube chat. Your @handle, your channel ID (UC...), or "
         "the link of the live stream itself. Needs the API key below. With a "
         "channel, the stream window looks for your live stream at most once "
         "every 15 minutes (YouTube allows 100 searches a day), so chat can "
         "take up to 15 minutes to appear after you go live (reopening the "
         "stream window while you are live reconnects at once); a pasted "
         "live-stream link connects at once, but only to that one stream. "
         "Read-only: nothing is ever sent to chat. Steps: "
         "docs/pending/ytchat.md."),
        ("stream.youtube_api_key", "YouTube Data API key", "text", "",
         "A free key from the Google Cloud Console (YouTube Data API v3, steps "
         "in docs/pending/ytchat.md). Shown as dots. It is sent only to "
         "www.googleapis.com, in a request header, and is never shown on the "
         "stream, logged, or written anywhere but ~/.config/hivemind/"
         "secrets.env (readable by you alone). A key "
         "can only read public chat; it cannot post or change anything. The "
         "free quota is 10,000 units a day and reading chat costs 1 a poll, "
         "so chat is read every 9.6 s at the fastest, all day; if the quota "
         "runs out the chat card says so until midnight Pacific time."),
        ("stream.chat_games", "Chat games (predictions, !stats, !why)", "bool", True,
         "Predictions on each trip, a leaderboard of who called it right, and "
         "answers to !stats !why !where !goal drawn on the stream. None of it "
         "touches the game."),
        ("stream.chat_w_rain", "Chat's W rain", "bool", True,
         "When chat types a W (\"W\", \"WWW\", \"W chat\", \"big W\" -- short "
         "messages only, so \"with\" or a sentence with a \"w\" in it is not "
         "one), gold W's fall down the stream window: three for one W, more "
         "and bigger the more people type it and the faster, up to 100 at "
         "once, with a \"W ×12\" count while it lasts. One person typing it "
         "over and over counts three times at once and then once every 2 s, "
         "so a spammer alone keeps a light rain going, never a heavy one. A "
         "message with a word from \"Ignore chat containing\" rains nothing. "
         "It is drawn on the stream window only: nothing reaches chat, the "
         "game or the bot. Off clears the rain at once."),
        ("stream.chat_names", "Chat names the milestones", "bool", False,
         "Off by default because it puts words chat wrote on your stream in "
         "large letters. On, !name <words> suggests a name for the next honey "
         "milestone and the most-backed one is shown when it is reached. "
         "Letters, digits and simple punctuation only; a name from someone "
         "a moderator times out or deletes is dropped."),
        ("stream.blocked_words", "Ignore chat containing", "text", "",
         "Words separated by commas. A message containing any of them is "
         "ignored completely: no vote, no call, no name."),
        ("stream.chat_may_pick_fields", "Chat may pick the next field", "bool", False,
         "THE ONE THAT CHANGES WHAT THE BOT DOES, so it is off until you turn "
         "it on. On, each trip opens a vote between the fields the planner "
         "itself ranks near its best, and the winner is the NEXT trip's field "
         "-- over the field pinned in Gathering, too. Never a field a boss "
         "lives in, never one with no walk home (that would be a rejoin), "
         "never a convert, a purchase, a fight or a chat message."),
        ("stream.chat_may_jump", "Chat can make the bot jump", "bool", True,
         "You asked for it: \"when people type jump the Ai jumps\". A chat "
         "message that is just \"jump\" (or !jump) makes the character jump "
         "-- only in the field, between two steps of the gather pattern, at "
         "most once every 4 s however many ask, and never on a walk between "
         "places, the cannon, a convert, a menu or the hive, or while you "
         "have Pause or Take Over on. An ask it could not use within 8 s is "
         "dropped. Nothing else chat types reaches the game."),
        ("stream.chat_cooldown_min", "Minutes between chat-picked trips", "int", 60,
         "One chat trip an hour. A gathering trip ends every 843 s (the "
         "median of 234 gaps in var/trips.jsonl, 2026-09-22 to 09-26), so 60 "
         "is at most one trip in four; with the floor below, the worst chat "
         "can cost is about an eighth of the honey, and only if it always "
         "picks the weakest field on the ballot. Kept across the bot's "
         "restarts (var/stream_gate.json)."),
        ("stream.chat_field_floor", "Only fields this close to the best (%)", "int", 50,
         "A field is on the ballot only if the planner scores it at least this "
         "share of its best choice, so a chat pick costs at most "
         "(100 - this)% of that one trip. MEASURED with the planner itself "
         "(after DESIGN 8dt) over a copy of var/field_notes.json (2026-09-26 "
         "07:45, Pine Tree pinned): pine tree 1,257 (its walk home latched, "
         "so it is left off), bamboo 1,125 (90%), stump 1,002 (80%) and "
         "mountain top 986 (78%) (both left off for their bosses), cactus "
         "880 (70%), pumpkin 817 (65%), strawberry 758 (60%), spider 501 "
         "(40%). At 50 or 60 that is a vote of bamboo, cactus, pumpkin and "
         "strawberry; at 75 only bamboo is left, and there is no vote."),
        ("stream.poll_seconds", "Vote and prediction length (seconds)", "int", 120,
         "Twitch's own polls run 15 to 1,800 s. 120 closes well inside the "
         "shortest quarter of the gaps between trips (447 s, var/trips.jsonl), "
         "so the result is in before the next field is chosen. A longer "
         "setting is cut to end 447 s after the ballot for that reason, and a "
         "call on the trip is cut at 447 s too."),
        ("stream.layout", "Stream window layout", "choice", "hud",
         "'hud' fills the stream window with the game and floats the cards on "
         "it as glass, with a viewfinder over the picture and the bot's "
         "commentary as a subtitle (gui/stream_hud); 'classic' is the earlier "
         "grid of cards round a smaller picture. Read when the stream window "
         "opens.", ["hud", "classic"]),
        # THE OLD HELP, KEPT AS ITS EVIDENCE (plain-words pass 2026-10-21):
        # 'live view' draws the frames the bot already writes (no extra
        # capture), at Performance's capture rate. 'key colour' paints that
        # area pure green (#00ff00) so OBS can put its own capture of the
        # game's window under it, at the game's 60 fps. Key it with OBS's
        # Color Key filter, not Chroma Key: a Chroma Key at its defaults also
        # clears the overlay's green text and bars (DESIGN 8eb). OBS takes the
        # window from KDE, not from the bot's compositor, so it is not one of
        # the screencopy clients DESIGN 8a counts.
        ("stream.game_view", "Game picture for OBS", "choice",
         "live view",
         "Picks what the stream window shows: 'live view' is the game, "
         "'key colour' is a green screen for OBS.",
         ["live view", "key colour"]),
        # PRIVACY ON THE STREAM (DESIGN 8ec, stream/privacy). All on by
        # default but UTC times, and all read by the stream window as they
        # change.
        ("stream.hide_private_text", "Hide private details in the stream's text", "bool", True,
         "Every word the stream draws passes one filter first. On, it hides "
         "file paths (your computer's user name is in them), links, server "
         "and user ids, IP addresses, e-mail addresses and your computer's "
         "login and host names, and it leaves out lines about the machine "
         "itself (memory, swap). MEASURED over every run log to run-452: of "
         "161,507 narrated lines, 155 had a path in them (5 with your home "
         "folder) and 209 were memory lines; the rest pass unchanged. Your "
         "private-server link, its code and the code on its own are hidden "
         "even with this off."),
        ("stream.hide_username", "Hide your Roblox username in the stream's text", "bool", True,
         "Your username (Movement's 'Your Roblox username'), and the ways a "
         "screen read or a viewer can spell it (a 0 for an O, a 4 for an A, "
         "dots or spaces between its letters, look-alike letters from other "
         "alphabets), never appear in the stream's words, and chat cannot "
         "name a milestone after it."),
        ("stream.private_words", "Also hide these words on the stream", "text", "",
         "Words separated by commas, hidden wherever the stream would draw "
         "them, look-alike spellings too, and at once in what is already on "
         "screen: your Roblox display name, your surname, a school or a town."),
        ("stream.cover_menus", "Hide Roblox's own menus in the game picture", "bool", True,
         "The Esc menu opens on People, which lists everyone in the server by "
         "display name and @username, yours included, and the bot opens it "
         "at every respawn. On, the stream blurs the menu panel from the "
         "moment the bot says it is opening it until a second after it is "
         "shut, and whenever the panel is seen; it covers the whole picture "
         "if the Roblox app itself comes up (its home page lists your "
         "friends). WITH THE KEY COLOUR (the game picture setting above) OBS "
         "shows its own capture of the game's window, every rejoin's app "
         "screens included, so the stream then paints SOLID covers over it "
         "and covers the whole picture while the bot is offline or rejoining "
         "or no frame has come for 1.5 s. Only the stream's copy of the "
         "picture is masked; the bot never sees a mask."),
        ("stream.blur_roblox_chat", "Blur the Roblox chat box", "bool", True,
         "Blurs the top-left of the picture (x 0-880, y 56-540 of the game's "
         "1920x1080) whenever the chat icon's unread badge is gone, which is "
         "when the chat window may be open. MEASURED: the chat window was "
         "never open on any of 358,353 saved frames, so this should almost "
         "never show."),
        ("stream.cover_by_hand", "Cover the game picture while you play by hand", "bool", True,
         "While you have the controls (Take Over), the stream shows a card in "
         "place of the game: anything you open yourself -- the player list "
         "(Tab), the Esc menu, chat, your friends -- has no mask that follows "
         "you. Off shows your play, with only the masks above."),
        ("stream.utc_times", "Show the stream's times in UTC", "bool", False,
         "The stream shows your local clock: the header's time, each line's "
         "time, 'Wealth Clock at', today's records and a recap at your "
         "midnight. A local clock tells viewers your time zone, which narrows "
         "down where you live (though a zone is shared by many countries). "
         "On, every time is shown in UTC, marked so, and the day turns at "
         "UTC midnight."),
        ("stream.clip_markers", "Write clip markers for highlights", "bool", True,
         "Adds a line to var/stream_clips.txt at every big convert, new best "
         "trip, knock-out, boss sighting, quest hand-in, milestone and daily "
         "recap: the time, and how long after the stream window opened, to "
         "find the highlights in a recording."),
        ("stream.voice", "The bot talks (text to speech)", "bool", True,
         "While the stream window is open, the bot says out loud what it is "
         "doing and deciding -- the next field and why, a cannon launch, the "
         "honey banked, a token chase, a boss, a knock-out -- in a lively voice "
         "and never the same words twice running. Only what really happened "
         "is said, after the same privacy gate as the stream's text. Spoken by "
         "Piper (offline, ~/Applications/piper) to the desktop's sound, which "
         "OBS's Desktop Audio carries."),
        ("stream.voice_name", "Voice", "choice", "joe",
         "Joe (a man's voice, CC0) or Kristin (a woman's voice, public domain) "
         "-- both licensed for use on a stream.", ["joe", "kristin"]),
        ("stream.voice_volume", "Voice volume (%)", "int", 80,
         "How loud the voice plays, 0-100."),
        ("stream.chat_ask", "Chat can ask the bot questions (!ask)", "bool", True,
         "Chat types !ask and a question; the bot answers on the stream and "
         "out loud -- in its own words, from what it really knows (where it "
         "is going and why, its honey, its quest). Never repeats what anyone "
         "typed or their name. Questions that are not PG, links, spam, or "
         "attempts to make it say something are ignored; one question per "
         "viewer every 5 minutes, one answer every 40 seconds."),
        ("stream.voice_room", "The voice talks to chat", "bool", True,
         "Now and then, when it has been quiet: a welcome, a reminder to like "
         "and subscribe, and what chat can do -- only the commands the stream "
         "really answers, and only while it is reading chat."),
        ("stream.voice_banter", "The voice tells jokes and bee facts", "bool", True,
         "Now and then, at most every 10 minutes, when the bot has nothing of its own to say: a bee joke, a real "
         "bee fact or the bot laughing at itself -- all PG, and only while it is "
         "really playing (stream/banter)."),
    ]),
    # TELEGRAM (the owner, 2026-10-14: "a setup telegram Bot tab so it gives
    # alerts and stats with toggles to choose what u want to get notified
    # about"). Read by scripts/telegram_alerts.py (the hivemind-telegram
    # service) at every alert, from this file -- it runs on the system python,
    # which has no PyYAML, so it reads these flat lines itself and keeps a copy
    # of the defaults (tests/unit/test_telegram_tab.py holds the two equal).
    # The bot token is NOT one of these: it lives in telegram.env (0600) and
    # never in this file, a preset or a log. Defaults by measured volume over
    # the 34 run logs of 2026-10-13/14: on for what needs you or is rare (a
    # needs-you card 2 a day, rejoins 5, knock-outs 8, purchases 4, Commando
    # 3, hand-ins 3 + Ant Challenges 10, Royal Jelly 1), off for the chatty
    # (Blender 16, planters 25, the self-review 20).
    ("Telegram", [
        ("telegram.alerts", "Send alerts to Telegram", "bool", False,
         "The master switch. Off, nothing is sent: no alert, no picture."),
        ("telegram.needs_you", "Questions that need you", "bool", True,
         "A card in the Decision Inbox: a purchase to confirm or a choice only "
         "you can make. Answer it in Hivemind."),
        ("telegram.terms", "Roblox's \"Updated Agreements\" box", "bool", True,
         "Roblox wants its new terms accepted, which the bot never does for "
         "you; it waits, trying again every 15 minutes."),
        ("telegram.rejoin", "Rejoins", "bool", True,
         "Stranded with pollen and rejoining the server (the Wealth Clock "
         "streak restarts). At most one every 30 minutes."),
        ("telegram.knocked_out", "Knocked out", "bool", True,
         "A mob knocked the character out, and how much pollen it lost. One "
         "message a knock-out."),
        ("telegram.error", "Errors and the bot stopping", "bool", True,
         "The bot hit an error (the watchdog restarts it), or has been down "
         "for 10 minutes without anyone pressing Stop, and when it is back."),
        ("telegram.quest", "Quests handed in", "bool", True,
         "Each quest handed in, and each Ant Challenge played for the Army "
         "Ants quest."),
        ("telegram.commando", "Commando Chick captured", "bool", True,
         "A Commando Chick beaten, with how long the fight took."),
        ("telegram.blender", "Blender crafts", "bool", False,
         "Each item the Blender finished and the bot collected. Off by "
         "default: about 16 a day."),
        ("telegram.planter", "Planters planted and harvested", "bool", False,
         "Each planter placed and each one harvested. Off by default: about "
         "25 a day."),
        ("telegram.purchases", "Purchases", "bool", True,
         "Everything the bot buys with honey or tickets (never Robux)."),
        ("telegram.royal_jelly", "Royal Jelly rolls", "bool", True,
         "The bee each Royal Jelly roll gave. A Mythic Bee is always sent, as "
         "a picture of the game, even with this off."),
        ("telegram.self_review", "Hourly self-review", "bool", False,
         "The bot's own hourly notes on what slowed it down. Off by default: "
         "one every hour."),
        ("telegram.commands", "Allow commands from Telegram", "bool", False,
         "/status, /screenshot, /pause, /resume, /stop and /report, sent to "
         "your bot, work -- only from your own chat (the one Detect chat "
         "found); anyone else's are ignored. /stop is the same clean stop as "
         "the Stop button. A stopped bot is started only from Hivemind. Off, "
         "they are ordinary messages."),
    ]),
    ("Stats cards", [
        ("telegram.stats_cards", "Stats card to Telegram", "choice", "off",
         "A picture of the bot's numbers: honey made, honey an hour, trips, "
         "crafts. 'daily at 21:00' sends the day's card; 'every 4 hours + "
         "daily' adds a 4-hour card at 09:00, 13:00 and 17:00.",
         ["off", "daily at 21:00", "every 4 hours + daily"]),
    ]),
    # THE WINDOW ITSELF (the owner, 2026-10-14: "a simple mode and then an
    # advanced mode"). Read and written by gui/window, never by the bot; the
    # switch at the top right of the window is this setting.
    ("Window", [
        ("gui.mode", "Window mode", "choice", "simple",
         "'simple' is the big live view, four numbers, what it is thinking, "
         "its goals and planters, and Start / Pause / Stop; 'advanced' is "
         "every tab. The switch at the top right of the window changes it, "
         "and it is kept for the next time the window opens.",
         ["simple", "advanced"]),
        # THE NEW LAYOUT (ROADMAP U18, the owner 2026-10-16/17: five simple
        # tabs, Advanced mode in Settings for the rest). Read by gui/app when
        # the window opens. 'new' by default since the owner, 2026-10-19: "i want
        # new UI to be default".
        ("gui.layout", "Window layout", "choice", "new",
         "'new' is the five tabs -- Macro, AI Progress, Boosting, Stats and "
         "Settings -- with Start / Pause / Stop always at the bottom and "
         "Advanced mode in Settings for every other option; 'classic' is the "
         "window as it was. Applies the next time the window opens.",
         ["classic", "new"]),
        # START ON BOOT (ROADMAP U13, viewer @Mouseinapizzabox 2026-10-15):
        # writes/removes ~/.config/autostart/hivemind.desktop (gui/autostart);
        # read again when the window opens at login, so OFF always wins.
        ("gui.start_on_boot", "Start farming when the PC starts", "bool", False,
         "Opens Hivemind after you log in and, after 60 seconds (with a Cancel "
         "button, and a Telegram note you can answer /stop to), presses Start "
         "-- only if no game of yours is running and there is enough free "
         "memory. Off removes the login entry again."),
    ]),
]


# U15B, SHIPPED DEFAULTS OFF (the owner, 2026-10-19: "leave everything off as
# default so people can customize"). Every key whose shipped default U15b
# flips (now all off), with the default it had BEFORE (integ at 67e96a6). tools/
# pin_owner_settings.py reads this to write the owner's own effective value
# of each one into his settings.yaml, so his bot changes nothing.
U15B_WAS: dict[str, Any] = {
    "gather.chase_tokens": True, "gather.micro_convert": True,
    "move.home_by_whirligig": True, "gather.follow_boost": True,
    "quests.enabled": True, "badges.look": True,
    "quests.polar": True, "quests.honey": True, "quests.bucko": True,
    "quests.riley": True, "quests.spirit": True, "quests.black_bear": True,
    "quests.brown_bear": True, "quests.panda": True, "quests.mother": True,
    "economy.dispensers": True, "economy.wealth_clock": True,
    "economy.memory_match": True, "economy.shop_look": True,
    "economy.planters": True, "economy.boosters": True, "economy.use_items": True,
    "economy.sticker_tickets": True, "economy.buy": True, "economy.blender": True,
    "economy.auto_jelly_off": "look",
    "boost.boosters": True, "boost.glitter": True, "boost.dice": True,
    "boost.item_buffs": True, "boost.ai": "look",
    "combat.bosses": True, "combat.commando": True, "combat.bug_runs": True,
    "combat.bug_loot": True, "combat.loot_by_sight": True,
    "combat.bug_ladybug": True, "combat.bug_rhino_beetle": True,
    "combat.bug_spider": True, "combat.bug_mantis": True,
    "combat.bug_scorpion": True, "combat.bug_werewolf": True,
    "combat.ant_challenge": True,
    "hive.read_bees": True, "hive.follow_plan": True, "goals.read_inventory": True,
    "telegram.alerts": True, "telegram.commands": True,
    "telegram.stats_cards": "daily at 21:00",
    # 2026-10-21 feature sweep: four NOT_WIRED switches that still shipped ON
    # (rule 5). Nothing reads them, so the flip changes no play; listed so
    # pin_owner_settings keeps a file's old value all the same.
    "combat.mobs": True, "quests.science": True, "economy.nectar_vials": True,
    "move.reset_to_start": True,
}


# U12, ENABLE/DISABLE EVERYTHING (the owner's friend, 2026-10-15): every
# errand and behaviour with its own on/off, on one page (Settings > Features,
# gui/shell). ONE LIST: the page draws it and tests/unit/test_settings_effect
# holds it to the schema -- each key must be read where it decides something,
# and every errand/behaviour toggle must be here or in FEATURE_EXCLUDED.
# (group, key, short label, one plain line, badge). The badge says what the
# code does today: "live" acts; "look-only" only logs what it would do (its
# *_LIVE constant is False); "needs measuring" acts on a guess nobody has
# measured yet.
FEATURE_GROUPS = ("Gathering", "Quests", "Errands and dispensers", "Boosts",
                  "Bosses and mobs", "Challenges", "Hive, jelly and eggs",
                  "Buying and crafting", "Alerts")
FEATURES: list[tuple[str, str, str, str, str]] = [
    ("Gathering", "gather.auto_field", "Pick the field for me",
     "Chooses each trip's field by the honey it expects an hour.", "live"),
    ("Gathering", "move.use_cannon", "Red cannon to far fields",
     "Flies to fields 400+ studs away instead of walking.", "live"),
    ("Gathering", "gather.use_sprinklers", "Place sprinklers",
     "Puts down your sprinklers when it starts farming a field.", "live"),
    ("Gathering", "gather.natro_field_start", "Start each field from its best spot",
     "Walks to the field's sprinkler spot and faces the right way first.", "live"),
    ("Gathering", "gather.leave_at_empty_bag", "Leave the hive when emptied",
     "Ends a convert as soon as the backpack reads empty.", "live"),
    ("Gathering", "move.home_glide_at_base", "Pine Tree: wait out speed",
     "Waits out a speed buff before gliding home from Pine Tree.", "live"),
    ("Gathering", "mode.macro", "Macro mode",
     "Your own field list (Macro > Gather) replaces the AI's choice.", "live"),
    ("Gathering", "gather.chase_tokens", "Chase tokens",
     "Detours for tokens it can see near the character.", "live"),
    ("Gathering", "gather.rotate_camera", "Sweep the camera for bubbles",
     "Turns the camera between passes so the tool pops bubbles.", "needs measuring"),
    ("Gathering", "gather.stay_in_field", "Stay on the flowers",
     "Steps back onto the flowers if it walks off them.", "needs measuring"),
    ("Gathering", "gather.micro_convert", "Micro-Converter when full",
     "Converts a full bag in the field with a Micro-Converter.", "live"),
    ("Gathering", "move.home_by_whirligig", "Home by Whirligig",
     "Uses a spare Whirligig to get back to the hive.", "live"),
    ("Quests", "quests.enabled", "Do quests",
     "Talks to the bears you tick below and does their quests.", "live"),
    ("Quests", "quests.first", "Quest fields first",
     "Gathers where a quest wants pollen, whatever it pays.", "live"),
    ("Quests", "quests.scroll", "Read the whole quest list",
     "Scrolls the quest panel to read every quest, not just the top.", "live"),
    ("Quests", "badges.look", "Look at the badge menu",
     "Pictures the badge menu once a session; claims nothing yet.", "look-only"),
] + [("Quests", f"quests.{key}", name.removeprefix("the "), f"Does {name}'s quests for you.", "live")
     for key, name in (("polar", "the Polar Bear"), ("honey", "the Honey Bee"),
                       ("bucko", "Bucko Bee"), ("riley", "Riley Bee"),
                       ("spirit", "the Spirit Bear"), ("black_bear", "the Black Bear"),
                       ("brown_bear", "the Brown Bear"), ("panda", "the Panda Bear"),
                       ("mother", "Mother Bear"))] + [
    ("Errands and dispensers", "economy.dispensers", "Dispensers",
     "Honey, treat and berry dispensers and the free Ant Pass, when due.", "live"),
    ("Errands and dispensers", "economy.wealth_clock", "Wealth Clock",
     "Collects the clock's tickets every hour.", "live"),
    ("Errands and dispensers", "economy.memory_match", "Memory Match",
     "Plays the honey Memory Match games; never tickets or Robux.", "live"),
    ("Errands and dispensers", "economy.planters", "Planters",
     "Places, harvests and replants the planters you hold.", "live"),
    ("Errands and dispensers", "nectar.keep_up", "Keep the nectars up",
     "Gathers where your planter grows a low nectar, if it costs under 15%.",
     "needs measuring"),
    ("Errands and dispensers", "economy.early_harvest", "Harvest planters early",
     "Harvests a growing planter early to protect field health.", "needs measuring"),
    ("Errands and dispensers", "economy.shop_look", "Check the Ticket Tent",
     "Opens the Ticket Tent's shop once and pictures it; buys nothing.", "look-only"),
    ("Errands and dispensers", "economy.beesmas", "Beesmas machines",
     "Visits the event machines while Beesmas is on.", "needs measuring"),
    ("Boosts", "boost.keeper", "Boost keeper",
     "Refreshes boosts just before they run out.", "live"),
    ("Boosts", "boost.boosters", "Keeper: field boosters",
     "Lets the keeper press field boosters on cooldown.", "live"),
    ("Boosts", "boost.glitter", "Keeper: Glitter",
     "Lets the keeper use Glitter before a boost ends.", "live"),
    ("Boosts", "boost.dice", "Keeper: Field Dice",
     "Lets the keeper roll Field Dice before a boost ends.", "live"),
    ("Boosts", "boost.item_buffs", "Item buffs in a boost",
     "Glue, extracts, Enzymes and Jelly Beans during a boost.", "live"),
    ("Boosts", "economy.boosters", "Walk to field boosters",
     "Presses a field booster when the odds pay for the walk.", "live"),
    ("Boosts", "gather.follow_boost", "Follow field boosts",
     "Gathers where a booster's boost landed.", "live"),
    ("Boosts", "economy.use_items", "Use spare items",
     "Glitter, Glue and extracts in the field; also Royal Jelly, feeding, "
     "the Blender and planters.", "live"),
    ("Boosts", "economy.sticker_tickets", "Sticker Stack with tickets",
     "Keeps the Sticker Stack boost going for 25 tickets.", "live"),
    ("Boosts", "boost.ai", "Boost helper",
     "Look: just tells you. Act: skips boosts that do not pay.", "live"),
    ("Bosses and mobs", "combat.bosses", "Fight bosses",
     "Fights the Coconut Crab, King Beetle, Tunnel Bear and Stump Snail.", "live"),
    ("Bosses and mobs", "combat.commando", "Commando Chick",
     "Fights it from the safe stair every 30 minutes.", "live"),
    ("Bosses and mobs", "combat.vicious", "Vicious Bee",
     "Hunts it at night in Clover and Spider.", "live"),
    ("Bosses and mobs", "combat.stump_snail", "Stump Snail",
     "Chips at its saved HP while that beats gathering.", "live"),
    ("Bosses and mobs", "combat.mondo_loot", "Mondo Chick loot",
     "Chases the tokens a defeated Mondo Chick drops.", "look-only"),
    ("Bosses and mobs", "combat.fireflies", "Fireflies",
     "Night trips to firefly fields when a goal wants Moon Charms.", "live"),
    ("Bosses and mobs", "combat.bug_runs", "Bug runs",
     "Goes out after a convert to kill field mobs.", "live"),
    ("Bosses and mobs", "combat.bug_loot", "Collect the drops",
     "Walks over the drops after a kill.", "live"),
    ("Bosses and mobs", "combat.loot_by_sight", "Loot by sight",
     "Chases a kill's loot it can see.", "live"),
] + [("Bosses and mobs", f"combat.bug_{key}", name,
      f"Bug runs for {name.lower()} even when no quest needs them.", "live")
     for key, name in (("ladybug", "Ladybugs"), ("rhino_beetle", "Rhino Beetles"),
                       ("spider", "The Spider"), ("mantis", "Mantises"),
                       ("scorpion", "Scorpions"), ("werewolf", "The Werewolf"))] + [
    ("Challenges", "combat.ant_challenge", "Ant Challenge",
     "Plays it with an Ant Pass when a quest wants ants.", "live"),
    ("Challenges", "challenges.stick_bug", "Stick Bug Challenge",
     "Takes the Stick Bug's free start; tickets never.", "look-only"),
    ("Hive, jelly and eggs", "hive.read_bees", "Read the hive",
     "Reads the bee menu every few hours; clicks nothing inside.", "live"),
    ("Hive, jelly and eggs", "goals.read_inventory", "Read the inventory",
     "Reads the goal materials' counts once a session.", "live"),
    ("Hive, jelly and eggs", "hive.follow_plan", "Royal Jelly follows the plan",
     "Royal Jelly goes where your Hive Planner says.", "live"),
    ("Hive, jelly and eggs", "eggs.hatch_mythic", "Hatch Mythic Eggs",
     "Puts a Mythic Egg in the next new hive slot instead of saving it.", "live"),
    ("Hive, jelly and eggs", "economy.auto_jelly_off", "Game's Auto-Jelly",
     "Look: only checks the game's switch. Act: turns it off.", "live"),
    ("Hive, jelly and eggs", "hive.grind_basic", "Gifted Basic grinder",
     "Basic Egg, Royal Jelly, repeat in one slot until it is gifted.",
     "needs measuring"),
    ("Buying and crafting", "economy.buy", "Buy what the plan says",
     "Gear, eggs and slots with honey and tickets; never Robux.", "live"),
    ("Buying and crafting", "economy.tickets.diamond_eggs", "Diamond Eggs with tickets",
     "400 tickets each at the Ticket Tent, only for the Diamond Mask; never hatched.", "live"),
    ("Buying and crafting", "economy.tickets.magic_beans", "Magic Beans with tickets",
     "20 tickets each, for a planter short of beans; says what it would buy.", "look-only"),
    ("Buying and crafting", "economy.blender", "Blender",
     "Crafts the material the next goal is short of.", "live"),
    ("Alerts", "telegram.alerts", "Telegram alerts",
     "Sends alerts to your phone (Settings > Telegram picks which).", "live"),
    ("Alerts", "telegram.commands", "Commands from Telegram",
     "Acts on the commands you send from your phone.", "live"),
    ("Alerts", "telegram.stats_cards", "Stats card to Telegram",
     "Sends the stats card on a schedule.", "live"),
]
# THE CORE FARM LOOP (U15b): gather, convert, walk home. On by default; every
# other FEATURES entry ships OFF.
CORE_FEATURES = frozenset({"gather.auto_field", "move.use_cannon",
                           "gather.use_sprinklers", "gather.natro_field_start",
                           "gather.leave_at_empty_bag", "move.home_glide_at_base"})
# Errand/behaviour toggles (by prefix and type) NOT on the Features page, and why.
FEATURE_EXCLUDED = {
    **{k: "nothing reads it (NOT_WIRED): a switch here would lie"
       for k in ("combat.mobs", "quests.science", "economy.nectar_vials",
                 "move.open_loop", "move.reset_to_start")},
    "economy.wind_shrine": "unreachable: there is no route to the shrine",
    "eggs.save_diamond": "a safeguard: off lets it do MORE (hatch Diamond Eggs)",
    "combat.bug_worth_it": "a safeguard: off sends MORE bug runs",
    "planner.errand_profit": "the ORDER errands run in; both values are a full order",
    "learn.token_school": "keeps training frames; changes no play",
    "server.hop": "which server it plays in, on Settings > Server",
    "server.hop_return": "which server it plays in, on Settings > Server",
    "account.join_last_server": "which server it joins, not what it does there",
    **{f"telegram.{k}": "which alerts; nothing is sent while Telegram alerts is off"
       for k in ("needs_you", "terms", "rejoin", "knocked_out", "error", "quest",
                 "commando", "blender", "planter", "purchases", "royal_jelly",
                 "self_review")},
}


def feature_off(key: str):
    """The value that switches a feature off: False, or a choice's 'off'/'never'."""
    entry = next(e for _, es in SECTIONS for e in es if e[0] == key)
    if entry[2] == "bool":
        return False
    return next(c for c in entry[5] if c in ("off", "never"))


def defaults() -> dict[str, Any]:
    return {entry[0]: entry[3] for _, entries in SECTIONS for entry in entries}


def describe(key: str) -> str:
    for _, entries in SECTIONS:
        for entry in entries:
            if entry[0] == key:
                return entry[4]
    return ""


def unreadable(exc: BaseException) -> str:
    """Why the settings file could not be read, WITHOUT QUOTING THE FILE.

    PyYAML's error text includes the offending source line with a caret under
    it, and that line can be `stream.youtube_api_key`'s (a SECRET) -- a
    hand-edit that breaks the syntax there put the key into the Log tab, the
    bot's log and the panel's warning (review of 8ed). So a YAML error is
    told by PyYAML's fixed words for it ("while scanning a quoted scalar",
    "found unexpected end of stream") and their line numbers only. A long
    quoted name in them -- an alias or a tag, which is text from the file --
    is cut out too; a token's name ('<block end>') is PyYAML's own and is
    kept. An OSError is told by the system's words, which name the file, not
    what is in it.
    """
    if isinstance(exc, yaml.MarkedYAMLError):
        parts = []
        for words, mark in ((exc.context, exc.context_mark),
                            (exc.problem, exc.problem_mark)):
            if words:
                words = re.sub(r"'(?!<)[^']{12,}'", "'…'", str(words))
                parts.append(words + (f" at line {mark.line + 1}"
                                      if mark is not None else ""))
        return ", ".join(parts) or "not valid YAML"
    if isinstance(exc, OSError):
        return exc.strerror or type(exc).__name__
    return type(exc).__name__


class Settings:
    """Read-side view of the settings file, with defaults for anything missing.

    Never raises on a missing or malformed file: a broken config must not stop
    the bot from running with sensible defaults, and `problems` records what was
    wrong so the GUI can say so.
    """

    def __init__(self, path: Path | str = CONFIG):
        self.path = Path(path)
        self.problems: list[str] = []
        self.values: dict[str, Any] = defaults()
        self.reload()

    def reload(self) -> list[str]:
        """Re-read the file. Returns the keys whose value changed.

        THE RUNNING BOT CALLS THIS NOW, from the socket thread, whenever the
        GUI saves a setting (DESIGN 8du) -- while the farm loop reads values
        on its own thread. So the new values are built aside and swapped in
        with one assignment: a reader sees the old dict or the new one, never
        the defaults half-way through a fill.
        """
        before = dict(getattr(self, "values", None) or {})
        values, problems = self._read()
        values.update(read_secrets(self.path))     # secrets.env wins (SECRET)
        for key in BOUNDS:
            used, why = settle(key, values.get(key))
            if why:
                problems.append(why)
                values[key] = used
        for key, check in LISTS.items():
            values[key], why = check(values.get(key))
            problems += why
        for key, locked in LOCKED.items():
            if values.get(key) != locked:
                problems.append(f"{key} is locked to {locked}; the file's "
                                f"{values.get(key)!r} is ignored")
                values[key] = locked
        self.values, self.problems = values, problems
        return sorted(k for k in set(before) | set(values)
                      if before.get(k) != values.get(k))

    def describe_changes(self, changed) -> str:
        """One line for the Log tab: what changed and when it applies."""
        if not changed:
            text = "settings re-read; nothing changed"
        else:
            when: dict[str, list[str]] = {}
            for key in changed:
                when.setdefault(takes_effect(key), []).append(key)
            text = "settings re-read: " + "; ".join(
                f"{', '.join(keys)} — {moment}" for moment, keys in when.items())
        if self.problems:
            text += " (problems: " + "; ".join(self.problems) + ")"
        return text

    def _read(self) -> tuple[dict[str, Any], list[str]]:
        """Defaults overlaid with whatever in the file is usable."""
        values: dict[str, Any] = defaults()
        problems: list[str] = []
        if not self.path.exists():
            return values, problems
        try:
            stored = yaml.safe_load(self.path.read_text())
        except (OSError, yaml.YAMLError) as exc:
            problems.append(f"could not read settings: {unreadable(exc)}")
            return values, problems
        if not isinstance(stored, dict):
            problems.append("settings file is not a mapping; using defaults")
            return values, problems
        known = defaults()
        for key, value in stored.items():
            if key not in known:
                # A setting from a newer version. Keep it rather than discard it,
                # so downgrading and upgrading does not silently erase choices.
                values[key] = value
                continue
            # bool is a subclass of int, so `isinstance(True, int)` is True and
            # a plain isinstance check accepts a YAML boolean for every int
            # setting AND -- via the int-for-float clause below -- every float
            # one. That is not cosmetic: `autonomy.min_confidence: no` became
            # 0.0 with NOTHING added to problems, which switches the
            # irreversibility firewall off. YAML makes it easy to write by
            # accident, too: `no`, `off` and `n` are all booleans.
            # So bool-ness must match exactly, in both directions.
            if isinstance(value, bool) and key in RETIRED_BOOLS:
                continue          # the dead switch's saved value: the default, quietly
            if isinstance(value, bool) != isinstance(known[key], bool):
                problems.append(
                    f"{key}: expected {type(known[key]).__name__}, "
                    f"got {type(value).__name__}"
                    + (" (YAML reads no/off/y/n as booleans)"
                       if isinstance(value, bool) else "")
                    + "; using default")
                continue
            if not isinstance(value, type(known[key])) and not (
                    isinstance(known[key], float) and isinstance(value, int)):
                problems.append(
                    f"{key}: expected {type(known[key]).__name__}, "
                    f"got {type(value).__name__}; using default")
                continue
            values[key] = value
        return values, problems

    def get(self, key: str, fallback: Any = None) -> Any:
        return self.values.get(key, fallback if fallback is not None
                               else defaults().get(key))

    def bool(self, key: str) -> bool:
        return bool(self.get(key))

    def int(self, key: str) -> int:
        try:
            return int(self.get(key))
        except (TypeError, ValueError):
            return int(defaults().get(key, 0))

    def float(self, key: str) -> float:
        try:
            return float(self.get(key))
        except (TypeError, ValueError):
            return float(defaults().get(key, 0.0))

    def fraction(self, key: str) -> float:
        """A percentage setting as 0..1, which is how the engines want it."""
        return max(0.0, min(1.0, self.int(key) / 100.0))

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        return key in self.values

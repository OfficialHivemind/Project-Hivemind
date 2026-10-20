"""A13: the golden-frame suite. Every screen reader, on saved REAL frames, with
the answer a person checked by eye on that frame -- so a change to a reader (or
to a template, a threshold, a region) cannot break one without a red test.

HOW IT IS LAID OUT
  READERS  one line per reader: the call the bot makes, reduced to a plain
           value (a tuple, a name, a bool).
  GOLDEN   per frame, the readers whose answer was checked on that frame.
           A None/False there is an answer too: "no modal on the world" is what
           stops a reader firing on the world.
  WRONG_TODAY  answers the reader gets WRONG today, with the right answer.
           strict xfail: the day a fix makes one right, it fails as XPASS, and
           the line moves up into GOLDEN. Wrong answers are never written as
           golden.

THE FRAMES. tests/fixtures/screens|dialogs (already here) and
tests/fixtures/golden (added 2026-10-26 and 27, copied byte for byte from the owner's
var/: each name says what and the date; the source is in GOLDEN's comment).
They are the owner's own screen, so tools/export_public.py leaves every
tests/fixtures image out of the public repo (EXCLUDE "tests/fixtures/*.png"
etc.; fnmatch's * crosses folders); a missing frame SKIPS, it never fails.

THE ANSWERS. Read off each frame by eye 2026-10-26 (HUD digits, the hotbar's
icons, the panel, the buff icons), then compared with what each reader returned
on the same commit. Where they agreed the answer is here; where they did not, it
is in WRONG_TODAY. Bar fills are compared to 0.01; the true fill is the pills'
own value/capacity (noted beside each).

Adding a frame: copy it in (never re-encode a frame: JPEG again moves pixels),
look at it, write the answers you SEE, run this file, and put any reader that
disagrees in WRONG_TODAY with why.
"""
from __future__ import annotations

import pathlib
import shutil
from functools import lru_cache

import cv2
import pytest

import hivemind
from hivemind.act import inventory, routes, shoplook
from hivemind.act.hive import _state_of
from hivemind.brain.farm import HudReader
from hivemind.datapaths import data
from hivemind.vision import (banner, buffs, coins, digits, feed, hotbar_items, night, notices,
                             questlist, screen, sprinkler, tokentypes)
from hivemind.vision import screenstate as ss

FIX = pathlib.Path(hivemind.__file__).resolve().parents[2] / "tests" / "fixtures"


@lru_cache(maxsize=None)
def _templates():
    return digits.TemplateSet.load(data("templates", "digits"))


@lru_cache(maxsize=None)
def _frame(name: str):
    path = FIX / name
    if not path.exists():
        pytest.skip(f"{name} is not in this checkout (private frames)")
    frame = cv2.imread(str(path))
    assert frame is not None, name
    return frame


def _pollen(f):
    r = HudReader(lambda: f, _templates()).pollen()
    return (r.state.name, r.value, r.capacity)


def _honey(f):
    r = HudReader(lambda: f, _templates()).honey()
    return r.value if r.state.name == "OK" else r.state.name


def _modal_click(f):
    """Where AppUI.dismiss_modal clicks (its first button), or None."""
    m = ss.find_modal(f)
    return None if m is None or not m.buttons else tuple(int(v) for v in m.button_centre(0))


def _bar(f):
    v = ss.pollen_bar_fill(f)
    return None if v is None else round(v, 2)


def _box(found):
    return None if found is None else tuple(int(v) for v in found)


READERS = {
    "screen": lambda f: ss.classify(f, _templates()).name,          # the join and the run's guard
    "pollen": _pollen,                                               # brain/farm HudReader
    "honey": _honey,
    "bar": _bar,                                                     # screenstate.pollen_bar_fill
    "modal_click": _modal_click,                                     # screenstate.find_modal
    "reset": ss.reset_dialog_present,
    "respawn_at": lambda f: _box(ss.respawn_button_point(f)),
    "make_honey": ss.make_honey_present,                             # own pad / empty-bag banner
    "banner": lambda f: _box(None if (p := banner.find(f)) is None else p.box),
    "cannon": lambda f: (ss.red_cannon_prompt_score(f) or 0.0) >= routes.CANNON_TEMPLATE_CONFIRMS,
    "side": questlist.side_panel,                                    # quest / badge panel open
    "thumb": lambda f: None if (t := questlist.thumb(f)) is None else (t.top, t.bottom),
    "hotbar": lambda f: tuple(s.item for s in hotbar_items.read(f)),
    "haste": lambda f: (lambda h: (h.present, h.stacks))(buffs.haste(f)),
    "bear": lambda f: buffs.bear(f).kind,
    "feed_rows": lambda f: len(feed.rows(f)),                        # the reward feed's pills
    "notice": lambda f: _box(notices.newest_box(f)),                 # red refusal notice
    "dialog": inventory.dialog_open,                                 # the Yes/No box
    "sky": night.sky,                                                # the two sky patches
    "night": night.is_night,                                         # sky, else the pad's floor
    "gushers": lambda f: len(sprinkler.find(f)),                     # Golden Gushers on screen
    # tesseract (skipped without it): what the bot does with the words
    "pad": lambda f: _state_of(shoplook.prompt_text(f)).name,
    "notice_kind": lambda f: notices.kind_of(notices.read_newest(f)),
    # vision/screen.offsets: (top left, top, bottom), each (dx, dy) or None
    "anchors": lambda f: tuple(screen.offsets(f).values()),
}
OCR = {"pad", "notice_kind"}

LOADOUT = ("sprinkler", "gumdrops", "whirligig", "field_dice", "micro_converter",
           "jelly_beans", "coconut")      # the owner's hotbar, 26 Oct
NOTHING = {"modal_click": None, "reset": False, "respawn_at": None, "dialog": False}
HUD_HERE = ((0, 0), (0, 0), (0, 0))      # each HUD piece where the 1920x1080 rule puts it
NO_HUD = (None, None, None)

GOLDEN = {
    # --- already-kept fixtures ----------------------------------------------
    "screens/in_game.png": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 445_372, 660_000), "honey": 10_216_184,
        "bar": 0.67, "make_honey": False, "side": None, "haste": (False, None),
        "bear": None, **NOTHING},                                    # true fill 0.675
    "screens/field_earning.png": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 103_439, 688_050), "honey": 16_201_128,
        "bar": 0.14, **NOTHING},                                     # true fill 0.150
    "screens/hive_make_honey.png": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 627_840, 660_000), "honey": 16_266_447,
        "bar": 0.95, "make_honey": True, **NOTHING},                 # true fill 0.951
    "screens/app_home.png": {"anchors": NO_HUD,
        "screen": "APP_HOME", "pollen": ("NO_HUD", None, None), "make_honey": False,
        **NOTHING},
    "screens/game_page_top.png": {
        "screen": "APP_HOME", "pollen": ("NO_HUD", None, None), **NOTHING},
    "screens/loading_splash.png": {"screen": "LOADING", **NOTHING},
    "screens/loading_headless.png": {"screen": "LOADING", **NOTHING},
    # the escape menu is dark (median luma 46, screenstate HOME_BAND note): there
    # is no menu class, so it reads LOADING; the hud says NO_HUD; the menu redraws
    # the Roblox button, so the top-left anchor is not seen (pills and bar are)
    "screens/escape_menu.png": {"anchors": (None, (0, 0), (0, 0)),
        "screen": "LOADING", "pollen": ("NO_HUD", None, None), "reset": False,
        "respawn_at": None, "modal_click": None},
    "screens/reset_dialog.png": {
        "screen": "LOADING", "pollen": ("NO_HUD", None, None), "reset": True,
        "respawn_at": (849, 483), "modal_click": None},
    "screens/modal_join_error.png": {"anchors": NO_HUD,     # Error 524, one button: Leave
        "screen": "MODAL", "modal_click": (960, 627), "pollen": ("NO_HUD", None, None)},
    "dialogs/micro_converter_hud_hold.jpg": {"anchors": HUD_HERE,   # A25: Yes/No box over the world
        "pollen": ("NO_HUD", None, None), "dialog": True, "modal_click": None},

    # --- golden/, copied 2026-10-26 ------------------------------------------
    # var/claim/walk_02.png (2026-09-20 12:57): a free pad, "E Claim Hive"
    "golden/claim_hive-0920.png": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 0, 660_000), "honey": 16_167_651, "bar": 0.0,
        "banner": (853, 62, 283, 58), "pad": "EMPTY", "make_honey": False, "cannon": False,
        "side": None, "haste": (False, None), "feed_rows": 0, "notice": None,
        # slots 3-7 EMPTY: the outline over green grass (hotbar_items AN EMPTY SLOT)
        "hotbar": ("sprinkler", "gumdrops", None, None, None, None, None), **NOTHING},
    # var/quest_reads/close-065946-open.jpg (2026-09-29 06:59): the quest menu
    # open on our pad, empty-bag banner, Haste x1 (no count drawn)
    "golden/quest_menu_open-0929.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 0, 2_587_500), "honey": 256_959_915,
        "side": "quests", "thumb": (176, 507), "make_honey": True, "pad": "UNKNOWN",
        "haste": (True, None), "bear": None,
        # slot 3 then held a green item with no template (x1): unknown is right
        "hotbar": ("sprinkler", "gumdrops", None, "field_dice", "micro_converter",
                   "jelly_beans", None),
        **NOTHING},
    # var/badges/20261026-182513/page.jpg (18:25): the badge menu open on our pad
    "golden/badge_menu_open-1026.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "honey": 1_256_329_995, "bar": 0.11,   # true fill 0.120
        # read '?,0?4,677' until 2026-10-26: a smeared fill pixel shifted the 1
        "pollen": ("OK", 1_044_677, 8_727_469),
        "side": "badges", "thumb": None, "hotbar": LOADOUT, "haste": (False, None),
        "make_honey": False, **NOTHING},
    # var/hotbar/hotbar-slot1-after-010059.jpg (01:00:59): the sprinkler press
    # refused, "You must be standing in a field to build a Sprinkler." (run log
    # 01:00:59 read the same); slot 1 shows its "0s" cooldown, 3/4/7 greyed x0
    "golden/sprinkler_refused-1026.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 0, 10_298_413), "honey": 1_245_723_507,
        "notice": (1565, 1033, 1903, 1053), "notice_kind": "not_in_field",
        "hotbar": (None,) + LOADOUT[1:], "haste": (True, None), "banner": None,
        "feed_rows": 0, **NOTHING},                                  # a blue bee, no pill
    # var/hotbar/hotbar-slot1-after-010105.jpg (01:01:05): one feed pill
    # "+37,500 Honey (from Honey Gift+)" over a red notice
    "golden/feed_honey_gift-1026.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 0, 10_298_413), "honey": 1_245_761_007,
        "notice": (1565, 1033, 1903, 1053), "notice_kind": "not_in_field",
        "feed_rows": 1, **NOTHING},                                  # a bee's blue is no pill
    # var/routes/attempt-1247/183617-cannon-settled.jpg: "E Fire the Red Cannon"
    "golden/red_cannon-1026.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 0, 8_727_469), "honey": 1_266_016_866,
        "banner": (853, 62, 283, 58), "cannon": True, "make_honey": False,
        "hotbar": LOADOUT, "haste": (False, None), "bear": None, "feed_rows": 0,
        "notice": None, **NOTHING},
    # var/routes/attempt-1247/184052-...home_mountain_top-24-walk-a4.jpg: walking
    # home with the bag OVER capacity (red bar), Haste x7
    "golden/haste_x7_bag_over-1026.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 8_930_814, 8_727_469), "honey": 1_271_346_016,
        "bar": 1.0, "hotbar": LOADOUT, "haste": (True, 7), "bear": None, "cannon": False,
        **NOTHING},
    # var/routes/attempt-1247/182625-...pepper_as_natro-06-walk-ds45.jpg: Black
    # Bear morph, Haste x1, two solid feed pills ("+5 Treats (from Cub Buddy)",
    # "+950 Honey (from Token Link)") under two faded ones
    "golden/black_bear_pepper-1026.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "honey": 1_256_341_812, "bar": 0.10,    # true fill 0.105
        "pollen": ("OK", 1_072_611, 10_211_138),                    # was '?,072,611'
        "hotbar": LOADOUT, "haste": (True, None), "bear": "black", "feed_rows": 2,
        **NOTHING},
    # var/routes/attempt-1247/183634-...mountain_top_as_natro-01-walk-a16.jpg:
    # gathering in Mountain Top (red and blue flowers), no feed, no notice
    "golden/mountain_top_flowers-1026.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 4_026, 12_300_276), "honey": 1_266_018_304,
        "bar": 0.0, "hotbar": LOADOUT, "haste": (False, None), "banner": None,
        "feed_rows": 0, "notice": None, **NOTHING},
    # var/incidents/20261026-175107-disconnect/149_t+10.8s.jpg: "Disconnected
    # ... (Error Code: 277)", Leave | Reconnect, over the blurred world
    "golden/disconnect_277-1026.jpg": {"anchors": NO_HUD,
        "screen": "MODAL", "pollen": ("NO_HUD", None, None),
        "modal_click": (1052, 627),                                  # Reconnect
        "reset": False, "dialog": False},
    # var/join/025019-ended_on_modal.png (2026-10-22 02:50): "Connection Failed
    # ... (Error Code: 279)", Cancel | Retry
    "golden/join_failed_279-1022.png": {"anchors": NO_HUD,
        "screen": "MODAL", "pollen": ("NO_HUD", None, None),
        "modal_click": (1052, 627),                                  # Retry
        "reset": False, "dialog": False},

    # --- golden/, copied 2026-10-27 (golden2) --------------------------------
    # Haste counts: each buff bar zoomed x2 and read by eye.
    # var/routes/attempt-1252/003625-natro_out_pepper-00-start.jpg: Haste x10
    # (two digits), on the pad with the empty-bag banner
    "golden/haste_x10-1027.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 0, 10_822_061), "haste": (True, 10),
        "make_honey": True, "cannon": False, "gushers": 0, "dialog": False},
    # attempt-1251/000643-...pepper_as_natro-03-walk-d32.jpg: Haste x2 with a
    # second "x2" (the blue flower buff) on the same bar, Black Bear; a
    # Gusher stands left of the player (zoomed)
    "golden/haste_x2_beside_x2-1027.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "haste": (True, 2), "bear": "black", "gushers": 1,
        "cannon": False, "dialog": False},
    # attempt-1251/000139-natro_out_ant_pass-00-start.jpg: Haste x5 drained to
    # its last rows; "E Make Honey" -- a blue E banner that is NOT the cannon's
    "golden/haste_x5_drained-1027.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 0, 10_822_061), "haste": (True, 5),
        "make_honey": True, "cannon": False, "gushers": 0},
    # attempt-1253/022159-natro_out_mountain_top_via_red_cannon-00-start.jpg:
    # Haste x8 half drained, "E Make Honey"
    "golden/haste_x8_drained-1027.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "haste": (True, 8), "make_honey": True, "cannon": False},
    # Red cannon. attempt-278/014836-...clover_via_red_cannon-04-camera-left.jpg
    # (2026-09-23): "E Fire the Red Cannon" at rest over a blue patch, the
    # case screenstate.red_cannon_prompt_box covers for banner.find
    "golden/red_cannon_over_blue-0923.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 0, 1_113_750), "honey": 10_011_134,
        "cannon": True, "gushers": 0, **NOTHING},
    # attempt-289/032108-from_hive_to_pine_tree_with_red_cannon-01-call-.jpg:
    # the same banner caught sliding in at y ~38, over the Honey pill
    "golden/red_cannon_sliding-0923.jpg": {"anchors": HUD_HERE,
        "cannon": True, "reset": False, "dialog": False},
    # The Roblox error dialog. var/incidents/<when>-disconnect/149_t+10.8s.jpg:
    # "Disconnected", Leave | Reconnect, under a "You've disconnected from
    # Voice Chat" toast at the top. 2026-10-13 07:19: "Roblox has shut down
    # the server for maintenance ... (Error Code: 275)"
    "golden/disconnect_275_toast-1013.jpg": {"anchors": NO_HUD,
        "screen": "MODAL", "pollen": ("NO_HUD", None, None), "reset": False,
        "dialog": False, "gushers": 0},
    # 2026-10-18 01:37: "... for being idle 20 minutes (Error Code: 278)"
    "golden/disconnect_278_toast-1018.jpg": {"anchors": NO_HUD,
        "screen": "MODAL", "pollen": ("NO_HUD", None, None), "reset": False,
        "dialog": False},
    # 2026-10-19 14:37: the same 278 over the hive
    "golden/disconnect_278_toast-1019.jpg": {"anchors": NO_HUD,
        "pollen": ("NO_HUD", None, None), "reset": False, "dialog": False},
    # 20261026-010404-disconnect/075_t+05.4s.jpg: the world 5 s before that
    # disconnect; one Gusher's cap behind a red token (zoomed)
    "golden/world_before_disconnect-1026.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 4_529_815, 14_643_056), "hotbar": LOADOUT,
        "gushers": 1, "reset": False, "dialog": False},
    # Night sky (vision/night). attempt-1082 (2026-10-19 11:30), one cannon
    # trip across the switch: open day sky in flight, then night 8 s later
    "golden/sky_day_flight-1019.jpg": {
        "screen": "IN_GAME", "sky": "day", "night": False},
    "golden/sky_night_landing-1019.jpg": {
        "screen": "IN_GAME", "sky": "night", "night": True},
    # attempt-539/080226-natro_out_spider_via_red_cannon-00-start.jpg: on the
    # pad by day (the flight 9 s later read the day sky, docs/pending/
    # nightsky.md); no sky in view
    "golden/pad_floor_false_night-0930.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 0, 3_234_375), "sky": None,
        "make_honey": True, "cannon": False},
    # var/memorymatch/20261013-024537/0062.7-turn05.jpg: Memory Match open,
    # the world dimmed behind it -- black, but not the night sky
    "golden/memory_match_dimmed-1013.jpg": {"sky": None, "night": False,
        "pollen": ("NO_HUD", None, None)},
    # Golden Gushers (vision/sprinkler), counted by eye on the full frame and
    # zoomed (datasets/sprinkler eyecheck, test runs: never trained on).
    # attempt-1036/215550-...sunflower_as_natro-01-walk-d16.jpg: two, left
    "golden/gushers_two-1016.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "gushers": 2, "hotbar": LOADOUT, **NOTHING},
    # attempt-1185/115530-...stump_as_natro-01-pause-.jpg: one, its post
    # behind the player (only the cap shows)
    "golden/gusher_behind_player-1022.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 160_638, 15_627_056), "gushers": 1,
        **NOTHING},
    # attempt-988/060535-...bamboo_as_natro-01-walk-d16.jpg: two, pale in the
    # sparkles, the left one behind a bubble
    "golden/gushers_pale_bamboo-1014.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 264_001, 7_174_248), "reset": False,
        "dialog": False},
    # attempt-1059/182047-...pine_tree_as_natro-01-walk-a16.jpg: two posts
    # side by side under sparkles
    "golden/gushers_sparkles_pine-1018.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "hotbar": LOADOUT, **NOTHING},
    # Typed token frames (TOKENS below), whole-frame answers too.
    # var/incidents/20261006-165403-token-nostart/120_t+08.7s.jpg
    "golden/tokens_blue_bursts-1006.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "hotbar": LOADOUT, "gushers": 0, "reset": False,
        "dialog": False},
    # var/incidents/235216-token/100_t+05.2s.jpg (2026-09-20)
    "golden/tokens_honey_haste_red-0920.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "pollen": ("OK", 243_685, 955_877), "honey": 4_073_487,
        "gushers": 0, **NOTHING},
    # var/incidents/20261007-145956-token-nostart/120_t+08.7s.jpg
    "golden/tokens_treat_honey_red-1007.jpg": {"anchors": HUD_HERE,
        "screen": "IN_GAME", "hotbar": LOADOUT, "gushers": 0, **NOTHING},
}

# (frame, reader, the RIGHT answer, why it is wrong today)
_RECONNECT = (1052, 627)
WRONG_TODAY = [
    # find_modal takes the Honey and Pollen pills (two light boxes, y 21) for
    # a modal's buttons and returns the Pollen pill's centre: on these world
    # frames dismiss_modal would click the pill (classify still says IN_GAME)
    ("golden/world_before_disconnect-1026.jpg", "modal_click", None,
     "the Honey/Pollen pills read as a modal's buttons"),
    ("golden/gushers_pale_bamboo-1014.jpg", "modal_click", None,
     "the Honey/Pollen pills read as a modal's buttons"),
    ("golden/tokens_blue_bursts-1006.jpg", "modal_click", None,
     "the Honey/Pollen pills read as a modal's buttons"),
    # ... and with a Disconnected dialog under the Voice Chat toast it never
    # reaches Reconnect: (447, 364) and (550, 98) are blurred world, and on
    # the 19th no modal at all (classify: UNKNOWN)
    ("golden/disconnect_275_toast-1013.jpg", "modal_click", _RECONNECT,
     "the Voice Chat toast / blurred world win over the dialog's buttons"),
    ("golden/disconnect_278_toast-1018.jpg", "modal_click", _RECONNECT,
     "the Voice Chat toast / blurred world win over the dialog's buttons"),
    ("golden/disconnect_278_toast-1019.jpg", "modal_click", _RECONNECT,
     "no modal found under the Voice Chat toast"),
    ("golden/disconnect_278_toast-1019.jpg", "screen", "MODAL",
     "classify reads UNKNOWN under the Voice Chat toast"),
    # the cannon banner mid-slide covers the pills: its E key is taken for a
    # modal button
    ("golden/red_cannon_sliding-0923.jpg", "screen", "IN_GAME",
     "a banner sliding over the pills reads as a modal"),
    ("golden/red_cannon_sliding-0923.jpg", "modal_click", None,
     "a banner sliding over the pills reads as a modal (its E key)"),
    # banner.find misses the cannon banner over blue (screenstate
    # red_cannon_prompt_box's note: 4 of 119 frames); the cannon read is right
    ("golden/red_cannon_over_blue-0923.jpg", "banner", (853, 62, 283, 58),
     "banner.find loses the banner's edge over a blue background"),
    # the pad's floor rule calls a sunny pad night (3.4% night green in shade)
    ("golden/pad_floor_false_night-0930.jpg", "night", False,
     "the floor rule's false night; no sky in view to overrule it"),
    # Gushers the colour gate never proposes (pale, behind a bubble), and a
    # post split into two boxes
    ("golden/gushers_pale_bamboo-1014.jpg", "gushers", 2,
     "the colour gate does not propose pale posts in sparkles"),
    ("golden/gushers_sparkles_pine-1018.jpg", "gushers", 2,
     "the left post's lower half is boxed again (3 boxes on 2 posts)"),
]

# THE TYPED TOKEN HEAD (vision/tokentypes, gather.token_types, off by default)
# on hand-boxed coins of the token dataset's TEST split (never trained on):
# (frame, (cx, cy, coin side) in frame px as coins.detect gives them, the kind
# read by eye on a 4x zoom of the crop, why it is wrong today or None).
# "unknown" is the right answer off a coin (a flower, the player, a leaf).
TOKENS = [
    ("golden/tokens_blue_bursts-1006.jpg", (856, 408, 148), "blue_boost", None),
    ("golden/tokens_blue_bursts-1006.jpg", (1135, 324, 74), "black_blue_burst", None),
    ("golden/tokens_blue_bursts-1006.jpg", (187, 422, 172), "blue_boost", None),
    ("golden/tokens_blue_bursts-1006.jpg", (1272, 307, 56), "black_red_burst",
     "a small far black/red burst is under tau"),
    ("golden/tokens_blue_bursts-1006.jpg", (730, 872, 74), "unknown", None),     # red flower
    ("golden/tokens_blue_bursts-1006.jpg", (998, 570, 259), "unknown", None),    # the player
    ("golden/tokens_honey_haste_red-0920.jpg", (218, 578, 225), "honey", None),
    ("golden/tokens_honey_haste_red-0920.jpg", (285, 435, 180), "haste", None),
    ("golden/tokens_honey_haste_red-0920.jpg", (660, 322, 120), "red_boost", None),
    ("golden/tokens_treat_honey_red-1007.jpg", (434, 495, 226), "item_treat", None),
    ("golden/tokens_treat_honey_red-1007.jpg", (1620, 747, 454), "honey", None),
    ("golden/tokens_treat_honey_red-1007.jpg", (247, 682, 226), "red_boost", None),
    ("golden/tokens_treat_honey_red-1007.jpg", (1737, 247, 226), "unknown", None),  # a leaf
]


@lru_cache(maxsize=None)
def _token_head():
    if not tokentypes.MODEL.exists():
        pytest.skip("no token-type model in this checkout")
    return tokentypes.Model.load()


def _token_kind(frame, coin) -> str:
    """The typed head's name for one coin, cut as coins.kinds_of cuts it."""
    cx, cy, side = coin
    s = coins.WORK_SCALE
    crop = coins.crop(coins.work_image(frame), cx * s, cy * s, side * s * coins.CROP_PAD)
    return _token_head().name(crop[None].astype("float32") / 255.0)[0]


@pytest.mark.parametrize("name, coin, want", [
    pytest.param(n, c, k, id=f"{n}:{c[0]},{c[1]}",
                 marks=[pytest.mark.xfail(reason=why, strict=True)] if why else [])
    for n, c, k, why in TOKENS])
def test_typed_token_head(name, coin, want):
    assert _token_kind(_frame(name), coin) == want


def _cases():
    for name, answers in GOLDEN.items():
        for reader, want in answers.items():
            yield pytest.param(name, reader, want, id=f"{name}:{reader}")


def _check(name, reader, want):
    if reader in OCR and shutil.which("tesseract") is None:
        pytest.skip("tesseract is not installed")
    got = READERS[reader](_frame(name))
    if isinstance(want, float):
        assert got == pytest.approx(want, abs=0.01), (name, reader, got)
    else:
        assert got == want, (name, reader, got)


@pytest.mark.parametrize("name, reader, want", list(_cases()))
def test_golden(name, reader, want):
    _check(name, reader, want)


@pytest.mark.parametrize("name, reader, want, why", [
    pytest.param(*w, id=f"{w[0]}:{w[1]}", marks=pytest.mark.xfail(reason=w[3], strict=True))
    for w in WRONG_TODAY])
def test_wrong_today(name, reader, want, why):
    _check(name, reader, want)


def test_every_reader_is_checked_on_some_frame():
    used = {r for answers in GOLDEN.values() for r in answers}
    assert used == set(READERS), set(READERS) - used


def test_the_frames_stay_out_of_the_public_export():
    """They are the owner's screen (export_public.EXCLUDE)."""
    import fnmatch
    tool = (FIX.parents[1] / "tools" / "export_public.py")
    if not tool.exists():
        pytest.skip("export_public.py is not in this checkout")
    text = tool.read_text(encoding="utf-8")
    for name in GOLDEN:
        path = f"tests/fixtures/{name}"
        ext = path.rsplit(".", 1)[1]
        assert f'"tests/fixtures/*.{ext}"' in text, ext
        assert fnmatch.fnmatch(path, f"tests/fixtures/*.{ext}"), path

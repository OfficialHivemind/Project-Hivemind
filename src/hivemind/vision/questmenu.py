"""Reading the player's OWN quests off the screen, instead of a wiki table.

THE OWNER'S IDEA, AND IT IS A BETTER ONE THAN MINE: read the quests the account
holds on joining.

It is better because a wiki table is generic and a screen is specific. Scraping
`quests.yaml` tells the bot what quests EXIST; reading the quest menu tells it
which ones THIS ACCOUNT holds, how far along each is, and what is left. One is
a reference book, the other is the actual state of the game -- and this project
has already paid for the difference once, when a map built from a descriptor
that could not tell places apart produced thirteen imaginary "places".

WHY IT IS FEASIBLE. The vision model reads game text accurately when it is
shown text that is really there: MEASURED, it transcribed a reward pill as
"+590 Honey (from Pumpkin Patch)" exactly, from 20-pixel-tall glyphs. A quest
panel is far larger. The hard part was never the reading.

THE HARD PART IS OPENING IT SAFELY, and the rule that governs this file:

    NEVER PRESS A KEY TO OPEN A MENU, AND NEVER GUESS A BUTTON.

The Roblox escape menu carries Log Out and Leave as ordinary activatable
tiles, and this bot has already opened a bear's dialogue by pressing the
interact key where it believed the hive was. So the quest menu is opened by
CLICKING A BUTTON WHOSE POSITION WAS MEASURED, the result is VERIFIED to be the
quest menu before anything is read, and it is closed the same way it was opened.
If the panel that appears is not the quest menu, this backs out and says so
rather than pressing anything else.

MEASURED HUD GEOMETRY, from a real 1920x1080 frame: six buttons in a row at
y = 128, starting at x = 27 and spaced 56 px apart.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..telemetry import readhealth

# The row of white HUD buttons under the buff tray, measured from a real frame.
BUTTON_Y = 128
BUTTON_X0 = 27
BUTTON_STEP = 56
BUTTON_COUNT = 6

# What each button opens, confirmed from the owner's screenshots.
BUTTONS = ("inventory", "quests", "bees", "badges", "settings", "robux_shop")

# Which one opens the quests. NOT YET CONFIRMED -- index 1 is the map-with-a-
# question-mark, which is the best candidate from looking at the icons, but a
# guess about which button to click is exactly what this module refuses to
# make. `confirmed` stays False until someone verifies it, and `button_for`
# will not hand back an unconfirmed index unless explicitly allowed.
QUEST_BUTTON_INDEX = 1
# CONFIRMED 2026-09-20 from the owner's own screenshots: the second HUD button,
# the map with a question mark, opens the quest list. The other five are, in
# order: inventory (egg), quests, bees (smiley), badges (rosette), settings
# (gear) and the Robux shop (money bag).
QUEST_BUTTON_CONFIRMED = True

# Words that say the panel on screen really is the quest menu. Checked before
# anything is read, so a mis-click reads nothing rather than reading garbage.
#
# THE HEADER WORD IS NOT ON SCREEN, which the first live read established. The
# panel that opened transcribed as
#
#     Optimizing Abilities
#     Discover 19 Bee Types. Complete.
#     Collect 820,020 Blue Pollen
#
# -- an entirely real quest, correctly read, and rejected because the literal
# word "quest" appears nowhere in it. The menu shows the quest's own text, not
# a title bar.
#
# So the test is on the SHAPE of quest text instead: a requirement line and a
# progress marker. Two distinct markers are required, not one, because a
# single common verb like "collect" appears on plenty of other panels, and
# reading the wrong panel as a quest list would write invented objectives into
# the bot's plans. Two is cheap for a real quest list -- every quest has both
# a thing to do and a state -- and unlikely anywhere else.
QUEST_WORDS = ("quest", "quests", "objective", "objectives")

# WHAT A REQUIREMENT LINE LOOKS LIKE. Used to tell a requirement from a quest
# TITLE, so it must contain only words that describe a thing to do or a state
# of doing it -- never the name of a bear.
#
# IT USED TO CONTAIN THE BEARS and that broke the parse on the owner's own
# quest list. "Honey Bee's Honey Hunt" and "Polar Bear: Candied Beetles" are
# both quest TITLES, both matched "honey bee" and "polar bear", and both were
# therefore filed as requirements of the quest above them -- so two of his
# four quests vanished into a third and the GUI showed their steps under the
# wrong heading. The bears belong in the panel-identification list below and
# nowhere else.
REQUIREMENT_WORDS = (
    # what a quest asks for
    "collect", "discover", "gather", "defeat", "deliver", "craft",
    "talk to", "reach", "give", "find", "use",
    # how far along it is
    "complete", "completed", "in progress", "claim reward",
)

# Only for `looks_like_quests`: does this panel look like a quest list at all?
# A bear's name is strong evidence of that and useless for anything else.
QUEST_SHAPE_WORDS = REQUIREMENT_WORDS + (
    "make", "reward",
    "black bear", "brown bear", "panda bear", "polar bear", "science bear",
    "spirit bear", "mother bear", "honey bee", "bucko", "riley",
)

# How many distinct shape markers make a panel a quest list.
QUEST_SHAPE_MINIMUM = 2

# A panel is large. If what appeared covers less than this, it is not a menu.
MIN_PANEL_FRACTION = 0.10


@dataclass(frozen=True)
class Quest:
    """One quest as the screen describes it."""
    giver: str = ""
    name: str = ""
    requirements: tuple[str, ...] = ()
    done: bool = False

    def describe(self) -> str:
        head = f"{self.giver}: {self.name}" if self.giver else self.name
        if self.requirements:
            head += " — " + "; ".join(self.requirements[:3])
        return head + (" [done]" if self.done else "")


def button_at(index: int, frame=None) -> tuple[int, int]:
    """Where a HUD button is, scaled to the frame. Measured at 1920x1080."""
    scale = 1.0 if frame is None else frame.shape[0] / 1080.0
    return (int((BUTTON_X0 + BUTTON_STEP * index) * scale),
            int(BUTTON_Y * scale))


# THE BUTTON IS LOOKED AT BEFORE IT IS CLICKED. MEASURED 2026-10-14 18:15
# (run-1005, var/quest_reads/close-181529-before.jpg): a Roblox promo toast,
# "You've got 15% off" with a blue "Shop now" button, sat over the HUD row at
# x 77-287, y 65-165. The quest click at (83, 128) hit its edge (nothing
# opened) and the badge click at (195, 128) hit "Shop now" -- Roblox's Robux
# Shop opened over the world, nothing the game's own buttons could close, and
# every walk leg after pushed against it until the run stopped. So a HUD button
# is clicked only when the white shape at its place matches its own template
# (data/templates/ui/hud_<name>.png, a 56x56 mask of the cream HUD white) by
# BUTTON_IOU and beats every other button's place by BUTTON_MARGIN -- the test
# act/autojelly first made for the gear. A refusal clicks nothing.
TEMPLATES = __import__("pathlib").Path(__file__).resolve().parents[3] / "data" / "templates" / "ui"
TEMPLATE_FILES = {"quests": "hud_quests.png", "badges": "hud_badges.png",
                  "settings": "hud_settings_gear.png"}
BUTTON_HALF = 28
BUTTON_IOU, BUTTON_MARGIN = 0.7, 0.15
FRAME_HW = (1080, 1920)


def _white(frame, cx: int, cy: int):
    """The cream HUD white (~(225,235,235): S < 70, V > 190) in the 56x56 cell
    round (cx, cy), or None off the frame's edge."""
    import cv2
    import numpy as np
    cell = frame[cy - BUTTON_HALF:cy + BUTTON_HALF, cx - BUTTON_HALF:cx + BUTTON_HALF, :3]
    if cy < BUTTON_HALF or cx < BUTTON_HALF or cell.shape[:2] != (2 * BUTTON_HALF,) * 2:
        return None
    hsv = cv2.cvtColor(np.ascontiguousarray(cell), cv2.COLOR_BGR2HSV)
    return (hsv[..., 1] < 70) & (hsv[..., 2] > 190)


def button_check(frame, name: str, template=None) -> tuple[bool, float, float]:
    """(button `name` shows plainly where measured, its IoU, the best other
    button's IoU). No template for `name` is a refusal."""
    if frame is None or tuple(frame.shape[:2]) != FRAME_HW:
        return False, 0.0, 0.0
    if template is None:
        import cv2
        t = (cv2.imread(str(TEMPLATES / TEMPLATE_FILES[name]), cv2.IMREAD_GRAYSCALE)
             if name in TEMPLATE_FILES else None)
        if t is None:
            return False, 0.0, 0.0
        template = t > 127

    def iou(i: int) -> float:
        m = _white(frame, *button_at(i))
        if m is None:
            return 0.0
        return float((m & template).sum()) / max(1, int((m | template).sum()))
    me = BUTTONS.index(name)
    mine = iou(me)
    other = max(iou(i) for i in range(1, len(BUTTONS)) if i != me)
    readhealth.note(f"{name} button", mine >= BUTTON_IOU and mine - other >= BUTTON_MARGIN, mine)
    return mine >= BUTTON_IOU and mine - other >= BUTTON_MARGIN, mine, other


# ROBLOX'S OWN OVERLAYS, which no game button closes, each found by a template
# cut from run-1005's frames and closed only by ITS OWN X (never a key: Escape
# is Roblox's menu with Leave on it). (template, the X's offset from the
# template's top-left). Scores MEASURED: 1.00 on the source frames and 0.99 on
# all 36 route frames of run-1005 that set off under the shop; at most 0.55
# (shop) and 0.68 (promo) over 500 other saved route and badge frames.
#   shop  -- the Robux Shop ("X Shop", Top picks, Buy ...), var/badges/
#            20261014-181516/page.jpg, header at (562, 255), its X at (578, 272)
#   promo -- the "You've got 15% off" toast's blue "Shop now" button,
#            var/quest_reads/close-181529-before.jpg at (88, 115); the toast's
#            X at (263, 88). The button itself is never clicked: it opens the shop.
OVERLAYS = {"shop": ("roblox_shop_header.png", (16, 17)),
            "promo": ("roblox_promo_shop_now.png", (175, -27))}
OVERLAY_SCORE = 0.85


def roblox_overlay(frame) -> tuple[str, tuple[int, int]] | None:
    """(which Roblox overlay shows, where its X is), or None. A 1920x1080 BGR
    frame; about 20 ms a template."""
    if frame is None or tuple(frame.shape[:2]) != FRAME_HW:
        return None
    import cv2
    gray = cv2.cvtColor(frame[..., :3], cv2.COLOR_BGR2GRAY)
    for kind, (name, (dx, dy)) in OVERLAYS.items():
        t = cv2.imread(str(TEMPLATES / name), cv2.IMREAD_GRAYSCALE)
        if t is None:
            continue
        _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))
        if score >= OVERLAY_SCORE:
            return kind, (x + dx, y + dy)
    return None


def quest_button(frame=None, allow_unconfirmed: bool = False):
    """Where to click for quests, or None while that is still a guess."""
    if not QUEST_BUTTON_CONFIRMED and not allow_unconfirmed:
        return None
    return button_at(QUEST_BUTTON_INDEX, frame)


# THERE IS NO PIXEL TEST FOR "A MENU IS OPEN" HERE, AND THAT IS DELIBERATE.
#
# The first version of this file had one: menus are flat, so find a large flat
# region. MEASURED against a real gameplay frame, it returned True -- because
# Roblox worlds are flat-shaded and large uniform areas are everywhere. It
# would have fired on every frame in the game.
#
# It cannot be calibrated either, because nothing in this project has ever
# captured a frame with the quest menu open. Shipping a threshold fitted to no
# data is exactly the mistake that produced thirteen imaginary places
# (docs/DESIGN.md 8b), so the check is done by READING instead: transcribe
# what appeared and see whether it says "quest". That is slower and it is
# honest, and `looks_like_quests` is the whole of it.
#
# TO DO BETTER: capture one frame with the menu open and measure it.


def looks_like_quests(text: str) -> bool:
    """Does the transcribed panel really look like a quest list?

    Either it names itself, or it has the shape of quest text: at least
    `QUEST_SHAPE_MINIMUM` distinct markers of "a thing to do" and "how far
    along it is". See QUEST_WORDS for why naming alone was not enough.
    """
    low = " ".join((text or "").lower().split())
    if not low:
        return False
    if any(word in low for word in QUEST_WORDS):
        return True
    hits = {word for word in QUEST_SHAPE_WORDS if word in low}
    return len(hits) >= QUEST_SHAPE_MINIMUM


# "142,504/820,020" -- the menu draws this UNDER the requirement, on its own
# line, so the transcription has it on its own line too.
_PAIR = re.compile(r"^([\d,.]+)\s*/\s*([\d,.]+)$")

# A BARE SHARE, the nectar steps' progress on its own line. MEASURED
# 2026-10-19..21 (night logs): "Collect 6 Hours of Satisfying Nectar.; (0%)"
# (29 lines) and "...Invigorating Nectar.; 44m06s (18%)" -- each filed as a
# step of its own, so the quest's reward was split over one step too many.
_BARE_SHARE = re.compile(r"^(?:[\dhms]+\s*)?\(\d{1,3}%\)$")

# A LINE THAT IS ONLY A VERDICT, e.g. "Complete!" or "Complete! Talk to
# Science Bear." The quest menu puts it on its own line whenever the
# requirement above fills the width; see merge_progress.
_BARE_DONE = re.compile(r"^complete[!.]?(?:\s+talk\s+to\s+[a-z ]+[.!]?)?$",
                        re.IGNORECASE)
# "complete" appearing anywhere, used to avoid folding a second verdict onto a
# line that already has one.
_DONE_WORD = re.compile(r"\bcomplete\b", re.IGNORECASE)
# The first number on a requirement line: the target it states in words.
_FIRST_NUMBER = re.compile(r"([\d][\d,.]*)")


def number(text: str | None) -> int | None:
    """A count as the menu writes it, or None.

    THOUSANDS SEPARATORS COME BACK BOTH WAYS. The game draws "636,363" and the
    model transcribed it "636.363" on the owner's own quest list, twice in the
    same panel. A dot followed by EXACTLY three digits, one or more times, is
    unambiguously a thousands group -- no quest target is fractional and no
    fraction has three digits in this menu -- so both spellings are read as
    the same number. Anything else is None rather than a guess.
    """
    if text is None:
        return None
    raw = str(text).strip().replace(",", "")
    if not raw:
        return None
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        raw = raw.replace(".", "")
    try:
        return int(raw)
    except ValueError:
        return None


def stated_target(line: str) -> int | None:
    """The count a requirement line asks for: its first number."""
    found = _FIRST_NUMBER.search(line or "")
    return number(found.group(1)) if found else None


def merge_progress(lines) -> list[str]:
    """Fold a bare "got/total" line onto the requirement above it.

    THE BUG THIS FIXES, measured from var/quests.json on 2026-09-21:

        Collect 6,000,000 Pollen
        1,497,207/6,000,000

    Two lines. Everything downstream reads ONE line at a time, and a line with
    no letters in it is not a requirement, so the pair was dropped and the
    requirement was left with a target and no progress. The owner saw the
    result in the GUI and said so: "quests section ive done parts of them but
    it shows 0/(whatever value is on quest) on them even tho ive done some".

    THE PAIR IS ONLY BELIEVED WHEN ITS TOTAL MATCHES THE STATED TARGET, which
    is the same rule `brain/questneeds._progress` already applies within a
    line, and it is here for the same reason. The backpack HUD sits behind the
    menu and leaks into the transcription: the same read ended

        Collect 16 Rhino Beetles. Complete! Talk to Polar Bear.
        12670/1072500

    and 1,072,500 is the backpack, not the beetles. Sixteen does not match it,
    so it is dropped. All eight genuine pairs in that read do match.

    A BARE "Complete!" LINE IS FOLDED THE SAME WAY, for the same reason.
    MEASURED 2026-09-23 from `var/quests.json`, the "Ready For Infrared"
    quest as this account actually holds it:

        Discover 20 Bee Types.
        Complete! Talk to Science Bear.
        Collect 1818181 Red Pollen.
        Complete! Talk to Science Bear.
        Collect 313 Red Boost Tokens.
        Complete! Talk to Science Bear.

    The menu puts the verdict on its own line whenever the requirement fills
    the width. `brain/questneeds._progress` looks for "complete" IN the
    requirement line, so it saw none of these and read all six as untouched:
    the planner believed 1.8 million red pollen and 313 Red Boost tokens were
    still wanted when the quest had been finished and was waiting to be handed
    in. Six requirements' worth of field bias, from a line break.

    Unlike a "got/total" pair there is nothing to cross-check a "Complete!"
    line against, so the safeguard is different: it is folded only onto a line
    that ASKS FOR SOMETHING (`asks_for_something`) and does not already carry
    its own progress. A stray "Complete!" under a quest TITLE is dropped.
    """
    out: list[str] = []
    for raw in lines or ():
        line = " ".join(str(raw).split())
        if not line:
            continue
        if _BARE_SHARE.match(line):
            continue            # a nectar step's "44m06s (18%)": no count to fold
        if _BARE_DONE.match(line):
            if (out and asks_for_something(out[-1])
                    and "/" not in out[-1]
                    and not _DONE_WORD.search(out[-1])):
                out[-1] = f"{out[-1]} {line}"
            # else: it belongs to a title or to a line that already said so.
            continue
        pair = _PAIR.match(line)
        if pair is None:
            out.append(line)
            continue
        total = number(pair.group(2))
        if not out or total is None:
            continue
        target = stated_target(out[-1])
        if target is not None and target == total and "/" not in out[-1]:
            out[-1] = f"{out[-1]} {line}"
        # else: it belongs to something else on screen. Dropped, not guessed.
    return out


# VERBS A STEP OPENS WITH that REQUIREMENT_WORDS leaves out, matched as the
# line's FIRST WORD only: as substrings "earn" is in "Learning" and "raise" in
# "Praise", and either would file a quest's title as a step. MEASURED
# 2026-09-30 on the first whole-list read (act/questscroll,
# var/quest_reads/scroll-20260930-225820): "Raise 6 Bees to Level 6.", "Feed
# 100 Treats to your Bees.", "Feed 25 Sunflower Seeds to your Bees." and
# "Obtain 1 Red Drive." (White, Blue, Glitched), with "Earn 10 Hotshot Badges"
# on the Science Bear's quest before -- each read as a title, so "Search For
# Sunflower Seeds" split into steps posing as quests and "Repairing Robo Bear"
# vanished.
# And MEASURED 2026-10-21 18:59 (research, var/quests.json against its read):
# "Share 50 Jelly Bean Tokens. 6/50" and "Purchase 1 Beequip from Dapper
# Bear's Shop. 0/1" were dropped, and "Match 5 Pairs ...", "Equip 5
# Beequips" and "Chase 256 Fireflies" filed as quests with no steps -- which
# also mispriced the real quests' steps. No quest title (quest_rewards.yaml,
# 316) opens with any of these.
# And MEASURED 2026-10-19..21 (runs 1067-1165): "Catch 10 Pink Bloom
# Petals." (25 lines), "Catch 50 Green Bloom Petals.", "Pop 100 Bubbles." and
# "Pop 25 Puffshrooms." filed as quests too. No title opens with either.
LEADING_VERBS = ("raise", "feed", "obtain", "earn",
                 "share", "match", "purchase", "equip", "chase", "catch", "pop")

# A STEP ENDS WITH A FULL STOP, A TITLE NEVER DOES: none of the 316 titles in
# quest_rewards.yaml (read 2026-10-21), and every line filed as a quest in the
# night logs of 2026-10-19..21 that ended in one was a step -- "Get a Score
# of 75 in the Ant Challenge." among them, whose "Get" also opens "Get Red-y".


def asks_for_something(line: str) -> bool:
    """Is this a requirement rather than a quest title? See REQUIREMENT_WORDS
    and LEADING_VERBS."""
    low = " ".join((line or "").lower().split())
    if any(word in low for word in REQUIREMENT_WORDS):
        return True
    first = low.split(" ", 1)[0].strip(".,:;!-*•") if low else ""
    return first in LEADING_VERBS


def parse(text: str) -> list[Quest]:
    """Turn a transcribed quest panel into quests.

    Deliberately forgiving about layout and strict about inventing: a line it
    cannot make sense of is dropped, never guessed at.
    """
    quests: list[Quest] = []
    giver = ""
    name = ""
    reqs: list[str] = []

    def flush():
        nonlocal name, reqs
        # A HEADING WITH NOTHING TO DO UNDER IT IS NOT A QUEST. The panel
        # transcription runs on past the quest list into whatever else is on
        # screen, and on the owner's own read that was
        #
        #     Server Version: 624
        #     VIP Server commands: /kick playerName /ban playerName ...
        #
        # which became a quest called "Server Version: 624" with the command
        # list as its requirement, and duly appeared in the GUI's quest panel.
        # A real quest always asks for something; this is how the tail of the
        # screen is kept out without a list of things to ignore.
        #
        # A TITLE IS NOT REQUIRED, A REQUIREMENT IS. Some layouts give the
        # bear's name and then go straight to the steps -- "Black Bear's
        # Quest" / "- Collect 100 pollen" -- with no title line at all, and
        # keying on the title dropped those and kept the bare heading above
        # them instead.
        if (name or giver) and any(asks_for_something(r) for r in reqs):
            quests.append(Quest(giver=giver, name=name,
                                requirements=tuple(merge_progress(reqs))))
        name, reqs = "", []

    for raw in (text or "").splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        low = line.lower()
        if low.endswith("'s quest") or low.endswith("quest:"):
            flush()
            giver = line.split("'")[0].strip()
            continue
        if line.startswith(("-", "*", "•")):
            reqs.append(line.lstrip("-*• ").strip())
            continue
        # A BARE "got/total" BELONGS TO THE LINE ABOVE IT, not to a new quest.
        # The menu draws progress under the requirement it measures. Kept here
        # verbatim and folded in by `merge_progress` at flush time, which is
        # where the total can be checked against the stated target.
        if _PAIR.match(line):
            reqs.append(line)
            continue
        # A LINE THAT ASKS FOR SOMETHING IS A REQUIREMENT, NOT A TITLE, even
        # when it is short and starts with a letter. The first real panel read
        # was
        #
        #     Optimizing Abilities
        #     Discover 19 Bee Types. Complete.
        #     Collect 820,020 Blue Pollen
        #
        # which is ONE quest with two requirements. Length alone made all
        # three look like titles, and reporting three quests where the screen
        # shows one is inventing structure that is not there.
        if (name and asks_for_something(line)) or ((name or giver) and line.endswith(".")):
            reqs.append(line)
        elif len(line) <= 60 and not any(ch.isdigit() for ch in line[:3]):
            flush()
            name = line
        else:
            reqs.append(line)
    flush()
    return quests

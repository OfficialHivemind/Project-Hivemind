"""Learning what a token looks like from what happens when one is walked to.

THE PROBLEM IT ANSWERS. The token detector's confidence is, measured, a bee
score: on the hand-labelled field frame the player's own bees read 0.72-0.99
and the nine real tokens 0.60-0.70 (docs/GAPS.md #5). Telling them apart
needs a classifier, a classifier needs labels, and nobody is going to sit and
label crops. The game labels them for us: walking onto a token CHANGES A
COUNTER -- the honey figure jumps for a honey token, the Haste stacks go up
for a haste token, a buff's stack digit rises, the pollen figure takes a lump
it would not have taken from gathering alone -- and walking onto a bee
changes nothing. So every chase is a lesson: the crop of the thing chased,
taken before the walk, and afterwards the verdict from the counters.

WHAT IT REFUSES TO CONCLUDE. A crop is labelled "nothing" (not a token) only
when the counter that kind SHOULD have moved was readable before and after
and did not move. A honey-coloured target that leaves the honey figure alone
after being reached is a bee or a number; a target of a kind whose effect
this cannot see -- a buff's first stack shows no digit, an ability token
shows nothing on the bar -- is "unknown", and unknown teaches nothing. Better
a smaller school than a wrong one.

THE CLASSIFIER is deliberately small: a HOG of the 48x48 crop plus an HSV
histogram, k-nearest neighbours (OpenCV's), retrained from the lessons on
disk whenever new ones arrive. It says nothing until it has MIN_LESSONS of
EACH class, and then only a probability, which the brain gates on
(`brain/tokenbrain`). Every lesson is kept as a PNG and a JSON line under
var/school/, so the set can be inspected, corrected or replayed.
"""
from __future__ import annotations

import collections
import json
import pathlib
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

CROP = 48
# THE WIDE CROP, for retraining the coin detector (vision/coinnet). MEASURED
# 2026-10-20: coins in the labelled frames are a median 112 px across, so the
# 48 px crop shows a coin's middle, never the whole coin with its rim that the
# detector sees -- 2,115 'collected' lessons were unusable for it. Kept
# beside the small one as a JPEG (~15 KB) in crops-wide/; the kNN above still
# reads only the 48 px crop.
WIDE_CROP = 192
MIN_LESSONS = 25
# WHERE THE LESSONS LIVE, under var/. A school is only as good as the detector
# whose chases taught it, and the lessons in var/school/ are the glyph
# detector's -- a detector that found bees (vision/tokens). MEASURED
# 2026-09-28 on the 174 sure coins labelled in data/models/coin_labels.json:
# that school gated 27% of real coins below SCHOOL_GATE_BELOW (tokenbrain),
# and 20% of random ground; median P 0.20 for both -- it cannot tell a coin
# from grass. The coin detector starts a school of its own here, and says
# nothing until it has MIN_LESSONS of each kind; var/school/ is left as it is.
SCHOOL_DIR = "school-coins"
# A pollen rise during a chase counts as a token's lump only when it exceeds
# what the pattern's own rate would have gathered in that time by this factor
# AND by this floor -- gathering never stops while the character detours, so
# the background rise has to be discounted, not ignored.
POLLEN_LUMP_FACTOR = 3.0
POLLEN_LUMP_MIN = 500
# HONEY TRICKLES TOO. MEASURED 2026-09-22 22:23 on the first live chases: the
# HUD read "+5/sec" to "+37/sec" honey in the field (bee abilities), and the
# first three chases -- of things called fuzz_bombs and rain_cloud -- were
# each judged "collected: honey rose by 273 / 345 / 97". That is the trickle
# over two to four seconds, not a token. Same rule as pollen: a rise counts
# only beyond the watched rate by the factor and a floor.
HONEY_LUMP_FACTOR = 3.0
HONEY_LUMP_MIN = 200
# THE SMALLEST HONEY TOKEN THE HUD HAS SHOWN. MEASURED in var/school/
# lessons.jsonl (2026-09-22..27, a trickle of 60-110 honey a second): of 153
# honey lumps beyond the trickle the 5th percentile was 253, and the smallest
# for a honey kind 247. A "nothing" for a honey kind needs a bar a token this
# small would have cleared (`judge`).
HONEY_TOKEN_SMALLEST = 250
# How long the pollen figure is watched to estimate the background rate.
RATE_WINDOW_S = 30.0
# Kinds by what their collection visibly changes. Anything not listed has an
# effect this cannot see on the HUD and is never labelled "nothing".
HONEY_KINDS = frozenset({"honey", "token_link"})
HASTE_KINDS = frozenset({"haste"})
# A HASTE TOKEN REFILLS THE SQUARE (DESIGN 8dx). The reader now sees a
# drained Haste (vision/buffs), so the snapshot before a chase often has one
# up, and a pickup then shows as its square filling again while the count
# may not move: at x10, or where the count is unreadable (no template for 7,
# 8 or 0). MEASURED on the drain scan of every saved route and homing frame:
# of 1,513 pairs of consecutive frames <= 5 s apart with the Haste read, 26
# have its drain line rise 4-30 rows and the other 1,487 at most 3 (the
# line's jitter); the count alone called 2 of the 26 "nothing" (attempt 244
# at 20:25:39, 344 at 00:26:44), and with the square's time as well only
# 344's is not collected -- its line before is under DRAIN_MIN_LIGHT_ROWS,
# so it is "unknown" now. A rise of the time left by this much (3.8 rows at
# 1.9 a second) is a refill; no pair without one rises by more than 1.6 s.
HASTE_REFILL_S = 2.0
POLLEN_LUMP_KINDS = frozenset({"baby_love", "puppy_love"})
# Stack-count kinds: a rise in ANY readable stack digit is positive evidence;
# their first stack shows no digit, so their absence proves nothing.
STACK_KINDS = frozenset({"focus", "inspire", "bomb_sync", "red_boost", "white_boost",
                         "tabby_love", "scratch", "rage", "mark_surge", "melody"})
# THE BUFF BAR RISES ON ITS OWN, like the honey and pollen figures. MEASURED
# in var/school/lessons.jsonl, 2026-09-26 (5,801 lessons, audit brain F9): of
# 837 "collected" labels, 519 rested on a stack rise alone. For kind=haste,
# 563 chases moved nothing, 56 moved haste, and 112 were "collected" by a
# stack rise while haste itself did not move; honey 324 / 30 / 56 the same
# way -- a stack rise came with 12-15% of chases, whatever was chased. So a
# kind with its own counter (HONEY_KINDS, HASTE_KINDS, POLLEN_LUMP_KINDS) is
# judged by that counter only, and a stack rise counts for any other kind
# only beyond the watched background rise, by the same factor as the lumps
# (POLLEN_LUMP_FACTOR, HONEY_LUMP_FACTOR). Unwatched, a stack rise proves
# nothing (as with honey). The 239 old labels this rules out -- haste 112,
# honey 56, token_link 38, baby_love 26, puppy_love 7 -- stay in the file
# and teach nothing (`_legacy_verdict`).
STACK_LUMP_FACTOR = 3.0
OWN_COUNTER_KINDS = HONEY_KINDS | HASTE_KINDS | POLLEN_LUMP_KINDS
STACK_EVIDENCE = ("the buff bar's stacks", "a buff's stacks rose", "a buff appeared")
GATE_BELOW = 0.3
# PHANTOM SPOTS: a 40 px screen cell where chases start and almost never
# arrive. MEASURED 2026-10-21 on 21,078 lessons (runs 531-1167): 7 cells had
# >= 50 chases under 15% reached, 1,106 chases -- six of them runs 539-540,
# honey seen ONCE (confidence 0.5) chased while a honey quest led, so only
# lessons at confidence 1.0 count. Since run 1050 the worst old cells were
# reached 28 of 28: a table learned before 1050 would have skipped 57 reached
# chases (10 collected) after it, hence the window of the latest lessons only
# (~23 h at 128 chases an hour). Today no cell qualifies; it is a guard.
PHANTOM_CELL_PX = 40
PHANTOM_MIN_CHASES = 50
PHANTOM_MAX_REACH = 0.15
PHANTOM_CONFIDENCE = 0.95       # a detector this sure is chased anyway
PHANTOM_WINDOW = 3000


def counts_for_phantom(evidence: str, outcome: str) -> bool:
    """A lesson that says whether the chase reached its token: NEVER, or a
    reached one judged "collected" / "nothing"."""
    return evidence == NEVER or outcome in ("collected", "nothing")
NEVER = "the chase never reached it"
HONEY_NOTHING = "reached it and the honey figure took no lump beyond its trickle"


@dataclass(frozen=True)
class Snapshot:
    """The counters that a collected token can move, at one moment."""
    at: float
    pollen: int | None
    honey: int | None
    haste_present: bool
    haste_stacks: int | None
    stacks: dict = field(default_factory=dict)      # slot -> readable stack count
    # Seconds of the Haste left by its drain line (vision/buffs remaining_s);
    # None: absent, or the line could not be read.
    haste_left: float | None = None


def snapshot(frame, pollen: int | None, honey: int | None, at: float | None = None) -> Snapshot:
    """Read the buff bar off `frame`; pollen and honey come from the HUD reader."""
    from ..vision import buffs
    counts: dict = {}
    haste_present, haste_stacks, haste_left = False, None, None
    if frame is not None:
        try:
            for i, icon in enumerate(buffs.slots(frame)):
                n = buffs.stacks(icon)
                if n is not None:
                    counts[i] = n
            h = buffs.haste(frame)
            haste_present, haste_stacks, haste_left = h.present, h.stacks, h.remaining_s
        except Exception:
            pass
    return Snapshot(at=time.monotonic() if at is None else at, pollen=pollen, honey=honey,
                    haste_present=haste_present, haste_stacks=haste_stacks, stacks=counts,
                    haste_left=haste_left)


def judge(kind: str, before: Snapshot, after: Snapshot, arrived: bool,
          pollen_rate: float | None, honey_rate: float | None = 0.0,
          stack_rate: float | None = None) -> tuple[str, str]:
    """`(outcome, evidence)`: "collected", "nothing" or "unknown", and why.

    `honey_rate` is the honey trickle per second watched before the chase;
    None means it could not be watched, and then a honey rise proves nothing.
    `stack_rate` is the buff bar's own rise per second, the same way (see
    STACK_LUMP_FACTOR).
    """
    if not arrived:
        return "unknown", NEVER
    seconds = max(0.0, after.at - before.at)
    # A KIND WITH ITS OWN COUNTER IS JUDGED BY IT; any other kind by any
    # counter, whatever it was called (the kind table can misname a token).
    allowed = ({"honey"} if kind in HONEY_KINDS else
               {"haste"} if kind in HASTE_KINDS else
               {"pollen"} if kind in POLLEN_LUMP_KINDS else
               {"honey", "haste", "stacks", "pollen"})
    honey_watched = (before.honey is not None and after.honey is not None
                     and honey_rate is not None)
    if honey_watched and "honey" in allowed:
        delta = after.honey - before.honey
        expected = honey_rate * seconds
        if delta > max(HONEY_LUMP_MIN, HONEY_LUMP_FACTOR * expected):
            return "collected", (f"honey rose {delta:,} in {seconds:.1f}s against "
                                 f"{expected:,.0f} expected from the trickle")
    # A Haste that was up already shows a pickup as its square refilling
    # (HASTE_REFILL_S), and as a count that rose only where the count after
    # is readable: an unreadable one before is x1 (no digit) or x7/x8/x10,
    # and a readable count after either is a rise.
    haste_timed = (before.haste_present and before.haste_left is not None
                   and after.haste_left is not None)
    if "haste" in allowed and after.haste_present:
        if not before.haste_present:
            return "collected", f"haste absent -> {after.haste_stacks or 1}"
        if haste_timed and after.haste_left - before.haste_left >= HASTE_REFILL_S:
            return "collected", (f"the Haste's square refilled: {before.haste_left:.0f}s -> "
                                 f"{after.haste_left:.0f}s left")
        if after.haste_stacks is not None and after.haste_stacks > (before.haste_stacks or 1):
            return "collected", f"haste {before.haste_stacks or 1} -> {after.haste_stacks}"
    # The background the bar would have risen by anyway; None = unwatched.
    stack_bar = (None if stack_rate is None
                 else STACK_LUMP_FACTOR * stack_rate * seconds)
    stacks_count = "stacks" in allowed and stack_bar is not None
    for slot, n in after.stacks.items():
        was = before.stacks.get(slot)
        if stacks_count and was is not None and n - was > stack_bar:
            return "collected", f"a buff's stacks rose x{was} -> x{n}"
    # A NEW ICON SHIFTS EVERY SLOT, so the per-slot test above misses the most
    # common collection of all: a buff token that was not up before. MEASURED
    # 2026-09-22 23:00 on the live bar, icons are added and removed from the
    # row and the ones to their right move; comparing the TOTAL of every
    # readable stack survives that, and a total that rises is a buff gained.
    was_total, now_total = sum(before.stacks.values()), sum(after.stacks.values())
    if stacks_count and now_total - was_total > stack_bar:
        return "collected", (f"the buff bar's stacks went from {was_total} to "
                             f"{now_total} altogether")
    if stacks_count and len(after.stacks) - len(before.stacks) > stack_bar:
        return "collected", (f"a buff appeared on the bar ({len(before.stacks)} "
                             f"icons with counts -> {len(after.stacks)})")
    if ("pollen" in allowed and before.pollen is not None
            and after.pollen is not None and pollen_rate is not None):
        delta = after.pollen - before.pollen
        expected = pollen_rate * seconds
        if delta > max(POLLEN_LUMP_MIN, POLLEN_LUMP_FACTOR * expected):
            return "collected", (f"pollen rose {delta:,} in {seconds:.1f}s against "
                                 f"{expected:,.0f} expected from gathering")
    # nothing moved: a verdict only where the kind's counter was watchable,
    # AND QUIET ENOUGH TO SHOW A TOKEN. A lump must clear max(HONEY_LUMP_MIN,
    # HONEY_LUMP_FACTOR x the trickle); once the trickle sets that bar a small
    # honey token vanishes under it. MEASURED 2026-10-07 in var/school-coins:
    # 155 honey "nothing" against 13 collected, every collected one beside a
    # trickle of 500-900 honey a second, and the "nothing" crops are coins --
    # honey drops, gold rims, boosts -- so the school gated honey tokens at
    # P 0.00 (run-734: 17 of 64 holds).
    if kind in HONEY_KINDS and honey_watched:
        expected = honey_rate * seconds
        hidden = max(HONEY_LUMP_MIN, HONEY_LUMP_FACTOR * expected) - expected
        if hidden < HONEY_TOKEN_SMALLEST:
            return "nothing", (f"{HONEY_NOTHING} ({expected:,.0f} expected in "
                               f"{seconds:.1f}s)")
        return "unknown", (f"reached it, but a trickle of {expected:,.0f} in "
                           f"{seconds:.1f}s hides a honey token under {hidden:,.0f}")
    if kind in HASTE_KINDS:
        # "Nothing" only where the Haste could be read both times: absent
        # before or after, its square's time, or its count.
        if (not (before.haste_present and after.haste_present) or haste_timed
                or (before.haste_stacks is not None and after.haste_stacks is not None)):
            return "nothing", "reached it and the haste stacks did not move"
        return "unknown", ("reached it, but neither the Haste's count nor its "
                           "square's time could be read both times")
    # Only a bar that did not rise at all: a +1 inside the background is
    # not a lump, but it is not proof of nothing either.
    rose = (now_total > was_total or len(after.stacks) > len(before.stacks)
            or any(before.stacks.get(s) is not None and n > before.stacks[s]
                   for s, n in after.stacks.items()))
    if kind in STACK_KINDS and after.stacks and before.stacks and not rose:
        return "nothing", ("reached it and nothing on the buff bar gained a "
                           "stack")
    if (kind in POLLEN_LUMP_KINDS and before.pollen is not None
            and after.pollen is not None and pollen_rate is not None):
        return "nothing", "reached it and the pollen figure took no lump"
    if "stacks" in allowed and rose:
        return "unknown", ("the buff bar rose, but " + (
            "its own background rise was not watched" if stack_bar is None
            else f"no more than its own background ({stack_bar:.1f} expected)"))
    return "unknown", f"a {kind} leaves no mark this can read on the HUD"


# THE VERDICT BY SIGHT (2026-10-21, look-only): act/chase looks once more
# SIGHT_SETTLE_S after arriving, and a target gone from where the walk left it
# was touched. Recorded beside the HUD verdict in every lesson (`sight`,
# `sight_evidence`); it becomes the LABEL only when this is True, after a
# day of both has been compared -- above all on honey tokens, where the HUD
# confirmed 157 of 1,831 reached (act/chase SIGHT_CHECK).
SIGHT_LABELS = False


def judge_by_sight(arrived: bool, sight: dict | None) -> tuple[str, str]:
    """`(verdict, evidence)` from act/chase's look after arriving:
    "collected" when the target was gone, else "unknown"; ("", why) when
    there was no look to judge by."""
    if not arrived:
        return "unknown", NEVER
    if not sight:
        return "", "no look after arriving"
    verdict = sight.get("verdict")
    settle = sight.get("settle_s")
    if verdict == "gone":
        return "collected", f"gone {settle}s after arriving ({sight.get('seen', 0)} in view)"
    if verdict == "still there":
        where = ("under the character" if sight.get("underfoot")
                 else f"{sight.get('near_px')} px from where the walk left it")
        return "unknown", f"still there {settle}s after arriving, {where}"
    return "", f"no verdict by sight ({verdict})"


def crop_of(frame, x: int, y: int, size: int = CROP):
    """A size x size BGR crop centred on (x, y), padded at the edges."""
    if frame is None:
        return None
    h, w = frame.shape[:2]
    half = size // 2
    x0, y0 = int(x) - half, int(y) - half
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(w, x0 + size), min(h, y0 + size)
    if sx1 <= sx0 or sy1 <= sy0:
        return None
    canvas[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = frame[sy0:sy1, sx0:sx1, :3]
    return canvas


def features(crop) -> np.ndarray:
    """HOG of the grayscale crop plus an HSV histogram, as one float vector."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hog = cv2.HOGDescriptor((CROP, CROP), (16, 16), (8, 8), (8, 8), 9)
    h = hog.compute(gray).reshape(-1)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256]).reshape(-1)
    hist = hist / max(1.0, float(hist.sum()))
    return np.concatenate([h, hist * 4.0]).astype(np.float32)


def _legacy_verdict(lesson) -> bool:
    """Lessons judged before the honey trickle was discounted (2026-09-22
    22:22-22:30, evidence written "honey rose by N") were the trickle, not
    tokens. They stay in the file as the record; they teach nothing."""
    if str(lesson.evidence or "").startswith("honey rose by "):
        return True
    # A honey "nothing" from before HONEY_TOKEN_SMALLEST, whose evidence has
    # no figures: judged under whatever trickle there was, in var/school-coins
    # 500-900 a second, which hides a small token.
    if lesson.outcome == "nothing" and str(lesson.evidence or "") == HONEY_NOTHING:
        return True
    # And a "collected" that rested on the buff bar alone for a kind with a
    # counter of its own (see STACK_LUMP_FACTOR): the background, not a token.
    return (lesson.outcome == "collected" and lesson.kind in OWN_COUNTER_KINDS
            and str(lesson.evidence or "").startswith(STACK_EVIDENCE))


@dataclass
class Lesson:
    id: str
    at: float
    kind: str
    confidence: float
    x: int
    y: int
    outcome: str = "unknown"
    evidence: str = ""
    attempt: int | None = None
    sight: str = ""              # judge_by_sight's verdict, beside the HUD's
    sight_evidence: str = ""
    # The detector's confidence in the chased track (tokenbrain trace
    # "detector"); `confidence` above is CONFIDENCE_BY_MATCHES. None before
    # 2026-10-21.
    detector_confidence: float | None = None
    # THE DETOUR'S COST (tokenbrain LOSS_FRACTION): pollen/s before the chase
    # (the background window) and over it (the HUD's pollen before and after
    # over the seconds between). None where either was unreadable.
    rate_before: float | None = None
    rate_during: float | None = None


class School:
    """The lessons on disk, the pollen-rate watcher, and the classifier."""

    def __init__(self, root, k: int = 5, min_lessons: int = MIN_LESSONS, clock=time.monotonic):
        self.root = pathlib.Path(root)
        self.crops = self.root / "crops"
        self.log = self.root / "lessons.jsonl"
        self.k = k
        self.min_lessons = min_lessons
        self.clock = clock
        self._pollen: collections.deque = collections.deque()
        self._honey: collections.deque = collections.deque()
        self._stacks: collections.deque = collections.deque()
        self._model = None
        self._trained_on = -1
        self._pending: dict[str, tuple[Lesson, Snapshot]] = {}
        self._seq = 0
        self.lessons: list[Lesson] = []
        # (cell, reached) of the latest PHANTOM_WINDOW sure chases, and per
        # cell [chases, reached] over that window (`phantom`)
        self._recent: collections.deque = collections.deque()
        self._cells: dict = collections.defaultdict(lambda: [0, 0])
        self._load()

    # ---- the pollen rate -------------------------------------------------------
    def tick(self, pollen: int | None, at: float | None = None,
             honey: int | None = None, stacks: int | None = None) -> None:
        """A periodic pollen (and honey, and buff-bar stack total) reading,
        for the background rates."""
        now = self.clock() if at is None else at
        for value, window in ((pollen, self._pollen), (honey, self._honey),
                              (stacks, self._stacks)):
            if value is None:
                continue
            window.append((now, int(value)))
            while window and now - window[0][0] > RATE_WINDOW_S:
                window.popleft()

    @staticmethod
    def _rate(window) -> float | None:
        if len(window) < 2:
            return None
        (t0, p0), (t1, p1) = window[0], window[-1]
        if t1 - t0 < 5.0:
            return None
        if p1 < p0:
            window.clear()
            return None
        return (p1 - p0) / (t1 - t0)

    def pollen_rate(self) -> float | None:
        """Pollen per second over the window, or None until there are two
        readings spanning at least five seconds. A fall (a convert, a death)
        empties the window: it is not a rate."""
        return self._rate(self._pollen)

    def honey_rate(self) -> float | None:
        """The honey trickle per second (bee abilities pay honey in the
        field), or None until watched for five seconds."""
        return self._rate(self._honey)

    def stack_rate(self) -> float | None:
        """How fast the buff bar's stack total RISES on its own, per second:
        every rise between two readings summed (buffs also expire, so the net
        change would hide them), or None until watched for five seconds."""
        window = self._stacks
        if len(window) < 2 or window[-1][0] - window[0][0] < 5.0:
            return None
        rises = sum(max(0, b[1] - a[1]) for a, b in zip(window, list(window)[1:]))
        return rises / (window[-1][0] - window[0][0])

    # ---- lessons -------------------------------------------------------------
    def begin(self, frame, x: int, y: int, kind: str, confidence: float,
              before: Snapshot, attempt: int | None = None,
              detector_confidence: float | None = None) -> Lesson | None:
        """A chase is about to start at (x, y): keep the crop and the counters."""
        crop = crop_of(frame, x, y)
        if crop is None:
            return None
        self._seq += 1
        lesson = Lesson(id=f"{int(self.clock() * 1000)}-{self._seq}-{x}-{y}", at=before.at, kind=kind,
                        confidence=float(confidence), x=int(x), y=int(y), attempt=attempt,
                        detector_confidence=(None if detector_confidence is None
                                             else float(detector_confidence)))
        self.crops.mkdir(parents=True, exist_ok=True)
        try:
            cv2.imwrite(str(self.crops / f"{lesson.id}.png"), crop)
        except Exception:
            return None
        wide = crop_of(frame, x, y, WIDE_CROP)
        if wide is not None:
            try:
                (self.root / "crops-wide").mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(self.root / "crops-wide" / f"{lesson.id}.jpg"), wide,
                            [cv2.IMWRITE_JPEG_QUALITY, 90])
            except Exception:
                pass                       # the lesson stands without it
        self._pending[lesson.id] = (lesson, before)
        return lesson

    def finish(self, lesson: Lesson, after: Snapshot, arrived: bool,
               sight: dict | None = None) -> Lesson:
        """The chase is over: judge it, write it down. `sight` is act/chase's
        look after arriving (ChaseResult.sight), judged beside the HUD."""
        pending = self._pending.pop(lesson.id, None)
        before = pending[1] if pending else None
        if before is None:
            lesson.outcome, lesson.evidence = "unknown", "no snapshot from before the chase"
        else:
            lesson.outcome, lesson.evidence = judge(lesson.kind, before, after, arrived,
                                                    self.pollen_rate(), self.honey_rate(),
                                                    self.stack_rate())
        lesson.sight, lesson.sight_evidence = judge_by_sight(arrived, sight)
        lesson.rate_before = self.pollen_rate()
        if before is not None and before.pollen is not None and after.pollen is not None \
                and after.at > before.at:
            lesson.rate_during = round((after.pollen - before.pollen) / (after.at - before.at), 1)
        if SIGHT_LABELS and lesson.outcome == "unknown" and lesson.sight == "collected":
            lesson.outcome = "collected"
            lesson.evidence = f"by sight: {lesson.sight_evidence}"
        if lesson.outcome == "unknown":
            # keep the crop for a human to look at; it teaches the classifier nothing
            self._append(lesson)
            return lesson
        self._append(lesson)
        self.lessons.append(lesson)
        return lesson

    def drop(self, lesson: Lesson, why: str) -> Lesson:
        """A chase that says nothing about its token -- the owner took the
        controls during it -- kept as "unknown", as `finish` keeps one it
        cannot judge: the crop stays for a human, and it teaches nothing."""
        self._pending.pop(lesson.id, None)
        lesson.outcome, lesson.evidence = "unknown", str(why)
        self._append(lesson)
        return lesson

    # ---- phantom spots ----------------------------------------------------------
    def _remember(self, lesson: Lesson) -> None:
        # only a lesson that says whether the chase got there: an owner
        # takeover (`drop`) or a no-snapshot "unknown" is not NEVER and would
        # count as reached, hiding a phantom (chase_lessons --phantom: same)
        if lesson.confidence != 1.0 or not counts_for_phantom(lesson.evidence, lesson.outcome):
            return
        cell = (int(lesson.x) // PHANTOM_CELL_PX, int(lesson.y) // PHANTOM_CELL_PX)
        reached = lesson.evidence != NEVER
        self._recent.append((cell, reached))
        c = self._cells[cell]
        c[0] += 1
        c[1] += reached
        if len(self._recent) > PHANTOM_WINDOW:
            old, was = self._recent.popleft()
            o = self._cells[old]
            o[0] -= 1
            o[1] -= was

    def phantom(self, x: int, y: int, detector: float | None = None) -> tuple[int, float] | None:
        """(chases, share reached) when (x, y)'s cell is a phantom spot over
        the latest PHANTOM_WINDOW lessons, else None. A target the detector
        is PHANTOM_CONFIDENCE sure of is never one."""
        if detector is not None and detector >= PHANTOM_CONFIDENCE:
            return None
        n, reached = self._cells.get((int(x) // PHANTOM_CELL_PX,
                                      int(y) // PHANTOM_CELL_PX), (0, 0))
        if n >= PHANTOM_MIN_CHASES and reached / n < PHANTOM_MAX_REACH:
            return n, reached / n
        return None

    def _append(self, lesson: Lesson) -> None:
        self._remember(lesson)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.log.open("a") as fh:
                fh.write(json.dumps(lesson.__dict__) + "\n")
        except OSError:
            pass

    def _load(self) -> None:
        self.lessons = []
        if not self.log.exists():
            return
        for line in self.log.read_text().splitlines():
            try:
                body = json.loads(line)
                lesson = Lesson(**{k: body.get(k) for k in Lesson.__dataclass_fields__})
            except Exception:
                continue
            self._remember(lesson)
            if _legacy_verdict(lesson):
                continue
            if lesson.outcome in ("collected", "nothing"):
                self.lessons.append(lesson)

    def counts(self) -> dict[str, int]:
        out = {"collected": 0, "nothing": 0}
        for lesson in self.lessons:
            out[lesson.outcome] = out.get(lesson.outcome, 0) + 1
        return out

    # ---- the classifier ----------------------------------------------------------
    def ready(self) -> bool:
        c = self.counts()
        return c["collected"] >= self.min_lessons and c["nothing"] >= self.min_lessons

    def _train(self) -> bool:
        if not self.ready():
            self._model = None
            return False
        if self._model is not None and self._trained_on == len(self.lessons):
            return True
        xs, ys = [], []
        for lesson in self.lessons:
            crop = cv2.imread(str(self.crops / f"{lesson.id}.png"))
            if crop is None or crop.shape[:2] != (CROP, CROP):
                continue
            xs.append(features(crop))
            ys.append(1 if lesson.outcome == "collected" else 0)
        if len(set(ys)) < 2 or not hasattr(cv2, "ml"):   # no cv2.ml: vision/fieldsense NO_ML
            self._model = None
            return False
        knn = cv2.ml.KNearest_create()
        knn.train(np.array(xs, dtype=np.float32), cv2.ml.ROW_SAMPLE,
                  np.array(ys, dtype=np.int32))
        self._model = knn
        self._trained_on = len(self.lessons)
        return True

    def score(self, crop) -> float | None:
        """P(token) for a crop, or None while the school is too small."""
        if crop is None or not self._train():
            return None
        k = min(self.k, len(self.lessons))
        _ret, _res, neighbours, _dist = self._model.findNearest(
            features(crop).reshape(1, -1), k)
        return float(np.mean(neighbours[0] == 1))

    def describe(self) -> str:
        c = self.counts()
        head = f"{c['collected']} token lesson(s), {c['nothing']} not-a-token"
        return head + (" — classifying" if self.ready() else
                       f" — silent until {self.min_lessons} of each")

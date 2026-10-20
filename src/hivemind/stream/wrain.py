"""Chat's W rain: when chat types "W", W's fall down the stream window.

THE OWNER'S ASK: when chat types W, a few W's fall down the screen -- the more
people and the faster, the more fall.

No Qt here, so every rule is driven offline with invented chat; the drawing
is gui/stream_rain. Nothing here reaches chat, the game or the bot: a W only
ever becomes pixels on the stream window.

  THE W      `w_worth(text)`: how many W's a message is worth, 0 if it is not
             a W. Short messages only, so a sentence that happens to hold a
             lone "w" is not one.
  THE LIMIT  a chatter's W's pass a token bucket: three at once, then one
             every two seconds. One person typing W over and over keeps a
             light rain going, never a heavy one.
  THE HEAT   the W's of the last 15 s, each chatter counted at most five
             times: more people, or the same people faster, raise it, and it
             sets how many W's a message drops and how big they are.
  THE BATCH  W's that arrive one by one fall at once. W's that arrive
             together are spread over the seconds after: YouTube's chat
             reader polls every 9.6 s at the fastest (stream/chat.
             YT_POLL_FLOOR) and hands over a poll's messages in one go, which
             would otherwise fall as one clump and then nothing for nine
             seconds.
  THE FALL   plain data: each W starts just above the top at a random place
             across the width, falls towards its own terminal speed, sways
             and tilts like a leaf -- never past 24 degrees, since a W upside
             down is an M -- and is gone once below the bottom. Never more
             than MAX_LIVE at once, nor more starting a second than the
             screen holds evenly; with nothing falling nothing runs.
  THE COUNT  "W ×12": the W messages of this streak, shown while W's fall.

DESIGN 8ee.
"""
from __future__ import annotations

import math
import random
import re
import unicodedata
from collections import deque
from dataclasses import dataclass

# ---- the W ---------------------------------------------------------------------
#
# A W-word is the letter W, once or repeated ("W", "w", "WWW"), with a plural
# on it or not ("W's in the chat"); punctuation and emoji at its ends are not
# part of it ("W!", "W🔥", "(W)"). A slash is kept, so "w/" and "w/e" are
# not W's; nor are "with", "what" or "wow", which are other words.
#
# A MESSAGE IS A W when
#   - every word in it is a W-word ("W W W", "WWWWWW", "W 🔥🔥"), or
#   - it is short (MAX_WORDS words, MAX_CHARS characters at most), holds a
#     W-word, and says no "not" ("W chat", "big W", "W bot", "what a W",
#     "massive W energy"; not "not a W"). In the middle of such a message
#     only a capital W counts: a small "w" between words is "with" as often
#     as not ("playing w my friend").
# A long sentence that merely contains a lone "w" is therefore never one.
MAX_WORDS = 5
MAX_CHARS = 40
# The most one message is worth: "WWWWWWWWWWWW" counts as five.
PER_MESSAGE_MAX = 5
W_WORD = re.compile(r"^(w+)(?:'s|s)?$", re.IGNORECASE)
# a word's leading and trailing punctuation and emoji -- anything but a
# letter, a digit, "_" or "/"
EDGES = re.compile(r"^[^\w/]+|[^\w/]+$")
NOT_WORDS = frozenset({"not", "no", "never", "nah", "isnt", "isn't", "aint",
                       "ain't", "wasnt", "wasn't", "dont", "don't", "zero"})


def w_worth(text) -> int:
    """How many W's `text` is worth, 1 to PER_MESSAGE_MAX; 0 if it is not a W.

    "W" 1, "WWW" 3, "W W W" 3, "W!" 1, "W chat" 1, "big W" 1, "W bot" 1;
    "with", "what", "w/", "not a W" and a long sentence with a "w" in it 0.
    """
    # NFKC folds the look-alikes chat pastes ("Ｗ", a full-width W, is "W")
    text = unicodedata.normalize("NFKC", str(text or "")).replace("’", "'")
    words = [w for w in (EDGES.sub("", token) for token in text.split()) if w]
    if not words:
        return 0
    found = [W_WORD.match(w) for w in words]
    if not any(found):
        return 0
    if all(found):
        return min(PER_MESSAGE_MAX, sum(len(m.group(1)) for m in found))
    if len(words) > MAX_WORDS or len(text.strip()) > MAX_CHARS:
        return 0
    if any(w.lower() in NOT_WORDS for w in words):
        return 0
    # at either end any W-word; in the middle only a capital W
    last = len(found) - 1
    count = sum(len(m.group(1)) for i, m in enumerate(found)
                if m and (i in (0, last) or m.group(1)[0] == "W"))
    return min(PER_MESSAGE_MAX, count)


# ---- the limit -----------------------------------------------------------------
# A token bucket per chatter: USER_BURST W's at once, then one every
# USER_REFILL_S. A W over the limit is ignored whole: it neither falls nor
# counts towards the heat or the count on screen.
USER_BURST = 3
USER_REFILL_S = 2.0
# Chatters whose buckets are kept; past this, the ones already full again
# (quiet for USER_BURST x USER_REFILL_S) are forgotten, as they hold nothing.
USERS_KEPT = 2000

# ---- the heat --------------------------------------------------------------------
# HEAT_WINDOW_S holds one of YouTube's 9.6 s polls and the spread after it
# (BATCH_SPREAD_S), so a chat that keeps it up there keeps its heat. A
# chatter counts at most HEAT_PER_USER times in it -- one W every 3 s --
# so typing faster than that rains more W's but no bigger ones, and one
# person alone never heats it past five people typing once.
HEAT_WINDOW_S = 15.0
HEAT_PER_USER = 5
# The heat at which the rain is at its heaviest: nine people each typing a W
# every 3 s, or forty-five typing it once. The level between is the heat's
# logarithm, so the first few extra chatters change the most -- the second
# person makes a visible difference, the fortieth a small one.
HEAT_FULL = 45.0

# ---- the batch ---------------------------------------------------------------------
# W's stamped within BATCH_S of the one before came in one go: a reader makes
# each ChatLine as it parses it (stream/chat, `at` is set then, on the
# reader's thread), so one poll of YouTube's or one read of a chat file is
# stamped a few microseconds apart, while Twitch sends each message as it is
# typed. The stamp and not the moment the window hears it, which is as late
# as the chat card's redraw for the line before. A batch falls BATCH_GAP_S
# apart, or closer so that all of it has fallen within BATCH_SPREAD_S --
# inside YouTube's 9.6 s, so one poll's W's are out before the next poll's
# arrive. A W that arrives on its own falls at once, and so does what is left
# of a batch when the next one comes: a busy Twitch chat whose messages come
# two or three to a read is never held back by more than the gap between
# reads.
BATCH_S = 0.001
BATCH_GAP_S = 1.0
BATCH_SPREAD_S = 8.0
# The most W messages waiting; past it a W is dropped. MAX_LIVE is full long
# before 200 have fallen.
QUEUE_MAX = 200

# ---- the fall --------------------------------------------------------------------
# W's dropped by one message: FEW when the heat is lowest, MANY at its
# highest, plus one for each W past the first in the message ("WWW" +2).
FEW = 3
MANY = 12
# The W's sizes, as the font's pixel size. A quiet rain uses the small three,
# a full one the big five.
SIZES_PX = (44, 54, 66, 80, 96, 112, 128)
# The most W's on screen at once: what keeps a heavy rain to about a quarter
# of the GUI thread. A frame is the W's drawn AND the stream window's cards
# and picture repainted under every W that moved -- most of it the second.
# MEASURED offscreen in the real stream window at 60 frames a second (scratch
# wrain/cost_cap.py), median / 99th percentile a frame: 80 W's 3.3 / 6.8 ms,
# 100 W's 4.0 to 4.2 / 7.5 to 7.8 (two runs), 120 4.7 / 8.8, 160 6.4 / 10.9
# -- against 16.7 ms a frame.
MAX_LIVE = 100
# ...AND THE MOST THAT START A SECOND: MAX_LIVE over how long a middling
# heavy W (SIZES_PX[4]) takes to fall (`fall_seconds`), after a burst of up to
# a quarter of MAX_LIVE at once. Capped by count alone, a heavy rain came in
# slabs: a burst filled the screen at once, fell and left together, and the
# screen emptied before the next (the first drive at the cap swung between
# 13 and 160). A W that cannot start within START_WAIT_S is dropped, so a
# heavy rain never lags chat by more than that.
START_BURST_SHARE = 0.25
START_WAIT_S = 1.5
# Falling: each W speeds up towards its own terminal speed, bigger ones
# faster (they read as nearer).
GRAVITY = 900.0                 # px/s^2 at rest
TERMINAL_BASE = 300.0           # px/s, plus TERMINAL_PER_PX x its size
TERMINAL_PER_PX = 2.2
# ...and it comes in already falling, at this share of that speed: it has
# been falling above the screen. From rest they bunched in the top 200 px,
# where the slow ones were (the first render at the cap).
START_SHARE = (0.55, 0.85)
# Swaying: a sine across of 12 to 40 px (scaled with size), one swing every
# 2 to 4 s, a slow drift of up to 40 px/s; tilted with its swing by 8 to 16
# degrees about a lean of up to 8, so never more than MAX_TILT_DEG.
SWAY_PX = (12.0, 40.0)
SWAY_RAD_S = (2 * math.pi / 4.0, 2 * math.pi / 2.0)
DRIFT_PX_S = 40.0
TILT_DEG = (8.0, 16.0)
LEAN_DEG = 8.0
MAX_TILT_DEG = 24.0
# How far above the top a W may start, so one message's W's come in over
# about half a second instead of in a line; and a margin over that of one
# step's fall at the fastest start (0.85 x 582 px/s x MAX_STEP_S), for a W
# that starts between two frames.
START_SPREAD_PX = 220.0
START_MARGIN_PX = 25.0
# A W's half-height at any tilt, as a share of its size, outline, shadow and
# margin included: MEASURED on the overlay's own pixmaps, 0.633 (128 px) to
# 0.659 (44 px). It starts with its bottom above the window's top and is gone
# once its top is below the bottom, so it never pops in or out on screen.
HALF_EXTENT = 0.66
# ...and its half-width (0.742 to 0.778 measured), so it starts whole inside
# the window's width.
HALF_WIDTH = 0.78
# A step longer than this is taken as this: a stalled GUI thread must not
# teleport every W a screen down when it comes back.
MAX_STEP_S = 0.05

# ---- the count -----------------------------------------------------------------------
# The streak goes on while each W falls within COMBO_KEEP_S of the last: past
# one YouTube poll gap, so a chat that keeps it up there keeps one count.
COMBO_KEEP_S = 12.0
COMBO_FROM = 2                  # "W ×2" and up; one W is not a streak
COMBO_IN_S = 0.15               # fade in
COMBO_OUT_S = 0.6               # fade out once the last W has fallen
COMBO_PULSE_S = 0.25            # the bump on each new W


def level_of(heat: float) -> float:
    """0 for a single W, 1 at HEAT_FULL and over."""
    if heat <= 1.0:
        return 0.0
    return min(1.0, math.log(heat) / math.log(HEAT_FULL))


def drops_for(level: float, worth: int = 1) -> int:
    """How many W's one message drops at `level`."""
    worth = max(1, min(PER_MESSAGE_MAX, int(worth)))
    return int(round(FEW + (MANY - FEW) * max(0.0, min(1.0, level)))) + worth - 1


def size_range(level: float) -> tuple[int, int]:
    """The indexes into SIZES_PX a W may take at `level`: 0-2 when quiet,
    2-6 at the heaviest."""
    level = max(0.0, min(1.0, level))
    return int(round(2 * level)), 2 + int(round(4 * level))


def terminal_speed(size_px: float) -> float:
    return TERMINAL_BASE + TERMINAL_PER_PX * size_px


def fall_seconds(size_px: float, height: float = 1080.0, step: float = 1 / 60) -> float:
    """How long a W of this size takes from the middle of where it may start
    to below the bottom, stepped as `Rain.advance` steps it."""
    terminal = terminal_speed(size_px)
    half = HALF_EXTENT * size_px
    y = -half - START_MARGIN_PX - START_SPREAD_PX / 2
    vy = terminal * sum(START_SHARE) / 2
    t = 0.0
    while y - half <= height:
        vy += (GRAVITY - GRAVITY / terminal * vy) * step
        y += vy * step
        t += step
    return t


@dataclass(eq=False, slots=True)
class Drop:
    """One falling W. `x`, `y` are its centre in window pixels, `angle` its
    tilt in degrees (clockwise); `size` indexes SIZES_PX. `drawn` is the
    overlay's own note of where it last drew it -- nothing here reads it."""
    x: float
    y: float
    vy: float
    terminal: float
    base_x: float
    drift: float
    sway: float
    swing: float
    phase: float
    tilt: float
    lean: float
    size: int
    angle: float = 0.0
    drawn: object = None


class Rain:
    """The W rain as data. Call `hear(user, text, now)` for each chat line and
    `advance(now)` once a frame while `busy`; `drops` is what to draw, and
    `combo`, `combo_alpha` and `combo_pulse` the count's number, opacity and
    bump. Times are seconds on any one clock (the overlay's is monotonic)."""

    def __init__(self, width: int = 1920, height: int = 1080,
                 rng: random.Random | None = None, max_live: int = MAX_LIVE):
        self.width, self.height = int(width), int(height)
        self.rng = rng or random.Random()
        self.max_live = int(max_live)
        self.start_rate = self.max_live / fall_seconds(SIZES_PX[4], self.height)
        self.start_burst = max(1.0, START_BURST_SHARE * self.max_live)
        self._starts = self.start_burst             # W's that may start now
        self._starts_at: float | None = None
        self._pending: deque = deque()              # (start by, level), W's to start
        self.drops: list[Drop] = []
        self.combo = 0
        self.combo_alpha = 0.0
        self.combo_pulse = 0.0
        self._users: dict[str, tuple[float, float]] = {}   # user -> (tokens, at)
        self._batch: list = []          # (user, worth), in arrival order
        self._fallen = 0                # how many of the batch have fallen
        self._batch_at = 0.0            # when its first one fell
        self._stamp: float | None = None   # the last W's own stamp
        self._recent: deque = deque()   # (fell at, user), for the heat
        self._fell_at: float | None = None
        self._last: float | None = None
        # what happened, for the drives and the doc
        self.heard = self.accepted = self.limited = 0
        self.spawned = self.capped = self.dropped = 0

    # ---- chat in ------------------------------------------------------------------
    def hear(self, user, text, now: float, stamp: float | None = None) -> int:
        """One chat message, heard at `now`; `stamp` is when its reader made
        it (ChatLine.at), `now` if not given. Its worth if it is a W that
        passed the limit (it falls now, or soon if it came with others),
        else 0."""
        self.heard += 1
        worth = w_worth(text)
        if not worth:
            return 0
        if self.waiting >= QUEUE_MAX:
            self.dropped += 1
            return 0
        if not self._take(str(user or ""), now):
            self.limited += 1
            return 0
        self.accepted += 1
        stamp = now if stamp is None else float(stamp)
        together = self._stamp is not None and 0.0 <= stamp - self._stamp < BATCH_S
        self._stamp = stamp
        if not together:
            # a batch of its own; whatever of the last has not fallen yet
            # falls now
            for waiting_user, waiting_worth in self._batch[self._fallen:]:
                self._fall(waiting_user, waiting_worth, now)
            self._batch, self._fallen, self._batch_at = [], 0, now
        self._batch.append((str(user or ""), worth))
        self._release(now)
        return worth

    def _take(self, user: str, now: float) -> bool:
        tokens, at = self._users.get(user, (float(USER_BURST), now))
        tokens = min(float(USER_BURST), tokens + max(0.0, now - at) / USER_REFILL_S)
        ok = tokens >= 1.0
        self._users[user] = (tokens - 1.0 if ok else tokens, now)
        if len(self._users) > USERS_KEPT:
            full = USER_BURST * USER_REFILL_S
            self._users = {u: v for u, v in self._users.items() if now - v[1] < full}
        return ok

    # ---- the heat -----------------------------------------------------------------
    def heat(self, now: float) -> float:
        """The W messages fallen in the last HEAT_WINDOW_S, each chatter
        counted at most HEAT_PER_USER times."""
        recent = self._recent
        while recent and recent[0][0] <= now - HEAT_WINDOW_S:
            recent.popleft()
        per: dict[str, int] = {}
        for _at, user in recent:
            per[user] = per.get(user, 0) + 1
        return float(sum(min(HEAT_PER_USER, n) for n in per.values()))

    def level(self, now: float) -> float:
        return level_of(self.heat(now))

    # ---- the batch ------------------------------------------------------------------
    @property
    def waiting(self) -> int:
        """W messages heard and not fallen yet."""
        return len(self._batch) - self._fallen

    def _gap(self) -> float:
        n = len(self._batch)
        return 0.0 if n < 2 else min(BATCH_GAP_S, BATCH_SPREAD_S / (n - 1))

    def _release(self, now: float) -> None:
        gap = self._gap()
        while self._fallen < len(self._batch) and now >= self._batch_at + self._fallen * gap:
            user, worth = self._batch[self._fallen]
            self._fallen += 1
            self._fall(user, worth, now)

    def _fall(self, user: str, worth: int, now: float) -> None:
        """One W message's W's start falling."""
        if self._fell_at is None or now - self._fell_at > COMBO_KEEP_S:
            self.combo = 0
        self._fell_at = now
        self.combo += 1
        self.combo_pulse = 1.0
        self._recent.append((now, user))
        level = self.level(now)
        self._pending.extend([(now + START_WAIT_S, level)] * drops_for(level, worth))
        self._start(now)

    def _start(self, now: float) -> None:
        """Start the waiting W's the rate, the burst and the cap allow; drop
        the ones that have waited START_WAIT_S."""
        if self._starts_at is not None:
            self._starts = min(self.start_burst, self._starts
                               + max(0.0, now - self._starts_at) * self.start_rate)
        self._starts_at = now
        pending = self._pending
        while pending and pending[0][0] < now:
            pending.popleft()
            self.capped += 1
        while pending and self._starts >= 1.0 and len(self.drops) < self.max_live:
            self._spawn(pending.popleft()[1])
            self._starts -= 1.0

    def _spawn(self, level: float) -> None:
        """One W, just above the top, somewhere across the width."""
        r = self.rng
        size = r.randint(*size_range(level))
        px = SIZES_PX[size]
        side = HALF_WIDTH * px
        x = r.uniform(side, max(side, self.width - side))
        terminal = terminal_speed(px)
        drop = Drop(x=x, y=-HALF_EXTENT * px - START_MARGIN_PX - r.uniform(0.0, START_SPREAD_PX),
                    vy=terminal * r.uniform(*START_SHARE), terminal=terminal,
                    base_x=x, drift=r.uniform(-DRIFT_PX_S, DRIFT_PX_S),
                    sway=r.uniform(*SWAY_PX) * px / 80.0, swing=r.uniform(*SWAY_RAD_S),
                    phase=r.uniform(0.0, 2 * math.pi), tilt=r.uniform(*TILT_DEG),
                    lean=r.uniform(-LEAN_DEG, LEAN_DEG), size=size)
        drop.x = drop.base_x + drop.sway * math.sin(drop.phase)
        drop.angle = drop.lean + drop.tilt * math.cos(drop.phase)
        self.drops.append(drop)
        self.spawned += 1

    # ---- a frame ----------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        """Anything falling, waiting, or the count still on screen."""
        return bool(self.drops or self.waiting or self._pending or self.combo_alpha > 0.0)

    def advance(self, now: float) -> list[Drop]:
        """Move everything to `now`. Returns the W's that left the window in
        this step (the overlay erases where it last drew them)."""
        dt = 0.0 if self._last is None else max(0.0, min(MAX_STEP_S, now - self._last))
        self._last = now
        gone, kept = [], []
        bottom = self.height
        for d in self.drops:
            d.vy += (GRAVITY - GRAVITY / d.terminal * d.vy) * dt
            d.y += d.vy * dt
            d.phase += d.swing * dt
            d.base_x += d.drift * dt
            d.x = d.base_x + d.sway * math.sin(d.phase)
            d.angle = d.lean + d.tilt * math.cos(d.phase)
            if d.y - HALF_EXTENT * SIZES_PX[d.size] > bottom:
                gone.append(d)
            else:
                kept.append(d)
        self.drops = kept
        # after the step, so a new W starts where it starts
        self._release(now)
        self._start(now)
        self.combo_pulse = max(0.0, self.combo_pulse - dt / COMBO_PULSE_S)
        if (self.drops or self.waiting or self._pending) and self.combo >= COMBO_FROM:
            self.combo_alpha = min(1.0, self.combo_alpha + dt / COMBO_IN_S)
        else:
            self.combo_alpha = max(0.0, self.combo_alpha - dt / COMBO_OUT_S)
        if not self.busy:
            self._last = None            # the next rain starts from rest
        return gone

    def clear(self) -> list[Drop]:
        """Everything off the screen at once (the owner switched it off).
        Returns the W's that were on it."""
        gone = self.drops
        self.drops = []
        self._batch, self._fallen = [], 0
        self._pending.clear()
        self._starts, self._starts_at = self.start_burst, None
        self._stamp = self._fell_at = self._last = None
        self._recent.clear()
        self.combo = 0
        self.combo_alpha = self.combo_pulse = 0.0
        return gone

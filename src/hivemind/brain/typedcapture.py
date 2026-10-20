"""Typed token labels, kept AT THE MOMENT a chased token pays.

THE PROBLEM (docs/pending/ai-audit.md, next #1). Every typed signal the bot
sees -- the reward feed's "+340 Honey (from Pine Tree Forest)", a Haste that
appears or refills, a new icon on the buff bar -- was logged without the
frame, and the school's crops (brain/school) carry only a verdict that a
neighbouring token can have earned (rp/data-tokens: the HUD verdict does not
type the chased token). So the typed head (vision/tokentypes) has 61 clean
examples at most beyond honey and haste.

WHAT IS KEPT, per chase whose pickup landed (`finish`): the chased token's
point and box, the trusted sightings of the deciding look (to tell later
whether the walk could have touched another one), a crop round the point of
the deciding frame and of every black-box frame of the WINDOW_S before it
(telemetry/incidents.between: frames already captured, encoded), the buff
bar strip before and after, the HUD and sight verdicts, and every feed read
from the last one before the chase to FEED_GRACE_S after it. Under
var/school-typed/<stamp>-<n>/. scripts/label_typed.py turns them into crops
only where exactly one token was reached and exactly one change happened.

CHEAP. Nothing is captured for it: the deciding frame and the after frame
are the school's, the window is the black box's. Nothing is written when
nothing was chased or nothing landed (save a late feed credit, `heard`).
MEASURED 2026-10-27 on real frames, 2 threads, niced, beside the live bot:
`begin` 0.3 ms median (two crops, references to the window's JPEGs);
`finish` with the write 32 ms median, 37 max (eight 1080p JPEG decodes),
once per paying chase of 2-4 s.

BOUNDED. MAX_CAPTURES folders and MAX_BYTES on disk; the oldest go first.
telemetry/storage.frames_allowed is asked before every write.

PRIVATE. No whole frame is written. Crops are cut inside the detector's
WORLD box (vision/coins), so the top bar, the menu column and the hotbar
are never in them, and the feed pills that reach into it are blacked out
(`world_crop`); a frame where the chat may be open
(stream/privacy.chat_may_be_open) is not used at all, and the bar strip
(x < 456, rows 58-96, inside the chat's region) is kept only from frames
where it is shut. What is NOT masked: another player's overhead name inside a
token's crop, as in the school's wide crops today.
"""
from __future__ import annotations

import collections
import json
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

DIR = "school-typed"
WINDOW_S = 0.5
# THE CROP round the chased point: 2.5 coin sides, never under 192 (the
# school's WIDE_CROP, for a target with no box) nor over 384.
CROP_SIDES = 2.5
CROP_MIN, CROP_MAX = 192, 384
# vision/buffs BAR_TOP..BAR_BOTTOM (58..96) and two rows each side, whose
# step against the icon's edge tells an icon from scenery (`occupied`).
BAR_ROWS, BAR_WIDTH, BAR_PAD = (56, 98), 456, 2
# The feed is read every ~3 s (vision/whereami DEFAULT_EVERY) and a line
# lives 9 s: a pickup's line reaches `heard` up to a read after the chase.
FEED_GRACE_S = 6.0
FEED_KEPT = 24
# A feed line lives ~9 s: a credit on any read this long before the chase
# began is an older pickup's, not a new one (`feed_prior`).
FEED_LINE_S = 9.0
# ANOTHER TOKEN THE WALK MAY HAVE TOUCHED: a trusted sighting this close to
# the straight line from the character to the target, and not the target.
# ponytail: a guess at the character's reach plus the keys' zig-zag (the walk
# is held keys, not a line); measure on captures with one change and lower.
PATH_PX = 100
SAME_PX = 30
# ON DISK. MEASURED 2026-10-27 on 12 token-school windows replayed through
# the hook: a capture is 194 KB median (243 KB max), 8 black-box crops. The
# school had 170-750 chases a day judged collected by the HUD or by sight
# (var/school-coins, 10-21..10-27), so the byte cap keeps ~2,100 captures,
# 3 to 12 days: label them (scripts/label_typed.py) before they rotate out.
MAX_CAPTURES = 2500
MAX_BYTES = 400 * 1024 * 1024
JPEG = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
# Round a feed pill blacked out of a crop: its rounded ends and the glow.
FEED_PAD = 6


def chat_may_be_open(frame) -> bool:
    """stream/privacy's test on a full frame; True when it cannot be told
    (an odd size), so such a frame is never used."""
    from ..stream import privacy
    if frame is None or tuple(frame.shape[:2]) != (privacy.FRAME_H, privacy.FRAME_W):
        return True

    def rgb(box):
        x, y, w, h = box
        return frame[y:y + h, x:x + w, :3][..., ::-1]
    return bool(privacy.chat_may_be_open(rgb(privacy.TOPBAR_PILL), rgb(privacy.CHAT_BADGE)))


def crop_box(x: int, y: int, box) -> tuple[int, int, int]:
    """(x0, y0, side) of the square crop round (x, y) for a coin `box`."""
    side = CROP_MIN
    if box:
        side = int(round(min(CROP_MAX, max(CROP_MIN, CROP_SIDES * max(box[2], box[3])))))
    return int(x) - side // 2, int(y) - side // 2, side


def world_crop(frame, x0: int, y0: int, side: int):
    """The square at (x0, y0), with everything outside the detector's WORLD
    box black (the HUD, the menu column, the top bar) and every feed pill
    black too.

    THE FEED IS INSIDE THE WORLD BOX. MEASURED 2026-10-27 (review) on 500
    frames of the 100 token windows: 101 of 812 feed pills sat inside
    coins.WORLD (pills reach up to y 847 and left to x 1169), in 51 frames.
    A pill in a crop is the label written beside the token ("+340 Honey"):
    a model would learn to read it. So the pills vision/feed finds are
    blacked out, padded by FEED_PAD."""
    from ..vision import coins, feed
    h, w = frame.shape[:2]
    wx0, wy0, wx1, wy1 = coins.world_box(w, h)
    out = np.zeros((side, side, 3), np.uint8)
    sx0, sy0 = max(wx0, x0), max(wy0, y0)
    sx1, sy1 = min(wx1, x0 + side), min(wy1, y0 + side)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = frame[sy0:sy1, sx0:sx1, :3]
        if sx1 > w * feed.SEARCH_LEFT and sy1 > h * feed.SEARCH_TOP:
            for r in feed.rows(frame):
                rx0, ry0 = max(0, r.x - FEED_PAD - x0), max(0, r.y - FEED_PAD - y0)
                rx1, ry1 = r.x + r.w + FEED_PAD - x0, r.y + r.h + FEED_PAD - y0
                if rx1 > 0 and ry1 > 0:
                    out[ry0:max(ry0, ry1), rx0:max(rx0, rx1)] = 0
    return out


def bar_strip(frame):
    return np.ascontiguousarray(frame[BAR_ROWS[0]:BAR_ROWS[1], :BAR_WIDTH, :3])


def on_path(seen, anchor, target, path_px: float = PATH_PX, same_px: float = SAME_PX) -> list:
    """[x, y, confidence] of every sighting within `path_px` of the segment
    anchor -> target, the target itself (within `same_px`) left out."""
    ax, ay = anchor
    tx, ty = target
    dx, dy = tx - ax, ty - ay
    length2 = float(dx * dx + dy * dy) or 1.0
    out = []
    for s in seen or ():
        sx, sy = float(s.x), float(s.y)
        if (sx - tx) ** 2 + (sy - ty) ** 2 <= same_px ** 2:
            continue
        t = max(0.0, min(1.0, ((sx - ax) * dx + (sy - ay) * dy) / length2))
        px, py = ax + t * dx, ay + t * dy
        if (sx - px) ** 2 + (sy - py) ** 2 <= path_px ** 2:
            out.append([int(sx), int(sy), round(float(getattr(s, "confidence", 0.0)), 3)])
    return out


@dataclass
class _Pending:
    begun: float
    meta: dict
    decide: np.ndarray
    bar_before: np.ndarray | None
    ring: list = field(default_factory=list)          # (t, jpeg bytes)
    finished: float | None = None


class TypedCapture:
    """The hook. `begin` at a chase's lesson, `finish` at its end, `heard`
    with every feed read. Never raises into the caller."""

    def __init__(self, root, ring=None, clock=time.monotonic,
                 max_captures: int = MAX_CAPTURES, max_bytes: int = MAX_BYTES,
                 allowed=None):
        self.root = Path(root)
        self.ring = ring
        self.clock = clock
        self.max_captures = int(max_captures)
        self.max_bytes = int(max_bytes)
        self.allowed = allowed            # storage.frames_allowed by default
        self.feed: collections.deque = collections.deque(maxlen=FEED_KEPT)
        self._pending: _Pending | None = None
        self._waiting: _Pending | None = None      # finished, no pickup yet
        self._written: tuple[float, Path] | None = None
        self._last_begin: float | None = None       # the latest chase's start
        self._last_arrived: float | None = None     # the latest chase that reached its token
        self._lock = threading.Lock()
        self._io = threading.Lock()                 # one write at a time (`heard`'s thread)
        self._seq = 0
        self.saved = self.skipped = self.rotated = 0
        self._sizes: collections.OrderedDict = collections.OrderedDict()
        try:
            for d in sorted(p for p in self.root.iterdir() if p.is_dir()):
                self._sizes[d.name] = sum(f.stat().st_size for f in d.iterdir())
        except OSError:
            pass

    # ---- the chase ------------------------------------------------------------
    def begin(self, frame, at: float, x: int, y: int, *, box=None, kind: str = "",
              seen=(), anchor=None, attempt=None, detector=None) -> bool:
        """The deciding frame of a chase at (x, y). False when nothing is kept
        for it (no frame, the chat may be open)."""
        try:
            self._pending = None
            prev = self._last_arrived
            with self._lock:
                self._last_begin = at
            if frame is None or chat_may_be_open(frame):
                self.skipped += frame is not None
                return False
            h, w = frame.shape[:2]
            anchor = anchor or (w // 2, h // 2)
            x0, y0, side = crop_box(x, y, box)
            before = [(t, text) for t, text in list(self.feed) if t <= at]
            ring = self.ring.between(at - WINDOW_S, at) if self.ring is not None else []
            meta = {
                "at": time.time(), "attempt": attempt, "kind": kind,
                "detector": None if detector is None else round(float(detector), 3),
                "point": [int(x), int(y)], "box": list(map(int, box)) if box else None,
                "anchor": [int(anchor[0]), int(anchor[1])], "frame_wh": [int(w), int(h)],
                "crop": [x0, y0, side], "seen": len(seen or ()),
                "on_path": on_path(seen, anchor, (x, y)),
                "feed_before": before[-1][1] if before else "",
                # every read of the line's life before it (a credit read
                # once and missed on the last read is still not new), and
                # how long since the chase before reached its token: that
                # pickup's line can first be read inside this chase's window
                "feed_prior": [text for t, text in before if t >= at - FEED_LINE_S],
                "prev_s": None if prev is None else round(at - prev, 2),
            }
            self._pending = _Pending(begun=at, meta=meta, decide=world_crop(frame, x0, y0, side),
                                     bar_before=bar_strip(frame), ring=ring)
            return True
        except Exception:
            self._pending = None
            return False

    def finish(self, after_frame, *, arrived: bool, outcome: str = "", evidence: str = "",
               sight: str = "", sight_evidence: str = "") -> Path | None:
        """The chase is over. Writes the capture when a pickup landed -- the
        HUD or sight verdict "collected", or a feed credit since it began --
        else keeps it FEED_GRACE_S for a late credit (`heard`). A chase that
        never reached its token keeps nothing: it cannot be labelled."""
        try:
            p, self._pending = self._pending, None
            now = self.clock()
            if arrived:
                self._last_arrived = now
            if p is None or not arrived:
                return None
            p.finished = now
            p.meta.update(arrived=bool(arrived), outcome=outcome, evidence=evidence,
                          sight=sight, sight_evidence=sight_evidence,
                          seconds=round(now - p.begun, 2))
            p.meta["bar_after"] = (after_frame is not None and not chat_may_be_open(after_frame))
            if p.meta["bar_after"]:
                p.meta["_bar_after"] = bar_strip(after_frame)
            why = ("hud" if outcome == "collected" else "sight" if sight == "collected"
                   else "feed" if self._credit_since(p.begun) else "")
            if not why:
                with self._lock:
                    self._waiting = p
                return None
            return self._write(p, why)
        except Exception:
            return None

    def drop(self) -> None:
        """The chase says nothing (the owner took the controls): keep nothing.
        Their walk may have picked something up: the next chase's credits are
        as doubtful as after a chase that arrived."""
        self._pending = None
        self._last_arrived = self.clock()

    def heard(self, text: str) -> None:
        """Every feed read (vision/whereami on_text), from the reader's
        thread. A credit within FEED_GRACE_S of a chase's end writes the
        capture that was waiting for one, or joins the one just written."""
        try:
            now = self.clock()
            line = " ".join(str(text).split())
            self.feed.append((now, line))
            if not CREDIT.search(line):
                return
            with self._lock:
                waiting, self._waiting = self._waiting, None
                written = self._written
            if waiting is not None and now - waiting.finished <= FEED_GRACE_S:
                self._write(waiting, "feed")
            elif written is not None and now - written[0] <= FEED_GRACE_S:
                meta = json.loads((written[1] / "meta.json").read_text(encoding="utf-8"))
                meta["feed"] = self._feed_rows(meta["begun_mono"])
                meta["next_dt"] = self._next_dt(meta["begun_mono"])
                (written[1] / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        except Exception:
            pass

    # ---- writing -----------------------------------------------------------------
    def _credit_since(self, t0: float) -> bool:
        return any(t >= t0 and CREDIT.search(text) for t, text in list(self.feed))

    def _next_dt(self, begun: float) -> float | None:
        """Seconds from this chase's start to the next chase's, if one began:
        reads from then on can hold that chase's credit (`label` stops there)."""
        with self._lock:
            nxt = self._last_begin
        return round(nxt - begun, 2) if nxt is not None and nxt > begun else None

    def _feed_rows(self, begun: float) -> list:
        return [[round(t - begun, 2), text] for t, text in list(self.feed) if t >= begun]

    def _write(self, p: _Pending, why: str) -> Path | None:
        with self._io:
            return self._write_locked(p, why)

    def _write_locked(self, p: _Pending, why: str) -> Path | None:
        from ..telemetry import storage
        allowed = self.allowed or storage.frames_allowed
        if not allowed(self.root):
            return None
        stamp = time.strftime('%Y%m%d-%H%M%S')
        out = self.root / f"{stamp}-{self._seq:04d}"
        while out.exists():                 # a restart within the same second
            self._seq += 1
            out = self.root / f"{stamp}-{self._seq:04d}"
        self._seq += 1
        try:
            out.mkdir(parents=True, exist_ok=True)
            meta = dict(p.meta)
            bar_after = meta.pop("_bar_after", None)
            x0, y0, side = meta["crop"]
            cv2.imwrite(str(out / "decide.jpg"), p.decide, JPEG)
            frames = []
            for i, (t, data) in enumerate(p.ring):
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if img is None or chat_may_be_open(img):
                    continue
                name = f"f{i:02d}.jpg"
                cv2.imwrite(str(out / name), world_crop(img, x0, y0, side), JPEG)
                frames.append([name, round(t - p.begun, 3)])
            if p.bar_before is not None:
                cv2.imwrite(str(out / "bar_before.png"), p.bar_before)
            if bar_after is not None:
                cv2.imwrite(str(out / "bar_after.png"), bar_after)
            meta.update(why=why, frames=frames, begun_mono=p.begun,
                        feed=self._feed_rows(p.begun), next_dt=self._next_dt(p.begun))
            (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        except (OSError, cv2.error):
            shutil.rmtree(out, ignore_errors=True)
            return None
        with self._lock:
            self._written = (p.finished or self.clock(), out)
        self.saved += 1
        self._sizes[out.name] = sum(f.stat().st_size for f in out.iterdir())
        self._rotate()
        return out

    def _rotate(self) -> None:
        """The oldest captures go until both caps hold again."""
        while self._sizes and (len(self._sizes) > self.max_captures
                               or sum(self._sizes.values()) > self.max_bytes):
            name, _size = self._sizes.popitem(last=False)
            shutil.rmtree(self.root / name, ignore_errors=True)
            self.rotated += 1

    def describe(self) -> str:
        mb = sum(self._sizes.values()) / 1e6
        return (f"typed captures: {self.saved} kept this run, {len(self._sizes)} on disk "
                f"({mb:.0f} MB), {self.rotated} rotated out, {self.skipped} skipped (chat)")


# ---- labelling (scripts/label_typed.py) ----------------------------------------------
# A credit always carries a "+" and a number (run_farm CREDIT).
CREDIT = re.compile(r"\+\s?[\d,]+")
# ONE CREDIT, AS TESSERACT READS IT. MEASURED 2026-10-27 on the 97 feed reads
# with a "+N" in the reason.txt of the 100 token windows: "+" read as "#" or
# "t", OCR junk between the number and the item ("+395'Honey", "+900—Honey"),
# "(from" read "rom" or "fram". 86 of the 97 parse; the rest are
# `unreadable` and make a capture label nothing.
CREDIT_LINE = re.compile(r"[+#t]\s?(\d[\d,.]*)[^A-Za-z(+#]{0,4}([A-Za-z][A-Za-z ]*?)"
                         r"\s*\(?\s*f?r[oa]m\s+([^)]+)\)")
# A "+N" that is no credit: the battle points of a kill line.
NOT_CREDIT = re.compile(r"\+\s?\d+[^A-Za-z]{0,3}Battle", re.IGNORECASE)
# The same line read twice is one credit: OCR drifts between reads, so a
# credit is its (item, source) and a line counts as new only when that pair
# was not on the read before the chase with the same amount.
TOKEN_LINK = "token link"


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", text.lower()).split())


def _singular(word: str) -> str:
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def credits(text: str) -> list[tuple[str, str, str]]:
    """(amount digits, item, source) of every credit line in one feed read."""
    out = []
    for amount, item, source in CREDIT_LINE.findall(text or ""):
        item = " ".join(_singular(w) for w in _words(item).split())
        if item:
            out.append((re.sub(r"\D", "", amount), item, _words(source)))
    return out


def unreadable(text: str) -> int:
    """The "+N" credits of a read that `credits` cannot parse."""
    plus = len(CREDIT.findall(text or "")) - len(NOT_CREDIT.findall(text or ""))
    return max(0, plus - len(credits(text)))


def new_credits(before, reads) -> list[tuple[str, str]]:
    """The distinct (item, source) credits the reads after the chase began
    show that the read(s) before it did not. `before`: one read or a list."""
    old = {c for text in ([before] if isinstance(before, str) else before)
           for c in credits(text)}
    seen: list[tuple[str, str]] = []
    for text in reads:
        for c in credits(text):
            if c not in old and c[1:] not in seen:
                seen.append(c[1:])
    return seen


_FIELDS: dict | None = None


def field_source(source: str) -> bool:
    """The credit's "(from ...)" names a field the knowledge base knows: a
    token picked up in it. MEASURED 2026-10-27 (review) on feed reads every
    ~3 s of the 40 token-school windows: of 29 new credits, 14 named no
    field -- Cub Buddy (treats), Leaves, Sprout, a Mantis's drop, a gift --
    and arrive in a chase's window whatever was chased."""
    global _FIELDS
    from ..vision import whereami
    if _FIELDS is None:
        import hivemind
        _FIELDS = whereami.field_names(
            Path(hivemind.__file__).resolve().parents[2] / "data/knowledge/world.yaml")
    return whereami.field_in(f"(from {source})", _FIELDS) is not None


def item_label(item: str) -> str:
    """The typed head's name for a credited item: honey, else item_<slug>."""
    return "honey" if item == "honey" else "item_" + item.replace(" ", "_")


# A TILE ON THE BAR: an icon's square has a step at its top or bottom edge
# that the rows beside it do not (`edge_step`: the step over the texture next
# to it). MEASURED 2026-10-27 on 3,360 slots of the 40 token-school windows:
# 1,378 under 1.0 (scenery), 99 from 1.0 to 2.5, 1,883 over 2.5. Icons abut
# from x = 0, so every slot left of the last one that steps is an icon too
# (a flame on dark red, a light icon on white sky step weakly).
EDGE_MIN = 2.0
# THE SAME ICON, by the HOG of the whole 38 px square (cosine distance): the
# drain dims an icon's top and many icons let the world show through, which
# grey levels do not survive. MEASURED 2026-10-27 on frames 4 s apart in the
# 40 token-school windows: one slot's own tile <= 0.074 in 90% of 727 pairs
# (the rest are mostly slots an icon came or went from), other slots' tiles
# <= 0.074 in 0.7% of 4,802; the 5th percentile of other icons is 0.169.
# Between the two a pair is UNCLEAR, and a bar with an unclear pair labels
# nothing (`bar_changes`).
SAME_ICON = 0.08
OTHER_ICON = 0.17
GAP = OTHER_ICON / 2           # align(): a match is cheaper than a gap pair below OTHER_ICON
# The slot after the last icon must be scenery beyond doubt: under 1.0 held
# 1,378 of the 1,476 slots under 2.5 in the count above.
SCENERY_MAX = 1.0
# ponytail: a guess at JPEG noise on an unchanged count (mean |difference| of
# the text corner); the misread it guards against (x21 read twice, once
# higher) was seen once on the held-out pairs.
TEXT_SAME = 12.0
_HOG = cv2.HOGDescriptor((32, 32), (16, 16), (8, 8), (8, 8), 9)


def edge_step(g, i: int) -> float:
    """How sharply slot i's square stands out of the rows round it: the step
    across its top or bottom edge over the rows' own texture beside it."""
    from ..vision import buffs
    x0, x1 = i * buffs.ICON + 2, (i + 1) * buffs.ICON - 2
    top, bottom = BAR_PAD, BAR_PAD + buffs.ICON

    def d(r):                               # mean |row r - row r+1|
        return float(np.abs(g[r, x0:x1] - g[r + 1, x0:x1]).mean())
    return max(d(top - 1) / (d(top) + 4.0), d(bottom - 1) / (d(bottom - 2) + 4.0))


def occupied(strip) -> list:
    """The icon tiles of a bar strip (bar_strip), left to right: every slot
    up to the last one whose square steps out of the scenery."""
    from ..vision import buffs
    g = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY).astype(np.float32)
    n = BAR_WIDTH // buffs.ICON
    last = max((i for i in range(n) if edge_step(g, i) >= EDGE_MIN), default=-1)
    return [strip[BAR_PAD:BAR_PAD + buffs.ICON, i * buffs.ICON:(i + 1) * buffs.ICON]
            for i in range(last + 1)]


def _hog(tile):
    g = cv2.cvtColor(cv2.resize(tile, (32, 32), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    h = _HOG.compute(g).reshape(-1)
    return h / (np.linalg.norm(h) + 1e-6)


def icon_distance(a, b) -> float:
    """1 - cosine of the two squares' HOGs (SAME_ICON, OTHER_ICON)."""
    return float(1.0 - _hog(a) @ _hog(b))


def icon_name(tile) -> str:
    """haste / melody by vision/buffs' templates, else buff_unnamed."""
    from ..vision import buffs
    canvas = np.zeros((buffs.BAR_BOTTOM, buffs.ICON, 3), np.uint8)
    canvas[buffs.BAR_TOP:] = tile
    for name in ("haste", "melody"):
        if buffs.find_all(canvas, name):
            return name
    return "buff_unnamed"


def stack_count(tile) -> int | None:
    """The icon's stacks: no count written is one stack (vision/buffs), an
    unreadable one None."""
    from ..vision import buffs
    return buffs.stacks(tile) if buffs.glyphs(tile) else 1


def _text_moved(a, b) -> bool:
    """The stack text's corner (vision/buffs TEXT_ROWS, TEXT_LEFT) changed:
    a count read higher on the same pixels is a misread, not a stack."""
    from ..vision import buffs
    r0, r1 = buffs.TEXT_ROWS
    x = buffs.TEXT_LEFT
    diff = np.abs(a[r0:r1, x:].astype(np.int16) - b[r0:r1, x:].astype(np.int16))
    return float(diff.mean()) > TEXT_SAME


def align(old: list, new: list, d=None, gap: float = GAP) -> list:
    """For each tile of `new`, the index of the `old` tile it is (None: it
    appeared). Order-keeping alignment at least cost, a match costing the
    icons' distance and a tile left unmatched on either side `gap`."""
    n, m = len(old), len(new)
    if d is None:
        d = np.array([[icon_distance(a, b) for b in new] for a in old]).reshape(n, m)
    cost = np.zeros((n + 1, m + 1))
    cost[:, 0] = np.arange(n + 1) * gap
    cost[0, :] = np.arange(m + 1) * gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i, j] = min(cost[i - 1, j] + gap, cost[i, j - 1] + gap,
                             cost[i - 1, j - 1] + d[i - 1, j - 1])
    out: list = [None] * m
    i, j = n, m
    while i and j:
        if np.isclose(cost[i, j], cost[i - 1, j - 1] + d[i - 1, j - 1]):
            out[j - 1] = i - 1
            i, j = i - 1, j - 1
        elif np.isclose(cost[i, j], cost[i, j - 1] + gap):
            j -= 1
        else:
            i -= 1
    return out


# HELD OUT, BY EYE, 2026-10-27: 200 pairs of frames 4 s apart from mob-sighting
# windows of 2026-09-24..10-26 that no rule here was tuned on (two earlier
# sets of 140 and 150 pairs were, and are not counted): 65 unclear (33%),
# 109 no pickup, 17 one, 9 more. Of the 17 one-pickup calls 16 were right
# and 1 could not be told by eye (a star x2 gone and a star with no count at
# the end: a new star, or the old one down a stack); of 20 random no-pickup
# calls 20 were right. Seen wrong on the tuning sets and still possible: a
# dark last icon on dark scenery (a flame) that no edge shows, and a Haste
# mid-slide when the bar shifts.
def bar_changes(before, after) -> tuple[list[tuple[str, int, str]], bool]:
    """((kind, slot, name) of every pickup the bar shows from `before` to
    `after`, clear). A pickup is an icon that was not there ("appeared") or
    one whose stack count rose ("stacked"); an icon that went is none. Not
    clear when a tile is neither surely the same icon as one before nor
    surely none of them (SAME_ICON..OTHER_ICON) and the templates do not
    name both. A Haste refill shows no new icon or count: see haste_refill."""
    from ..vision import buffs
    new = occupied(after)
    # BEFORE, AS FAR AS EITHER BAR REACHES: a last icon that did not step
    # out of its scenery (a flask on white sky) would otherwise come back as
    # "appeared"; a slot of scenery kept here can only go unmatched.
    old = [before[BAR_PAD:BAR_PAD + buffs.ICON, i * buffs.ICON:(i + 1) * buffs.ICON]
           for i in range(max(len(occupied(before)), len(new)))]
    g = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # AND AFTER, ONLY WHERE THE NEXT SLOT IS SURELY SCENERY: one that steps a
    # little may be a last icon the edge did not see, a pickup this would miss.
    clear = len(new) >= BAR_WIDTH // buffs.ICON or edge_step(g, len(new)) <= SCENERY_MAX
    d = np.array([[icon_distance(a, b) for b in new] for a in old]).reshape(len(old), len(new))
    names_old = [icon_name(t) for t in old]
    names_new = [icon_name(t) for t in new]
    for i, a in enumerate(names_old):          # the templates know these two
        for j, b in enumerate(names_new):
            if a == b != "buff_unnamed":
                d[i, j] = 0.0
    out = []
    for j, k in enumerate(align(old, new, d)):
        if k is None:
            clear &= bool(not len(old) or d[:, j].min() >= OTHER_ICON or names_new[j] != "buff_unnamed")
            out.append(("appeared", j, names_new[j]))
            continue
        clear &= bool(d[k, j] <= SAME_ICON)
        a, b = stack_count(old[k]), stack_count(new[j])
        if a is None or b is None:
            clear = False
        elif b > a and _text_moved(old[k], new[j]):
            out.append(("stacked", j, names_new[j]))
    return out, clear


def haste_refill(before, after) -> bool:
    """The Haste's square refilled by brain/school.HASTE_REFILL_S or more."""
    from ..vision import buffs
    from .school import HASTE_REFILL_S

    def left(strip):
        canvas = np.zeros((BAR_ROWS[1], BAR_WIDTH, 3), np.uint8)
        canvas[BAR_ROWS[0]:] = strip
        h = buffs.haste(canvas)
        return h.remaining_s if h.present else None
    a, b = left(before), left(after)
    return a is not None and b is not None and b - a >= HASTE_REFILL_S


def label(meta: dict, bar_before=None, bar_after=None) -> tuple[str | None, str, list]:
    """(label or None, why, changes) of one capture: a label only when the
    chase reached its token and no other was near the walk, and exactly one
    change happened -- a new feed credit, a buff icon that appeared or
    stacked, a Haste refill, or a honey or pollen lump the feed did not
    credit. No bar before and after, or one unclear, labels nothing: a buff
    it cannot see could be the second change. A feed credit counts only
    when it names a field, was on no read of the line's life before the
    chase, was read before the next chase began, and the chase before did
    not reach its token within FEED_GRACE_S; any other credit refuses."""
    if not meta.get("arrived"):
        return None, "the chase never reached it", []
    if meta.get("on_path"):
        return None, f"{len(meta['on_path'])} other token(s) near the walk", []
    changes: list[tuple[str, str]] = []
    # THE FEED WINDOW ENDS where the next chase began: from then on a read
    # can hold that chase's credit.
    nxt = meta.get("next_dt")
    reads = [text for dt, text in meta.get("feed") or ()
             if dt >= 0 and (nxt is None or dt < nxt)]
    if any(unreadable(t) > unreadable(meta.get("feed_before", "")) for t in reads):
        return None, "a feed credit it cannot read", changes
    fed = new_credits([meta.get("feed_before", "")] + list(meta.get("feed_prior") or ()), reads)
    for item, source in fed:
        if source == TOKEN_LINK:
            changes.append(("feed", "token_link"))
        elif field_source(source):
            changes.append(("feed", item_label(item)))
        else:                   # Cub Buddy, Leaves, a Sprout, a mob: not surely this token's
            return None, f"a credit from {source or 'nowhere read'}", changes
    prev = meta.get("prev_s")
    if fed and prev is not None and prev < FEED_GRACE_S:
        # THE CHASE BEFORE reached its token prev_s ago and its line can be
        # read first now (the builder's own FEED_GRACE_S, the other way).
        # MEASURED 2026-10-27 (review, var/school-coins lessons.jsonl): half
        # of all chases begin within 3.5 s of the one before.
        return None, "a credit the chase before may have earned", changes
    if bar_before is None or bar_after is None:
        return None, "no buff bar before and after", changes
    bar, clear = bar_changes(bar_before, bar_after)
    if not clear:
        return None, "the buff bar is unclear", changes
    changes += [("bar", name) for _kind, _slot, name in bar]
    if not any(name == "haste" for _src, name in changes) and haste_refill(bar_before, bar_after):
        changes.append(("bar", "haste"))
    evidence = str(meta.get("evidence") or "")
    if evidence.startswith("honey rose") and not any(n == "honey" for _s, n in changes):
        changes.append(("hud", "honey"))
    if evidence.startswith("pollen rose"):
        changes.append(("hud", "pollen"))
    if len(changes) != 1:
        return None, f"{len(changes)} changes", changes
    name = changes[0][1]
    if name in ("pollen", "token_link"):
        return None, f"a {name.replace('_', ' ')} change names no token", changes
    return name, "one token reached, one change", changes

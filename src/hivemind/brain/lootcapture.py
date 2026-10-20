"""Loot labels, kept AT THE MOMENT the reward feed names a mob's drop.

THE PROBLEM. The feed names every drop a kill leaves -- "+1 Treat (from
Ladybug)", "+1 Royal Jelly (from Sprout)" -- and run_farm writes each one to
var/mob_drops.jsonl (act/bugrun.FeedDrops), but never with the frame: the
loot chases (bugrun.loot_by_sight) see every drop as a plain "coin", and the
typed head (vision/tokentypes) refuses a mob's credit (brain/typedcapture
label: "not surely this token's"). So nothing can learn what a Royal Jelly
on the ground looks like.

WHAT IS KEPT, per feed read that brings a new drop (`dropped`): crops round
the character of the black-box frames (telemetry/incidents.between) of the
LOOKBACK_S before the read, one every PITCH_S, the buff bar of the first
and last of them, the read's text and the read before it, and the drops. Under var/school-loot/<stamp>-<n>/. `label` (run
by scripts/label_loot.py) names a crop's coin only where exactly one credit
is new in the read and exactly one coin went from beside the character.

MEASURED 2026-10-27 on var/mob_kills.jsonl + var/mob_drops.jsonl (3-27 Oct):
a Bond line is on the kill's own read (4,859 of 6,184 within 0.5 s, median
0.0 s): it is given, not picked up (GIVEN), so it keeps nothing. Honey and the
items come a median 6.1 s after the kill (p90 18 s): walked onto.

CHEAP. Nothing is captured for it: the frames are the black box's. A read
with no drop writes nothing. MEASURED 2026-10-27 on 12 real black-box
windows, niced beside the live bot: `dropped` 71 ms median, 97 max (14
JPEG decodes, crops and writes), on the feed reader's thread, 10-160
times a day. Only while learn.loot_capture is on (off by
default).

BOUNDED. MAX_CAPTURES folders and MAX_BYTES on disk; the oldest go first.
telemetry/storage.frames_allowed is asked before every write.

PRIVATE. No whole frame is written. Crops are typedcapture.world_crop's: cut
inside the detector's WORLD box (vision/coins), so the top bar, the menu
column, the hotbar and the chat's corner are never in them, and the feed
pills that reach into it are blacked out (a pill is the label: a model would
learn to read it). A frame where the chat may be open is not used. What is
NOT masked: another player's overhead name inside the crop, as in the
school's crops today.
"""
from __future__ import annotations

import collections
import json
import shutil
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from . import typedcapture as tc

DIR = "school-loot"
SETTING = "learn.loot_capture"
# GIVEN, NOT PICKED UP (see the docstring): no coin, and no second pickup.
GIVEN = frozenset({"bond"})
# AND NOT KEPT: honey from a mob, the commonest coin, which the typed head
# already learns from field credits (docs/pending/ai-tokens-typed.md, 42 test
# rows); 791 of the 1,270 picked-up drop lines of 20-27 Oct were honey.
SKIP = GIVEN | {"honey"}
# THE FRAMES BEFORE THE READ. The feed is read every ~3 s (vision/whereami
# DEFAULT_EVERY) and tesseract takes ~0.2 s (vision/feed), so the pickup was
# in the 3.2 s before the read's text arrived; a second more shows the coin
# before the walk reached it.
LOOKBACK_S = 4.0
PITCH_S = 0.25
# THE CROP: a square round the character (act/chase ANCHOR), HALF px each
# side. A coin is walked onto within act/chase ARRIVED_PIXELS (110) of it.
HALF = 256
# ON DISK. MEASURED 2026-10-27 on the 44 backfilled captures
# (scripts/label_loot.py --backfill): 0.76 MB a capture (13-14 crops). The
# reads this keeps (a drop not Bond, not honey) were 22 a day on 23-26 Oct,
# 160 on 20 Oct (var/mob_drops.jsonl; it depends on the field farmed), so
# the byte cap keeps 2.5 days at the busiest and about 18 at today's rate.
MAX_CAPTURES = 1000
MAX_BYTES = 300 * 1024 * 1024
JPEG = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
READS_KEPT = 4


class LootCapture:
    """The hook: `heard` with every feed read, `dropped` with each new drop
    of that read (act/bugrun.FeedDrops). Never raises into the caller."""

    def __init__(self, root, ring=None, clock=time.monotonic,
                 max_captures: int = MAX_CAPTURES, max_bytes: int = MAX_BYTES,
                 allowed=None):
        self.root = Path(root)
        self.ring = ring
        self.clock = clock
        self.max_captures = int(max_captures)
        self.max_bytes = int(max_bytes)
        self.allowed = allowed            # storage.frames_allowed by default
        # ONLY WHAT `label` CAN NAME. MEASURED 2026-10-27 (review) on
        # var/mob_drops.jsonl: 325 of the 3,098 drop lines past SKIP name no
        # item of the mob table -- 148 "honex" and more tesseract misreads of
        # honey, plus a few unlisted drops -- and label refuses those, so
        # their capture was only disk. Empty when the table cannot be read:
        # then nothing is filtered.
        try:
            self.known = known_items()
        except Exception:
            self.known = frozenset()
        self.reads: collections.deque = collections.deque(maxlen=READS_KEPT)
        self._open: tuple[float, Path] | None = None    # this read's capture
        self._io = threading.Lock()
        self._seq = 0
        self.saved = self.skipped = self.rotated = 0
        self._sizes: collections.OrderedDict = collections.OrderedDict()
        try:
            for d in sorted(p for p in self.root.iterdir() if p.is_dir()):
                self._sizes[d.name] = sum(f.stat().st_size for f in d.iterdir())
        except OSError:
            pass

    def heard(self, text: str) -> None:
        try:
            self.reads.append((self.clock(), " ".join(str(text).split())))
        except Exception:
            pass

    def dropped(self, mob: str, item: str, amount: int, *, attempt=None,
                field=None) -> Path | None:
        """One new drop of the latest read: the read's capture, written on its
        first drop and joined by the rest. None when nothing is kept."""
        try:
            if item in SKIP or not self.reads or self.ring is None:
                return None
            if self.known and _singular(item) not in self.known:
                return None
            with self._io:
                return self._dropped(mob, item, amount, attempt, field)
        except Exception:
            return None

    def _dropped(self, mob, item, amount, attempt, field) -> Path | None:
        read_at, text = self.reads[-1]
        drop = [str(mob), str(item), int(amount)]
        if self._open is not None and self._open[0] == read_at:
            meta_path = self._open[1] / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["drops"].append(drop)
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            return self._open[1]
        from ..telemetry import storage
        if not (self.allowed or storage.frames_allowed)(self.root):
            return None
        picked, last = [], None
        for t, data in self.ring.between(read_at - LOOKBACK_S, read_at):
            if last is None or t - last >= PITCH_S - 1e-6:
                picked.append((t, data))
                last = t
        if not picked:
            return None
        before = [(t, s) for t, s in list(self.reads)[:-1]]
        stamp = time.strftime('%Y%m%d-%H%M%S')
        out = self.root / f"{stamp}-{self._seq:04d}"
        while out.exists():                 # a restart within the same second
            self._seq += 1
            out = self.root / f"{stamp}-{self._seq:04d}"
        self._seq += 1
        frames, meta = [], None
        try:
            out.mkdir(parents=True, exist_ok=True)
            for i, (t, data) in enumerate(picked):
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if img is None or tc.chat_may_be_open(img):
                    self.skipped += img is not None
                    continue
                if meta is None:
                    meta = _frame_meta(img)
                    cv2.imwrite(str(out / "bar_first.png"), tc.bar_strip(img))
                cv2.imwrite(str(out / "bar_last.png"), tc.bar_strip(img))
                x0, y0, side = meta["crop"]
                name = f"f{i:02d}.jpg"
                cv2.imwrite(str(out / name), tc.world_crop(img, x0, y0, side), JPEG)
                frames.append([name, round(t - read_at, 3)])
            if meta is None:
                shutil.rmtree(out, ignore_errors=True)
                return None
            meta.update(at=time.time(), attempt=attempt, field=field, drops=[drop],
                        feed=text, feed_before=before[-1][1] if before else "",
                        feed_before_dt=round(before[-1][0] - read_at, 2) if before else None,
                        frames=frames)
            (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        except (OSError, cv2.error, ValueError):
            shutil.rmtree(out, ignore_errors=True)
            return None
        self._open = (read_at, out)
        self.saved += 1
        self._sizes[out.name] = sum(f.stat().st_size for f in out.iterdir())
        while self._sizes and (len(self._sizes) > self.max_captures
                               or sum(self._sizes.values()) > self.max_bytes):
            name, _size = self._sizes.popitem(last=False)
            shutil.rmtree(self.root / name, ignore_errors=True)
            self.rotated += 1
        return out

    def describe(self) -> str:
        mb = sum(self._sizes.values()) / 1e6
        return (f"loot captures: {self.saved} kept this run, {len(self._sizes)} on disk "
                f"({mb:.0f} MB), {self.rotated} rotated out, {self.skipped} frames skipped (chat)")


def _singular(item) -> str:
    return " ".join(tc._singular(w) for w in str(item).split())


def _frame_meta(img) -> dict:
    from ..act import chase
    h, w = img.shape[:2]
    ax, ay = chase.anchor_of(w, h)
    return {"frame_wh": [int(w), int(h)], "anchor": [int(ax), int(ay)],
            "crop": [int(ax) - HALF, int(ay) - HALF, 2 * HALF]}


# ---- labelling (scripts/label_loot.py) ------------------------------------------
# A COIN AT THE CHARACTER: within this of the anchor it is being walked onto
# (act/chase ARRIVED_PIXELS 110, and the coin's own half side).
# ponytail: set by eye on the backfilled captures' sheet; measure on live ones.
AT_PX = 170
# AND GONE: no coin that near on this many looks after it, up to the read.
GONE_LOOKS = 2
# A COIN, NOT THE CHARACTER: only sightings this sure count, the owner's own
# chase cut (gather.chase_confidence 0.7, p 0.9984; vision/tokens).
MIN_CONFIDENCE = 0.7
# THE SAME COIN ON THE LOOK BEFORE: within this of it (a look is PITCH_S).
# ponytail: a guess at a walk's quarter-second on screen near the character.
STEP_PX = 80


def known_items(path=None) -> frozenset:
    """The drops data/knowledge/mobs.yaml measured (`drops:` keys), singular:
    an OCR misread ("honex") names nothing and labels nothing."""
    import yaml
    from ..datapaths import data
    doc = yaml.safe_load(Path(path or data("knowledge", "mobs.yaml")).read_text(encoding="utf-8"))
    out = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "drops" and isinstance(v, dict):
                    out.update(_singular(x) for x in v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(doc)
    return frozenset(out)


def credits(text: str) -> set:
    """(amount, item, source) of every "+N Item (from Source)" in one read,
    the item singular, as the drop log reads them (act/bugrun.DROPPED: it
    takes tesseract's plus read as a 1, which typedcapture.CREDIT_LINE does
    not -- MEASURED on the 99 backfilled reads, 41 of whose drops that one
    found no credit for). ponytail: a credit neither pattern reads is no
    second credit here; the coin rule below is the other guard."""
    from ..act import bugrun
    return {(m.group(1).replace(",", ""),
             " ".join(tc._singular(w) for w in m.group(2).lower().split()),
             " ".join(m.group(3).lower().split()))
            for m in bugrun.DROPPED.finditer(str(text or ""))}


def label(meta: dict, looks, known, bar_before=None, bar_after=None
          ) -> tuple[str | None, str, tuple | None]:
    """(label or None, why, (frame name, [x0, y0, x1, y1]) in crop pixels).

    `looks`: [(frame name, dt, [(x, y, side, confidence), ...])] for the
    capture's frames, in crop pixels; `bar_before` / `bar_after` the buff bar
    strips of its first and last frame (typedcapture.bar_strip). A label only
    when the read's one new credit (Bond aside) is the drop, an item the mob
    table knows; the buff bar shows no pickup of its own (a buff token gives
    no credit); and exactly one sure coin was beside the character on two
    looks in a row, the later its last there, with none there after it on
    the GONE_LOOKS or more looks up to the read."""
    old = credits(meta.get("feed_before", ""))
    new = sorted({c[1:] for c in credits(meta.get("feed", "")) if c not in old and c[1] not in GIVEN})
    drops = {(_singular(item), str(mob))
             for mob, item, _n in meta.get("drops") or () if item not in GIVEN}
    if len(new) > 1 or len(drops) > 1:
        return None, f"{max(len(new), len(drops))} credits in one read", None
    if not drops or not new:
        return None, "the read shows no new drop", None
    item = next(iter(drops))[0]
    if new[0][0] != item:
        return None, f"a credit for {new[0][0]} beside the {item} drop", None
    if item not in known:
        return None, "an item the drop table does not name", None
    if bar_before is None or bar_after is None:
        return None, "no buff bar before and after", None
    bar, clear = tc.bar_changes(bar_before, bar_after)
    if not clear:
        return None, "the buff bar is unclear", None
    if bar or tc.haste_refill(bar_before, bar_after):
        return None, "a buff token picked up too", None
    x0, y0, _side = meta["crop"]
    ax, ay = meta["anchor"][0] - x0, meta["anchor"][1] - y0
    looks = sorted(looks, key=lambda lk: lk[1])
    near = [[s for s in seen if s[3] >= MIN_CONFIDENCE
             and (s[0] - ax) ** 2 + (s[1] - ay) ** 2 <= AT_PX ** 2]
            for _name, _dt, seen in looks]
    last = max((i for i, n in enumerate(near) if n), default=None)
    if last is None:
        return None, "no coin beside the character", None
    if len(looks) - 1 - last < GONE_LOOKS:
        return None, "the coin beside the character did not go", None
    if len(near[last]) > 1:
        return None, f"{len(near[last])} coins beside the character", None
    x, y, side, _c = near[last][0]
    if last == 0 or not any((p[0] - x) ** 2 + (p[1] - y) ** 2 <= STEP_PX ** 2
                            for p in near[last - 1]):
        return None, "the coin beside the character was there on one look only", None
    h = side / 2.0
    box = [int(round(x - h)), int(round(y - h)), int(round(x + h)), int(round(y + h))]
    return tc.item_label(item), "one credit, one coin gone at the character", (looks[last][0], box)

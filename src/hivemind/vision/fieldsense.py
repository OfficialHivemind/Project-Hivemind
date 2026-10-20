"""Which field this looks like, and whether the character is still in one.

THE FEED STAYS THE AUTHORITY. `vision/whereami` only claims a field when the
game names it ("+590 Honey (from Pumpkin Patch)"), and nothing here changes
that. What the feed cannot do is speak between pickups: nothing at the end of
a walk out, a median 21 s later on arrival (84 walks, research `placerec`),
and nothing at all while the character drifts off the edge of a field. This
module answers in the gaps, with a number saying how often an answer like it
was right on nights it had never seen (DESIGN 8dz).

Two measurements, both on one 480x270 copy of the frame:

  LOOKS LIKE    a classifier over regional colour histograms. The frame is
                cut into a 4x3 grid, each cell gets an 18x3 hue-saturation
                histogram with the HUD, the reward feed, the hotbar and the
                character masked out, and one-vs-rest RBF SVMs (cv2.ml) score
                every class the gallery knows. MEASURED leave-one-night-out
                by scripts/train_fieldsense.py (data/models/fieldsense.json,
                2026-09-26: 2,246 feed-labelled frames of 11 places, 6
                nights): 91.4% top-1, and gating on the margin between the
                best two scores gives 99.3% precision at half the frames and
                97.3% at 90% (the research's own frames: 91.8% one-vs-rest,
                90.0% nearest neighbour, 91.2% one multi-class SVM,
                scratchpad fieldsense/exp2.py). DESIGN 8b's "colour
                histograms are useless for identity" tested ONE whole-screen
                histogram against a threshold, from the owner's moving
                camera; with the bot's fixed camera, a grid and a trained
                classifier the same signal separates the fields. It is still a
                prior and never a fix: `Look.sure` is the held-out precision of
                looks like this one, from the trainer's table, and None where
                the trainer could not measure one.
  FLOWER BED    the share of 96x96-px ground cells around the character that
                are flower bed rather than grass, path, wood or wall -- no
                training. White, red and blue petals count and yellow ones
                do not (the research's rule), and 31% of Sunflower's own
                frames are under the edge (Strawberry's 7%). MEASURED (research
                `fieldseg` edge_eval): AUC 0.940 in-field against off-field
                frames, 0.979 on the owner's own session; the trainer's
                frames 0.935 (1,908 field frames against 296 of the hive and
                the landmarks -- the only other places the game labels, so
                not the ground just past a field's edge, and not the next
                field's flowers). It is what says the pattern has walked the
                character off the flowers.

WHERE THE LABELS COME FROM. Only from the game: a frame is labelled with a
field when it lies between two reward-feed fixes that both name it no more
than 40 s apart (or within 2 s of one), with no hive or landmark panel within
20 s -- the feed also fires during a convert at the hive, naming a field the
character has left. The research labelled 145,675 saved frames that way
(vpr/label.py); `scripts/train_fieldsense.py` builds the seed gallery with the
same rule, and `Labeller` applies it live, so every night the bot plays adds
the frames the feed has just labelled to `var/fieldsense/` and the next
training uses them. That is what the research found limits it: 1 taught visit
per field gives 56-63%, 4 give 86%, 8 give 92% and 15 give 96% (placerec,
balanced over 6 fields). And the trainer measured it forward in time, each
attempt scored before it is taught: 83.6% by the gallery as the night began,
90.7% by one that learned the night's earlier attempts (1,648 frames).

WHAT IT COSTS. MEASURED by the trainer: a look (shrink, descriptor, the SVMs
and the flower bed) 5.8 ms median, 6.1 ms p95, on a 1920x1080 frame, one
thread; at LOOK_EVERY that is about 1.2% of one core. Training the 11 SVMs on
2,246 frames takes 2.6 s, so the gallery is retrained in the background as it
grows, at the lowest priority.
"""
from __future__ import annotations

import collections
import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..datapaths import data, var

# NO cv2.ml, SAID ONCE. MEASURED 2026-10-19 (the owner's 5th Windows run): pip's
# opencv-python on Python 3.14 has no `ml` module ("module 'cv2' has no
# attribute 'ml'") -- OpenCV 5 moved it to the contrib build [assumed from the
# version; Arch's opencv 5.0.0 is built with contrib and has it].
NO_ML = ("this OpenCV has no cv2.ml (install opencv-contrib-python in place of "
         "opencv-python) -- the field classifier stays off")

# The working size. Everything below was measured at a quarter of the
# client's 1920x1080 (IMREAD_REDUCED_COLOR_4 in the research, INTER_AREA
# from the live array here -- the same area average).
W, H = 480, 270
FULL_W, FULL_H = 1920, 1080

# ---- the descriptor ----------------------------------------------------------
#
# WHAT IS MASKED OUT, as fractions of the frame, MEASURED off 1920x1080 frames
# (research vpr/common.py `hud_mask`, sheet_mask.jpg):
#   the top strip: honey/pollen pills, menu, panel prompt     y < 0.075
#   the top-left buttons and the buff tray                    x < 0.19, y < 0.16
#   the hotbar and the bottom                                 y > 0.885
#   the reward feed's pills, bottom right (feed.SEARCH_*)     x > 0.80, y > 0.70
#   the character, at the orbit camera's centre               0.40 < x < 0.60,
#                                                             0.38 < y < 0.86
#   the '?' button, top right                                 x > 0.94, y < 0.16
# The run logs' "own body" line pins the character at (964, 550) of 1920x1080
# (run-434 to run-440), inside that box.
def _hud_mask(w: int = W, h: int = H) -> np.ndarray:
    m = np.ones((h, w), np.uint8)
    m[: int(0.075 * h), :] = 0
    m[: int(0.16 * h), : int(0.19 * w)] = 0
    m[int(0.885 * h):, :] = 0
    m[int(0.70 * h):, int(0.80 * w):] = 0
    m[int(0.38 * h): int(0.86 * h), int(0.40 * w): int(0.60 * w)] = 0
    m[: int(0.16 * h), int(0.94 * w):] = 0
    return m


MASK = _hud_mask()
# 4 columns x 3 rows, 18 hue x 3 saturation bins, pixels with V in (25, 245)
# only (black and blown-out pixels carry no hue). The research's `d_regions`,
# the best of seven descriptors it measured across nights (placerec: SIFT-VLAD
# 54.7%, ORB bag-of-words 38.1%, HOG 65.9%, the repo's whole-screen
# signature 78.3%, regional histograms 90.0%).
GRID = (4, 3)
HUE_BINS, SAT_BINS = 18, 3
V_MIN, V_MAX = 25, 245
DIM = GRID[0] * GRID[1] * HUE_BINS * SAT_BINS          # 648

# The SVMs' settings, the ones the research measured across nights (placerec
# eval_night.py: C=10, gamma=1 on Hellinger-normalised histograms, 91.2%
# multi-class); exp1.py gives the same 0.912 at C=10 and C=30, 0.915 at C=3
# and 0.898 at gamma=2, so nothing is balanced on a knife edge.
SVM_C = 10.0
SVM_GAMMA = 1.0


def shrink(frame) -> np.ndarray:
    """A BGR copy at W x H (from 1920x1080 BGR or BGRA, or already small)."""
    img = frame[:, :, :3] if frame.ndim == 3 and frame.shape[2] > 3 else frame
    if img.shape[1] == W and img.shape[0] == H:
        return np.ascontiguousarray(img)
    return cv2.resize(np.ascontiguousarray(img), (W, H),
                      interpolation=cv2.INTER_AREA)


def describe(small: np.ndarray) -> np.ndarray:
    """The 648-long regional hue-saturation descriptor of a W x H frame:
    per-cell histograms, square-rooted (Hellinger), then L2-normalised."""
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    value = hsv[:, :, 2]
    keep = ((MASK > 0) & (value > V_MIN) & (value < V_MAX)).astype(np.uint8)
    gx, gy = GRID
    out = []
    for j in range(gy):
        for i in range(gx):
            ys = slice(j * H // gy, (j + 1) * H // gy)
            xs = slice(i * W // gx, (i + 1) * W // gx)
            hist = cv2.calcHist([hsv[ys, xs]], [0, 1], keep[ys, xs],
                                [HUE_BINS, SAT_BINS], [0, 180, 0, 256]).ravel()
            total = float(hist.sum())
            out.append(np.sqrt(hist / total) if total > 0 else hist)
    vec = np.concatenate(out).astype(np.float32)
    return vec / (float(np.linalg.norm(vec)) + 1e-6)


# STORED AS BYTES. Every component is a square-rooted share in [0, 1], so
# 255 steps lose at most 0.002 per component; the trainer scores the
# quantised gallery, which is what runs. 648 bytes a frame instead of 2,592.
def quantise(vec: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(np.asarray(vec, np.float32) * 255.0), 0, 255).astype(np.uint8)


def unquantise(codes: np.ndarray) -> np.ndarray:
    vec = np.asarray(codes, np.float32) / 255.0
    norm = np.linalg.norm(vec, axis=-1, keepdims=True)
    return (vec / np.maximum(norm, 1e-6)).astype(np.float32)


# ---- the flower bed ----------------------------------------------------------
#
# A SECOND MASK, the research's own for this measure (fieldseg features.py),
# in W x H pixels: the top HUD (y < 22), the hotbar and bottom tray (y >= 243,
# 975 at full size), the reward feed (x >= 390, y >= 189), the top-right icons
# and the character with its bag label, CHAR.
VALID = np.ones((H, W), np.uint8)
VALID[:22, :] = 0
VALID[243:, :] = 0
VALID[189:, 390:] = 0
VALID[:30, 440:] = 0
CHAR = (190, 78, 300, 190)                  # x0, y0, x1, y1
VALID[CHAR[1]:CHAR[3], CHAR[0]:CHAR[2]] = 0
# The ground around the character's feet, cut into CELL x CELL cells: 24 px
# here is 96 px at full size, about one flower tile beside the feet.
GROUND = (110, 120, 380, 243)               # x0, y0, x1, y1
CELL = 24
_GMASK = np.zeros((H, W), np.uint8)
_GMASK[GROUND[1]:GROUND[3], GROUND[0]:GROUND[2]] = 1
_GMASK &= VALID
# A cell is FLOWER BED with at least this much grass AND this much petal
# (white/red/blue blobs); at least 60% of it must be unmasked to count at all.
# The research's measured rule (features.py `fieldness`).
BED_GRASS, BED_PETALS, CELL_VALID = 0.2, 0.015, 0.6
# A frame that is mostly black, or blown out, gives no opinion: dark share
# at least 0.5 after balancing (edge_eval), raw median brightness at least
# 0.95 (arrival_informative.txt: the camera clipped into something bright).
# Both were set after looking at the data, the research says so, and the
# trainer reports what share of frames they refuse.
DARK_NO_OPINION = 0.5
WHITEOUT_NO_OPINION = 0.95
_OPEN = np.ones((2, 2), np.uint8)


def _balance(hsv: np.ndarray) -> tuple[np.ndarray, float]:
    """Brightness scaled so the GRASS sits at V=160 (fields are lit very
    differently), or the 90th percentile at 200 without enough grass."""
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    ok = VALID.astype(bool)
    grass = ok & (h >= 35) & (h < 88) & (s >= 60) & (v >= 20)
    if grass.sum() >= 0.02 * ok.sum():
        ref = float(np.median(v[grass][::3]))
        gain = float(np.clip(160.0 / max(ref, 1.0), 0.7, 5.0))
    else:
        ref = float(np.percentile(v[ok][::5], 90))
        gain = float(np.clip(200.0 / max(ref, 1.0), 0.7, 5.0))
    out = hsv.copy()
    out[:, :, 2] = cv2.convertScaleAbs(v, alpha=gain)
    return out, gain


def _classes(hsv: np.ndarray) -> np.ndarray:
    """Per-pixel colour class: 0 grass, 1 white, 2 red, 3 blue petal, 6 dark,
    and the rest (grey, sky, purple, orange, yellow, other) as 7-10."""
    h = hsv[:, :, 0].astype(np.int16)
    s = hsv[:, :, 1].astype(np.int16)
    v = hsv[:, :, 2].astype(np.int16)
    lab = np.full(h.shape, 10, np.uint8)
    lab[(s < 60) & (v >= 60) & (v < 215)] = 7
    lab[(h >= 88) & (h < 106) & (s >= 60) & (v >= 180)] = 8
    lab[(h >= 130) & (h < 168) & (s >= 80) & (v >= 100)] = 9
    lab[(h >= 9) & (h < 20) & (s >= 100) & (v >= 110)] = 5
    lab[(h >= 20) & (h < 35) & (s >= 100) & (v >= 150)] = 4
    lab[(h >= 35) & (h < 88) & (s >= 60) & (v >= 70)] = 0
    lab[((h < 9) | (h >= 168)) & (s >= 120) & (v >= 150)] = 2
    lab[(h >= 100) & (h < 130) & (s >= 120) & (v >= 150)] = 3
    lab[(s < 60) & (v >= 215)] = 1
    lab[v < 60] = 6
    return lab


def _petals(lab: np.ndarray) -> np.ndarray:
    """Petal pixels, opened (drops 1-px laser lines and sparkles), with blobs
    over 1,200 px removed (speech bubbles, walls, snow, panels)."""
    m = ((lab == 1) | (lab == 2) | (lab == 3)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, _OPEN)
    k, cc, st, _ = cv2.connectedComponentsWithStats(m, connectivity=4)
    if k > 1:
        big = np.where(st[:, cv2.CC_STAT_AREA] > 1200)[0]
        big = big[big > 0]
        if big.size:
            m[np.isin(cc, big)] = 0
    return m


@dataclass(frozen=True)
class Bed:
    """The flower bed around the character in one frame."""
    share: float                 # of the valid ground cells, 0..1
    cells: int                   # valid ground cells looked at
    # Where the bed cells sit, relative to where ALL valid cells sit, in
    # full-size pixels (+x right, +y down the screen): the way to walk to
    # get deeper into the flowers. (0, 0) when none, or all, are bed.
    towards: tuple[float, float]
    dark: float                  # share of the frame that is dark, balanced
    raw_median: float            # median brightness before balancing, 0..1

    @property
    def informative(self) -> bool:
        return (self.cells > 0 and self.dark < DARK_NO_OPINION
                and self.raw_median < WHITEOUT_NO_OPINION)


def flower_bed(small: np.ndarray) -> Bed:
    """The research's `fieldness`, plus the direction of the bed cells."""
    raw = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hsv, _gain = _balance(raw)
    lab = _classes(hsv)
    ok = VALID.astype(bool)
    raw_median = float(np.median(raw[:, :, 2][ok])) / 255.0
    dark = float((lab[ok] == 6).mean())
    x0, y0, x1, y1 = GROUND
    ny, nx = (y1 - y0) // CELL, (x1 - x0) // CELL
    sl = (slice(y0, y0 + ny * CELL), slice(x0, x0 + nx * CELL))
    valid = _GMASK[sl].astype(np.float32)

    def cells(a):
        return a.reshape(ny, CELL, nx, CELL).sum(axis=(1, 3))

    counted = cells(valid)
    grass = cells((lab[sl] == 0) * valid) / np.maximum(counted, 1)
    petal = cells(_petals(lab)[sl] * valid) / np.maximum(counted, 1)
    good = counted >= CELL * CELL * CELL_VALID
    bed = good & (grass >= BED_GRASS) & (petal >= BED_PETALS)
    n = int(good.sum())
    towards = (0.0, 0.0)
    if n and 0 < int(bed.sum()) < n:
        rows, cols = np.mgrid[0:ny, 0:nx]
        cx = (x0 + (cols + 0.5) * CELL) * (FULL_W / W)
        cy = (y0 + (rows + 0.5) * CELL) * (FULL_H / H)
        towards = (float(cx[bed].mean() - cx[good].mean()),
                   float(cy[bed].mean() - cy[good].mean()))
    return Bed(share=float(bed.sum()) / max(n, 1), cells=n, towards=towards,
               dark=dark, raw_median=raw_median)


# ---- the classifier ----------------------------------------------------------

MODEL = data("models", "fieldsense.npz")
MODEL_NOTES = data("models", "fieldsense.json")
LIVE_DIR = var("fieldsense")

# HOW MANY TAUGHT FRAMES A CLASS KEEPS, newest visits first. The research's
# sampler (vpr/sample.py): at most 45 frames per class per attempt, 2.5 s
# apart so neighbours are not near-duplicates, and 700 per class -- about 15
# visits, where placerec measured 96% (8 visits 92%, 4 visits 86%). A
# rolling window rather than all of history, because the game changes (event
# decorations, BSS updates: the client log names the build) and the newest
# visits look most like tomorrow.
PER_ATTEMPT = 45
PER_CLASS = 700
THIN_SECONDS = 2.5
# A PLACE IS TAUGHT ONLY WITH AT LEAST THIS MANY VISITS BEHIND IT. MEASURED
# (placerec, balanced over 6 fields): 1 taught visit 56-63%, 2 visits 73-75%,
# 4 visits 86%. Below 4 a class mostly confuses the others; its frames are
# kept, and it is taught once its fourth visit is.
MIN_VISITS = 4
# A LOOK'S NUMBER NEEDS THIS MANY HELD-OUT PREDICTIONS BEHIND IT. With 20
# a measured 95% has a binomial standard error of 5 points; with fewer the
# trainer writes no number and the look gives no opinion on that class.
MIN_MEASURED = 20
# Live shards are loaded this many at a time before the gallery is compacted
# (`Gallery.compact`), so loading never holds more than this many attempts'
# frames beyond what trains: at most PER_ATTEMPT a class each.
COMPACT_EVERY = 50


@dataclass(frozen=True)
class Look:
    """One frame, looked at."""
    at: float
    field: str | None             # the best-scoring class, None untrained
    margin: float                 # best score minus the runner-up's
    second: str | None
    # The held-out precision of looks that named this class with a margin
    # like this one (the trainer's table): how often such a look was RIGHT
    # on a night the gallery had never seen. None: not measured.
    sure: float | None
    bed: Bed
    code: np.ndarray | None = field(default=None, repr=False, compare=False)

    @property
    def informative(self) -> bool:
        return self.bed.informative

    def names(self, place: str, trust: float) -> bool:
        """Does this look name `place`, as surely as `trust`?"""
        return (self.informative and self.field == place
                and self.sure is not None and self.sure >= trust)

    def doubts(self, place: str, trust: float) -> bool:
        """Does it name somewhere ELSE, as surely as `trust`?"""
        return (self.informative and self.field is not None
                and self.field != place and self.sure is not None
                and self.sure >= trust)

    def describe(self, trust: bool = True) -> str:
        """`trust=False` leaves the "N% right" out: the trust table is
        measured on gathering frames. MEASURED 2026-10-22 (vision review):
        walk-end frames, from another camera angle, were right only 714 of
        967 times (74%) at trust 0.95, and attempt-117x walk ends read
        "pepper at 1.0" at a sprinkler and "spider 0.98" at the blender."""
        bed = (f"{self.bed.share:.0%} flower bed around the character"
               if self.informative else "too dark or washed out to read")
        if self.field is None:
            return f"no classifier yet; {bed}"
        pretty = self.field.replace("_", " ")
        if not trust and self.sure is not None:
            return (f"looks most like {pretty} (no percentage: the trust table "
                    f"is for gathering frames, not walk ends); {bed}")
        if self.sure is None:
            return (f"looks most like {pretty} (not measured for it, so no "
                    f"opinion); {bed}")
        return (f"looks like {pretty} ({self.sure:.0%} of looks like this were "
                f"right on unseen nights); {bed}")


def night_of(epoch: float) -> str:
    """The research's night: the calendar date of the time minus 12 h, so one
    overnight session is one night."""
    return time.strftime("%m-%d", time.localtime(float(epoch) - 12 * 3600))


class Gallery:
    """Labelled descriptors: the trainer's seed plus what live runs added.

    Arrays, not objects: 648 bytes a frame. `rows()` is what trains."""

    def __init__(self):
        self.codes = np.zeros((0, DIM), np.uint8)
        self.labels: list[str] = []
        self.attempts: list[int] = []
        self.times: list[float] = []
        self.sources: list[str] = []

    def __len__(self) -> int:
        return len(self.labels)

    def extend(self, codes, labels, attempts, times, source: str) -> None:
        codes = np.asarray(codes, np.uint8).reshape(-1, DIM)
        if not len(codes):
            return
        self.codes = np.concatenate([self.codes, codes])
        self.labels += [str(x) for x in labels]
        self.attempts += [int(x) for x in attempts]
        self.times += [float(x) for x in times]
        self.sources += [source] * len(codes)

    def load(self, path: Path, source: str) -> int:
        """Add one .npz (the trainer's model or a live shard). Returns rows."""
        with np.load(path, allow_pickle=False) as z:
            codes = z["codes"]
            labels = [str(x) for x in z["labels"]]
            attempts = z["attempts"]
            times = z["times"]
        self.extend(codes, labels, attempts, times, source)
        return len(labels)

    def compact(self) -> int:
        """Drop what `rows` will never train on: a class's older visits past
        PER_CLASS. A class still short of MIN_VISITS keeps every frame (it is
        taught once its next visit arrives). Returns the rows dropped. Without
        it every live shard since the first would sit in memory -- a visit
        keeps at most PER_ATTEMPT frames of 648 bytes, but the shards grow by
        one per attempt, for good."""
        visits = collections.defaultdict(set)
        for label, attempt in zip(self.labels, self.attempts):
            visits[label].add(attempt)
        keep = set(int(i) for i in self.rows())
        keep |= {i for i, label in enumerate(self.labels)
                 if len(visits[label]) < MIN_VISITS}
        if len(keep) == len(self.labels):
            return 0
        idx = sorted(keep)
        dropped = len(self.labels) - len(idx)
        self.codes = self.codes[idx]
        for name in ("labels", "attempts", "times", "sources"):
            values = getattr(self, name)
            setattr(self, name, [values[i] for i in idx])
        return dropped

    def rows(self, per_class: int = PER_CLASS,
             per_attempt: int = PER_ATTEMPT) -> np.ndarray:
        """The indices that train: per class, the newest attempts first, at
        most `per_attempt` of each and `per_class` in all."""
        by = collections.defaultdict(list)
        for i, (label, attempt) in enumerate(zip(self.labels, self.attempts)):
            by[(label, attempt)].append(i)
        keep = []
        for label in sorted(set(self.labels)):
            if len({a for (lab, a) in by if lab == label}) < MIN_VISITS:
                continue
            visits = sorted((a for (lab, a) in by if lab == label),
                            key=lambda a: -max(self.times[i] for i in by[(label, a)]))
            taken = 0
            for a in visits:
                rows = by[(label, a)]
                if len(rows) > per_attempt:
                    step = len(rows) / float(per_attempt)
                    rows = [rows[int(k * step)] for k in range(per_attempt)]
                rows = rows[: max(0, per_class - taken)]
                keep += rows
                taken += len(rows)
                if taken >= per_class:
                    break
        return np.array(sorted(keep), np.int64)


class Classifier:
    """One-vs-rest RBF SVMs, cv2.ml. MEASURED one-vs-rest against one
    multi-class SVM on the research's frames, nights held out: 91.8% against
    91.2% top-1, and -- what the multi-class SVM cannot give at all -- a
    margin between the best two raw scores that ranks its own mistakes
    (99.1% precision at 50% coverage, exp2.py; the trainer's 99.3%)."""

    def __init__(self, classes: list[str], models: list, signs: list[float]):
        self.classes = list(classes)
        self.models = list(models)
        self.signs = list(signs)

    @classmethod
    def train(cls, X: np.ndarray, labels: list[str]) -> "Classifier":
        classes = sorted(set(labels))
        y = np.array([classes.index(x) for x in labels], np.int32)
        X = np.ascontiguousarray(X, np.float32)
        models, signs = [], []
        for c in range(len(classes)):
            svm = cv2.ml.SVM_create()
            svm.setType(cv2.ml.SVM_C_SVC)
            svm.setKernel(cv2.ml.SVM_RBF)
            svm.setC(SVM_C)
            svm.setGamma(SVM_GAMMA)
            svm.train(X, cv2.ml.ROW_SAMPLE, (y == c).astype(np.int32))
            # cv2.ml's RAW_OUTPUT sign depends on which label it met first,
            # so it is fixed once, against the model's own label predictions
            # on the rows it was trained on.
            raw = svm.predict(X, flags=cv2.ml.STAT_MODEL_RAW_OUTPUT)[1].ravel()
            said = svm.predict(X)[1].ravel() == 1
            signs.append(-1.0 if float(np.mean((raw < 0) == said)) > 0.5 else 1.0)
            models.append(svm)
        return cls(classes, models, signs)

    def scores(self, X: np.ndarray) -> np.ndarray:
        """(n, classes) signed decision values, larger = more like the class."""
        X = np.ascontiguousarray(np.asarray(X, np.float32).reshape(-1, DIM))
        out = np.empty((len(X), len(self.models)), np.float32)
        for c, (svm, sign) in enumerate(zip(self.models, self.signs)):
            out[:, c] = sign * svm.predict(
                X, flags=cv2.ml.STAT_MODEL_RAW_OUTPUT)[1].ravel()
        return out


def top_two(scores: np.ndarray, classes: list[str]):
    """(best class, margin over the runner-up, runner-up) of one score row."""
    order = np.argsort(-scores)
    best = classes[int(order[0])]
    if len(order) < 2:
        return best, float("inf"), None
    return (best, float(scores[order[0]] - scores[order[1]]),
            classes[int(order[1])])


class Trust:
    """The trainer's held-out precision table: per class, margin bands and
    how often a look in each band named the class correctly on a night the
    gallery had not seen. {class: [[lo, hi, precision, n], ...]}."""

    def __init__(self, table: dict | None = None):
        self.table = {str(k): [list(b) for b in v] for k, v in (table or {}).items()}

    def sure(self, place: str, margin: float) -> float | None:
        for lo, hi, precision, n in self.table.get(place, ()):
            lo = -np.inf if lo is None else lo
            hi = np.inf if hi is None else hi
            if lo <= margin < hi:
                return float(precision) if n >= MIN_MEASURED else None
        return None


class FieldSense:
    """The classifier and the flower-bed measure behind one `look`.

    It loads the trainer's gallery (data/models/fieldsense.npz) and every
    live shard in var/fieldsense/, and trains in the background, so a look
    taken before the SVMs exist still measures the flower bed. `add` takes
    the frames the feed has just labelled (see `Labeller`) and retrains once
    RETRAIN_AFTER have arrived."""

    # One visit's worth of new frames (PER_ATTEMPT) before training again.
    RETRAIN_AFTER = PER_ATTEMPT

    def __init__(self, model: Path | None = MODEL, notes: Path | None = MODEL_NOTES,
                 live_dir: Path | None = LIVE_DIR, attempt: int | None = None,
                 emit=None, clock=time.time):
        self.emit = emit or (lambda text: None)
        self.clock = clock
        self.gallery = Gallery()
        self.notes: dict = {}
        self.trust = Trust()
        self.classifier: Classifier | None = None
        self.live_dir = live_dir
        self.attempt = int(attempt) if attempt is not None else -1
        self._lock = threading.Lock()
        self._training = False
        self._fresh = 0
        self._shard: dict[str, list] = {"codes": [], "labels": [], "attempts": [],
                                        "times": []}
        self._rows: list[int] = []          # shard slot -> gallery row
        self._unsaved = 0
        self.problems: list[str] = []
        if notes is not None:
            try:
                self.notes = json.loads(Path(notes).read_text())
                self.trust = Trust(self.notes.get("trust"))
            except (OSError, ValueError) as exc:
                self.problems.append(f"no measured trust table ({exc})")
        if model is not None:
            try:
                self.gallery.load(Path(model), "seed")
            except (OSError, ValueError, KeyError) as exc:
                self.problems.append(f"no seed gallery ({exc})")
        if live_dir is not None:
            shards = sorted(Path(live_dir).glob("live-*.npz"))
            for k, shard in enumerate(shards, start=1):
                try:
                    self.gallery.load(shard, "live")
                except (OSError, ValueError, KeyError) as exc:
                    self.problems.append(f"skipped {shard.name} ({exc})")
                if k % COMPACT_EVERY == 0 or k == len(shards):
                    self.gallery.compact()

    # ---- training ----------------------------------------------------------
    def train_now(self) -> bool:
        """Train on the gallery's current rows. False when there is too little
        (fewer than two classes)."""
        with self._lock:
            idx = self.gallery.rows()
            labels = [self.gallery.labels[i] for i in idx]
            X = unquantise(self.gallery.codes[idx]) if len(idx) else None
        if X is None or len(set(labels)) < 2:
            return False
        model = Classifier.train(X, labels)
        with self._lock:
            self.classifier = model
        self.emit(f"field classifier trained on {len(labels):,} feed-labelled "
                  f"frames of {len(model.classes)} places "
                  f"({sum(1 for s in (self.gallery.sources[i] for i in idx) if s == 'live'):,} "
                  f"of them from live runs)")
        return True

    def train_async(self) -> None:
        """Train on a background thread at the lowest priority, once at a
        time; a train asked for during one runs after it."""
        if not hasattr(cv2, "ml"):
            if NO_ML not in self.problems:
                self.problems.append(NO_ML)
            return
        with self._lock:
            if self._training:
                self._fresh = max(self._fresh, self.RETRAIN_AFTER)
                return
            self._training = True

        def work():
            try:
                try:
                    os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
                except (OSError, AttributeError):
                    pass
                try:
                    self.train_now()
                except Exception as exc:          # a look must never end the run
                    said = f"training failed ({exc})"
                    if said not in self.problems:   # once, not once a retrain
                        self.problems.append(said)
            finally:
                with self._lock:
                    self._training = False
                    again = self._fresh >= self.RETRAIN_AFTER
                    if again:
                        self._fresh = 0
                if again:
                    self.train_async()

        threading.Thread(target=work, daemon=True,
                         name="hivemind-fieldsense-train").start()

    @property
    def trained(self) -> bool:
        return self.classifier is not None

    def measured(self) -> bool:
        """Are the trainer's numbers about the classifier looking now? Its
        trust bands are margins over the runner-up among exactly the classes
        it measured (data/models/fieldsense.json `classes`); once live
        learning has taught a place it had not (MIN_VISITS visits), every
        margin is against a new competitor and no band describes it. False
        then, and before the first training, so the rules those numbers
        switched on (run_farm `sense_rules`) stay off until
        scripts/train_fieldsense.py has measured the new set."""
        model = self.classifier
        return (model is not None
                and sorted(model.classes) == list(self.notes.get("classes") or ()))

    # ---- looking -----------------------------------------------------------
    def look(self, frame, at: float | None = None) -> Look:
        small = shrink(frame)
        code = quantise(describe(small))
        bed = flower_bed(small)
        model = self.classifier
        when = self.clock() if at is None else float(at)
        if model is None:
            return Look(at=when, field=None, margin=0.0, second=None, sure=None,
                        bed=bed, code=code)
        scores = model.scores(unquantise(code[None, :]))[0]
        best, margin, second = top_two(scores, model.classes)
        # NO NUMBER FROM A TABLE ABOUT ANOTHER CLASSIFIER. MEASURED 2026-10-21
        # 22:54:54 (run-1174.log:150): "looks like strawberry (86% ...)" in
        # Pepper, the 2026-09-26 table of 11 classes read for a classifier of
        # 22. A margin against new competitors is in no band (`measured`).
        sure = self.trust.sure(best, margin) if self.measured() else None
        return Look(at=when, field=best, margin=margin, second=second,
                    sure=sure, bed=bed, code=code)

    # ---- learning ----------------------------------------------------------
    def add(self, code: np.ndarray, label: str, at: float) -> int:
        """One frame the game labelled, kept for this run's shard and trained
        on after RETRAIN_AFTER of them. Returns its place in the shard, for
        `replace`."""
        with self._lock:
            self.gallery.extend(code[None, :], [label], [self.attempt], [at], "live")
            row = len(self.gallery) - 1
            for key, value in (("codes", code), ("labels", label),
                               ("attempts", self.attempt), ("times", at)):
                self._shard[key].append(value)
            self._rows.append(row)
            slot = len(self._rows) - 1
            due = self._changed()
        if due:
            self.save()
            self.train_async()
        return slot

    def replace(self, slot: int, code: np.ndarray, at: float) -> None:
        """Put a newer frame of the same visit in `slot` (see Labeller)."""
        with self._lock:
            row = self._rows[slot]
            self.gallery.codes[row] = code
            self.gallery.times[row] = float(at)
            self._shard["codes"][slot] = code
            self._shard["times"][slot] = float(at)
            due = self._changed()
        if due:
            self.save()
            self.train_async()

    def _changed(self) -> bool:
        self._fresh += 1
        self._unsaved += 1
        if self._fresh >= self.RETRAIN_AFTER:
            self._fresh = 0
            return True
        return False

    def save(self) -> Path | None:
        """This run's live frames, to var/fieldsense/live-<attempt>.npz,
        atomically (a temporary file renamed over it)."""
        if self.live_dir is None:
            return None
        with self._lock:
            if not self._shard["labels"] or not self._unsaved:
                return None
            payload = {
                "codes": np.asarray(self._shard["codes"], np.uint8).reshape(-1, DIM),
                "labels": np.asarray(self._shard["labels"]),
                "attempts": np.asarray(self._shard["attempts"], np.int32),
                "times": np.asarray(self._shard["times"], np.float64)}
            self._unsaved = 0
        folder = Path(self.live_dir)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = (f"{self.attempt:04d}" if self.attempt >= 0
                 else time.strftime("%Y%m%d-%H%M%S"))
        path = folder / f"live-{stamp}.npz"
        tmp = folder / f".{path.name}.tmp.npz"
        np.savez_compressed(tmp, **payload)
        os.replace(tmp, path)
        return path

    def describe(self) -> str:
        seed = sum(1 for s in self.gallery.sources if s == "seed")
        live = len(self.gallery) - seed
        state = ("trained" if self.trained else "not trained yet")
        return (f"field classifier {state}: {seed:,} seed and {live:,} live "
                f"feed-labelled frames"
                + (f"; {'; '.join(self.problems)}" if self.problems else ""))


# ---- live labelling ----------------------------------------------------------

# THE RESEARCH'S LABELLING RULE, live (vpr/label.py). A look is a field's when
# it lies between two consecutive feed fixes that BOTH name that field no more
# than BRACKET_SECONDS apart, or within NEAR_FIX_SECONDS of a fix of it; and
# no panel fix (hive pad, landmark) within PANEL_VETO_SECONDS -- the feed also
# fires during a convert at the hive, naming a field the player has left. A
# hive or landmark look is one within PANEL_WINDOW of that panel fix (log
# stamps are truncated to the second). A look is committed only once the veto
# window has passed with no panel fix in it.
BRACKET_SECONDS = 40.0
NEAR_FIX_SECONDS = 2.0
PANEL_VETO_SECONDS = 20.0
PANEL_WINDOW = (-0.5, 1.5)


class Labeller:
    """Holds recent looks until the game says what they showed."""

    def __init__(self, sense: FieldSense, clock=time.time, keep_seconds: float = 90.0):
        self.sense = sense
        self.clock = clock
        self.keep = float(keep_seconds)
        self.looks: collections.deque = collections.deque()   # (at, code)
        self.fixes: collections.deque = collections.deque()   # (at, field)
        self.panels: collections.deque = collections.deque()  # (at, place)
        self.ready: dict[float, tuple] = {}                   # at -> (code, label, panel)
        self.taught: collections.Counter = collections.Counter()
        self.dropped: collections.Counter = collections.Counter()
        self._last_taught: dict[str, float] = {}
        self._seen: collections.Counter = collections.Counter()
        self._slots: dict[str, list[int]] = collections.defaultdict(list)
        self._rng = random.Random(8)
        # Fixes arrive on the feed reader's thread, panels on the loop's and
        # looks on the watcher's.
        self._lock = threading.Lock()

    def saw(self, look: Look) -> None:
        with self._lock:
            if look.code is not None and look.informative:
                self.looks.append((look.at, look.code))
            self._expire()

    def fix(self, place: str, at: float) -> None:
        """A reward-feed fix naming `place`."""
        with self._lock:
            self._fix(place, at)

    def _fix(self, place: str, at: float) -> None:
        prev = self.fixes[-1] if self.fixes else None
        self.fixes.append((float(at), str(place)))
        for t, code in self.looks:
            near = abs(t - at) <= NEAR_FIX_SECONDS
            bracketed = (prev is not None and prev[1] == place
                         and at - prev[0] <= BRACKET_SECONDS and prev[0] <= t <= at)
            if near or bracketed:
                self._candidate(t, code, str(place), panel=False)
        self._expire()

    def panel(self, place: str, at: float) -> None:
        """A panel fix (the hive pad, a landmark)."""
        with self._lock:
            self._panel(place, at)

    def _panel(self, place: str, at: float) -> None:
        self.panels.append((float(at), str(place)))
        lo, hi = PANEL_WINDOW
        for t, code in self.looks:
            if at + lo <= t <= at + hi:
                self._candidate(t, code, str(place), panel=True)
        self._expire()

    def _candidate(self, t: float, code, label: str, panel: bool) -> None:
        """Two different names for one look make it nobody's (the research
        dropped a frame with a field label and a panel label too)."""
        had = self.ready.get(t)
        if had is None:
            self.ready[t] = (code, label, panel)
        elif had[1] != label:
            self.ready[t] = (None, "", panel)

    def commit(self) -> int:
        """Teach every candidate whose veto window has passed clean. Returns
        how many were taught."""
        with self._lock:
            return self._commit()

    def _commit(self) -> int:
        now = self.clock()
        taught = 0
        for t in sorted(self.ready):
            if now < t + PANEL_VETO_SECONDS:
                break
            code, label, panel = self.ready.pop(t)
            if code is None:
                self.dropped["named twice"] += 1
                continue
            if not panel and any(abs(p - t) <= PANEL_VETO_SECONDS
                                 for p, _ in self.panels):
                self.dropped["a panel within 20 s"] += 1
                continue
            if t - self._last_taught.get(label, -1e9) < THIN_SECONDS:
                continue
            self._last_taught[label] = t
            # AT MOST PER_ATTEMPT A VISIT, SPREAD OVER ALL OF IT: reservoir
            # sampling (Vitter's algorithm R), so an hour in one field keeps
            # 45 frames from the whole hour rather than its first two minutes.
            self._seen[label] += 1
            slots = self._slots[label]
            if len(slots) < PER_ATTEMPT:
                slots.append(self.sense.add(code, label, t))
            else:
                k = self._rng.randrange(self._seen[label])
                if k >= PER_ATTEMPT:
                    continue
                self.sense.replace(slots[k], code, t)
            self.taught[label] += 1
            taught += 1
        return taught

    def _expire(self) -> None:
        cutoff = self.clock() - self.keep
        for queue in (self.looks, self.fixes, self.panels):
            while queue and queue[0][0] < cutoff:
                queue.popleft()


# ---- watching while it plays -------------------------------------------------

# One look every half second: the flower-bed rule below holds for
# EDGE_HOLD_SECONDS, which at this rate is three or four looks, and the look
# costs about 5.8 ms (see the module docstring), 1.2% of one core.
LOOK_EVERY = 0.5
# "OFF THE FIELD" MUST HOLD THIS LONG. MEASURED (fieldseg dense_control/
# persist.txt, every saved frame at ~10 fps): held 0 s, 10.9 false alarms a
# minute of normal gathering; 1 s, 1.98; 2 s, 0.34, and it still fired on
# the drift exits of trips 276, 292, 294, 322, 325 and 351 (6 of 7), 6-57 s
# after the last pickup in the aimed field and before the feed named the new
# one; 3 s, 0.20 and 5 of 7 trips missed or late.
EDGE_HOLD_SECONDS = 2.0


class Watcher:
    """Looks at frames the live view already captured, a few times a second.

    The same arrangement as `whereami.Tracker` and for the same reason: every
    extra screencopy client on the nested compositor cost the owner a session
    on 2026-09-20, so nothing here captures. `offer` is called from the live
    view's frame hook; almost every call is a clock comparison."""

    def __init__(self, sense: FieldSense, labeller: Labeller | None = None,
                 every: float = LOOK_EVERY, clock=time.time,
                 keep_seconds: float = 30.0):
        self.sense = sense
        self.labeller = labeller
        self.every = float(every)
        self.clock = clock
        self.keep = float(keep_seconds)
        self.looks: collections.deque = collections.deque()
        self.busy = False
        self.offered = 0
        self.taken = 0
        self.failures = 0
        self._last: float | None = None
        self._stop = False
        self._lock = threading.Lock()

    def offer(self, frame) -> bool:
        self.offered += 1
        if self._stop or frame is None or self.busy:
            return False
        now = self.clock()
        if self._last is not None and now - self._last < self.every:
            return False
        self._last = now
        self.busy = True
        threading.Thread(target=self._look, args=(frame, now), daemon=True,
                         name="hivemind-fieldsense").start()
        return True

    def _look(self, frame, at: float) -> None:
        try:
            look = self.sense.look(frame, at=at)
            self.record(look)
        except Exception:
            self.failures += 1                   # looking must never end a run
        finally:
            self.busy = False

    def record(self, look: Look) -> None:
        with self._lock:
            self.looks.append(look)
            cutoff = look.at - self.keep
            while self.looks and self.looks[0].at < cutoff:
                self.looks.popleft()
        self.taken += 1
        if self.labeller is not None:
            self.labeller.saw(look)
            self.labeller.commit()

    def recent(self, seconds: float) -> list[Look]:
        now = self.clock()
        with self._lock:
            return [lk for lk in self.looks if now - lk.at <= seconds]

    def off_field(self, threshold: float, hold: float = EDGE_HOLD_SECONDS) -> bool | None:
        """Has every informative look of the last `hold` seconds put the
        flower bed below `threshold`? None when there are not enough looks
        to say: fewer than one per LOOK_EVERY across the hold, less one --
        looks come at LOOK_EVERY or a frame later, so a 2 s hold asked at a
        random moment holds three or four of them, and asking for four
        would say nothing about half the time."""
        looks = [lk for lk in self.recent(hold) if lk.informative]
        if len(looks) < max(2, int(round(hold / self.every)) - 1):
            return None
        return all(lk.bed.share < threshold for lk in looks)

    def stop(self) -> None:
        self._stop = True

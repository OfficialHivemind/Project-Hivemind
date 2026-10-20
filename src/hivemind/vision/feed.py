"""The reward feed, bottom right, which is the game telling us where we are.

THE OWNER FOUND THIS, not the code. They said they were in Pumpkin, and the frame
taken that second had this in the corner:

    +590 Honey (from Pumpkin Patch)

The game names the field, in words, for free. That matters because 8b records
that nothing else in this project can: whole-screen colour signatures do not
separate places at any threshold, and the vision model gets 7/10 and is
systematically wrong about Pumpkin Patch in particular.

WHAT IT IS AND IS NOT. Their second message was the important one: "when i go over
a honey token". The feed fires on PICKUP, not continuously. MEASURED across their
session, 4 of 24 sampled frames name a known field -- an anchor roughly every
nine seconds while farming, and nothing at all while walking between fields.

So this is not a position sensor. It is an ANCHOR: rare, and certain when it
fires. That is still more than this project has ever had, and in particular it
is the first way to answer "did I actually arrive?", which every recorded route
has so far had to assume.

IT IS ALSO A GENERAL EVENT LOG. The same 24 frames carried "defeated mantis!
(+5 battle points)", "ninja bee advanced to level 7!", "demon bee is out of
energy!" and "surprise balloons from goldentime!" -- combat results, bee levels
and energy, none of which the bot can currently see by any other means.

WHY THE PILLS ARE FOUND BY GEOMETRY AND THE TEXT IS READ SECOND.

Because the model lies when there is nothing to read. Asked to transcribe a feed
crop with no pills in it, it returned "claim hive" in ELEVEN of 24 frames --
text that appears nowhere near that corner of the screen. Given a blank image
and a head full of Bee Swarm context, it invents plausible Bee Swarm text. So
the pills are located by colour and shape FIRST, and nothing is read unless a
pill is actually there.

MEASURED GEOMETRY, from a real frame at 1920x1080 with one pill in it:

    pill hue        103-110        (a narrow, distinctive blue)
    saturation      >= 97
    value           >= 127
    row height      20 px
    row pitch       ~29 px
    right edge      ~17 px in from the frame edge
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

from ..telemetry import readhealth

# The blue of the pill body. Measured p5-p95 was 103-110 on one frame; the band
# is widened a little either side because a single frame is a single frame, and
# narrowed nowhere, because the ground in these fields is green (hue 35-85) and
# the sky is a much paler blue.
HUE_LOW, HUE_HIGH = 98, 118
SAT_MIN = 90
VALUE_MIN = 110

# Where to look. The feed is anchored to the bottom-right corner; these are
# fractions of the frame so a resolution change does not silently break it.
SEARCH_TOP = 0.70
SEARCH_LEFT = 0.55

# What counts as a row. Height and width in pixels at 1920x1080, scaled by the
# frame height so the same numbers hold at another resolution.
MIN_HEIGHT, MAX_HEIGHT = 14, 40
MIN_WIDTH = 120
MIN_FILL = 0.55            # a pill is a solid bar, not a scattering of pixels


@dataclass(frozen=True)
class Row:
    """One pill in the feed, in frame coordinates."""
    x: int
    y: int
    w: int
    h: int

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def crop(self, frame: np.ndarray, pad: int = 2) -> np.ndarray:
        h, w = frame.shape[:2]
        x0, y0 = max(0, self.x - pad), max(0, self.y - pad)
        x1, y1 = min(w, self.x + self.w + pad), min(h, self.y + self.h + pad)
        return frame[y0:y1, x0:x1]


# A row of a merged blob is a pill's when this share of it is blue (see rows).
BAND_FILL = 0.75

# THE COLUMN. The pills are one fixed-width column hanging from the right
# edge: a solid pill spans x 1565-1904 whatever its words, the newest one
# grows out from 1565, and a fading one keeps its blue longest at its right
# end (1904). Blue anywhere else is the world's: Mountain Top's blue flowers
# read as 4 pills, a blue bee's side as 1 (tests/fixtures/golden, 2026-10-26).
# MEASURED 2026-10-26 over 6,425 frames (var/loot_misses, var/routes/
# attempt-102*/124*), every row the colour test found: left edges 1563-1568
# on 2,067 (1565 alone 1,258), right edges 1903-1907 on 2,031, against no
# other left edge above 45 and no other right edge above 14 but the frame's
# own 1920 (1,121: blue running off the edge, a pill joined to it starts at
# 1565 and is kept). A row is kept when it starts or ends there.
# A PILL JOINED TO BLUE ON BOTH SIDES (the Pine Tree's flowers) does neither:
# 595 such rows across the column in those frames, half of them pills with
# their words in them. So a row that does neither is kept when the column
# part of it holds words: TEXT_STROKES or more short white runs (letter
# strokes, white as read_text's white pass) along one of its lines. MEASURED
# on the 595: 252 had 0-1 (the world's blue), 247 had 15 or more (pills);
# the 96 between were mixed (faded old lines, Blue Flower Field's flowers,
# sampled by eye), 19 of them at 10-14. Mountain Top's flower row has 0.
# ASSUMED: the feed hangs from the right edge at its pixel size at other
# frame sizes, as the measured GUI does (vision/screen); only 1920x1080 is
# measured.
COLUMN_LEFT_IN = 355       # 1920 - 1565
COLUMN_RIGHT_IN = 16       # 1920 - 1904
COLUMN_SLACK = 4
TEXT_STROKES = 10
STROKE_MAX = 6             # px: a letter's stroke, not a white flower


def _scale(frame: np.ndarray) -> float:
    return frame.shape[0] / 1080.0


def rows(frame: np.ndarray) -> list[Row]:
    """Every feed pill in the frame, top to bottom. Empty when there is no feed.

    This is the gate. Nothing reads text unless this returns something.
    """
    if frame is None or frame.size == 0:
        return []
    h, w = frame.shape[:2]
    y0, x0 = int(h * SEARCH_TOP), int(w * SEARCH_LEFT)
    region = frame[y0:, x0:, :3]
    if region.size == 0:
        return []

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = ((hue >= HUE_LOW) & (hue <= HUE_HIGH) &
            (sat >= SAT_MIN) & (val >= VALUE_MIN)).astype(np.uint8)
    # Close along the row only: the text inside a pill is white, so a pill is a
    # blue bar with white holes in it and has to be joined back up horizontally.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((1, 25), np.uint8))

    scale = _scale(frame)
    lo_h, hi_h = MIN_HEIGHT * scale, MAX_HEIGHT * scale
    lo_w = MIN_WIDTH * scale

    found: list[Row] = []
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if bw < lo_w:
            continue
        if lo_h <= bh <= hi_h and area / float(bw * bh) >= MIN_FILL:
            found.append(Row(x=int(x + x0), y=int(y + y0), w=int(bw), h=int(bh)))
            continue
        # A PILL JOINED TO BLUE BEHIND IT. MEASURED 2026-10-03 03:01:53
        # (var/loot_misses/20261003-030153-2.jpg): the newest line, "+580
        # Honey (from Rhino Beetle)", 79% inside this mask, merged with the
        # Pine Tree's blue flowers under it into one 340x49 blob at fill 0.45
        # -- too tall and too sparse -- and the feed read only the ends of
        # the faded lines above it. A pill is a band of rows nearly all blue
        # across the blob's width; such a band, the height of a pill, is one.
        if bh <= hi_h:
            continue
        inside = (labels[y:y + bh, x:x + bw] == i)
        full = inside.mean(axis=1) >= BAND_FILL
        start = None
        for k, on in enumerate(list(full) + [False]):
            if on and start is None:
                start = k
            elif not on and start is not None:
                if lo_h <= k - start <= hi_h:
                    found.append(Row(x=int(x + x0), y=int(y + y0 + start),
                                     w=int(bw), h=int(k - start)))
                start = None
    return sorted((r for r in found if _in_column(frame, r)), key=lambda r: r.y)


def _in_column(frame: np.ndarray, row: Row) -> bool:
    """Does the row start at the feed's left edge, end at its right edge, or
    hold words inside the column? (THE COLUMN above.) Else it is the world."""
    frame_w = frame.shape[1]
    left, right = frame_w - COLUMN_LEFT_IN, frame_w - COLUMN_RIGHT_IN
    if (abs(row.x - left) <= COLUMN_SLACK
            or abs(row.x + row.w - right) <= COLUMN_SLACK):
        return True
    band = frame[row.y:row.bottom, max(row.x, left):min(row.x + row.w, right), :3]
    if band.size == 0:
        return False
    white = _white(cv2.cvtColor(np.ascontiguousarray(band), cv2.COLOR_BGR2HSV))
    edges = np.diff(np.pad(white.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    for line in edges:
        runs = np.flatnonzero(line == -1) - np.flatnonzero(line == 1)
        if int((runs <= STROKE_MAX).sum()) >= TEXT_STROKES:
            return True
    return False


def _white(hsv: np.ndarray) -> np.ndarray:
    """The feed's white letters."""
    return (hsv[:, :, 1] < 70) & (hsv[:, :, 2] > 170)


def present(frame: np.ndarray) -> bool:
    """Is there anything in the feed at all? Cheap, and the guard against
    asking a language model to read an empty rectangle."""
    return bool(rows(frame))


def strip(frame: np.ndarray, pad: int = 3) -> np.ndarray | None:
    """One image containing every pill, or None when the feed is empty.

    Reading the whole feed in a single pass costs one model call instead of one
    per row, and keeps the lines in order, which matters because the newest
    entry is the one that says where we are now.
    """
    found = rows(frame)
    if not found:
        return None
    h, w = frame.shape[:2]
    x0 = max(0, min(r.x for r in found) - pad)
    x1 = min(w, max(r.x + r.w for r in found) + pad)
    y0 = max(0, found[0].y - pad)
    y1 = min(h, found[-1].bottom + pad)
    return frame[y0:y1, x0:x1]



# ---- reading the strip without the vision model ------------------------------
#
# WHY. The strip was read by the vision model every few seconds while farming
# (vision/whereami.Tracker, 3 s): about 2 s of the GPU the game is using per
# read, and the model's server grew past 3.5 GB and was recycled 13 times in 40
# minutes of run-560. The feed is clean UI text on a flat pill, which
# tesseract reads. MEASURED 2026-10-01 on 40 strips of the day's Pine Tree
# frames, both readers on each: a field named by both 15 times, the same field
# all 15; 4 named by the model alone (3 of them "rom ...)", which
# whereami.FROM now takes, the fourth read by the white pass below); the same
# 7 kills ("Defeated Mantis!") from each; 0.16 s a read on the CPU against the
# model's 2.2 s on the GPU. On 106 strips of the day the field it named was
# the one the model's own fixes named at the time every time (49 Pine Tree,
# 4 Pumpkin from the morning's Pumpkin trips).
TESSERACT = "tesseract"
# This machine's tesseract has only the Afrikaans model (vision/amulet says
# why that is enough for the game's Latin script).
LANGUAGE = "afr"
UPSCALE = 3.0
TIMEOUT_S = 6.0
SOURCE = re.compile(r"rom\s+[A-Za-z][A-Za-z '-]{2,30}\)", re.I)


def _tesseract(image: np.ndarray, run=subprocess.run) -> str:
    ok, png = cv2.imencode(".png", image)
    if not ok:
        return ""
    try:
        out = run([TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "6"],
                  input=png.tobytes(), capture_output=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    raw = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) else str(out.stdout)
    return " ".join(raw.split())


def read_text(strip: np.ndarray, run=subprocess.run) -> str:
    """The strip's words by tesseract, '' when it cannot run.

    The grey image first; when that names no source ("(from X)"), the white
    letters alone, which read the credits the grey pass loses -- never both
    joined, so a kill line is never counted twice (act/bugrun)."""
    if strip is None or getattr(strip, "size", 0) == 0:
        return ""
    big = cv2.resize(strip, None, fx=UPSCALE, fy=UPSCALE, interpolation=cv2.INTER_CUBIC)
    text = _tesseract(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY), run)
    if SOURCE.search(text):
        return _noted(text)
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
    white = np.where(_white(hsv), 0, 255).astype(np.uint8)
    other = _tesseract(white, run)
    return _noted(other if SOURCE.search(other) else text)


def _noted(text: str) -> str:
    """S3 (telemetry/readhealth): a shown feed strip whose words name a source."""
    readhealth.note("feed line", bool(SOURCE.search(text)))
    return text


def row_texts(frame: np.ndarray, run=subprocess.run) -> list[str]:
    """Each feed pill's words by tesseract, top to bottom; [] for no feed.
    One pill at a time reads a boost line the whole strip's pass loses
    (MEASURED 2026-10-02 on the 96 Blue Field Booster frames)."""
    out = []
    for row in rows(frame):
        crop = row.crop(frame)
        if getattr(crop, "size", 0) == 0:
            continue
        big = cv2.resize(crop, None, fx=UPSCALE, fy=UPSCALE, interpolation=cv2.INTER_CUBIC)
        text = _tesseract(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY), run)
        if text:
            out.append(text)
    return out

"""The Ant Challenge's own HUD: "Time: 4:53", "Round: 2", "Score: 1" (ROADMAP Q2).

WHY. 168 of the 175 games kept in var/antchallenge (28 Sep - 26 Oct) ended
"Ant Challenge ended because you died." (the chat, read off each game's
amulet-table frame), median score 43, and the last round read on their last
six looks was 10 in 95 games and 11 in 12 more (docs/pending/q2-ants.md).
Every 5th round "always contains a Giant Ant" (wiki Ant_Challenge, read
2026-09-30) and the looks before the deaths show one walking onto the
character (var/antchallenge/20261026-185454/0100.8, 0103.3: "Giant Ant
(Lvl 5) HP: 1,227", round 10). Army Ants -- the quest the account is on --
are "much more common" after round 15 (wiki Army_Ant, read 2026-10-26). So
the round is what the play has to know.

HOW. MEASURED 2026-10-26 on 175 games' frames: the three lines are white
letters at the top middle, x 1040-1360, y 70-300 of a 1920x1080 frame; the
white pixels alone (S <= 45, V >= 215, the same cut that read the arena's
nameplates, docs/pending/integration.md 2026-10-01), black on white, 2x,
`--psm 6`, read "Time: 4:29 / und:5 / ore: 19" -- the "Ro" and "Sc" are
often lost to the swarm over them, so the numbers are matched on the tails.
A look with the swarm over the box reads nothing (~1 in 5); a number that
jumps is not believed (`RoundTracker`).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

from hivemind.vision import screen

# The box, (x0, y0, x1, y1) on 1920x1080. ASSUMED to hang from the top middle
# like the Honey/Pollen pills (vision/screen; only 1920x1080 measured).
HUD_BOX = (1040, 70, 1360, 300)
WHITE_MAX_S, WHITE_MIN_V = 45, 215
UPSCALE = 2
TESSERACT = "tesseract"
LANGUAGE = "afr"            # the only Latin model on this machine (vision/amulet)
TIMEOUT_S = 6.0

_TIME = re.compile(r"(\d)\s*[:.]\s*(\d\d)")
_ROUND = re.compile(r"(?:ound|und|nd)\s*[:!.]?\s*(\d{1,2})\b", re.I)
_SCORE = re.compile(r"(?:ore|re)\s*[:!.]?\s*(\d{1,3})\b", re.I)
_GIANT = re.compile(r"giant", re.I)


@dataclass
class Hud:
    time_left: int | None = None    # seconds
    round: int | None = None
    score: int | None = None
    giant: bool = False             # "Giant" read in the box (its nameplate)


def parse(text: str) -> Hud:
    """The numbers in the reader's text; None for each one not read."""
    hud = Hud(giant=bool(_GIANT.search(text)))
    for line in text.splitlines():
        if hud.time_left is None and "ime" in line.lower():
            m = _TIME.search(line)
            if m:
                hud.time_left = int(m.group(1)) * 60 + int(m.group(2))
        if hud.round is None:
            m = _ROUND.search(line)
            if m:
                hud.round = int(m.group(1))
                continue
        if hud.score is None:
            m = _SCORE.search(line)
            if m:
                hud.score = int(m.group(1))
    return hud


def read(frame, run=subprocess.run) -> Hud:
    """The HUD on this frame; an empty Hud when it cannot be read."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return Hud()
    x0, y0, x1, y1 = screen.box(frame, HUD_BOX, anchor=screen.TOP)
    roi = frame[max(0, y0):y1, max(0, x0):x1, :3]
    if roi.size == 0:
        return Hud()
    hsv = cv2.cvtColor(np.ascontiguousarray(roi), cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 1] <= WHITE_MAX_S) & (hsv[:, :, 2] >= WHITE_MIN_V)
    page = np.where(white, 0, 255).astype(np.uint8)
    page = cv2.resize(page, None, fx=UPSCALE, fy=UPSCALE, interpolation=cv2.INTER_NEAREST)
    ok, png = cv2.imencode(".png", page)
    if not ok:
        return Hud()
    try:
        out = run([TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "6"],
                  input=png.tobytes(), capture_output=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return Hud()
    text = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) else str(out.stdout)
    return parse(text)


class RoundTracker:
    """The round the game is on, from reads that sometimes miss or misread
    (one look read "48" in round 10). A read is believed when it is the
    current round or up to two ahead (a look every ~2.5 s, a round every
    ~10 s MEASURED); anything else is ignored."""

    def __init__(self):
        self.round = 0
        self.score = 0
        self.time_left: int | None = None

    def see(self, hud: Hud) -> bool:
        """Take one read; True when the round moved on."""
        moved = False
        if hud.round is not None and self.round < hud.round <= self.round + 2:
            self.round, moved = hud.round, True
        if hud.score is not None and self.score <= hud.score <= self.score + 15:
            self.score = hud.score
        if hud.time_left is not None and hud.time_left <= 300:
            self.time_left = hud.time_left
        return moved


def giant_round(rnd: int, every: int = 5) -> bool:
    """A round with a Giant Ant in it, and the one after (MEASURED: 12 of the
    deaths came at round 11, the round-10 Giant Ant still alive)."""
    return rnd >= every and rnd % every in (0, 1)

"""The amulet choice at the end of the Ant Challenge: find "Keep Old", or nothing.

WHY IT IS READ AT ALL. Every Ant Challenge ends in an Ant Amulet, whatever
the score -- 24 and under is a bronze one (BSS wiki, Ant Amulet) -- and when
the player already has one the game puts up a table of the old and the new
with two buttons: "Keep Old", which keeps the one they have, and "Replace",
which asks for a confirmation and then throws theirs away for good (BSS wiki,
Amulet). Natro answers the same prompt for its boss amulets the same way: it
finds its "keep" button by image and clicks nothing else (natro_macro.ahk
`nm_AmuletPrompt`). A bot's short challenge scores low, so the old amulet is
the better one in all but the unluckiest case, and the only click this
module ever offers is "Keep Old".

HOW, FIRST: THE TWO BUTTONS BY COLOUR, THEN THEIR OWN WORDS. The table's
buttons are a solid red "Keep Old" and a solid green "Replace" side by side,
the same size, their tops level (MEASURED 2026-09-28 on two frames of one
table, var/amulet/: red 159x48 at (829, 598), green 160x45 at (1008, 598),
BGR ~(33, 41, 194) and ~(39, 117, 33)). `find_buttons` finds that pair;
each button is then read alone -- its white letters made black on white,
one line (`--psm 7`) -- and only a pair that reads "Keep Old" and "Replace"
word for word is the table. The click point is the red button's own
centre. WHY: the reading below, over the whole middle of the screen, read
neither button on either frame while the table stood in plain view -- the
grass and a strawberry behind it drowned the white-on-red words ("no amulet
table in the 30s", run-529, and the owner walked the bot round
the Dandelion Field with the table still up). The pair read "Keep Old" /
"Replace" exactly on both.

THEN, IF THERE IS NO PAIR: tesseract (the system's 5.x; no Python binding is
installed) reads the middle of the screen as sparse text, one word per row
of its TSV with a box and a confidence. "Keep" and "Old" side by side on one
line, both read with confidence, is the button; the click point is their
joint centre. `Replace` on the same screen is what says this is the amulet
table and not some other "keep" -- the caller clicks only when both are
there.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

# The middle of a 1920x1080 frame, as (x0, y0, x1, y1): where the table sits
# (Natro searches the centre 500 px of the window for its button).
REGION = (400, 120, 1520, 980)
FRAME_SIZE = (1920, 1080)
# Upscaling helps tesseract with game UI text; the words are read, not guessed.
UPSCALE = 2.0
MIN_CONFIDENCE = 60.0
TESSERACT = "tesseract"
# THE LANGUAGE MODEL IS AFRIKAANS, AND THAT IS ENOUGH. This machine's tesseract
# has only `afr` and `osd` data (/usr/share/tessdata: no eng.traineddata, and
# installing it is the owner's to do). Afrikaans is Latin script, and its
# model read the game's own panel word for word ("Spend 1 Ant Pass to / Play
# the Ant Challenge", var/places/ant_challenge-230525.jpg) and a drawn "Keep
# Old" / "Replace" pair, 2026-09-28.
LANGUAGE = "afr"
TIMEOUT_S = 8.0


# THE BUTTONS' COLOURS, in OpenCV's HSV (hue 0-180). Red wraps round 0.
RED_HUE_LOW, RED_HUE_HIGH = 6, 174        # red is hue <= 6 or >= 174
RED_MIN_S, RED_MIN_V = 170, 150
GREEN_HUE = (50, 75)
GREEN_MIN_S, GREEN_V = 170, (70, 160)
# A button's size at 1920x1080 (MEASURED 159-160 x 45-48), with room either
# way, and how solid it is: the letters are holes (0.70-0.75 measured).
BUTTON_W = (110, 220)
BUTTON_H = (34, 64)
BUTTON_MIN_FILL = 0.55
# The pair: tops level, the green one just right of the red, the same width.
PAIR_TOP_SLACK = 8
PAIR_GAP = (4, 60)
PAIR_WIDTH_RATIO = 1.25
# A button's letters: white, so low saturation and bright.
LETTER_MAX_S, LETTER_MIN_V = 90, 190
BUTTON_UPSCALE = 3


@dataclass
class Word:
    text: str
    conf: float
    x: int          # frame coordinates of the word's box
    y: int
    w: int
    h: int
    line: tuple     # tesseract's (block, paragraph, line) of the word


@dataclass
class Choice:
    """What the reader found: the "Keep Old" button's centre (None if not
    read), whether "Replace" was on screen too, and every word it read."""
    keep_old: tuple | None
    replace: bool
    words: list

    @property
    def is_amulet_table(self) -> bool:
        return self.keep_old is not None and self.replace

    def describe(self) -> str:
        said = " ".join(w.text for w in self.words)[:160]
        if self.is_amulet_table:
            return (f"the amulet table: \"Keep Old\" at {self.keep_old}, "
                    f"\"Replace\" beside it")
        if self.keep_old is not None:
            return f"\"Keep Old\" at {self.keep_old} but no \"Replace\": {said!r}"
        return f"no \"Keep Old\" on screen ({said!r})" if said else "no text on screen"


def read_words(frame, region=REGION, run=subprocess.run) -> list[Word]:
    """Every word tesseract reads in `region` of the frame (scaled to the
    frame's size), with a box in frame coordinates. [] when it cannot run."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    h, w = frame.shape[:2]
    sx, sy = w / FRAME_SIZE[0], h / FRAME_SIZE[1]
    x0, y0, x1, y1 = (int(region[0] * sx), int(region[1] * sy),
                      int(region[2] * sx), int(region[3] * sy))
    roi = frame[y0:y1, x0:x1, :3]
    if roi.size == 0:
        return []
    grey = cv2.cvtColor(np.ascontiguousarray(roi), cv2.COLOR_BGR2GRAY)
    big = cv2.resize(grey, None, fx=UPSCALE, fy=UPSCALE, interpolation=cv2.INTER_CUBIC)
    ok, png = cv2.imencode(".png", big)
    if not ok:
        return []
    try:
        out = run([TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "11", "tsv"],
                  input=png.tobytes(), capture_output=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return []
    text = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) else str(out.stdout)
    return parse_tsv(text, x0, y0)


def parse_tsv(tsv: str, x0: int = 0, y0: int = 0, upscale: float = UPSCALE) -> list[Word]:
    """tesseract's TSV rows as Words, boxes back in frame coordinates."""
    words: list[Word] = []
    for row in tsv.splitlines()[1:]:
        parts = row.split("\t")
        if len(parts) < 12 or not parts[11].strip():
            continue
        try:
            conf = float(parts[10])
            left, top, width, height = (int(parts[6]), int(parts[7]),
                                        int(parts[8]), int(parts[9]))
        except ValueError:
            continue
        words.append(Word(text=parts[11].strip(), conf=conf,
                          x=x0 + int(left / upscale), y=y0 + int(top / upscale),
                          w=int(width / upscale), h=int(height / upscale),
                          line=(parts[2], parts[3], parts[4])))
    return words


def _clean(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalpha())


def find_choice(words: list[Word], min_conf: float = MIN_CONFIDENCE) -> Choice:
    """Where "Keep Old" is, and whether "Replace" is there too."""
    sure = [w for w in words if w.conf >= min_conf]
    keep_old = None
    for a in sure:
        if _clean(a.text) != "keep":
            continue
        for b in sure:
            if (_clean(b.text) == "old" and b.line == a.line and b.x > a.x
                    and b.x - (a.x + a.w) < 3 * max(a.h, b.h)):
                x_left, x_right = a.x, b.x + b.w
                top = min(a.y, b.y)
                bottom = max(a.y + a.h, b.y + b.h)
                keep_old = ((x_left + x_right) // 2, (top + bottom) // 2)
                break
        if keep_old:
            break
    replace = any(_clean(w.text) == "replace" for w in sure)
    return Choice(keep_old=keep_old, replace=replace, words=list(words))


def _boxes(mask, sx: float, sy: float) -> list[tuple]:
    """The button-sized, button-solid blobs of `mask`, as (x, y, w, h)."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    out = []
    for x, y, w, h, area in stats[1:count]:
        if not (BUTTON_W[0] * sx <= w <= BUTTON_W[1] * sx
                and BUTTON_H[0] * sy <= h <= BUTTON_H[1] * sy):
            continue
        if area < BUTTON_MIN_FILL * w * h:
            continue
        out.append((int(x), int(y), int(w), int(h)))
    return out


def find_buttons(frame, region=REGION):
    """((x, y, w, h) of the red button, of the green one) in frame
    coordinates when the table's pair of buttons is on screen, else None."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    h, w = frame.shape[:2]
    sx, sy = w / FRAME_SIZE[0], h / FRAME_SIZE[1]
    x0, y0, x1, y1 = (int(region[0] * sx), int(region[1] * sy),
                      int(region[2] * sx), int(region[3] * sy))
    roi = np.ascontiguousarray(frame[y0:y1, x0:x1, :3])
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = (((hue <= RED_HUE_LOW) | (hue >= RED_HUE_HIGH))
           & (sat >= RED_MIN_S) & (val >= RED_MIN_V))
    green = ((hue >= GREEN_HUE[0]) & (hue <= GREEN_HUE[1]) & (sat >= GREEN_MIN_S)
             & (val >= GREEN_V[0]) & (val <= GREEN_V[1]))
    for rx, ry, rw, rh in _boxes(red, sx, sy):
        for gx, gy, gw, gh in _boxes(green, sx, sy):
            gap = gx - (rx + rw)
            if (abs(gy - ry) <= PAIR_TOP_SLACK * sy
                    and PAIR_GAP[0] * sx <= gap <= PAIR_GAP[1] * sx
                    and max(rw, gw) <= PAIR_WIDTH_RATIO * min(rw, gw)):
                return ((x0 + rx, y0 + ry, rw, rh), (x0 + gx, y0 + gy, gw, gh))
    return None


def read_button(frame, box, run=subprocess.run) -> str:
    """The words on one button: its white letters made black on white, read
    as one line. "" when tesseract cannot run."""
    x, y, w, h = box
    crop = np.ascontiguousarray(frame[y:y + h, x:x + w, :3])
    if crop.size == 0:
        return ""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    letters = (hsv[..., 1] < LETTER_MAX_S) & (hsv[..., 2] > LETTER_MIN_V)
    page = np.where(letters, 0, 255).astype(np.uint8)
    page = cv2.copyMakeBorder(page, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    page = cv2.resize(page, None, fx=BUTTON_UPSCALE, fy=BUTTON_UPSCALE,
                      interpolation=cv2.INTER_NEAREST)
    ok, png = cv2.imencode(".png", page)
    if not ok:
        return ""
    try:
        out = run([TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "7"],
                  input=png.tobytes(), capture_output=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    text = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) else str(out.stdout)
    return text.strip()


def read_buttons(frame, run=subprocess.run) -> Choice | None:
    """The table found by its buttons (see HOW, FIRST), or None: no pair, or
    a pair whose words are not "Keep Old" and "Replace" exactly."""
    pair = find_buttons(frame)
    if pair is None:
        return None
    keep_box, replace_box = pair
    keep_text, replace_text = read_button(frame, keep_box, run), read_button(frame, replace_box, run)
    if _clean(keep_text) != "keepold" or _clean(replace_text) != "replace":
        return None
    x, y, w, h = keep_box
    rx, ry, rw, rh = replace_box
    words = [Word(text=keep_text, conf=100.0, x=x, y=y, w=w, h=h, line=("button", "keep", "")),
             Word(text=replace_text, conf=100.0, x=rx, y=ry, w=rw, h=rh,
                  line=("button", "replace", ""))]
    return Choice(keep_old=(x + w // 2, y + h // 2), replace=True, words=words)


def read_choice(frame, run=subprocess.run) -> Choice:
    """The buttons first; the whole middle of the screen only when there is
    no pair that reads right."""
    found = read_buttons(frame, run=run)
    if found is not None:
        return found
    return find_choice(read_words(frame, run=run))

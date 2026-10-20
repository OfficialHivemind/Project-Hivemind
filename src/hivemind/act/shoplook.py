"""Looking at a shop, buying nothing: E on its counter, the window read, E out.

THE OWNER, 2026-10-01: "the ai should learn to buy stuff ... buying even bees".
Nothing of a shop's window has been seen by this bot. The wiki's own
screenshots of one (File:The honey mask in shop,.png; File:Purchase dis.png,
read 2026-10-02) show what to expect: E at the counter's "Open Shop" opens it;
inside, the top prompt reads "Leave Shop" and E leaves; the item's name and
price are text in a panel to the right ("Honey Mask", "100,000,000 Honey"); the
action button sits between two arrows ("Craft Item", "Equipped"). So this is
the LOOK that comes first, under the rules the inventory and the badges keep:

  * E ONLY ON AN EXACT READ. "open shop" to go in, "leave shop" to come out;
    any other prompt and nothing is pressed (the Red Cannon's "Fire the Red
    Cannon" is a step away from the Ticket Tent's counter).
  * NO CLICK, NO OTHER KEY inside the window -- but one: `browse` clicks the
    window's right arrow, only when asked, and only on a frame where that
    arrow is drawn (`arrow_there`). The action button is never touched here;
    buying is a separate step, built against these pictures.
  * THE SHOP TRAP (wiki, Glitches): "When players reset with the shop open,
    they are unable to close the interface", and a shop opened straight after
    a field booster shows the booster's button where "Close Shop" belongs. So
    this never resets, the caller never runs it straight after a booster, and
    a window that will not say "Leave Shop" is reported `trapped` -- for the
    caller's rejoin, which clears it -- rather than pressed at.

Nothing here walks a route. `approach` is the key that steps from where the
caller left the character toward the counter, a step at a time, until the
counter's own prompt reads; the caller owns getting there and home.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

OPEN = "open shop"
LEAVE = "leave shop"
# ONE APPROACH STEP, held: about 4 studs at the ~28 studs a second routes
# measure (act/routes), so a step cannot carry the character across a
# counter's pad between two reads of its prompt.
STEP_S = 0.15
APPROACH_MAX_S = 4.0     # the most the approach walks (~110 studs) before giving up
SETTLE_S = 1.5           # after an E, before looking
# A READ THAT FAILED IS NOT A STEP. MEASURED 2026-10-02 06:09 (attempt 577,
# the first look): the vision model's server was recycled mid-approach and
# the approach stepped on through reads that came back None -- 27 steps, at
# 1.6x speed (haste x4 and the Brown Bear morph), about 180 studs walked
# without a read that could have seen the counter. A failed read now waits
# READ_RETRY_S and reads again, READ_MISSES times at most, and steps never.
READ_MISSES = 10
READ_RETRY_S = 1.0
APPROACH_KEEP_EVERY = 4  # approach frames kept, one in this many steps
E_TRIES = 4              # looks-and-presses for one E the input dropped
E_RETRY_S = 2.0
LEAVE_LOOKS = 4          # looks for "leave shop" after going in, SETTLE_S apart
LEAVE_PRESSES = 2        # E presses tried on an exact "leave shop" to get out


def _norm(text) -> str:
    """Lower case, one space, and the key hint ("E Leave Shop") dropped."""
    low = " ".join(str(text or "").lower().split())
    return low[2:] if low.startswith("e ") else low


def says(text, phrase: str) -> bool:
    """The panel reads `phrase` and nothing else (the key hint "E" allowed)."""
    return _norm(text) == phrase


@dataclass
class ShopLook:
    ok: bool = False                 # went in, read the window, came out
    reason: str = ""
    went_in: bool = False
    came_out: bool = False
    trapped: bool = False            # in, and no "leave shop" to come out by
    window: str = ""                 # the window, transcribed
    steps: int = 0                   # approach steps walked
    kept: list = field(default_factory=list)
    reads: list = field(default_factory=list)   # each different prompt read, in order
    steered: int = 0                 # approach steps a steer sent sideways
    catalogue: list = field(default_factory=list)  # every window `browse` read

    def describe(self) -> str:
        if self.trapped:
            return (f"in the shop and its prompt never read \"Leave Shop\" — "
                    f"trapped (the wiki's Shop Trap); a rejoin clears it: {self.reason}")
        if not self.ok:
            return f"did not look at the shop: {self.reason}"
        return (f"looked at the shop and left it ({self.steps} approach step(s)); "
                f"the window read: {self.window[:160]!r}")


def look(vin, frames, read_panel, transcribe=None, *, approach: str = "w",
         keep_dir: Path | None = None, sleep=time.sleep, note=None,
         speed=None, read_prompt=None, stopped=None,
         taken_over=None, steer=None, inside=None) -> ShopLook:
    """Step `approach` until the counter's prompt reads "open shop", go in, read
    and keep the window, come out on an exact "leave shop". `speed()`: the
    movespeed factor now (act/routes `_speed_factor`), so a step covers the
    same ground under a haste or a morph. `read_prompt(frame)`: a second
    reader of the prompt's own box (`prompt_text`). `stopped()`: a stop was
    asked for -- no step and no E into the shop after it. `taken_over()`: the
    owner has the controls (GuardedInput `stale`), when a dropped E is his and
    not retried. `steer(frame) -> keys`: the keys for the next step, from the
    frame just read (`ticket_tent_steer`), `approach` when it says nothing.
    `inside(frame, out)`: run once with the window open and read, before the
    way out (`browse`); whatever it raises, the way out still runs."""
    say = note or (lambda text: None)
    out = ShopLook()

    def factor() -> float:
        try:
            value = float(speed()) if speed is not None else 1.0
        except Exception:
            value = 1.0
        return value if 0.5 <= value <= 4.0 else 1.0

    def asked(check) -> bool:
        try:
            return bool(check()) if check is not None else False
        except Exception:
            return False

    def heard(text) -> None:
        said = "<no read>" if text is None else repr(text)
        if not out.reads or out.reads[-1] != said:
            out.reads.append(said)

    # EVERY READ IS GUARDED: a raise from in here would leave the window
    # open for a caller whose way home is a reset -- the Shop Trap.
    def frame_now():
        try:
            return frames()
        except Exception:
            return None

    def panel(frame=None):
        try:
            return read_panel(frame if frame is not None else frames())
        except Exception:
            return None

    # TO THE COUNTER: a step at a time, until its own prompt reads -- and a
    # step only after a read that worked (READ_MISSES), never after a stop.
    walked, misses = 0.0, 0
    last = frame_now()
    seen = panel(last) if last is not None else None
    heard(seen)
    while not says(seen, OPEN):
        if asked(stopped):
            out.reason = "a stop was asked for on the way to the counter"
            return out
        if seen is None:
            misses += 1
            if misses > READ_MISSES:
                out.reason = (f"the prompt could not be read {READ_MISSES}x in a "
                              f"row on the way to the counter, so no step was "
                              f"taken blind (reads: {', '.join(out.reads[-6:])})")
                return out
            sleep(READ_RETRY_S)
            seen = panel()
            heard(seen)
            continue
        misses = 0
        if walked >= APPROACH_MAX_S:
            out.reason = (f"no \"Open Shop\" within {APPROACH_MAX_S:.0f}s of "
                          f"holding {approach} at walking speed (reads: "
                          f"{', '.join(out.reads[-6:])})")
            return out
        hold = STEP_S / factor()          # read BEFORE the key goes down
        keys = approach
        if steer is not None and last is not None:
            try:
                keys = str(steer(last) or approach)
            except Exception:
                keys = approach
        try:
            if vin.press(*keys) is False:
                out.reason = "the owner's Pause or Take Over held the step back"
                return out
            sleep(hold)
        finally:
            vin.release(*keys)
        walked += STEP_S
        out.steps += 1
        if keys != approach:
            out.steered += 1
        frame = frame_now()
        last = frame
        seen = panel(frame) if frame is not None else None
        heard(seen)
        if out.steps % APPROACH_KEEP_EVERY == 0:
            _keep(keep_dir, frame, out, f"approach-{out.steps:02d}", ext="jpg")

    # BOTH READERS, AND ONLY WHAT THEY POSITIVELY SAY. MEASURED 2026-10-02
    # 06:37 (attempt 578, the second look): inside the Ticket Tent the prompt
    # reads "E Leave Shop" in a RED box drawn over the tent's red wall; the two
    # merge into one blob that vision/banner's shape rules refuse, so
    # read_panel said '' -- "no panel" -- while the window was open
    # (var/shoplook/20261002-063750-trapped.png). The old way out took a ''
    # for "left", which would have sent the caller's reset into an open shop.
    # So `read_prompt` (tesseract on the prompt's own box, `prompt_text`) is
    # asked too, IN is a read of "Leave Shop" by either, and OUT is a read of
    # "Open Shop" back at the counter by either; anything else is trapped.
    def either(frame):
        words = panel(frame) if frame is not None else None
        alt = None
        if read_prompt is not None and frame is not None:
            try:
                alt = read_prompt(frame)
            except Exception:
                alt = None
        heard(words)
        if alt is not None and not says(words, LEAVE) and not says(words, OPEN):
            heard(f"(ocr) {alt}")
        return words, alt

    def state_now():
        """("in" | "out" | None, frame): a fresh frame, both readers."""
        frame = frame_now()
        words, alt = either(frame)
        if says(words, LEAVE) or says(alt, LEAVE):
            return "in", frame
        if says(words, OPEN) or says(alt, OPEN):
            return "out", frame
        return None, frame

    # EVERY E ON A FRESH READ, AND A DROPPED E LOOKED AT AGAIN (the review of
    # 2026-10-02 07:30). A read taken before the window was pictured and
    # transcribed is seconds old, and a close that lands late would let a
    # second E open the shop again. And GuardedInput drops the first E after
    # an owner's Pause by design ("e" is stale after a wait) -- the caller
    # looks again and presses again; only a Take Over is his to keep.
    def press_e(want: str) -> str:
        """'pressed', 'not-reading' (the fresh read is not `want`) or 'held'."""
        for _try in range(E_TRIES):
            state, _frame = state_now()
            if state != want:
                return "not-reading"
            if vin.tap("e") is not False:
                return "pressed"
            if asked(taken_over):
                return "held"
            sleep(E_RETRY_S)
        return "held"

    # IN: one E, on an exact "Open Shop" read again just before it.
    if asked(stopped):
        out.reason = "a stop was asked for at the counter"
        return out
    went = press_e("out")
    if went != "pressed":
        out.reason = ("the counter's prompt no longer read \"Open Shop\" just "
                      "before the E" if went == "not-reading" else
                      "the owner's Pause or Take Over held the E back")
        return out
    out.went_in = True
    # "OPENED NOTHING" ONLY ON TWO LOOKS IN A ROW AT THE COUNTER: one look can
    # be a window that has not drawn yet, and the caller resets after it.
    at_counter = 0
    for _ in range(LEAVE_LOOKS + 1):
        sleep(SETTLE_S)
        state, frame = state_now()
        if state == "in":
            _keep(keep_dir, frame, out, "window")
            if transcribe is not None:
                try:
                    out.window = str(transcribe(frame) or "")
                except Exception as exc:
                    say(f"shop look: could not transcribe the window ({exc})")
            if inside is not None:
                try:
                    inside(frame, out)
                except Exception as exc:
                    say(f"shop look: inside the window: {exc}")
            break
        at_counter = at_counter + 1 if state == "out" else 0
        if at_counter >= 2:
            out.went_in = False
            out.reason = ("E at \"Open Shop\" opened nothing (two looks in a row "
                          "still read the counter's prompt)")
            return out
    else:
        out.trapped = True
        _keep(keep_dir, frame_now(), out, "trapped")
        out.reason = (f"after the E neither reader saw \"Leave Shop\" "
                      f"(reads: {', '.join(out.reads[-6:])})")
        return out

    # OUT: E only on an exact "Leave Shop" read again just before it, and OUT
    # only on two looks in a row at the counter's "Open Shop" with no "Leave
    # Shop" between -- a failed or empty read is never "left".
    for _ in range(LEAVE_PRESSES):
        went = press_e("in")
        if went == "held":
            out.trapped = True
            out.reason = "the owner's Take Over held the E back, inside the shop"
            return out
        state, at_counter = None, 0
        for _look in range(LEAVE_LOOKS + 1):
            sleep(SETTLE_S)
            now, _frame = state_now()
            if now == "in":
                state = "in"
                break
            at_counter = at_counter + 1 if now == "out" else 0
            if at_counter >= 2:
                state = "out"
                break
        if state == "out":
            out.came_out = True
            out.ok = True
            say("shop look: out of the shop; the counter's \"Open Shop\" reads again")
            return out
        if state is None:
            out.trapped = True
            _keep(keep_dir, frame_now(), out, "not-out")
            out.reason = (f"after the E to leave, neither two looks of \"Open Shop\" "
                          f"nor \"Leave Shop\" -- not taken for out of the shop "
                          f"(reads: {', '.join(out.reads[-6:])})")
            return out
    out.trapped = True
    out.reason = f"E pressed {LEAVE_PRESSES}x on \"Leave Shop\" and it still reads it"
    return out


def _keep(folder: Path | None, frame, out: ShopLook, tag: str, ext: str = "png") -> None:
    if folder is None or frame is None:
        return
    try:
        import cv2
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{tag}.{ext}"
        cv2.imwrite(str(path), frame[:, :, :3])
        out.kept.append(str(path))
    except Exception:
        pass


# ---- what was seen, and when to look again ---------------------------------

# WHERE A SHOP'S WORDS ARE, at 1920x1080. MEASURED 2026-10-02 06:37:50 on the
# Ticket Tent's window (var/shoplook/20261002-063750-trapped.png), each read
# exactly by tesseract: the prompt's own box ("Leave Shop", the same box the
# blue prompts use -- "Fire the Red Cannon", "Open Shop" read there too), the
# item's name ("Photon Bee Egg") and price ("500 Tickets") at the top of the
# panel on the right, and the button between the arrows ("Can't afford").
PROMPT_BOX = (780, 58, 1140, 124)          # x0, y0, x1, y1
ITEM_NAME_BOX = (1696, 252, 1906, 294)
ITEM_PRICE_BOX = (1696, 296, 1906, 326)
BUTTON_BOX = (826, 862, 1034, 912)


def _ocr_line(frame, box, run=None, psm: int = 7) -> str:
    """One line of a shop's own text, by tesseract (vision/beemenu's binary
    and language); "" when it cannot run or the box is off the frame. `psm`
    6 reads a box of more than one line as one ("Buy for 60,000,000" over
    "Honey")."""
    import subprocess
    import cv2
    from ..vision.beemenu import LANGUAGE, TESSERACT
    if frame is None or getattr(frame, "size", 0) == 0:
        return ""
    x0, y0, x1, y1 = box
    crop = frame[y0:y1, x0:x1, :3]
    if crop.size == 0:
        return ""
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(grey, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    ok, png = cv2.imencode(".png", big)
    if not ok:
        return ""
    try:
        out = (run or subprocess.run)(
            [TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", str(int(psm))],
            input=png.tobytes(), capture_output=True, timeout=10.0)
    except (OSError, subprocess.SubprocessError):
        return ""
    raw = out.stdout
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    return " ".join(text.split())


def prompt_text(frame, run=None) -> str:
    """The prompt's own box read by tesseract, letters only ("Open Shop |"
    -> "open shop"): the second reader `look` asks, for a prompt the panel
    finder cannot see (a red one over a red wall)."""
    low = _ocr_line(frame, PROMPT_BOX, run).lower()
    return " ".join("".join(c if c.isalpha() else " " for c in low).split())


# A GIVER'S PROMPT RAISED ONE PANEL-HEIGHT. MEASURED 2026-10-12 (route audit):
# at the Bucko Bee the prompt was on screen in a miss, ~50 px higher than in a
# landing (var/routes/attempt-832/061848-*-26-walk-w20.jpg, over the HUD's
# Honey/Pollen bar, against attempt-820/190601-*-26), blue on Bucko's blue so
# the panel finder missed it, and PROMPT_BOX read only its last line ("ad").
# Read as a block (psm 6, the name wraps: "Talk to Gifted Bucko / Bee"), the
# normal box gives 'e talk to gifted bucko bee_' on the landing and the raised
# one 'e talk to gifted bucko : bee -' on the miss.
RAISED_PROMPT_BOX = (780, 8, 1140, 74)


def talk_prompt(frame, run=None) -> str:
    """'talk to <name>' read off the prompt's box or the one raised above it,
    letters only, from the words "talk to" on (the E key reads as a stray
    "e"); "" when neither box says it."""
    for box in (PROMPT_BOX, RAISED_PROMPT_BOX):
        low = _ocr_line(frame, box, run, psm=6).lower()
        words = " ".join("".join(c if c.isalpha() else " " for c in low).split())
        at = words.find("talk to ")
        if at >= 0:
            return words[at:]
    return ""


# A PLANTER'S OWN BAR, big and green at the top, when the character stands on
# it. MEASURED 2026-10-13 00:39:52 (var/planters/place-20261013-003952-unseen.jpg):
# the Blue Clay went into Spider -- the feed said "-1 Blue Clay Planter" -- but
# the camera faced a wall, so no "Harvest ..." prompt showed and the placing was
# booked unverified. The banner read "Blue Clay Planter (0.0%)" once its white
# letters were taken alone (tesseract reads the green as noise otherwise).
PLANTER_BANNER_BOX = (600, 150, 1320, 270)
# THE BAR SITS HIGHER OR LOWER WITH THE CAMERA: 01:47:12 the Ticket's
# "Ticket Planter (0.0%)" stood at y 268-336, below the box above
# (place-20261013-014712-unseen.jpg). Three overlapping bands find both
# measured bars and nothing on the Ticket that really was refused (00:40:56).
PLANTER_BANNER_BANDS = tuple((560, y, 1360, y + 120) for y in (150, 230, 310))


def white_banner_text(frame, run=None, box=PLANTER_BANNER_BOX, *, fx: float = 1.5,
                      white: int = 200, smooth: bool = False) -> str:
    """The white letters in `box`, as one line ("" when nothing reads).
    `fx`/`white`/`smooth` for a small bar (act/planter.BAR_STRIPS)."""
    import subprocess
    import cv2
    import numpy as np
    from ..vision.beemenu import LANGUAGE, TESSERACT
    if frame is None or getattr(frame, "size", 0) == 0:
        return ""
    x0, y0, x1, y1 = box
    crop = frame[y0:y1, x0:x1, :3]
    if crop.size == 0:
        return ""
    if smooth:
        crop = cv2.resize(crop, None, fx=fx, fy=fx, interpolation=cv2.INTER_CUBIC)
    page = np.where(crop.min(axis=2) > white, 0, 255).astype(np.uint8)
    if smooth:
        page = cv2.copyMakeBorder(page, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    else:
        page = cv2.resize(cv2.copyMakeBorder(page, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255),
                          None, fx=fx, fy=fx, interpolation=cv2.INTER_NEAREST)
    ok, png = cv2.imencode(".png", page)
    if not ok:
        return ""
    try:
        out = (run or subprocess.run)([TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "7"],
                                      input=png.tobytes(), capture_output=True, timeout=8.0)
    except (OSError, subprocess.SubprocessError):
        return ""
    text = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) else str(out.stdout)
    return " ".join(text.split())


def window_text(frame, run=None) -> str:
    """The window's item, price and button, by tesseract: a RECORD of what
    the shop showed ("Photon Bee Egg | 500 Tickets | Can't afford"), never a
    reason to press anything. The frame itself is kept beside it.

    THE BUTTON AS A BLOCK. A long price wraps the button's words onto two
    lines, and read as one line they were noise: MEASURED 2026-10-03 on the
    Mountain Top Shop's Spark Staff, "Buy forH%g,gIOO_OOO" by --psm 7 and
    "Buy for 60,000,000 Honey" by --psm 6, the Ticket Tent's three windows
    "Buy for 500 Tickets" either way."""
    return " | ".join(_ocr_line(frame, box, run, psm=psm)
                      for box, psm in ((ITEM_NAME_BOX, 7), (ITEM_PRICE_BOX, 7),
                                       (BUTTON_BOX, 6)))


# THE WINDOW'S ARROWS, MEASURED 2026-10-02 22:04 at the Ticket Tent
# (var/shoplook/20261002-220426-window.png): a blue bar across the bottom
# centre, x 761-1100 and y 847-926, a white arrow at each end and the green
# action button between them (831-1029). A 28 px patch round each arrow's
# centre read 0.97 blue-or-white and no green; the button's centre 0.73 green.
ARROW_LEFT = (788, 886)
ARROW_RIGHT = (1072, 886)
ARROW_HALF = 14
ARROW_MIN_SHARE = 0.85
BROWSE_MAX = 16            # the Ticket Tent sells 11 (wiki Ticket_Tent)
BROWSE_SETTLE_S = 0.8
BROWSE_SAME_LOOKS = 2      # reads of an unchanged window before the arrow is taken to have done nothing


def _shares(hsv, y0, y1, x0, x1):
    p = hsv[y0:y1, x0:x1]
    h, sat, val = p[..., 0], p[..., 1], p[..., 2]
    blue = (h >= 95) & (h <= 125) & (sat >= 120) & (val >= 120)
    white = (sat < 50) & (val > 210)
    green = (h >= 40) & (h <= 85) & (sat >= 100) & (val >= 60)
    red = ((h <= 8) | (h >= 170)) & (sat >= 120) & (val >= 80)
    # the dimmed button of an item already owned ("Equipped"): MEASURED
    # 2026-10-03 05:14 on the Mountain Top Shop's Beekeeper's Boots, H 95-98,
    # S ~181, V 141-207 -- the bar round it is H 108, V 255, none of it teal
    teal = (h >= 90) & (h <= 100) & (sat >= 120) & (val >= 120) & (val <= 215)
    return {k: float(v.mean()) if v.size else 0.0
            for k, v in (("blue", blue), ("white", white), ("green", green), ("red", red),
                         ("teal", teal))}


def bar_there(frame) -> bool:
    """The window's arrow bar is drawn: its blue above and below the button
    and in the gaps beside it, and the button green ("Buy for ...") or red
    ("Can't afford"). MEASURED 2026-10-02 on the two window frames (all 1.00,
    the button 0.73 green / 0.72 red) against twelve approach frames of the
    world outside (0.23 at most). Or teal, an owned item's dimmed "Equipped"
    (0.76): the Mountain Top Shop's browse stopped at the Boots on it
    (2026-10-03 05:14), three items in and the Hive Slot not reached."""
    import cv2
    import numpy as np
    if frame is None or frame.shape[0] < 930 or frame.shape[1] < 1100:
        return False
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[840:930, 760:1100, :3]),
                       cv2.COLOR_BGR2HSV)
    top = _shares(hsv, 9, 19, 30, 310)["blue"]           # y 849-859, x 790-1070
    bottom = _shares(hsv, 74, 84, 30, 310)["blue"]       # y 914-924
    gaps = min(_shares(hsv, 30, 60, 52, 66)["blue"],     # x 812-826
               _shares(hsv, 30, 60, 274, 288)["blue"])   # x 1034-1048
    button = _shares(hsv, 36, 57, 120, 220)              # y 876-897, x 880-980
    return (min(top, bottom, gaps) >= 0.9
            and max(button["green"], button["red"], button["teal"]) >= 0.5)


def arrow_there(frame, at=ARROW_RIGHT) -> bool:
    """The window's arrow is drawn at `at`: the bar is there (`bar_there`)
    and the arrow's white with the bar's blue round it, none of the button's
    green -- so a click there lands on the arrow and nothing else."""
    import cv2
    import numpy as np
    if not bar_there(frame):
        return False
    x, y = int(at[0]), int(at[1])
    patch = frame[y - ARROW_HALF:y + ARROW_HALF, x - ARROW_HALF:x + ARROW_HALF, :3]
    if patch.size == 0:
        return False
    got = _shares(cv2.cvtColor(np.ascontiguousarray(patch), cv2.COLOR_BGR2HSV),
                  0, 2 * ARROW_HALF, 0, 2 * ARROW_HALF)
    return (got["blue"] + got["white"] >= ARROW_MIN_SHARE and got["white"] >= 0.4
            and got["green"] < 0.02)


def item_name(window: str) -> str:
    """The item's name out of a `window_text` read ("Photon Bee Egg")."""
    return str(window or "").split("|")[0].strip()


BROWSE_CAME_ROUND = "came round"


def browse(click, frames, transcribe, *, sleep=time.sleep, stopped=None,
           keep=None, max_items: int = BROWSE_MAX, why=None) -> list:
    """Inside a shop's window: read it, click its right arrow, read again,
    until the first item comes round again. Returns each window read once,
    in order. The arrow is clicked only on a frame where `arrow_there` sees
    it; an unreadable name, a click the input refused, a stop, or an arrow
    that changed nothing ends it. `keep(frame, tag)` keeps a frame. `why`, a
    dict, is given "stopped": BROWSE_CAME_ROUND when the whole catalogue was
    read, else what ended it early."""
    seen: list = []
    first = None
    stop = f"{max_items} items read"
    for i in range(max_items + 1):
        frame, text = None, ""
        for _look in range(BROWSE_SAME_LOOKS):
            frame = frames()
            text = str(transcribe(frame) or "") if frame is not None else ""
            if not seen or item_name(text) != item_name(seen[-1]):
                break
            sleep(BROWSE_SETTLE_S)
        name = item_name(text)
        if not name:
            stop = "a window whose item's name did not read"
            break
        if seen and name == item_name(seen[-1]):
            stop = f"the arrow changed nothing (still {name!r})"
            break
        if first is None:
            first = name
        elif name == first:
            stop = BROWSE_CAME_ROUND
            break
        seen.append(text)
        if keep is not None:
            keep(frame, f"browse-{i:02d}")
        if stopped is not None and stopped():
            stop = "a stop was asked for"
            break
        if i >= max_items:
            break
        if not arrow_there(frame):
            stop = f"no arrow seen on the window at {name!r}"
            break
        if click(*ARROW_RIGHT) is False:
            stop = "the input refused the arrow's click"
            break
        sleep(BROWSE_SETTLE_S)
    if isinstance(why, dict):
        why["stopped"] = stop
    return seen


# ---- buying: the one click on the action button --------------------------
#
# THE OWNER, 2026-10-02: "the bot is allowed to do the game purchases so long
# as they dont cost robux meaning it can spend my honey tickets and other
# recourses without my permission". So `buy` presses the window's action
# button -- the only click on it anywhere -- and only when every word of the
# window says exactly the purchase asked for:
#
#   * the item's name is the one asked for (browsed to by the right arrow);
#   * the price reads as a number in the currency asked for, no more than
#     the caller allows, and the button repeats that price ("Buy for 500
#     Tickets", read 2026-10-02 22:04);
#   * NOTHING ON THE WINDOW SAYS ROBUX (or R$) -- a purchase in real money is
#     never this bot's, whatever else reads right;
#   * the button is green ("Buy ..."), never red ("Can't afford").
#
# After the click it looks again: the purchase is believed only when the
# button no longer offers the same purchase at the same price, or the
# caller's own count (`counted`, e.g. the tickets) fell by the price.
BUY_SETTLE_S = 1.5
BUY_WORDS = ("buy for", "purchase")
ROBUX_WORDS = ("robux", "r$")


def _number(text: str) -> int | None:
    """The first whole number in `text`, its thousands marked by "," or "."
    -- the window draws "60,000,000" and tesseract reads its commas as either
    (MEASURED 2026-10-03 on the Mountain Top Shop's prices: "60.000.000",
    "20,000.000", "15.000.000"). A "." that is not before exactly three
    digits ends the number ("1.5" is 1), so no decimal grows into a price.
    And a space between groups of three: MEASURED 2026-10-06 00:37, the Hive
    Slot's button read 'Buy for 508,855 908 Honey' and the purchase was refused
    as a button that did not offer the price (a merge made wrongly can only
    disagree with the price line, which refuses the purchase too)."""
    import re
    found = re.search(r"\d{1,3}(?:[., ]\d{3})+(?!\d)|\d+", str(text or ""))
    if not found:
        return None
    try:
        return int(re.sub(r"[., ]", "", found.group(0)))
    except ValueError:
        return None


def _norm_name(text: str) -> str:
    return " ".join(str(text or "").lower().split())


@dataclass
class Bought:
    ok: bool = False
    reason: str = ""
    window: str = ""             # what the window read when the button was pressed
    after: str = ""              # and after
    price: int | None = None
    browsed: list = field(default_factory=list)

    def describe(self) -> str:
        return (f"bought it — {self.window!r}" if self.ok
                else f"did not buy: {self.reason}")


BUTTON_PRICE_SLACK = 1e-5


def buy(click, frames, transcribe, want: str, *, currency: str, most: int,
        sleep=time.sleep, stopped=None, keep=None, counted=None,
        button_green=None) -> Bought:
    """Inside a shop's window: browse to `want` and press its button once,
    under the rules above. `counted()`: the caller's count of `currency` now
    (None when unknown). `button_green(frame)`: the button reads as the green
    "Buy" one (default: the bar's own colour test)."""
    out = Bought()
    want_n = _norm_name(want)
    green = button_green or _button_green
    frame, text, unchanged, last, first = None, "", 0, None, None
    for i in range(BROWSE_MAX + 1):
        frame = frames()
        text = str(transcribe(frame) or "") if frame is not None else ""
        name = _norm_name(item_name(text))
        if name == want_n:
            break
        if first is None:
            first = name
        elif name == first and name != last:
            out.reason = f"{want!r} not found: the catalogue came round in {len(out.browsed)} item(s)"
            return out
        # AN ARROW THAT CHANGED NOTHING ends the search (`browse`'s own rule)
        unchanged = unchanged + 1 if (last is not None and name == last) else 0
        if unchanged >= BROWSE_SAME_LOOKS:
            out.reason = f"the arrow stopped changing the item (at {item_name(text)!r})"
            return out
        if last is None or name != last:
            out.browsed.append(text)
        last = name
        if stopped is not None and stopped():
            out.reason = "a stop was asked for while browsing"
            return out
        if i >= BROWSE_MAX or not arrow_there(frame):
            out.reason = f"{want!r} not found in {len(out.browsed)} item(s)"
            return out
        if click(*ARROW_RIGHT) is False:
            out.reason = "the input refused the arrow's click"
            return out
        sleep(BROWSE_SETTLE_S)
    else:
        out.reason = f"{want!r} not found"
        return out
    out.browsed.append(text)
    out.window = text
    low = text.lower()
    if any(word in low for word in ROBUX_WORDS):
        out.reason = f"the window mentions Robux ({text!r}) -- never bought"
        return out
    parts = [p.strip() for p in text.split("|")]
    price_text = parts[1] if len(parts) > 1 else ""
    button = parts[2] if len(parts) > 2 else ""
    out.price = _number(price_text)
    if out.price is None or currency.lower() not in price_text.lower():
        out.reason = f"the price does not read as {currency} ({price_text!r})"
        return out
    if out.price > int(most):
        out.reason = f"it costs {out.price:,} {currency}, over the {int(most):,} allowed"
        return out
    # "Buy for 500 Tickets" (the Ticket Tent, read 2026-10-02) must repeat the
    # price; a bare "Purchase" (the wiki's other shops) carries none, so the
    # price line above is the price
    said = _number(button)
    low_button = button.lower()
    # THE BUTTON SAYS WHAT IS SPENT. MEASURED 2026-10-06 04:55: slot 39's window
    # read '676,212.641 Honey' over 'Buy for 676,212,647 Honey' -- the price line
    # misread in its last digit -- and the purchase was refused. A button naming
    # the currency, within `most`, and within BUTTON_PRICE_SLACK of the price
    # line (a digit dropped is ten times off, and still refused) is taken at its word.
    if (said is not None and out.price and said != out.price and "buy for" in low_button
            and currency.lower() in low_button and said <= int(most)
            and abs(said - out.price) <= max(10, out.price * BUTTON_PRICE_SLACK)):
        out.price = said
    # "CRAFT ITEM" FOR GEAR WITH A RECIPE. MEASURED 2026-10-07 02:15 at the Blue
    # HQ: 'Bubble Mask | 100.000.000 Honey | Craft Item' (and the Blue Guard's)
    # -- a price line in honey, a button without one, which the game draws green
    # only when the honey and every material are held (`green`, below)
    offers = (("buy for" in low_button and said == out.price)
              or ("purchase" in low_button and "purchased" not in low_button
                  and said in (None, out.price))
              or ("craft item" in low_button and said is None))
    if not offers:
        out.reason = f"the button does not offer this purchase ({button!r})"
        return out
    if not green(frame):
        out.reason = f"the button is not the green buy button ({button!r})"
        return out
    had = counted() if counted is not None else None
    if stopped is not None and stopped():
        out.reason = "a stop was asked for at the button"
        return out
    x0, y0, x1, y1 = BUTTON_BOX
    if click((x0 + x1) // 2, (y0 + y1) // 2) is False:
        out.reason = "the input refused the button's click"
        return out
    sleep(BUY_SETTLE_S)
    after_frame = frames()
    out.after = str(transcribe(after_frame) or "") if after_frame is not None else ""
    if keep is not None:
        keep(after_frame, "bought")
    has = counted() if counted is not None else None
    if had is not None and has is not None and had - has >= out.price:
        out.ok, out.reason = True, f"{currency} fell {had:,} -> {has:,}"
        return out
    if out.after and out.after != out.window:
        out.ok, out.reason = True, f"the window changed to {out.after!r}"
        return out
    out.reason = (f"the click changed nothing that was read (window {out.after!r}"
                  + (f", {currency} {had} -> {has}" if had is not None else "") + ")")
    return out


def _button_green(frame) -> bool:
    import cv2
    import numpy as np
    if frame is None:
        return False
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[876:897, 880:980, :3]), cv2.COLOR_BGR2HSV)
    return _shares(hsv, 0, hsv.shape[0], 0, hsv.shape[1])["green"] >= 0.5


# ---- a game window's own close: the red square with a white X -------------
#
# MEASURED on the wiki's picture of the Blender's window (File:Blendermenu.png,
# read 2026-10-03): its close is a red square at the window's top left, a
# white X on it, the blue title bar running right from it. Found by its
# colours wherever the window is drawn, so a window not yet seen on this
# machine can still be shut by its own button.
CLOSE_MIN_SIDE = 24
CLOSE_MAX_SIDE = 140


def find_close_x(frame):
    """(x, y) of a window's red close square -- red, near-square, with white
    inside it and the window's blue just right of it -- or None."""
    import cv2
    import numpy as np
    if frame is None:
        return None
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[:, :, :3]), cv2.COLOR_BGR2HSV)
    h, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = (((h <= 8) | (h >= 170)) & (sat >= 140) & (val >= 110)).astype(np.uint8)
    blue = (h >= 100) & (h <= 125) & (sat >= 120) & (val >= 120)
    white = (sat <= 40) & (val >= 220)
    n, _labels, stats, _cent = cv2.connectedComponentsWithStats(red, connectivity=8)
    best = None
    for i in range(1, n):
        x, y, w, hh, area = stats[i]
        if not (CLOSE_MIN_SIDE <= w <= CLOSE_MAX_SIDE and CLOSE_MIN_SIDE <= hh <= CLOSE_MAX_SIDE):
            continue
        if not 0.75 <= w / float(hh) <= 1.33 or area < 0.45 * w * hh:
            continue
        inside = white[y:y + hh, x:x + w].mean()
        right = blue[y:y + hh, x + w:min(frame.shape[1], x + w + 2 * w)].mean()
        if inside < 0.05 or right < 0.4:
            continue
        if best is None or (y, x) < (best[1], best[0]):
            best = (x + w // 2, y + hh // 2)
    return best


def code() -> str:
    """This module's bytes, so a fix to the look makes a failed one due again."""
    try:
        return hashlib.sha1(Path(__file__).read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


def _load(path: Path) -> dict:
    try:
        body = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def record(path: Path, look: ShopLook, *, shop: str, clock=time.time) -> dict:
    """Append one look to `path` (var/shoplook.json); returns the entry."""
    from ..files import atomic_write
    body = _load(path)
    entry = {"at": clock(), "shop": shop, "ok": bool(look.ok),
             "reason": str(look.reason), "went_in": bool(look.went_in),
             "came_out": bool(look.came_out), "trapped": bool(look.trapped),
             "steps": int(look.steps), "window": str(look.window)[:4000],
             "reads": list(look.reads)[-READS_KEPT:], "kept": list(look.kept),
             "catalogue": list(look.catalogue)[:BROWSE_MAX + 1],
             "code": code()}
    looks = body.get("looks") if isinstance(body.get("looks"), list) else []
    body["looks"] = _pruned(looks + [entry])
    atomic_write(Path(path), json.dumps(body, indent=1))
    # WHAT THE WINDOW SHOWED OWNED (brain/sight, ROADMAP G13): every item panel
    # read, by its own name, "Equip(ped)"/"Purchased" or a price, with its frame
    # -- the evidence the gear questions are checked against before asking
    try:
        from ..brain import sight
        sight.record_look(Path(path).parent, entry, clock=clock)
    except Exception:
        pass
    return entry


# THE FILE IS THE MEMORY OF WHAT WAS DONE, so a done look must outlive the
# pruning. It kept the last 20 looks, and MEASURED 2026-10-03 05:34 the
# night's fourteen shop surveys had pushed out the Ticket Tent's first look
# and its catalogue -- both walked again -- and would next have pushed out
# the slot survey that holds the Mountain Top Shop's way in
# (run_farm.mts_counter_legs), losing the Hive Slot's route. Now LOOKS_KEPT
# looks, and past them each shop's newest look that went right is kept.
LOOKS_KEPT = 400
READS_KEPT = 80            # a survey reads after each of its legs and taps


def _pruned(looks: list) -> list:
    if len(looks) <= LOOKS_KEPT:
        return looks
    recent = looks[-LOOKS_KEPT:]
    done = {e.get("shop") for e in recent if isinstance(e, dict) and e.get("ok")}
    older: dict = {}
    for e in looks[:-LOOKS_KEPT]:
        if isinstance(e, dict) and e.get("ok") and e.get("shop") not in done:
            older.pop(e.get("shop"), None)       # the newest of each, in order
            older[e.get("shop")] = e
    return list(older.values()) + recent


VIA_MISS_RETRY_SECONDS = 3600.0


def not_due(path: Path, shop: str, retry_seconds: float, clock=time.time) -> str:
    """Why `shop` is not to be looked at now, or "". Looked at once, it is
    not looked at again here (what comes next is buying, a separate step);
    a look that failed waits `retry_seconds`, unless this module changed."""
    looks = [e for e in (_load(path).get("looks") or [])
             if isinstance(e, dict) and e.get("shop") == shop]
    if any(e.get("ok") for e in looks):
        when = max(float(e.get("at") or 0.0) for e in looks if e.get("ok"))
        return f"already looked at, {time.strftime('%Y-%m-%d %H:%M', time.localtime(when))}"
    if not looks:
        return ""
    last = looks[-1]
    try:
        age = clock() - float(last.get("at") or 0.0)
    except (TypeError, ValueError):
        return ""
    # A WALK THERE THAT MISSED IS NOT A LOOK. MEASURED 2026-10-21 11:52
    # (pro_shop_survey_door_jump): the route to the start missed its ledge
    # jump, only the "arrived" read was taken, and the new legs then waited
    # the full 6 h without being tried once.
    # Surveys only: other looks keep no reads at all.
    if "_survey" in shop and len(last.get("reads") or ()) <= 1:
        retry_seconds = min(retry_seconds, VIA_MISS_RETRY_SECONDS)
    if last.get("code") == code() and 0 <= age < retry_seconds:
        return (f"tried {age / 60:.0f} min ago and did not get a look "
                f"({str(last.get('reason'))[:120]})")
    return ""



# THE TICKET TENT'S DOORWAY, BY ITS CARPET. MEASURED 2026-10-02 on the
# approach frames kept by the looks at 06:37 (in at the 8th step) and 11:38
# (pressed against the tent's wall right of the doorway): the yellow carpet
# that runs into the doorway is the biggest yellow blob below the ticket sign
# (H 18-32, S >= 150, V >= 180, rows 33%-75% of the frame), centred at x 781
# four steps out on the look that went in and at x 685 on the one that
# missed, the character at the centre (960); by the miss's 8th step the
# carpet had slid to x 529. So the approach walks w and sidesteps toward the
# carpet whenever its centre is more than CARPET_DEADBAND px off the
# character's.
CARPET_HUE = (18, 32)
CARPET_SAT_MIN, CARPET_VAL_MIN = 150, 180
CARPET_ROWS = (0.33, 0.75)
CARPET_MIN_PX = 1500
CARPET_DEADBAND = 120


def ticket_tent_steer(frame) -> str:
    """'w', 'wa' or 'wd': forward, edging toward the doorway's carpet."""
    import cv2
    import numpy as np
    if frame is None or getattr(frame, "size", 0) == 0:
        return "w"
    h, w = frame.shape[:2]
    y0, y1 = int(h * CARPET_ROWS[0]), int(h * CARPET_ROWS[1])
    band = frame[y0:y1, :, :3]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 0] >= CARPET_HUE[0]) & (hsv[:, :, 0] <= CARPET_HUE[1])
            & (hsv[:, :, 1] >= CARPET_SAT_MIN) & (hsv[:, :, 2] >= CARPET_VAL_MIN)
            ).astype(np.uint8)
    n, _lbl, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return "w"
    best = max(range(1, n), key=lambda i: stats[i][4])
    if stats[best][4] < CARPET_MIN_PX:
        return "w"
    dx = float(cents[best][0]) - w / 2.0
    if dx < -CARPET_DEADBAND:
        return "wa"
    if dx > CARPET_DEADBAND:
        return "wd"
    return "w"

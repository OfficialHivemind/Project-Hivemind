"""The game's own Auto-Jelly switch: read in the Settings tab, and switched OFF.

THE OWNER, 2026-10-14 (ROADMAP H12): a fully autonomous bot has to be able to
turn Auto-Jelly off itself. With BSS's Auto-Jelly ON every
Jelly Beans use and every one-at-a-time Royal Jelly roll is refused with a
"... (Auto-Jelly is ON)" box (act/inventory.dialog_question reads it as
"<question> autojelly on"). The BSS wiki: the System Page opens from "the cog
in the menu bar" and the Auto-Jelly settings are "at the bottom" of it.

MEASURED 2026-10-14 22:55 on the first look (var/autojelly/20261014-225554/
page-00.jpg): the gear opens a side panel, x 0-310 -- Promo Codes, Trade,
Leaderboards, Cub Console, then "Options:" rows, each a label and TWO buttons,
ON at x~221 and OFF at x~274; the CURRENT state is the bright one (ON green
S~180, OFF red S~200; the other faded, S 34-47). A whole-page OCR mangled it
("Optlons", "Mus:c"); one row's label read alone (psm 7, Otsu) reads clean.
Every step is checked and anything unsure closes the tab and says so:

  1. THE GEAR, TEMPLATE-CHECKED. The fifth HUD button (vision/questmenu
     BUTTONS, "settings") is clicked only when the white shape at its place
     matches data/templates/ui/hud_settings_gear.png (cut 2026-10-14 from
     var/routes/attempt-1002 ...-00-start.jpg) by BUTTON_IOU and beats the
     inventory/quests/bees/badges/Robux buttons' places by BUTTON_MARGIN.
     MEASURED over 150 saved route start frames: 146 pass, 4 refused (bright
     backgrounds) -- a refusal clicks nothing. Never the Robux shop beside it.
  2. THE PAGE MUST LOOK LIKE SETTINGS: at least SETTINGS_MINIMUM option rows
     (an ON/OFF button pair at the measured places) before the wheel turns.
  3. THE ROW BY ITS LABEL: each option row's label read alone; the one whose
     letters read "autojelly". Its state is the bright button; neither or both
     bright, or two such rows, is unsure.
  4. ONLY IN `act` MODE, and only when it reads ON, its OFF button is clicked
     once, the page read again, and OFF believed only when read.
  5. NO KEYS -- never Enter, never Escape (Roblox's menu). The only way out is
     the gear it came in by (act/quests._close).

SAFE ROLLOUT, `economy.auto_jelly_off`: "look" (the default) does all of it but
the click, keeps every frame in var/autojelly/<stamp>/ and logs what it WOULD
click; Claude flips it to "act" after reading those frames.
"""
from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..vision import questmenu
from . import quests

ROOT = Path(__file__).resolve().parents[3]
KEEP_DIR = ROOT / "var" / "autojelly"
JELLY_FILE = ROOT / "var" / "jelly.json"            # run_farm's "auto_jelly_at"
GEAR_TEMPLATE = ROOT / "data" / "templates" / "ui" / "hud_settings_gear.png"
BUTTON = "settings"
# THE TAB (MEASURED 2026-10-14, see above), at 1920x1080. The wheel turns over
# the panel's list (act/badges' side list, x 0-320, y 170-970).
LIST_BOX = (0, 170, 320, 970)
LIST_POINT = (150, 600)
PAGE_NOTCHES = 5                 # positive is down (act/badges)
PAGES_MOST = 8
END_CHANGE = 0.02
ON_X, OFF_X = 221, 274           # the two buttons' centres
BUTTON_HALF = (18, 8)            # half width, half height looked at
LABEL_X = (2, 192)               # the label's strip, left of the buttons
ROW_HALF = 16
ROWS_Y = (180, 960)
GREEN_H, RED_H = (55, 95), (10, 155)     # hue: green inside; red/pink outside
BUTTON_V = 100
SAT_BRIGHT = 120                 # the current state's button (measured 177-200)
SAT_FADED = 90                   # the other one (measured 34-47)
SETTINGS_MINIMUM = 3
LABEL = "autojelly"
LABEL_SIMILAR = 0.8
# THE AUTO-JELLY SECTION (MEASURED 2026-10-14 23:35, var/autojelly/20261014-
# 233540/page-05.jpg): no one "Auto-Jelly" switch -- a header "Auto-Jelly
# Settings:" at the list's bottom, 44 px above four ON/OFF rows: Until
# Legendary, Until Mythic, Require Gifted, Require Mutation (the wiki's System
# Page: jellies auto-roll until those are met; ALL OFF = no Auto-Jelly). Their
# outlined labels OCR as noise ("Vrid Legemdery"), so the rows go by ORDER under
# the header, which reads near enough ("Avto-Jely Settngs").
SECTION = "autojellysettings"
SECTION_SIMILAR = 0.7
SECTION_ROWS = ("Until Legendary", "Until Mythic", "Require Gifted", "Require Mutation")
HEADER_ABOVE = 44
HEADER_X1 = 310
ROW_GAP = (40, 60)
CLICK_SETTLE_S = 1.0
MIN_GAP_S = 3600.0               # a box seen again re-runs it, at most hourly
MODES = ("off", "look", "act")     # off: never opened (run_farm skips it)


@dataclass
class Toggle:
    state: str                   # "on" / "off"
    x: int                       # its OFF button's centre: the click
    y: int
    row_y: int
    green: float
    red: float


@dataclass
class AutoJellyRun:
    ok: bool = False
    mode: str = "look"
    state: str = ""              # what the row read: on / off / ""
    would_click: tuple | None = None
    switches: list = field(default_factory=list)
    clicked: bool = False
    now_off: bool = False
    reason: str = ""
    menu_open: bool = False
    pages: int = 0
    kept: str = ""

    def describe(self) -> str:
        tail = " — SETTINGS STILL OPEN" if self.menu_open else ""
        if self.now_off:
            return ("Auto-Jelly: switched off in Settings (" + ", ".join(self.switches)
                    + " now OFF)" + tail)
        if self.state == "off":
            return "Auto-Jelly: already OFF in Settings, nothing to do" + tail
        if self.state == "on" and self.mode == "look":
            return (f"Auto-Jelly: found it ON in Settings ({', '.join(self.switches)}); "
                    f"would switch it off (look-only) — OFF buttons at {self.would_click}" + tail)
        return f"Auto-Jelly: not switched — {self.reason}" + tail


def mode_of(settings) -> str:
    try:
        value = str(settings.get("economy.auto_jelly_off") or "look")
    except Exception:
        return "look"
    return value if value in MODES else "look"


# ---- when ----------------------------------------------------------------

def _at(path: Path, key: str) -> float:
    try:
        return float(json.loads(Path(path).read_text()).get(key) or 0.0)
    except (OSError, ValueError, AttributeError, TypeError):
        return 0.0


def mark_box(keep_dir: Path = KEEP_DIR, clock=time.time) -> None:
    """The "(Auto-Jelly is ON)" box was seen (a Jelly Beans use refused)."""
    try:
        Path(keep_dir).mkdir(parents=True, exist_ok=True)
        (Path(keep_dir) / "box.json").write_text(json.dumps({"at": clock()}))
    except OSError:
        pass


def due(keep_dir: Path = KEEP_DIR, jelly_file: Path = JELLY_FILE, clock=time.time) -> bool:
    """Never looked, or the box came back since the last look (an hour on).
    Once a process is the caller's."""
    last = _at(Path(keep_dir) / "last.json", "at")
    if not last:
        return True
    box = max(_at(Path(keep_dir) / "box.json", "at"), _at(jelly_file, "auto_jelly_at"))
    return box > last and clock() - last >= MIN_GAP_S


# ---- pixels and words ------------------------------------------------------

def gear_check(frame, template=None) -> tuple[bool, float, float]:
    """(the gear is where measured, its IoU, the best other button's IoU) --
    vision/questmenu.button_check, which every HUD errand now shares."""
    return questmenu.button_check(frame, BUTTON, template)


def _letters(text) -> str:
    return re.sub(r"[^a-z]", "", str(text or "").lower())


def _is_label(letters: str) -> bool:
    if LABEL in letters:
        return True
    n = len(LABEL)
    return any(difflib.SequenceMatcher(None, letters[i:i + n], LABEL).ratio() >= LABEL_SIMILAR
               for i in range(max(1, len(letters) - n + 1)))


@dataclass
class Option:
    label: str
    y: int
    state: str | None            # "on" / "off" / None (unsure)
    sat_on: float
    sat_off: float


def _button(hsv, x: int, y: int):
    import numpy as np
    hx, hy = BUTTON_HALF
    p = hsv[max(0, y - hy):y + hy, max(0, x - hx):x + hx].reshape(-1, 3)
    return np.median(p, 0) if p.size else None


def _is_pair(hsv, y: int) -> bool:
    on, off = _button(hsv, ON_X, y), _button(hsv, OFF_X, y)
    if on is None or off is None:
        return False
    return (GREEN_H[0] <= on[0] <= GREEN_H[1] and on[2] >= BUTTON_V
            and not (RED_H[0] < off[0] < RED_H[1]) and off[2] >= BUTTON_V)


def read_label(frame, y: int, run=None, x1: int = None) -> str:
    """One option row's label read alone (psm 7): grey, x3, Otsu, dark on light.
    `x1` widens it (the section header spans the panel)."""
    import subprocess
    import cv2
    from ..vision.beemenu import LANGUAGE, TESSERACT
    crop = frame[max(0, y - ROW_HALF):y + ROW_HALF, LABEL_X[0]:(x1 or LABEL_X[1]), :3]
    if crop.size == 0:
        return ""
    g = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), None, fx=3, fy=3,
                   interpolation=cv2.INTER_CUBIC)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if b.mean() < 128:
        b = 255 - b
    ok, png = cv2.imencode(".png", cv2.copyMakeBorder(b, 10, 10, 10, 10,
                                                      cv2.BORDER_CONSTANT, value=255))
    if not ok:
        return ""
    try:
        out = (run or subprocess.run)([TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "7"],
                                      input=png.tobytes(), capture_output=True, timeout=10.0)
    except (OSError, subprocess.SubprocessError):
        return ""
    text = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) else str(out.stdout)
    return text.strip()


def option_rows(frame, read=None) -> list[Option]:
    """Every option row on the page: an ON/OFF pair at the measured places,
    its state the bright button, its label read alone."""
    import cv2
    import numpy as np
    if frame is None:
        return []
    read = read or read_label
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[:, :, :3]), cv2.COLOR_BGR2HSV)
    ys = [y for y in range(ROWS_Y[0], min(ROWS_Y[1], frame.shape[0] - 10), 2) if _is_pair(hsv, y)]
    runs: list[list[int]] = []
    for y in ys:
        if runs and y - runs[-1][-1] <= 4:
            runs[-1].append(y)
        else:
            runs.append([y])
    out = []
    for run in runs:
        if run[-1] - run[0] < 2 * BUTTON_HALF[1]:          # too thin for a button
            continue
        y = (run[0] + run[-1]) // 2
        on, off = _button(hsv, ON_X, y), _button(hsv, OFF_X, y)
        s_on, s_off = float(on[1]), float(off[1])
        state = ("on" if s_on >= SAT_BRIGHT and s_off <= SAT_FADED else
                 "off" if s_off >= SAT_BRIGHT and s_on <= SAT_FADED else None)
        out.append(Option(read(frame, y), y, state, s_on, s_off))
    return out


def looks_like_settings(rows) -> bool:
    return len(rows) >= SETTINGS_MINIMUM


def _is_section(letters: str) -> bool:
    n = len(SECTION)
    return any(difflib.SequenceMatcher(None, letters[i:i + n], SECTION).ratio() >= SECTION_SIMILAR
               for i in range(max(1, len(letters) - n + 1)))


def find_section(frame, rows, read=None) -> tuple[list | None, str]:
    """The four Auto-Jelly rows under their header, in SECTION_ROWS' order,
    or (None, why); why "" = not on this page (scroll on)."""
    read = read or (lambda f, y: read_label(f, y, x1=HEADER_X1))
    clusters: list[list] = []
    for r in rows:
        if clusters and ROW_GAP[0] <= r.y - clusters[-1][-1].y <= ROW_GAP[1]:
            clusters[-1].append(r)
        else:
            clusters.append([r])
    for c in clusters:
        if c[0].y - HEADER_ABOVE < ROWS_Y[0] - ROW_HALF:
            continue                      # its header is off the top: scroll on
        if not _is_section(_letters(read(frame, c[0].y - HEADER_ABOVE))):
            continue
        if len(c) != len(SECTION_ROWS):
            return None, (f"the Auto-Jelly section has {len(c)} row(s), "
                          f"{len(SECTION_ROWS)} wanted — not guessing")
        unsure = [SECTION_ROWS[i] for i, r in enumerate(c) if r.state is None]
        if unsure:
            return None, f"{', '.join(unsure)} not plainly ON or OFF"
        return c, ""
    return None, ""


def _said(section) -> str:
    return ", ".join(f"{name} {r.state.upper()}" for name, r in zip(SECTION_ROWS, section))


# ---- the errand ------------------------------------------------------------

def switch_off(vin, frames, *, settings=None, read=None, sleep=time.sleep,
               on_note=None, keep_dir: Path = KEEP_DIR, stamp=None,
               clock=time.time, template=None) -> AutoJellyRun:
    """Open Settings by the gear, find Auto-Jelly, switch it off in `act`
    mode (only say so in `look`), close by the gear. Written to last.json."""
    note = on_note or (lambda text: None)
    read = read or read_label           # (frame, row y) -> the row's label
    out = AutoJellyRun(mode=mode_of(settings))
    folder = Path(keep_dir) / (stamp or time.strftime("%Y%m%d-%H%M%S"))
    try:
        _run(vin, frames, read, sleep, note, out, folder, template)
    except Exception as exc:
        out.reason = out.reason or f"raised: {exc}"
    finally:
        quests._park(vin, note)
        try:
            Path(keep_dir).mkdir(parents=True, exist_ok=True)
            (Path(keep_dir) / "last.json").write_text(json.dumps(
                {"at": clock(), "mode": out.mode, "state": out.state,
                 "now_off": out.now_off, "said": out.describe(), "kept": out.kept}))
        except OSError:
            pass
    note(out.describe())
    return out


def _keep(folder: Path, frame, name: str, words=(), out=None) -> None:
    try:
        import cv2
        folder.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(folder / f"{name}.jpg"), frame[:, :, :3],
                    [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if words:
            (folder / f"{name}.txt").write_text("\n".join(
                f"y {r.y}\t{r.state or '?'}\t(ON S {r.sat_on:.0f}, OFF S {r.sat_off:.0f})\t{r.label}"
                for r in words))
        if out is not None:
            out.kept = str(folder)
    except Exception:
        pass


def _run(vin, frames, read, sleep, note, out, folder, template) -> None:
    before = quests._grab(frames, note)
    if before is None:
        out.reason = "no frame to look at"
        return
    _keep(folder, before, "00-before", out=out)
    ok, gear, other = gear_check(before, template)
    if not ok:
        out.reason = (f"the gear button is not plainly where it was measured (match "
                      f"{gear:.2f}, best other button {other:.2f}) — nothing clicked")
        return
    x, y = questmenu.button_at(questmenu.BUTTONS.index(BUTTON))
    note(f"Auto-Jelly: opening Settings by the gear at ({x}, {y}) (match {gear:.2f})")
    if vin.click(x, y) is False:
        out.reason = "the click was held back by the owner's Pause or Take Over"
        return
    sleep(quests.SETTLE_SECONDS)
    page = quests._grab(frames, note)
    changed = quests.changed_fraction(before, page) if page is not None else 0.0
    if page is None or changed < quests.CHANGED_TO_OPEN:
        out.reason = f"nothing opened ({changed:.0%} of the screen changed) — no more clicks"
        if page is not None:
            _keep(folder, page, "01-nothing", out=out)
        return
    out.menu_open = True
    try:
        _inside(vin, frames, read, sleep, note, out, folder, page)
    finally:
        last = quests._grab(frames, note)
        quests._close(vin, frames, before, out, sleep, note, x, y,
                      opened=last if last is not None else page,
                      what="Settings tab", gone=_gone(last))


def _gone(opened):
    """A side panel's border (vision/questlist.side_panel) when one shows."""
    from ..vision import questlist
    try:
        if opened is None or questlist.side_panel(opened) is None:
            return None
    except Exception:
        return None
    return lambda now: questlist.side_panel(now) is None


def _inside(vin, frames, read, sleep, note, out, folder, page) -> None:
    words = option_rows(page, read)
    _keep(folder, page, "page-00", words, out)
    out.pages = 1
    if not looks_like_settings(words):
        out.reason = (f"what opened does not look like Settings ({len(words)} option "
                      f"row(s), {SETTINGS_MINIMUM} wanted) — backing out")
        return
    section, why = find_section(page, words, read)
    n = 0
    while section is None and not why and n + 1 < PAGES_MOST:
        n += 1
        vin.move_mouse(*LIST_POINT)
        vin.scroll(PAGE_NOTCHES)
        sleep(quests.SETTLE_SECONDS)
        nxt = quests._grab(frames, note)
        if nxt is None:
            break
        x0, y0, x1, y1 = LIST_BOX
        if quests.changed_fraction(page[y0:y1, x0:x1], nxt[y0:y1, x0:x1]) < END_CHANGE:
            break                                    # the list's end
        page, words = nxt, option_rows(nxt, read)
        _keep(folder, page, f"page-{n:02d}", words, out)
        out.pages += 1
        section, why = find_section(page, words, read)
    if section is None:
        out.reason = why or f"no Auto-Jelly section in {out.pages} page(s) of Settings"
        return
    on = [(SECTION_ROWS[i], r) for i, r in enumerate(section) if r.state == "on"]
    out.state = "on" if on else "off"
    note(f"Auto-Jelly: {_said(section)}")
    if not on:
        out.ok = True
        return
    out.would_click = tuple((OFF_X, r.y) for _name, r in on)
    out.switches = [name for name, _r in on]
    if out.mode != "act":
        out.ok = True
        out.reason = "look-only (economy.auto_jelly_off is look)"
        return
    for _name, r in on:
        if vin.click(OFF_X, r.y) is False:
            out.reason = "the click was held back by the owner's Pause or Take Over"
            return
        out.clicked = True
        sleep(CLICK_SETTLE_S)
    again = quests._grab(frames, note)
    if again is None:
        out.reason = "clicked, but no frame to check it by"
        return
    words = option_rows(again, read)
    _keep(folder, again, "after-click", words, out)
    check, why = find_section(again, words, read)
    if check is not None and all(r.state == "off" for r in check):
        out.ok, out.now_off, out.state = True, True, "off"
        return
    out.reason = ("clicked once each; after: "
                  + (_said(check) if check else why or "the section is gone") + " — not clicking again")

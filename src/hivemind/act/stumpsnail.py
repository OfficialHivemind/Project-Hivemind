"""The Stump Snail: chipped at over many sessions, and only while that beats
gathering.

WHAT IT IS (wiki Stump_Snail, read 2026-10-12 through the API): a level 6 mob
with 30,000,000 HP that circles the Stump Field, "posing no direct threat but
dealing 30 damage upon contact" (its head only), and goes back to its cave in a
straight line once the player leaves. "Like the Commando Chick, the Stump
Snail's health is saved, allowing players to attack it in multiple sessions."
Beaten, it gives a Shell Amulet (at least bronze), 30,000,000 honey, 1-100 Glue
and 1-10 Star Jelly for certain; 50-250 tickets, 1-25 Magic Beans and more
maybe -- straight into the inventory, no tokens -- and comes back in 96 hours
(81.6 with a gifted Vicious Bee).

MEASURED ON THIS ACCOUNT, the bar's own "HP:" read by eye off the four Stump
trips of 2026-10-06 (var/routes/attempt-676, *_stump* frames):

    06:37:20  29,879,792     trips.jsonl: 1,169 s gathered there
    07:01:47  29,774,018                    568 s
    07:16:49  29,720,512                  1,194 s
    07:37:48  29,635,540

The damage IS kept across visits (the label reads "Stump Snail (Lvl 6) (HP
Saves)"), and 243,558 HP came off in 2,931 s in the field: 83 HP/s (71-94 by
trip). The rest is ~99 hours of fighting at that rate. On 2026-10-12 the
planner's own rate for the next trip (brain/decide `_measured_rate` on
var/field_notes.json, Pine Tree's paid pair) read 3,747 pollen/s, and the trip
ledger's last 48 h ran 25,000-37,000 a second gathered on the three best
fields. The owner's guide (data/knowledge/guides/blue_hive_guide.md:1331):
"Stump Snail: seldom worth turning on".

NATRO'S FIGHT (submacros/natro_macro.ahk:15482-15641, read 2026-10-12): every 4
days with StumpSnailCheck on (default off, :598): reset, `nm_gotoField("stump")`,
20 looks 150 ms apart for any health bar, one tile forward, the sprinkler, the
camera up twice (PgUp, :157), then the tool held in 30 s blocks until the
amulet table (`nm_AmuletPrompt`, its sign of a kill, :15553), a death, a frozen
honey counter, or SnailTime minutes (5/10/15/"Kill", default 15: :594, :5472).
A time limit brings the next try 30 min on (:15599), no snail 2 h (:15614), a
kill 4 days. Its `loop 2` also runs a SECOND session straight after a first that
ran out of time (:15484, :15633): not copied. Its health estimate is the bar's
green/red split (`nm_HealthDetection`, :10864); at 99% that is a pixel or two of
a ~110 px bar and cannot see a session's dent, so the HP is read off the bar's
own text instead (`read_hp`). The sprinkler and the frozen-honey check have
no use here (the bees hit it without one) and are skipped.

THE PRICE (brain/value.q). A hit point is a honey at the kill (30,000,000 of
each), so S seconds there pay dps*S honey -- a lower bound: the amulet, Star
Jelly, Glue and the possible tickets are unpriced -- against gathering for S
plus the walk. Q is linear in S, so there is no best short session: when the
snail beats gathering every second there pays and Natro's 15 minutes every 30
go (SESSION_S, AGAIN_S); when it does not, no length pays, and only a short
re-measure (PROBE_S) a week later (PROBE_EVERY_S) watches for the hive's attack
catching up. At 83 HP/s against 3,747/s it does not, by 45x: the break-even is
~4,000 HP/s (3,747 x (900 + 51) / 900, a walk that always lands), a kill in
about two hours of fighting.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
from pathlib import Path

import cv2
import numpy as np

from ..brain import value as value_mod
from ..vision.beemenu import LANGUAGE, OCR_TIMEOUT_S, TESSERACT
from ..vision.nameplate import (BAR_HUE, BAR_MIN_SATURATION, BAR_MIN_VALUE, BRIDGE_PX,
                                LABEL_BELOW_HUD, MAX_ASPECT, MAX_H, MAX_W, MIN_ASPECT,
                                MIN_H, MIN_W, WHITE_MAX_SATURATION, WHITE_MIN_VALUE,
                                WORLD_BOTTOM, WORLD_LEFT, WORLD_RIGHT)
from ..brain import mobtable

SNAIL_HP = 30_000_000             # wiki infobox `hp`, and its `honey` is the same number
HONEY_PER_HP = 1.0                # so a hit point off it is a honey at the kill
COOLDOWN_S = mobtable.respawn("stump_snail")  # 96 h (Natro :15483 `floor(345600*...)`; wiki); mobs.yaml via brain/mobtable (K7)
SESSION_S = 900.0                 # Natro's default SnailTime, 15 min (:594)
AGAIN_S = 1_800.0                 # Natro: a session out of time, again in 30 min (:15599)
# A RE-MEASURE. Two minutes: at 83 HP/s that is ~10,000 HP against the text's
# 1 HP resolution (read_hp), so one probe gives the rate to a few percent and
# outlasts the first seconds' faster burst (2026-10-06: 100-160 HP/s over each
# arrival's 2-3 s); it costs those 120 s and the walk, ~0.64M honey at
# 3,747/s, once a week.
PROBE_S = 120.0
PROBE_EVERY_S = 7 * 86_400.0      # the hive's attack moves over weeks; the back-off's own ceiling
ABSENT_OPEN_S = 7_200.0           # no snail: Natro looks again in 2 hours (:15614)
LOST_RETRY_S = 7_200.0            # a lost try doubles this, as act/beetle
LOST_RETRY_MAX_S = 7 * 86_400.0
LOOKS, LOOK_EVERY_S = 20, 0.25    # the looks for it on arrival, as the other bosses
ARRIVAL_READS = 3                 # ...until this many reads: one misread cannot set the start
CHECK_EVERY_S = 5.0               # a look for a death, the amulet table and its HP
KEEP_EVERY_S = 60.0               # a check's frame kept once a minute (180 a session otherwise)
MIN_SPAN_S = 30.0                 # readings this far apart before a rate is believed
MIN_BEES = 10                     # wiki Stump_Field `bees = 10` (data/knowledge/world.yaml:83)
# THE WALK OUT, when the skills ledger has no median for natro_out_stump:
# MEASURED 47-51 s, the four walks of 2026-10-06 (attempt-676, 063623-063714 ...).
WALK_S = 51.0
TILT = 2                          # Natro's two RotUp (PgUp) before the fight, undone after

# NATRO'S STEP IN, after the looks (`nm_Walk(1, FwdKey)`, :15504).
START = ({"op": "walk", "keys": "w", "studs": 4.0},)


def defeated(feed_text: str) -> bool:
    """The feed's word that it is beaten, if the game prints one (unseen for
    the snail: the amulet table is Natro's sign, and the one relied on)."""
    said = "".join(str(feed_text or "").lower().split())
    return "defeated" in said and "snail" in said


# ---- its HP, off the bar's own text -----------------------------------------
# WHY NOT vision/nameplate.find. MEASURED on the twenty attempt-676 frames
# with its bar on screen: it found it in 2. The snail is far off in its cave
# on arrival, so its bar sits at y 82-113 -- above nameplate's WORLD_TOP
# (100) -- and "HP: 29,879,792" spans the bar the way a planter's name does
# (one read as a planter). Here: the same UI green below the HUD pills, the
# same bridge and shape limits, any fill over HP_BAR_MIN_FILL (MEASURED
# 0.74-0.99 with the text in it), and white text inside (nameplate's
# white): MEASURED 0.046-0.103 of the snail's twenty bars, 0-0.031 of the
# Stump Field's bright leaves that pass the rest.
HP_BAR_MIN_FILL = 0.6
HP_BAR_MIN_WHITE = 0.04
# The text: white with a dark outline on that green, read by tesseract as
# black on white (act/shoplook's grey reading read none). MEASURED on the
# twenty bars, 108 combinations of scale, interpolation, value, saturation
# and a dilation tried: the best read 15 exactly, 3 malformed (refused by
# HP_TEXT) and 2 WRONG -- a 7 read as a 1, 600 and 60,000 HP low (the next
# best had two 600,000 low). Read at scale 4 AND 3 and kept only when both
# agree: 12 exact, 0 wrong. A look that reads nothing costs a look. On 1,207
# other route frames (the rest of attempt-676, 600 from attempts 7xx/8xx) it
# read 5 numbers, each a real "HP:" of another field's mob (12-170); the
# Stump Field has none (wiki Stump_Field), so there any reading is the snail.
HP_SCALES, HP_TEXT_MIN_V, HP_TEXT_MAX_S, HP_DILATE, HP_PAD = (4, 3), 140, 110, 2, 20
HP_TEXT = re.compile(r"HP:?(\d{1,3}(?:,\d{3})*)")
HP_BOXES = 3                      # the whitest candidates read, at most


def hp_boxes(frame) -> list[tuple[int, int, int, int]]:
    """Every bar-shaped box of nameplate green with white text in it, below
    the HUD, the whitest first."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    hsv = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (BAR_HUE[0], BAR_MIN_SATURATION, BAR_MIN_VALUE),
                        (BAR_HUE[1], 255, 255))
    green[:LABEL_BELOW_HUD] = 0
    green[WORLD_BOTTOM:] = 0
    green[:, :WORLD_LEFT] = 0
    green[:, WORLD_RIGHT:] = 0
    white = (hsv[:, :, 2] >= WHITE_MIN_VALUE) & (hsv[:, :, 1] <= WHITE_MAX_SATURATION)
    closed = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((1, BRIDGE_PX), np.uint8))
    count, _labels, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    found = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i][:5])
        if not (MIN_H <= h <= MAX_H and MIN_W <= w <= MAX_W and MIN_ASPECT <= w / h <= MAX_ASPECT
                and area >= HP_BAR_MIN_FILL * w * h):
            continue
        text = float(white[y:y + h, x:x + w].mean())
        if text >= HP_BAR_MIN_WHITE:
            found.append((text, (x, y, w, h)))
    return [box for _, box in sorted(found, reverse=True)]


def hp_text(crop, scale: int = HP_SCALES[0], run=subprocess.run) -> str:
    """One bar's text by tesseract at `scale`, its white as black on white."""
    big = cv2.resize(crop[:, :, :3], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
    ink = ((hsv[:, :, 2] >= HP_TEXT_MIN_V) & (hsv[:, :, 1] <= HP_TEXT_MAX_S)).astype(np.uint8)
    ink = cv2.dilate(ink, np.ones((HP_DILATE, HP_DILATE), np.uint8))
    page = cv2.copyMakeBorder(np.where(ink > 0, 0, 255).astype(np.uint8), HP_PAD, HP_PAD,
                              HP_PAD, HP_PAD, cv2.BORDER_CONSTANT, value=255)
    ok, png = cv2.imencode(".png", page)
    if not ok:
        return ""
    try:
        out = run([TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "7",
                   "-c", "tessedit_char_whitelist=HP:0123456789,"],
                  input=png.tobytes(), capture_output=True, timeout=OCR_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    raw = out.stdout
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)


def parse_hp(text: str) -> int | None:
    """"HP: 29,879,792" -> 29879792; None unless the whole text is "HP" and a
    number grouped by threes, no more than the snail's own HP."""
    m = HP_TEXT.fullmatch("".join(str(text or "").split()))
    if m is None:
        return None
    hp = int(m.group(1).replace(",", ""))
    return hp if hp <= SNAIL_HP else None


def read_hp(frame, run=subprocess.run, boxes=None) -> int | None:
    """The snail's HP off the first bar on screen that reads as one at every
    scale of HP_SCALES, or None. `boxes` (x, y, w, h) instead of hp_boxes':
    the Commando Chick's whole hurt bar (vision/nameplate.hurt_bars), its
    text in the dark red -- MEASURED 2026-10-13 on the 20 bars of
    var/commando/20261013-135246: 19 read, falling 13,434 -> 5,812 without
    a step up, the 3 checked by eye exact; 1 refused (9,035 vs 9,039 at the
    two scales); ~270 ms for both scales."""
    for x, y, w, h in (hp_boxes(frame) if boxes is None else list(boxes))[:HP_BOXES]:
        crop = frame[y:y + h, x:x + w]
        reads = {parse_hp(hp_text(crop, scale, run)) for scale in HP_SCALES}
        if len(reads) == 1 and None not in reads:
            return reads.pop()
    return None


def dps(readings) -> float | None:
    """HP a second off it over ONE session's (time, hp) readings: the median
    slope of every pair at least MIN_SPAN_S apart (Theil-Sen), so a misread
    moves one reading and not the rate. None without such a pair; never
    below 0."""
    pts = sorted(readings)
    slopes = [(h0 - h1) / (t1 - t0) for i, (t0, h0) in enumerate(pts)
              for t1, h1 in pts[i + 1:] if t1 - t0 >= MIN_SPAN_S]
    return max(0.0, float(statistics.median(slopes))) if slopes else None


def hp_left(readings) -> int | None:
    """The HP at the last looks: the median of the last three readings."""
    last = [hp for _, hp in sorted(readings)[-3:]]
    return int(statistics.median(last)) if last else None


# ---- the price ----------------------------------------------------------------
def session_q(rate: float | None, seconds: float, rho: float | None, p: float | None = None,
              walk_s: float = WALK_S, fail_s: float | None = None) -> float | None:
    """brain/value.q for `seconds` at the snail: rate*seconds honey (paid at
    the kill) against gathering at `rho` for those seconds and the walk; p the
    walk's landing odds (0.5 with no verdict, as value.score). None while
    either rate is unmeasured."""
    if rate is None or rho is None:
        return None
    return value_mod.q(rate * seconds * HONEY_PER_HP, 0.5 if p is None else p,
                       seconds + walk_s, rho, fail_s)


def session_seconds(state: dict, rho: float | None, p: float | None = None,
                    walk_s: float = WALK_S, fail_s: float | None = None) -> float:
    """SESSION_S when a full session pays at the rate last measured; else
    PROBE_S -- no rate measured yet, or gathering pays more."""
    q = session_q(state.get("dps"), SESSION_S, rho, p, walk_s, fail_s)
    return SESSION_S if q is not None and q > 0 else PROBE_S


# ---- when -------------------------------------------------------------------
def load(path: Path) -> dict:
    try:
        body = json.loads(Path(path).read_text())
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, path)


def record(state: dict, result: str, now: float, rate: float | None = None,
           hp: int | None = None, q: float | None = None) -> dict:
    """The state after a try: "killed", "absent", "fought" (it ran its time;
    `q` is a full session's worth at the rate now known), or a loss ("died",
    "walk", "unread": it ran and no rate was ever read). A rate or an HP read
    is kept whatever the result."""
    out = dict(state)
    row = {"at": now, "result": result}
    if rate is not None:
        out["dps"] = row["dps"] = round(float(rate), 1)
    if hp is not None:
        out["hp"] = row["hp"] = int(hp)
    out["tries"] = (list(state.get("tries") or []) + [row])[-20:]
    if result == "killed":
        out["killed_at"] = now
        out["hp"] = SNAIL_HP              # it comes back whole
        out["next_at"] = now + COOLDOWN_S
    elif result == "absent":
        out["absent_at"] = now
        out["next_at"] = now + ABSENT_OPEN_S
    elif result == "fought":
        out["next_at"] = now + (AGAIN_S if q is not None and q > 0 else PROBE_EVERY_S)
    else:
        # each loss in a row doubles the wait (a death or a walk that keeps
        # failing must not cost one every few hours), a week at most
        lost = 0
        for t in reversed(out["tries"]):
            if t.get("result") in ("killed", "absent", "fought"):
                break
            lost += 1
        out["next_at"] = now + min(LOST_RETRY_S * 2 ** (lost - 1), LOST_RETRY_MAX_S)
    return out


def due(state: dict, now: float) -> bool:
    return now >= float(state.get("next_at", 0.0) or 0.0)


if __name__ == "__main__":
    # ponytail: the smallest check that fails if the pure logic breaks.
    now = 1_000_000.0
    assert parse_hp("HP:29,879,792\n") == 29_879_792
    assert parse_hp("HP: 512") == 512
    assert parse_hp("HP:29,14,018") is None and parse_hp("P:29,724,036") is None
    assert parse_hp("HP:31,000,000") is None
    # 2026-10-06's arrivals, 83 HP/s between them
    assert round(dps([(0.0, 29_879_792), (1_169.0, 29_774_018)])) == 90
    assert dps([(0.0, 29_879_792), (3.0, 29_879_488)]) is None
    q = session_q(83.0, SESSION_S, 3_747.0, p=0.9)
    assert q < 0 and session_seconds({"dps": 83.0}, 3_747.0, 0.9) == PROBE_S
    assert session_seconds({"dps": 5_000.0}, 3_747.0, 0.9) == SESSION_S
    assert session_seconds({}, 3_747.0) == PROBE_S
    s = record({}, "fought", now, rate=83.0, hp=29_000_000, q=q)
    assert s["next_at"] == now + PROBE_EVERY_S and s["dps"] == 83.0
    assert record(s, "fought", now, q=1.0)["next_at"] == now + AGAIN_S
    lost = record(record(s, "died", now), "walk", now)
    assert lost["next_at"] == now + 2 * LOST_RETRY_S
    killed = record(lost, "killed", now)
    assert killed["next_at"] == now + COOLDOWN_S and killed["hp"] == SNAIL_HP
    assert not due(killed, now + 10) and due(killed, now + COOLDOWN_S)
    assert defeated("Defeated Stump Snail!") and not defeated("Defeated Rhino Beetle!")
    print("stumpsnail: ok")

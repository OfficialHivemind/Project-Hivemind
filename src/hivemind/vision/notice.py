"""Everything the bot can point at in a frame, in one call.

THE OWNER ASKED TO SEE IT THINKING: the AI highlighting what it notices. The
GUI's live view has always been able
to draw boxes -- its whole docstring is about the overlay being the point --
and nothing ever sent it any, so it has only ever shown a picture.

This collects what the bot genuinely detects, in the shape the panel draws:
`{"kind", "x", "y", "w", "h", "label"}` with kind in token / mob / target /
landmark.

THE RULE HERE IS THE SAME AS EVERYWHERE ELSE: nothing is drawn that is not
really detected. It would be easy to scatter plausible boxes over a frame and
it would look impressive in a screenshot, which is exactly why this only
reports detectors that have been measured against real frames:

    the notification panel   vision/banner.find    12/12 on real frames
    the HUD pills            fixed regions         read every run
    honeycomb-coloured mass  a yellow HSV band     10-50x field separation

That last one is deliberately NOT called "the hive". It measures a colour, and
that colour is also on ramps, gliders and other players' hives -- the owner
spotted the overlay claiming all three. Only the "Make Honey" panel has ever
identified OUR hive, and it is reported separately.

MOBS AND TOKENS USED TO BE DELIBERATELY ABSENT, because neither had a
detector. Both now do, both were measured against real frames, and this file
was simply never updated -- so the live view kept showing a picture with three
HUD rectangles on it while the bot was chasing tokens it could see perfectly
well. The owner caught it: no tokens were highlighted on the AI's view (perhaps
because it was not in a field).

    tokens   vision/tokens.detect     the coin detector, data/models/coins.json
    mobs     vision/nameplate.find    0 false positives on every real frame

A token at or above the chase threshold is a "token" (the live view rings
it); one the detector reported below it is a "maybe" (a faint dot) -- the
near-misses stay visible, which is the only way to see why a chase did or did
not start, without a paragraph of text on each. The threshold is the one the
chaser acts on: `chase_at`, the owner's gather.chase_confidence when the
caller passes it, else `tokens.CHASE_CONFIDENCE`.

The box is the COIN's square, which the coin detector measures.
"""
from __future__ import annotations

import numpy as np

import cv2

from . import banner, nameplate, tokens
from .screenstate import HONEY_REGION, POLLEN_REGION, hud_region

# The hive is only worth pointing at when it really is in view. MEASURED: a
# frame in the Pine Tree field carries 8,837-11,840 yellow pixels while one at
# the hive carries 88,331-522,511. 40,000 sits in the empty middle.
HIVE_YELLOW_VISIBLE = 40_000


# The hive row's honeycomb walls. This lives in `vision` because it is a
# colour measurement, and because `vision` may not import `act` -- the
# layering test caught exactly that when it was defined the other way round.
#
# MEASURED 2026-09-22 20:00-20:15 across 26 homing frames (var/homing), the
# hive fixtures (tests/fixtures/screens/hive) and 250 field frames from
# var/incidents, in HSV (OpenCV ranges, H 0-179):
#
#     the honeycomb, shaded side (run 237, wedged against Hive 1)  H 23-24  S 203-209  V 151-179
#     the honeycomb at the horizon from a field (run 240)          H 24     S 185-252  V 150-195
#     the honeycomb lit, standing on our own pad (fixture)         H 24-26  S 181-244  V 159-255
#     a honey token filling the view (run 240, look 14)            H 24     S 184-233  V 151-254
#     the Pineapple Patch's pineapple and the sky behind it        H 20-23  S 254-255  V 254-255
#     sunflowers, dandelions                                       H 21-26  S 190-235  V 225-255
#
# The old band (H 20-34, S 120+, V 150+) counted the pineapple as 74,000-
# 82,000 hive pixels from the Pineapple Patch and a honey token as 268,855
# -- the loop stepped toward the token. S <= 240 removes the pineapple and
# the sky (both fully saturated) and keeps 97% of the lit honeycomb; H 21-30
# removes the orange end. Brightness is NOT in the band: the same wall reads
# V 151-179 in shadow and V 254 lit, so a V cap would lose the hive from its
# own pad. Tokens and flowers share the hive's colour and are told apart by
# SHAPE instead -- see act/hive.hive_bearing, which counts only the yellow
# that reaches the top of the world: the hive is the one yellow thing tall
# enough to.
HIVE_YELLOW = ((21, 150, 145), (30, 240, 255))


def _hive_box(frame: np.ndarray) -> dict | None:
    """Bounding box of the hive's honeycomb yellow, when enough is on screen."""
    hsv = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2HSV)
    lo, hi = HIVE_YELLOW
    mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
    mask[:170, :] = 0
    mask[900:, :] = 0
    count = int(mask.sum() // 255)
    if count < HIVE_YELLOW_VISIBLE:
        return None
    # The LARGEST BLOB, not the extent of every yellow pixel. The hive row is
    # walled in honeycomb on both sides, so min/max over all of it returns a
    # box the size of the screen -- which points at nothing and is exactly the
    # sort of impressive-looking, useless overlay this module is supposed to
    # avoid.
    count_blobs, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count_blobs < 2:
        return None
    biggest = max(stats[1:count_blobs], key=lambda r: r[4])
    x, y, w, h, area = (int(v) for v in biggest[:5])
    if area < HIVE_YELLOW_VISIBLE // 4:
        return None
    # LABELLED FOR WHAT IT MEASURES, WHICH IS NOT "the hive".
    #
    # The owner watched the overlay and called this exactly right: yellow
    # ramps, unclaimed hives and gliders' yellow parts were all taken for our
    # hive. All true. This finds HONEYCOMB-COLOURED
    # PIXELS, and in Bee Swarm that colour is also on ramps, on gliders, and
    # on every other player's hive including unclaimed ones.
    #
    # It is still worth drawing -- it is a real measurement and it is what the
    # walk-home steering uses -- but calling it "hive" claims an identification
    # nothing here performed. The only thing that has ever identified OUR hive
    # is the panel reading "Make Honey", which is a separate detector and is
    # drawn separately.
    return {"kind": "landmark", "x": x, "y": y, "w": w, "h": h,
            "label": f"honeycomb yellow ({count // 1000}k px) — not "
                     f"necessarily our hive"}


def notice(frame: np.ndarray, readings: dict | None = None, *,
           world: bool = True, ignore=None, sightings=None,
           bars: bool = True, chase_at: float | None = None) -> list[dict]:
    """What is on screen, as boxes the live view can draw.

    `readings` is optional and only decorates the labels -- pass
    {"pollen": "283,681/688,050", "honey": "16,329,246"} to have the HUD boxes
    say what was read out of them, which is how a viewer can tell a correct
    reading from a plausible one.

    `world=False` skips the two expensive world detectors. MEASURED on a real
    frame: the whole call is 30.3 ms, of which tokens are 10.4 and health bars
    15.4. The live view's budget at the configured 20 fps is 50 ms a frame and
    it shares its captures with the bot's own vision -- a fourth concurrent
    screencopy client has killed the game twice (DESIGN 8a) -- so 26 ms of
    detection is worth skipping on a screen that cannot contain either thing.
    The app home, the loading splash and a modal are all such screens.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    found: list[dict] = []
    readings = readings or {}

    panel = banner.find(frame)
    if panel is not None:
        # NOT called "prompt" until something has READ it. The owner watched
        # the overlay label a blue archway in the world as a prompt: "it
        # thought anything blue was prompt". `banner.find` locates a
        # blue-ish panel by shape and position, which is all it claims; the
        # words on it are what make it a prompt, and those come from the text
        # reader. Pass readings={"prompt": "<text>"} once it has been read.
        label = readings.get("prompt")
        found.append({"kind": "landmark", "x": panel.x, "y": panel.y,
                      "w": panel.w, "h": panel.h,
                      "label": f"prompt: {label}" if label
                               else "blue panel (text not read)"})

    for name, region in (("pollen", POLLEN_REGION), ("honey", HONEY_REGION)):
        x, y, w, h = hud_region(frame, region)
        label = f"{name}: {readings[name]}" if name in readings else name
        found.append({"kind": "landmark", "x": x, "y": y, "w": w, "h": h,
                      "label": label})

    hive = _hive_box(frame)
    if hive is not None:
        found.append(hive)

    if world:
        found += _token_boxes(frame, ignore=ignore, sightings=sightings,
                              chase_at=chase_at)
        if bars:
            found += _mob_boxes(frame)
    return found


def _token_boxes(frame: np.ndarray, ignore=None, sightings=None,
                 chase_at: float | None = None) -> list[dict]:
    """Every token sighting, including the ones too weak to chase.

    Kept separate from the chaser's threshold on purpose. A viewer needs to
    see the sighting the chaser declined as well as the one it took, because
    "it walked past a token" and "it never saw a token" look identical
    otherwise.
    """
    # `sightings` lets the caller hand in a detection it has already paid
    # for. The live-view loop runs the detector anyway, to teach
    # `vision.pinned`, and running it twice a frame is not free.
    if sightings is None:
        try:
            sightings = tokens.detect(frame)
        except Exception:
            return []
    # `ignore(x, y)` is `vision.pinned.Pinned.is_pinned`: a mark that does not
    # move while the view does is the player's own bee or the interface, and
    # drawing a token on the character's own head is worse than drawing
    # nothing.
    if callable(ignore):
        try:
            sightings = [s for s in sightings if not ignore(s.x, s.y)]
        except Exception:
            pass
    gate = tokens.CHASE_CONFIDENCE if chase_at is None else float(chase_at)
    out = []
    for hit in sightings:
        box = getattr(hit, "box", None)
        if box:
            left, top, width, height = box
        else:
            # No box recorded: point at the centre rather than invent an
            # extent. A zero-size box still draws a label and a marker.
            left, top, width, height = hit.x, hit.y, 0, 0
        chaseable = hit.confidence >= gate
        kind = getattr(hit, "kind", "") or "unknown"
        name = "token" if kind in ("", "unknown") else kind.replace("_", " ")
        # The percentage is the chase threshold's own scale: gather.chase_
        # confidence 70 is a ring at "70%".
        tag = f"{name} {hit.confidence * 100:.0f}%"
        out.append({
            "kind": "token" if chaseable else "maybe",
            "x": left, "y": top, "w": width, "h": height,
            "tag": tag,
            "label": (f"{tag} — {hit.why}" if chaseable else
                      f"{tag}, below the chase's {gate * 100:.0f}% — {hit.why}")})
    return out


def _mob_boxes(frame: np.ndarray) -> list[dict]:
    """Health bars. Hostile ones as mobs; a Bloom's bar as what it is."""
    try:
        plates = nameplate.find_all(frame)
    except Exception:
        return []
    out = []
    for plate in plates:
        out.append({"kind": "mob" if plate.hostile else "landmark",
                    "x": plate.x, "y": plate.y, "w": plate.w, "h": plate.h,
                    "label": plate.describe()})
    return out

"""Where a box measured on a 1920x1080 frame is on THIS frame (ROADMAP RL3 stage 1).

Every box in the code is measured on the owner's 1920x1080 game. This is the
one place that turns such a box into the frame in hand, so a player whose
game is another size reads the same things. At 1920x1080 every function here
returns its input unchanged (tests/unit/test_screen.py).

THE GAME'S GUI DOES NOT STRETCH WITH THE WINDOW. MEASURED 2026-10-21 02:49
(var/incidents/20261021-024944-hud-missing: four 1280x720 in-world frames of
the Sober client, template-matched at 1:1 against 1920x1080 run-frames, scores
0.88-1.00): every piece is drawn at the same pixel size and keeps its distance
from the edge or middle it hangs from:

    Roblox button, menu, chat, buff and egg icons   top left      dx 0,    dy 0
    Honey and Pollen pills                          top middle    dx -320, dy 0
    hotbar slot 1                                   bottom middle dx -320, dy -360

(-320 = (1280 - 1920) / 2, -360 = 720 - 1080.) The old habit of stretching a
box by w/1920 put the Honey box at x 440 when the pill was at 340; that is why
the HUD reader saw no HUD at 1280x720 and the run stopped. So a box is moved
with its ANCHOR, not scaled.

ASSUMED, not measured yet (docs/pending/rl3-screens.md, stage 2): that the
other anchors behave the same; that UI_SCALE stays 1 on Windows at 100%
display scaling (above 100% Roblox may draw its GUI bigger, which is what
UI_SCALE is for); the "?" help button follows neither rule above (dx -615,
dy -23) and is not modelled. The 3D world is not GUI: it is not handled here.
"""
from __future__ import annotations

from functools import lru_cache

BASE_W, BASE_H = 1920, 1080

# What a box hangs from, as (x, y) shares of the frame. Only the three
# measured above; add one when a second size has shown where it sits.
TOP_LEFT = (0.0, 0.0)
TOP = (0.5, 0.0)
BOTTOM = (0.5, 1.0)

# The GUI's size against the 1920x1080 measurements. MEASURED 1.0 on Sober at
# 1920x1080 and 1280x720 (above). ponytail: one constant for every player;
# stage 2 measures it per player (the Honey pill is 294 px wide at 1.0).
UI_SCALE = 1.0

# MEASURED ANCHORS (the HUD item; RL3). The rule above says where each
# anchor's pieces should be; `measure`, once on the first in-world frame of a
# run, LOOKS for one piece per anchor near that spot and keeps how far off it
# is, so every box hung from that anchor follows the real GUI (a PC build, a
# client that draws its bar elsewhere).
# (template in data/templates/ui, its 1920x1080 top-left, the least score).
# Each template is the per-pixel median of 431 var/hotbar/*-stack1.jpg frames
# (10-10..10-26), its alpha the pixels whose 90th-percentile spread over them
# stayed <= 25-30 (the GUI, not the world behind it); the tile is its outline
# only (its inside shows the item). MEASURED 2026-10-27 on 611 other saved
# frames (stack and press frames, September route frames, the golden frames),
# searched +-SEARCH px: every in-world frame found all three at (0, 0) but
# the outline, 61 times 1 px off (flat grey places it to a pixel at best:
# SNAP). Least in-world scores (p1): button 0.996, Honey 0.974, outline 0.729;
# on the disconnect/join-error frames at most 0.40, 0.10 and 0.43.
ANCHOR_PIECES = {TOP_LEFT: ("anchor_roblox.png", (10, 8), 0.9),
                 TOP: ("anchor_honey.png", (662, 28), 0.9),
                 BOTTOM: ("anchor_hotbar.png", (697, 975), 0.6)}
SEARCH = 40
SNAP = 3            # a shift under this many px is noise (the outline's 1 px)
# LOOK-ONLY: measure() says what it would move; while False no box moves.
# Flip once a run's log shows (0, 0) at 1920x1080 and the right shift at
# another size (docs/pending/tplmask.md).
ANCHORS_LIVE = False
_shift: dict = {}


def _size(frame) -> tuple[int, int]:
    h, w = frame.shape[:2]
    return int(w), int(h)


def _rule(frame, x: float, y: float, anchor) -> tuple[int, int]:
    w, h = _size(frame)
    ax, ay = anchor
    return (int(round(ax * w + (x - ax * BASE_W) * UI_SCALE)),
            int(round(ay * h + (y - ay * BASE_H) * UI_SCALE)))


def point(frame, x: float, y: float, anchor=TOP_LEFT) -> tuple[int, int]:
    """A 1920x1080 point hanging from `anchor`, in `frame`'s pixels."""
    px, py = _rule(frame, x, y, anchor)
    dx, dy = _shift.get(anchor, (0, 0))
    return px + dx, py + dy


@lru_cache(maxsize=None)
def _piece(name: str):
    from ..datapaths import data
    from . import templates
    return templates.load(data("templates", "ui", name))


def offsets(frame) -> dict:
    """{anchor: (dx, dy) of its piece from where the rule puts it, or None
    when the piece is not seen}. Reads only."""
    from . import templates
    out = {}
    for anchor, (name, (x, y), least) in ANCHOR_PIECES.items():
        tpl = _piece(name)
        th, tw = tpl.shape[:2]
        ex, ey = _rule(frame, x, y, anchor)
        x0, y0 = max(ex - SEARCH, 0), max(ey - SEARCH, 0)
        hit = templates.find(frame, tpl, threshold=least,
                             region=(x0, y0, ex + tw + SEARCH - x0, ey + th + SEARCH - y0))
        if hit is None:
            out[anchor] = None
            continue
        dx, dy = hit.x - ex, hit.y - ey
        out[anchor] = (dx if abs(dx) >= SNAP else 0, dy if abs(dy) >= SNAP else 0)
    return out


def measure(frame) -> dict:
    """`offsets`, kept for every box when ANCHORS_LIVE (an unseen piece keeps
    the rule's place). Once, on the first in-world frame of a run."""
    found = offsets(frame)
    _shift.clear()
    if ANCHORS_LIVE:
        _shift.update({a: d for a, d in found.items() if d})
    return found


def region(frame, r, anchor=TOP_LEFT) -> tuple[int, int, int, int]:
    """An (x, y, w, h) region measured at 1920x1080, in `frame`'s pixels."""
    x, y, rw, rh = r
    fx, fy = point(frame, x, y, anchor)
    return fx, fy, int(round(rw * UI_SCALE)), int(round(rh * UI_SCALE))


def box(frame, b, anchor=TOP_LEFT) -> tuple[int, int, int, int]:
    """An (x0, y0, x1, y1) box measured at 1920x1080, in `frame`'s pixels."""
    x0, y0, x1, y1 = b
    return point(frame, x0, y0, anchor) + point(frame, x1, y1, anchor)


def to_base(frame, x: float, y: float) -> tuple[int, int]:
    """A position in `frame` as 1920x1080 coordinates, stretched: the
    pointer's space (act/join.to_input, MEASURED 2026-10-21 01:36: the pointer
    spans the whole output as 1920x1080 whatever size the frame is)."""
    w, h = _size(frame)
    return int(round(x * BASE_W / w)), int(round(y * BASE_H / h))
